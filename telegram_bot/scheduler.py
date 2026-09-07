import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime, timedelta
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
from config import ADMIN_IDS_SET, BOT_USERNAME
import database as db
from keyboards.inline import (
    normalize_custom_reaction_emojis,
    strip_leading_reaction_glyphs,
    DEFAULT_REACTION_EMOJIS,
)
from keyboards.callback_data import CB_REACTION, cb
from utils.helpers import (
    get_channel_ad_next_async,
    get_channel_ad_next_full_async,
    should_show_channel_ad,
    apply_post_watermark,
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

# FloodWait kutishining yuqori chegarasi: Telegram juda katta `retry_after`
# qaytarsa (masalan 900s) scheduler ishini butunlay muzlatib qo'ymaymiz —
# shu chegaragacha kutamiz, qolganini `retry_post` orqali DB'ga ko'chiramiz.
FLOOD_WAIT_SLEEP_MAX = 60.0

# --- IDEMPOTENT YUBORISH: "yuborildi" markeri kafolati -----------------------
# Post Telegramga chiqqach DB'ga 'posted' + sent_message_id yozilishi SHART —
# aks holda stale-recovery uni 10 daqiqadan keyin 'pending' ga qaytaradi va
# post IKKINCHI marta chiqadi. Neon'da qisqa uzilishlar bo'lib turadi, shuning
# uchun marker yozuvi:
#   1) eksponensial backoff bilan bir necha marta qayta uriniladi;
#   2) baribir yozilmasa — xotiradagi ``_UNPERSISTED_SENT`` ro'yxatiga va
#      lokal journal fayliga tushadi. Shu jarayon ichida o'sha post hech
#      qachon qayta yuborilmaydi (``_execute_send`` boshida guard), har
#      scheduler tick'i boshida marker qayta yozishga urinadi
#      (``flush_unpersisted_sent_markers``) — DB tiklanishi bilan holat
#      to'g'rilanadi. Journal restartdan keyin ham o'qiladi (best-effort).
SENT_MARKER_RETRY_DELAYS = (0.5, 1.0, 2.0, 4.0)


def _resolve_sent_journal_path() -> str:
    """SENT_JOURNAL_PATH env: yo'l → shu fayl; 'off'/'none'/'0' → o'chirilgan ('');
    berilmagan → vaqtinchalik papkadagi standart fayl."""
    raw = os.getenv("SENT_JOURNAL_PATH")
    if raw is None:
        return os.path.join(tempfile.gettempdir(), "postassist_sent_journal.json")
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
                       end_date=None) -> dict:
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
    if not marker.get("marker_done"):
        ok = False
        try:
            ok = _db_ok(await db.run_db(
                db.mark_post_as_sent, pid, marker.get("message_id"), marker.get("channel_id"),
                int(marker.get("delete_after_hours") or 0), marker.get("extra_ids") or None,
            ))
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

    # Channel ad'ni qo'shish (faqat ad-free litsenziyasi yo'q foydalanuvchilar uchun)
    if not has_ad_free and ad:
        text = f"{text}\n\n{ad}" if text else ad

    brand = (brand_text or "").strip()
    limit = int(limit) if limit else 0

    # Limit bo'yicha kesish (brand_text uchun joy zaxiralash)
    if limit > 0:
        if brand:
            # Nishon va uni ajratuvchi ikki qator uchun joy zaxiraga olinadi
            reserved = len(brand) + 2
            allowed = max(0, limit - reserved)
            if len(text) > allowed:
                text = text[:allowed].rstrip()
        elif len(text) > limit:
            text = text[:limit]

    # Brand text'ni qo'shish (admin tomonidan sozlangan bo'lsa)
    if brand:
        text = f"{text}\n\n{brand}" if text else brand

    # Yakuniy limit tekshiruvi
    if limit > 0 and len(text) > limit:
        # Nishonning o'zi limitdan uzun bo'lgan chekka holat
        text = text[:limit]
    return text


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
        cap = caption if i == 0 else None
        parse = "HTML" if cap else None
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
        # 0) Avvalgi tick'larda DB'ga yozilmay qolgan "yuborildi" markerlari —
        #    yangi postlarni olishdan OLDIN yoziladi (idempotentlik kafolati).
        await flush_unpersisted_sent_markers()
        now = now_tashkent()
        due_posts = await db.run_db(db.get_due_posts, now)
        if due_posts:
            logger.info("Yuboriladigan postlar soni: %d", len(due_posts))
        for index, post in enumerate(due_posts):
            # 1) Mikro-kechikish — birinchi postdan keyin har safar.
            if index:
                await asyncio.sleep(SEND_MICRO_DELAY)
            try:
                await _execute_send(bot, post)
            except RetryAfter as e:
                # 2) Telegram FloodWait (429): ko'rsatilgan muddat kutiladi va
                # navbat XAVFSIZ davom ettiriladi (post qayta navbatga qo'yiladi).
                wait_seconds = flood_wait_seconds(e)
                logger.warning(
                    "Telegram FloodWait (429): %.0fs kutilmoqda (Post ID: %s)",
                    wait_seconds, post[0] if post else "?",
                )
                await asyncio.sleep(wait_seconds)
                await _requeue_post(post, wait_seconds)
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


