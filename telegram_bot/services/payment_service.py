"""PaymentService — to'lov biznes mantiq.

Stars to'lovlari, karta cheklari va admin tasdiqlash.
DB CRUD qismlari ``database`` modulida qoladi.

Foydalanish::

    from services.payment_service import PaymentService
    result = PaymentService.process_stars_payment(user_id, charge_id, amount, payload)
"""

import logging
import re
from contextlib import contextmanager

from database import (
    db_cursor,
    PAYMENT_STATUS_SUCCEEDED,
    _invalidate_user,
    _cache_clear,
    _normalize_language_code,
)

logger = logging.getLogger(__name__)


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
    ) -> dict:
        """Stars to'lovini qayta ishlaydi: audit + obuna berish (atomik).

        Bitta tranzaksiyada:
          1) payments jadvaliga yozadi (idempotent — charge_id UNIQUE),
          2) users obunasini uzaytiradi.

        Returns::

            {"ok": True, "duplicate": True/False, "days": int}
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

        try:
            # 5-bosqich: to'lov audit yozuvi + obuna uzaytirish — BITTA
            # atomik blokda (transaction). Xatoda ikkalasi birga qaytariladi,
            # ya'ni "pul olindi, lekin PRO berilmadi" holati mumkin emas.
            with transaction() as cur:
                # User mavjudligini tekshirib qulflash
                cur.execute("SELECT 1 FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
                if not cur.fetchone():
                    return {"ok": False, "duplicate": False, "reason": "user_not_found"}

                # Idempotent yozuv
                cur.execute(
                    """
                    INSERT INTO payments (user_id, amount, currency, payload,
                                          telegram_payment_charge_id, status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """,
                    (user_id, amount, "XTR", payload, charge_id, status),
                )
                payment_row = cur.fetchone()
                if not payment_row:
                    return {"ok": True, "duplicate": True, "days": 0}

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
            return {"ok": True, "duplicate": False, "days": int(duration_days)}
        except Exception as e:
            logger.error("PaymentService.process_stars_payment xatosi: %s", e)
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
        """Chekni tasdiqlaydi va PRO beradi (atomik)."""
        try:
            # Chek tasdiqlash + PRO uzaytirish — bitta tranzaksiya (5-bosqich).
            with transaction() as cur:
                cur.execute(
                    "SELECT status, user_id, days_granted FROM payment_receipts "
                    "WHERE id = %s FOR UPDATE",
                    (int(receipt_id),),
                )
                row = cur.fetchone()
                if not row:
                    return {"ok": False, "reason": "not_found"}
                status, user_id, default_days = row
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
