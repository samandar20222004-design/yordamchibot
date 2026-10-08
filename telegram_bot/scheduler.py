import asyncio
import json
import logging
import os
import random
import re
from datetime import date, datetime, timedelta
import pytz
from telegram import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
    InputMediaAudio,
)
from telegram.error import TelegramError, RetryAfter, TimedOut, NetworkError
from config import (
    ADMIN_IDS_SET,
    BOT_USERNAME,
    QUIET_STAGGER_MIN_SECONDS,
    QUIET_STAGGER_MAX_SECONDS,
    CHANNEL_STAGGER_MIN_SECONDS,
)
import database as db
from services.delivery import delivery_service
from services import lifecycle_service as lifecycle
from services import event_tracker
from services.cleanup_service import cleanup_old_records
from keyboards.inline import (
    normalize_custom_reaction_emojis,
    strip_leading_reaction_glyphs,
    DEFAULT_REACTION_EMOJIS,
)
from keyboards.callback_data import CB_REACTION, cb
from utils.telegram_sanitizer import (
    sanitize_html, html_length, utf16_length, has_allowed_html, truncate_text,
    TELEGRAM_TEXT_LIMIT, TELEGRAM_CAPTION_LIMIT,
)
from utils.helpers import (
    get_channel_ad_next_full_async,
    should_show_channel_ad,
    apply_post_watermark,
    telegram_html_payload,
)

logger = logging.getLogger(__name__)

# ⏰ BUTUN BOT UCHUN YAGONA VAQT ZONASI — Toshkent (UTC+5).
# Barcha sana/vaqt hisob-kitoblari, APScheduler triggerlari va DB'ga
# yoziladigan `scheduled_time` qiymatlari SHU zonaga bog'lanadi.
TIMEZONE_NAME = "Asia/Tashkent"
tashkent_tz = pytz.timezone(TIMEZONE_NAME)

# Tarmoq xatosidan keyin qayta urinishdan oldin kutish (soniya)
NETWORK_RETRY_DELAY = 30

# --- Telegram FloodWait (429) himoyasi -------------------------------------
# Postlar orasidagi mikro-kechikish: Telegram bir xil botdan ketma-ket
# kelayotgan yuborishlarni 429 (Too Many Requests) bilan bloklab qo'ymasligi
# uchun har post orasiga juda kichik pauza qo'yiladi.
SEND_MICRO_DELAY_MIN = 0.05
SEND_MICRO_DELAY_MAX = 0.1
SEND_MICRO_DELAY = 0.08  # soniya — 0.05..0.1 oralig'ida

# Quiet Hours tugashi (08:00) uchun thundering-herd himoyasi. Bir tickda
# 08:00:00 ga yig'ilgan postlar DB navbatida 30..180 soniyalik oynalar bilan
# tarqatiladi. Bir kanal postlari orasidagi qat'iy minimum — 60 soniya.
QUIET_HERD_HOUR = 8
# Config qiymatlari yuqoridan olinadi; runtime'da haddan tashqari keng
# oynani qabul qilmaslik uchun yuqori cap saqlanadi.
QUIET_STAGGER_MIN_SECONDS = min(QUIET_STAGGER_MIN_SECONDS, 3600.0)
QUIET_STAGGER_MAX_SECONDS = min(max(QUIET_STAGGER_MIN_SECONDS, QUIET_STAGGER_MAX_SECONDS), 3600.0)
CHANNEL_STAGGER_MIN_SECONDS = min(CHANNEL_STAGGER_MIN_SECONDS, 3600.0)

# Telegram RetryAfter bergan kanal Telegram aytgan muddatdan keyin ham kichik
# xavfsizlik buferi davomida muzlatiladi.
FLOOD_WAIT_SAFETY_SECONDS = 5.0

# FloodWait kutishining yuqori chegarasi: Telegram juda katta `retry_after`
# qaytarsa (masalan 900s) scheduler ishini butunlay muzlatib qo'ymaymiz —
# shu chegaragacha kutamiz, qolganini `retry_post` orqali DB'ga ko'chiramiz.
FLOOD_WAIT_SLEEP_MAX = 60.0

# 11-bosqich (P0): FloodWait butun schedulerni BLOKLAMAYDI. Tick ichida
# real kutish faqat shu chegaragacha (soniya); qolgan muddat DB'da
# (``retry_post``) — aynan shu post uchun kechiktiriladi, qolgan kanallar
# navbatdagi postlari davom etadi.
FLOOD_WAIT_INLINE_SLEEP_MAX = 5.0

# Kanal bo'yicha FloodWait "sovutish" jadvali: {channel_id: monotonic_until}.
# Telegram 429 qaytargan kanalga shu muddat ichida boshqa post yuborilmaydi
# (ular ham DB'da kechiktiriladi) — limit uzayib ketmasligi uchun.
_CHANNEL_FLOOD_UNTIL: dict = {}

# UNKNOWN_DELIVERY (P0): albom (media group) yuborishda TimedOut/NetworkError
# bo'lsa Telegram xabarni qabul qilgan bo'lishi mumkin — qayta yuborish
# dublikat albom chiqaradi. Bunday postlar 'unknown' bo'ladi va avtomatik
# qayta yuborilmaydi (admin health panelida ko'rinadi).
UNKNOWN_DELIVERY = "unknown"

# Avto-o'chirishda vaqtinchalik xatodan keyin qayta urinish (soniya).
AUTO_DELETE_RETRY_DELAY = 300

# --- IDEMPOTENT YUBORISH: "yuborildi" markeri kafolati -----------------------
# post_deliveries Telegram delivery'sining asosiy, doimiy source-of-truth'i.
# Post Telegramga chiqqach delivery status='sent' + message_id yozilishi SHART;
# scheduled_posts markerining retry mexanizmi esa shu yozuvni yakunlaydi.
# ``_UNPERSISTED_SENT`` faqat DB qisqa uzilganda shu jarayon ichida qayta
# yuborishni to'suvchi best-effort legacy fallback; normal holatda vaqtinchalik
# JSON journal ishlatilmaydi.
SENT_MARKER_RETRY_DELAYS = (0.5, 1.0, 2.0, 4.0)


def _resolve_sent_journal_path() -> str:
    """Legacy SENT_JOURNAL_PATH opt-in yo'lini o'qiydi.

    Berilmaganida bo'sh qaytadi: P0 delivery markerlari DB'da saqlanadi.
    """
    raw = os.getenv("SENT_JOURNAL_PATH")
    if raw is None:
        # P0: normal operation no longer depends on a temporary JSON journal;
        # post_deliveries is the source of truth. Explicit path remains as a
        # legacy/test-only escape hatch for old deployments.
        return ""
    raw = raw.strip()
    if raw.lower() in ("", "off", "none", "0", "false"):
        return ""
    return raw


SENT_JOURNAL_PATH = _resolve_sent_journal_path()
_UNPERSISTED_SENT: dict = {}   # post_id -> marker (DB'ga hali yozilmagan "yuborildi" faktlari)
_journal_loaded = False


def _journal_load() -> None:
    """Journal faylini (bo'lsa) bir marta xotiraga yuklaydi."""
    global _journal_loaded
    if _journal_loaded:
        return
    _journal_loaded = True
    if not SENT_JOURNAL_PATH:
        return
    try:
        if not os.path.isfile(SENT_JOURNAL_PATH):
            return
        with open(SENT_JOURNAL_PATH, encoding="utf-8") as fh:
            data = json.load(fh) or {}
        loaded = 0
        for key, marker in data.items():
            try:
                pid = int(key)
            except (TypeError, ValueError):
                continue
            if isinstance(marker, dict):
                _UNPERSISTED_SENT.setdefault(pid, marker)
                loaded += 1
        if loaded:
            logger.warning(
                "Sent-journal: %d ta post Telegramga yuborilgan, lekin DB markeri yozilmagan — "
                "qayta yuborilmaydi, marker keyingi tick'da yoziladi.", loaded,
            )
    except Exception:
        logger.exception("Sent-journal o'qishda xato (%s)", SENT_JOURNAL_PATH)


def _journal_save() -> None:
    """Xotiradagi ro'yxatni journal fayliga atomik yozadi (bo'sh bo'lsa faylni o'chiradi)."""
    if not SENT_JOURNAL_PATH:
        return
    try:
        if not _UNPERSISTED_SENT:
            if os.path.isfile(SENT_JOURNAL_PATH):
                os.remove(SENT_JOURNAL_PATH)
            return
        tmp = SENT_JOURNAL_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({str(k): v for k, v in _UNPERSISTED_SENT.items()}, fh, ensure_ascii=False)
        os.replace(tmp, SENT_JOURNAL_PATH)
    except Exception:
        logger.exception("Sent-journal yozishda xato (%s)", SENT_JOURNAL_PATH)


def _db_ok(result) -> bool:
    """DB yozuv natijasi: faqat aniq ``False`` — xato. ``None``/``True`` — muvaffaqiyat
    (eski yoki soxta (test) funksiyalar ``None`` qaytaradi)."""
    return result is not False


def _build_sent_marker(post_id, sent_msg_id, channel_id, delete_after_hours, extra_ids,
                       recurrence_type=None, recurrence_day=None, recurrence_time=None,
                       end_date=None, idempotency_key=None) -> dict:
    """Telegramga yuborilgan post uchun DB'ga yozilishi kerak bo'lgan barcha
    ma'lumot (JSON-serializable): 'posted' markeri + takrorlanuvchi post uchun
    keyingi vaqt / yakunlanganlik."""
    marker = {
        "post_id": int(post_id),
        "message_id": int(sent_msg_id) if sent_msg_id else None,
        "channel_id": str(channel_id) if channel_id is not None else None,
        "delete_after_hours": int(delete_after_hours or 0),
        "extra_ids": [int(x) for x in (extra_ids or []) if x],
        "next_time": None,
        "completed": False,
        "marker_done": False,
        "delivery_key": idempotency_key,
        "delivery_done": False,
        "sent_at": now_tashkent().isoformat(),
    }
    if recurrence_type in ("daily", "weekly"):
        try:
            now = now_tashkent()
            if end_date and _as_tashkent(end_date) and now >= _as_tashkent(end_date):
                marker["completed"] = True
            else:
                next_time = calculate_next_time(recurrence_type, recurrence_day, recurrence_time, now)
                if next_time:
                    marker["next_time"] = next_time.isoformat()
        except Exception:
            logger.exception("Takrorlanuvchi post uchun keyingi vaqtni hisoblashda xato (Post ID: %s)", post_id)
    return marker


async def _apply_sent_marker(marker: dict) -> bool:
    """Markerni DB'ga yozishga BIR marta urinadi. ``True`` — hammasi yozildi.

    Bosqichlar idempotent: 'posted' markeri yozilgach ``marker_done`` belgilanadi,
    keyingi urinishlar faqat qolgan qismini (takrorlash) bajaradi."""
    pid = int(marker["post_id"])
    # post_deliveries — yangi asosiy idempotency marker. Legacy markerlarda
    # delivery_key yo'q, shuning uchun eski restart oqimi ham saqlanadi.
    delivery_key = marker.get("delivery_key")

    # 11-bosqich (P0): 'posted' (scheduled_posts) + 'sent' (post_deliveries)
    # BITTA atomik tranzaksiyada yoziladi — Telegram'ga chiqqan post DB'da
    # darhol va bo'linmas holda "yuborildi" bo'ladi. Crash bo'lsa ham ikkala
    # marker birga yoki umuman yozilmaydi (ikkinchi holatda in-memory guard
    # va flush qayta yozadi; post QAYTA YUBORILMAYDI).
    if not marker.get("marker_done"):
        ok = False
        try:
            ok = _db_ok(await db.run_db(
                db.mark_post_as_sent, pid, marker.get("message_id"), marker.get("channel_id"),
                int(marker.get("delete_after_hours") or 0), marker.get("extra_ids") or None,
                delivery_key,
            ))
            if ok and delivery_key:
                marker["delivery_done"] = True
        except TypeError:
            # Legacy/fake adapter: delivery_key parametrini bilmaydi —
            # eski ikki bosqichli oqim (avval delivery, keyin posted).
            ok = await _apply_sent_marker_legacy(marker)
            if not ok:
                return False
        except Exception as e:
            logger.exception(
                "Post Telegramga yuborildi (Msg ID: %s), lekin DB ga 'posted' deb belgilashda xatolik (Post ID: %s): %s",
                marker.get("message_id"), pid, e,
            )
        if not ok:
            # Zaxira: hech bo'lmaganda statusni 'posted' qilamiz (qayta yuborilmasin)
            try:
                ok = _db_ok(await db.run_db(db.mark_post_status, pid, "posted"))
            except Exception:
                ok = False
        if not ok:
            return False
        marker["marker_done"] = True

    if delivery_key and not marker.get("delivery_done"):
        # Atomik yozuv delivery'ni qamrab olmagan bo'lsa (legacy adapter) —
        # alohida idempotent 'sent' markeri.
        delivery_ok = False
        try:
            delivery_ok = _db_ok(await db.run_db(
                delivery_service.mark_sent_by_key, delivery_key, marker.get("message_id")
            ))
        except Exception as e:
            logger.exception("Delivery sent marker yozilmadi (Post ID: %s): %s", pid, e)
        if not delivery_ok:
            return False
        marker["delivery_done"] = True

    next_time_raw = marker.get("next_time")
    try:
        if next_time_raw:
            next_time = datetime.fromisoformat(next_time_raw)
            if not _db_ok(await db.run_db(db.reschedule_recurring_post, pid, next_time)):
                return False
            if not _db_ok(await db.run_db(db.mark_post_status, pid, "pending")):
                return False
        elif marker.get("completed"):
            if not _db_ok(await db.run_db(db.mark_post_status, pid, "completed")):
                return False
    except Exception as e:
        logger.exception("Takrorlanuvchi postni qayta rejalashtirishda xato (Post ID: %s): %s", pid, e)
        return False
    return True


