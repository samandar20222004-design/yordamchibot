"""ReferralService — PostAssist V2 (8-BOSQICH): referal anti-abuse tizimi.

Yangi foydalanuvchi referral havola bilan (``/start ref_123``) botga kirganda
quyidagi himoyalar qo'llanadi:

1. **Self-referral** — ``referrer_id == new_user_id``: o'z-o'zini taklif
   qilish darhol rad etiladi (referrer biriktirilmaydi, bonus yo'q).
2. **Takroriy referral** — foydalanuvchi oldin botga kirgan bo'lsa
   (``users`` jadvalida yozuvi bor, ``created_at`` eski) yoki unga
   allaqachon referrer biriktirilgan bo'lsa — bonus BERILMAYDI va referrer
   O'ZGARMAYDI. Bir foydalanuvchi butun umrida faqat BIR TAKLIF bilan
   hisoblanadi — faqat birinchisi.
3. **Noma'lum referrer** — referrer bazada mavjud bo'lmasa yozuv osmonda
   qolmasligi uchun biriktirilmaydi (bonus yo'q).

Bonus (mukofot) doim ``CreditsService`` orqali **atomik tranzaksiyada**
beriladi va ``credits_ledger`` jadvaliga audit qatori yoziladi — "bonus
berildi, lekin audit yo'q" holati imkonsiz.

Foydalanish::

    from services.referral_service import ReferralService

    result = ReferralService.register_new_user(
        user_id=42, username="ali", full_name="Ali", referrer_id=7,
    )
    # {"is_new": True, "referrer_id": 7, "reward": 3, "reason": "ok"}
    # yoki takroriy/self-referral'da:
    # {"is_new": False, "referrer_id": 7, "reward": 0, "reason": "existing_user"}
"""

import logging

