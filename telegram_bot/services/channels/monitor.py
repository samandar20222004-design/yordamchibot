"""📡 CHANNEL MONITOR — asinxron monitoring va batch agregatsiya (FAZA 8,9,22).

Qat'iy qoidalar:
  * Har bir kanal posti kelganda AI CHAQIRILMAYDI!
  * Faqat yengil xom ma'lumot (uzunlik, vaqt, media turi) -> DB event yozish.
  * Tahlil faqat batch ko'rinishida yoki foydalanuvchi "Kanal tahlili"ni so'raganda.

Bu modul ``monitoring.py`` (ko'plik) ning idempotent, AI'siz, batch varianti.
Hech qanday AI import yo'q — server va kvotani asrash uchun.

Ish oqimi:
  Telegram update -> extract_lightweight_metadata -> insert_channel_post_event
  (ON CONFLICT DO NOTHING idempotent).

Batch:
  batch_aggregate_channel(channel_id) -> get_channel_post_events -> compute_channel_dna_extended
  -> save_channel_dna_profile (UPSERT, ON CONFLICT DO NOTHING bilan xavfsiz).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Reuse lightweight helpers from monitoring.py if available, but implement
# own version to avoid accidental AI calls and to be self-contained.
try:
    from services.channels.monitoring import (
        extract_event_metadata as _monitoring_extract,
        emoji_density as _emoji_density,
        detect_cta as _detect_cta,
        media_info as _media_info,
    )
except Exception:  # pragma: no cover — fallback if monitoring not importable
    _monitoring_extract = None
    _emoji_density = None
    _detect_cta = None
    _media_info = None

try:
    from services.channels.dna import compute_channel_dna_extended, confidence_float
except Exception:  # pragma: no cover
    compute_channel_dna_extended = None
    confidence_float = None

# Timezones — reuse if monitoring provides, else fallback
try:
    from services.channels.monitoring import TASHKENT_TZ, UTC_TZ
except Exception:
    import pytz
    TASHKENT_TZ = pytz.timezone("Asia/Tashkent")
    UTC_TZ = pytz.UTC


def _import_database():
    try:
        import database as _db
        return _db
    except Exception:  # pragma: no cover
        return None


# ---------------------------------------------------------------------------
# Yengil metadata ajratish (AI'siz, PURE)
# ---------------------------------------------------------------------------
def extract_lightweight_metadata(message: Any) -> dict:
    """PTB Message dan yengil xom ma'lumot (AI'siz).

    Qaytadi: channel_id, message_id, post_hour, post_weekday, has_media,
    media_type, media_file_id, length, cta_detected, emoji_density.
    Hech qachon istisno ko'tarmaydi.
    """
    # If monitoring module available, delegate to its pure function (also AI'siz)
    if _monitoring_extract is not None:
        try:
            return _monitoring_extract(message)
        except Exception as e:
            logger.debug("monitor: monitoring.extract_event_metadata xato: %s", e)

    # Fallback self-contained implementation (no AI)
    channel_id = ""
    message_id = None
    text = ""
    has_media = False
    media_type = None
    file_id = None
    post_dt = None

    try:
        chat = getattr(message, "chat", None)
        if chat is not None:
            channel_id = str(getattr(chat, "id", "") or "")
        message_id = getattr(message, "message_id", None)
        text = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()

        # Minimal media detection without importing heavy logic
        for attr in ("video", "video_note", "animation", "audio", "document", "photo", "sticker", "poll"):
            obj = getattr(message, attr, None)
            if obj is not None:
                has_media = True
                media_type = attr
                # Try file_id
                try:
                    if attr == "photo":
                        # photo is list/tuple
                        sizes = obj if isinstance(obj, (list, tuple)) else getattr(obj, "photo", None) or []
                        if sizes:
                            largest = max(sizes, key=lambda s: int(getattr(s, "file_size", 0) or 0))
                            file_id = getattr(largest, "file_id", None)
                    else:
                        file_id = getattr(obj, "file_id", None)
                except Exception:
                    file_id = None
                break

        raw_date = getattr(message, "date", None)
        if raw_date is not None:
            if raw_date.tzinfo is None:
                post_dt = UTC_TZ.localize(raw_date)
            else:
                post_dt = raw_date.astimezone(UTC_TZ)
    except Exception as e:
        logger.debug("extract_lightweight_metadata: xato %s", e)

    if post_dt is None:
        post_dt = datetime.now(UTC_TZ)
    try:
        tashkent_dt = post_dt.astimezone(TASHKENT_TZ)
        post_hour = int(tashkent_dt.hour)
        post_weekday = int(tashkent_dt.weekday())
    except Exception:
        post_hour, post_weekday = 0, 0

    # Emoji density — yengil hisob (AI'siz)
    emoji_dens = 0.0
    if _emoji_density is not None:
        try:
            emoji_dens = _emoji_density(text)
        except Exception:
            emoji_dens = 0.0
    else:
        # Fallback: count emoji-like chars via simple heuristic
        try:
            # Count chars outside ascii letters/digits/punct
            emoji_dens = round(len([c for c in text if ord(c) > 127]) / max(1, len(text)), 6)
        except Exception:
            emoji_dens = 0.0

    cta = False
    if _detect_cta is not None:
        try:
            cta = _detect_cta(text)
        except Exception:
            cta = False
    else:
        # Minimal CTA detection
        lowered = (text or "").lower()
        cta_keywords = ("buyurtma", "obuna", "bosing", "subscribe", "buy now", "👉", "👇", "🔗")
        cta = any(kw in lowered for kw in cta_keywords)

    return {
        "channel_id": channel_id,
        "message_id": message_id,
        "post_hour": post_hour,
        "post_weekday": post_weekday,
        "has_media": bool(has_media),
        "media_type": media_type,
        "media_file_id": str(file_id)[:255] if file_id else None,
        "length": len(text),
        "cta_detected": bool(cta),
        "emoji_density": float(emoji_dens or 0.0),
    }


# ---------------------------------------------------------------------------
# DB yozish (idempotent, AI'siz)
# ---------------------------------------------------------------------------
async def record_post_event(message: Any, db_module: Any = None) -> bool:
    """Yengil metadata ajratib DB ga yozish — AI CHAQIRILMAYDI!

    Idempotent: (channel_id, message_id) UNIQUE + ON CONFLICT DO NOTHING.
    Qaytadi: True yangi event, False duplicate yoki xato.
    """
    if message is None:
        return False
    try:
        meta = extract_lightweight_metadata(message)
    except Exception as e:
        logger.warning("monitor: metadata xatosi %s", e)
        return False
    if not meta["channel_id"] or meta["message_id"] is None:
        return False
    db = db_module if db_module is not None else _import_database()
    if db is None or not hasattr(db, "insert_channel_post_event"):
        logger.debug("monitor: DB modul yo'q — event o'tkazib yuborildi")
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
        else:
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
        logger.warning("monitor: channel_post_events yozishda xato (%s): %s", meta["channel_id"], e)
        return False


async def _guarded_record(message: Any, db_module: Any = None) -> None:
    try:
        await record_post_event(message, db_module=db_module)
    except Exception as e:
        logger.warning("monitor: background record xatosi %s", e)


def schedule_post_event_ingest(message: Any, db_module: Any = None) -> "asyncio.Task | None":
    """Event ingestionni BACKGROUND TASK sifatida boshlaydi (non-blocking, AI'siz).

    Handler await QILMAYDI — event loop bloklanmaydi.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("monitor: Event loop yo'q — ingestion o'tkazib yuborildi")
        return None
    task = loop.create_task(_guarded_record(message, db_module))
    return task


# Alias for compatibility
handle_new_post = record_post_event
ingest_channel_post_event = record_post_event


# ---------------------------------------------------------------------------
# BATCH AGREGATSIYA (faqat DB, AI'siz) — FAZA 8,9,22
# ---------------------------------------------------------------------------
async def batch_aggregate_channel(
    channel_id: str | int,
    db_module: Any = None,
    batch_size: int = 500,
    use_ai: bool = False,
) -> dict:
    """Kanal postlarini batch ko'rinishida agregatsiya qilish — AI'siz!

    Qat'iy qoida: use_ai=True bo'lsa ham, bu funksiya AI CHAQIRMAYDI
    (faqat DB agregatsiyasi). AI tahlil faqat foydalanuvchi
    "Kanal tahlili"ni so'raganda alohida servis orqali ishga tushadi.

    Qaytadi:
      * {"ok": False, "error": "..."} — xato
      * {"ok": True, "insufficient": True, ...} — kam ma'lumot
      * {"ok": True, "insufficient": False, "profile": {...}, "saved": bool}
    """
    if use_ai:
        logger.info("monitor: batch_aggregate_channel use_ai=True berildi, lekin AI chaqirilmaydi (faqat DB agregatsiyasi)")

    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return {"ok": False, "error": "INVALID_CHANNEL", "message": "Kanal ID bo'sh"}

    db = db_module if db_module is not None else _import_database()
    if db is None:
        return {"ok": False, "error": "DB_UNAVAILABLE", "message": "DB modul yo'q"}

    if compute_channel_dna_extended is None:
        return {"ok": False, "error": "DNA_UNAVAILABLE", "message": "DNA moduli yuklanmadi"}

    # Ownership check optional — if db has get_channel_owner_id, we could check,
    # but batch job may run without user context (e.g., cron). So we skip IDOR here
    # unless caller provides user_id separately via get_channel_dna_extended.

    try:
        run_db = getattr(db, "run_db", None)
        if run_db is not None:
            events = await run_db(db.get_channel_post_events, ch_id, batch_size)
        else:
            events = db.get_channel_post_events(ch_id, batch_size)
    except Exception as e:
        logger.error("monitor: get_channel_post_events xatosi (%s): %s", ch_id, e)
        return {"ok": False, "error": "DB_ERROR", "message": str(e)[:200]}

    if not isinstance(events, list):
        events = []

    result = compute_channel_dna_extended(events)

    if result.get("insufficient"):
        return {
            "ok": True,
            "insufficient": True,
            "channel_id": ch_id,
            "sample_size": result.get("sample_size", 0),
            "confidence": result.get("confidence", 0.0),
            "message": result.get("message"),
            "metrics": result.get("metrics"),
            "overall": result.get("overall"),
            "saved": False,
        }

    profile = result.get("profile") or {}
    saved = False
    try:
        if hasattr(db, "save_channel_dna_profile"):
            if run_db is not None:
                await run_db(
                    db.save_channel_dna_profile,
                    channel_id=ch_id,
                    profile=profile,
                    sample_size=result.get("sample_size"),
                    confidence=result.get("confidence"),
                )
            else:
                db.save_channel_dna_profile(
                    channel_id=ch_id,
                    profile=profile,
                    sample_size=result.get("sample_size"),
                    confidence=result.get("confidence"),
                )
            saved = True
        # Also save legacy for backward compat
        if hasattr(db, "save_channel_intelligence_profile"):
            avg_len = profile.get("average_post_length") or profile.get("avg_length_value") or 0
            if run_db is not None:
                await run_db(
                    db.save_channel_intelligence_profile,
                    ch_id,
                    avg_post_length=avg_len,
                    emoji_level=profile.get("emoji_level", "medium"),
                    cta_style=profile.get("cta_style", "sometimes"),
                    formatting_style=profile.get("formatting_style", "balanced"),
                    confidence=int(result.get("confidence", 0.0) * 100),
                    sample_size=result.get("sample_size", 0),
                )
            else:
                db.save_channel_intelligence_profile(
                    ch_id,
                    avg_post_length=avg_len,
                    emoji_level=profile.get("emoji_level", "medium"),
                    cta_style=profile.get("cta_style", "sometimes"),
                    formatting_style=profile.get("formatting_style", "balanced"),
                    confidence=int(result.get("confidence", 0.0) * 100),
                    sample_size=result.get("sample_size", 0),
                )
            saved = True
    except Exception as e:
        logger.warning("monitor: batch save xatosi (%s): %s", ch_id, e)

    return {
        "ok": True,
        "insufficient": False,
        "channel_id": ch_id,
        "sample_size": result.get("sample_size"),
        "confidence": result.get("confidence"),
        "confidence_score": result.get("confidence_score"),
        "profile": profile,
        "metrics": result.get("metrics"),
        "overall": result.get("overall"),
        "saved": saved,
    }


async def get_aggregated_metrics(channel_id: str | int, db_module: Any = None, batch_size: int = 500) -> dict:
    """Foydalanuvchi 'Kanal tahlili' so'raganda chaqiriladigan batch agregatsiya.

    Bu funksiya ham AI chaqirmaydi — faqat DB dagi eventlarni agregatsiya qiladi.
    AI tahlil (agar kerak bo'lsa) alohida, yuqori darajadagi servisda,
    foydalanuvchi so'rovidan keyin ishga tushadi.
    """
    return await batch_aggregate_channel(channel_id, db_module=db_module, batch_size=batch_size, use_ai=False)


# ---------------------------------------------------------------------------
# ChannelMonitor klassi — qulay API
# ---------------------------------------------------------------------------
class ChannelMonitor:
    """Kanal monitoringi uchun qulay klass (AI'siz)."""

    def __init__(self, db_module: Any = None):
        self.db = db_module or _import_database()

    async def handle_update(self, message: Any) -> bool:
        """Yangi kanal posti kelganda chaqiriladi — yengil, AI'siz."""
        return await record_post_event(message, db_module=self.db)

    def schedule(self, message: Any) -> "asyncio.Task | None":
        """Background task sifatida rejalashtirish (non-blocking)."""
        return schedule_post_event_ingest(message, db_module=self.db)

    async def aggregate(self, channel_id: str | int, batch_size: int = 500) -> dict:
        """Batch agregatsiya — faqat DB, AI'siz."""
        return await batch_aggregate_channel(channel_id, db_module=self.db, batch_size=batch_size, use_ai=False)

    async def analyze(self, channel_id: str | int, batch_size: int = 500) -> dict:
        """Kanal tahlili so'ralganda — batch agregatsiya (AI'siz)."""
        return await get_aggregated_metrics(channel_id, db_module=self.db, batch_size=batch_size)


# For backward compatibility, expose monitoring functions
__all__ = [
    "ChannelMonitor",
    "batch_aggregate_channel",
    "extract_lightweight_metadata",
    "get_aggregated_metrics",
    "handle_new_post",
    "ingest_channel_post_event",
    "record_post_event",
    "schedule_post_event_ingest",
]