async def _apply_sent_marker_legacy(marker: dict) -> bool:
    """Eski adapterlar uchun ikki bosqichli marker (delivery → posted)."""
    pid = int(marker["post_id"])
    delivery_key = marker.get("delivery_key")
    if delivery_key and not marker.get("delivery_done"):
        try:
            if not _db_ok(await db.run_db(
                delivery_service.mark_sent_by_key, delivery_key, marker.get("message_id")
            )):
                return False
        except Exception as e:
            logger.exception("Delivery sent marker yozilmadi (Post ID: %s): %s", pid, e)
            return False
        marker["delivery_done"] = True
    try:
        return _db_ok(await db.run_db(
            db.mark_post_as_sent, pid, marker.get("message_id"), marker.get("channel_id"),
            int(marker.get("delete_after_hours") or 0), marker.get("extra_ids") or None,
        ))
    except Exception as e:
        logger.exception("'posted' markeri yozilmadi (Post ID: %s): %s", pid, e)
        return False


async def _persist_sent_marker(marker: dict, retry_delays=SENT_MARKER_RETRY_DELAYS) -> bool:
    """Yuborilgan post markerini DB'ga yozadi — backoff bilan qayta urinib.

    Marker AVVAL xotira/journalga tushadi (send va DB yozuvi orasidagi crash
    ham post faktini yo'qotmasin), muvaffaqiyatdan keyin o'chiriladi. Hech
    qachon istisno tashlamaydi: yozilmasa ``False`` — post keyingi tick'da
    ``flush_unpersisted_sent_markers`` orqali to'g'rilanadi."""
    pid = int(marker["post_id"])
    _UNPERSISTED_SENT[pid] = marker
    _journal_save()
    attempt = 0
    while True:
        try:
            done = await _apply_sent_marker(marker)
        except Exception:
            logger.exception("Sent-marker yozishda kutilmagan xato (Post ID: %s)", pid)
            done = False
        if done:
            _UNPERSISTED_SENT.pop(pid, None)
            _journal_save()
            return True
        if attempt >= len(retry_delays):
            logger.error(
                "Post %s Telegramga yuborildi, lekin DB markeri yozilmadi — journalda saqlandi; "
                "post QAYTA YUBORILMAYDI, marker keyingi tick'da qayta uriniladi.", pid,
            )
            _journal_save()
            return False
        delay = retry_delays[attempt]
        attempt += 1
        logger.warning(
            "Post %s: DB markerini yozishda vaqtinchalik xato, %.1fs dan keyin qayta uriniladi (%d/%d)",
            pid, delay, attempt, len(retry_delays),
        )
        await asyncio.sleep(delay)


async def flush_unpersisted_sent_markers() -> int:
    """Har tick boshida: yozilmay qolgan "yuborildi" markerlarini DB'ga yozishga urinadi.

    ``get_due_posts`` dan OLDIN chaqiriladi — stale-recovery 'pending' ga qaytargan
    post yana olinishidan avval 'posted' ga qaytariladi. Qaytaradi: yozilganlar soni."""
    _journal_load()
    if not _UNPERSISTED_SENT:
        return 0
    done = 0
    for pid in list(_UNPERSISTED_SENT):
        marker = _UNPERSISTED_SENT.get(pid)
        if not marker:
            _UNPERSISTED_SENT.pop(pid, None)
            continue
        try:
            if await _apply_sent_marker(marker):
                _UNPERSISTED_SENT.pop(pid, None)
                done += 1
        except Exception:
            logger.exception("Sent-marker flush xatosi (Post ID: %s)", pid)
    _journal_save()
    if done:
        logger.info("Sent-marker flush: %d ta post markeri DB'ga yozildi.", done)
    return done


def is_sent_but_unpersisted(post_id) -> bool:
    """Post Telegramga yuborilgan-u, DB markeri hali yozilmaganmi (qayta yuborish taqiqlanadi)."""
    _journal_load()
    try:
        return int(post_id) in _UNPERSISTED_SENT
    except (TypeError, ValueError):
        return False


def flood_wait_seconds(error, default: float = 5.0) -> float:
    """``RetryAfter`` xatosidan xavfsiz kutish muddatini (soniya) chiqaradi.

    Telegram ba'zan ``retry_after`` ni ``None``/``0``/``str`` ko'rinishida
    qaytaradi — hech qanday holatda ``TypeError`` bo'lmasligi kerak.
    Natija ``[1.0, FLOOD_WAIT_SLEEP_MAX]`` oralig'ida cheklanadi.
    """
    raw = getattr(error, "retry_after", None)
    try:
        value = float(raw) if raw is not None else float(default)
    except (TypeError, ValueError):
        value = float(default)
    if value <= 0:
        value = float(default)
    return max(1.0, min(value, FLOOD_WAIT_SLEEP_MAX))


def flood_wait_inline_sleep(wait_seconds: float) -> float:
    """Tick ichida REAL kutiladigan muddat (qolgani DB'da kechiktiriladi)."""
    try:
        value = float(wait_seconds)
    except (TypeError, ValueError):
        value = 1.0
    return max(0.0, min(value, FLOOD_WAIT_INLINE_SLEEP_MAX))


def _channel_key(channel_id) -> str:
    return str(channel_id) if channel_id is not None else ""


async def _delivery_send(bot, method: str, **kwargs):
    """YAGONA delivery engine orqali Telegram yuborish (PHASE 5).

    Barcha kanal postlari ``services.delivery`` dvigatelidan o'tadi:
    1 post/s (kanal) + 30 msg/s (umumiy) rate-limit, RetryAfter tasnifi va
    dead-letter klassifikatsiyasi shu yerda. Scheduler ``defer`` rejimini
    tanlaydi (``inline_max_wait=0``): dvigatel 429 da inline kutmaydi —
    aniq kutish + jitter DB'dagi ``retry_post``/kanal sovutishida
    (``flood_wait_seconds`` + jitter) boshqariladi, shu bilan navbat
    hech qachon muzmaydi va dublikat chiqmaydi.
    """
    return await delivery_service.execute(bot, method, inline_max_wait=0.0, **kwargs)


def mark_channel_flood(channel_id, wait_seconds: float) -> None:
    """Kanalni ``wait_seconds`` davomida FloodWait sovutishiga qo'yadi."""
    try:
        wait = max(1.0, float(wait_seconds))
    except (TypeError, ValueError):
        wait = 1.0
    import time as _t
    _CHANNEL_FLOOD_UNTIL[_channel_key(channel_id)] = _t.monotonic() + wait


def channel_flood_remaining(channel_id) -> float:
    """Kanal hali FloodWait sovutishida bo'lsa qolgan soniya, aks holda 0."""
    import time as _t
    key = _channel_key(channel_id)
    until = _CHANNEL_FLOOD_UNTIL.get(key)
    if not until:
        return 0.0
    remaining = until - _t.monotonic()
    if remaining <= 0:
        _CHANNEL_FLOOD_UNTIL.pop(key, None)
        return 0.0
    return remaining


def clear_channel_flood(channel_id=None) -> None:
    """Testlar/admin uchun: kanal (yoki barcha) FloodWait sovutishini tozalaydi."""
    if channel_id is None:
        _CHANNEL_FLOOD_UNTIL.clear()
    else:
        _CHANNEL_FLOOD_UNTIL.pop(_channel_key(channel_id), None)


def stagger_quiet_hour_posts(posts, now=None, *, uniform=None):
    """08:00:00 herd paketiga persistent, kanal-xavfsiz vaqtlar beradi.

    Birinchi post darhol qoladi; keyingilar oldingi global slotdan 30..180s
    keyin joylashadi. Shu kanalning avvalgi slotidan kamida 60s o'tishi ham
    kafolatlanadi. Faqat aynan 08:00:00 ga qo'yilgan postlar o'zgartiriladi;
    shu sababli DB'ga bir marta ko'chirilgan post keyingi tickda qayta jitter
    qilinmaydi. ``uniform`` injectable bo'lib testlarni deterministik qiladi.
    """
    now = _as_tashkent(now or now_tashkent())
    rand = uniform or random.uniform
    result = []
    herd_offset = 0.0
    herd_seen = 0
    channel_offsets = {}

    for post in posts or ():
        scheduled = _as_tashkent(post[9] if post and len(post) > 9 else None)
        is_herd = bool(
            scheduled
            and scheduled.hour == QUIET_HERD_HOUR
            and scheduled.minute == 0
            and scheduled.second == 0
            and scheduled.microsecond == 0
        )
        if not is_herd:
            result.append((post, None))
            continue

        base = max(scheduled, now)
        channel = _channel_key(post[2] if len(post) > 2 else None)
        if herd_seen:
            step = max(QUIET_STAGGER_MIN_SECONDS, min(float(rand(
                QUIET_STAGGER_MIN_SECONDS, QUIET_STAGGER_MAX_SECONDS
            )), QUIET_STAGGER_MAX_SECONDS))
            herd_offset += step
        channel_floor = channel_offsets.get(channel, -CHANNEL_STAGGER_MIN_SECONDS)
        herd_offset = max(herd_offset, channel_floor + CHANNEL_STAGGER_MIN_SECONDS)
        channel_offsets[channel] = herd_offset
        target = base + timedelta(seconds=herd_offset)
        result.append((post, target if herd_seen else None))
        herd_seen += 1
    return result


# --- Avto-o'chirish xatolarini tasniflash -----------------------------------
# PHASE 9 & 10: MessageNotFound vs Forbidden xavfsiz ajratiladi.
# Ikkalasi ham qayta urinilmaydi, lekin monitoringda farqlanadi.
_DELETE_NOT_FOUND_PATTERNS = (
    "message to delete not found",
    "message_id_invalid",
    "message identifier is not specified",
    "message can't be deleted",
    "message cant be deleted",
)

_DELETE_FORBIDDEN_PATTERNS = (
    "chat not found",
    "chat_not_found",
    "bot was kicked",
    "bot is not a member",
    "not enough rights",
    "have no rights",
    "channel_private",
    "chat_write_forbidden",
    "message_delete_forbidden",
    "bot was blocked",
    "bot is blocked",
    "forbidden",
    "user is deactivated",
    "chat is deactivated",
)

# Eski nom — backward compat (testlar import qilishi mumkin)
_DELETE_GONE_PATTERNS = _DELETE_NOT_FOUND_PATTERNS + _DELETE_FORBIDDEN_PATTERNS


def classify_delete_error(error) -> str:
    """Avto-o'chirish xatosi tasnifi (PHASE 9 & 10).

    Qaytadi:
      * ``"gone"``       — xabar topilmadi / allaqachon o'chirilgan (MessageNotFound)
      * ``"forbidden"``   — bot cheklangan / huquq yo'q (Forbidden, BotKicked)
      * ``"transient"``   — vaqtinchalik (tarmoq, FloodWait, TimedOut)

    Faqat ``transient`` bo'lmaganda DB'da ``deleted_at`` yoziladi. ``gone`` va
    ``forbidden`` ikkalasi ham qayta urinilmaydi, lekin log'da ajratiladi.
    """
    if error is None:
        return "gone"
    if isinstance(error, (RetryAfter, TimedOut)):
        return "transient"
    text = str(error).lower()
    if any(p in text for p in _DELETE_NOT_FOUND_PATTERNS):
        return "gone"
    if any(p in text for p in _DELETE_FORBIDDEN_PATTERNS):
        return "forbidden"
    # PTB'da BadRequest — NetworkError subklassi, nom bo'yicha avval tekshiramiz
    name = type(error).__name__.lower()
    if isinstance(error, TelegramError):
        if "forbidden" in name:
            return "forbidden"
        if "badrequest" in name:
            if any(p in text for p in _DELETE_FORBIDDEN_PATTERNS):
                return "forbidden"
            return "gone"
    if isinstance(error, NetworkError):
        return "transient"
    return "transient"


def calculate_next_time(recurrence_type, recurrence_day, recurrence_time, current_time):
    """Takrorlanuvchi postning keyingi chiqish vaqti (Toshkent vaqtida).

    ``current_time`` timezone'siz (naive) berilsa — Toshkent zonasiga
    bog'lanadi, boshqa zonada berilsa Toshkentga o'giriladi. Shu sababli
    natija HAR DOIM ``Asia/Tashkent`` da bo'ladi (server UTC'da ishlasa ham).
    """
    now = _as_tashkent(current_time)
    if now is None:
        return None
    if recurrence_time is None:
        return None
    if recurrence_type == 'daily':
        next_dt = _replace_tashkent(now, recurrence_time.hour, recurrence_time.minute)
        if next_dt <= now:
            next_dt = _shift_tashkent(next_dt, days=1)
        return next_dt
    elif recurrence_type == 'weekly':
        if recurrence_day is None:
            return None
        days_ahead = (int(recurrence_day) - now.weekday() + 7) % 7
        if days_ahead == 0:
            days_ahead = 7
        next_dt = _replace_tashkent(now, recurrence_time.hour, recurrence_time.minute)
        return _shift_tashkent(next_dt, days=days_ahead)
    return None


