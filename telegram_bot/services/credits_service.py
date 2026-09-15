"""CreditsService — PostAssist V2 (8-BOSQICH): AI-ballar auditi (credits ledger).

Har bir ball o'zgarishi — berilganda ham, yechilganda ham — ``credits_ledger``
jadvaliga doimiy audit qatori qo'shiladi:

* ``add_credits(user_id, amount, op_type, ref_id)`` — musbat miqdor
  (masalan ``+10``, ``op_type='promo'``);
* ``spend_credits(user_id, amount, op_type, ref_id)`` — manfiy miqdor
  (masalan ``-2``, ``op_type='ai_request'``); balans yetarli bo'lmasa
  ``InsufficientCreditsError`` ko'tariladi va **hech narsa yozilmaydi**;
* ``get_user_history(user_id, limit=20)`` — foydalanuvchining so'nggi
  audit yozuvlari (eng yangisi birinchi).

**Atomiklik.** Balans yangilashi (``UPDATE users SET ai_credits = ...``) va
ledger yozuvi (``INSERT INTO credits_ledger``) DOIM bitta tranzaksiyada
bajariladi. Tranzaksiyani chaqiruvchi ochgan bo'lsa (``cur`` berilgan) —
yozuv shu tranzaksiyada COMMIT/ROLLBACK bo'ladi; berilmagan bo'lsa servis
o'zi bitta tranzaksiya ochadi (va ich-ma-ich chaqiruvda SAVEPOINT qabul
qilinadi). Shunday qilib "balans o'zgardi, lekin audit yozuvi yo'q" (yoki
aksincha) holati imkonsiz.

``balance_after`` maydoni har bir qatorda ushbu yozuvdan KEYINGI balansni
saqlaydi — ledger tarixi bo'ylab to'liq hisob-kitobni (audit) qayta tiklash
imkonini beradi.

Foydalanish::

    from services.credits_service import CreditsService, InsufficientCreditsError

    CreditsService.add_credits(user_id, 10, "promo", ref_id="PROMO100")
    try:
        CreditsService.spend_credits(user_id, 2, "ai_request")
    except InsufficientCreditsError as e:
        ...  # e.required / e.available — aniq sonlar
"""

import logging

import database as db

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# operation_type qiymatlari (VARCHAR(32))
# ──────────────────────────────────────────────────────────────
OP_DAILY_BONUS = "daily_bonus"   # kunlik streak bonusi
OP_REFERRAL = "referral"         # do'st taklif qilgan mukofoti
OP_AI_REQUEST = "ai_request"     # AI so'rovi uchun ball (yechish va refund)
#: AI so'rovi muvaffaqiyatsiz tugaganda bron qaytarilganda (PHASE 2 / 1-qadam:
#: ``refund_ai_request``) — yechishdan (``ai_request``) alohida tur, shunda
#: ledger tarixida "yechildi / qaytarildi" juftligi aniq ko'rinadi.
OP_AI_REFUND = "ai_refund"
OP_PROMO = "promo"               # promo/aksiya berilgan ball
OP_ADMIN = "admin"               # admin tomonidan berilgan/olingan ball

#: Qo'shimcha tur — foydalanuvchilararo ball o'tkazish (har bir yo'nalish
#: alohida qator: yechilgan tomon manfiy, qabul qilgan tomon musbat).
OP_TRANSFER = "transfer"

#: Ruxsat etilgan ``operation_type`` to'plami (oq ro'yxat — ledger'ga
#: noma'lum tur yozib bo'lmaydi).
VALID_OPERATION_TYPES = (
    OP_DAILY_BONUS,
    OP_REFERRAL,
    OP_AI_REQUEST,
    OP_AI_REFUND,
    OP_PROMO,
    OP_ADMIN,
    OP_TRANSFER,
)

#: ``get_user_history`` limit chegaralari (1..100).
HISTORY_LIMIT_MIN = 1
HISTORY_LIMIT_MAX = 100


class InsufficientCreditsError(Exception):
    """Foydalanuvchida so'ralgan ball yetarli emas — yechish bloklandi.

    Shu istisno ko'tarilganda tranzaksiya ROLLBACK bo'ladi: balans va
    ``credits_ledger`` o'zgarmaydi (yarim yozuv qolmaydi).
    """

    def __init__(self, user_id, required, available):
        self.user_id = user_id
        self.required = int(required)
        self.available = int(available)
        super().__init__(
            f"Foydalanuvchi {user_id}: ball yetarli emas "
            f"(kerak {self.required}, mavjud {self.available})"
        )


