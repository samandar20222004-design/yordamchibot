# -*- coding: utf-8 -*-
"""
=====================================================================
 👤 USERS — profil, til, tier, kvota, kredits, referallar, onboarding
=====================================================================

Foydalanuvchi profili, til (uz/ru/en), onboarding holati, seriya raqami, referral o'yini, AI krediti/quotasi, PRO obuna (tier) va barcha foydalanuvchi-guruh limitlari (``check_*_limit``).

Qatlam: REPOSITORY — domain ma'lumotlariga kirish.

Bu modul yadroga (``database``: pool / tranzaksiya / kesh / sxema)
``repositories.runtime`` orqali **kech bog'lanadi**: ``db_cursor``,
``transaction``, ``_cache_*`` va boshqa yadro yordamchilari chaqiruv
paytida ``database`` modulining joriy atributiga qarab yuradi. Shu
sabab ``unittest.mock.patch("database.db_cursor")`` kabi mavjud mock
nuqtalari bu modulga ko'chirilgandan keyin ham kuchini yo'qotmaydi.
"""

import json
import random
import string
import threading
from datetime import datetime, timedelta
import logging


from config import DATABASE_URL, PLAN_LIMITS as CONFIG_PLAN_LIMITS  # noqa: F401

from database import DB_STATS_CACHE_TTL, DB_USER_CACHE_TTL, _MISS, tashkent_tz
from repositories.runtime import (  # noqa: F401
    _cache_clear, _cache_get, _cache_set, _invalidate_user,
    _profile_invalidate, db_cursor, db_transaction, get_user_profile,
    peek_user_profile
)

from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)


# ====================================================================
# 👤 USERS — profil, til, tier, kvota, kredits, referallar, onboarding
# ====================================================================

# --- USERS & CREDITS ---
def _normalize_language_code(language_code) -> str:
    """Telegram language_code → 'ru', 'en' yoki 'uz'."""
    raw = str(language_code or "").strip().lower()
    if raw.startswith("ru"):
        return "ru"
    if raw.startswith("en"):
        return "en"
    return "uz"


def _generate_user_code(cur) -> str:
    letters = string.ascii_lowercase
    for _ in range(50):
        code = "".join(random.choice(letters) for _ in range(2)) + random.choice(string.digits)
        cur.execute("SELECT 1 FROM users WHERE user_code = %s", (code,))
        if not cur.fetchone():
            return code
    return "".join(random.choice(letters) for _ in range(3)) + "".join(random.choice(string.digits) for _ in range(2))


# ============================================================
# REFERAL MUKOFOTI — FAQAT AI BALL (PRO berilmaydi)
# ============================================================
REFERRAL_TOP_TIER_FRIENDS = 3   # dastlabki nechta do'st "katta" mukofot oladi


REFERRAL_TOP_TIER_REWARD = 3    # 1-, 2-, 3-do'st uchun har biriga


REFERRAL_BASE_REWARD = 1        # 4-do'st va undan keyingilar uchun har biriga


def referral_reward_for(friend_number: int) -> int:
    """N-chi taklif qilingan do'st uchun beriladigan AI ball miqdori.

    ``friend_number`` — bu do'st referrer uchun nechanchi ekani (1 dan boshlab).
    1, 2, 3 → +3; 4 va undan keyingi barchasi → +1. Noto'g'ri (0 yoki manfiy)
    qiymat 1-do'st sifatida qaraladi.
    """
    try:
        n = int(friend_number)
    except (TypeError, ValueError):
        n = 1
    if n < 1:
        n = 1
    return REFERRAL_TOP_TIER_REWARD if n <= REFERRAL_TOP_TIER_FRIENDS else REFERRAL_BASE_REWARD


def total_referral_reward(friends_count: int) -> int:
    """``friends_count`` ta do'st uchun jami beriladigan AI ball (yig'indi)."""
    try:
        n = max(0, int(friends_count))
    except (TypeError, ValueError):
        n = 0
    return sum(referral_reward_for(i) for i in range(1, n + 1))


class _UserSaveResult(int):
    """``save_user`` natijasi — ``bool`` bilan TO'LIQ mos, ammo boy maydonli.

    Nega ``int`` subclassi (1-BOSQICH): eski chaqiruvchilar natijani
    ``if save_user(...):`` / ``== True`` / ``bool()`` shaklida ishlatadi —
    ``int`` merosxo'rligi shu qarorlarni O'ZGARMAGAN qiladi, shu bilan
    birga yangi maydonlar (``.lang``) orqali /start ikkinchi DB so'rovini
    (``get_user_language``) umuman qisqartirishga imkon beradi.

    ``lang`` — saqlangan til. Yangi foydalanuvchida ``language_code``
    dan, eskisida ``users.language_code`` ustunidan (bir xil tranzaksiya
    ichida) olinadi. ``None`` bo'lsa — bazada til yo'q, xato emas.

    (``__slots__`` ishlatilmaydi: ``int`` kabi o'lchamli (variable-length)
    built-in turga bo'sh bo'lmagan ``__slots__`` qo'yib bo'lmaydi. Bu obyekt
    faqat /start da bir marta yaratiladi — xotira muammosi yo'q.)
    """

    def __new__(cls, is_new: bool, lang=None, referrer_id=None,
                reward: int = 0, reason: str = ""):
        obj = super().__new__(cls, 1 if is_new else 0)
        obj.lang = _normalize_language_code(lang) if lang else None
        obj.referrer_id = referrer_id
        obj.reward = int(reward or 0)
        obj.reason = reason or ""
        return obj

    def __repr__(self) -> str:  # pragma: no cover — log/debug uchun
        return (f"_UserSaveResult(is_new={bool(self)}, lang={self.lang!r}, "
                f"reward={self.reward})")


def save_user(user_id: int, username: str, full_name: str = "", referrer_id: int = None,
              language_code: str = None) -> bool:
    """Foydalanuvchini saqlaydi: yangi — ro'yxatdan o'tkazadi, eski — yangilaydi.

    8-bosqich: referal anti-abuse qoidalari (self-referral, takroriy
    referral, noma'lum referrer) va ball mukofoti
    ``services.referral_service.ReferralService.register_new_user`` orqali
    BIR atomik tranzaksiyada bajariladi; mukofot formulasi
    ``referral_reward_for(n)`` (1-3 do'st +3, keyingilar +1 — PRO berilmaydi)
    va har bir bonus ``credits_ledger`` jadvaliga audit yozuvi tushadi.

    1-BOSQICH: natija ``_UserSaveResult`` — ``bool`` ga mos (orqa moslik),
    lekin ``.lang`` maydoni ham beriladi. Shu bilan ``/start`` da
    ``get_user_language`` uchun ALOHIDA (ikkinchi) DB so'rovi kerak bo'lmaydi:
    bitta upsert = bitta round-trip.

    Returns: ``_UserSaveResult`` — True/False ga teng (``bool()`` ishlaydi).
    """
    from services.referral_service import ReferralService
    try:
        result = ReferralService.register_new_user(
            user_id, username, full_name=full_name,
            referrer_id=referrer_id, language_code=language_code,
        )
        is_new = bool(result.get("is_new"))
        # Tilni TTL keshga yozamiz — keyingi ``get_user_language`` chaqiruvi
        # (boshqa ekranlar: /cabinet, til tanlash) KESHDAN o'qiladi va
        # qo'shimcha DB so'rovi qilmaydi.
        lang = result.get("language_code")
        if lang:
            _cache_set(f"user_lang:{int(user_id)}",
                       _normalize_language_code(lang), DB_USER_CACHE_TTL)
        return _UserSaveResult(
            is_new=is_new,
            lang=lang,
            referrer_id=result.get("referrer_id"),
            reward=result.get("reward"),
            reason=result.get("reason"),
        )
    except Exception as e:
        logger.error(f"User saqlash xatosi: {e}")
        return _UserSaveResult(False)


def _today_tashkent():
    """Toshkent vaqtidagi bugungi sana (Render serveri UTC da bo'lgani uchun
    `date.today()` noto'g'ri kun ko'rsatishi mumkin edi)."""
    return datetime.now(tashkent_tz).date()


def claim_daily_streak_bonus(user_id: int) -> dict:
    today = _today_tashkent()
    reward_map = {1: 1, 2: 1, 3: 2, 4: 1, 5: 2, 6: 2, 7: 4}

    # 8-bosqich: bonus ballini CreditsService orqali yechamiz (credits_ledger).
    from services.credits_service import CreditsService

    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT last_bonus_date, streak_days, ai_credits FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
            row = cur.fetchone()
            if not row:
                return {"success": False, "msg": "Foydalanuvchi topilmadi."}

            last_date, streak, credits = row
            streak = streak or 0

            if last_date == today:
                return {
                    "success": False,
                    "msg": "Siz bugungi bonusingizni olgansiz! Ertaga yana kiring.",
                    "streak": streak,
                    "credits": credits
                }

            if last_date == today - timedelta(days=1):
                streak = streak + 1 if streak < 7 else 1
            else:
                streak = 1

            bonus_amount = reward_map.get(streak, 1)

            cur.execute("""
                UPDATE users 
                SET streak_days = %s, last_bonus_date = %s 
                WHERE user_id = %s
            """, (streak, today, user_id))
            # 8-bosqich: bonusni CreditsService orqali SHU tranzaksiyada
            # qo'shamiz — balans va credits_ledger audit yozuvi (op_type=
            # 'daily_bonus') birga commit/rollback bo'ladi.
            grant = CreditsService.grant_in_tx(
                cur, user_id, bonus_amount, CreditsService.OP_DAILY_BONUS)
            new_credits = grant["balance_after"]
            _invalidate_user(user_id)
            _cache_clear("system_stats")

            return {
                "success": True,
                "streak": streak,
                "bonus_amount": bonus_amount,
                "credits": new_credits,
                "is_reset": (streak == 1 and last_date is not None and last_date != today - timedelta(days=1))
            }
    except Exception as e:
        logger.error(f"Streak bonus xatosi: {e}")
        return {"success": False, "msg": "Tizim xatoligi yuz berdi."}