def _as_tashkent(value):
    """Istalgan datetime'ni Toshkent vaqtiga keltiradi (naive → localize)."""
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        return tashkent_tz.localize(value)
    return value.astimezone(tashkent_tz)


def _replace_tashkent(moment, hour: int, minute: int):
    """Soat/daqiqani almashtiradi va DST/UTC-ofsetni qayta normallashtiradi.

    ``datetime.replace()`` pytz obyektida eski ofsetni saqlab qoladi —
    shuning uchun natija ``normalize()`` orqali qayta hisoblanadi.
    """
    naive = moment.replace(tzinfo=None, hour=hour, minute=minute, second=0, microsecond=0)
    return tashkent_tz.localize(naive)


def _shift_tashkent(moment, **delta):
    """Toshkent vaqtida kun/soat qo'shadi (ofset qayta normallashtiriladi)."""
    return tashkent_tz.normalize(moment + timedelta(**delta))


def now_tashkent():
    """Hozirgi Toshkent vaqti — kodning barcha nuqtalari uchun yagona manba."""
    return datetime.now(tashkent_tz)


def compose_post_text(content: str, has_ad_free: bool, channel_ad: str,
                      brand_text: str = "", limit: int = None) -> str:
    """Post matniga (ixtiyoriy) admin reklamasi va nishonni qo'shadi.

    ``brand_text`` — admin belgilagan so'z/watermark (masalan ``@PostAssistrobot``).
    Standart qiymati bo'sh, ya'ni majburiy watermark YO'Q — litsenziyasiz post ham
    toza chiqadi; nishon faqat admin yoqsa qo'shiladi.

    ``limit`` berilsa (Telegram: caption 1024, oddiy matn 4096), asosiy matn
    nishonga joy qoldirib kesiladi va nishon KESISHDAN KEYIN qo'shiladi — shu
    sababli u chegara tufayli hech qachon yo'qolib qolmaydi.

    Eslatma: Watermark (@username) endi ``apply_post_watermark`` orqali content'ga
    oldindan qo'shiladi (bepul foydalanuvchilar uchun). Bu funksiya faqat channel_ad
    va brand_text'ni qo'shadi.
    """
    text = content or ""
    ad = (channel_ad or "").strip()
    if not has_ad_free and ad:
        text = f"{text}\n\n{ad}" if text else ad
    brand = (brand_text or "").strip()
    html_mode = has_allowed_html(text) or has_allowed_html(brand)
    trim = sanitize_html if html_mode else truncate_text
    size = html_length if html_mode else utf16_length
    budget = int(limit) if limit else None
    # Normalize fragments separately so broken content cannot swallow the brand.
    text = trim(text, None)
    brand = trim(brand, budget)
    if budget is not None and budget > 0:
        allowed = max(0, budget - size(brand) - 2) if brand else budget
        text = trim(text, allowed)
        if not size(text):
            text = ""
    if brand:
        text = f"{text}\n\n{brand}" if text else brand
    return trim(text, budget if budget and budget > 0 else None)


def parse_album_items(file_id) -> list:
    """Albom JSON'ini listga aylantiradi; xato bo'lsa bo'sh list."""
    if not file_id:
        return []
    try:
        items = json.loads(file_id) if isinstance(file_id, str) else file_id
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(items, list):
        return []
    cleaned = []
    for item in items[:10]:
        if not isinstance(item, dict):
            continue
        fid = item.get("file_id")
        kind = (item.get("type") or "photo").lower()
        if fid:
            cleaned.append({"type": kind, "file_id": fid, "caption": item.get("caption") or ""})
    return cleaned


# ============================================================
# 🧹 KANALGA TOZA MATN — ichki xizmat/preview yozuvlarini olish
# ============================================================
# Kanalga yuborilayotganda asl post matni (caption/text) dan tashqari hech
# qanday ICHKI TEXNIK xabar qo'shilmasligi kerak: "Postni tasdiqlang:",
# "Kanal:", "Turi: Albom...", "Tugma:", "Reaksiyalar:", "Avto-o'chirish:"
# kabi botning tasdiqlash (preview) kartasi qatorlari KANALGA ASLO CHIQMASLIGI
# SHART. Foydalanuvchi bot xabarini (masalan tasdiqlash kartasini) post matni
# sifatida yuborib qo'yishi mumkin — shunday qatorlar yuborishdan oldin
# olinadi. Faqat aniq tan olingan xizmat yorliqlari (emoji-boshli preview
# qatorlari, uz/ru) olinadi; foydalanuvchining odatiy matni o'zgarmaydi.
_INTERNAL_TECHNICAL_LINE_PATTERNS = (
    # Tasdiqlash kartasi sarlavhasi:
    #   "📋 Postni tasdiqlang:" / "📋 Подтвердите пост:" / "📋 Confirm the post:"
    re.compile(r"^📋\s*(?:Postni tasdiqlang|Подтвердите пост|Confirm the post)\b.*$", re.I),
    # "📢 Kanal: ..." / "📢 Канал: ..." / "📢 Channel: ..."
    re.compile(r"^📢\s*(?:Kanal|Канал|Channel)\s*:.*$", re.I),
    # "📦 Turi: ..." / "📦 Тип: ..." / "📦 Type: ..."
    re.compile(r"^📦\s*(?:Turi|Тип|Type)\s*:.*$", re.I),
    # Albom xulosasi (preview): "🖼 Albom: 6 ta rasm" / "🖼 Альбом: 6 фото" /
    # "🖼 Album: 6 photos" (bu qator albom preview'ida alohida qatorda chiqadi)
    re.compile(r"^(?:🖼\s*)?(?:Albom|Альбом|Album)\s*:\s*\d+.*$", re.I),
    # "⏰ Vaqt belgilanmagan" / "⏰ Время не указано" / "⏰ Time not set"
    re.compile(r"^⏰\s*(?:Vaqt belgilanmagan|Время не указано|Time not set)\s*\.?\s*$", re.I),
    # "⏰ 2026-09-07 14:00 (Toshkent vaqti)" / "⏰ ... (время Ташкента)" /
    # "⏰ Sep 07, 2026 14:00 (Tashkent time)"
    re.compile(r"^⏰\s*\S.*(?:Toshkent vaqti|время Ташкента|Tashkent time)\s*\)?\s*\.?\s*$", re.I),
    # "🔁 Har kuni, soat 10:00 da" / "🔁 Ежедневно, в 10:00" / "🔁 Daily at 10:00"
    # (faqat preview formati — vaqt (HH:MM) qismi SHART bo'lsa kesiladi;
    #  foydalanuvchi o'z matnidagi "🔁 Har kuni..." kabi oddiy qator qoladi)
    re.compile(r"^🔁\s*(?:Har kuni|Ежедневно|Daily)\b[,:]?\s*(?:soat\s+|в\s+|at\s+)?\d{1,2}:\d{2}", re.I),
    # "📅 Har Dushanba, soat 10:00 da" / "📅 Каждый Понедельник, в 10:00" /
    # "📅 Every Monday at 10:00"
    re.compile(r"^📅\s*(?:Har |Каждый |Every )\S+.*?[,:]?\s*(?:soat\s+|в\s+|at\s+)?\d{1,2}:\d{2}", re.I),
    # "📋 Matn:" / "📋 Текст:" / "📋 Text:" yorlig'i (matnning O'ZI keyingi
    # qatorda qoladi)
    re.compile(r"^📋\s*(?:Matn|Текст|Text)\s*:.*$", re.I),
    # "🔘 Tugma: ..." / "🔘 Кнопка: ..." / "🔘 Button: disabled"
    re.compile(r"^🔘\s*(?:Tugma|Кнопка|Button)\b\s*:?.*$", re.I),
    # "👍 Reaksiyalar: ..." / "👍 Реакции: ..." / "👍 Reactions: disabled"
    re.compile(r"^👍\s*(?:Reaksiyalar|Реакции|Reactions)\b\s*:?.*$", re.I),
    # "⏳ Avto-o'chirish: 24 soat" / "⏳ Авто-удаление: 24 ч." /
    # "⏳ Auto-delete: 24 h"
    re.compile(r"^⏳\s*(?:Avto-?o'chirish|Авто-?удаление|Auto-?delete)\b\s*:?.*$", re.I),
    # Preview "matn kesildi" eslatmasi (uz/ru/en)
    re.compile(r"^⚠️\s*(?:Eslatma|Примечание|Note)\s*:.*(?:belgi|символ\w*|character\w*).*$", re.I),
)

#: Preview qatorlaridagi HTML teglar (<b>, <i>, <code>…) — solishtirishdan
#: oldin olib tashlanadi, aks holda "📦 <b>Type:</b> Text" kabi qatorlar
#: pattern'ga tushmay, kanal postiga sizib chiqadi.
_PREVIEW_HTML_TAG_RE = re.compile(r"</?(?:b|i|u|s|code|pre|tg-emoji)[^>]*>")


def _preview_comparable_line(line: str) -> str:
    """Texnik qatorlarni tanish uchun soddalashtirilgan ko'rinish."""
    return _PREVIEW_HTML_TAG_RE.sub(" ", (line or "").strip())




def sanitize_channel_content(content: str) -> str:
    """Kanalga yuboriladigan matndan botning ICHKI xizmat/preview qatorlarini oladi.

    ``"Postni tasdiqlang:"``, ``"Kanal:"``, ``"Turi: Albom..."``, ``"Tugma:"``,
    ``"Reaksiyalar:"``, ``"Avto-o'chirish:"`` kabi tasdiqlash kartasi (preview)
    yozuvlari kanaldagi postda HECH QACHON chiqmasligi kerak. Foydalanuvchi
    bot xabarini post matni sifatida yuborib qo'ysa, shunday qatorlar yuborish
    dan oldin olinadi. Faqat aniq tan olingan preview qatorlari (emoji-boshli,
    uz/ru) kesiladi — odatiy post matni o'zgarmaydi.
    """
    if not content:
        return content or ""
    text = content if isinstance(content, str) else str(content)
    lines = text.split("\n")
    cleaned = [
        line for line in lines
        if not any(p.match(_preview_comparable_line(line)) for p in _INTERNAL_TECHNICAL_LINE_PATTERNS)
    ]
    return "\n".join(cleaned).strip()


def build_reaction_buttons(post_id: int, enable_reactions: bool, reaction_emojis=None) -> list:
    """Post ostidagi reaksiya tugmalari (BITTA QATOR, yassi ro'yxat).

    - ``reaction_emojis`` (DB'dagi saqlangan tanlov) bo'lsa — shu emojilar
      ishlatiladi. Foydalanuvchi QO'LDA kiritgan kanondan tashqari emojilar
      (😍, 💯, 🙏 ...) ham saqlanib qoladi va kanal postida tugma bo'ladi.
    - Aks holda (eski postlar) standart to'plam (👍 ❤️ 🔥 👏) ishlatiladi.
    - Reaksiya o'chiq bo'lsa yoki emoji topilmasa — bo'sh ro'yxat (tugmasiz).

    Qaytarilgan qiymat — ``InlineKeyboardButton`` larning yassi ro'yxati
    (bitta qator); chaqiruv nuqtasida ``buttons.append(reactions_row)``
    bilan ishlatiladi. Telegram bir qatorga 5 tadan ko'p emoji tugmani
    sig'dira olmasligi mumkin, shuning uchun 5 ta bilan chegaralanadi
    (qolgan tanlovlar post_enhancer oqimida ko'p qatorli ko'rinishda
    to'liq chiqadi).
    """
    if not enable_reactions:
        return []
    # Avval foydalanuvchi tanlagan emojilar (kanonik + qo'lda kiritilganlar).
    emojis = normalize_custom_reaction_emojis(reaction_emojis, max_count=5)
    if not emojis:
        # Eski postlar (reaction_emojis NULL/buzilgan) — standart to'plam.
        emojis = list(DEFAULT_REACTION_EMOJIS)
    return [
        InlineKeyboardButton(emoji, callback_data=cb(CB_REACTION, post_id, emoji))
        for emoji in emojis[:5]
    ]


def _build_album_media(items: list, caption: str):
    """Albom elementlarini ``send_media_group`` uchun InputMedia ro'yxatiga aylantiradi.

    - Barcha elementlar (rasm/video/hujjat/audio) SAQLANADI — faqat birinchisi
      o'chirilmaydi, hech bir fayl yo'qolmaydi.
    - Caption faqat BIRINCHI elementga qo'shiladi (Telegram albomlarda captions
      faqat bitta xabarda bo'ladi).
    - GIF (animation) Telegram media-guruhida alohida tur sifatida
      qo'llab-quvvatlanmaydi — u hujjat (document) sifatida yuboriladi.
    """
    media = []
    for i, item in enumerate(items):
        cap, parse = telegram_html_payload(caption, TELEGRAM_CAPTION_LIMIT) if i == 0 else (None, None)
        fid = item["file_id"]
        kind = (item.get("type") or "photo").lower()
        if kind == "video":
            media.append(InputMediaVideo(media=fid, caption=cap, parse_mode=parse))
        elif kind == "document" or kind == "animation":
            media.append(InputMediaDocument(media=fid, caption=cap, parse_mode=parse))
        elif kind == "audio":
            media.append(InputMediaAudio(media=fid, caption=cap, parse_mode=parse))
        else:
            media.append(InputMediaPhoto(media=fid, caption=cap, parse_mode=parse))
    return media


