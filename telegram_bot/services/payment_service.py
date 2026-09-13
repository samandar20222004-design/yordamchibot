"""PaymentService — to'lov biznes mantiq.

Stars to'lovlari, karta cheklari va admin tasdiqlash.
DB CRUD qismlari ``database`` modulida qoladi.

💳 TO'LOV TURLARI (HUDUDGA BOG'LIQ — tilga EMAS):
  * ``payment_method='uzcard_humo'``          → 🇺🇿 mahalliy kartalar, ledger'da valyuta 'UZS' (so'm);
  * ``payment_method='international_stars'``  → 🌍 Telegram Stars/Crypto, ledger'da valyuta 'XTR' (Stars).
Ikki tur ham BIR ledger jadvalida (``payments``) saqlanadi, ammo
``payment_method`` + ``currency`` ustunlari orqali qat'iy AJRATILGAN.

Foydalanish::

    from services.payment_service import PaymentService
    result = PaymentService.process_stars_payment(user_id, charge_id, amount, payload)
    # yoki karta to'lovi uchun (admin chek tasdiqlaganda avtomatik):
    result = PaymentService.record_card_payment(user_id, receipt_id, amount_uzs)
"""

import logging
import re
from contextlib import contextmanager

from database import (
    db_cursor,
    PAYMENT_STATUS_SUCCEEDED,
    PAYMENT_METHOD_UZCARD_HUMO,
    PAYMENT_METHOD_INTERNATIONAL_STARS,
    PAYMENT_METHODS,
    _invalidate_user,
    _cache_clear,
    _normalize_language_code,
)
# 6-bosqich: admin harakatlari auditi (chek tasdiqlash/rad etish).
from services.audit_service import AuditService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 💳 TO'LOV USULI (payment_method) va VALYUTA — ledger'dagi ajratgichlar.
# Kanonik konstantalar ``database`` modulida (yagona manba) — bu yerda
# qayta eksport qilinadi. Qayd etish: tanlov HUDUDIY, tilga bog'liq emas —
# istalgan til foydalanuvchisi istalgan usuldan to'lay oladi.
# ---------------------------------------------------------------------------
__all__ = [
    "PaymentService",
    "PAYMENT_METHOD_UZCARD_HUMO",
    "PAYMENT_METHOD_INTERNATIONAL_STARS",
    "PAYMENT_METHODS",
    "normalize_payment_method",
    "currency_for_method",
    "RECEIPT_STATUS_PENDING",
    "RECEIPT_STATUS_APPROVED",
    "RECEIPT_STATUS_REJECTED",
    "transaction",
]

#: Har bir usulning ledger'dagi standart valyutasi (ISO 4217 / XTR=Stars).
PAYMENT_METHOD_CURRENCY = {
    PAYMENT_METHOD_UZCARD_HUMO: "UZS",
    PAYMENT_METHOD_INTERNATIONAL_STARS: "XTR",
}


def normalize_payment_method(method, default: str = PAYMENT_METHOD_INTERNATIONAL_STARS) -> str:
    """Qiymatni ruxsat etilgan payment_method'ga keltiradi.

    'UzCard_Humo' / 'UZCARD_HUMO ' → 'uzcard_humo'; noma'lum → ``default``.
    Ledger'ga HECH QACHON tasodifiy satr tushmaydi (audit tozaligi).
    """
    raw = str(method or "").strip().lower()
    if raw in PAYMENT_METHODS:
        return raw
    return default


def currency_for_method(method: str) -> str:
    """Usul bo'yicha standart valyuta: uzcard_humo → UZS, stars → XTR."""
    return PAYMENT_METHOD_CURRENCY.get(
        normalize_payment_method(method), "XTR"
    )