# Eslatma: avvalgi "reklamasiz postlar litsenziyasi" (buy/refund/toggle/
# consume/peek_ad_free_*) funksiyalari OLIB TASHLANDI. Reklamasiz rejim endi
# to'liq avtomatik: PRO (is_premium) yoki admin → reklama umuman qo'shilmaydi,
# oddiy foydalanuvchi → admin belgilagan reklama oralig'i (ad_pool) qo'llanadi.
# ``users.ad_free_posts`` / ``users.ad_free_active`` ustunlari mavjud bazani
# buzmaslik uchun saqlanadi, lekin endi o'qilmaydi/yozilmaydi.


def add_user_credit(user_id: int, amount: int = 1) -> bool:
    """Ball qo'shadi (odatda 1 — AI xatosidagi refund).

    8-bosqich: ``CreditsService.add_credits`` orqali — balans va
    ``credits_ledger`` audit yozuvi BIR tranzaksiyada (op_type='ai_request').
    """
    from services.credits_service import CreditsService
    try:
        result = CreditsService.add_credits(
            user_id, amount, CreditsService.OP_AI_REQUEST)
        return bool(result.get("success"))
    except Exception as e:
        logger.error(f"Ball qaytarish xatosi: {e}")
        return False


def get_user_credits(user_id: int) -> int:
    cache_key = f"user_credits:{user_id}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    try:
        with db_cursor() as cur:
            cur.execute("SELECT ai_credits FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            credits = row[0] if row and row[0] is not None else 0
            _cache_set(cache_key, credits, DB_USER_CACHE_TTL)
            return credits
    except Exception as e:
        logger.error(f"Ball olish xatosi: {e}")
        return 0


def use_user_credit(user_id: int) -> bool:
    """Atomically spend one credit; prevents double-spending on concurrent updates.

    8-bosqich: ``CreditsService.spend_credits`` orqali — balans va
    ``credits_ledger`` audit yozuvi BIR tranzaksiyada (op_type='ai_request').
    Balans yetarli bo'lmasa (InsufficientCreditsError) ``False`` qaytadi va
    hech qanday yarim yozuv qolmaydi.
    """
    from services.credits_service import CreditsService, InsufficientCreditsError
    try:
        result = CreditsService.spend_credits(
            user_id, 1, CreditsService.OP_AI_REQUEST)
        return bool(result.get("success"))
    except InsufficientCreditsError:
        return False
    except Exception as e:
        logger.error(f"Ball ayirish xatosi: {e}")
        return False


def find_user_by_target(target: str):
    target_clean = target.strip().lstrip("@").lower()
    try:
        with db_cursor() as cur:
            if target_clean.isdigit():
                cur.execute("SELECT user_id, full_name, username, user_code, ai_credits FROM users WHERE user_id = %s", (int(target_clean),))
            else:
                cur.execute("SELECT user_id, full_name, username, user_code, ai_credits FROM users WHERE LOWER(user_code) = %s OR LOWER(username) = %s", (target_clean, target_clean))
            return cur.fetchone()
    except Exception as e:
        logger.error(f"Foydalanuvchi qidirish xatosi: {e}")
        return None


def transfer_user_credits(from_user_id: int, to_user_id: int, amount: int) -> tuple[bool, str]:
    if from_user_id == to_user_id:
        return False, "O'zingizga ball o'tkaza olmaysiz."
    if amount < 3 or amount > 20:
        return False, "O'tkazish miqdori kamida 3 ta, ko'pi bilan 20 ta bo'lishi kerak."

    try:
        with db_cursor(commit=True) as cur:
            # 9-bosqich (high-concurrency): ikkala foydalanuvchi qatori BITTA
            # so'rovda, DOIM user_id o'sish tartibida qulflanadi. Aks holda
            # A→B va B→A o'tkazmalari bir vaqtda kelganda qulflar teskari
            # tartibda olinib PostgreSQL "deadlock detected" berardi.
            # Deterministik tartib deadlock'ni butunlay yo'q qiladi.
            cur.execute(
                "SELECT user_id, ai_credits, created_at FROM users "
                "WHERE user_id IN (%s, %s) ORDER BY user_id FOR UPDATE",
                (from_user_id, to_user_id),
            )
            locked = {int(r[0]): r for r in cur.fetchall()}
            row_from = locked.get(int(from_user_id))
            if not row_from:
                return False, "Foydalanuvchi topilmadi."

            _uid, credits, created_at = row_from
            if created_at:
                now_tz = datetime.now(tashkent_tz)
                created_tz = tashkent_tz.localize(created_at) if created_at.tzinfo is None else created_at.astimezone(tashkent_tz)
                if (now_tz - created_tz).days < 3:
                    return False, "⚠️ <b>Xavfsizlik qoidasi:</b> Yangi ro'yxatdan o'tgan foydalanuvchilar ballarni <b>3 kun o'tgach</b> boshqalarga ulasha oladi."

            if credits < amount:
                return False, "Hisobingizda yetarli ball mavjud emas."

            if int(to_user_id) not in locked:
                return False, "Qabul qiluvchi foydalanuvchi topilmadi."

            # 8-bosqich: ball o'tkazish CreditsService orqali — ikkala tomonning
            # balans va credits_ledger audit yozuvlari SHU tranzaksiyada
            # (op_type='transfer'): yechilgan tomon manfiy, qabul qilgan musbat.
            from services.credits_service import CreditsService
            CreditsService.spend_in_tx(
                cur, from_user_id, amount, CreditsService.OP_TRANSFER,
                ref_id=str(to_user_id))
            CreditsService.add_in_tx(
                cur, to_user_id, amount, CreditsService.OP_TRANSFER,
                ref_id=str(from_user_id))
            _invalidate_user(from_user_id)
            _invalidate_user(to_user_id)
            _cache_clear("system_stats")
            return True, "Ballar muvaffaqiyatli o'tkazildi!"
    except Exception as e:
        logger.error(f"Ball o'tkazish xatosi: {e}")
        return False, f"Tizim xatoligi: {e}"


def get_referral_stats(user_id: int) -> dict:
    cache_key = f"user_stats:{user_id}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    # Profil RAM'da bo'lsa — 0 DB; sovuq bo'lsa BITTA birlashgan so'rov (bu
    # profilni ham keshga yuklaydi: keyingi kod/kanal/til/PRO o'qishlari RAM'dan).
    prof = get_user_profile(user_id)
    if prof is not None:
        return {"referrals_count": prof["referrals_count"],
                "ai_credits": prof["ai_credits"], "streak": prof["streak"]}
    try:
        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users WHERE referrer_id = %s", (user_id,))
            ref_count = cur.fetchone()[0]
            cur.execute("SELECT ai_credits, streak_days FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            credits = row[0] if row and row[0] is not None else 0
            streak = row[1] if row and len(row) > 1 and row[1] is not None else 0
            data = {"referrals_count": ref_count, "ai_credits": credits, "streak": streak}
            _cache_set(cache_key, data, DB_USER_CACHE_TTL)
            return data
    except Exception as e:
        logger.error(f"Referral xatosi: {e}")
        return {"referrals_count": 0, "ai_credits": 0, "streak": 0}


def touch_user_activity(user_ids) -> list[int]:
    """Berilgan foydalanuvchilarning faolligini vaqt bilan belgilaydi.

    Faqat ID va timestamp saqlanadi — update matni, username yoki chat payloadi
    saqlanmaydi. ``RETURNING`` foydalanuvchi hali ro'yxatdan o'tmagan bo'lsa
    health_service'ga keyingi flush uchun qayta urinish imkonini beradi.
    """
    try:
        ids = []
        for raw_id in user_ids or []:
            uid = int(raw_id)
            if uid > 0 and uid not in ids:
                ids.append(uid)
            if len(ids) >= 1000:
                break
    except (TypeError, ValueError):
        return []
    if not ids:
        return []
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE users SET last_active_at = GREATEST("
                "COALESCE(last_active_at, NOW()), NOW()) "
                "WHERE user_id = ANY(%s) RETURNING user_id",
                (ids,),
            )
            rows = cur.fetchall() or []
        return [int(row[0]) for row in rows if row and row[0] is not None]
    except Exception:
        logger.warning("Foydalanuvchi faolligini yangilashda xato", extra={
            "event": "user_activity_flush_failed",
            "error_code": "USER_ACTIVITY_DB_ERROR",
        })
        return []


def get_all_user_ids() -> list:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT user_id FROM users")
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Foydalanuvchilar xatosi: {e}")
        return []


def get_retention_cohort(days: int = 30, limit: int = 5000) -> list:
    """SPRINT 4 — onboarding/retention kohortasi (TTFP + D1/D7 uchun xom qatorlar).

    Har bir foydalanuvchi uchun: ro'yxatdan o'tish (``created_at``), oxirgi
    faollik (``last_active_at``) va BIRINCHI post vaqti
    (``scheduled_posts.created_at`` ning eng kichigi). Yangi jadval YO'Q —
    mavjud ma'lumotlardan o'qiladi, hisob-kitob
    ``services.onboarding_telemetry`` da (pure funksiyalar).

    Returns:
        ``[{"user_id", "created_at", "last_active_at", "first_post_at"}, ...]``
        (xatoda — bo'sh ro'yxat; statistika ekrani yiqilmaydi).
    """
    try:
        window = max(1, min(int(days), 365))
    except (TypeError, ValueError):
        window = 30
    try:
        safe_limit = max(1, min(int(limit), 50_000))
    except (TypeError, ValueError):
        safe_limit = 5000
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT u.user_id, u.created_at, u.last_active_at, fp.first_post_at
                  FROM users u
                  LEFT JOIN LATERAL (
                        SELECT MIN(sp.created_at) AS first_post_at
                          FROM scheduled_posts sp
                         WHERE sp.user_id = u.user_id
                  ) fp ON TRUE
                 WHERE u.created_at >= NOW() - make_interval(days => %s)
                   AND u.deleted_at IS NULL
                 ORDER BY u.created_at DESC
                 LIMIT %s
                """,
                (window, safe_limit),
            )
            rows = cur.fetchall() or []
        return [
            {
                "user_id": row[0],
                "created_at": row[1],
                "last_active_at": row[2],
                "first_post_at": row[3],
            }
            for row in rows
        ]
    except Exception as e:
        logger.warning(f"Retention kohortasini olish xatosi: {e}")
        return []


def get_user_language(user_id: int) -> str:
    """Foydalanuvchi tilini qaytaradi ('uz' yoki 'ru'). Topilmasa 'uz'."""
    cache_key = f"user_lang:{user_id}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    prof = peek_user_profile(user_id)
    if prof is not None:
        return prof["lang"]
    try:
        with db_cursor() as cur:
            cur.execute("SELECT language_code FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            lang = _normalize_language_code(row[0] if row else None)
            _cache_set(cache_key, lang, DB_USER_CACHE_TTL)
            return lang
    except Exception as e:
        logger.error(f"User tilini olish xatosi: {e}")
        return "uz"


def set_user_language(user_id: int, language_code: str) -> bool:
    """Foydalanuvchi tilini yangilaydi ('uz' | 'ru')."""
    lang = _normalize_language_code(language_code)
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE users SET language_code = %s WHERE user_id = %s",
                (lang, user_id),
            )
            updated = cur.rowcount > 0
        _cache_clear(f"user_lang:{user_id}")
        _profile_invalidate(user_id, lang=lang)  # write-through: RAM profil yangi tilda qoladi
        return updated
    except Exception as e:
        logger.error(f"User tilini saqlash xatosi: {e}")
        return False


# ============================================================
# 🆕 ONBOARDING — yangi foydalanuvchilar uchun sodda klaviatura
# ============================================================
# Qaror mantiqi (3 kun / 3 post) ``onboarding.py`` da — bu funksiya faqat
# xom faktlarni qaytaradi: created_at, chiqarilgan postlar soni va
# foydalanuvchi to'liq menyuni o'zi ochganmi.

def get_user_onboarding(user_id: int) -> dict:
    """Onboarding uchun xom ma'lumotlarni qaytaradi.

    Qaytadi::

        {"created_at": datetime | None,
         "posts_published": int,          # status = 'posted' postlar soni
         "full_menu_unlocked": bool}      # "⚙️ To'liq menyuni ochish" bosilganmi

    Foydalanuvchi topilmasa yoki DB xatosi bo'lsa **bo'sh dict** qaytadi —
    chaqiruvchi (``onboarding.decide_menu_mode``) bo'sh ma'lumotni "to'liq
    menyu" deb hisoblaydi, ya'ni xatolik hech qachon foydalanuvchini
    cheklamaydi (fail-open).
    """
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT created_at, COALESCE(full_menu_unlocked, FALSE) "
                "FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return {}
            created_at, unlocked = row
            cur.execute(
                "SELECT COUNT(*) FROM scheduled_posts "
                "WHERE user_id = %s AND status = 'posted'",
                (user_id,),
            )
            posts_published = int((cur.fetchone() or (0,))[0] or 0)
            return {
                "created_at": created_at,
                "posts_published": posts_published,
                "full_menu_unlocked": bool(unlocked),
            }
    except Exception as e:
        logger.error(f"get_user_onboarding xatosi: {e}")
        return {}


def set_user_full_menu_unlocked(user_id: int, unlocked: bool = True) -> bool:
    """"⚙️ To'liq menyuni ochish" belgisini yozadi.

    ``True`` qaytsa — yozuv yangilandi. Onboarding keshi ham tozalanadi,
    shunda keyingi menyu darhol to'liq ko'rinishda chiqadi.
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE users SET full_menu_unlocked = %s WHERE user_id = %s",
                (bool(unlocked), int(user_id)),
            )
            updated = cur.rowcount > 0
        if updated:
            _invalidate_user(user_id)
            try:
                import onboarding
                onboarding.invalidate_simple_menu(user_id)
            except Exception as _silent_exc:
                log_silent_failure("repositories.users_repository:set_user_full_menu_unlocked", _silent_exc, user_id=user_id)
        return updated
    except Exception as e:
        logger.error(f"To'liq menyu belgisini saqlash xatosi: {e}")
        return False


def get_user_code(user_id: int) -> str:
    cache_key = f"user_code:{user_id}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    prof = peek_user_profile(user_id)
    if prof is not None:
        return prof["user_code"]
    try:
        with db_cursor() as cur:
            cur.execute("SELECT user_code FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            code = row[0] if row and row[0] else str(user_id)
            _cache_set(cache_key, code, DB_USER_CACHE_TTL)
            return code
    except Exception as e:
        logger.error(f"User kod xatosi: {e}")
        return str(user_id)


def get_user_channel_list_for_analytics(user_id: int) -> list:
    """Foydalanuvchi kanallarini analitika uchun bitta bounded query'da qaytaradi.

    Returns: [(channel_id, channel_title), ...].  ``LIMIT`` N+1/oversized
    keyboard regressiyalaridan himoya qiladi; detail view keyingi so'rovni
    faqat tanlangan kanal uchun bajaradi.
    """
    try:
        from config import ANALYTICS_MAX_BATCH_IDS
        with db_cursor() as cur:
            cur.execute(
                "SELECT channel_id, channel_title FROM channels "
                "WHERE user_id = %s AND is_active = TRUE "
                "ORDER BY id ASC LIMIT %s",
                (user_id, ANALYTICS_MAX_BATCH_IDS),
            )
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Analytics channel list xatosi: {e}")
        return []


def get_user_overview_stats(user_id: int) -> dict:
    """📊 Statistika (PostAssist V2, 5-mikro qadam) — ixcham umumiy ko'rsatkichlar.

    Asosiy menyudagi «📊 Statistika» ekrani uchun foydalanuvchi darajasidagi
    4 ta asosiy ko'rsatkich:

    * ``channels``        — ulangan faol kanallar soni;
    * ``created_posts``   — jami yaratilgan postlar (barcha holatlar);
    * ``scheduled_posts`` — rejalashtirilgan (pending) postlar;
    * ``ai_requests``     — AI so'rovlar soni (kredit sarflangan so'rovlar,
                            ``credits_ledger`` auditi bo'yicha);
    * ``credits_spent``   — sarflangan kreditlar jami (har so'rov = 1 kredit,
                            refund'lar hisobga olinmaydi).

    DB xatosida ham HECH QACHON istisno ko'tarmaydi — nollar qaytadi
    (ekran bo'sh bo'lsa ham foydalanuvchiga ko'rsatiladi).
    """
    cache_key = f"user_overview_stats:{user_id}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    result = {
        "channels": 0,
        "created_posts": 0,
        "scheduled_posts": 0,
        "ai_requests": 0,
        "credits_spent": 0,
    }
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM channels "
                "WHERE user_id = %s AND is_active = TRUE",
                (user_id,),
            )
            result["channels"] = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM scheduled_posts WHERE user_id = %s",
                (user_id,),
            )
            result["created_posts"] = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM scheduled_posts "
                "WHERE user_id = %s AND status = 'pending'",
                (user_id,),
            )
            result["scheduled_posts"] = cur.fetchone()[0]
            # AI so'rovlar / sarflangan kreditlar — credits_ledger auditi:
            # har bir haqiqiy AI so'rovi 1 kredit yechadi (amount < 0,
            # operation_type='ai_request'); refund (amount > 0) sanalmaydi.
            cur.execute(
                "SELECT COUNT(*), COALESCE(SUM(-amount), 0) FROM credits_ledger "
                "WHERE user_id = %s AND operation_type = 'ai_request' "
                "AND amount < 0",
                (user_id,),
            )
            row = cur.fetchone()
            if row:
                result["ai_requests"] = int(row[0] or 0)
                result["credits_spent"] = int(row[1] or 0)
        _cache_set(cache_key, result, DB_STATS_CACHE_TTL)
    except Exception as e:
        logger.error(f"User overview stats xatosi: {e}")
    return result