def build_ad_button_row(ad) -> list:
    """Reklamaning inline URL tugmasi qatorini tuzadi (bo'lmasa bo'sh ro'yxat).

    ``ad`` — ``{"button_text": ..., "button_url": ...}`` ko'rinishidagi dict.
    Tugma matni ham, havolasi ham bo'lgandagina tugma yasaladi.
    """
    if not isinstance(ad, dict):
        return []
    btn_text = (ad.get("button_text") or "").strip()
    btn_url = (ad.get("button_url") or "").strip()
    if not btn_text or not btn_url:
        return []
    return [InlineKeyboardButton(text=btn_text[:64], url=btn_url)]


async def resolve_channel_ad(channel_id, has_ad_free: bool) -> dict:
    """Kanal uchun shu postda reklama chiqishi kerakligini hal qiladi.

    Har bir kanalning post sanagichi ALOHIDA oshiriladi va admin panelda
    belgilangan oraliq (masalan har 3-, 4- yoki 5-post) bo'yicha tekshiriladi.
    Reklama chiqmasa bo'sh dict qaytadi.
    """
    empty = {"text": "", "button_text": "", "button_url": "", "post_number": 0}
    # Sanagich reklamasiz (ad-free litsenziyali) postlarda ham oshadi —
    # kanal bo'yicha post tartibi uzluksiz bo'lishi kerak.
    try:
        post_number = await db.run_db(db.bump_channel_post_count, channel_id)
    except Exception:
        logger.exception("Kanal post sanagichini oshirishda xato: %s", channel_id)
        post_number = 0
    empty["post_number"] = post_number

    if has_ad_free:
        return empty

    # Admin paneldagi "📢 Kanal postlariga reklama qo'shish" bo'limi
    # o'chirilgan bo'lsa reklama umuman chiqmaydi. Sanagich o'sishda davom
    # etadi — bo'lim qayta yoqilganda post tartibi buzilmaydi.
    try:
        ad_settings = await db.run_db(db.get_ad_settings)
        if not ad_settings.get("channel_ad_status", True):
            return empty
    except Exception:
        logger.debug("Kanal reklama holatini o'qib bo'lmadi — standart yoqilgan")

    try:
        interval = await db.run_db(db.get_channel_ad_interval)
    except Exception:
        interval = db.CHANNEL_AD_INTERVAL_DEFAULT

    if not should_show_channel_ad(post_number, interval):
        return empty

    ad = await get_channel_ad_next_full_async()
    if not (ad.get("text") or "").strip():
        return empty

    ad["post_number"] = post_number
    try:
        await db.run_db(db.mark_channel_ad_shown, channel_id, post_number)
    except Exception:
        logger.debug("Reklama belgisini yozib bo'lmadi (kanal: %s)", channel_id)
    return ad


async def check_and_send_posts(bot):
    """Muddati yetgan postlarni yuborish (har 1 daqiqada scheduler orqali).

    Barcha DB chaqiruvlari alohida thread'da bajariladi (db.run_db),
    shuning uchun Telegram polling event loop'ini bloklamaydi. Postlar atomik
    ravishda 'processing' holatiga o'tkaziladi — takroriy yuborish bo'lmaydi.

    FloodWait (429) himoyasi:
      * har post orasida ``SEND_MICRO_DELAY`` (0.05–0.1s) mikro-kechikish —
        Telegram ketma-ket yuborishlarni rate-limit qilmasligi uchun;
      * ``telegram.error.RetryAfter`` ushlanadi va ``asyncio.sleep(retry_after)``
        bilan kutiladi — navbat to'xtamaydi, post yo'qolmaydi.
    """
    try:
        # 9-bosqich (graceful shutdown): yopilish boshlangan bo'lsa YANGI
        # ishlar navbatdan OLINMAYDI — faol yuborishlar tugashiga ruxsat
        # beriladi, lekin yangi post 'processing' ga o'tkazilmaydi.
        if lifecycle.is_shutting_down():
            logger.info("Scheduler: bot yopilmoqda — yangi postlar olinmaydi.")
            return
        # 0) Avvalgi tick'larda DB'ga yozilmay qolgan "yuborildi" markerlari —
        #    yangi postlarni olishdan OLDIN yoziladi (idempotentlik kafolati).
        await flush_unpersisted_sent_markers()
        now = now_tashkent()
        due_posts = await db.run_db(db.get_due_posts, now)
        if due_posts:
            logger.info("Yuboriladigan postlar soni: %d", len(due_posts))

        # Quiet Hours oxiridagi 08:00 herd'ni Telegramga tegmasdan oldin DB'da
        # tarqatamiz. get_due_posts qatorlarni allaqachon processing qilgan;
        # kelajak slotlari retry_post orqali pending holatiga atomik qaytadi.
        ready_posts = []
        for post, stagger_at in stagger_quiet_hour_posts(due_posts, now):
            if stagger_at is not None and stagger_at > now:
                await db.run_db(db.retry_post, post[0], stagger_at)
                logger.info(
                    "Quiet-hours stagger: post %s (kanal %s) → %s",
                    post[0], post[2], stagger_at.isoformat(),
                )
            else:
                ready_posts.append(post)
        due_posts = ready_posts

        for index, post in enumerate(due_posts):
            # 1) Mikro-kechikish — birinchi postdan keyin har safar.
            if index:
                await asyncio.sleep(SEND_MICRO_DELAY)
            # 9-bosqich: paket o'rtasida shutdown so'ralgan bo'lsa — qolgan
            # (hali Telegramga yuborilmagan) postlar darhol 'pending' ga
            # qaytariladi; ular keyingi ishga tushishda yuboriladi.
            if lifecycle.is_shutting_down():
                await _requeue_unsent_on_shutdown(due_posts[index:])
                break
            # 1b) Kanal FloodWait sovutishida bo'lsa — bu post Telegramga
            #     URINILMAYDI, DB'da kechiktiriladi; boshqa kanallar davom etadi.
            channel_id = post[2] if post and len(post) > 2 else None
            cooldown = channel_flood_remaining(channel_id)
            if cooldown > 0:
                logger.info(
                    "Kanal %s FloodWait sovutishida (%.0fs) — post %s kechiktirildi.",
                    channel_id, cooldown, post[0] if post else "?",
                )
                await _requeue_post(post, cooldown)
                continue
            try:
                with lifecycle.track(f"post:{post[0] if post else '?'}"):
                    await _execute_send(bot, post)
            except RetryAfter as e:
                # 2) Telegram FloodWait (429): scheduler BLOKLANMAYDI —
                #    qisqa (≤ FLOOD_WAIT_INLINE_SLEEP_MAX) pauza, post esa
                #    Telegram ko'rsatgan to'liq muddatga DB'da kechiktiriladi;
                #    kanal sovutishga qo'yiladi, navbat XAVFSIZ davom etadi.
                wait_seconds = flood_wait_seconds(e)
                logger.warning(
                    "Telegram FloodWait (429): post %s %.0fs ga kechiktirildi (kanal %s)",
                    post[0] if post else "?", wait_seconds, channel_id,
                )
                inline_sleep = flood_wait_inline_sleep(wait_seconds)
                # Freeze darhol boshlanadi va Telegram RetryAfter + 5s xavfsizlik
                # buferini to'liq qamraydi. Kalit kanalga xos: boshqa kanallar
                # mustaqil davom etadi.
                mark_channel_flood(
                    channel_id, wait_seconds + FLOOD_WAIT_SAFETY_SECONDS
                )
                await asyncio.sleep(inline_sleep)
                # DB retry ham aynan RetryAfter + 5s (+ kichik collision jitter).
                await _requeue_post(
                    post,
                    wait_seconds + FLOOD_WAIT_SAFETY_SECONDS
                    + delivery_service.retry_jitter(),
                )
            except Exception:
                logger.exception("Post yuborishda kutilmagan xato (Post ID: %s)", post[0] if post else "?")
                # Xatolik yuz berganda post 'processing' da qolib ketmasligi uchun qayta navbatga qo'yamiz.
                await _requeue_post(post, 60)
    except Exception:
        logger.exception("Scheduler ishida kutilmagan xato")


async def _requeue_post(post, delay_seconds: float) -> None:
    """Postni ``delay_seconds`` dan keyin qayta navbatga qo'yadi (xatosiz)."""
    if not post:
        return
    try:
        retry_at = now_tashkent() + timedelta(seconds=max(1.0, float(delay_seconds)))
        await db.run_db(db.retry_post, post[0], retry_at)
    except Exception:
        logger.exception("Postni qayta navbatlashda xato (Post ID: %s)", post[0])


async def _requeue_unsent_on_shutdown(posts) -> int:
    """Graceful shutdown: paketda HALI YUBORILMAGAN postlarni darhol 'pending'
    ga qaytaradi (``get_due_posts`` ularni 'processing' qilib olgan edi).

    Postlar Telegramga yuborilmagan — shuning uchun qayta navbatga qo'yish
    xavfsiz (duplikat bo'lmaydi). ``scheduled_time`` o'z qiymatida qoladi:
    keyingi ishga tushishda darhol yuboriladi. Qaytadi: qaytarilganlar soni.
    """
    count = 0
    for post in posts or ():
        if not post:
            continue
        try:
            # retry_at = asl vaqt (o'tmishda) — keyingi tick'da darhol due bo'ladi.
            scheduled = post[9] if len(post) > 9 and post[9] is not None else now_tashkent()
            await db.run_db(db.retry_post, post[0], scheduled)
            count += 1
        except Exception:
            logger.exception("Shutdown: postni navbatga qaytarishda xato (Post ID: %s)", post[0])
    if count:
        logger.warning(
            "Graceful shutdown: %d ta yuborilmagan post 'pending' ga qaytarildi "
            "(keyingi ishga tushishda yuboriladi).", count,
        )
    return count


async def _mark_delivery_failed(delivery_key, error, is_transient: bool = True):
    """Delivery claim qilinganidan keyingi Telegram xatosini DB ga yozadi.

    PostAssist V2: vaqtinchalik xatoda backoff (30s/2m/5m/15m) qo'yiladi,
    doimiy xatoda yoki 5-urinishda ham xato bo'lsa ``dead_letter`` bo'ladi.
    Qaytadi: delivery_service natijasi (dict) yoki None (kalit yo'q / DB xatosi).
    ``None`` — chaqiruvchi eski oqimda davom etishi kerak (qayta navbat).
    """
    if not delivery_key:
        return None
    try:
        return await db.run_db(
            delivery_service.mark_failed_by_key, delivery_key, error,
            is_transient,
        )
    except Exception:
        logger.exception("Delivery failed marker yozilmadi (%s)", delivery_key)
        return None


def _delivery_is_dead(result) -> bool:
    """Delivery natijasi 'dead_letter' ekanligini tekshiradi (None-safe)."""
    return isinstance(result, dict) and (
        result.get("status") == delivery_service.STATUS_DEAD_LETTER
        or result.get("dead") is True
    )


def _delivery_is_unknown(result) -> bool:
    """Delivery natijasi 'unknown' (UNKNOWN_DELIVERY) ekanligini tekshiradi."""
    return isinstance(result, dict) and (
        result.get("status") == UNKNOWN_DELIVERY or result.get("unknown") is True
    )


async def _mark_delivery_unknown(post_id, delivery_key, error) -> bool:
    """UNKNOWN_DELIVERY: delivery + scheduled_posts 'unknown' (blind retry yo'q).

    Hech qachon istisno tashlamaydi. Qaytadi: DB'ga yozildimi.
    """
    ok_delivery = True
    if delivery_key:
        try:
            ok_delivery = _db_ok(await db.run_db(
                delivery_service.mark_unknown_by_key, delivery_key, error
            ))
        except Exception:
            logger.exception("Delivery unknown markeri yozilmadi (%s)", delivery_key)
            ok_delivery = False
    ok_post = False
    try:
        ok_post = _db_ok(await db.run_db(db.mark_post_status, post_id, UNKNOWN_DELIVERY))
    except Exception:
        logger.exception("Post %s 'unknown' statusi yozilmadi", post_id)
    logger.error(
        "UNKNOWN_DELIVERY: post %s albomi yuborilayotganda Telegram javobi olinmadi (%s: %s). "
        "Dublikat xavfi tufayli avtomatik qayta yuborilmaydi — admin tekshiruvi kerak.",
        post_id, type(error).__name__, error,
    )
    return bool(ok_delivery and ok_post)


# ============================================================================
# P0 (VAZIFA 2): NOANIQ YETKAZIB BERISH — KANAL DEDUPLIKATSIYASI
# ----------------------------------------------------------------------------
# TimedOut/NetworkError'da so'rov Telegramga ketgan bo'lishi mumkin. Bunday
# holatda ko'r-ko'rrona qayta yuborish bitta postni kanalga IKKI MARTA chiqaradi.
# Yechim: qayta urinishdan OLDIN kanalning oxirgi xabarlari o'qiladi va post
# matni/mediasi SHA256 fingerprint bo'yicha solishtiriladi:
#   * topilsa        → delivery 'sent' (DELIVERED), qayta yuborilmaydi;
#   * yo'qligi aniq  → xavfsiz qayta yuborish;
#   * tasdiqlanmasa  → verify_pending (keyingi tekshiruvgacha YUBORILMAYDI),
#                      urinishlar tugagach — UNKNOWN (admin ko'radi).
AMBIGUOUS_PROBE_TIMEOUT = 8.0          # kanal o'qish uchun qat'iy timeout (soniya)


def _post_media_count(post_type, file_id) -> int:
    """Postdagi media elementlari soni (albom uchun ro'yxat uzunligi)."""
    return int(delivery_service.post_media_count(post_type, file_id))