@contextmanager
def transaction(commit: bool = True):
    """To'lov oqimi uchun BITTA atomik tranzaksiya bloki (5-bosqich).

    Blok ichidagi barcha SQL'lar bitta DB ulanishidan o'tadi va faqat blok
    muvaffaqiyatli tugaganda COMMIT qilinadi — istisnoda to'liq ROLLBACK.
    Bu ``database.transaction()`` (``db_transaction``) bilan bir xil
    semantika: ikkalasi ham ``db_cursor`` primitivi ustida qurilgan, shuning
    uchun qavat testlarda bir xil nuqtadan mock qilinadi.
    """
    with db_cursor(commit=commit) as cur:
        yield cur

# Karta chek holatlari
RECEIPT_STATUS_PENDING = "pending"
RECEIPT_STATUS_APPROVED = "approved"
RECEIPT_STATUS_REJECTED = "rejected"


class PaymentService:
    """To'lovlarni boshqarish: Stars, karta chek, tasdiqlash."""

    # ──────────────────────────────────────────────────────────────
    # VALIDATE_PAYLOAD — Stars invoice payload tekshiruvi
    # ──────────────────────────────────────────────────────────────
    _STARS_PAYLOAD_RE = re.compile(r"^sub_(stars_1m|stars_3m|stars_1y)_([0-9]+)$")

    # Standart tariflar
    STARS_PLANS = {
        "stars_1m": {"stars": 75, "days": 30},
        "stars_3m": {"stars": 175, "days": 90},
        "stars_1y": {"stars": 550, "days": 365},
    }

    @staticmethod
    def validate_payload(
        payload_data: str,
        user_id: int = None,
        amount: int = None,
        currency: str = None,
    ) -> tuple:
        """Invoice payload + summa + valuta'ni qat'iy tekshiradi.

        Returns: ``(plan_info, error_message)``
          - plan_info: ``{"plan_key": str, "stars": int, "days": int}`` yoki ``None``
          - error_message: ``str`` yoki ``None``
        """
        match = PaymentService._STARS_PAYLOAD_RE.fullmatch(str(payload_data or ""))
        if not match:
            return None, "Noto'g'ri to'lov payload'i."
        plan_key, payload_user = match.groups()

        if user_id is not None:
            try:
                if int(payload_user) != int(user_id):
                    return None, "To'lov foydalanuvchiga mos emas."
            except (TypeError, ValueError):
                return None, "Noto'g'ri foydalanuvchi ID."

        plan = PaymentService.STARS_PLANS.get(plan_key)
        if not plan:
            return None, "Noto'g'ri tarif."

        if currency is not None and str(currency).upper() != "XTR":
            return None, "To'lov valyutasi noto'g'ri."

        if amount is not None:
            try:
                if int(amount) != int(plan["stars"]):
                    return None, "To'lov summasi tarifga mos emas."
            except (TypeError, ValueError):
                return None, "To'lov summasi noto'g'ri."

        return {"plan_key": plan_key, "stars": plan["stars"], "days": plan["days"]}, None

    # ──────────────────────────────────────────────────────────────
    # PROCESS_STARS_PAYMENT — atomik to'lov + obuna berish
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def process_stars_payment(
        user_id: int,
        charge_id: str,
        amount: int,
        payload: str,
        plan: str = "pro",
        duration_days: int = 30,
        payment_method: str = None,
        currency: str = None,
    ) -> dict:
        """To'lovni qayta ishlaydi: audit + obuna berish (atomik).

        Bitta tranzaksiyada:
          1) payments jadvaliga yozadi (idempotent — charge_id UNIQUE),
          2) users obunasini uzaytiradi.

        ``payment_method`` — ledger'dagi usul ajratgichi:
          * ``'international_stars'`` (default) → 🌍 Telegram Stars, valyuta 'XTR';
          * ``'uzcard_humo'``                   → 🇺🇿 mahalliy karta, valyuta 'UZS'.
        ``currency`` berilmasa, usulga qarab avtomatik tanlanadi
        (``currency_for_method``) — ledger HECH QACHON noto'g'ri valyuta
        yozmaydi. Noma'lum usul qat'iy ``international_stars``'ga tushadi.

        Returns::

            {"ok": True, "duplicate": True/False, "days": int,
             "payment_method": str, "currency": str}
            yoki
            {"ok": False, "duplicate": False, "reason": str}
        """
        charge_id = (charge_id or "").strip()
        try:
            duration_days = int(duration_days)
        except (TypeError, ValueError):
            duration_days = 0

        if not charge_id or duration_days <= 0:
            return {"ok": False, "duplicate": False, "reason": "invalid_payment"}

        status = PAYMENT_STATUS_SUCCEEDED
        method = normalize_payment_method(payment_method)
        curcy = str(currency or "").strip().upper() or currency_for_method(method)

        try:
            # 5-bosqich: to'lov audit yozuvi + obuna uzaytirish — BITTA
            # atomik blokda (transaction). Xatoda ikkalasi birga qaytariladi,
            # ya'ni "pul olindi, lekin PRO berilmadi" holati mumkin emas.
            with transaction() as cur:
                # User mavjudligini tekshirib qulflash
                cur.execute("SELECT 1 FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
                if not cur.fetchone():
                    return {"ok": False, "duplicate": False, "reason": "user_not_found"}

                # Idempotent yozuv — usul (payment_method) va valyuta (currency)
                # bilan: 🇺🇿 Uzcard/Humo → UZS, 🌍 Stars → XTR.
                cur.execute(
                    """
                    INSERT INTO payments (user_id, amount, currency, payload,
                                          telegram_payment_charge_id, status,
                                          payment_method)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """,
                    (user_id, amount, curcy, payload, charge_id, status, method),
                )
                payment_row = cur.fetchone()
                if not payment_row:
                    return {"ok": True, "duplicate": True, "days": 0,
                            "payment_method": method, "currency": curcy}

                # Obuna uzaytirish: max(current_expiry, NOW()) + days
                cur.execute(
                    "UPDATE users SET plan_type = %s, "
                    "subscription_expires_at = GREATEST("
                    "COALESCE(subscription_expires_at, NOW()), NOW()) "
                    "+ (%s || ' days')::INTERVAL "
                    "WHERE user_id = %s",
                    (plan, str(int(duration_days)), user_id),
                )
                if cur.rowcount == 0:
                    return {"ok": False, "duplicate": False, "reason": "user_not_found"}

            _invalidate_user(user_id)
            _cache_clear("system_stats")
            _cache_clear("admin_dashboard_stats")
            return {"ok": True, "duplicate": False, "days": int(duration_days),
                    "payment_method": method, "currency": curcy}
        except Exception as e:
            logger.error("PaymentService.process_stars_payment xatosi: %s", e)
            return {"ok": False, "duplicate": False, "reason": "database_error"}

    # ------------------------------------------------------------------
    # RECORD_CARD_PAYMENT — 🇺🇿 mahalliy karta to'lovini ledger'ga yozish
    # ------------------------------------------------------------------
    @staticmethod
    def _receipt_charge_key(receipt_id: int) -> str:
        """Chek uchun ledger idempotency kaliti (charge_id o'rniga).

        ``payments.telegram_payment_charge_id`` UNIQUE — ``receipt:<id>``
        formatti tasdiqlangan chek bo'yicha LEDGER qatorini qayta-qayta
        yozishning oldini oladi (takroriy approve — duplicate).
        """
        return f"receipt:{int(receipt_id)}"

    @staticmethod
    def _insert_card_ledger_row(cur, user_id: int, receipt_id: int, amount_uzs: int) -> bool:
        """``payments`` ledger'iga UZS/uscard_humo qatorini SHU tranzaksiyada qo'shadi.

        Yangi qator → True, duplicate → False. Boshqa tranzaksiyani buzmaydi.
        """
        charge_key = PaymentService._receipt_charge_key(receipt_id)
        try:
            amount_uzs = max(0, int(amount_uzs or 0))
        except (TypeError, ValueError):
            amount_uzs = 0
        cur.execute(
            """
            INSERT INTO payments (user_id, amount, currency, payload,
                                  telegram_payment_charge_id, status,
                                  payment_method)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (int(user_id), amount_uzs, currency_for_method(PAYMENT_METHOD_UZCARD_HUMO),
             charge_key, charge_key, PAYMENT_STATUS_SUCCEEDED,
             PAYMENT_METHOD_UZCARD_HUMO),
        )
        try:
            return int(getattr(cur, "rowcount", 0) or 0) > 0
        except (TypeError, ValueError):
            return True

    @staticmethod
    def record_card_payment(
        user_id: int, receipt_id: int, amount_uzs: int = 0,
    ) -> dict:
        """Tasdiqlangan karta to'lovini ledger'ga alohida yozadi (idempotent).

        Odatda ``_approve_receipt`` ichidagi BIR tranzaksiyada chaqiriladi;
        bu metod qo'lda qayta hisob-kitob / migratsiya uchun mavjud.

        Returns::

            {"ok": True, "duplicate": True/False,
             "payment_method": "uzcard_humo", "currency": "UZS"}
        """
        try:
            receipt_id = int(receipt_id)
        except (TypeError, ValueError):
            return {"ok": False, "duplicate": False, "reason": "invalid_receipt"}
        if receipt_id <= 0:
            return {"ok": False, "duplicate": False, "reason": "invalid_receipt"}
        try:
            with transaction() as cur:
                inserted = PaymentService._insert_card_ledger_row(
                    cur, user_id, receipt_id, amount_uzs
                )
            return {"ok": True, "duplicate": not inserted,
                    "payment_method": PAYMENT_METHOD_UZCARD_HUMO,
                    "currency": "UZS"}
        except Exception as e:
            logger.error("PaymentService.record_card_payment xatosi: %s", e)
            return {"ok": False, "duplicate": False, "reason": "database_error"}

    # ──────────────────────────────────────────────────────────────
    # PROCESS_RECEIPT — karta chek tasdiqlash/rad etish
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def process_receipt(receipt_id: int, admin_id: int, approved: bool) -> dict:
        """Chekni tasdiqlaydi yoki rad etadi.

        approved=True:  status='approved' + PRO muddati uzaytiriladi.
        approved=False: status='rejected'.

        Returns::

            {"ok": True, "user_id": int, "days": int, "language_code": str}
            yoki
            {"ok": False, "reason": str}
        """
        if approved:
            return PaymentService._approve_receipt(receipt_id, admin_id)
        else:
            return PaymentService._reject_receipt(receipt_id, admin_id)

    @staticmethod
    def _approve_receipt(receipt_id: int, admin_id: int) -> dict:
        """Chekni tasdiqlaydi va PRO beradi (atomik).

        🇺🇿 Mahalliy karta to'lovi (Uzcard / Humo) tasdiqlanganda ledger'ga
        qator USHBU tranzaksiyada qo'shiladi: valyuta — UZS (so'm), usul —
        ``payment_method='uzcard_humo'`` (xalqaro 'international_stars' /
        'XTR' yozuvlaridan ALIQSA saqlanadi). Idempotency: ``receipt:<id>``
        charge kaliti UNIQUE — chek ikki marta tasdiqlansa ham ledger'da
        BIRTA qator turadi (eski mock-testlar 3 ustunli satr qaytarsa ham
        ishlaydi: amount_uzs ixtiyoriy o'qiladi).
        """
        try:
            # Chek tasdiqlash + PRO uzaytirish — bitta tranzaksiya (5-bosqich).
            with transaction() as cur:
                cur.execute(
                    "SELECT status, user_id, days_granted, amount_uzs "
                    "FROM payment_receipts WHERE id = %s FOR UPDATE",
                    (int(receipt_id),),
                )
                row = cur.fetchone()
                if not row:
                    return {"ok": False, "reason": "not_found"}
                status, user_id, default_days = row[0], row[1], row[2]
                amount_uzs = row[3] if len(row) > 3 else 0
                if status == RECEIPT_STATUS_APPROVED:
                    return {"ok": False, "reason": "already_approved"}

                grant_days = int(default_days or 30)
                if grant_days <= 0:
                    grant_days = 30

                # PRO berish: max(current_expiry, NOW()) + days
                cur.execute(
                    "UPDATE users SET plan_type = 'pro', "
                    "subscription_expires_at = GREATEST("
                    "   COALESCE(subscription_expires_at, NOW()), NOW())"
                    "   + (%s || ' days')::INTERVAL "
                    "WHERE user_id = %s",
                    (str(grant_days), int(user_id)),
                )
                cur.execute(
                    "UPDATE payment_receipts SET status = 'approved', "
                    "decided_by = %s, reviewed_at = NOW(), days_granted = %s "
                    "WHERE id = %s",
                    (int(admin_id), grant_days, int(receipt_id)),
                )
                # 6-bosqich: audit yozuvi SHU tranzaksiyada (atomik).
                AuditService.log_receipt_decision(
                    admin_id, receipt_id, approved=True,
                    user_id=user_id, days=grant_days,
                    old_status=status, cur=cur,
                )
                # 💳 Ledger: mahalliy karta to'lovi (UZS / 'uzcard_humo') —
                # PRO grant, audit va to'lov yozuvi BIR atomik blokda.
                PaymentService._insert_card_ledger_row(
                    cur, user_id, receipt_id, amount_uzs
                )
                # Foydalanuvchi tilini olish
                lang = "uz"
                cur.execute(
                    "SELECT language_code FROM users WHERE user_id = %s", (int(user_id),)
                )
                lrow = cur.fetchone()
                lang = _normalize_language_code(lrow[0] if lrow else "uz")

            _invalidate_user(int(user_id))
            _cache_clear("system_stats")
            _cache_clear("admin_dashboard_stats")
            return {
                "ok": True,
                "user_id": int(user_id),
                "days": grant_days,
                "language_code": lang,
            }
        except Exception as e:
            logger.error("PaymentService._approve_receipt xatosi: %s", e)
            return {"ok": False, "reason": "error"}

    @staticmethod
    def _reject_receipt(receipt_id: int, admin_id: int) -> dict:
        """Chekni rad etadi."""
        try:
            with transaction() as cur:
                cur.execute(
                    "SELECT status, user_id FROM payment_receipts WHERE id = %s FOR UPDATE",
                    (int(receipt_id),),
                )
                row = cur.fetchone()
                if not row:
                    return {"ok": False, "reason": "not_found"}
                status, user_id = row
                if status != RECEIPT_STATUS_PENDING:
                    return {"ok": False, "reason": "already_reviewed"}
                cur.execute(
                    "UPDATE payment_receipts SET status = 'rejected', "
                    "decided_by = %s, reviewed_at = NOW() WHERE id = %s",
                    (int(admin_id), int(receipt_id)),
                )
                # 6-bosqich: audit yozuvi SHU tranzaksiyada (atomik).
                AuditService.log_receipt_decision(
                    admin_id, receipt_id, approved=False,
                    user_id=user_id, old_status=status, cur=cur,
                )
            return {"ok": True, "user_id": int(user_id)}
        except Exception as e:
            logger.error("PaymentService._reject_receipt xatosi: %s", e)
            return {"ok": False, "reason": "error"}

    # ──────────────────────────────────────────────────────────────
    # GET_USER_PAYMENT_HISTORY — to'lov tarixi
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def get_user_payment_history(user_id: int, limit: int = 20) -> list:
        """Foydalanuvchi Stars to'lovlar tarixini qaytaradi.

        Returns: [{"id", "amount", "currency", "payload", "charge_id", "created_at"}, ...]
        """
        try:
            limit = max(1, min(int(limit), 100))
            with db_cursor() as cur:
                cur.execute(
                    "SELECT id, amount, currency, payload, "
                    "telegram_payment_charge_id, created_at "
                    "FROM payments WHERE user_id = %s "
                    "ORDER BY created_at DESC LIMIT %s",
                    (int(user_id), limit),
                )
                rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "amount": r[1],
                    "currency": r[2],
                    "payload": r[3],
                    "charge_id": r[4],
                    "created_at": r[5],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error("PaymentService.get_user_payment_history xatosi: %s", e)
            return []
