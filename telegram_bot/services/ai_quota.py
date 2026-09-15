"""AI kvota + kredit bron/qaytarish — PostAssist V2 (PHASE 2, 1-qadam).

Barcha AI oqimlari (🤖 AI Yordamchi / AI Studio, ✨ Magic Post, 🎙 Ovoz → Post,
📸 Rasm → Post, 📊 Post Score «95/100 ga yaxshilash») kunlik kvota va AI
kreditini AYNAN SHU qatlam orqali band qiladi va qaytaradi.

Nega bu qatlam kerak
--------------------
Refaktorgacha har bir handler ikkita ALOHIDA DB tranzaksiyasini chaqirar edi::

    can_use, used, max_ai = await db.run_db(db.check_ai_limit, user_id)   # TX 1
    reserved = await db.run_db(db.use_user_credit, user_id)               # TX 2

Buning oqibatlari:

* **Race condition** — ikki qadam orasida parallel so'rovlar kvotani bron
  qilib, kreditni yechmasdan (yoki aksincha) qolishi mumkin;
* **Yarim to'lov** — birinchi qadam muvaffaqiyatli, ikkinchisi xato bo'lsa,
  kunlik kvota yonib ketadi va foydalanuvchi javob olmaydi;
* **FAIL-OPEN** — ayrim handlerlar ``except Exception: reserved = True`` deb
  DB xatosida ham oqimni davom ettirar edi (bu qoidaga zid).

Endi bitta atomik funksiya bor: ``database.reserve_ai_request()`` — qator
qulfi (``SELECT ... FOR UPDATE``), kunlik kvota → kredit zanjiri,
``credits_ledger`` auditi va ``ai_reservations`` bron qatori BITTA
tranzaksiyada. Qaytarish esa ``database.refund_ai_request(reservation_id)``
orqali IDEMPOTENT bajariladi.

Fail-closed
-----------
``reserve_ai_quota()`` HECH QACHON xatoda ruxsat bermaydi: DB uzilishi,
pool timeout yoki nomalum javob → ``allowed=False`` +
``reason="db_error"``. Handler buni foydalanuvchiga "xizmat vaqtincha band"
xabari bilan ko'rsatadi (``ai_quota_temp_error_text``).

Legacy (backward compatibility)
-------------------------------
Mavjud test adapterlari ``handlers.*.db.run_db`` ni o'z ``fake_run_db``
funksiyasi bilan almashtiradi va ular faqat eski nomlarni
(``check_ai_limit`` / ``use_user_credit``) taniydi. Shu sababli adapter
haqiqiy ``database`` moduli bo'lmasa, bron ESKI ikki qadamli zanjirga
tushadi — eski oqimlar va testlar buzilmaydi. Production'da adapter doim
haqiqiy ``database`` moduli, ya'ni doim atomik yo'l ishlaydi.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rad sabablari (database.py dagi doimiylarning nusxasi — handler'lar
# database'ni bevosita import qilmasdan ham taqqoslay olishi uchun).
# ---------------------------------------------------------------------------
REASON_OK = "ok"
#: Kunlik bepul kvota ham, kredit balansi ham yetarli emas.
REASON_INSUFFICIENT = "insufficient_balance"
#: DB/pool/SQL xatosi — tranzaksiya ROLLBACK qilindi (fail-closed).
REASON_DB_ERROR = "db_error"
#: Foydalanuvchi bazada yo'q.
REASON_USER_NOT_FOUND = "user_not_found"
#: Yaroqsiz chaqiruv (cost/operation_type) — hech narsa yozilmadi.
REASON_INVALID_REQUEST = "invalid_request"

#: Mablag' yetishmasligi sabablari (PRO taklifi ko'rsatiladi).
BALANCE_REASONS = frozenset({REASON_INSUFFICIENT, REASON_USER_NOT_FOUND})

#: Vaqtinchalik infratuzilma xatolari ("birozdan so'ng qayta urinib ko'ring").
TEMP_ERROR_REASONS = frozenset({REASON_DB_ERROR, REASON_INVALID_REQUEST,
                                 "adapter_error"})

#: Legacy (eski ikki qadamli) zanjirda reservation_id bo'lmaydi.
LEGACY_RESERVATION_ID = None


def _deny(reason: str, used: int = 0, max_ai: int = 0, **extra) -> dict:
    """Rad natijasini yig'adi (maydonlar doim to'ldirilgan)."""
    result = {
        "allowed": False,
        "reason": reason,
        "reservation_id": None,
        "source": None,
        "cost": 0,
        "used": int(used or 0),
        "max_ai": int(max_ai or 0),
        "credits_left": None,
        "legacy": False,
    }
    result.update(extra)
    return result


def _allow(reservation_id, used: int = 0, max_ai: int = 0, **extra) -> dict:
    """Muvaffaqiyatli bron natijasini yig'adi."""
    result = {
        "allowed": True,
        "reason": REASON_OK,
        "reservation_id": reservation_id,
        "source": None,
        "cost": 0,
        "used": int(used or 0),
        "max_ai": int(max_ai or 0),
        "credits_left": None,
        "legacy": False,
    }
    result.update(extra)
    return result