def _build_post_signature(post_type, content, file_id, marker=None) -> dict:
    """Kanal tekshiruvi uchun post imzosi (SHA256 to'plami)."""
    return delivery_service.build_delivery_signature(
        content, media_count=_post_media_count(post_type, file_id), marker=marker
    )


async def _probe_channel_recent_posts(bot, channel_id, limit: int = None) -> dict:
    """Kanalning oxirgi xabarlarini o'qish (dedup tekshiruvi uchun).

    Manbalar: (1) bot admin bo'lgan kanallar uchun ``channel_posts_history``
    (DB), (2) ochiq kanallar uchun ``t.me/s/<username>`` veb-preview (username
    Telegram ``getChat`` orqali aniqlanadi). Hech qanday holatda istisno
    ko'tarmaydi — o'qib bo'lmasa ``{"status": "unavailable"}`` qaytadi va
    chaqiruvchi ko'r-ko'rrona retry QILMAYDI.
    """
    from utils.channel_reader import read_channel_posts, STATUS_OK

    limit = int(limit or delivery_service.AMBIGUOUS_VERIFY_LIMIT)
    targets = []
    try:
        chat = await bot.get_chat(channel_id)
        username = getattr(chat, "username", None)
        if username:
            targets.append(f"@{username}")
    except Exception as exc:
        logger.debug("Kanal username aniqlanmadi (%s): %s", channel_id, exc)
    targets.append(str(channel_id))

    for target in targets:
        try:
            result = await asyncio.wait_for(
                read_channel_posts(target, limit), timeout=AMBIGUOUS_PROBE_TIMEOUT
            )
        except Exception as exc:
            logger.debug("Kanal tekshiruvi o'qilmadi (%s): %s", target, exc)
            continue
        if (isinstance(result, dict) and result.get("status") == STATUS_OK
                and result.get("posts")):
            return {"status": "ok", "items": list(result["posts"]), "source": target}
    return {"status": "unavailable", "items": []}


async def _resolve_ambiguous_delivery(bot, post_id, channel_id, post_type, content,
                                      file_id, delivery_key, attempt: int, error,
                                      max_attempts: int = None) -> str:
    """Noaniq (TimedOut/NetworkError) holatni kanal tekshiruvi bilan hal qiladi.

    Qaytadi: ``"delivered"`` — kanalda topildi (qayta YUBORILMAYDI),
             ``"ready"``     — yo'qligi tasdiqlandi (xavfsiz qayta urinish),
             ``"pending"``   — tasdiqlanmadi (keyinroq yana tekshiriladi),
             ``"unknown"``   — urinishlar tugadi (admin ko'radi).
    """
    signature = _build_post_signature(post_type, content, file_id)
    probe = await _probe_channel_recent_posts(bot, channel_id)
    kwargs = {}
    if max_attempts is not None:
        kwargs["max_attempts"] = max(1, int(max_attempts))
    decision = await delivery_service.resolve_ambiguous(
        probe=probe, channel_id=channel_id, signature=signature,
        attempt=attempt, key=delivery_key, error=error, run=db.run_db, **kwargs,
    )
    status = decision.get("status")

    if status == delivery_service.STATUS_SENT:
        try:
            await db.run_db(db.mark_post_status, post_id, "posted")
        except Exception:
            logger.exception("Post %s 'posted' statusi yozilmadi (dedup)", post_id)
        return "delivered"

    if status == "verify_pending":
        retry_in = float(decision.get("retry_in") or delivery_service.AMBIGUOUS_VERIFY_DELAY)
        try:
            await db.run_db(
                db.retry_post, post_id, now_tashkent() + timedelta(seconds=retry_in)
            )
        except Exception:
            logger.exception("Post %s verify_pending retry vaqti yozilmadi", post_id)
        return "pending"

    if status == delivery_service.STATUS_UNKNOWN:
        try:
            await db.run_db(db.mark_post_status, post_id, UNKNOWN_DELIVERY)
        except Exception:
            logger.exception("Post %s 'unknown' statusi yozilmadi", post_id)
        return "unknown"

    if status == "ready":
        return "ready"
    return "unavailable"


async def _handle_ambiguous_send_error(bot, post_id, channel_id, post_type, content,
                                       file_id, delivery_key, delivery_marker_key,
                                       album_api_started, error, verify_attempt: int = 1):
    """TimedOut/NetworkError oqimi: ko'r-ko'rrona retry YO'Q (P0).

    Eski xatti-harakat (regressiya yo'q): oddiy matn/media postda xato
    avvalgidek ``failed`` + ``retry_post`` bo'ladi, albomda esa — UNKNOWN.
    Farqi: qayta yuborishdan oldin kanal tekshiriladi va post kanalda
    topilsa — DELIVERED (0 duplikat); tekshirib bo'lmasa — verify_pending
    (yuborish kechiktiriladi, ko'r-ko'rrona yuborilmaydi).
    """
    key = delivery_marker_key or delivery_key
    try:
        attempt = max(1, int(verify_attempt) + 1)
    except (TypeError, ValueError):
        attempt = 1

    # Albom (media group) uchun: "tasdiqlanmadi" darhol UNKNOWN bo'ladi —
    # verify_pending bilan kechiktirish YO'Q (qisman chiqqan albom xavfi).
    outcome = await _resolve_ambiguous_delivery(
        bot, post_id, channel_id, post_type, content, file_id, key, attempt, error,
        max_attempts=1 if album_api_started else None,
    )

    if outcome == "delivered":
        logger.warning(
            "Post %s: noaniq yuborish ANIQLANDI — post kanalda allaqachon bor, "
            "qayta yuborilmaydi (0 duplikat).", post_id,
        )
        return

    # Albom: qisman chiqqan bo'lishi mumkin — eski konservativ yo'l (UNKNOWN),
    # lekin post kanalda TOPILSA yuqorida allaqachon 'delivered' bo'lgan.
    if album_api_started:
        await _mark_delivery_unknown(post_id, key, error)
        return

    delivery_result = await _mark_delivery_failed(delivery_key, error, is_transient=True)
    if _delivery_is_dead(delivery_result):
        logger.warning(
            "Post %s: tarmoq urinishlari tugadi (dead_letter) — 'failed' deb yakunlanadi.",
            post_id,
        )
        await db.run_db(db.mark_post_status, post_id, "failed")
        return

    if outcome in ("pending", "unknown"):
        # Tasdiqlanmadi: Telegramga yuborilmaydi; post keyingi tekshiruvga
        # qayta navbatga qo'yiladi (marker delivery yozuvida saqlanadi).
        if outcome == "pending" and key:
            await db.run_db(
                delivery_service.mark_verify_pending_by_key, key, error, attempt,
                delivery_service.AMBIGUOUS_VERIFY_DELAY,
            )
        logger.warning(
            "Post %s: noaniq yetkazib berish tasdiqlanmadi (%s) — ko'r-ko'rrona retry "
            "qilinmaydi, keyingi tekshiruvga qoldirildi.", post_id, outcome,
        )
        if outcome == "pending":
            await db.run_db(
                db.retry_post, post_id,
                now_tashkent() + timedelta(seconds=delivery_service.AMBIGUOUS_VERIFY_DELAY),
            )
        return

    # "ready" — post kanalda YO'Q ekani tasdiqlandi: xavfsiz qayta yuborish.
    logger.warning(
        "Telegram tarmoq xatosi (Post ID: %s): %s; post kanalda yo'qligi tasdiqlandi — "
        "qayta uriniladi", post_id, error,
    )
    delay = _delivery_retry_delay(delivery_result, NETWORK_RETRY_DELAY)
    retry_at = now_tashkent() + timedelta(seconds=delay)
    await db.run_db(db.retry_post, post_id, retry_at)


def _delivery_retry_delay(result, fallback: float) -> float:
    """Delivery natijasidagi backoff (soniya) yoki fallback qiymat."""
    if isinstance(result, dict):
        try:
            backoff = float(result.get("backoff_seconds") or 0)
        except (TypeError, ValueError):
            backoff = 0
        if backoff > 0:
            return backoff
    return float(fallback)


async def _send_precheck_and_claim(bot, post):
    """1/3 — PRE-SEND CHECKS & DEDUP VERIFICATION (SPRINT 2 decomposition).

    ``_execute_send`` avvalgi 360+ qatorlik monolitining BIRINCHI mas'uliyati:
    idempotentlik guard'i, holatni "processing" belgilash va delivery claim
    (atomik bron — 0 duplikat kafolati). Hech narsa Telegramga YUBORILMAYDI.

    Returns:
        ``None`` — chaqiruvchi SHU YERDA to'xtashi kerak (post allaqachon
        yuborilgan / boshqa worker claim qilgan / retry kutilmoqda va h.k.,
        asl monolit xatti-harakati bilan AYNAN bir xil).
        ``dict`` ("ctx") — keyingi ikki bosqich (payload va post-send) uchun
        kerakli barcha holat.
    """
    (
        post_id, user_id, channel_id, post_type, content, file_id,
        btn_text, btn_url, enable_reactions, scheduled_time,
        recurrence_type, recurrence_day, recurrence_time, end_date,
        delete_after_hours, reaction_emojis
    ) = post

    # 0. IDEMPOTENTLIK GUARD'I: bu post allaqachon Telegramga chiqqan, faqat DB
    #    markeri yozilmay qolgan bo'lsa (masalan, stale-recovery uni 'pending' ga
    #    qaytargan) — QAYTA YUBORILMAYDI, faqat marker yozishga urinamiz.
    if is_sent_but_unpersisted(post_id):
        logger.warning(
            "Post %s allaqachon Telegramga yuborilgan (DB markeri kutilmoqda) — qayta yuborilmaydi.",
            post_id,
        )
        await _persist_sent_marker(_UNPERSISTED_SENT[int(post_id)], retry_delays=())
        return None

    # Legacy adapters may return None for posts without delivery settings.
    # Database exceptions still propagate; never hide a failed settings read.
    delivery_options = await db.run_db(db.get_post_delivery_options, post_id) or {}
    delivery_kwargs = {
        key: delivery_options.get(key) is True
        for key in ("disable_notification", "protect_content")
    }

    # 1. Post holatini Telegramga yuborishdan oldin qat'iy "processing" qilib belgilaymiz (processing_started_at bilan)
    if await db.run_db(db.mark_post_processing, post_id) is False:
        # DB hozir yozuvni qabul qilmayapti — yuborishdan OLDIN to'xtaymiz
        # (aks holda yuborilgach marker ham yozilmay qolishi ehtimoli katta).
        # Chaqiruvchi (check_and_send_posts) postni qayta navbatga qo'yadi.
        raise RuntimeError(f"DB 'processing' markerini yozib bo'lmadi (Post ID: {post_id})")

    # P0-04 / PostAssist V2: scheduled_posts statusi yetarli emas, chunki
    # restart/crash va parallel schedulerlar orasida aynan Telegram
    # delivery'sini claim qilish kerak. post_deliveries 'sent' bo'lsa
    # Telegramga qayta murojaat qilmaymiz (0 duplikat kafolati).
    delivery_key = delivery_service.build_idempotency_key(post_id, channel_id, scheduled_time)
    delivery_marker_key = None
    delivery_claim = await db.run_db(
        delivery_service.claim_post_for_delivery, post_id, channel_id, scheduled_time
    )
    # P0: avvalgi noaniq urinishdan qolgan "kanal tekshiruvi kutilmoqda"
    # markeri (bo'lsa) — yuborishdan oldin dedup tekshiruvi o'tkaziladi.
    delivery_claim_verify_attempt = delivery_service.delivery_verify_attempt(
        delivery_claim.get("last_error") if isinstance(delivery_claim, dict) else None
    )
    if isinstance(delivery_claim, dict):
        claim_status = delivery_claim.get("status")
        if delivery_claim.get("sent") or claim_status == "sent":
            await db.run_db(db.mark_post_status, post_id, "posted")
            return None
        if _delivery_is_dead(delivery_claim):
            # Doimiy xato yoki urinishlar tugagan — post hech qachon
            # yuborilmaydi, navbatda ('processing') qolib ketmasligi uchun
            # 'failed' deb yakunlaymiz.
            logger.warning(
                "Post %s delivery'si dead_letter — qayta urinilmaydi.", post_id,
            )
            await db.run_db(db.mark_post_status, post_id, "failed")
            return None
        if _delivery_is_unknown(delivery_claim):
            # UNKNOWN_DELIVERY: avvalgi urinishda Telegram javobi olinmagan —
            # xabar kanalda bo'lishi mumkin. Blind retry TAQIQLANADI.
            logger.warning(
                "Post %s delivery'si UNKNOWN — avtomatik qayta yuborilmaydi (admin ko'radi).",
                post_id,
            )
            await db.run_db(db.mark_post_status, post_id, UNKNOWN_DELIVERY)
            return None
        if not delivery_claim.get("claimed"):
            if claim_status == "processing":
                # Boshqa scheduler instance hozir yuborayotgan bo'lishi mumkin.
                return None
            if delivery_claim.get("retry_pending"):
                # Backoff hali o'tmagan — postni retry vaqtiga qaytaramiz.
                retry_at = delivery_claim.get("next_retry_at") or (
                    now_tashkent() + timedelta(seconds=NETWORK_RETRY_DELAY)
                )
                await db.run_db(db.retry_post, post_id, retry_at)
                return None
            raise RuntimeError(
                f"Delivery claim bajarilmadi (Post ID: {post_id}, "
                f"status={claim_status})"
            )
        delivery_marker_key = delivery_claim.get("idempotency_key") or delivery_key
    elif delivery_claim is False:
        raise RuntimeError(f"Delivery claim bajarilmadi (Post ID: {post_id})")
    elif delivery_claim is True:
        # Minimal fake/legacy DB adapterlari uchun ham marker ishlaydi.
        delivery_marker_key = delivery_key

    return {
        "post_id": post_id, "user_id": user_id, "channel_id": channel_id,
        "post_type": post_type, "content": content, "file_id": file_id,
        "btn_text": btn_text, "btn_url": btn_url,
        "enable_reactions": enable_reactions, "scheduled_time": scheduled_time,
        "recurrence_type": recurrence_type, "recurrence_day": recurrence_day,
        "recurrence_time": recurrence_time, "end_date": end_date,
        "delete_after_hours": delete_after_hours, "reaction_emojis": reaction_emojis,
        "delivery_options": delivery_options, "delivery_kwargs": delivery_kwargs,
        "delivery_key": delivery_key, "delivery_marker_key": delivery_marker_key,
        "delivery_claim": delivery_claim,
        "delivery_claim_verify_attempt": delivery_claim_verify_attempt,
    }


