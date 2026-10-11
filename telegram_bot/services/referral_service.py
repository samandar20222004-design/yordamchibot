"""ReferralService — PostAssist V2: referal anti-abuse + ACTION-BASED mukofot.

🌱 STEP 2 (ORGANIC GROWTH) refaktori: bonus endi /start paytida EMAS,
taklif qilingan foydalanuvchi BIRINCHI YAROQLI AMALINI (post yaratish /
rejalashtirish — ``database.add_post`` yoki ``schedule_week_posts``)
bajarganidan KEYIN beriladi. Shu bilan:

* "o'lik jonlar"ni ro'yxatdan o'tkazib ball yig'ish (farming) iqtisodiy
  ma'nosini yo'qotadi — mukofot faqat REAL qiymat (birinchi post) evaziga;
* takroriy claim imkonsiz: ``users.referral_rewarded_at`` belgisi atomik
  shartli UPDATE bilan qo'yiladi (bir do'st = faqat BIR mukofot).

Anti-abuse qoidalari (ro'yxatdan o'tishda, ``/start ref_123``):

1. **Self-referral** — ``referrer_id == new_user_id``: o'z-o'zini taklif
   qilish darhol rad etiladi (referrer biriktirilmaydi, bonus yo'q).
2. **Takroriy referral** — foydalanuvchi oldin botga kirgan bo'lsa
   (``users`` jadvalida yozuvi bor) yoki unga allaqachon referrer
   biriktirilgan bo'lsa — referrer O'ZGARMAYDI. Bir foydalanuvchi butun
   umrida faqat BIR TAKLIF bilan hisoblanadi — faqat birinchisi.
3. **Noma'lum referrer** — referrer bazada mavjud bo'lmasa biriktirilmaydi.
4. **Duplicate account farming** — bir xil referrer ostida bir xil
   ``signup_fingerprint`` (SHA-256(username|full_name)) bilan ikkinchi va
   undan keyingi hisoblar kopya/deb hisoblanadi: biriktirish saqlanadi
   (attribution), lekin mukofot DOIMLYK bloklanadi
   (``referral_block_reason='duplicate_profile'``). Telegram'da qurilma
   ID'si mavjud emas — profil barmog'i + action-gate + konversiya limiti
   birgalikda "fermer" hisoblarning iqtisodiy foydasini nolga tushiradi.

Mukofot (konversiya paytida) doim ``CreditsService`` orqali **atomik
tranzaksiyada** beriladi va ``credits_ledger`` jadvaliga audit qatori
yoziladi — "bonus berildi, lekin audit yo'q" holati imkonsiz. Tarif
hisobi (1-3 do'st +3, keyingilar +1) endi FAQAT KONVERSIYA QILGAN
(do'sti birinchi post yaratgan) takliflar bo'yicha yuritiladi.

Foydalanish::

    from services.referral_service import ReferralService

    result = ReferralService.register_new_user(
        user_id=42, username="ali", full_name="Ali", referrer_id=7,
    )
    # {"is_new": True, "referrer_id": 7, "reward": 0, "reason": "ok",
    #  "reward_status": "pending_first_action"}
    #
    # Do'st birinchi postini yaratgach (add_post hook'i chaqiradi):
    conv = ReferralService.register_first_action(42)
    # {"granted": True, "reward": 3, "referrer_id": 7, "reason": "ok"}
"""

import hashlib
import logging
import threading
from collections import deque