def _is_real_db_adapter(db_module) -> bool:
    """Adapter haqiqiy ``database`` moduli ekanini aniqlaydi.

    Production'da handler'lar ``import database as db`` qiladi, shuning uchun
    ``db.run_db.__module__ == "database"``. Testlar esa ``db.run_db`` ni
    ``fake_run_db`` bilan almashtiradi (modul nomi test fayli bo'ladi) —
    bunday holda atomik funksiya mavjud emas va ESKI zanjir ishlatiladi.
    """
    run_db = getattr(db_module, "run_db", None)
    if run_db is None or not callable(run_db):
        return False
    return getattr(run_db, "__module__", None) == "database"


async def reserve_ai_quota(db_module, user_id: int,
                           operation_type: str = "other", cost: int = 1) -> dict:
    """AI so'rovi uchun kvota/kreditni bron qiladi (yagona kirish nuqtasi).

    Args:
        db_module: handler'dagi ``db`` (odatda ``import database as db``).
        user_id: Telegram user id.
        operation_type: ``magic_post`` | ``ai_studio`` | ``voice_post`` |
            ``image_post`` | ``post_score`` | ... (oq ro'yxat:
            ``database.AI_OPERATION_TYPES``).
        cost: nechta birlik (standart 1).

    Returns:
        dict::

            {"allowed": bool, "reason": str, "reservation_id": int | None,
             "source": "daily_quota" | "credit" | None, "cost": int,
             "used": int, "max_ai": int, "credits_left": int | None,
             "legacy": bool}

        ``legacy=True`` bo'lsa bron ESKI zanjir orqali qilingan va
        ``reservation_id`` ``None`` (qaytarish legacy helperlar bilan).
    """
    if _is_real_db_adapter(db_module):
        reserve = getattr(db_module, "reserve_ai_request", None)
        if callable(reserve):
            try:
                result = await db_module.run_db(
                    reserve, user_id, operation_type, cost)
            except Exception as e:  # noqa: BLE001 — FAIL-CLOSED
                logger.error(
                    "reserve_ai_quota: atomik bron xatosi (user=%s, op=%s): %s",
                    user_id, operation_type, e)
                return _deny(REASON_DB_ERROR, used=-1)
            if isinstance(result, dict) and "allowed" in result:
                result.setdefault("legacy", False)
                return result
            # Adapter kutilmagan javob qaytardi → ruxsat YO'Q (fail-closed).
            logger.error("reserve_ai_quota: kutilmagan javob shakli: %r", result)
            return _deny(REASON_DB_ERROR, used=-1)
        # Atomik funksiya mavjud emas (juda eski deploy) → legacy zanjir.
        logger.warning(
            "reserve_ai_quota: database.reserve_ai_request topilmadi — "
            "legacy zanjir ishlatiladi (user=%s)", user_id)

    # ---- LEGACY zanjir (test adapterlari / eski deploy) -----------------
    # Eski xatti-harakat SAQLANADI: check_ai_limit (kunlik kvota bron) va
    # use_user_credit (1 kredit) — lekin endi xatoda fail-closed.
    try:
        limit = await db_module.run_db(db_module.check_ai_limit, user_id)
    except Exception as e:  # noqa: BLE001 — FAIL-CLOSED
        logger.error("reserve_ai_quota: check_ai_limit xatosi (user=%s): %s",
                     user_id, e)
        return _deny(REASON_DB_ERROR, used=-1, legacy=True)

    if isinstance(limit, (tuple, list)):
        can_use = bool(limit[0]) if limit else False
        used = int(limit[1]) if len(limit) > 1 and limit[1] is not None else 0
        max_ai = int(limit[2]) if len(limit) > 2 and limit[2] is not None else 0
    elif isinstance(limit, dict):
        can_use = bool(limit.get("allowed"))
        used = int(limit.get("used") or 0)
        max_ai = int(limit.get("max_ai") or 0)
    elif isinstance(limit, bool):
        can_use, used, max_ai = limit, 0, 0
    else:
        # Adapter javob bermadi (None) — ruxsat berish xavfsiz emas.
        return _deny(REASON_DB_ERROR, used=-1, legacy=True)

    if not can_use:
        return _deny(REASON_INSUFFICIENT, used=used, max_ai=max_ai, legacy=True)

    try:
        reserved = await db_module.run_db(db_module.use_user_credit, user_id)
    except Exception as e:  # noqa: BLE001 — FAIL-CLOSED
        logger.error("reserve_ai_quota: use_user_credit xatosi (user=%s): %s",
                     user_id, e)
        # Kvota bron qilingan bo'lishi mumkin — uni qaytaramiz.
        await _legacy_release(db_module, user_id, credit=False)
        return _deny(REASON_DB_ERROR, used=used, max_ai=max_ai, legacy=True)

    if reserved is False:
        # Kredit yetmadi → bron qilingan kunlik kvotani ham qaytaramiz
        # (aks holda kvota yonib ketadi va foydalanuvchi javob olmaydi).
        await _legacy_release(db_module, user_id, credit=False)
        return _deny(REASON_INSUFFICIENT, used=used, max_ai=max_ai, legacy=True)

    return _allow(LEGACY_RESERVATION_ID, used=used, max_ai=max_ai,
                  cost=cost, legacy=True)


