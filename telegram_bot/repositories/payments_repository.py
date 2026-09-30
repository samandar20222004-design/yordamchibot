# -*- coding: utf-8 -*-
"""
=====================================================================
 💳 PAYMENTS — to'lov cheklari, holatlar, orderlar, kvitansiyalar
=====================================================================

To'lov holatlari va usullari, Telegram Stars payment orderlari, karta chek (payment_receipts) tasdiqlash/rad etish oqimi va to'lov sog'ligi hisobotlari.

Qatlam: REPOSITORY — domain ma'lumotlariga kirish.

Bu modul yadroga (``database``: pool / tranzaksiya / kesh / sxema)
``repositories.runtime`` orqali **kech bog'lanadi**: ``db_cursor``,
``transaction``, ``_cache_*`` va boshqa yadro yordamchilari chaqiruv
paytida ``database`` modulining joriy atributiga qarab yuradi. Shu
sabab ``unittest.mock.patch("database.db_cursor")`` kabi mavjud mock
nuqtalari bu modulga ko'chirilgandan keyin ham kuchini yo'qotmaydi.
"""

import logging

from database import (  # noqa: F401
    PAYMENT_STATUS_FAILED, PAYMENT_STATUS_PENDING, PAYMENT_STATUS_REFUNDED
)
from repositories.runtime import (  # noqa: F401
    _cache_clear, _normalize_language_code, db_cursor
)

logger = logging.getLogger(__name__)


# ====================================================================
# 💳 PAYMENTS — to'lov cheklari, holatlar, orderlar, kvitansiyalar
# ====================================================================

# ============================================================
# 💳 TO'LOVLAR TARIXI (foydalanuvchi uchun)
# ============================================================

def get_user_payment_history(user_id: int, limit: int = 10) -> list:
    """Foydalanuvchi to'lovlari tarixi (yangidan eskiga, ``limit`` dona).

    Ikkita manba birlashtiriladi:
      * ``payments``          — Telegram Stars (XTR) to'lovlari;
      * ``payment_receipts``  — admin tasdiqlagan qo'lda (karta) to'lovlar.

    Har bir yozuv: ``{"date": datetime|None, "amount": int, "currency": str,
    "method": "stars"|"card", "status": "succeeded"|"approved"|"pending"}``.
    Xatoda bo'sh ro'yxat qaytadi (ekranda «to'lov yo'q» ko'rinadi).
    """
    rows = []
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT created_at, amount, currency, payment_method, status "
                "FROM payments WHERE user_id = %s "
                "ORDER BY created_at DESC LIMIT %s",
                (user_id, int(limit)),
            )
            for created_at, amount, currency, method, status in cur.fetchall():
                rows.append({
                    "date": created_at,
                    "amount": int(amount or 0),
                    "currency": (currency or "XTR").upper(),
                    "method": "card" if str(method or "").lower() in (
                        "uzcard_humo", "card",
                    ) else "stars",
                    "status": str(status or "succeeded"),
                })
            cur.execute(
                "SELECT reviewed_at, created_at, amount_uzs, status "
                "FROM payment_receipts "
                "WHERE user_id = %s AND status IN ('approved', 'pending') "
                "ORDER BY COALESCE(reviewed_at, created_at) DESC LIMIT %s",
                (user_id, int(limit)),
            )
            for reviewed_at, created_at, amount_uzs, status in cur.fetchall():
                rows.append({
                    "date": reviewed_at or created_at,
                    "amount": int(amount_uzs or 0),
                    "currency": "UZS",
                    "method": "card",
                    "status": str(status or "pending"),
                })
    except Exception as e:
        logger.error(f"Payment history xatosi: {e}")
        return []

    # Ikkala manba sanalar bo'yicha birlashtirilib, yangisi yuqorida turadi.
    # Ehtiyot: sanalar naive (payments) yoki aware (receipts) bo'lishi mumkin —
    # to'g'ridan-to'g'ri taqqoslash o'rniga unix-timestamp'ga keltiramiz.
    def _sort_ts(row):
        date = row.get("date")
        if date is None:
            return 0.0
        try:
            return float(date.timestamp())
        except Exception:
            return 0.0

    rows.sort(key=_sort_ts, reverse=True)
    return rows[: int(limit)]