import database as db
from services.credits_service import CreditsService

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Anti-abuse sabablari (natija dict'ining "reason" maydoni)
# ──────────────────────────────────────────────────────────────
REASON_OK = "ok"                          # referrer qabul qilindi (biriktirildi)
REASON_NO_REFERRAL = "no_referral"        # ref_kod berilmagan (oddiy /start)
REASON_SELF_REFERRAL = "self_referral"    # o'z-o'zini taklif — rad etildi
REASON_EXISTING_USER = "existing_user"    # foydalanuvchi allaqachon botda (takroriy)
REASON_ALREADY_REREFERRED = "already_referred"  # referrer allaqachon biriktirilgan
REASON_UNKNOWN_REFERRER = "unknown_referrer"    # referrer bazada topilmadi

#: 🌱 STEP 2 — qo'shimcha anti-abuse sabablari (konversiya oqimi).
REASON_DUPLICATE_PROFILE = "duplicate_profile"  # kopya hisob (farming) — bloklandi
REASON_ALREADY_REWARDED = "already_rewarded"    # mukofot allaqachon berilgan (claim takrori)
REASON_USER_NOT_FOUND = "user_not_found"        # foydalanuvchi bazada yo'q
REASON_DB_ERROR = "db_error"                    # baza xatosi (fail-soft)
REASON_BAD_USER = "bad_user"                    # noto'g'ri user_id

#: ``register_new_user`` natijasidagi ``reward_status`` qiymatlari:
#: mukofot holati (STEP 2: bonus birinchi amaldan KEYIN beriladi).
REWARD_NONE = "none"                        # referrer yo'q — mukofot kutilmaydi
REWARD_PENDING = "pending_first_action"     # birinchi post kutilmoqda
REWARD_BLOCKED = "blocked"                  # anti-abuse: mukofot bloklanadi

#: ``users.referral_block_reason`` qiymatlari (audit uchun qisqa tokenlar).
BLOCK_DUPLICATE_PROFILE = "duplicate_profile"


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


def signup_fingerprint(username, full_name) -> str:
    """Ro'yxatdan o'tish profilining barqaror barmog'i (SHA-256, 64 belgi).

    ``username`` va ``full_name`` normallashtiriladi (lower, probellar
    siqiladi) — "Ali Karimov" va "ali  karimov" BIRTA barmoq beradi.
    Duplicate device/account farming detektori shu belgini bir xil
    referrer ostidagi boshqa hisoblar bilan solishtiradi. PII xesh
    ko'rinishida saqlanadi (qayta tiklanmaydi).
    """
    uname = " ".join(str(username or "").strip().lower().split())
    fname = " ".join(str(full_name or "").strip().lower().split())
    return hashlib.sha256(f"{uname}|{fname}".encode("utf-8")).hexdigest()


# ──────────────────────────────────────────────────────────────
# Konversiya bildirishnomalari (bounded in-memory navbat)
# ──────────────────────────────────────────────────────────────
# Mukofot repository qatlamida (add_post hook'i, sync thread) beriladi —
# u yerda Telegram bot obyekti YO'Q. Shu sababli referrerga yuboriladigan
# xabarlar yengil navbatga qo'yiladi va ``scheduler.referral_reward_notices_job``
# (har 1 daqiqada) ularni bot orqali yetkazadi. Navbat bounded: bot qayta
# ishga tushsa yo'qoladi — bu QABUL QILINADIGAN holat, chunki mukofotning
# o'zi (balans + credits_ledger) bazada DOIMY saqlangan.
_NOTICES_MAX = 500
_notices_lock = threading.Lock()
_pending_notices: "deque[dict]" = deque(maxlen=_NOTICES_MAX)


def queue_reward_notice(referrer_id: int, reward: int, referred_user_id: int) -> None:
    """Mukofot haqidagi bildirishnomani navbatga qo'yadi (best-effort)."""
    try:
        with _notices_lock:
            _pending_notices.append({
                "referrer_id": int(referrer_id),
                "reward": int(reward),
                "referred_user_id": int(referred_user_id),
            })
    except Exception:  # noqa: BLE001 — bildirishnoma kritik emas
        logger.debug("Referral bildirishnomasi navbatga qo'yilmadi", exc_info=True)


def pop_reward_notices(limit: int = 25) -> list:
    """Navbatdagi bildirishnomalarni oladi (scheduler job'i uchun)."""
    try:
        limit = max(1, min(int(limit), _NOTICES_MAX))
    except (TypeError, ValueError):
        limit = 25
    out = []
    with _notices_lock:
        while _pending_notices and len(out) < limit:
            out.append(_pending_notices.popleft())
    return out


def pending_notice_count() -> int:
    """Navbatdagi bildirishnomalar soni (test/monitoring uchun)."""
    with _notices_lock:
        return len(_pending_notices)


def reset_pending_notices() -> None:
    """Faqat testlar uchun — bildirishnoma navbatini tozalaydi."""
    with _notices_lock:
        _pending_notices.clear()


class ReferralService:
    """Referal ro'yxatdan o'tish + action-based mukofot (atomik, anti-abuse)."""

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
    # DUPLICATE ACCOUNT FARMING DETEKTORI (STEP 2)
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def is_duplicate_signup(cur, referrer_id: int, new_user_id: int,
                            fingerprint: str) -> bool:
        """Bir xil referrer ostida BIR XIL profil barmog'i allaqachon bormi?

        ``True`` — bu hisob "kopya" (device/account farming ehtimoli):
        biriktirish saqlanadi, lekin mukofot bloklanadi. Tekshiruv faqat
        bir xil referrer doirasida — boshqa referrerdagi oddiy o'xshash
        ismlar (masalan "Ali") noto'g'ri bloklanmaydi.
        """
        if not fingerprint or not referrer_id:
            return False
        try:
            cur.execute(
                "SELECT 1 FROM users WHERE referrer_id = %s "
                "AND signup_fingerprint = %s AND user_id <> %s LIMIT 1",
                (int(referrer_id), str(fingerprint), int(new_user_id)),
            )
            return bool(cur.fetchone())
        except Exception as exc:  # noqa: BLE001 — detektor fail-soft
            logger.warning("Duplicate-signup tekshiruvi bajarilmadi: %s", exc)
            return False

    # ──────────────────────────────────────────────────────────────
    # BONUS (CreditsService orqali, atomik) — KONVERSIYADA
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def grant_bonus_in_tx(cur, referrer_id: int, new_user_id: int) -> int:
        """Referrer'ga taklif mukofotini BERADI — chaqiruvchi tranzaksiyasida.

        🌱 STEP 2: tarif hisobi (``database.referral_reward_for(n)``: 1-,
        2-, 3-do'st uchun +3 tadan, keyingi har biriga +1; PRO berilmaydi)
        endi FAQAT KONVERSIYA QILGAN do'stlar bo'yicha yuritiladi —
        ``referral_rewarded_at IS NOT NULL``. Chaqiruvchi
        (``register_first_action``) shu tranzaksiyada do'stning
        ``referral_rewarded_at`` belgisini OLDIN qo'yadi, shuning uchun
        COUNT joriy konversiyani ham o'z ichiga oladi.

        Hisob-kitob (COUNT) va yozish (UPDATE users + INSERT
        credits_ledger) BIR tranzaksiyada — parallel konversiyalar poyga
        (race) hosil qilmaydi: COUNT dan OLDIN referrer qatori
        ``FOR UPDATE`` bilan qulflanadi. Aks holda bir referrer'ning bir
        nechta do'sti AYNI PAYTDA birinchi post yaratsa, READ COMMITTED
        izolyatsiyasida ikkala tranzaksiya ham bir xil COUNT ko'rib,
        ikkalasiga bir xil tarif yozardi. Qulf tarif hisobini referrer
        bo'yicha ketma-ketlashtiradi; qulf ochilgach COUNT yangi
        snapshot'da (boshqa tranzaksiya commit qilgan konversiyalar bilan)
        hisoblanadi.

        ``new_user_id`` — taklif qilingan do'stning ID'si (ledger'dagi
        ``reference_id`` sifatida saqlanadi). Berilgan mukofot (int) qaytadi.
        """
        cur.execute(
            "SELECT user_id FROM users WHERE user_id = %s FOR UPDATE", (referrer_id,)
        )
        cur.execute(
            "SELECT COUNT(*) FROM users WHERE referrer_id = %s "
            "AND referral_rewarded_at IS NOT NULL",
            (referrer_id,),
        )
        referral_count = int((cur.fetchone() or (0,))[0] or 0)
        reward = db.referral_reward_for(referral_count)
        CreditsService.add_in_tx(
            cur, referrer_id, int(reward), CreditsService.OP_REFERRAL,
            ref_id=str(new_user_id),
        )
        return int(reward)

    # ──────────────────────────────────────────────────────────────
    # ASOSIY OQIM 1 — /start (ref_kod bilan ham, bilmasdan ham)
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def register_new_user(user_id, username: str, full_name: str = "",
                          referrer_id=None, language_code: str = None,
                          _retry: int = 3) -> dict:
        """Foydalanuvchini ro'yxatdan o'tkazadi (yoki ma'lumotini yangilaydi).

        🌱 STEP 2: bu bosqichda bonus BERILMAYDI — referrer faqat
        biriktiriladi (attribution). Mukofot do'st birinchi postini
        yaratgach ``register_first_action`` orqali beriladi.

        Butun oqim BITTA atomik tranzaksiyada: anti-abuse tekshiruvi
        (self-referral, takroriy, noma'lum referrer, duplicate farming) +
        ``INSERT users``.

        Qaytadi::

            {"is_new": bool,             # True — yangi yozuv yaratildi
             "referrer_id": int | None,  # yakundagi referrer (yoki None)
             "reward": int,              # STEP 2: /start da doim 0
             "reward_status": str,       # none | pending_first_action | blocked
             "reason": str,              # REASON_* sabab
             "language_code": str}       # saqlangan til (1-BOSQICH: /start
                                         # bitta so'rovda is_new + til oladi)
        """
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return {"is_new": False, "referrer_id": None, "reward": 0,
                    "reward_status": REWARD_NONE,
                    "reason": REASON_NO_REFERRAL}

        try:
            with db.db_transaction() as cur:
                # --- Takroriy referral himoyasi (birinchi tekshiruv) --------
                # 1-BOSQICH: ``language_code`` ham SHU bir so'rovda olinadi —
                # /start da eski foydalanuvchi uchun alohida
                # ``get_user_language`` chaqiruvi (2-urishli round-trip)
                # kerak bo'lmasligi kerak.
                cur.execute(
                    "SELECT user_id, referrer_id, language_code "
                    "FROM users WHERE user_id = %s",
                    (user_id,),
                )
                existing = cur.fetchone()
                if existing:
                    # Foydalanuvchi allaqachon botda (created_at eski) —
                    # referrer O'ZGARMAYDI va hech qanday bonus yo'q.
                    existing_ref = existing[1]
                    existing_lang = existing[2] if len(existing) > 2 else None
                    reason = (
                        REASON_ALREADY_REREFERRED
                        if existing_ref else REASON_EXISTING_USER
                    )
                    cur.execute(
                        # 🔐 SPRINT 1: ilgari "Ma'lumotlarimni o'chirish" bilan
                        # soft-delete qilingan hisob qaytsa — belgi olinadi
                        # (balans/credits qayta BERILMAYDI: suiiste'moldan himoya).
                        "UPDATE users SET username = %s, full_name = %s, "
                        "deleted_at = NULL WHERE user_id = %s",
                        (username or "", full_name or "", user_id),
                    )
                    db._invalidate_user(user_id)
                    return {
                        "is_new": False,
                        "referrer_id": int(existing_ref) if existing_ref else None,
                        "reward": 0,
                        "reward_status": (
                            REWARD_PENDING if existing_ref else REWARD_NONE
                        ),
                        "reason": reason,
                        "language_code": existing_lang,
                    }

                # --- Anti-abuse: self-referral / noma'lum referrer ----------
                valid_ref, reason = ReferralService.validate_referral(
                    cur, user_id, referrer_id
                )

                # --- Anti-abuse: duplicate device/account farming ------------
                # Bir xil referrer + bir xil profil barmog'i = kopya hisob.
                # Biriktirish saqlanadi, mukofot bloklanadi (audit belgisi
                # ``referral_block_reason`` da qoladi).
                fingerprint = signup_fingerprint(username, full_name)
                block_reason = None
                if valid_ref and ReferralService.is_duplicate_signup(
                        cur, valid_ref, user_id, fingerprint):
                    block_reason = BLOCK_DUPLICATE_PROFILE
                    logger.warning(
                        "Duplicate farming shubhasi: user=%s referrer=%s "
                        "(bir xil profil barmog'i) — mukofot bloklandi",
                        user_id, valid_ref,
                    )

                # --- Yangi foydalanuvchi (boshlang'ich 5 ball bilan) ---------
                code = db._generate_user_code(cur)
                lang = db._normalize_language_code(language_code)
                cur.execute(
                    """
                    INSERT INTO users (user_id, username, full_name, user_code,
                                       referrer_id, ai_credits, streak_days,
                                       created_at, language_code,
                                       signup_fingerprint, referral_block_reason)
                    VALUES (%s, %s, %s, %s, %s, 5, 0, NOW(), %s, %s, %s)
                    """,
                    (user_id, username or "", full_name or "", code,
                     valid_ref, lang, fingerprint, block_reason),
                )

                # 🌱 STEP 2: bonus /start da BERILMAYDI — mukofot do'stning
                # birinchi postida (``register_first_action``) beriladi.
                if valid_ref:
                    reward_status = (
                        REWARD_BLOCKED if block_reason else REWARD_PENDING
                    )
                else:
                    reward_status = REWARD_NONE

                db._invalidate_user(user_id)
                if valid_ref:
                    db._invalidate_user(valid_ref)
                db._cache_clear("system_stats")
                return {
                    "is_new": True,
                    "referrer_id": valid_ref,
                    "reward": 0,
                    "reward_status": reward_status,
                    "reason": reason,
                    "language_code": lang,
                }
        except Exception as e:
            # Parallel /start da tasodifiy user_code to'qnashsa (UNIQUE, 6760 ta kod) tranzaksiya
            # to'liq ROLLBACK bo'lgan — yangi kod bilan qayta uriniladi (foydalanuvchi yo'qolmaydi).
            if _retry > 0 and "users_user_code_key" in str(e):
                return ReferralService.register_new_user(
                    user_id, username, full_name, referrer_id, language_code, _retry - 1)
            # Tranzaksiya avtomatik ROLLBACK bo'ldi — yarim yozuv qolmaydi.
            logger.error("ReferralService.register_new_user xatosi (user=%s): %s",
                         user_id, e)
            return {"is_new": False, "referrer_id": None, "reward": 0,
                    "reward_status": REWARD_NONE,
                    "reason": REASON_NO_REFERRAL, "error": str(e)}

    # ──────────────────────────────────────────────────────────────
    # ASOSIY OQIM 2 — BIRINCHI YAROQLI AMAL (konversiya → mukofot)
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def register_first_action(user_id, *, notify: bool = True) -> dict:
        """Taklif qilingan foydalanuvchining BIRINCHI posti → referrer mukofoti.

        ``database.add_post`` (yoki ``schedule_week_posts``) hook'i chaqiradi.
        Butun oqim BITTA atomik tranzaksiyada va IDEMPOTENT:

        1. ``UPDATE users SET referral_rewarded_at = NOW() WHERE ...
           AND referral_rewarded_at IS NULL AND referral_block_reason IS
           NULL RETURNING referrer_id`` — shartli UPDATE qator qulfi ostida
           bajariladi: parallel chaqiruvlardan FAQAT BITTASI g'olib bo'ladi
           (repeated claim himoyasi);
        2. ``credits_ledger`` da referrer uchun aynan shu do'st bo'yicha
           (``reference_id = user_id``) referral qatori ALLAQACHON bo'lsa —
           mukofot berilmaydi (himoyaning ikkinchi qatlami, legacy
           backfill bilan moslik);
        3. Referrer qatori ``FOR UPDATE`` qulflanadi → tarif hisobi
           (konversiylar soni) → ``CreditsService.add_in_tx`` (balans +
           ledger auditi BIR tranzaksiyada).

        Hech qachon istisno ko'tarmaydi (fail-soft): post saqlash oqimi
        referal tufayli HECH QACHON buzilmaydi.

        Qaytadi::

            {"granted": True, "reward": 3, "referrer_id": 7, "reason": "ok"}
            {"granted": False, "reason": "no_referral" | "already_rewarded"
             | "duplicate_profile" | "unknown_referrer" | "user_not_found"
             | "bad_user" | "db_error"}
        """
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return {"granted": False, "reward": 0, "referrer_id": None,
                    "reason": REASON_BAD_USER}
        try:
            with db.db_transaction() as cur:
                # 1) Atomik, idempotent claim: belgi FAQAT birinchi g'olibga.
                cur.execute(
                    "UPDATE users SET referral_rewarded_at = NOW() "
                    "WHERE user_id = %s AND referrer_id IS NOT NULL "
                    "AND referral_rewarded_at IS NULL "
                    "AND referral_block_reason IS NULL "
                    "RETURNING referrer_id",
                    (user_id,),
                )
                row = cur.fetchone()
                if not row or row[0] is None:
                    return ReferralService._first_action_skip_reason(cur, user_id)
                referrer_id = int(row[0])

                # 2) Ledger double-check (repeated claim'ning ikkinchi qatlami).
                cur.execute(
                    "SELECT 1 FROM credits_ledger WHERE user_id = %s "
                    "AND operation_type = %s AND reference_id = %s LIMIT 1",
                    (referrer_id, CreditsService.OP_REFERRAL, str(user_id)),
                )
                if cur.fetchone():
                    logger.info(
                        "Referral konversiya: user=%s referrer=%s — ledger'da "
                        "allaqachon bor (mukofot takrorlanmadi)", user_id, referrer_id)
                    return {"granted": False, "reward": 0,
                            "referrer_id": referrer_id,
                            "reason": REASON_ALREADY_REWARDED}

                # 3) Referrer haqiqiy hisobmi? (qulf + tarif + grant)
                cur.execute(
                    "SELECT user_id FROM users WHERE user_id = %s FOR UPDATE",
                    (referrer_id,),
                )
                if not cur.fetchone():
                    logger.warning(
                        "Referral konversiya: referrer=%s bazada yo'q "
                        "(user=%s) — mukofot berilmadi", referrer_id, user_id)
                    return {"granted": False, "reward": 0,
                            "referrer_id": referrer_id,
                            "reason": REASON_UNKNOWN_REFERRER}
                reward = ReferralService.grant_bonus_in_tx(
                    cur, referrer_id, user_id)
                db._invalidate_user(user_id)
                db._invalidate_user(referrer_id)
                db._cache_clear("system_stats")
            logger.info(
                "Referral konversiya mukofoti: referrer=%s user=%s +%s "
                "(birinchi post)", referrer_id, user_id, reward)
            if notify:
                queue_reward_notice(referrer_id, reward, user_id)
            return {"granted": True, "reward": int(reward),
                    "referrer_id": referrer_id, "reason": REASON_OK}
        except Exception as e:  # noqa: BLE001 — fail-soft (post oqimi buzilmaydi)
            logger.error(
                "ReferralService.register_first_action xatosi (user=%s): %s",
                user_id, e)
            return {"granted": False, "reward": 0, "referrer_id": None,
                    "reason": REASON_DB_ERROR, "error": str(e)}

    @staticmethod
    def _first_action_skip_reason(cur, user_id: int) -> dict:
        """Claim UPDATE bo'sh qaytarganda aniq sababni aniqlaydi (read-only)."""
        try:
            cur.execute(
                "SELECT referrer_id, referral_rewarded_at, referral_block_reason "
                "FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        except Exception:  # noqa: BLE001
            row = None
        if not row:
            reason = REASON_USER_NOT_FOUND
        elif not row[0]:
            reason = REASON_NO_REFERRAL
        elif row[1] is not None:
            reason = REASON_ALREADY_REWARDED
        else:
            reason = row[2] or REWARD_BLOCKED
        return {"granted": False, "reward": 0, "referrer_id": None,
                "reason": reason}


__all__ = [
    "BLOCK_DUPLICATE_PROFILE",
    "REASON_ALREADY_REWARDED",
    "REASON_ALREADY_REREFERRED",
    "REASON_BAD_USER",
    "REASON_DB_ERROR",
    "REASON_DUPLICATE_PROFILE",
    "REASON_EXISTING_USER",
    "REASON_NO_REFERRAL",
    "REASON_OK",
    "REASON_SELF_REFERRAL",
    "REASON_UNKNOWN_REFERRER",
    "REASON_USER_NOT_FOUND",
    "REWARD_BLOCKED",
    "REWARD_NONE",
    "REWARD_PENDING",
    "ReferralService",
    "parse_referral_code",
    "pending_notice_count",
    "pop_reward_notices",
    "queue_reward_notice",
    "reset_pending_notices",
    "signup_fingerprint",
]