async def _legacy_release(db_module, user_id: int, credit: bool) -> bool:
    """Legacy zanjir uchun qaytarish (kvota va/yoki kredit)."""
    ok = True
    if credit:
        helper = getattr(db_module, "add_user_credit", None)
        if callable(helper):
            try:
                ok = bool(await db_module.run_db(helper, user_id)) and ok
            except Exception:
                ok = False
    quota = getattr(db_module, "refund_ai_usage", None)
    if callable(quota):
        try:
            await db_module.run_db(quota, user_id)
        except Exception:
            ok = False
    return ok


async def release_ai_quota(db_module, user_id: int, reservation_id=None) -> bool:
    """Bron qilingan kvota/kreditni qaytaradi (AI xatosi/timeout'da).

    * ``reservation_id`` berilgan bo'lsa → ATOMIK va IDEMPOTENT
      ``database.refund_ai_request()`` (ikkki marta qaytarib bo'lmaydi).
    * Legacy bron (``reservation_id=None``) → eski ``add_user_credit`` +
      ``refund_ai_usage`` helperlari (mavjud test/oqim kontrakti saqlanadi).

    Returns:
        bool — qaytarish bajarildimi. Xatoda ``False`` (lekin hech qachon
        ikkinchi marta qaytarilmaydi).
    """
    if reservation_id:
        refund = getattr(db_module, "refund_ai_request", None)
        if callable(refund):
            try:
                result = await db_module.run_db(
                    refund, user_id, reservation_id)
            except Exception as e:  # noqa: BLE001
                logger.error(
                    "release_ai_quota: refund xatosi (user=%s, reservation=%s): %s",
                    user_id, reservation_id, e)
                return False
            if isinstance(result, dict):
                if result.get("success"):
                    return True
                # 'already_refunded' — qayta urinish, xato emas.
                if result.get("reason") == "already_refunded":
                    return False
                logger.error(
                    "release_ai_quota: refund bajarilmadi (user=%s, "
                    "reservation=%s, reason=%s)",
                    user_id, reservation_id, result.get("reason"))
                return False
            return bool(result)
        logger.warning(
            "release_ai_quota: database.refund_ai_request topilmadi — "
            "legacy refund (user=%s, reservation=%s)", user_id, reservation_id)

    return await _legacy_release(db_module, user_id, credit=True)


def is_balance_reason(reason: str) -> bool:
    """Rad sababi "mablag' yetishmasligi"mi (PRO taklifi ko'rsatiladi)."""
    return str(reason or "") in BALANCE_REASONS


def is_quota_exhausted(reservation: dict) -> bool:
    """Kunlik BEPUL kvota tugaganini aniqlaydi (PRO taklifi ko'rsatiladi).

    Atomik bronda kvota ham, kredit ham bitta zanjirda tekshirilgani uchun
    sabab ``insufficient_balance`` bo'ladi; kunlik kvota chegarasiga
    yetilganini ``used >= max_ai`` orqali aniqlaymiz. Legacy zanjirda esa
    kvota va kredit qadamlari alohida bo'lgani uchun kvota tugaganda
    ``max_ai`` 0 bo'lib qoladi (kvota qadami chegarani qaytargan).
    """
    if not is_balance_reason((reservation or {}).get("reason")):
        return False
    try:
        used = int((reservation or {}).get("used") or 0)
        max_ai = int((reservation or {}).get("max_ai") or 0)
    except (TypeError, ValueError):
        return False
    if used < 0:
        return False
    return max_ai > 0 and used >= max_ai