PAYMENT_STATUS_SUCCEEDED = "succeeded"


PAYMENT_STATUSES = (
    PAYMENT_STATUS_PENDING,
    PAYMENT_STATUS_SUCCEEDED,
    PAYMENT_STATUS_FAILED,
    PAYMENT_STATUS_REFUNDED,
)


#: 💳 To'lov usuli (payment_method) — HUDUDIY tanlov, tilga bog'liq emas:
#:   'uzcard_humo'         → 🇺🇿 Uzcard / Humo (so'm);
#:   'international_stars' → 🌍 Telegram Stars / Crypto (~$ ekvivalent).
#: Ledger audit tozaligi uchun FAQAT shu ikki qiymat qabul qilinadi
#: (noma'lum qiymat 'international_stars'ga normallashtiriladi —
#: PaymentService.normalize_payment_method bilan bir xil mantiq).
PAYMENT_METHOD_UZCARD_HUMO = "uzcard_humo"


PAYMENT_METHOD_INTERNATIONAL_STARS = "international_stars"


PAYMENT_METHODS = (PAYMENT_METHOD_UZCARD_HUMO, PAYMENT_METHOD_INTERNATIONAL_STARS)


def _normalize_payment_method(method) -> str:
    """payment_method qiymatini ruxsat etilgan to'plamga keltiradi."""
    raw = str(method or "").strip().lower()
    if raw in PAYMENT_METHODS:
        return raw
    return PAYMENT_METHOD_INTERNATIONAL_STARS


def log_stars_payment(user_id: int, amount: int, currency: str, payload: str, telegram_payment_id: str = "",
                      status: str = "succeeded", payment_method: str = None) -> bool:
    """To'lovni audit jadvaliga idempotent yozadi (Stars yoki karta).

    ``telegram_payment_charge_id`` NULL bo'lishi mumkin (legacy/manual
    chaqiriqlar uchun), ammo haqiqiy Telegram charge ID doimo unique.

    ``status`` — 5-bosqich audit holati (``pending | succeeded | failed |
    refunded``); ``payments_status`` CHECK'i shu to'plamni DB darajasida
    qat'iy ushlab turadi va ``idx_payments_user (user_id, status)`` indeksini
    ishlatib to'lov tarixini holat bo'yicha chizadi.

    ``payment_method`` — 💳 usul ajratgichi (``'international_stars'``
    default yoki ``'uzcard_humo'``); ledger'da valyuta bilan birga saqlanadi,
    shunda mahalliy (UZS) va xalqaro (XTR) oqimlar ARXIVDA ham adashmaydi.
    """
    if status not in PAYMENT_STATUSES:
        status = PAYMENT_STATUS_SUCCEEDED
    method = _normalize_payment_method(
        payment_method
        if payment_method is not None
        else (PAYMENT_METHOD_INTERNATIONAL_STARS if str(currency or "").upper() != "UZS"
              else PAYMENT_METHOD_UZCARD_HUMO)
    )
    try:
        charge_id = (telegram_payment_id or "").strip() or None
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO payments (user_id, amount, currency, payload,
                                      telegram_payment_charge_id, status,
                                      payment_method)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (user_id, amount, currency, payload, charge_id, status, method),
            )
            inserted = cur.rowcount > 0
        _cache_clear("system_stats")
        _cache_clear("admin_dashboard_stats")
        return inserted
    except Exception as e:
        logger.error(f"Stars payment log xatosi: {e}")
        return False


def process_stars_payment(
    user_id: int,
    amount: int,
    currency: str,
    payload: str,
    telegram_payment_id: str,
    plan: str = "pro",
    duration_days: int = 30,
) -> dict:
    """To'lovni audit qilish va obunani uzaytirishni bitta tranzaksiyada bajaradi.

    .. deprecated:: v2
        Servis orqali chaqirish tavsiya etiladi:
        ``PaymentService.process_stars_payment(user_id, charge_id, amount, payload, plan, duration_days)``
    """
    from services.payment_service import PaymentService
    return PaymentService.process_stars_payment(
        user_id, telegram_payment_id, amount, payload, plan, duration_days
    )