import database as db
from services.credits_service import CreditsService

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Anti-abuse sabablari (natija dict'ining "reason" maydoni)
# ──────────────────────────────────────────────────────────────
REASON_OK = "ok"                          # referrer qabul qilindi, bonus berildi
REASON_NO_REFERRAL = "no_referral"        # ref_kod berilmagan (oddiy /start)
REASON_SELF_REFERRAL = "self_referral"    # o'z-o'zini taklif — rad etildi
REASON_EXISTING_USER = "existing_user"    # foydalanuvchi allaqachon botda (takroriy)
REASON_ALREADY_REREFERRED = "already_referred"  # referrer allaqachon biriktirilgan
REASON_UNKNOWN_REFERRER = "unknown_referrer"    # referrer bazada topilmadi


def parse_referral_code(raw) -> int | None:
    """/start argumentidan referral kodini ajratib oladi.

    ``"ref_123"`` → ``123``. Boshqa shakllar (``None``, ``"ref_abc"``,
    ``"ref_0"``, bo'sh satr) → ``None`` (referal ishtirok etmaydi).
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text.startswith("ref_"):
        return None
    digits = text[len("ref_"):]
    if not digits.isdigit():
        return None
    value = int(digits)
    return value if value > 0 else None


class ReferralService:
    """Referal ro'yxatdan o'tish: anti-abuse qoidalari + atomik bonus."""

    # ──────────────────────────────────────────────────────────────
    # ANTI-ABUSE TEKSHIRUV
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def validate_referral(cur, new_user_id, referrer_id):
        """Referral kodini tekshiradi va ``(yaroqli_id | None, sabab)`` qaytaradi.

        Qoidalar (tartibda):

        * ``referrer_id`` berilmagan/buzilgan → ``(None, REASON_NO_REFERRAL)``;
        * ``referrer_id == new_user_id`` → ``(None, REASON_SELF_REFERRAL)``
          (self-referral — darhol rad etiladi);
        * referrer bazada yo'q → ``(None, REASON_UNKNOWN_REFERRER)``;
        * aks holda → ``(int(referrer_id), REASON_OK)``.
        """
        try:
            ref = int(referrer_id) if referrer_id is not None else None
        except (TypeError, ValueError):
            ref = None
        if ref is None or ref <= 0:
            return None, REASON_NO_REFERRAL

        try:
            new_user_id = int(new_user_id)
        except (TypeError, ValueError):
            return None, REASON_NO_REFERRAL
        if ref == new_user_id:
            logger.warning(
                "Self-referral rad etildi: user=%s o'z havolasidan kirdi",
                new_user_id,
            )
            return None, REASON_SELF_REFERRAL

        # Referrer haqiqiy hisob bo'lishi shart — aks holda bonus kimga
        # yoziladi? (osmondagi referral yozuvi qolmasin).
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (ref,))
        if not cur.fetchone():
            logger.warning(
                "Noma'lum referrer: ref=%s (user=%s) biriktirilmadi",
                ref, new_user_id,
            )
            return None, REASON_UNKNOWN_REFERRER
        return ref, REASON_OK

    # ──────────────────────────────────────────────────────────────
    # BONUS (CreditsService orqali, atomik)
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def grant_bonus_in_tx(cur, referrer_id: int, new_user_id: int) -> int:
        """Referrer'ga taklif mukofotini BERADI — chaqiruvchi tranzaksiyasida.

        Formuladir ``database.referral_reward_for(n)``: 1-, 2-, 3-do'st
        uchun +3 tadan, 4-do'st va undan keyingi har biriga +1 (PRO
        berilmaydi). Hisob-kitob (COUNT) va yozish (UPDATE users + INSERT
        credits_ledger) BIR tranzaksiyada — parallel ``/start`` chaqiruvlari
        poyga (race) hosil qilmaydi.

        ``new_user_id`` — taklif qilingan do'stning ID'si (ledger'dagi
        ``reference_id`` sifatida saqlanadi). Berilgan mukofot (int) qaytadi.
        """
        cur.execute(
            "SELECT COUNT(*) FROM users WHERE referrer_id = %s", (referrer_id,)
        )
        referral_count = int((cur.fetchone() or (0,))[0] or 0)
        reward = db.referral_reward_for(referral_count)
        CreditsService.add_in_tx(
            cur, referrer_id, int(reward), CreditsService.OP_REFERRAL,
            ref_id=str(new_user_id),
        )
        return int(reward)

    # ──────────────────────────────────────────────────────────────
    # ASOSIY OQIM — /start (ref_kod bilan ham, bilmasdan ham)
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def register_new_user(user_id, username: str, full_name: str = "",
                          referrer_id=None, language_code: str = None) -> dict:
        """Foydalanuvchini ro'yxatdan o'tkazadi (yoki ma'lumotini yangilaydi).

        Butun oqim BITTA atomik tranzaksiyada: anti-abuse tekshiruvi +
        ``INSERT users`` + (yaroqli bo'lsa) ``CreditsService`` orqali bonus
        va ``credits_ledger`` audit yozuvi.

        Qaytadi::

            {"is_new": bool,            # True — yangi yozuv yaratildi
             "referrer_id": int | None, # yakundagi referrer (yoki None)
             "reward": int,             # berilgan bonus (takroriy'da 0)
             "reason": str}             # REASON_* sabab
        """
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return {"is_new": False, "referrer_id": None, "reward": 0,
                    "reason": REASON_NO_REFERRAL}

        try:
            with db.db_transaction() as cur:
                # --- Takroriy referral himoyasi (birinchi tekshiruv) --------
                cur.execute(
                    "SELECT user_id, referrer_id FROM users WHERE user_id = %s",
                    (user_id,),
                )
                existing = cur.fetchone()
                if existing:
                    # Foydalanuvchi allaqachon botda (created_at eski) —
                    # bonus BERILMAYDI va referrer O'ZGARMAYDI.
                    existing_ref = existing[1]
                    reason = (
                        REASON_ALREADY_REREFERRED
                        if existing_ref else REASON_EXISTING_USER
                    )
                    cur.execute(
                        "UPDATE users SET username = %s, full_name = %s "
                        "WHERE user_id = %s",
                        (username or "", full_name or "", user_id),
                    )
                    db._invalidate_user(user_id)
                    return {
                        "is_new": False,
                        "referrer_id": int(existing_ref) if existing_ref else None,
                        "reward": 0,
                        "reason": reason,
                    }

                # --- Anti-abuse: self-referral / noma'lum referrer ----------
                valid_ref, reason = ReferralService.validate_referral(
                    cur, user_id, referrer_id
                )

                # --- Yangi foydalanuvchi (boshlang'ich 5 ball bilan) ---------
                code = db._generate_user_code(cur)
                lang = db._normalize_language_code(language_code)
                cur.execute(
                    """
                    INSERT INTO users (user_id, username, full_name, user_code,
                                       referrer_id, ai_credits, streak_days,
                                       created_at, language_code)
                    VALUES (%s, %s, %s, %s, %s, 5, 0, NOW(), %s)
                    """,
                    (user_id, username or "", full_name or "", code,
                     valid_ref, lang),
                )

                # --- Bonus: CreditsService orqali (shu tranzaksiyada) -------
                reward = 0
                if valid_ref:
                    reward = ReferralService.grant_bonus_in_tx(
                        cur, valid_ref, user_id
                    )

                db._invalidate_user(user_id)
                if valid_ref:
                    db._invalidate_user(valid_ref)
                db._cache_clear("system_stats")
                return {
                    "is_new": True,
                    "referrer_id": valid_ref,
                    "reward": reward,
                    "reason": reason,
                }
        except Exception as e:
            # Tranzaksiya avtomatik ROLLBACK bo'ldi — yarim yozuv qolmaydi.
            logger.error("ReferralService.register_new_user xatosi (user=%s): %s",
                         user_id, e)
            return {"is_new": False, "referrer_id": None, "reward": 0,
                    "reason": REASON_NO_REFERRAL, "error": str(e)}