async def _execute_send(bot, post):
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
        return

    # 1. Post holatini Telegramga yuborishdan oldin qat'iy "processing" qilib belgilaymiz (processing_started_at bilan)
    if await db.run_db(db.mark_post_processing, post_id) is False:
        # DB hozir yozuvni qabul qilmayapti — yuborishdan OLDIN to'xtaymiz
        # (aks holda yuborilgach marker ham yozilmay qolishi ehtimoli katta).
        # Chaqiruvchi (check_and_send_posts) postni qayta navbatga qo'yadi.
        raise RuntimeError(f"DB 'processing' markerini yozib bo'lmadi (Post ID: {post_id})")

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

    # WATERMARK: Bepul foydalanuvchilar postlariga bot username qo'shish
    watermarked_content = await apply_post_watermark(clean_content, user_id, BOT_USERNAME)

    sent_msg = None
    extra_ids = []
    try:
        # Telegram caption limiti 1024, oddiy matn limiti 4096 belgidan iborat.
        # Limit compose_post_text ichida qo'llanadi — nishon kesishdan KEYIN
        # qo'shiladi, shuning uchun u hech qachon kesilib ketmaydi.
        pt_for_limit = str(post_type).lower()
        text_limit = (
            1024 if pt_for_limit in
            ("photo", "video", "animation", "document", "audio", "voice", "album")
            else 4096
        )
        final_content = compose_post_text(
            watermarked_content, has_ad_free, channel_ad, brand_text, limit=text_limit
        )
    except Exception:
        logger.exception("Post matnini tayyorlashda xatolik (Post ID: %s)", post_id)
        await db.run_db(db.mark_post_status, post_id, "failed")
        return

    try:
        pt = str(post_type).lower()
        target_chat = int(channel_id) if str(channel_id).lstrip('-').isdigit() else channel_id

        if pt == "album":
            items = parse_album_items(file_id)
            if not items:
                logger.error("Albom tarkibi bo'sh (Post ID: %s)", post_id)
                await db.run_db(db.mark_post_status, post_id, "failed")
                return
            if len(items) == 1:
                # Bitta element — oddiy media (tugmalar ishlashi uchun)
                only = items[0]
                sent_msg = await _send_single_media(
                    bot, target_chat, only["type"], only["file_id"], final_content, reply_markup
                )
            else:
                media = _build_album_media(items, final_content)
                sent_group = await bot.send_media_group(chat_id=target_chat, media=media)
                sent_msg = sent_group[0] if sent_group else None
                extra_ids = [m.message_id for m in (sent_group or [])[1:] if getattr(m, "message_id", None)]
                # sendMediaGroup reply_markup'ni qo'llab-quvvatlamaydi — tugmalarni alohida xabar
                if reply_markup:
                    follow = await bot.send_message(
                        chat_id=target_chat, text="🔗", reply_markup=reply_markup
                    )
                    if follow and follow.message_id:
                        extra_ids.append(follow.message_id)
        elif pt == "photo":
            sent_msg = await bot.send_photo(chat_id=target_chat, photo=file_id, caption=final_content, reply_markup=reply_markup, parse_mode="HTML")
        elif pt == "video":
            sent_msg = await bot.send_video(chat_id=target_chat, video=file_id, caption=final_content, reply_markup=reply_markup, parse_mode="HTML")
        elif pt == "animation":
            sent_msg = await bot.send_animation(chat_id=target_chat, animation=file_id, caption=final_content, reply_markup=reply_markup, parse_mode="HTML")
        elif pt == "document":
            sent_msg = await bot.send_document(chat_id=target_chat, document=file_id, caption=final_content, reply_markup=reply_markup, parse_mode="HTML")
        elif pt == "audio":
            sent_msg = await bot.send_audio(chat_id=target_chat, audio=file_id, caption=final_content, reply_markup=reply_markup, parse_mode="HTML")
        elif pt == "voice":
            sent_msg = await bot.send_voice(chat_id=target_chat, voice=file_id, caption=final_content, reply_markup=reply_markup, parse_mode="HTML")
        elif pt == "sticker":
            sent_msg = await bot.send_sticker(
                chat_id=target_chat, sticker=file_id, reply_markup=reply_markup
            )
        else:
            sent_msg = await bot.send_message(chat_id=target_chat, text=final_content or " ", reply_markup=reply_markup, parse_mode="HTML")

        sent_msg_id = sent_msg.message_id if sent_msg else None
        # Post Telegramga muvaffaqiyatli yuborildi! Bundan keyin HECH QANDAY
        # holatda (DB xatosi, restart) post qayta yuborilmasligi kerak:
        # marker (posted + sent_message_id + takrorlash rejasi) backoff bilan
        # yoziladi; yozilmasa xotira/journal guard'ida qoladi.
        sent_marker = _build_sent_marker(
            post_id, sent_msg_id, channel_id, delete_after_hours, extra_ids,
            recurrence_type, recurrence_day, recurrence_time, end_date,
        )

    except RetryAfter as e:
        # Telegram rate-limit (FloodWait, 429) — vaqtinchalik holat.
        # 1) Telegram ko'rsatgan muddat davomida JIM turamiz (aks holda
        #    keyingi so'rovlar ham 429 bilan qaytadi va limit uzayadi).
        # 2) Post yo'qolmasligi uchun qayta navbatga qo'yamiz.
        wait_seconds = flood_wait_seconds(e)
        logger.warning(
            "Telegram FloodWait (Post ID: %s), %.0fs kutiladi va qayta uriniladi",
            post_id, wait_seconds,
        )
        await asyncio.sleep(wait_seconds)
        retry_at = now_tashkent() + timedelta(seconds=wait_seconds)
        await db.run_db(db.retry_post, post_id, retry_at)
        return
    except (TimedOut, NetworkError) as e:
        logger.warning(f"Telegram tarmoq xatosi (Post ID: {post_id}): {e}; qayta uriniladi")
        retry_at = now_tashkent() + timedelta(seconds=NETWORK_RETRY_DELAY)
        await db.run_db(db.retry_post, post_id, retry_at)
        return
    except TelegramError as e:
        logger.error(f"Post yuborishda xato (Post ID: {post_id}): {e}")
        await db.run_db(db.mark_post_status, post_id, "failed")
        return

    # Yuborildi → marker (posted / takrorlanuvchi: keyingi vaqt + pending /
    # muddati tugagan: completed). Hech qachon istisno tashlamaydi — shuning
    # uchun yuborilgan post hech qachon _requeue_post ga tushmaydi.
    await _persist_sent_marker(sent_marker)