# ============================================================
# CARD PAYMENT RECEIPTS — Admin Approval Flow
# ============================================================
# Foydalanuvchi karta orqali to'lagach chek (rasm/PDF) yuboradi. U
# ``payment_receipts`` jadvaliga ``pending`` holatida yoziladi va barcha
# adminlarga yuboriladi. Admin ✅ Tasdiqlash bosganda status ``approved``
# bo'lib, PRO muddati ATOMIK uzaytiriladi (bitta tranzaksiyada). ❌ Rad etishda
# ``rejected`` deb belgilanadi.

RECEIPT_STATUS_PENDING = "pending"


def create_payment_order(
    user_id: int, plan: str, days: int, amount: int, currency: str = "UZS",
    ttl_hours: int = 48,
) -> str:
    """Karta to'lovi uchun buyurtma (order_id) yaratadi."""
    import uuid
    order_id = uuid.uuid4().hex
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO payment_orders
                    (order_id, user_id, plan, days, amount, currency, status, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending',
                        NOW() + (%s || ' hours')::INTERVAL)
                """,
                (order_id, int(user_id), str(plan), int(days), int(amount),
                 str(currency or "UZS"), str(int(ttl_hours))),
            )
        return order_id
    except Exception as e:
        logger.error("create_payment_order xatosi: %s", e)
        return ""


def get_payment_order(order_id: str):
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT order_id, user_id, plan, days, amount, currency, status, "
                "receipt_id FROM payment_orders WHERE order_id = %s",
                (str(order_id or ""),),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "order_id": row[0], "user_id": int(row[1]), "plan": row[2],
            "days": int(row[3]), "amount": int(row[4] or 0),
            "currency": row[5], "status": row[6], "receipt_id": row[7],
        }
    except Exception as e:
        logger.error("get_payment_order xatosi: %s", e)
        return None


def attach_receipt_to_order(order_id: str, receipt_id: int) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE payment_orders SET receipt_id = %s "
                "WHERE order_id = %s AND status = 'pending'",
                (int(receipt_id), str(order_id)),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("attach_receipt_to_order xatosi: %s", e)
        return False


def save_payment_receipt(
    user_id: int,
    media_type: str = "photo",
    file_id: str = "",
    caption: str = "",
    username: str = "",
    full_name: str = "",
    language_code: str = "uz",
    days_granted: int = 30,
    amount_uzs: int = 0,
) -> int:
    """Yangi karta chekini ``pending`` holatida saqlaydi.

    Returns: receipt id (xato: 0). ``media_type`` — 'photo' | 'document'.
    ``amount_uzs`` — so'mdagi to'lov summasi (CARD_TARIFFS); admin ✅
    bosganda payments ledger'iga USHBU summa 'UZS' valyutasi va
    'uzcard_humo' usuli bilan yoziladi.
    """
    if not file_id:
        return 0
    try:
        amount_uzs = max(0, int(amount_uzs or 0))
    except (TypeError, ValueError):
        amount_uzs = 0
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO payment_receipts
                    (user_id, username, full_name, language_code, media_type,
                     file_id, caption, status, days_granted, amount_uzs)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s)
                RETURNING id
                """,
                (int(user_id), username or "", full_name or "",
                 _normalize_language_code(language_code) or "uz",
                 media_type if media_type in ("photo", "document") else "photo",
                 file_id, caption or "", int(days_granted) if days_granted else 30,
                 amount_uzs),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0
    except Exception as e:
        logger.error(f"payment_receipt saqlash xatosi: {e}")
        return 0


def _payment_receipt_row_to_dict(row) -> dict:
    return {
        "id": int(row[0]),
        "user_id": int(row[1]),
        "username": row[2] or "",
        "full_name": row[3] or "",
        "language_code": row[4] or "uz",
        "media_type": row[5] or "photo",
        "file_id": row[6] or "",
        "caption": row[7] or "",
        "status": row[8] or "pending",
        "created_at": row[9],
        "reviewed_at": row[10],
        "decided_by": row[11],
        "days_granted": int(row[12]) if row[12] else 30,
    }