def invalidate_user_overview_stats(user_id: int) -> None:
    """«🔄 Yangilash» bosilganda foydalanuvchi statistikasi keshini tozalaydi."""
    try:
        _cache_clear(f"user_overview_stats:{user_id}")
    except Exception as _silent_exc:
        log_silent_failure("repositories.users_repository:invalidate_user_overview_stats", _silent_exc, user_id=user_id)


# ============================================================
# ⚙️ FOYDALANUVCHI SOZLAMALARI (PostAssist V2, 5-mikro qadam)
# ============================================================
# 🔔 Bildirishnomalar va 🎨 Post sozlamalari ekranlari shu jadvaldan
# o'qiladi/yoziladi (user_settings). Kalitlar handler tomonida OQ RO'YXAT
# bilan cheklanadi — bu modul faqat saqlashni ta'minlaydi.

def get_user_setting(user_id: int, key: str, default: bool = False) -> bool:
    """Bitta foydalanuvchi sozlamasini qaytaradi (xato/jadval yo'q → default)."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT value FROM user_settings WHERE user_id = %s AND key = %s",
                (user_id, str(key)[:64]),
            )
            row = cur.fetchone()
            return bool(row[0]) if row else bool(default)
    except Exception as e:
        logger.debug(f"get_user_setting xatosi (default qaytadi): {e}")
        return bool(default)


def get_user_settings_bulk(user_id: int, keys: list, defaults: dict = None) -> dict:
    """Bir nechta sozlamani BITTA so'rovda qaytaradi: ``{key: bool}``.

    ``defaults`` berilsa yo'q kalitlar uchun shu qiymatlar ishlatiladi
    (aks holda ``False``). Jadval mavjud bo'lmasa ham crash yo'q.
    """
    keys = [str(k)[:64] for k in (keys or [])]
    defaults = defaults or {}
    result = {k: bool(defaults.get(k, False)) for k in keys}
    if not keys:
        return result
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT key, value FROM user_settings "
                "WHERE user_id = %s AND key = ANY(%s)",
                (user_id, keys),
            )
            for key, value in cur.fetchall():
                result[key] = bool(value)
    except Exception as e:
        logger.debug(f"get_user_settings_bulk xatosi (defaultlar qaytadi): {e}")
    return result


def set_user_setting(user_id: int, key: str, value: bool) -> bool:
    """Sozlamani saqlaydi (UPSERT). Muvaffaqiyatda ``True``."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO user_settings (user_id, key, value, updated_at) "
                "VALUES (%s, %s, %s, NOW()) "
                "ON CONFLICT (user_id, key) DO UPDATE "
                "SET value = EXCLUDED.value, updated_at = NOW()",
                (user_id, str(key)[:64], bool(value)),
            )
        return True
    except Exception as e:
        logger.error(f"set_user_setting xatosi: {e}")
        return False


