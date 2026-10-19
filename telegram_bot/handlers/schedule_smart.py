"""Bot: tabiiy til va OVOZLI rejalash (post vaqti bosqichi — ``GET_TIME``).

* Matn: «har dam olish kuni soat 12:00 da», «ikki kunda bir marta 18:30» va h.k. (`services.schedule_nlp`, AI'siz). Oddiy vaqt
  («18:00», «ertaga 9:00») eski parserdan o'tadi — xulq o'zgarmagan.
* Ovoz: foydalanuvchi vaqtni ovozli xabar bilan aytadi. Kvota (`services.voice_schedule_quota`): free — butun umr bo'yicha bir
  martalik, PRO — kuniga cheklangan, admin — cheksiz. Bron ovozni matnga o'girishdan OLDIN; transkripsiya yoki aniqlash
  muvaffaqiyatsiz bo'lsa bron QAYTARILADI (foydalanuvchi imkoniyati yo'qolmaydi).
* Natija har doim tasdiq kartasiga tushadi (foydalanuvchi ko'radi va tasdiqlaydi); hech narsa o'zi yuborilmaydi.
"""
from __future__ import annotations

import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

import config
import database as db
from config import ADMIN_IDS_SET
from locales.translations import get_lang, get_text
from services import voice_schedule_quota as voice_quota
from services.schedule_nlp import parse_schedule_text
from services.user_timezone import utz
from translations import voice_t
from utils.audio_transcriber import check_duration, check_size, transcribe_voice
from utils.date_format import format_datetime
from utils.helpers import html_escape
from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

HEARD_MAX_CHARS = 200


def apply_proposal(context, start: datetime, recurrence: dict | None) -> None:
    """Taklifni tasdiq kartasi holatiga yozadi (``confirm_*`` kalitlari — qo'lda kiritish bilan bir xil shakl)."""
    ud = context.user_data
    ud["confirm_post_time"] = start
    ud["confirm_end_date"] = None
    if recurrence is None:
        ud["confirm_recurrence_type"] = "none"
        ud["confirm_recurrence_day"] = None
        ud["confirm_recurrence_time_str"] = None
        return
    ud["confirm_recurrence_type"] = recurrence["type"]
    ud["confirm_recurrence_day"] = recurrence["day"]
    ud["confirm_recurrence_time_str"] = recurrence["time"].strftime("%H:%M:00")


async def show_proposal(update: Update, context: ContextTypes.DEFAULT_TYPE, parsed: dict, prefix: str = ""):
    """Taklif qabul qilindi: holatga yozadi, «vaqt belgilandi» xabarini va tasdiq kartasini ko'rsatadi -> CONFIRM_POST."""
    from handlers.new_post import CONFIRM_POST, _show_confirmation

    lang = get_lang(context)
    apply_proposal(context, parsed["start"], parsed["recurrence"])
    try:
        await update.message.reply_text(
            prefix + get_text("np_time_set", lang, time=format_datetime(parsed["start"], lang)), parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001
        log_silent_failure("handlers.schedule_smart:show_proposal", exc, lang=lang)
    await _show_confirmation(update.message, context)
    return CONFIRM_POST


def try_text(text: str, now: datetime) -> dict | None:
    """Matndagi TAKRORLANUVCHI iborani aniqlaydi (aks holda ``None`` — eski parser ishlaydi, xulq o'zgarmaydi)."""
    parsed = parse_schedule_text(text, now)
    if parsed.get("ok") and parsed.get("recurrence"):
        return parsed
    return None


def _quota_message(res: dict, lang: str) -> str:
    reason = res.get("reason")
    if reason == "limit" and res.get("scope") == voice_quota.SCOPE_LIFETIME:
        return get_text("vs_limit_free", lang, n=int(config.PRO_VOICE_SCHEDULE_DAILY))
    if reason == "limit":
        return get_text("vs_limit_pro", lang, n=int(res.get("limit") or config.PRO_VOICE_SCHEDULE_DAILY))
    if reason == "disabled":
        return get_text("vs_disabled", lang)
    return get_text("vs_unavailable", lang)


async def time_voice_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vaqtni OVOZLI xabar bilan aytish (``GET_TIME``): cheklovlar -> kvota bron -> STT -> aniqlash -> tasdiq kartasi."""
    from handlers.new_post import GET_TIME
    from handlers.voice_post import _extract_voice_media

    msg = update.message
    user = update.effective_user
    if msg is None or user is None:
        return GET_TIME
    user_id = user.id
    lang = get_lang(context)
    media = _extract_voice_media(msg)
    if media is None:
        return GET_TIME

    is_admin = user_id in ADMIN_IDS_SET
    tier = "free"
    if not is_admin:
        try:
            tier = str(await db.run_db(db.get_plan_tier, user_id) or "free")
        except Exception:  # noqa: BLE001 — aniqlab bo'lmasa free qoidasi (qat'iyroq)
            tier = "free"
    is_pro = tier != "free"

    ok, limit = check_duration(getattr(media, "duration", 0), is_pro)
    if not ok:
        await msg.reply_text(voice_t("vp_too_long", lang, mins=max(1, limit // 60)), parse_mode="HTML")
        return GET_TIME
    if not check_size(getattr(media, "file_size", None)):
        await msg.reply_text(voice_t("vp_too_large", lang), parse_mode="HTML")
        return GET_TIME

    # --- kvota (ovozni matnga o'girishdan OLDIN) ---
    quota = await voice_quota.reserve(db, user_id, tier, is_admin)
    if not quota["allowed"]:
        await msg.reply_text(_quota_message(quota, lang), parse_mode="HTML")
        return GET_TIME
    rid = quota.get("reservation_id")

    async def give_back():
        await voice_quota.release(db, user_id, rid)

    await msg.reply_text(voice_t("vp_listening", lang), parse_mode="HTML")
    try:
        tg_file = await context.bot.get_file(media.file_id)
        data = bytes(await tg_file.download_as_bytearray())
        if not check_size(len(data)):
            await give_back()
            await msg.reply_text(voice_t("vp_too_large", lang), parse_mode="HTML")
            return GET_TIME
        filename = getattr(media, "file_name", None) or ("voice.ogg" if getattr(msg, "voice", None) else "audio.mp3")
        result = await transcribe_voice(data, filename)
    except Exception as exc:  # noqa: BLE001 — hech qachon yiqilmaydi
        logger.warning("Ovozli rejalash: yuklash/STT xatosi (user=%s): %s", user_id, type(exc).__name__)
        result = {"error": "stt_unavailable"}

    heard = str((result or {}).get("text") or "").strip()
    if (result or {}).get("error") or len(heard) < 2:
        await give_back()
        key = "vp_empty_text" if not (result or {}).get("error") else "vp_transcribe_error"
        await msg.reply_text(voice_t(key, lang), parse_mode="HTML")
        return GET_TIME

    parsed = parse_schedule_text(heard, datetime.now(utz()))
    if not parsed.get("ok"):
        await give_back()
        await msg.reply_text(
            get_text("vs_not_understood", lang, text=html_escape(heard[:HEARD_MAX_CHARS])), parse_mode="HTML")
        return GET_TIME

    note = ""
    if rid is not None and quota.get("scope") == voice_quota.SCOPE_LIFETIME:
        note = get_text("vs_free_used_note", lang, n=int(config.PRO_VOICE_SCHEDULE_DAILY)) + "\n\n"
    prefix = get_text("vs_heard", lang, text=html_escape(heard[:HEARD_MAX_CHARS])) + "\n\n" + note
    return await show_proposal(update, context, parsed, prefix=prefix)