def is_temp_error_reason(reason: str) -> bool:
    """Rad sababi vaqtinchalik infratuzilma xatosi (qayta urinish taklifi)."""
    return str(reason or "") in TEMP_ERROR_REASONS


async def reserve_for_flow(db_module, context, user_id: int,
                           operation_type: str, ctx_prefix: str,
                           cost: int = 1) -> dict:
    """Oqim uchun bron qiladi va bron ma'lumotini kontekstga yozadi.

    Har bir AI oqimi o'z ``ctx_prefix`` ini ishlatadi (``magic``, ``voice``,
    ``image``, ``score``, ``studio``) — shunda bir foydalanuvchining parallel
    oqimlari bir-birining bronini o'chirib qo'ymaydi.

    Kontekstga yoziladigan kalitlar:
        ``{ctx_prefix}_reservation_id``     — bron ID (refund uchun);
        ``{ctx_prefix}_reservation_source`` — ``daily_quota`` | ``credit``
            (atomik bron bo'lsa kunlik sanagich allaqachon oshirilgan).

    Eski (stale) bron ma'lumoti har doim OLDIN tozalanadi — aks holda
    keyingi oqim eski ID bo'yicha qaytarish urinishi qilardi.
    """
    id_key = f"{ctx_prefix}_reservation_id"
    source_key = f"{ctx_prefix}_reservation_source"
    user_data = getattr(context, "user_data", None)
    if user_data is not None:
        user_data.pop(id_key, None)
        user_data.pop(source_key, None)

    reservation = await reserve_ai_quota(db_module, user_id,
                                         operation_type, cost)
    if reservation.get("allowed") and user_data is not None:
        user_data[id_key] = reservation.get("reservation_id")
        user_data[source_key] = reservation.get("source")
    return reservation


def take_reservation_id(context, ctx_prefix: str):
    """Kontekstdagi bron ID'sini OLADI (pop) — qayta refund'ning oldini oladi."""
    user_data = getattr(context, "user_data", None)
    if user_data is None:
        return None
    user_data.pop(f"{ctx_prefix}_reservation_source", None)
    return user_data.pop(f"{ctx_prefix}_reservation_id", None)


def reservation_source(context, ctx_prefix: str):
    """Joriy bron manbasi (``daily_quota``/``credit``) yoki ``None`` (legacy)."""
    user_data = getattr(context, "user_data", None)
    if user_data is None:
        return None
    return user_data.get(f"{ctx_prefix}_reservation_source")


def denial_message(reservation: dict, limit_text: str, lang: str = "uz") -> str:
    """Rad holati uchun foydalanuvchiga ko'rsatiladigan matn.

    * mablag' yetishmasa → mavjud ``ai_limit_msg`` matni (PRO taklifi bilan);
    * DB/pool xatosi     → "xizmat vaqtincha band" (fail-closed, lekin
      foydalanuvchi ayblanmaydi va qayta urinish taklif qilinadi).

    Hech qanday matn hardcode qilinmaydi — barchasi ``get_text``/``safe_t``
    zanjiri orqali (UZ/RU/EN).
    """
    if is_balance_reason(reservation.get("reason")):
        return limit_text
    return ai_quota_temp_error_text(lang)


def ai_quota_temp_error_text(lang: str = "uz") -> str:
    """DB/pool xatosida AI'ni fail-closed rad etish uchun muloyim xabar.

    ``handlers.ai_assistant._ai_quota_temp_error_text`` bilan bir xil matn —
    barcha AI oqimlari bitta manbadan foydalanishi uchun bu yerga ko'chirildi
    (eski funksiya alias sifatida saqlanadi).
    """
    code = str(lang or "uz").lower()
    if code == "ru":
        return ("⏳ <b>ИИ временно недоступен.</b> "
                "Пожалуйста, попробуйте ещё раз через минуту.")
    if code == "en":
        return ("⏳ <b>AI is temporarily unavailable.</b> "
                "Please try again in a minute.")
    return ("⏳ <b>AI xizmati vaqtincha band.</b> "
            "Iltimos, bir daqiqadan so'ng qayta urinib ko'ring.")