# ============================================================
# SUBSCRIPTIONS, LIMITS & MONETIZATION
# ============================================================

# Tarif limitlari
PLAN_LIMITS = {
    key: {
        "max_channels": int(info["max_channels"]),
        "daily_ai_requests": int(info["daily_ai_requests"]),
    }
    for key, info in CONFIG_PLAN_LIMITS.items()
}


# Navbatda turishi mumkin bo'lgan postlar soni (free uchun).
# PRO/Enterprise — cheksiz (999).
FREE_QUEUE_MAX_POSTS = 5


def _ensure_limit_reset(cur, user_id: int):
    """Kunlik AI sanagichini yangilash (agar kun o'tgan bo'lsa)."""
    cur.execute(
        "UPDATE users SET ai_requests_today = 0, last_limit_reset = CURRENT_DATE "
        "WHERE user_id = %s AND last_limit_reset < CURRENT_DATE",
        (user_id,),
    )


def is_premium(user_id: int) -> bool:
    """Foydalanuvchi PRO yoki Enterprise ekanligini tekshiradi.

    .. deprecated:: v2
        Servis orqali chaqirish tavsiya etiladi:
        ``SubscriptionService.is_premium(user_id)``
    """
    from services.subscription_service import SubscriptionService
    return SubscriptionService.is_premium(user_id)