async def _send_single_media(bot, target_chat, kind, file_id, caption, reply_markup):
    kind = (kind or "photo").lower()
    if kind == "video":
        return await bot.send_video(chat_id=target_chat, video=file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
    if kind == "document":
        return await bot.send_document(chat_id=target_chat, document=file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
    if kind == "audio":
        return await bot.send_audio(chat_id=target_chat, audio=file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
    if kind == "animation":
        return await bot.send_animation(chat_id=target_chat, animation=file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
    return await bot.send_photo(chat_id=target_chat, photo=file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")


async def check_and_delete_expired_posts(bot):
    """Avto-o'chirish muddati yetgan xabarlarni kanaldan o'chirish (har 1 daqiqada)."""
    try:
        now = now_tashkent()
        to_delete = await db.run_db(db.get_posts_to_delete, now)
        for item in to_delete:
            pid, ch_id, msg_id = item
            try:
                target_chat = int(ch_id) if str(ch_id).lstrip('-').isdigit() else ch_id
                await bot.delete_message(chat_id=target_chat, message_id=msg_id)
            except Exception as e:
                logger.warning(f"Avto-o'chirish xatosi (Post {pid}): {e}")
            finally:
                # Xabar topilmasa ham, qayta-qayta urinmaslik uchun bazada belgilab qo'yamiz.
                await db.run_db(db.mark_post_as_deleted, pid)
    except Exception:
        logger.exception("Avto-o'chirish ishida kutilmagan xato")


async def cleanup_old_data_job():
    """Eski ma'lumotlarni tozalash (har 6 soatda) — baza o'sib ketmasligi uchun."""
    try:
        result = await db.run_db(db.cleanup_old_data)
        logger.info("DB tozalash yakunlandi: %s", result)
    except Exception:
        logger.exception("DB tozalashda kutilmagan xato")