async def _verify_no_duplicate_before_send(bot, ctx: dict, final_content: str) -> bool:
    """1b/3 — YUBORISHDAN OLDIN DEDUP TEKSHIRUVI (pre-send checks guruhi).

    Avvalgi urinish TimedOut/NetworkError bilan noaniq qolgan bo'lsa (delivery
    ``AMBIGUOUS_VERIFY`` markeri), Telegramga YUBORMASDAN avval kanal
    tekshiriladi: post allaqachon chiqqan bo'lsa — DELIVERED (dublikat YO'Q),
    yo'qligi tasdiqlansa — xavfsiz yuborish davom etadi.

    Returns:
        ``True`` — xavfsiz, yuborish davom etishi mumkin.
        ``False`` — chaqiruvchi SHU YERDA to'xtashi kerak (allaqachon
        yuborilgan yoki hali noaniq).
    """
    delivery_marker_key = ctx["delivery_marker_key"]
    delivery_claim = ctx["delivery_claim"]
    if not (delivery_marker_key and delivery_service.delivery_verify_pending(
            delivery_claim.get("last_error") if isinstance(delivery_claim, dict) else None)):
        return True

    gate_attempt = ctx["delivery_claim_verify_attempt"] + 1
    gate_outcome = await _resolve_ambiguous_delivery(
        bot, ctx["post_id"], ctx["channel_id"], ctx["post_type"], final_content, ctx["file_id"],
        delivery_marker_key, gate_attempt,
        RuntimeError("ambiguous delivery (verify pending)"),
    )
    if gate_outcome == "delivered":
        logger.warning(
            "Post %s: kanal tekshiruvi post ALLAQACHON kanalda ekanini aniqladi — "
            "qayta yuborilmaydi (0 duplikat).", ctx["post_id"],
        )
        return False
    if gate_outcome in ("pending", "unknown"):
        return False
    # "ready" — post kanalda YO'Q ekani tasdiqlandi: xavfsiz yuborish.
    return True


async def _build_send_payload(ctx: dict):
    """2/3 — PAYLOAD FORMATTING & MEDIA HANDLING (SPRINT 2 decomposition).

    Tugmalar (link/reklama/reaksiya), watermark, ichki texnik qatorlarni
    tozalash va Telegram caption/matn limitiga moslashtirilgan YAKUNIY matn
    shu yerda tayyorlanadi. Haqiqiy Telegram API chaqiruvi bu yerda
    QILINMAYDI (buning uchun :func:`_dispatch_post_to_telegram`).

    Returns:
        ``None`` — matn tayyorlashda xato (post 'failed' deb belgilandi,
        chaqiruvchi shu yerda to'xtaydi).
        ``dict`` — ``reply_markup``, ``final_content``, ``text_limit``.
    """
    post_id = ctx["post_id"]
    user_id = ctx["user_id"]
    channel_id = ctx["channel_id"]
    post_type = ctx["post_type"]
    content = ctx["content"]
    btn_text = ctx["btn_text"]
    btn_url = ctx["btn_url"]
    enable_reactions = ctx["enable_reactions"]
    reaction_emojis = ctx["reaction_emojis"]

    buttons = []
    if btn_text and btn_url:
        buttons.append([InlineKeyboardButton(text=btn_text, url=btn_url)])

    is_admin = (user_id in ADMIN_IDS_SET)

    # Litsenziyani yuborishdan OLDIN tekshiramiz; sarflash faqat
    # muvaffaqiyatli yuborilgandan keyin amalga oshiriladi.
    has_ad_free = True if is_admin else await db.run_db(db.is_premium, user_id)

    # Reklama: har bir KANAL uchun alohida post sanagichi + admin belgilagan
    # oraliq (har 3-, 4- yoki 5-post). Reklama chiqsa uning inline URL tugmasi
    # ham postga qo'shiladi.
    ad = await resolve_channel_ad(channel_id, has_ad_free)
    channel_ad = (ad.get("text") or "").strip()
    ad_button_row = build_ad_button_row(ad)
    if ad_button_row:
        buttons.append(ad_button_row)

    # Multi-select reaksiyalar: foydalanuvchi tanlagan emojilar ishlatiladi
    # (eski postlarda reaction_emojis NULL bo'lsa — standart to'plam).
    # Qo'lda kiritilgan kanondan tashqari emojilar ham shu yerda saqlanadi.
    reactions_row = build_reaction_buttons(post_id, enable_reactions, reaction_emojis)
    if reactions_row:
        buttons.append(reactions_row)
    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None

    # Admin tomonidan yoqilgan nishon (masalan @PostAssistrobot) — bo'sh bo'lsa qo'shilmaydi.
    brand_text = (await db.run_db(db.get_setting, "post_tag_text", "")).strip()

    # Reaksiya emojilari FAQAT inline tugma (reply_markup). Caption/matn
    # boshiga sizib chiqqan glyph qatori (👍 ❤️ 🔥\n\n...) yuborishdan oldin
    # olinadi. Eski postlarda reaction_emojis NULL bo'lsa — tugmalar bilan
    # bir xil standart to'plam solishtiriladi.
    strip_emojis = reaction_emojis
    if enable_reactions and not normalize_custom_reaction_emojis(strip_emojis):
        strip_emojis = list(DEFAULT_REACTION_EMOJIS)
    clean_content = strip_leading_reaction_glyphs(content or "", strip_emojis)

    # 🧹 ICHKI XIZMAT MATNLARI KANALGA CHIQMAYDI: foydalanuvchi tasdiqlash
    # kartasini (preview) yoki boshqa bot xabarini post matni sifatida yuborib
    # qo'ysa — "Postni tasdiqlang:", "Kanal:", "Turi: Albom...", "Tugma:",
    # "Reaksiyalar:", "Avto-o'chirish:" kabi ichki texnik qatorlar yuborishdan
    # oldin olinadi. Kanalda faqat foydalanuvchining ASL matni qoladi.
    clean_content = sanitize_channel_content(clean_content)

    # WATERMARK: Bepul foydalanuvchilar postlariga bot username qo'shish
    watermarked_content = await apply_post_watermark(clean_content, user_id, BOT_USERNAME)

    # Telegram caption limiti 1024, oddiy matn limiti 4096 belgidan iborat.
    # Limit compose_post_text ichida qo'llanadi — nishon kesishdan KEYIN
    # qo'shiladi, shuning uchun u hech qachon kesilib ketmaydi.
    pt_for_limit = str(post_type).lower()
    text_limit = (
        TELEGRAM_CAPTION_LIMIT if pt_for_limit in
        ("photo", "video", "animation", "document", "audio", "voice", "album")
        else TELEGRAM_TEXT_LIMIT
    )
    try:
        final_content = compose_post_text(
            watermarked_content, has_ad_free, channel_ad, brand_text, limit=text_limit
        )
    except Exception:
        logger.exception("Post matnini tayyorlashda xatolik (Post ID: %s)", post_id)
        await db.run_db(db.mark_post_status, post_id, "failed")
        return None

    return {
        "reply_markup": reply_markup,
        "final_content": final_content,
        "text_limit": text_limit,
    }


async def _dispatch_post_to_telegram(bot, ctx: dict, payload: dict, send_state: dict):
    """2b/3 — MEDIA TURI BO'YICHA YUBORISH (payload/media handling davomi).

    Album/photo/video/... Telegram API chaqiruvlari shu yerda. Xatolarni
    ATAYLAB ushlamaydi — chaqiruvchi (:func:`_execute_send`) tashqi
    ``try/except`` zanjirida FloodWait/TimedOut/TelegramError'ni markaziy
    boshqaradi (xatti-harakat eski monolit bilan bir xil).

    ``send_state`` — o'zgaruvchan konteyner: ``album_api_started`` xato
    chiqib ketgan taqdirda ham chaqiruvchiga ma'lum bo'lishi uchun (albom
    ``send_media_group`` chaqiruvi BOSHLANGAN, lekin javob kelmagan bo'lishi
    mumkin — ambiguous-delivery boshqaruvi shu bayroqqa qaraydi).
    """
    post_id = ctx["post_id"]
    channel_id = ctx["channel_id"]
    post_type = ctx["post_type"]
    file_id = ctx["file_id"]
    delivery_kwargs = ctx["delivery_kwargs"]
    final_content = payload["final_content"]
    text_limit = payload["text_limit"]
    reply_markup = payload["reply_markup"]

    pt = str(post_type).lower()
    target_chat = int(channel_id) if str(channel_id).lstrip('-').isdigit() else channel_id

    safe_final_content, final_parse_mode = telegram_html_payload(final_content or "", text_limit)

    sent_msg = None
    extra_ids = []

    if pt == "album":
        items = parse_album_items(file_id)
        if not items:
            logger.error("Albom tarkibi bo'sh (Post ID: %s)", post_id)
            await db.run_db(db.mark_post_status, post_id, "failed")
            return {"stop": True, "target_chat": target_chat, "sent_msg": None, "extra_ids": []}
        if len(items) == 1:
            # Bitta element — oddiy media (tugmalar ishlashi uchun)
            only = items[0]
            sent_msg = await _send_single_media(
                bot, target_chat, only["type"], only["file_id"], safe_final_content, reply_markup, final_parse_mode, **delivery_kwargs
            )
        else:
            media = _build_album_media(items, final_content)
            send_state["album_api_started"] = True
            sent_group = await _delivery_send(bot, "send_media_group", chat_id=target_chat, **delivery_kwargs, media=media)
            send_state["album_api_started"] = False
            sent_msg = sent_group[0] if sent_group else None
            extra_ids = [m.message_id for m in (sent_group or [])[1:] if getattr(m, "message_id", None)]
            # sendMediaGroup reply_markup'ni qo'llab quvvatlamaydi — tugmalarni alohida xabar
            if reply_markup:
                follow = await _delivery_send(
                    bot, "send_message",
                    chat_id=target_chat, **delivery_kwargs, text="🔗", reply_markup=reply_markup
                )
                if follow and follow.message_id:
                    extra_ids.append(follow.message_id)
    elif pt == "photo":
        sent_msg = await _delivery_send(bot, "send_photo", chat_id=target_chat, **delivery_kwargs, photo=file_id, caption=safe_final_content, reply_markup=reply_markup, parse_mode=final_parse_mode)
    elif pt == "video":
        sent_msg = await _delivery_send(bot, "send_video", chat_id=target_chat, **delivery_kwargs, video=file_id, caption=safe_final_content, reply_markup=reply_markup, parse_mode=final_parse_mode)
    elif pt == "animation":
        sent_msg = await _delivery_send(bot, "send_animation", chat_id=target_chat, **delivery_kwargs, animation=file_id, caption=safe_final_content, reply_markup=reply_markup, parse_mode=final_parse_mode)
    elif pt == "document":
        sent_msg = await _delivery_send(bot, "send_document", chat_id=target_chat, **delivery_kwargs, document=file_id, caption=safe_final_content, reply_markup=reply_markup, parse_mode=final_parse_mode)
    elif pt == "audio":
        sent_msg = await _delivery_send(bot, "send_audio", chat_id=target_chat, **delivery_kwargs, audio=file_id, caption=safe_final_content, reply_markup=reply_markup, parse_mode=final_parse_mode)
    elif pt == "voice":
        sent_msg = await _delivery_send(bot, "send_voice", chat_id=target_chat, **delivery_kwargs, voice=file_id, caption=safe_final_content, reply_markup=reply_markup, parse_mode=final_parse_mode)
    elif pt == "sticker":
        sent_msg = await _delivery_send(
            bot, "send_sticker",
            chat_id=target_chat, **delivery_kwargs, sticker=file_id, reply_markup=reply_markup
        )
    else:
        sent_msg = await _delivery_send(bot, "send_message", chat_id=target_chat, **delivery_kwargs, text=safe_final_content or " ", reply_markup=reply_markup, parse_mode=final_parse_mode)

    return {"stop": False, "target_chat": target_chat, "sent_msg": sent_msg, "extra_ids": extra_ids}