def get_user_plan(user_id: int) -> dict:
    """Foydalanuvchi obuna ma'lumotlarini qaytaradi."""
    try:
        with db_cursor() as cur:
            _ensure_limit_reset(cur, user_id)
            cur.execute(
                "SELECT plan_type, subscription_expires_at, ai_requests_today "
                "FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"plan_type": "free", "expires_at": None, "ai_used": 0}
            plan_type, expires_at, ai_used = row
            return {
                "plan_type": plan_type or "free",
                "expires_at": expires_at,
                "ai_used": ai_used or 0,
            }
    except Exception as e:
        logger.error(f"get_user_plan xatosi: {e}")
        return {"plan_type": "free", "expires_at": None, "ai_used": 0}


def check_channel_limit(user_id: int) -> tuple[bool, int, int]:
    """Kanal limitini tekshiradi. Returns: (can_add, current, max).

    3-BOSQICH (P0): muddati o'tgan PRO/enterprise obunasi FREE limitlariga
    tushadi (va lazy ravishda DB'da ham 'free' qilinadi) — eski ``plan_type``
    ustuni muddat tugaganidan keyin ham PRO limit berib qo'ymasligi uchun.
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT plan_type FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            plan = (row[0] if row else "free") or "free"
            # 3-BOSQICH (P0): muddati o'tgan PRO → avtomatik FREE limitlari.
            plan = _effective_plan(cur, plan, user_id)
            cur.execute(
                "SELECT COUNT(*) FROM channels WHERE user_id = %s AND is_active = TRUE",
                (user_id,),
            )
            count = cur.fetchone()[0]
            max_ch = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])["max_channels"]
            return (count < max_ch, count, max_ch)
    except Exception as e:
        logger.error(f"check_channel_limit xatosi: {e}")
        return (True, 0, 2)


def downgrade_expired_subscriptions() -> int:
    """Muddati o'tgan BARCHA PRO/enterprise obunalarni 'free' ga tushiradi.

    3-BOSQICH (P1): ``SubscriptionService.get_status`` faqat bitta foydalanuvchini
    lazy downgrade qiladi; bu sweep esa periodik job (scheduler
    ``subscription_sweep_job``) orqali hamma bazani bir tranzaksiyada tozalaydi —
    muddati tugagan PRO hech qachon PRO limitlarda qolib ketmaydi.

    Qaytaradi: tushirilgan foydalanuvchilar soni (DB xatosida 0, istisno yo'q).
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE users SET plan_type = 'free' "
                "WHERE plan_type IN ('pro', 'enterprise') "
                "AND subscription_expires_at IS NOT NULL "
                "AND subscription_expires_at <= NOW()"
            )
            count = int(cur.rowcount or 0)
        if count:
            _cache_clear("system_stats")
        return count
    except Exception as e:
        logger.error(f"downgrade_expired_subscriptions xatosi: {e}")
        return 0


_AI_QUOTA_RESERVATIONS: dict[int, int] = {}


_AI_QUOTA_RESERVATIONS_LOCK = threading.Lock()


def _remember_ai_quota_reservation(user_id: int) -> None:
    with _AI_QUOTA_RESERVATIONS_LOCK:
        uid = int(user_id)
        _AI_QUOTA_RESERVATIONS[uid] = _AI_QUOTA_RESERVATIONS.get(uid, 0) + 1
        if len(_AI_QUOTA_RESERVATIONS) > 10000:
            _AI_QUOTA_RESERVATIONS.clear()


def _consume_ai_quota_reservation(user_id: int) -> bool:
    with _AI_QUOTA_RESERVATIONS_LOCK:
        uid = int(user_id)
        count = _AI_QUOTA_RESERVATIONS.get(uid, 0)
        if count <= 0:
            return False
        if count == 1:
            _AI_QUOTA_RESERVATIONS.pop(uid, None)
        else:
            _AI_QUOTA_RESERVATIONS[uid] = count - 1
        return True


def _subscription_expired(cur, user_id: int) -> bool:
    """PRO/enterprise obunasi muddati o'tganini tekshiradi (lazy downgrade uchun).

    3-BOSQICH (P0): ``check_ai_limit`` / ``check_channel_limit`` avval faqat
    ``plan_type`` ustuniga qaragan — muddati o'tgan, lekin hali ``get_status``
    chaqirilmagan PRO foydalanuvchi PRO limitlarini SAQLAB QOLAR edi. Endi
    pro/enterprise planlarda ``subscription_expires_at`` ham tekshiriladi.

    DB xatosida ``False`` qaytaradi (joriy plan saqlanadi — fail-safe);
    qat'iy fail-closed talab qilinadigan joylarda chaqiruvchi allaqachon
    exception'larni yutadi.
    """
    try:
        cur.execute(
            "SELECT subscription_expires_at FROM users WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        if not row or row[0] is None:
            return False  # cheksiz obuna (enterprise/legacy)
        from datetime import timezone as _tz
        expires_at = row[0]
        if getattr(expires_at, "tzinfo", None) is None:
            expires_at = expires_at.replace(tzinfo=_tz.utc)
        return expires_at <= datetime.now(_tz.utc)
    except Exception:
        return False


def _effective_plan(cur, plan: str, user_id: int) -> str:
    """Plan nomini obuna muddatini hisobga olib tuzatadi (expired PRO → free)."""
    if plan in ("pro", "enterprise") and _subscription_expired(cur, user_id):
        # Lazy downgrade: keyingi so'rovlarda qayta tekshirilmasin.
        try:
            cur.execute(
                "UPDATE users SET plan_type = 'free' WHERE user_id = %s",
                (user_id,),
            )
        except Exception as _silent_exc:
            log_silent_failure("repositories.users_repository:_effective_plan", _silent_exc, user_id=user_id)
        return "free"
    return plan


def check_ai_limit(user_id: int) -> tuple[bool, int, int]:
    """Kunlik AI limitini ATOMIK bron qiladi. Returns: (can_use, used, max).

    Production P0: check va increment alohida bo'lsa parallel so'rovlarda race
    condition paydo bo'ladi. Shu sababli FREE kvota shu funksiyaning o'zida DB
    darajasida bitta shartli UPDATE bilan bron qilinadi:

        UPDATE users SET ai_requests_today = ai_requests_today + 1
        WHERE user_id = $1 AND ai_requests_today < $2

    DB uzilishi/timeout/pool xatosi yoki foydalanuvchi topilmasligi — qat'iy
    FAIL-CLOSED: can_use=False. Muvaffaqiyatli bron qilingan so'rovdan keyingi
    eski ``increment_ai_usage`` chaqiruvi idempotent no-op bo'ladi.
    """
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return (False, -1, PLAN_LIMITS["free"]["daily_ai_requests"])
    try:
        with db_cursor(commit=True) as cur:
            _ensure_limit_reset(cur, user_id)
            cur.execute(
                "SELECT plan_type, COALESCE(ai_requests_today, 0) "
                "FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return (False, 0, PLAN_LIMITS["free"]["daily_ai_requests"])
            plan, ai_used = row
            plan = plan or "free"
            # 3-BOSQICH (P0): muddati o'tgan PRO → avtomatik FREE limitlari.
            plan = _effective_plan(cur, plan, user_id)
            max_ai = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])["daily_ai_requests"]
            cur.execute(
                "UPDATE users SET ai_requests_today = COALESCE(ai_requests_today, 0) + 1 "
                "WHERE user_id = %s AND COALESCE(ai_requests_today, 0) < %s "
                "RETURNING ai_requests_today",
                (user_id, max_ai),
            )
            updated = cur.fetchone()
            if updated:
                used_after = int(updated[0] or 0)
                _remember_ai_quota_reservation(user_id)
                return (True, used_after, max_ai)
            return (False, int(ai_used or 0), max_ai)
    except Exception as e:
        logger.error(f"check_ai_limit fail-closed xatosi: {e}")
        # used=-1 — handler uchun vaqtinchalik infratuzilma xatosi signali.
        return (False, -1, PLAN_LIMITS["free"]["daily_ai_requests"])


def refund_ai_usage(user_id: int) -> bool:
    """Bron qilingan kunlik AI kvotasini qaytaradi (AI/provayder yiqilganda)."""
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return False
    try:
        # Agar keyingi legacy increment no-op bo'lishi uchun xotirada reservation
        # turgan bo'lsa, uni ham yechamiz.
        _consume_ai_quota_reservation(user_id)
        with db_cursor(commit=True) as cur:
            _ensure_limit_reset(cur, user_id)
            cur.execute(
                "UPDATE users SET ai_requests_today = GREATEST(COALESCE(ai_requests_today, 0) - 1, 0) "
                "WHERE user_id = %s",
                (user_id,),
            )
        return True
    except Exception as e:
        logger.error(f"refund_ai_usage xatosi: {e}")
        return False


def increment_ai_usage(user_id: int):
    """AI so'rov sanagichini oshiradi (legacy/idempotent).

    ``check_ai_limit`` allaqachon atomik bron qilgan bo'lsa, bu funksiya no-op:
    eski handler/test oqimlari buzilmaydi, lekin production'da double-count
    bo'lmaydi. Bevosita chaqirilganda esa fail-closed semantikasiga mos ravishda
    DB xatosini yutadi, lekin hech qachon ruxsat bermaydi.
    """
    try:
        if _consume_ai_quota_reservation(int(user_id)):
            return
        with db_cursor(commit=True) as cur:
            _ensure_limit_reset(cur, user_id)
            cur.execute(
                "UPDATE users SET ai_requests_today = COALESCE(ai_requests_today, 0) + 1 WHERE user_id = %s",
                (user_id,),
            )
    except Exception as e:
        logger.error(f"increment_ai_usage xatosi: {e}")


# ============================================================
# 🔒 PHASE 2 / 1-QADAM — ATOMIK AI BRON (KVOTA + KREDIT)
# ------------------------------------------------------------
# Muammo (refaktorgacha): ``check_ai_limit`` va ``use_user_credit`` IKKITA
# alohida tranzaksiyada ishlar edi. Natijada:
#   * parallel so'rovlarda kunlik kvota bron qilinib, kredit yechilmay
#     qolishi (yoki aksincha) mumkin — "yarim to'lov" holati;
#   * ikki qadam orasidagi xato yarim bron qoldirardi (kvota yondi,
#     foydalanuvchi javob olmadi);
#   * ayrim handlerlar DB xatosida ``allowed=True`` deb davom etardi
#     (FAIL-OPEN).
#
# Yechim: ``reserve_ai_request()`` bitta atomik blokda
#   1) foydalanuvchi qatorini ``SELECT ... FOR UPDATE`` bilan QULFLAYDI,
#   2) kunlik sanagichni yangilaydi (kun o'tgan bo'lsa),
#   3) bepul kunlik kvota bo'lsa — kvotadan ``cost`` ni yechadi,
#   4) kvota tugagan bo'lsa — ``ai_credits`` dan ``cost`` ni yechadi
#      (balans + ``credits_ledger`` auditi BIR tranzaksiyada),
#   5) bronni ``ai_reservations`` jadvaliga yozadi va ``reservation_id``
#      qaytaradi — keyinchalik ``refund_ai_request()`` shu ID bilan
#      IDEMPOTENT qaytaradi.
#
# Qat'iy FAIL-CLOSED: har qanday DB/pool/SQL xatosida tranzaksiya ROLLBACK
# qilinadi va ``allowed=False, reason="db_error"`` qaytadi. HECH QACHON
# xatoda ruxsat berilmaydi.
# ============================================================

#: ``reserve_ai_request`` rad sabablari (handler matn tanlashi uchun).
AI_RESERVE_OK = "ok"


#: Bepul kunlik kvota ham, kredit balansi ham yetarli emas.
AI_RESERVE_INSUFFICIENT = "insufficient_balance"


#: DB/pool/SQL xatosi — tranzaksiya ROLLBACK qilindi (fail-closed).
AI_RESERVE_DB_ERROR = "db_error"


#: Foydalanuvchi bazada yo'q.
AI_RESERVE_USER_NOT_FOUND = "user_not_found"


#: ``cost``/``operation_type`` yaroqsiz (chaqiruvchi xatosi) — hech narsa yozilmadi.
AI_RESERVE_INVALID_REQUEST = "invalid_request"


#: Bron manbalari (``ai_reservations.source``).
AI_RESERVE_SOURCE_QUOTA = "daily_quota"


AI_RESERVE_SOURCE_CREDIT = "credit"


#: ``ai_reservations.status`` qiymatlari.
AI_RESERVATION_ACTIVE = "active"


AI_RESERVATION_REFUNDED = "refunded"


#: Ruxsat etilgan ``operation_type`` to'plami (oq ro'yxat). ``*`` bilan
#: boshlanadigan ixtiyoriy belgilash ham qabul qilinadi (masalan
#: ``magic_post:sales``) — lekin asos qism oq ro'yxatda bo'lishi shart.
AI_OPERATION_TYPES = (
    "ai_chat", "ai_studio", "magic_post", "voice_post", "image_post",
    "post_score", "post_enhancer", "content_calendar", "other",
)


#: ``cost`` chegaralari (so'rov bitta AI chaqiruvi = 1).
AI_RESERVE_COST_MIN = 1


AI_RESERVE_COST_MAX = 100


def _deny_ai_reserve(reason: str, used: int = 0,
                     max_ai: int = None, **extra) -> dict:
    """Rad javobini yig'adi (barcha maydonlar doim to'ldirilgan bo'ladi)."""
    result = {
        "allowed": False,
        "reason": reason,
        "reservation_id": None,
        "source": None,
        "cost": 0,
        "used": int(used or 0),
        "max_ai": (int(max_ai) if max_ai is not None
                   else PLAN_LIMITS["free"]["daily_ai_requests"]),
        "credits_left": None,
    }
    result.update(extra)
    return result


def _effective_plan_strict(cur, plan: str, user_id: int) -> str:
    """``_effective_plan`` ning QAT'IY (fail-closed) varianti.

    ``_effective_plan`` obuna muddatini tekshirishda xato bo'lsa ``False``
    qaytarib, foydalanuvchini PRO deb qoldiradi (fail-open). Atomik bron
    zanjirida bu yaramaydi: xato bo'lsa istisno ko'tariladi va chaqiruvchi
    (``reserve_ai_request``) butun tranzaksiyani ROLLBACK qilib, so'rovni
    rad etadi.
    """
    plan = (plan or "free").strip().lower() or "free"
    if plan not in ("pro", "enterprise"):
        return plan
    # Xato bo'lsa istisno tarqaladi — bu yerda yutilmaydi (fail-closed).
    cur.execute(
        "SELECT subscription_expires_at FROM users WHERE user_id = %s",
        (user_id,),
    )
    row = cur.fetchone()
    if not row or row[0] is None:
        return plan  # cheksiz obuna (enterprise/legacy)
    from datetime import timezone as _tz
    expires_at = row[0]
    if getattr(expires_at, "tzinfo", None) is None:
        expires_at = expires_at.replace(tzinfo=_tz.utc)
    if expires_at > datetime.now(_tz.utc):
        return plan
    # Muddati o'tgan PRO → FREE (lazy downgrade, shu tranzaksiyada).
    cur.execute(
        "UPDATE users SET plan_type = 'free' WHERE user_id = %s", (user_id,)
    )
    return "free"


def reserve_ai_request(user_id: int, operation_type: str = "other",
                       cost: int = 1) -> dict:
    """AI so'rovi uchun kvota/kreditni BITTA atomik tranzaksiyada bron qiladi.

    Bu funksiya ``check_ai_limit`` + ``use_user_credit`` juftligining
    tranzaksiyaga birlashtirilgan o'rnini bosadi: bitta ulanish, bitta
    ``BEGIN ... COMMIT``, qator qulfi (``SELECT ... FOR UPDATE``) va
    ``ai_reservations`` audit qatori.

    Args:
        user_id: Telegram user id.
        operation_type: qaysi oqim (``magic_post``, ``ai_studio``, ...).
            Oq ro'yxat: ``AI_OPERATION_TYPES``; ``"magic_post:sales"`` kabi
            belgilash ham qabul qilinadi.
        cost: nechta birlik yechiladi (standart 1).

    Returns:
        dict — doim bir xil shakl::

            {"allowed": bool, "reason": str, "reservation_id": int | None,
             "source": "daily_quota" | "credit" | None, "cost": int,
             "used": int, "max_ai": int, "credits_left": int | None}

        ``reason`` qiymatlari: ``ok`` | ``insufficient_balance`` |
        ``db_error`` | ``user_not_found`` | ``invalid_request``.

    Kafolatlar:
        * **Atomik** — kvota, kredit, ``credits_ledger`` auditi va bron
          qatori BITTA tranzaksiyada; xatoda hammasi ROLLBACK.
        * **Race-free** — parallel so'rovlarda ``FOR UPDATE`` qulfi tufayli
          bitta balansdan ikki marta yechib bo'lmaydi.
        * **FAIL-CLOSED** — har qanday xatoda ``allowed=False``.
    """
    # ---- argument validatsiyasi (DB'ga tegmasdan, fail-closed) ----------
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return _deny_ai_reserve(AI_RESERVE_INVALID_REQUEST,
                                used=-1, error="bad_user_id")
    try:
        cost_int = int(cost)
    except (TypeError, ValueError):
        return _deny_ai_reserve(AI_RESERVE_INVALID_REQUEST,
                                used=-1, error="bad_cost")
    if not (AI_RESERVE_COST_MIN <= cost_int <= AI_RESERVE_COST_MAX):
        return _deny_ai_reserve(AI_RESERVE_INVALID_REQUEST,
                                used=-1, error="cost_out_of_range")
    op_base = str(operation_type or "").strip().split(":", 1)[0].lower()
    if op_base not in AI_OPERATION_TYPES:
        return _deny_ai_reserve(AI_RESERVE_INVALID_REQUEST,
                                used=-1, error="bad_operation_type")

    from services.credits_service import CreditsService, InsufficientCreditsError

    max_ai = PLAN_LIMITS["free"]["daily_ai_requests"]
    try:
        # BITTA atomik blok: qator qulfi → kvota → kredit → bron qatori.
        with db_cursor(commit=True) as cur:
            # 1) Qatorni QULFLASH — parallel bronlar shu yerda navbatga turadi.
            #    COALESCE plan_type ustuni bo'lmagan eski bazalarda ham
            #    ishlashi uchun; ``FOR UPDATE`` qulfni oladi.
            cur.execute(
                "SELECT COALESCE(plan_type, 'free'), "
                "COALESCE(ai_requests_today, 0), COALESCE(ai_credits, 0) "
                "FROM users WHERE user_id = %s FOR UPDATE",
                (uid,),
            )
            row = cur.fetchone()
            if not row:
                # Foydalanuvchi yo'q — ruxsat YO'Q (fail-closed).
                return _deny_ai_reserve(AI_RESERVE_USER_NOT_FOUND,
                                        used=0, max_ai=max_ai)
            plan_raw, used_before, credits_before = row
            used_before = int(used_before or 0)
            credits_before = int(credits_before or 0)

            # 2) Kunlik sanagichni yangilash (kun o'tgan bo'lsa) — shu
            #    tranzaksiyada, shu qulflangan qatorda.
            _ensure_limit_reset(cur, uid)
            cur.execute(
                "SELECT COALESCE(ai_requests_today, 0) FROM users "
                "WHERE user_id = %s",
                (uid,),
            )
            reset_row = cur.fetchone()
            if reset_row:
                used_before = int(reset_row[0] or 0)

            # 3) Amaldagi tarif (muddati o'tgan PRO → FREE, qat'iy).
            plan = _effective_plan_strict(cur, plan_raw, uid)
            max_ai = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])["daily_ai_requests"]

            source = None
            credits_after = credits_before

            # 4a) Bepul kunlik kvota bo'lsa — AVVAL kvotadan yechiladi.
            if used_before < max_ai:
                cur.execute(
                    "UPDATE users SET ai_requests_today = "
                    "COALESCE(ai_requests_today, 0) + %s "
                    "WHERE user_id = %s "
                    "AND COALESCE(ai_requests_today, 0) + %s <= %s "
                    "RETURNING COALESCE(ai_requests_today, 0)",
                    (cost_int, uid, cost_int, max_ai),
                )
                quota_row = cur.fetchone()
                if quota_row:
                    source = AI_RESERVE_SOURCE_QUOTA
                    used_before = int(quota_row[0] or 0)

            # 4b) Kvota tugagan (yoki tarifda kunlik kvota yo'q) → KREDIT.
            if source is None:
                # Kredit yo'li SAVEPOINT ichida: balans yetarli bo'lmasa bron
                # qatori ham ROLLBACK bo'ladi (bazada "yetim bron" qolmaydi).
                try:
                    with db_transaction() as tx_cur:
                        # INSERT oldin: ledger yozuviga aniq bron ID'si tushadi.
                        tx_cur.execute(
                            "INSERT INTO ai_reservations "
                            "(user_id, operation_type, cost, source, status) "
                            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                            (uid, op_base, cost_int, AI_RESERVE_SOURCE_CREDIT,
                             AI_RESERVATION_ACTIVE),
                        )
                        res_row = tx_cur.fetchone()
                        reservation_id = int(res_row[0]) if res_row else 0
                        spend = CreditsService.spend_in_tx(
                            tx_cur, uid, cost_int,
                            op_type=CreditsService.OP_AI_REQUEST,
                            ref_id=f"ai_reservation:{reservation_id}",
                        )
                        if not spend.get("success"):
                            raise InsufficientCreditsError(
                                uid, cost_int, credits_before)
                        credits_after = int(spend.get("balance_after") or 0)
                except InsufficientCreditsError as exc:
                    # SAVEPOINT ROLLBACK qilindi → INSERT ham bekor.
                    raise _InsufficientBalanceSignal(
                        int(getattr(exc, "available", 0) or 0),
                        used_before, max_ai,
                    )
                source = AI_RESERVE_SOURCE_CREDIT
            else:
                # Kvota bron qilingan — bron qatori shu tranzaksiyada yoziladi.
                cur.execute(
                    "INSERT INTO ai_reservations "
                    "(user_id, operation_type, cost, source, status) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (uid, op_base, cost_int, AI_RESERVE_SOURCE_QUOTA,
                     AI_RESERVATION_ACTIVE),
                )
                res_row = cur.fetchone()
                reservation_id = int(res_row[0]) if res_row else 0

    except _InsufficientBalanceSignal as sig:
        # Yetarli mablag' yo'q — bu xato emas, lekin ruxsat ham yo'q.
        return _deny_ai_reserve(
            AI_RESERVE_INSUFFICIENT, used=sig.used, max_ai=sig.max_ai,
            credits_left=sig.available)
    except Exception as e:  # noqa: BLE001 — QAT'IY FAIL-CLOSED
        # Tranzaksiya bloki ROLLBACK qildi: yarim bron/yarim yechuv qolmadi.
        logger.error("reserve_ai_request fail-closed xatosi (user=%s, op=%s): %s",
                     uid, op_base, e)
        return _deny_ai_reserve(AI_RESERVE_DB_ERROR, used=-1, max_ai=max_ai,
                                error=type(e).__name__)

    # Kesh tranzaksiyadan KEYIN tozalanadi (eski balans ko'rinib qolmasin).
    try:
        _invalidate_user(uid)
    except Exception as _silent_exc:
        log_silent_failure("repositories.users_repository:reserve_ai_request", _silent_exc, user_id=user_id)
    # Eslatma: avtomatik faollik bonusi (+2) shu primitivada EMAS —
    # ``services.ai_quota.reserve_ai_quota`` choke point'da beriladi. Bu
    # funksiya qattiq kvota semantikasi uchun TOZA qoladi (race testlar).
    return {
        "allowed": True,
        "reason": AI_RESERVE_OK,
        "reservation_id": int(reservation_id or 0),
        "source": source,
        "cost": cost_int,
        "used": used_before,
        "max_ai": max_ai,
        "credits_left": credits_after,
    }