def get_payment_receipt(receipt_id: int):
    """Bitta chekni id bo'yicha qaytaradi (topilmasa None)."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT id, user_id, username, full_name, language_code, "
                "media_type, file_id, caption, status, created_at, reviewed_at, "
                "decided_by, days_granted "
                "FROM payment_receipts WHERE id = %s",
                (int(receipt_id),),
            )
            row = cur.fetchone()
        return _payment_receipt_row_to_dict(row) if row else None
    except Exception as e:
        logger.error(f"payment_receipt olish xatosi: {e}")
        return None


def list_payment_receipts(status: str = "pending", limit: int = 20) -> list:
    """Berilgan holatdagi cheklarni (yangi birinchi) qaytaradi."""
    try:
        limit = max(1, min(int(limit), 100))
        with db_cursor() as cur:
            cur.execute(
                "SELECT id, user_id, username, full_name, language_code, "
                "media_type, file_id, caption, status, created_at, reviewed_at, "
                "decided_by, days_granted "
                "FROM payment_receipts WHERE status = %s "
                "ORDER BY id DESC LIMIT %s",
                (status, limit),
            )
            return [_payment_receipt_row_to_dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"payment_receiptlar ro'yxati xatosi: {e}")
        return []


def list_pending_payment_receipts(limit: int = 20) -> list:
    """Kutayotgan (tasdiqlanmagan) cheklar."""
    return list_payment_receipts(RECEIPT_STATUS_PENDING, limit)


def approve_payment_receipt(receipt_id: int, admin_id: int, days: int = None) -> dict:
    """Chekni tasdiqlaydi va PRO muddatini ATOMIK uzaytiradi.

    .. deprecated:: v2
        Servis orqali chaqirish tavsiya etiladi:
        ``PaymentService.process_receipt(receipt_id, admin_id, approved=True)``
    """
    from services.payment_service import PaymentService
    return PaymentService.process_receipt(receipt_id, admin_id, True)


def reject_payment_receipt(receipt_id: int, admin_id: int) -> dict:
    """Chekni rad etadi (faqat hali ko'rib chiqilmagan bo'lsa).

    .. deprecated:: v2
        Servis orqali chaqirish tavsiya etiladi:
        ``PaymentService.process_receipt(receipt_id, admin_id, approved=False)``
    """
    from services.payment_service import PaymentService
    return PaymentService.process_receipt(receipt_id, admin_id, False)


def get_payments_health_counts() -> dict:
    """Health panel uchun to'lov ko'rsatkichlari (11-bosqich).

    Qaytadi: ``pending_receipts`` (ko'rib chiqilmagan cheklar),
    ``approved_24h`` (so'nggi 24 soatda tasdiqlangan cheklar),
    ``stars_24h`` (so'nggi 24 soatdagi Stars to'lovlari), ``error``.
    DB xatosida crash yo'q — ``error`` to'ldiriladi.
    """
    counts = {"pending_receipts": 0, "approved_24h": 0, "stars_24h": 0, "error": None}
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM payment_receipts WHERE status = 'pending'"
            )
            row = cur.fetchone()
            counts["pending_receipts"] = int(row[0]) if row else 0
            try:
                cur.execute(
                    "SELECT COUNT(*) FROM payment_receipts "
                    "WHERE status = 'approved' "
                    "AND reviewed_at >= NOW() - INTERVAL '24 hours'"
                )
                row = cur.fetchone()
                counts["approved_24h"] = int(row[0]) if row else 0
            except Exception:
                counts["approved_24h"] = 0
            try:
                cur.execute(
                    "SELECT COUNT(*) FROM payments "
                    "WHERE currency = 'XTR' "
                    "AND created_at >= NOW() - INTERVAL '24 hours'"
                )
                row = cur.fetchone()
                counts["stars_24h"] = int(row[0]) if row else 0
            except Exception:
                counts["stars_24h"] = 0
    except Exception as e:
        logger.error(f"payments health counts xatosi: {e}")
        counts["error"] = f"{type(e).__name__}: {e}"[:200]
    return counts


def get_pending_receipts_count() -> int:
    """Admin panel ko'rsatkichi uchun kutayotgan cheklar soni."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM payment_receipts WHERE status = 'pending'"
            )
            return int(cur.fetchone()[0])
    except Exception as e:
        logger.error(f"pending receipts count xatosi: {e}")
        return 0