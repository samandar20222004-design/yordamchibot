"""📡 KANAL MONITORINGI VA EVENT INGESTION (PostAssist V2 — PHASE B, 1-band).

Kanalga yangi post yoki tahrirlangan post tushganda (PTB channel-post
update'lari) metama'lumotlar ASINXRON VA BLOKLAMAYDIGAN rejimda
``channel_post_events`` jadvaliga yoziladi:

    channel_id, message_id, post_hour, post_weekday, has_media, media_type,
    media_file_id, length, cta_detected, emoji_density, created_at

Xavfsizlik va barqarorlik kafolatlari:
  * **Idempotency** — ``(channel_id, message_id)`` UNIQUE + ``ON CONFLICT
    DO NOTHING``: duplicate eventlar (tahrirlangan post, qayta update)
    qayta yozilmaydi;
  * **Media fayllar SAQLANMAYDI** — bazaga faqat ``media_file_id`` va
    ``media_type`` (turi) tushadi (hech qanday blob/ fayl mazmuni yo'q);
  * **Fail-soft** — hech qanday xato bot oqimini to'xtatmaydi (log +
    o'tkazib yuborish); ``schedule_post_event_ingest`` background task
    yaratadi va handler hech narsa kutmaydi (event loop bloklanmaydi).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any

import pytz

logger = logging.getLogger(__name__)

#: Post vaqt/kun hisob-kitoblari YAGONA vaqt zonada (scheduler bilan bir xil —
#: Asia/Tashkent, UTC+5).
TASHKENT_TZ = pytz.timezone("Asia/Tashkent")
UTC_TZ = pytz.utc

# ---------------------------------------------------------------------------
# EMOJI zichligi
# ---------------------------------------------------------------------------
# Keng qamrovli, lekin yengil emoji diapazonlari (pictographs, transport,
# symbolik belgilar, emoji ko'rsatkichlari va variation/ZWJ teglar).
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # smiley, emoticon, tashkilot, transport, suv, supplemental
    "\u2600-\u27BF"          # ob-havo, sport, dingbats
    "\u2300-\u23FF"          # soat/soat belgilari (⌛ ⏰)
    "\u2B00-\u2BFF"          # yulduzlar/ko'rsatkichlar (⭐)
    "\u25A0-\u25FF"          # geometrik shakllar (▪️)
    "\u2190-\u21FF"          # strelkalar (↩️)
    "\u2700-\u27BF"          # qoralashlar (✂️ ✅)
    "\uFE0F"                 # variation selector
    "\u200D"                 # zero-width joiner
    "\u203C\u2049"           # ‼ ⁉
    "\u00A9\u00AE"           # © ®
    "\u2764"                 # ❤
    "]",
    flags=re.UNICODE,
)


def emoji_density(text: str) -> float:
    """Matndagi emoji zichligi: emoji soni / matn uzunligi.

    Bo'sh matnda 0.0. Katta/uzun matnlarda ~0.0–0.05 oralig'ida bo'ladi
    (masalan 450 belgili matnda 4 ta emoji ≈ 0.009).
    """
    if not text:
        return 0.0
    try:
        found = _EMOJI_RE.findall(text or "")
        return round(len(found) / max(1, len(text)), 6)
    except Exception:  # pragma: no cover — regex deyarli yiqilmaydi
        return 0.0


# ---------------------------------------------------------------------------
# CTA aniqlash (uz / ru / en)
# ---------------------------------------------------------------------------
_CTA_KEYWORDS = (
    # 🇺🇿 O'zbekcha
    "buyurtma", "bosing", "bosib", "obuna", "obunaga", "obunaboring",
    "sotib oling", "sotib olish", "ro'yxatdan", "yozib qoling", "hamdam",
    "shartnoma", "boshqaruv", "tugmani bosing", "hazirdan", "hozirdan",
    "arizangizni", "so'rov yuboring", "biz bilan",
    # 🇷🇺 Rus tili
    "подпишись", "подписка", "подписаться", "подпишусь", "закажи",
    "заказать", "заказ", "купить", "купи ", "куплю", "нажми", "нажми ",
    "напиши", "написать", "перейди", "переход", "ссылк", "жми",
    "не пропуст", "забронируй", "останься",
    # 🇬🇧 English
    "subscribe", "follow us", "order now", "buy now", "shop now",
    "click ", "tap the", "tap to", "link in", "sign up", "join us",
    "act now", "don't miss", "dont miss", "learn more",
    # Cross-language CTA hints
    "👉", "👇", "🔗",
)


def detect_cta(text: str) -> bool:
    """Matnda CTA (call-to-action) belgilarini aniqlaydi (uz/ru/en)."""
    if not text:
        return False
    lowered = (text or "").lower()
    for kw in _CTA_KEYWORDS:
        if kw in lowered:
            return True
    return False


# ---------------------------------------------------------------------------
# Media tahlili (faqat file_id va turi — fayl mazmuni SAQLANMAYDI)
# ---------------------------------------------------------------------------
_MEDIA_CHECKS = (
    ("video", "video"),
    ("video_note", "video_note"),
    ("animation", "animation"),
    ("audio", "audio"),
    ("document", "document"),
    ("photo", "photo"),
    ("sticker", "sticker"),
    ("poll", "poll"),
)


def _photo_file_id(photo) -> str | None:
    """Foto guruhidagi ENG KATTA nusxaning file_id (rasm mazmuni emas).

    PTB v21+ da ``Message.photo`` — PhotoSize'lar TUPLE'isi; eski versiyalarda
    esa obyekt sifatida berilishi mumkin — ikkala shaklni qabul qilamiz.
    """
    try:
        if isinstance(photo, (list, tuple)):
            sizes = list(photo)
        else:
            sizes = list(getattr(photo, "photo", None) or [])
        if not sizes:
            return None
        largest = max(sizes, key=lambda s: int(getattr(s, "file_size", 0) or 0))
        return getattr(largest, "file_id", None)
    except Exception:
        return None


def media_info(message: Any) -> tuple[bool, str | None, str | None]:
    """Xabardan media ma'lumotini ajratadi: ``(has_media, media_type, file_id)``.

    Faqat ``file_id`` va turi qaytariladi — media faylining o'zi bazaga
    yoki xotiraga qo'yilmaydi.
    """
    for attr, mtype in _MEDIA_CHECKS:
        obj = getattr(message, attr, None)
        if obj is None:
            continue
        if attr == "photo":
            fid = _photo_file_id(obj)
            if fid:
                return True, mtype, str(fid)[:255]
            return True, mtype, None
        fid = getattr(obj, "file_id", None)
        if fid:
            return True, mtype, str(fid)[:255]
        return True, mtype, None
    return False, None, None


# ---------------------------------------------------------------------------
# Event metama'lumotini ajratish (PURE funksiya — test uchun qulay)
# ---------------------------------------------------------------------------
def extract_event_metadata(message: Any) -> dict:
    """PTB ``Message`` (channel_post) dan ``channel_post_events`` qatorini quradi.

    Vaqt/kun ``Asia/Tashkent`` zonasi bo'yicha:
      * ``post_hour``    — 0..23;
      * ``post_weekday`` — 0 (Dushanba) .. 6 (Yakshanba).

    Xabar ``date`` yo'q bo'lsa hozirgi vaqt olinadi. Hech qachon istisno
    ko'tarmaydi — eng yomonsi ``None``/``0`` qadriyatlar bilan qaytadi.
    """
    channel_id = ""
    message_id = None
    text = ""
    has_media, media_type, file_id = False, None, None
    post_dt = None

    try:
        chat = getattr(message, "chat", None)
        if chat is not None:
            channel_id = str(getattr(chat, "id", "") or "")
        message_id = getattr(message, "message_id", None)
        text = (getattr(message, "text", None)
                or getattr(message, "caption", None)
                or "").strip()
        has_media, media_type, file_id = media_info(message)
        raw_date = getattr(message, "date", None)
        if raw_date is not None:
            if raw_date.tzinfo is None:
                post_dt = UTC_TZ.localize(raw_date)
            else:
                post_dt = raw_date.astimezone(UTC_TZ)
    except Exception as e:  # pragma: no cover — har doim qaytadi
        logger.debug("extract_event_metadata: qiymat olishda xato: %s", e)

    if post_dt is None:
        post_dt = datetime.now(UTC_TZ)
    try:
        tashkent_dt = post_dt.astimezone(TASHKENT_TZ)
        post_hour = int(tashkent_dt.hour)
        post_weekday = int(tashkent_dt.weekday())  # 0=Dushanba..6=Yakshanba
    except Exception:  # pragma: no cover
        post_hour, post_weekday = 0, 0

    return {
        "channel_id": channel_id,
        "message_id": message_id,
        "post_hour": post_hour,
        "post_weekday": post_weekday,
        "has_media": bool(has_media),
        "media_type": media_type,
        "media_file_id": file_id,
        "length": len(text),
        "cta_detected": detect_cta(text),
        "emoji_density": emoji_density(text),
    }


# ---------------------------------------------------------------------------
# Asinxron ingestion (bloklamaydigan rejim)
# ---------------------------------------------------------------------------
def _import_database():
    try:
        import database as _db
        return _db
    except Exception:  # pragma: no cover
        return None


async def ingest_channel_post_event(message: Any, db_module: Any = None) -> bool:
    """Bitta kanal postining metama'lumotini bazaga yozadi (idempotent).

    Qaytadi: ``True`` — yangi event qo'shildi; ``False`` — duplicate
    (ON CONFLICT DO NOTHING) yoki xato. Xatolar log'da — istisno yo'q.
    """
    if message is None:
        return False
    try:
        meta = extract_event_metadata(message)
    except Exception as e:
        logger.warning("channel event metadata xatosi: %s", e)
        return False
    if not meta["channel_id"] or meta["message_id"] is None:
        return False
    db = db_module if db_module is not None else _import_database()
    if db is None or not hasattr(db, "insert_channel_post_event"):
        logger.debug("DB modul mavjud emas — channel event o'tkazib yuborildi")
        return False
    try:
        run_db = getattr(db, "run_db", None)
        if run_db is not None:
            inserted = await run_db(
                db.insert_channel_post_event,
                channel_id=meta["channel_id"],
                message_id=meta["message_id"],
                post_hour=meta["post_hour"],
                post_weekday=meta["post_weekday"],
                has_media=meta["has_media"],
                media_type=meta["media_type"],
                media_file_id=meta["media_file_id"],
                length=meta["length"],
                cta_detected=meta["cta_detected"],
                emoji_density=meta["emoji_density"],
            )
        else:  # pragma: no cover — sinov muhitlaridagi minimal fake DB
            inserted = db.insert_channel_post_event(
                channel_id=meta["channel_id"],
                message_id=meta["message_id"],
                post_hour=meta["post_hour"],
                post_weekday=meta["post_weekday"],
                has_media=meta["has_media"],
                media_type=meta["media_type"],
                media_file_id=meta["media_file_id"],
                length=meta["length"],
                cta_detected=meta["cta_detected"],
                emoji_density=meta["emoji_density"],
            )
        return bool(inserted)
    except Exception as e:
        logger.warning("channel_post_events yozishda xato (%s): %s",
                       meta["channel_id"], e)
        return False


async def _guarded_ingest(message: Any, db_module: Any = None) -> None:
    """Background task o'rami — exception'ni yutib loglaydi (leak yo'q)."""
    try:
        await ingest_channel_post_event(message, db_module=db_module)
    except Exception as e:  # noqa: BLE001 — task hech qachon yiqitilmaydi
        logger.warning("channel event ingestion (background) xatosi: %s", e)


def schedule_post_event_ingest(message: Any, db_module: Any = None) -> "asyncio.Task | None":
    """Event ingestionni BACKGROUND TASK sifatida boshlaydi (non-blocking).

    Handler ``await`` QILMAYDI — event loop bloklanmaydi, DB so'rovi
    alohida task/thread'da bajariladi. Task'ga ulangan exception-guard
    "Task exception was never retrieved" ogohlantirishini oldini oladi.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Event loop yo'q (misol uchun oddiy CLI) — bloklamaymiz, o'tkazib
        # yuboramiz (monitoring bot funksionalligi uchun shart emas).
        logger.debug("Event loop yo'q — channel event ingestion o'tkazib yuborildi")
        return None
    task = loop.create_task(_guarded_ingest(message, db_module))
    return task