class _InsufficientBalanceSignal(Exception):
    """Ichki signal: mablag' yetarli emas (tranzaksiyani toza yakunlash uchun).

    ``InsufficientCreditsError`` to'g'ridan-to'g'ri tashqi blokka chiqsa
    ``db_cursor`` ROLLBACK qiladi — bu kerakli xatti-harakat, lekin "balans
    kam" holati tizim xatosi emas. Shu sababli ichki signalga o'rab, aniq
    sonlar (mavjud balans, sarflangan kvota) bilan qaytaramiz.
    """

    __slots__ = ("available", "used", "max_ai")

    def __init__(self, available: int, used: int, max_ai: int):
        self.available = int(available or 0)
        self.used = int(used or 0)
        self.max_ai = int(max_ai or 0)
        super().__init__("insufficient_balance")


def refund_ai_request(user_id: int, reservation_id) -> dict:
    """Bron qilingan AI kvota/kreditini ATOMIK va IDEMPOTENT qaytaradi.

    AI so'rovi muvaffaqiyatsiz tugaganda (timeout, provayder xatosi, bo'sh
    javob) chaqiriladi. Qaytarish manbaga qarab aniq bajariladi:

    * ``source='daily_quota'`` → ``ai_requests_today`` kamaytiriladi;
    * ``source='credit'``      → ``ai_credits`` qaytadi va ``credits_ledger``
      ga ``ai_refund`` audit yozuvi tushadi.

    Idempotentlik: ``UPDATE ai_reservations SET status='refunded'
    WHERE id=%s AND user_id=%s AND status='active'`` — qaytarilgan bron
    ikkinchi marta qaytarilmaydi (parallel refund/retry ham xavfsiz).

    Returns:
        dict::

            {"success": bool, "reason": "refunded" | "not_found" |
             "already_refunded" | "invalid_reservation" | "db_error",
             "reservation_id": int | None, "source": str | None}

    FAIL-CLOSED: DB xatosida ``success=False, reason="db_error"`` — hech
    qanday yarim qaytaruv qolmaydi (tranzaksiya ROLLBACK).
    """
    try:
        rid = int(reservation_id)
    except (TypeError, ValueError):
        return {"success": False, "reason": "invalid_reservation",
                "reservation_id": None, "source": None}
    if rid <= 0:
        return {"success": False, "reason": "invalid_reservation",
                "reservation_id": None, "source": None}
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return {"success": False, "reason": "invalid_reservation",
                "reservation_id": rid, "source": None}

    from services.credits_service import CreditsService

    try:
        with db_cursor(commit=True) as cur:
            # Bitta atomik holat o'tishi: faqat 'active' bron qaytariladi.
            cur.execute(
                "UPDATE ai_reservations SET status = %s, refunded_at = NOW() "
                "WHERE id = %s AND user_id = %s AND status = %s "
                "RETURNING source, cost",
                (AI_RESERVATION_REFUNDED, rid, uid, AI_RESERVATION_ACTIVE),
            )
            row = cur.fetchone()
            if not row:
                # Nima uchun qaytmadi — aniq sabab (audit/monitoring uchun).
                cur.execute(
                    "SELECT status, source FROM ai_reservations "
                    "WHERE id = %s AND user_id = %s",
                    (rid, uid),
                )
                info = cur.fetchone()
                reason = ("already_refunded"
                          if info and info[0] == AI_RESERVATION_REFUNDED
                          else "not_found")
                return {"success": False, "reason": reason,
                        "reservation_id": rid,
                        "source": (info[1] if info else None)}
            source = str(row[0] or "")
            cost = int(row[1] or 0)

            if source == AI_RESERVE_SOURCE_QUOTA:
                # Kunlik kvota qaytadi (manfiyga tushib ketmaydi).
                _ensure_limit_reset(cur, uid)
                cur.execute(
                    "UPDATE users SET ai_requests_today = GREATEST("
                    "COALESCE(ai_requests_today, 0) - %s, 0) "
                    "WHERE user_id = %s",
                    (cost, uid),
                )
            else:
                # Kredit qaytadi + audit yozuvi (BIR tranzaksiyada).
                add = CreditsService.add_in_tx(
                    cur, uid, cost,
                    op_type=CreditsService.OP_AI_REFUND,
                    ref_id=f"ai_reservation:{rid}",
                )
                if not add.get("success"):
                    # Foydalanuvchi o'chirilgan bo'lishi mumkin — yarim
                    # qaytaruv qoldirmaslik uchun tranzaksiyani buzamiz.
                    raise RuntimeError(
                        f"refund: kredit qaytarilmadi ({add.get('error')})")
    except Exception as e:  # noqa: BLE001 — FAIL-CLOSED
        logger.error("refund_ai_request xatosi (user=%s, reservation=%s): %s",
                     uid, rid, e)
        return {"success": False, "reason": "db_error",
                "reservation_id": rid, "source": None}

    try:
        _invalidate_user(uid)
    except Exception as _silent_exc:
        log_silent_failure("repositories.users_repository:refund_ai_request", _silent_exc, user_id=user_id)
    return {"success": True, "reason": "refunded",
            "reservation_id": rid, "source": source}