class CreditsService:
    """AI-ball balans va ``credits_ledger`` auditi (atomik tranzaksiya)."""

    # Operation-type doimiylari klass atributi sifatida ham ochiq:
    # ``CreditsService.OP_AI_REQUEST`` yoki modul darajasidagi
    # ``OP_AI_REQUEST`` — ikkalasi bir xil qiymat.
    OP_DAILY_BONUS = OP_DAILY_BONUS
    OP_REFERRAL = OP_REFERRAL
    OP_AI_REQUEST = OP_AI_REQUEST
    OP_AI_REFUND = OP_AI_REFUND
    OP_PROMO = OP_PROMO
    OP_ADMIN = OP_ADMIN
    OP_TRANSFER = OP_TRANSFER

    # ──────────────────────────────────────────────────────────────
    # YAKUNIY API (chaqiruvchi tranzaksiyadan mustaqil)
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def add_credits(user_id, amount, op_type=OP_PROMO, ref_id=None, cur=None) -> dict:
        """Ball qo'shadi (musbat miqdor) va ledger'ga audit yozadi.

        ``cur`` berilmasa o'z tranzaksiyasi ochiladi; berilgan bo'lsa
        chaqiruvchining tranzaksiyasida (SAVEPOINT) bajariladi.

        Qaytadi::

            {"success": True, "user_id": int, "amount": int,
             "balance_after": int, "ledger_id": int}

        Foydalanuvchi topilmasa::

            {"success": False, "error": "user_not_found", "user_id": int}

        Noto'g'ri ``op_type`` yoki manfiy miqdor → ``ValueError``
        (chaqiruvchi xatosini yutmaydi).
        """
        amount = int(amount)
        if amount <= 0:
            raise ValueError("add_credits: miqdor musbat bo'lishi kerak")
        op = CreditsService._validate_op(op_type)
        if cur is None:
            with db.db_transaction() as own_cur:
                result = CreditsService._add_in_tx(
                    own_cur, user_id, amount, op, ref_id)
            if result.get("success"):
                CreditsService._invalidate(result["user_id"])
            return result
        return CreditsService._add_in_tx(cur, user_id, amount, op, ref_id)

    @staticmethod
    def spend_credits(user_id, amount, op_type=OP_AI_REQUEST, ref_id=None,
                      cur=None) -> dict:
        """Ball yechadi (manfiy miqdor) va ledger'ga audit yozadi.

        Balans yetarli bo'lmasa ``InsufficientCreditsError`` ko'tariladi —
        balans va ledger O'ZGARMAYDI. Foydalanuvchi umuman topilmasa
        ``{"success": False, "error": "user_not_found"}`` qaytadi.

        Qaytadi (muvaffaqiyatda)::

            {"success": True, "user_id": int, "amount": -int,
             "balance_after": int, "ledger_id": int}
        """
        amount = int(amount)
        if amount <= 0:
            raise ValueError("spend_credits: miqdor musbat bo'lishi kerak")
        op = CreditsService._validate_op(op_type)
        if cur is None:
            try:
                with db.db_transaction() as own_cur:
                    result = CreditsService._spend_in_tx(
                        own_cur, user_id, amount, op, ref_id)
            except InsufficientCreditsError:
                # Tranzaksiya avtomatik ROLLBACK bo'ldi — hech narsa yozilmadi.
                raise
            if result.get("success"):
                CreditsService._invalidate(result["user_id"])
            return result
        return CreditsService._spend_in_tx(cur, user_id, amount, op, ref_id)

    @staticmethod
    def get_user_history(user_id, limit: int = 20) -> list:
        """Foydalanuvchining so'nggi audit yozuvlari (eng yangisi birinchi).

        Har bir element::

            {"id": int, "user_id": int, "amount": int, "balance_after": int,
             "operation_type": str, "reference_id": str | None,
             "created_at": datetime}

        Xatoda (jadval yo'q, DB uzilgan) ``[]`` qaytadi — foydalanuvchi
        hech qachon tizim xatosi ko'rmaydi.
        """
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return []
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 20
        limit = max(HISTORY_LIMIT_MIN, min(HISTORY_LIMIT_MAX, limit))
        try:
            with db.db_transaction(commit=False) as cur:
                cur.execute(
                    "SELECT id, user_id, amount, balance_after, operation_type, "
                    "reference_id, created_at FROM credits_ledger "
                    "WHERE user_id = %s ORDER BY created_at DESC, id DESC "
                    "LIMIT %s",
                    (user_id, limit),
                )
                rows = cur.fetchall() or []
            return [
                {
                    "id": int(r[0]),
                    "user_id": int(r[1]),
                    "amount": int(r[2]),
                    "balance_after": int(r[3]),
                    "operation_type": r[4],
                    "reference_id": r[5],
                    "created_at": r[6],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error("credits_ledger o'qish xatosi (user=%s): %s", user_id, e)
            return []

    # ──────────────────────────────────────────────────────────────
    # TRANZAKSIYA ICHIDAGI YADRO (cur — chaqiruvchining kursori)
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def add_in_tx(cur, user_id, amount, op_type=OP_PROMO, ref_id=None) -> dict:
        """Tranzaksiya ichida ball qo'shish (yagona yadro, ``add_credits``
        ham shunga delegat qiladi). Kesh/bevosita commit YO'Q — tranzaksiya
        egasi (chaqiruvchi) javobgar."""
        return CreditsService._add_in_tx(
            cur, user_id, int(amount), CreditsService._validate_op(op_type), ref_id)

    @staticmethod
    def grant_in_tx(cur, user_id, amount, op_type=OP_PROMO, ref_id=None) -> dict:
        """Tranzaksiya ichida bonus/mukofot berish (kunlik streak, referal
        va h.k. oqimlari uchun atama alias) — ``add_in_tx`` bilan bir xil."""
        return CreditsService.add_in_tx(
            cur, user_id, amount, op_type=op_type, ref_id=ref_id)

    @staticmethod
    def spend_in_tx(cur, user_id, amount, op_type=OP_AI_REQUEST,
                    ref_id=None) -> dict:
        """Tranzaksiya ichida ball yechish (yagona yadro). Yetarli bo'lmasa
        ``InsufficientCreditsError`` — chaqiruvchi tranzaksiyani ROLLBACK
        qiladi (yoki SAVEPOINT'ga qaytaradi)."""
        return CreditsService._spend_in_tx(
            cur, user_id, int(amount), CreditsService._validate_op(op_type), ref_id)

    # ──────────────────────────────────────────────────────────────
    # Ichi-dan-ichi amallar (faqat cur bilan)
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def _add_in_tx(cur, user_id, amount, op, ref_id=None) -> dict:
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return {"success": False, "error": "bad_user"}
        cur.execute(
            "UPDATE users SET ai_credits = COALESCE(ai_credits, 0) + %s "
            "WHERE user_id = %s RETURNING ai_credits",
            (int(amount), user_id),
        )
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": "user_not_found", "user_id": user_id}
        balance_after = int(row[0] or 0)
        ledger_id = CreditsService._ledger_insert(
            cur, user_id, int(amount), balance_after, op, ref_id)
        return {
            "success": True,
            "user_id": user_id,
            "amount": int(amount),
            "balance_after": balance_after,
            "ledger_id": ledger_id,
        }

    @staticmethod
    def _spend_in_tx(cur, user_id, amount, op, ref_id=None) -> dict:
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return {"success": False, "error": "bad_user"}
        # Bitta atomik UPDATE: balans yetarli bo'lgan holdagina yechiladi.
        # Parallel yechishlarda ikki so'rov bir ballni "o'g'irlay olmaydi" —
        # har biri o'z qatorini qulf bilan oladi.
        cur.execute(
            "UPDATE users SET ai_credits = ai_credits - %s "
            "WHERE user_id = %s AND ai_credits >= %s RETURNING ai_credits",
            (int(amount), user_id, int(amount)),
        )
        row = cur.fetchone()
        if row:
            balance_after = int(row[0] or 0)
            ledger_id = CreditsService._ledger_insert(
                cur, user_id, -int(amount), balance_after, op, ref_id)
            return {
                "success": True,
                "user_id": user_id,
                "amount": -int(amount),
                "balance_after": balance_after,
                "ledger_id": ledger_id,
            }
        # Yechilmadi: foydalanuvchi yo'qmi yoki ball kammi — aniq sababni
        # aniqlaymiz (ledger'ga HECH QANDAY yozuv tushmaydi).
        cur.execute(
            "SELECT ai_credits FROM users WHERE user_id = %s", (user_id,)
        )
        user_row = cur.fetchone()
        if not user_row:
            return {"success": False, "error": "user_not_found", "user_id": user_id}
        available = int(user_row[0] or 0)
        raise InsufficientCreditsError(user_id, amount, available)

    @staticmethod
    def _ledger_insert(cur, user_id, amount, balance_after, op, ref_id=None) -> int:
        """Ledger'ga audit qatorini yozadi (chaqiruvchi tranzaksiyasida)."""
        cur.execute(
            "INSERT INTO credits_ledger "
            "(user_id, amount, balance_after, operation_type, reference_id) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (
                int(user_id),
                int(amount),
                int(balance_after),
                op,
                str(ref_id) if ref_id is not None else None,
            ),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _validate_op(op_type) -> str:
        op = str(op_type or "").strip()
        if op not in VALID_OPERATION_TYPES:
            raise ValueError(
                f"Noma'lum operation_type: {op_type!r} "
                f"(ruxsat etilgan: {', '.join(VALID_OPERATION_TYPES)})"
            )
        return op

    @staticmethod
    def _invalidate(user_id):
        """Kesh tozalash (faqat mustaqil tranzaksiya yakunida chaqiriladi)."""
        try:
            db._invalidate_user(int(user_id))
            db._cache_clear("system_stats")
        except Exception:
            pass