async def _finalize_sent_post(bot, ctx: dict, sent_marker: dict, sent_msg_id, target_chat) -> None:
    """3/3 — POST-SEND STATE UPDATE & ANALYTICS TRIGGER (SPRINT 2 decomposition).

    Telegramga muvaffaqiyatli yuborilgandan KEYIN bajariladigan ishlar:
    doimiy marker yozish (``posted`` + ``sent_message_id`` + takrorlash
    rejasi), ixtiyoriy auto-pin va YENGIL/ASINXRON foydalanuvchi hodisasi
    (``services.event_tracker``) — qaysi post turlari ko'p yuborilayotganini
    kuzatish uchun. Hech qachon istisno otmaydi (eski monolit kafolati
    saqlanadi — yuborilgan post hech qachon qayta navbatga tushmaydi).
    """
    await _persist_sent_marker(sent_marker)
    if sent_msg_id and ctx["delivery_options"].get("auto_pin") is True:
        try:
            await bot.pin_chat_message(
                chat_id=target_chat, message_id=sent_msg_id, disable_notification=True
            )
        except Exception:
            # Pinning failure must never retry an already delivered post.
            logger.warning("Auto-pin failed (Post ID: %s)", ctx["post_id"], exc_info=True)

    # 📊 SPRINT 2 (VAZIFA 3) — engil/asinxron analitika: qaysi post turi
    # qancha yuborilgani (shu orqali eng ko'p/kam ishlatilgan formatlar
    # keyinchalik ``event_tracker.usage_report()`` bilan aniqlanadi).
    event_tracker.track(ctx["user_id"], f"post_sent:{str(ctx['post_type']).lower()}")


async def _execute_send(bot, post):
    """Postni Telegramga yetkazish — 3 bosqichli orkestrator (SPRINT 2):

      1) :func:`_send_precheck_and_claim` — idempotentlik, holat, delivery
         claim (+ :func:`_verify_no_duplicate_before_send` — dedup gate);
      2) :func:`_build_send_payload` + :func:`_dispatch_post_to_telegram` —
         kontent/tugmalar tayyorlash va media turi bo'yicha Telegram API
         chaqiruvi;
      3) :func:`_finalize_sent_post` — doimiy marker, auto-pin, analitika.

    Xatti-harakat avvalgi (monolit) ``_execute_send`` bilan AYNAN bir xil —
    bu FAQAT kod tashkilotini (Single Responsibility) yaxshilaydi.
    """
    ctx = await _send_precheck_and_claim(bot, post)
    if ctx is None:
        return

    payload = await _build_send_payload(ctx)
    if payload is None:
        return

    final_content = payload["final_content"]

    # ── P0 (VAZIFA 2): YUBORISHDAN OLDIN DEDUP TEKSHIRUVI ──────────────────
    if not await _verify_no_duplicate_before_send(bot, ctx, final_content):
        return

    # ── P0: IDEMPOTENT DELIVERY LOCK ───────────────────────────────────────
    # DB claim allaqachon atomik; bu qo'shimcha qatlam bir jarayondagi
    # tasklar (va Redis mavjud bo'lsa — instansiyalar) orasida bir xil postni
    # IKKI MARTA yuborishni to'sadi.
    delivery_key = ctx["delivery_key"]
    delivery_marker_key = ctx["delivery_marker_key"]
    post_id = ctx["post_id"]
    delivery_lock_key = delivery_marker_key or delivery_key
    lock_token = await delivery_service.acquire_delivery_lock(delivery_lock_key)
    if lock_token is None:
        logger.warning(
            "Post %s: delivery lock band (boshqa worker yubormoqda) — qayta navbatga.",
            post_id,
        )
        await _mark_delivery_failed(delivery_key, RuntimeError("delivery lock busy"),
                                    is_transient=True)
        await db.run_db(
            db.retry_post, post_id,
            now_tashkent() + timedelta(seconds=delivery_service.DELIVERY_LOCK_RETRY_DELAY),
        )
        return

    send_state = {"album_api_started": False}
    sent_marker = None
    sent_msg_id = None
    target_chat = None
    try:
        dispatch_result = await _dispatch_post_to_telegram(bot, ctx, payload, send_state)
        if dispatch_result["stop"]:
            return
        target_chat = dispatch_result["target_chat"]
        sent_msg = dispatch_result["sent_msg"]
        extra_ids = dispatch_result["extra_ids"]

        sent_msg_id = sent_msg.message_id if sent_msg else None
        # Post Telegramga muvaffaqiyatli yuborildi! Bundan keyin HECH QANDAY
        # holatda (DB xatosi, restart) post qayta yuborilmasligi kerak:
        # marker (posted + sent_message_id + takrorlash rejasi) backoff bilan
        # yoziladi; yozilmasa xotira/journal guard'ida qoladi.
        sent_marker = _build_sent_marker(
            post_id, sent_msg_id, ctx["channel_id"], ctx["delete_after_hours"], extra_ids,
            ctx["recurrence_type"], ctx["recurrence_day"], ctx["recurrence_time"], ctx["end_date"],
            delivery_marker_key,
        )

    except RetryAfter as e:
        # Telegram rate-limit (FloodWait, 429) — vaqtinchalik holat.
        # 1) Telegram ko'rsatgan muddat davomida JIM turamiz (aks holda
        #    keyingi so'rovlar ham 429 bilan qaytadi va limit uzayadi).
        # 2) Post yo'qolmasligi uchun qayta navbatga qo'yamiz (5-urinishda
        #    ham 429 bo'lsa delivery dead_letter bo'lib, post yakunlanadi).
        delivery_result = await _mark_delivery_failed(delivery_key, e, is_transient=True)
        wait_seconds = flood_wait_seconds(e)
        logger.warning(
            "Telegram FloodWait (Post ID: %s, kanal %s): post %.0fs ga kechiktiriladi",
            post_id, ctx["channel_id"], wait_seconds,
        )
        # Scheduler BLOKLANMAYDI: kanal sovutishga qo'yiladi, tick ichida faqat
        # qisqa pauza; to'liq kutish DB'dagi retry vaqtida.
        inline_sleep = flood_wait_inline_sleep(wait_seconds)
        mark_channel_flood(
            ctx["channel_id"], wait_seconds + FLOOD_WAIT_SAFETY_SECONDS
        )
        await asyncio.sleep(inline_sleep)
        if _delivery_is_dead(delivery_result):
            logger.warning(
                "Post %s: FloodWait urinishlari tugadi (dead_letter) — 'failed' deb yakunlanadi.",
                post_id,
            )
            await db.run_db(db.mark_post_status, post_id, "failed")
            return
        # Aniq kutish vaqti + jitter (PHASE 5): DB retry vaqtiga 0..0.25s
        # tasodifiy oraliq qo'shiladi — thundering-herd 429 oldini oladi.
        retry_at = now_tashkent() + timedelta(
            seconds=wait_seconds + FLOOD_WAIT_SAFETY_SECONDS
            + delivery_service.retry_jitter()
        )
        await db.run_db(db.retry_post, post_id, retry_at)
        return
    except (TimedOut, NetworkError) as e:
        # P0 (VAZIFA 2): noaniq holat — ko'r-ko'rrona retry TAQIQLANADI. Avval
        # kanalning oxirgi xabarlari tekshiriladi (SHA256 fingerprint):
        # topilsa DELIVERED, yo'qligi tasdiqlansa xavfsiz retry, aks holda
        # verify_pending (yuborilmaydi) → urinishlar tugagach UNKNOWN.
        await _handle_ambiguous_send_error(
            bot, post_id, ctx["channel_id"], ctx["post_type"], final_content, ctx["file_id"],
            delivery_key, delivery_marker_key, send_state["album_api_started"], e,
            verify_attempt=ctx["delivery_claim_verify_attempt"],
        )
        return
    except TelegramError as e:
        # Noma'lum Telegram xatosi (masalan BadRequest): odatda doimiy
        # (noto'g'ri so'rov) — takrorlash foydasiz, dead_letter + 'failed'.
        # SchedulerService ichida ham chat_not_found/bot_kicked naqshlari
        # qo'shimcha tekshiriladi.
        delivery_result = await _mark_delivery_failed(delivery_key, e, is_transient=False)
        logger.error(f"Post yuborishda xato (Post ID: {post_id}): {e}")
        if not _delivery_is_dead(delivery_result) and isinstance(delivery_result, dict):
            # Kutilmagan holat (masalan, transient deb topildi) — backoff bilan qayta.
            delay = _delivery_retry_delay(delivery_result, NETWORK_RETRY_DELAY)
            retry_at = now_tashkent() + timedelta(seconds=delay)
            await db.run_db(db.retry_post, post_id, retry_at)
            return
        await db.run_db(db.mark_post_status, post_id, "failed")
        return
    except Exception as e:
        delivery_result = await _mark_delivery_failed(delivery_key, e, is_transient=True)
        if _delivery_is_dead(delivery_result):
            logger.warning(
                "Post %s: urinishlar tugadi (dead_letter) — 'failed' deb yakunlanadi.",
                post_id,
            )
            await db.run_db(db.mark_post_status, post_id, "failed")
            return
        raise
    finally:
        # P0: idempotent delivery lock HAR QANDAY holatda bo'shatiladi
        # (xato/return/cancel — barchasida). DB'dagi 'processing' claim'i
        # marker yozilgunga qadar qo'shimcha himoya bo'lib qoladi.
        await delivery_service.release_delivery_lock(delivery_lock_key, lock_token)

    await _finalize_sent_post(bot, ctx, sent_marker, sent_msg_id, target_chat)


async def _send_single_media(bot, target_chat, kind, file_id, caption, reply_markup, parse_mode="HTML", **delivery_kwargs):
    kind = (kind or "photo").lower()
    if kind == "video":
        return await _delivery_send(bot, "send_video", chat_id=target_chat, **delivery_kwargs, video=file_id, caption=caption, reply_markup=reply_markup, parse_mode=parse_mode)
    if kind == "document":
        return await _delivery_send(bot, "send_document", chat_id=target_chat, **delivery_kwargs, document=file_id, caption=caption, reply_markup=reply_markup, parse_mode=parse_mode)
    if kind == "audio":
        return await _delivery_send(bot, "send_audio", chat_id=target_chat, **delivery_kwargs, audio=file_id, caption=caption, reply_markup=reply_markup, parse_mode=parse_mode)
    if kind == "animation":
        return await _delivery_send(bot, "send_animation", chat_id=target_chat, **delivery_kwargs, animation=file_id, caption=caption, reply_markup=reply_markup, parse_mode=parse_mode)
    return await _delivery_send(bot, "send_photo", chat_id=target_chat, **delivery_kwargs, photo=file_id, caption=caption, reply_markup=reply_markup, parse_mode=parse_mode)


async def check_and_delete_expired_posts(bot):
    """Avto-o'chirish muddati yetgan xabarlarni kanaldan o'chirish (har 1 daqiqada).

    11-bosqich (P0): ``deleted=true`` FAQAT xabar haqiqatan o'chirilganda yoki
    Telegram uni topa olmaganda (``classify_delete_error == "gone"``) yoziladi.
    Vaqtinchalik xatoda (tarmoq, timeout, FloodWait) yozuv TEGILMAYDI —
    o'chirish ``AUTO_DELETE_RETRY_DELAY`` dan keyin qayta rejalashtiriladi.
    """
    try:
        now = now_tashkent()
        to_delete = await db.run_db(db.get_posts_to_delete, now)
        for item in to_delete:
            pid, ch_id, msg_id = item
            target_chat = int(ch_id) if str(ch_id).lstrip('-').isdigit() else ch_id
            try:
                await bot.delete_message(chat_id=target_chat, message_id=msg_id)
            except Exception as e:
                kind = classify_delete_error(e)
                if kind == "transient":
                    delay = AUTO_DELETE_RETRY_DELAY
                    if isinstance(e, RetryAfter):
                        delay = max(delay, flood_wait_seconds(e))
                    logger.warning(
                        "Avto-o'chirish vaqtinchalik xatosi (Post %s): %s — %.0fs dan keyin qayta uriniladi",
                        pid, e, delay,
                    )
                    await _defer_deletion(pid, delay)
                    continue
                # PHASE 9 & 10: gone (MessageNotFound) vs forbidden (bot kicked / no rights)
                # ikkalasi ham qayta urinilmaydi, lekin log'da ajratiladi (diagnostika).
                if kind == "forbidden":
                    logger.warning(
                        "Avto-o'chirish: bot huquqi yo'q / kanal topilmadi (Post %s): %s — qayta urinilmaydi",
                        pid, e,
                    )
                else:
                    logger.warning(f"Avto-o'chirish: xabar topilmadi yoki o'chirib bo'lmaydi (Post {pid}): {e}")
            await _mark_deleted_safe(pid)
    except Exception:
        logger.exception("Avto-o'chirish ishida kutilmagan xato")


async def _mark_deleted_safe(row_id) -> None:
    try:
        await db.run_db(db.mark_post_as_deleted, row_id)
    except Exception:
        logger.exception("Avto-o'chirish markerini yozishda xato (row %s)", row_id)


async def _defer_deletion(row_id, delay_seconds: float) -> None:
    try:
        fn = getattr(db, "defer_post_deletion", None)
        if fn is None:
            return
        await db.run_db(fn, row_id, int(delay_seconds))
    except Exception:
        logger.exception("Avto-o'chirishni kechiktirishda xato (row %s)", row_id)