def check_queue_limit(user_id: int) -> tuple[bool, int, int]:
    """Navbatdagi postlar soni limitini tekshiradi.

    Returns: (can_add, current, max).
    """
    try:
        with db_cursor() as cur:
            cur.execute("SELECT plan_type FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            plan = (row[0] if row else "free") or "free"
            cur.execute(
                "SELECT COUNT(*) FROM scheduled_posts WHERE user_id = %s AND status = 'pending'",
                (user_id,),
            )
            count = cur.fetchone()[0]
            max_q = FREE_QUEUE_MAX_POSTS if plan == "free" else 999
            return (count < max_q, count, max_q)
    except Exception as e:
        logger.error(f"check_queue_limit xatosi: {e}")
        return (True, 0, FREE_QUEUE_MAX_POSTS)


def sync_stars_subscription(user_id: int, state: str, expires_at=None) -> bool:
    """Synchronize a Telegram Stars recurring-subscription update.

    Telegram cancellation stops future renewals, but does not revoke an already
    paid period. Thus ``canceled``/``failed`` records billing state while PRO
    remains enabled until ``subscription_expires_at``; the existing expiry
    sweep downgrades it afterwards. A successful recurring payment supplies an
    exact Telegram expiration timestamp, which is kept monotonic so delayed
    updates cannot shorten a later paid period.
    """
    try:
        uid = int(user_id)
        status = str(state or "").strip().lower()
    except (TypeError, ValueError):
        return False
    if uid <= 0 or status not in {"active", "canceled", "failed"}:
        return False

    try:
        with db_cursor(commit=True) as cur:
            if status == "active" and expires_at is not None:
                cur.execute(
                    "UPDATE users SET "
                    "plan_type = CASE WHEN plan_type = 'enterprise' THEN plan_type ELSE 'pro' END, "
                    "subscription_expires_at = CASE "
                    "WHEN plan_type = 'enterprise' THEN subscription_expires_at "
                    "ELSE GREATEST(COALESCE(subscription_expires_at, %s), %s) END, "
                    "stars_subscription_state = 'active' "
                    "WHERE user_id = %s",
                    (expires_at, expires_at, uid),
                )
            elif status == "active":
                # An "active" BotSubscriptionUpdated update can mean the user
                # re-enabled auto-renew; it is not a payment and must not grant
                # a fresh month or create an unbounded PRO plan.
                cur.execute(
                    "UPDATE users SET "
                    "plan_type = CASE "
                    "WHEN plan_type = 'enterprise' THEN 'enterprise' "
                    "WHEN subscription_expires_at > NOW() "
                    "  OR (plan_type = 'pro' AND subscription_expires_at IS NULL) "
                    "THEN 'pro' ELSE 'free' END, "
                    "stars_subscription_state = 'active' "
                    "WHERE user_id = %s",
                    (uid,),
                )
            else:
                # Cancellation/failed renewal keeps the already-paid period;
                # expired PRO is downgraded immediately, unlimited enterprise
                # and manually granted plans (NULL expiry) remain untouched.
                cur.execute(
                    "UPDATE users SET "
                    "plan_type = CASE "
                    "WHEN plan_type = 'enterprise' THEN 'enterprise' "
                    "WHEN subscription_expires_at > NOW() "
                    "  OR (plan_type = 'pro' AND subscription_expires_at IS NULL) "
                    "THEN 'pro' ELSE 'free' END, "
                    "stars_subscription_state = %s "
                    "WHERE user_id = %s",
                    (status, uid),
                )
            updated = cur.rowcount > 0
        if updated:
            _invalidate_user(uid)
            _cache_clear("system_stats")
            _cache_clear("admin_dashboard_stats")
        return updated
    except Exception as e:
        logger.error("sync_stars_subscription xatosi: %s", e)
        return False


def set_user_plan(user_id: int, plan: str, days: int = None,
                  admin_id: int = None) -> bool:
    """Foydalanuvchi tarifini o'zgartiradi.

    ``admin_id`` (6-bosqich) berilsa — PRO berish harakati
    ``admin_audit_logs`` jadvaliga yoziladi (atomik).

    .. deprecated:: v2
        Servis orqali chaqirish tavsiya etiladi:
        ``SubscriptionService.activate(user_id, plan, days)``
    """
    from services.subscription_service import SubscriptionService
    if plan not in PLAN_LIMITS:
        return False
    if days and days > 0:
        return SubscriptionService.activate(user_id, plan, days, admin_id=admin_id)
    else:
        # Cheksiz (days=None yoki 0) — activate qiyin bo'lgani uchun
        # to'g'ridan-to'g'ri DB ga yozamiz
        try:
            with db_cursor(commit=True) as cur:
                cur.execute(
                    "UPDATE users SET plan_type = %s, subscription_expires_at = NULL "
                    "WHERE user_id = %s",
                    (plan, user_id),
                )
                updated = cur.rowcount > 0
            _invalidate_user(user_id)
            return updated
        except Exception as e:
            logger.error(f"set_user_plan xatosi: {e}")
            return False


def create_promo_code(code: str, plan_type: str = "pro", duration_days: int = 30,
                      max_uses: int = None, admin_id: int = None) -> bool:
    """Promo-kod yaratadi (admin).

    ``admin_id`` (6-bosqich) berilsa — harakat ``admin_audit_logs``
    jadvaliga kod yaratilgan tranzaksiyada yoziladi (atomik).

    .. deprecated:: v2
        Servis orqali chaqirish tavsiya etiladi:
        ``PromoService.create_promo(code, duration_days, max_uses, expires_at, plan_type)``
    """
    from services.promo_service import PromoService
    return PromoService.create_promo(code, duration_days, max_uses, None,
                                     plan_type, admin_id=admin_id)


def redeem_promo_code(user_id: int, code: str) -> tuple[bool, str]:
    """Promo-kodni bir marta, race-free tarzda faollashtiradi.

    .. deprecated:: v2
        Servis orqali chaqirish tavsiya etiladi:
        ``PromoService.redeem_promo(user_id, code)``
    """
    from services.promo_service import PromoService
    return PromoService.redeem_promo(user_id, code)


# ============================================================
# REFERAL — faqat ma'lumot funksiyalari (PRO mukofoti OLIB TASHLANGAN)
# ============================================================
# Avvalgi "3 ta faol do'st = 30 kun PRO" mantiqi (REFERRAL_PRO_THRESHOLD,
# get_active_referral_count, check_and_grant_referral_pro,
# get_referral_pro_progress) butunlay olib tashlandi. Do'st taklif qilish
# endi faqat AI ball beradi — qarang: ``referral_reward_for``.


def get_referrer_id(user_id: int) -> int | None:
    """Foydalanuvchini taklif qilgan (referrer) foydalanuvchi ID'si.

    Hech kim taklif qilmagan bo'lsa (ustun NULL) yoki baza xato bersa — None.

    Eslatma: ``run_db`` orqali chaqiriladi (``await db.run_db(db.get_referrer_id, user_id)``) —
    ichida kursor O'ZI ochiladi, tashqaridan kursor uzatilmaydi.
    """
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT referrer_id FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if row and row[0]:
                return int(row[0])
            return None
    except Exception as e:
        logger.error(f"get_referrer_id xatosi: {e}")
        return None


# ============================================================
# 🔐 SPRINT 1 — MAXFIYLIK: «MA'LUMOTLARIMNI O'CHIRISH» (GDPR)
# ============================================================
#: Foydalanuvchi o'chirganda SAQLANADIGAN (qonuniy audit) jadvallar.
#: Bu ro'yxat matnda ham (``translations/privacy.py``), testlarda ham
#: qo'riqlanadi — o'zgartirilsa, uchala joy yangilanishi shart.
ACCOUNT_DELETE_RETAINED_TABLES = (
    "payments", "payment_receipts", "payment_orders", "credits_ledger",
)

#: Kanal darajasida (``channel_id`` orqali) tozalanadigan jadvallar.
#: ``(jadval, ustun, channel_id_turi)`` — turi ``str`` bo'lsa VARCHAR(255),
#: ``int`` bo'lsa BIGINT (schema.sql bilan bir xil).
_ACCOUNT_DELETE_CHANNEL_SCOPED = (
    ("channel_dna", "channel_id", str),
    ("channel_insights", "channel_id", str),
    ("channel_comment_insights", "channel_id", str),
    ("channel_intelligence_profiles", "channel_id", str),
    ("channel_post_events", "channel_id", str),
    ("channel_post_counters", "channel_id", str),
    ("channel_posts_history", "channel_id", str),
    ("sent_post_messages", "channel_id", str),
    ("post_deliveries", "channel_id", int),
)


def _delete_user_channels_data(cur, user_id: int, channel_ids: list) -> dict:
    """Kanal-darajali tahlil/navbat ma'lumotlarini o'chiradi (helper).

    Faqat shu foydalanuvchiga tegishli kanallar bo'yicha ishlaydi —
    boshqa egalikdagi kanal ma'lumotiga tegilmaydi.
    """
    counts: dict = {}
    if not channel_ids:
        return counts
    as_text = [str(c) for c in channel_ids]
    as_int = []
    for value in channel_ids:
        try:
            as_int.append(int(str(value)))
        except (TypeError, ValueError):
            continue
    for table, column, kind in _ACCOUNT_DELETE_CHANNEL_SCOPED:
        values = as_text if kind is str else as_int
        if not values:
            continue
        try:
            cur.execute(
                f"DELETE FROM {table} WHERE {column} = ANY(%s)",  # noqa: S608 — jadval nomi kod-konstanta  # nosec B608
                (values,),
            )
            counts[table] = int(cur.rowcount or 0)
        except Exception as table_exc:  # noqa: BLE001 — bitta jadval xatosi qolganini to'xtatmaydi
            logger.warning(
                "delete_user_data: %s tozalanmadi (user=%s): %s",
                table, user_id, table_exc,
            )
            counts[table] = 0
    return counts


def delete_user_data(user_id: int) -> dict:
    """«🗑 Ma'lumotlarimni o'chirish» — kaskadli/soft-delete (GDPR).

    Bitta atomik tranzaksiyada:
      1. ``users`` — soft-delete + anonimlashtirish (ism/username/referrer/
         rol tozalanadi, ``deleted_at`` qo'yiladi; ``user_id`` audit uchun
         qoladi);
      2. ``channels`` — soft-delete (``is_active=FALSE``, nom va tur
         tozalanadi);
      3. post matnlari — qoralamalar/navbat bekor qilinadi, matn/media
         maydonlari NULL qilinadi (yuborilgan postlar tarixi ham);
      4. AI tarixi — ``ai_usage_events`` (uchinchi tomon so'rov telemetriyasi)
         va ``ai_reservations`` o'chiriladi;
      5. kanal-darajali tahlil jadvallari, shablonlar, manbalar, qo'llab-
         quvvatlash murojaatlari, sozlamalar va jamoa a'zoligi tozalanadi.

    SAQLANADI (qonuniy/buxgalteriya auditi): ``payments``,
    ``payment_receipts``, ``payment_orders``, ``credits_ledger`` —
    ``ACCOUNT_DELETE_RETAINED_TABLES``.

    Qaytaradi::

        {"ok": True, "channels": N, "posts": N, "ai_events": N,
         "already_deleted": bool, "cleaned": {jadval: qatorlar}}

    Xatoda: ``{"ok": False, "reason": "..."}`` — handler foydalanuvchiga
    xavfsiz xabar qaytaradi, xato esa log/Sentry'da ko'rinadi.
    """
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        logger.error("delete_user_data: noto'g'ri user_id=%r", user_id)
        return {"ok": False, "reason": "invalid_user_id"}
    if uid <= 0:
        logger.error("delete_user_data: musbat bo'lmagan user_id=%s", uid)
        return {"ok": False, "reason": "invalid_user_id"}

    summary = {
        "ok": True, "user_id": uid, "channels": 0, "posts": 0,
        "ai_events": 0, "already_deleted": False, "cleaned": {},
    }
    try:
        with db_transaction() as cur:
            cur.execute("SELECT deleted_at FROM users WHERE user_id = %s", (uid,))
            row = cur.fetchone()
            if row is not None and row[0] is not None:
                summary["already_deleted"] = True
                summary["cleaned"] = {}
                return summary

            cur.execute(
                "SELECT channel_id FROM channels WHERE user_id = %s", (uid,))
            channel_ids = [r[0] for r in (cur.fetchall() or [])]
            summary["channels"] = len(channel_ids)

            # --- 1) Post matnlari: navbat bekor + matn/media tozalanadi ---
            cur.execute(
                """
                UPDATE scheduled_posts
                   SET content = NULL, file_id = NULL,
                       inline_button_text = NULL, inline_button_url = NULL,
                       reaction_emojis = NULL,
                       delivery_options = '{}'::jsonb
                 WHERE user_id = %s
                """,
                (uid,),
            )
            summary["cleaned"]["scheduled_posts"] = int(cur.rowcount or 0)
            cur.execute(
                """
                UPDATE scheduled_posts SET status = 'cancelled'
                 WHERE user_id = %s
                   AND status IN ('draft', 'pending_approval', 'approved',
                                  'scheduled', 'pending', 'processing',
                                  'failed', 'unknown')
                """,
                (uid,),
            )
            summary["posts"] = int(cur.rowcount or 0)
            # Navbatdagi yuborilishlar (post_deliveries CHECK'i 'cancelled'ni
            # bilmaydi) — PENDING qatorlar o'chiriladi (qayta yuborilmasin).
            cur.execute(
                """
                DELETE FROM post_deliveries
                 WHERE status IN ('pending', 'processing', 'failed')
                   AND post_id IN (SELECT id FROM scheduled_posts WHERE user_id = %s)
                """,
                (uid,),
            )
            summary["cleaned"]["post_deliveries_pending"] = int(cur.rowcount or 0)

            # --- 2) Kanal-darajali tahlil/navbat ma'lumotlari ---
            summary["cleaned"].update(
                _delete_user_channels_data(cur, uid, channel_ids))

            # --- 3) Foydalanuvchi-darajali jadvallar ---
            channel_members = 0
            if channel_ids:
                cur.execute(
                    "DELETE FROM channel_members "
                    "WHERE user_id = %s OR channel_id = ANY(%s)",
                    (uid, [str(c) for c in channel_ids]),
                )
                channel_members = int(cur.rowcount or 0)
            else:
                cur.execute("DELETE FROM channel_members WHERE user_id = %s", (uid,))
                channel_members = int(cur.rowcount or 0)
            summary["cleaned"]["channel_members"] = channel_members

            # Manbalar: avval ularga bog'langan item/draft, keyin manba.
            cur.execute(
                "DELETE FROM source_drafts WHERE user_id = %s", (uid,))
            summary["cleaned"]["source_drafts"] = int(cur.rowcount or 0)
            cur.execute(
                """
                DELETE FROM source_items
                 WHERE source_id IN (SELECT id FROM content_sources WHERE user_id = %s)
                """,
                (uid,),
            )
            summary["cleaned"]["source_items"] = int(cur.rowcount or 0)
            cur.execute(
                "DELETE FROM content_sources WHERE user_id = %s", (uid,))
            summary["cleaned"]["content_sources"] = int(cur.rowcount or 0)

            for table in ("post_templates", "user_settings", "ai_reservations",
                          "promo_redemptions", "admin_roles"):
                cur.execute(f"DELETE FROM {table} WHERE user_id = %s", (uid,))  # noqa: S608  # nosec B608 — jadval nomi kod-konstanta (DELETE ... WHERE user_id = %s)
                summary["cleaned"][table] = int(cur.rowcount or 0)

            cur.execute(
                "DELETE FROM support_tickets WHERE user_id = %s", (uid,))
            summary["cleaned"]["support_tickets"] = int(cur.rowcount or 0)

            # --- 4) AI tarixi (uchinchi tomon so'rov telemetriyasi) ---
            cur.execute(
                "DELETE FROM ai_usage_events WHERE user_id = %s", (uid,))
            summary["ai_events"] = int(cur.rowcount or 0)
            summary["cleaned"]["ai_usage_events"] = summary["ai_events"]

            # --- 5) Kanal ulanishlari: soft-delete + anonimlashtirish ---
            cur.execute(
                """
                UPDATE channels
                   SET is_active = FALSE, channel_title = NULL,
                       deleted_at = NOW()
                 WHERE user_id = %s
                """,
                (uid,),
            )
            summary["cleaned"]["channels_soft_deleted"] = int(cur.rowcount or 0)

            # --- 6) Hisob: soft-delete + anonimlashtirish ---
            cur.execute(
                """
                UPDATE users
                   SET username = NULL, full_name = NULL, referrer_id = NULL,
                       ai_credits = 0, role = 'user', language_code = 'uz',
                       last_active_at = NULL, deleted_at = NOW()
                 WHERE user_id = %s
                """,
                (uid,),
            )
            summary["cleaned"]["users_anonymized"] = int(cur.rowcount or 0)

            # --- 7) Audit izi (self-service: actor = foydalanuvchining o'zi) ---
            cur.execute(
                """
                INSERT INTO admin_audit_logs
                    (admin_id, action, target_type, target_id, ip_or_metadata)
                VALUES (%s, 'user_data_deleted', 'user', %s, %s::jsonb)
                """,
                (uid, str(uid), json.dumps({
                    "self_service": True,
                    "channels": summary["channels"],
                    "posts": summary["posts"],
                    "ai_events": summary["ai_events"],
                    "retained": list(ACCOUNT_DELETE_RETAINED_TABLES),
                }, ensure_ascii=False)),
            )

        # Kesh tozalash — tranzaksiya COMMIT bo'lgach (eskirgan profil qolmasin).
        _invalidate_user(uid)
        try:
            _cache_clear("user_lang")
        except Exception as cache_exc:  # noqa: BLE001
            logger.warning(
                "delete_user_data: kesh tozalanmadi (user=%s): %s", uid, cache_exc)
        return summary
    except Exception as exc:  # noqa: BLE001 — handler'ga xavfsiz xabar qaytadi
        logger.error(
            "delete_user_data xatosi (user=%s): %s", uid, exc, exc_info=True)
        return {"ok": False, "reason": "db_error", "user_id": uid}