async def recover_on_startup() -> dict:
    """Restart recovery (P0): bot ishga tushganda 'processing' da qolib
    ketgan postlarni XAVFSIZ tiklaydi — Telegramga chiqqanlari 'posted',
    UNKNOWN_DELIVERY bo'lganlari 'unknown', yuborilmaganlari 'pending'.

    ``check_and_send_posts`` birinchi tick'idan OLDIN chaqiriladi. Hech qachon
    istisno tashlamaydi.
    """
    try:
        fn = getattr(db, "recover_processing_posts_on_startup", None)
        if fn is None:
            await db.run_db(db.recover_stale_processing_posts)
            return {}
        result = await db.run_db(fn, 0) or {}
        if any(result.get(k) for k in ("posted", "unknown", "requeued")):
            logger.warning(
                "Restart recovery: posted=%s, unknown=%s, requeued=%s",
                result.get("posted"), result.get("unknown"), result.get("requeued"),
            )
        return result
    except Exception:
        logger.exception("Restart recovery xatosi")
        return {}


async def cleanup_old_data_job():
    """Eski ma'lumotlarni tozalash (har 6 soatda) — baza o'sib ketmasligi uchun."""
    try:
        result = await db.run_db(db.cleanup_old_data)
        logger.info("DB tozalash yakunlandi: %s", result)
    except Exception:
        logger.exception("DB tozalashda kutilmagan xato")


#: 📡 PHASE D (2/2) — bildirishnoma matni uchun yengil HTML-xavfsiz escape.
def _notice_escape(value) -> str:
    try:
        from utils.helpers import html_escape
        return html_escape(str(value or ""))
    except Exception:  # pragma: no cover — escape har doim mavjud
        return (str(value or "").replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))


async def poll_content_sources_job(bot=None):
    """📡 PHASE D (2/2) — vaqti kelgan RSS/ATOM manbalarini avtomatik tekshirish.

    Har 15 daqiqada bir marta: ``db.get_due_content_sources`` orqali intervali
    to'lgan FAOLLAR (``enabled``) manbalar olinadi va
    ``services.sources.rss_service.poll_due_sources`` ularni ketma-ket
    qayta ishlaydi:

      * har bir yangi element ``source_items`` ga yoziladi — **dublikat
        (UNIQUE(source_id, external_id)) qayta ishlanmaydi**;
      * har bir yangi element uchun Channel DNA asosida qoralama tayyorlanadi
        (``source_drafts``, status='pending');
      * ``autopublish`` YOQILGAN manbada qoralama ``autopublish_draft`` orqali
        ``scheduled_posts`` navbatiga yoziladi (keyin oddiy scheduler chiqaradi);
      * egasiga 3 tagacha qorlama haqida bildirishnoma yuboriladi.

    Kafolatlar:
      * **hech qachon istisno tashlamaydi** — bitta manba xatosi qolganlarini
        to'xtatmaydi (``poll_due_sources`` fail-soft) va job jim o'tib ketmaydi
        (xato loglanadi);
      * tarmoq/SSRF himoyasi servis qatlamida (5 MB / 10 s, ichki tarmoq
        bloklangan) — scheduler hech qanday havolani tekshirmasdan o'tkazmaydi;
      * bot ``None`` bo'lsa (test) bildirishnomalar yuborilmaydi, lekin
        tekshiruv va navbatga yozish baribir bajariladi.
    """
    try:
        from services.sources.rss_service import (
            MAX_SOURCES_PER_TICK,
            autopublish_draft,
            poll_due_sources,
        )
    except Exception:  # pragma: no cover — servis modulining o'zi yo'q
        logger.exception("Kontent manbalari: servis moduli yuklanmadi")
        return None

    async def _schedule_post(source, draft):
        """Qoralamani navbatga yozadi (autopublish)."""
        try:
            return await autopublish_draft(db, source, draft)
        except Exception:  # noqa: BLE001 — bitta post xatosi tick'ni to'xtatmaydi
            logger.exception("Kontent manbalari: avtopublish xatosi (id=%s)",
                             (source or {}).get("id"))
            return 0

    async def _notify(user_id, source, drafts):
        """Egasiga yangi qoralamalar haqida xabar yuboradi (≤3 ta)."""
        if bot is None or not user_id or not drafts:
            return
        from translations import sources_t
        from utils.telegram_sanitizer import sanitize_html
        lang = str((source or {}).get("lang") or "uz")
        channel = _notice_escape(str((source or {}).get("channel_title")
                                          or ""))
        for draft in list(drafts)[:3]:
            title = _notice_escape(str(draft.get("title") or "")[:120])
            text = sanitize_html(str(draft.get("text") or ""), 2000)
            try:
                await bot.send_message(
                    chat_id=int(user_id),
                    text=sources_t("src_rss_new_draft_notice", lang,
                                   channel=channel, title=title, text=text),
                    parse_mode="HTML",
                )
            except Exception:  # noqa: BLE001 — bloklangan bot xatosi job'ni
                logger.info("Kontent manbalari: bildirishnoma yuborilmadi "
                            "(user=%s)", user_id, exc_info=True)
                return

    try:
        with lifecycle.track("poll_content_sources"):
            summary = await poll_due_sources(
                db, notifier=_notify, schedule_post=_schedule_post,
                limit=MAX_SOURCES_PER_TICK)
        if summary.get("checked"):
            logger.info(
                "Kontent manbalari: tekshirildi=%s, yangi qoralama=%s, "
                "navbatga=%s, xato=%s", summary.get("checked"),
                summary.get("drafts"), summary.get("scheduled"),
                summary.get("errors"))
        return summary
    except Exception:  # noqa: BLE001 — scheduler hech qachon yiqilmaydi
        logger.exception("Kontent manbalari: poll ishida kutilmagan xato")
        return None


async def subscription_sweep_job():
    """3-BOSQICH (P1): muddati o'tgan PRO/enterprise obunalarni FREE ga tushirish.

    Har 15 daqiqada bitta indeksli UPDATE — obuna muddati tugagan foydalanuvchi
    ``SubscriptionService.get_status`` chaqirilmasa ham PRO AI/kanal limitlarida
    qolib ketmaydi. Hech qachon istisno tashlamaydi (scheduler barqarorligi).
    """
    try:
        count = await db.run_db(db.downgrade_expired_subscriptions)
        if count:
            logger.warning(
                "Obuna sweep: %d ta muddati o'tgan PRO/enterprise foydalanuvchi FREE ga tushirildi.",
                count,
            )
    except Exception:
        logger.exception("Obuna sweep ishida kutilmagan xato")


async def cleanup_old_records_job():
    """9-bosqich: kunlik (03:00 Toshkent) paketli tozalash worker'i.

    ``services.cleanup_service.cleanup_old_records`` — 30 kundan eski 'sent'
    delivery jurnallari va 60 kundan eski / bekor qilingan vaqtinchalik
    sessiya-kredit qoldiqlari LIMIT 1000 paketlar bilan, har paket alohida
    tranzaksiyada o'chiriladi (katta jadval qulflanmaydi). Faol/yangi
    yozuvlarga tegilmaydi. Hech qachon istisno ko'tarmaydi.
    """
    try:
        with lifecycle.track("cleanup_old_records"):
            summary = await cleanup_old_records()
        if summary.get("errors"):
            logger.warning("Kunlik tozalash xatolar bilan yakunlandi: %s", summary)
        else:
            logger.info("Kunlik tozalash yakunlandi: jami %s ta yozuv o'chirildi.",
                        summary.get("total", 0))
        return summary
    except Exception:
        logger.exception("Kunlik tozalashda kutilmagan xato")
        return None


# ============================================================
# PHASE E — WEEKLY CHANNEL ADVISOR DELIVERY
# ============================================================
async def weekly_channel_reports_job(bot=None):
    """Send a compact report to each channel owner every Monday morning.

    Delivery is best-effort and never touches the channel itself.  A missing
    report, a Telegram error, or a database error skips that owner and lets the
    scheduler continue with the remaining channels.
    """
    if bot is None:
        return {"sent": 0, "skipped": 0}
    sent = skipped = 0
    try:
        channels = await db.run_db(db.get_all_channels)
    except Exception:
        logger.exception("Weekly Channel Advisor: kanallarni olishda xato")
        return {"sent": 0, "skipped": 0, "error": "db"}
    from services.channels.advisor import compute_weekly_insights, render_report_card
    for row in channels or ():
        try:
            channel_id, title, owner_id = row[0], row[1], row[2]
            owner_id = int(owner_id)
            records = await db.run_db(db.get_channel_weekly_posts, str(channel_id), 7)
            report = compute_weekly_insights(records or [])
            card = render_report_card(report, channel_title=str(title or channel_id))
            await bot.send_message(chat_id=owner_id, text="🗓 <b>Dushanba kanal hisoboti</b>\n\n" + card,
                                   parse_mode="HTML")
            sent += 1
        except Exception:
            skipped += 1
            logger.warning("Weekly Channel Advisor: bitta kanal egasiga yuborilmadi", exc_info=True)
    return {"sent": sent, "skipped": skipped}


# ============================================================
# 🌅 DAILY CONTENT RETENTION + 🗓 UZBEKISTAN CALENDAR
# ============================================================
def _nudge_row_values(row):
    """Normalize one repository nudge row without trusting database strings."""
    if isinstance(row, dict):
        return (
            row.get("channel_id"), row.get("channel_title"), row.get("user_id"),
            row.get("language_code") or row.get("lang") or "uz",
            row.get("topics"), row.get("tone") or "",
        )
    try:
        values = list(row)
        values += [None] * max(0, 6 - len(values))
        return (values[0], values[1], values[2], values[3] or "uz", values[4], values[5] or "")
    except (TypeError, IndexError):
        return (None, None, None, "uz", None, "")


async def daily_morning_digest_job(bot=None, now=None):
    """Send one opt-in 09:00 (Tashkent) content-gap nudge per eligible channel.

    The job does no AI calls and uses Channel DNA topics only when already
    available. A single SQL anti-join excludes both Bot-posted and observed
    channel posts newer than the 48-hour cutoff.
    """
    if bot is None:
        return {"sent": 0, "skipped": 0}
    from services.retention import (
        DEFAULT_CONTENT_GAP_HOURS,
        build_content_ideas,
        build_daily_digest_text,
        normalize_lang,
    )

    if isinstance(now, date) and not isinstance(now, datetime):
        current = tashkent_tz.localize(datetime.combine(now, datetime.min.time()))
    else:
        current = _as_tashkent(now) if now is not None else now_tashkent()
    if current is None:
        current = now_tashkent()
    since = current - timedelta(hours=DEFAULT_CONTENT_GAP_HOURS)
    try:
        rows = await db.run_db(
            db.get_channels_for_content_nudges,
            "notify_morning_digest",
            since,
        ) or []
    except Exception:
        logger.exception("Daily morning digest: nudge recipients could not be loaded")
        return {"sent": 0, "skipped": 0, "error": "db"}

    from handlers.daily_retention import build_morning_digest_keyboard
    sent = skipped = 0
    for row in rows:
        channel_id, channel_title, user_id, lang, topics, _tone = _nudge_row_values(row)
        try:
            user_id = int(user_id)
            channel_id = str(channel_id or "").strip()
            if user_id <= 0 or not channel_id:
                skipped += 1
                continue
            lang = normalize_lang(lang)
            ideas = build_content_ideas(channel_title or "", topics, lang)
            await bot.send_message(
                chat_id=user_id,
                text=build_daily_digest_text(channel_title or "", ideas, lang),
                reply_markup=build_morning_digest_keyboard(channel_id, lang),
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            skipped += 1
            logger.info("Daily morning digest not delivered (user=%s)", user_id,
                        exc_info=True)
    logger.info("Daily morning digest completed: sent=%s skipped=%s", sent, skipped)
    return {"sent": sent, "skipped": skipped}


async def uzbekistan_calendar_reminders_job(bot=None, today=None):
    """Send opt-in localized reminders exactly three days before calendar dates."""
    if bot is None:
        return {"sent": 0, "skipped": 0}
    from services.retention import normalize_lang
    from services.uzbekistan_calendar import (
        calendar_reminder_text,
        get_events_for_reminder,
    )

    current = today
    if current is None:
        current = now_tashkent().date()
    elif isinstance(current, datetime):
        current = _as_tashkent(current).date()
    try:
        events = get_events_for_reminder(current, 3)
    except (TypeError, ValueError):
        events = ()
    if not events:
        return {"sent": 0, "skipped": 0}

    try:
        rows = await db.run_db(
            db.get_channels_for_content_nudges,
            "notify_uzbek_calendar",
            None,
        ) or []
    except Exception:
        logger.exception("Uzbekistan calendar: nudge recipients could not be loaded")
        return {"sent": 0, "skipped": 0, "error": "db"}

    from handlers.daily_retention import build_calendar_reminder_keyboard
    sent = skipped = 0
    for row in rows:
        channel_id, _channel_title, user_id, lang, _topics, _tone = _nudge_row_values(row)
        try:
            user_id = int(user_id)
            channel_id = str(channel_id or "").strip()
            if user_id <= 0 or not channel_id:
                skipped += len(events)
                continue
            lang = normalize_lang(lang)
            for event in events:
                await bot.send_message(
                    chat_id=user_id,
                    text=calendar_reminder_text(event, lang),
                    reply_markup=build_calendar_reminder_keyboard(event.key, channel_id, lang),
                    parse_mode="HTML",
                )
                sent += 1
        except Exception:
            skipped += 1
            logger.info("Uzbekistan calendar reminder not delivered (user=%s)", user_id,
                        exc_info=True)
    logger.info("Uzbekistan calendar reminders completed: sent=%s skipped=%s", sent, skipped)
    return {"sent": sent, "skipped": skipped}
