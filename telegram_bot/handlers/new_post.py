import asyncio
import json
import time
from datetime import datetime, timedelta
import pytz
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import (
    BTN_ALL_CHANNELS_TARGET, BTN_MAIN_MENU, BTN_SKIP_BUTTON,
    BTN_T_5MIN, BTN_T_15MIN, BTN_T_1H, BTN_T_DAILY, BTN_T_WEEKLY,
    BTN_DUR_1W, BTN_DUR_1M, BTN_DUR_3M, BTN_DUR_6M, BTN_DUR_1Y, BTN_DUR_INF,
    WEEKDAY_MAP, WEEKDAY_LABELS,
    get_main_keyboard, get_cancel_keyboard, get_button_prompt_keyboard,
    get_reactions_keyboard, get_auto_delete_keyboard, get_time_keyboard,
    get_duration_keyboard, get_weekday_keyboard
)
from keyboards.inline import btn_label
from utils.helpers import html_escape, parse_future_time, safe_html, parse_reactions_input
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

tashkent_tz = pytz.timezone("Asia/Tashkent")

# Albom (media_group) yig'ish: bir nechta rasm/video bitta post bo'lishi uchun.
# concurrent_updates=True bo'lgani uchun token+sleep ishlaydi.
_ALBUM_BUFFERS = {}
_ALBUM_WAIT_SECONDS = 1.5
_ALBUM_MAX_ITEMS = 10

CHOOSE_CHANNEL = 100
GET_CONTENT = 101
GET_BTN_TITLE = 102
GET_BTN_URL = 103
GET_REACTIONS = 104
GET_AUTO_DELETE = 105
GET_TIME = 106
DAILY_TIME = 107
RECUR_DAY = 108
RECUR_TIME = 109
GET_DURATION = 110
CONFIRM_POST = 111       # Tasdiqlash ekrani
EDIT_CONFIRM_FIELD = 112  # Confirmation'dan tahrirlash

def build_channel_labels(channels) -> dict:
    """Kanal ro'yxatidan tugma yorliqlari xaritasini tuzadi ({label: channel_id}).

    - Bo'sh/None sarlavhali kanal ham yaroqli yorliq oladi (Telegram bo'sh
      tugma matnini rad etadi).
    - Bir xil nomli kanallar bir-birini yopib qo'ymaydi: nomga ID, kerak
      bo'lsa tartib raqami qo'shiladi.
    """
    channels_map = {}
    for ch_id, ch_title in channels:
        label = btn_label(ch_title, "Kanal", max_length=48)
        if label in channels_map:
            label = f"{label} ({ch_id})"
        base_label = label
        suffix = 2
        while label in channels_map:
            label = f"{base_label} #{suffix}"
            suffix += 1
        channels_map[label] = ch_id
    return channels_map


async def start_new_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    is_admin = (user_id in ADMIN_IDS_SET)
    channels = await db.run_db(db.get_user_channels, user_id)
    if not channels:
        await update.message.reply_text(
            "⚠️ <b>Ulangan kanal yoki guruh topilmadi!</b>\n\n"
            "Avval '📢 Kanal/Guruhlar' bo'limidan kanal yoki guruhingizni ulang.",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    # Bir xil nomli kanallar bo'lsa, nomga ID qo'shib farqlaymiz —
    # aks holda ikkita kanal bir xil nomda bo'lsa, biri ikkinchisini yopib qo'yardi.
    # Nomsiz (bo'sh sarlavhali) kanal ham yaroqli yorliq oladi: Telegram bo'sh
    # tugma matnini qabul qilmaydi.
    channels_map = build_channel_labels(channels)
    keyboard = [[label] for label in channels_map]
    if len(channels) > 1:
        keyboard.append([BTN_ALL_CHANNELS_TARGET])
    keyboard.append([BTN_MAIN_MENU])

    context.user_data["channels_map"] = channels_map
    await update.message.reply_text(
        "📢 <b>Qaysi kanal yoki guruhga post rejalashtiramiz?</b>\nRo'yxatdan tanlang 👇",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="HTML"
    )
    return CHOOSE_CHANNEL

async def channel_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == BTN_ALL_CHANNELS_TARGET:
        context.user_data["selected_channel_id"] = "ALL"
        context.user_data["selected_channel_title"] = "🌐 Barchasi"
    else:
        channels_map = context.user_data.get("channels_map", {})
        if text not in channels_map:
            await update.message.reply_text("⚠️ Bunday kanal topilmadi. Qaytadan tanlang:")
            return CHOOSE_CHANNEL
        context.user_data["selected_channel_id"] = channels_map[text]
        context.user_data["selected_channel_title"] = text

    await update.message.reply_text(
        f"✅ Tanlandi: <b>{html_escape(context.user_data['selected_channel_title'])}</b>\n\n"
        f"📝 <b>Post uchun kontentni yuboring:</b>\n"
        f"(Matn, rasm, video, albom, hujjat, audio, ovozli xabar yoki stiker)",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return GET_CONTENT


def _media_item_from_message(msg):
    """Bitta xabardan media elementi (albom yoki yakka). None = matn."""
    caption = msg.caption or ""
    if msg.photo:
        return {"type": "photo", "file_id": msg.photo[-1].file_id, "caption": caption}
    if msg.video:
        return {"type": "video", "file_id": msg.video.file_id, "caption": caption}
    if msg.document:
        return {"type": "document", "file_id": msg.document.file_id, "caption": caption}
    if msg.audio:
        return {"type": "audio", "file_id": msg.audio.file_id, "caption": caption}
    if msg.animation:
        return {"type": "animation", "file_id": msg.animation.file_id, "caption": caption}
    if msg.voice:
        return {"type": "voice", "file_id": msg.voice.file_id, "caption": caption}
    if msg.sticker:
        return {"type": "sticker", "file_id": msg.sticker.file_id, "caption": ""}
    return None


def _purge_stale_albums():
    now = time.time()
    stale = [k for k, v in _ALBUM_BUFFERS.items() if now - v.get("ts", 0) > 120]
    for k in stale:
        _ALBUM_BUFFERS.pop(k, None)


def _apply_single_media(context, item):
    context.user_data["post_type"] = item["type"]
    context.user_data["file_id"] = item["file_id"]
    context.user_data["content"] = item.get("caption") or ""


async def _ask_button_prompt(msg):
    await msg.reply_text(
        "🔘 <b>Post ostiga havola tugma qo'shilsinmi?</b>\n\n"
        "Tugma ustidagi yozuvni tanlang yoki o'zingiz yozing:\n"
        "Kerak bo'lmasa, '➡️ Tugmasiz davom etish' ni bosing:",
        reply_markup=get_button_prompt_keyboard(),
        parse_mode="HTML"
    )
    return GET_BTN_TITLE


def _build_preview_text(context) -> str:
    """Confirmation ekrani uchun post preview matnini tuzadi."""
    channel_title = context.user_data.get("selected_channel_title", "Kanal")
    post_type = context.user_data.get("post_type", "text")
    content = context.user_data.get("content", "")
    btn_text = context.user_data.get("btn_text")
    btn_url = context.user_data.get("btn_url")
    enable_reactions = context.user_data.get("enable_reactions", False)
    delete_after_hours = context.user_data.get("delete_after_hours", 0)
    post_time = context.user_data.get("confirm_post_time")
    recurrence_type = context.user_data.get("confirm_recurrence_type", "none")
    recurrence_time_str = context.user_data.get("confirm_recurrence_time_str")
    recurrence_day = context.user_data.get("confirm_recurrence_day")

    if recurrence_type == "daily" and recurrence_time_str:
        when_text = f"🔁 Har kuni, soat {recurrence_time_str[:5]} da"
    elif recurrence_type == "weekly" and recurrence_time_str:
        day_label = WEEKDAY_LABELS.get(recurrence_day, "?")
        when_text = f"📅 Har {day_label}, soat {recurrence_time_str[:5]} da"
    elif post_time:
        when_text = f"⏰ {post_time.strftime('%Y-%m-%d %H:%M')} (Toshkent vaqti)"
    else:
        when_text = "⏰ Vaqt belgilanmagan"

    type_labels = {
        "text": "📝 Matn", "photo": "🖼 Rasm", "video": "🎬 Video",
        "document": "📄 Hujjat", "audio": "🎵 Audio", "voice": "🎙 Ovozli",
        "sticker": "😀 Stiker", "album": "🖼 Albom", "animation": "🎞 GIF",
    }
    type_text = type_labels.get(post_type, "📝 Xabar")

    content_preview = ""
    if content:
        preview = content[:300]
        if len(content) > 300:
            preview += "…"
        content_preview = f"\n\n📋 <b>Matn:</b>\n{safe_html(preview)}"

    btn_info = ""
    if btn_text and btn_url:
        btn_info = f"\n🔘 Tugma: <b>{html_escape(btn_text)}</b>"
    react_info = "\n👍 Reaksiyalar: Yoqilgan" if enable_reactions else ""
    del_info = f"\n⏳ Avto-o'chirish: {delete_after_hours} soat" if delete_after_hours > 0 else ""

    return (
        f"📋 <b>Postni tasdiqlang:</b>\n\n"
        f"📢 <b>Kanal:</b> {html_escape(channel_title)}\n"
        f"📦 <b>Turi:</b> {type_text}\n"
        f"{when_text}"
        f"{content_preview}"
        f"{btn_info}{react_info}{del_info}"
    )


def _get_confirm_keyboard():
    """Tasdiqlash ekranidagi inline tugmalar."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Tasdiqlash va rejalashtirish", callback_data="confirm_post:ok")],
        [InlineKeyboardButton("⚡️ Navbatga qo'yish (Queue)", callback_data="confirm_post:queue")],
        [
            InlineKeyboardButton("✏️ Tahrirlash", callback_data="confirm_post:edit"),
            InlineKeyboardButton("❌ Bekor qilish", callback_data="confirm_post:cancel"),
        ],
    ])


def _get_edit_confirm_keyboard():
    """Tahrirlash sub-menyusi tugmalari."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📝 Matn", callback_data="edit_field:content"),
            InlineKeyboardButton("📢 Kanal", callback_data="edit_field:channel"),
        ],
        [
            InlineKeyboardButton("⏰ Vaqt", callback_data="edit_field:time"),
            InlineKeyboardButton("🔘 Tugma", callback_data="edit_field:btn"),
        ],
        [InlineKeyboardButton("⬅️ Orqaga (tasdiqlashga)", callback_data="edit_field:back")],
    ])


async def _show_confirmation(target_msg, context):
    """Preview kartasini ko'rsatadi va CONFIRM_POST holatiga qaytadi."""
    preview = _build_preview_text(context)
    post_type = context.user_data.get("post_type", "text")
    file_id = context.user_data.get("file_id")
    keyboard = _get_confirm_keyboard()

    if file_id and post_type in ("photo", "video", "document", "audio", "animation"):
        cap = preview[:1024]
        try:
            if post_type == "photo":
                await target_msg.reply_photo(photo=file_id, caption=cap, reply_markup=keyboard, parse_mode="HTML")
            elif post_type == "video":
                await target_msg.reply_video(video=file_id, caption=cap, reply_markup=keyboard, parse_mode="HTML")
            elif post_type == "document":
                await target_msg.reply_document(document=file_id, caption=cap, reply_markup=keyboard, parse_mode="HTML")
            elif post_type == "audio":
                await target_msg.reply_audio(audio=file_id, caption=cap, reply_markup=keyboard, parse_mode="HTML")
            elif post_type == "animation":
                await target_msg.reply_animation(animation=file_id, caption=cap, reply_markup=keyboard, parse_mode="HTML")
            else:
                await target_msg.reply_text(preview[:4096], reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await target_msg.reply_text(preview[:4096], reply_markup=keyboard, parse_mode="HTML")
    else:
        await target_msg.reply_text(preview[:4096], reply_markup=keyboard, parse_mode="HTML")


async def content_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = update.effective_user.id

    if msg.media_group_id:
        item = _media_item_from_message(msg)
        if not item or item["type"] in ("voice", "sticker"):
            return GET_CONTENT

        _purge_stale_albums()
        key = (user_id, msg.media_group_id)
        buf = _ALBUM_BUFFERS.setdefault(key, {"items": [], "seq": 0, "ts": time.time()})
        if len(buf["items"]) < _ALBUM_MAX_ITEMS:
            buf["items"].append(item)
        buf["seq"] += 1
        buf["ts"] = time.time()
        my_seq = buf["seq"]

        # Boshqa albom elementlari ham start bo'lishi uchun avval yield
        await asyncio.sleep(0)
        await asyncio.sleep(_ALBUM_WAIT_SECONDS)
        current = _ALBUM_BUFFERS.get(key)
        if not current or current.get("seq") != my_seq:
            return GET_CONTENT

        items = _ALBUM_BUFFERS.pop(key, {}).get("items") or [item]
        caption = next((i.get("caption") or "" for i in items if i.get("caption")), "")
        if len(items) == 1:
            _apply_single_media(context, items[0])
        else:
            context.user_data["post_type"] = "album"
            context.user_data["file_id"] = json.dumps(items, ensure_ascii=False)
            context.user_data["content"] = caption
        return await _ask_button_prompt(msg)

    item = _media_item_from_message(msg)
    if item:
        _apply_single_media(context, item)
    else:
        context.user_data["post_type"] = "text"
        context.user_data["file_id"] = None
        context.user_data["content"] = msg.text or ""

    return await _ask_button_prompt(msg)

async def btn_title_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # AI Yordamchi tugmasi
    if text == "✨ AI Yordamchi":
        content = context.user_data.get("content", "")
        if not content:
            await update.message.reply_text(
                "⚠️ <b>Post matni bo'sh.</b>\nAvval matn kiriting.",
                parse_mode="HTML",
            )
            return GET_BTN_TITLE
        preview = content[:200]
        if len(content) > 200:
            preview += "…"
        await update.message.reply_text(
            f"✨ <b>AI Yordamchi</b>\n\n"
            f"📋 Joriy matn:\n<i>{html_escape(preview)}</i>\n\n"
            f"Qaysi amalni bajaramiz?",
            reply_markup=_get_ai_action_keyboard(),
            parse_mode="HTML",
        )
        return GET_BTN_TITLE

    if text == BTN_SKIP_BUTTON:
        context.user_data["btn_text"], context.user_data["btn_url"] = None, None
        await update.message.reply_text(
            "👍 <b>Post ostiga reaksiya tugmalari qo'shilsinmi?</b>",
            reply_markup=get_reactions_keyboard(),
            parse_mode="HTML"
        )
        return GET_REACTIONS

    context.user_data["btn_text"] = text
    await update.message.reply_text(
        f"🔗 <b>'{html_escape(text)}'</b> tugmasi bosilganda ochiladigan havola yoki kanal username'ini yuboring:\n\n"
        f"Masalan: <code>@kanalim</code> yoki <code>https://sayt.uz</code>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return GET_BTN_URL

async def btn_url_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    btn_link = text
    if btn_link.startswith("@"):
        btn_link = f"https://t.me/{btn_link.lstrip('@')}"
    elif not (btn_link.startswith("http://") or btn_link.startswith("https://") or btn_link.startswith("t.me/")):
        if "." in btn_link:
            btn_link = "https://" + btn_link
        else:
            btn_link = f"https://t.me/{btn_link.lstrip('@')}"

    context.user_data["btn_url"] = btn_link
    await update.message.reply_text(
        "👍 <b>Post ostiga reaksiya tugmalari qo'shilsinmi?</b>",
        reply_markup=get_reactions_keyboard(),
        parse_mode="HTML"
    )
    return GET_REACTIONS

async def reactions_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    parsed = parse_reactions_input(text)
    if parsed is None:
        await update.message.reply_text(
            "⚠️ <b>Iltimos, quyidagi tugmalardan birini tanlang:</b>\n"
            "• Reaksiya emojilari: <code>👍</code> <code>❤️</code> <code>🔥</code> <code>👏</code>\n"
            "• <code>➡️ Reaksiyasiz davom etish</code> — reaksiyasiz",
            reply_markup=get_reactions_keyboard(),
            parse_mode="HTML"
        )
        return GET_REACTIONS

    context.user_data["enable_reactions"] = parsed

    await update.message.reply_text(
        "🗑️ <b>Post kanalda qancha vaqt tursin?</b>\n\n"
        "Belgilangan vaqt o'tgach, bot uni kanaldan avtomatik o'chirib tashlaydi:",
        reply_markup=get_auto_delete_keyboard(),
        parse_mode="HTML"
    )
    return GET_AUTO_DELETE

async def auto_delete_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    hours = 0
    if "12" in text:
        hours = 12
    elif "24" in text:
        hours = 24
    elif "48" in text:
        hours = 48
    elif "72" in text:
        hours = 72

    context.user_data["delete_after_hours"] = hours

    now = datetime.now(tashkent_tz)
    example = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    await update.message.reply_text(
        "🕒 <b>Post qaysi vaqtda chiqsin?</b>\n\n"
        "Tayyor tugmalardan tanlang yoki aniq vaqtni yozing:\n"
        f"Namuna: <code>{example}</code>",
        reply_markup=get_time_keyboard(),
        parse_mode="HTML"
    )
    return GET_TIME

async def _save_and_finish(update, context, post_time, recurrence_type='none', recurrence_day=None, recurrence_time_str=None, end_date=None):
    is_admin = (update.effective_user.id in ADMIN_IDS_SET)
    user_id = update.effective_user.id
    selected_channel_id = context.user_data["selected_channel_id"]
    channel_title = context.user_data.get("selected_channel_title", "Kanal")
    post_type = context.user_data["post_type"]
    content = context.user_data.get("content")
    file_id = context.user_data.get("file_id")
    btn_text = context.user_data.get("btn_text")
    btn_url = context.user_data.get("btn_url")
    enable_reactions = context.user_data.get("enable_reactions", False)
    delete_after_hours = context.user_data.get("delete_after_hours", 0)

    post_time_tz = post_time.astimezone(tashkent_tz)
    channels = (
        await db.run_db(db.get_user_channels, user_id)
        if selected_channel_id == "ALL"
        else [(selected_channel_id, channel_title)]
    )
    ok_count = 0

    for ch_id, _ in channels:
        pid = await db.run_db(
            db.add_post,
            user_id=user_id, channel_id=ch_id, post_type=post_type, content=content,
            file_id=file_id, scheduled_time=post_time_tz, recurrence_type=recurrence_type,
            recurrence_day=recurrence_day, recurrence_time=recurrence_time_str, end_date=end_date,
            btn_text=btn_text, btn_url=btn_url, enable_reactions=enable_reactions,
            delete_after_hours=delete_after_hours
        )
        if pid:
            ok_count += 1

    if ok_count:
        if recurrence_type == 'daily':
            when_text = f"🔁 Har kuni, soat {recurrence_time_str[:5]} da"
        elif recurrence_type == 'weekly':
            when_text = f"📅 Har {WEEKDAY_LABELS.get(recurrence_day)}, soat {recurrence_time_str[:5]} da"
        else:
            when_text = f"⏰ {post_time_tz.strftime('%Y-%m-%d %H:%M')}"

        del_info = f"\n⏳ Kanalda turish muddati: <b>{delete_after_hours} soat</b>" if delete_after_hours > 0 else ""
        await update.message.reply_text(
            f"✅ <b>Post muvaffaqiyatli rejalashtirildi!</b>\n\n"
            f"📢 Joylash: <b>{html_escape(channel_title)}</b>\n"
            f"{when_text}{del_info}",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("❌ Saqlashda xatolik yuz berdi.", reply_markup=get_main_keyboard(is_admin), parse_mode="HTML")
    context.user_data.clear()

async def time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    now = datetime.now(tashkent_tz)

    if text == BTN_T_DAILY:
        await update.message.reply_text("🔁 <b>Har kuni soat nechida chiqsin?</b>\nMasalan: <code>10:00</code> yoki <code>18:30</code>", reply_markup=get_cancel_keyboard(), parse_mode="HTML")
        return DAILY_TIME
    elif text == BTN_T_WEEKLY:
        await update.message.reply_text("📅 <b>Haftaning qaysi kuni chiqsin?</b>", reply_markup=get_weekday_keyboard(), parse_mode="HTML")
        return RECUR_DAY

    post_time = None
    try:
        if text == BTN_T_5MIN:
            post_time = now + timedelta(minutes=5)
        elif text == BTN_T_15MIN:
            post_time = now + timedelta(minutes=15)
        elif text == BTN_T_1H:
            post_time = now + timedelta(hours=1)
        else:
            post_time = parse_future_time(text.strip(), now)
            if post_time is None:
                naive_time = datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
                post_time = tashkent_tz.localize(naive_time)

        if post_time is None or post_time <= now:
            await update.message.reply_text("⚠️ Kelajakdagi vaqtni kiriting:")
            return GET_TIME
    except Exception:
        await update.message.reply_text("⚠️ Format xato! Masalan: <code>2026-08-30 18:00</code> yoki <code>18:00</code> shaklida yuboring.", parse_mode="HTML")
        return GET_TIME

    # Confirmation ekranini ko'rsatish
    context.user_data["confirm_post_time"] = post_time
    context.user_data["confirm_recurrence_type"] = "none"
    context.user_data["confirm_recurrence_day"] = None
    context.user_data["confirm_recurrence_time_str"] = None
    context.user_data["confirm_end_date"] = None
    await _show_confirmation(update.message, context)
    return CONFIRM_POST

async def daily_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        hh, mm = map(int, text.split(":"))
        assert 0 <= hh < 24 and 0 <= mm < 60
    except Exception:
        await update.message.reply_text("⚠️ Noto'g'ri vaqt formati. Masalan: <code>10:00</code>", parse_mode="HTML")
        return DAILY_TIME

    now = datetime.now(tashkent_tz)
    first_run = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if first_run <= now:
        first_run += timedelta(days=1)

    context.user_data["rec_first_run"] = first_run
    context.user_data["rec_type"] = "daily"
    context.user_data["rec_time_str"] = f"{hh:02d}:{mm:02d}:00"
    context.user_data["rec_day"] = None

    await update.message.reply_text("⏳ <b>Post qancha muddat davomida har kuni chiqsin?</b>", reply_markup=get_duration_keyboard(), parse_mode="HTML")
    return GET_DURATION

async def recur_day_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text not in WEEKDAY_MAP:
        await update.message.reply_text("⚠️ Kunlardan birini tanlang:")
        return RECUR_DAY

    context.user_data["rec_day"] = WEEKDAY_MAP[text]
    await update.message.reply_text(f"🕒 <b>Har {text} soat nechida chiqsin?</b>\nMasalan: <code>10:00</code>", reply_markup=get_cancel_keyboard(), parse_mode="HTML")
    return RECUR_TIME

async def recur_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        hh, mm = map(int, text.split(":"))
        assert 0 <= hh < 24 and 0 <= mm < 60
    except Exception:
        await update.message.reply_text("⚠️ Noto'g'ri format! Masalan: <code>10:00</code>", parse_mode="HTML")
        return RECUR_TIME

    now = datetime.now(tashkent_tz)
    target_day = context.user_data["rec_day"]
    days_ahead = (target_day - now.weekday() + 7) % 7
    first_run = now.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(days=days_ahead)
    if first_run <= now:
        first_run += timedelta(days=7)

    context.user_data["rec_first_run"] = first_run
    context.user_data["rec_type"] = "weekly"
    context.user_data["rec_time_str"] = f"{hh:02d}:{mm:02d}:00"

    await update.message.reply_text("⏳ <b>Ushbu post qancha muddat davomida chiqsin?</b>", reply_markup=get_duration_keyboard(), parse_mode="HTML")
    return GET_DURATION

async def duration_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    now = datetime.now(tashkent_tz)
    end_date = None

    if text == BTN_DUR_1W:
        # Yangi: post har kuni roppa-rosa 1 hafta (7 kun) davomida chiqadi
        end_date = now + timedelta(days=7)
    elif text == BTN_DUR_1M:
        end_date = now + timedelta(days=30)
    elif text == BTN_DUR_3M:
        end_date = now + timedelta(days=90)
    elif text == BTN_DUR_6M:
        end_date = now + timedelta(days=180)
    elif text == BTN_DUR_1Y:
        end_date = now + timedelta(days=365)
    elif text == BTN_DUR_INF:
        end_date = None
    else:
        await update.message.reply_text("⚠️ Variantlardan birini tanlang:")
        return GET_DURATION

    # Confirmation ekranini ko'rsatish
    context.user_data["confirm_post_time"] = context.user_data["rec_first_run"]
    context.user_data["confirm_recurrence_type"] = context.user_data["rec_type"]
    context.user_data["confirm_recurrence_day"] = context.user_data["rec_day"]
    context.user_data["confirm_recurrence_time_str"] = context.user_data["rec_time_str"]
    context.user_data["confirm_end_date"] = end_date
    await _show_confirmation(update.message, context)
    return CONFIRM_POST


# ============================================================
# CONFIRMATION CALLBACK HANDLERS
# ============================================================

async def confirm_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tasdiqlash ekranidagi tugmalar: OK / Queue / Edit / Cancel."""
    query = update.callback_query
    await query.answer()
    data = query.data
    action = data.split(":", 1)[1] if ":" in data else ""
    user_id = query.from_user.id
    is_admin = (user_id in ADMIN_IDS_SET)

    if action == "cancel":
        context.user_data.clear()
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            "🚫 <b>Post bekor qilindi.</b>\nAsosiy menyuga qaytdingiz 👇",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    if action == "edit":
        await query.message.reply_text(
            "✏️ <b>Qaysi qismini tahrirlash kerak?</b>",
            reply_markup=_get_edit_confirm_keyboard(),
            parse_mode="HTML",
        )
        return EDIT_CONFIRM_FIELD

    if action == "queue":
        selected_channel_id = context.user_data.get("selected_channel_id")
        if not selected_channel_id:
            await query.message.reply_text(
                "⚠️ <b>Kanal tanlanmagan.</b>",
                reply_markup=get_main_keyboard(is_admin),
                parse_mode="HTML",
            )
            context.user_data.clear()
            return ConversationHandler.END

        now = datetime.now(tashkent_tz)
        slots = await db.run_db(db.get_queue_slots, user_id)
        ch_id_for_q = selected_channel_id if selected_channel_id != "ALL" else "ALL"
        occupied = await db.run_db(db.get_queue_occupied_times, user_id, ch_id_for_q, now.date())

        slot_dt, label = db.find_next_queue_slot(slots, occupied, now)
        if not slot_dt:
            tomorrow = now + timedelta(days=1)
            tomorrow_start = tashkent_tz.localize(
                datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0)
            )
            occ_tom = await db.run_db(db.get_queue_occupied_times, user_id, ch_id_for_q, tomorrow.date())
            slot_dt, label = db.find_next_queue_slot(slots, occ_tom, tomorrow_start)

        if not slot_dt:
            for day_off in range(2, 8):
                future_date = now.date() + timedelta(days=day_off)
                occ = await db.run_db(db.get_queue_occupied_times, user_id, ch_id_for_q, future_date)
                future_start = tashkent_tz.localize(
                    datetime(future_date.year, future_date.month, future_date.day, 0, 0)
                )
                slot_dt, label = db.find_next_queue_slot(slots, occ, future_start)
                if slot_dt:
                    break

        if not slot_dt:
            await query.message.reply_text(
                "⚠️ <b>Bo'sh slot topilmadi.</b>\n7 kun ichida barcha slotlar band.",
                reply_markup=get_main_keyboard(is_admin),
                parse_mode="HTML",
            )
            context.user_data.clear()
            return ConversationHandler.END

        post_type = context.user_data.get("post_type")
        content = context.user_data.get("content")
        file_id = context.user_data.get("file_id")
        btn_text = context.user_data.get("btn_text")
        btn_url = context.user_data.get("btn_url")
        enable_reactions = context.user_data.get("enable_reactions", False)
        delete_after_hours = context.user_data.get("delete_after_hours", 0)
        channel_title = context.user_data.get("selected_channel_title", "Kanal")

        channels = (
            await db.run_db(db.get_user_channels, user_id)
            if selected_channel_id == "ALL"
            else [(selected_channel_id, channel_title)]
        )
        ok_count = 0
        for ch_id, _ in channels:
            try:
                pid = await db.run_db(
                    db.add_post,
                    user_id=user_id, channel_id=ch_id, post_type=post_type, content=content,
                    file_id=file_id, scheduled_time=slot_dt, recurrence_type='none',
                    recurrence_day=None, recurrence_time=None, end_date=None,
                    btn_text=btn_text, btn_url=btn_url, enable_reactions=enable_reactions,
                    delete_after_hours=delete_after_hours
                )
                if pid:
                    ok_count += 1
            except Exception:
                pass

        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        if ok_count:
            time_str = slot_dt.strftime("%H:%M")
            await query.message.reply_text(
                f"⚡️ <b>Post navbatga qo'yildi!</b>\n\n"
                f"📅 {label}, soat {time_str}\n"
                f"📢 Kanal: <b>{html_escape(channel_title)}</b>",
                reply_markup=get_main_keyboard(is_admin),
                parse_mode="HTML",
            )
        else:
            await query.message.reply_text(
                "❌ <b>Navbatga qo'yishda xatolik.</b>",
                reply_markup=get_main_keyboard(is_admin),
                parse_mode="HTML",
            )
        context.user_data.clear()
        return ConversationHandler.END

    # action == "ok"
    post_time = context.user_data.get("confirm_post_time")
    recurrence_type = context.user_data.get("confirm_recurrence_type", "none")
    recurrence_day = context.user_data.get("confirm_recurrence_day")
    recurrence_time_str = context.user_data.get("confirm_recurrence_time_str")
    end_date = context.user_data.get("confirm_end_date")

    if not post_time:
        await query.message.reply_text("⚠️ <b>Vaqt belgilanmagan.</b>", reply_markup=get_main_keyboard(is_admin), parse_mode="HTML")
        context.user_data.clear()
        return ConversationHandler.END

    selected_channel_id = context.user_data.get("selected_channel_id")
    channel_title = context.user_data.get("selected_channel_title", "Kanal")
    post_type = context.user_data.get("post_type")
    content = context.user_data.get("content")
    file_id = context.user_data.get("file_id")
    btn_text = context.user_data.get("btn_text")
    btn_url = context.user_data.get("btn_url")
    enable_reactions = context.user_data.get("enable_reactions", False)
    delete_after_hours = context.user_data.get("delete_after_hours", 0)

    post_time_tz = post_time.astimezone(tashkent_tz)
    channels = (
        await db.run_db(db.get_user_channels, user_id)
        if selected_channel_id == "ALL"
        else [(selected_channel_id, channel_title)]
    )
    ok_count = 0
    for ch_id, _ in channels:
        try:
            pid = await db.run_db(
                db.add_post,
                user_id=user_id, channel_id=ch_id, post_type=post_type, content=content,
                file_id=file_id, scheduled_time=post_time_tz, recurrence_type=recurrence_type,
                recurrence_day=recurrence_day, recurrence_time=recurrence_time_str, end_date=end_date,
                btn_text=btn_text, btn_url=btn_url, enable_reactions=enable_reactions,
                delete_after_hours=delete_after_hours
            )
            if pid:
                ok_count += 1
        except Exception:
            pass

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    if ok_count:
        if recurrence_type == "daily" and recurrence_time_str:
            when_text = f"🔁 Har kuni, soat {recurrence_time_str[:5]} da"
        elif recurrence_type == "weekly" and recurrence_time_str:
            day_label = WEEKDAY_LABELS.get(recurrence_day, "?")
            when_text = f"📅 Har {day_label}, soat {recurrence_time_str[:5]} da"
        else:
            when_text = f"⏰ {post_time_tz.strftime('%Y-%m-%d %H:%M')}"
        del_info = f"\n⏳ Kanalda turish muddati: <b>{delete_after_hours} soat</b>" if delete_after_hours > 0 else ""
        await query.message.reply_text(
            f"✅ <b>Post muvaffaqiyatli rejalashtirildi!</b>\n\n"
            f"📢 Joylash: <b>{html_escape(channel_title)}</b>\n"
            f"{when_text}{del_info}",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML"
        )
    else:
        await query.message.reply_text("❌ <b>Saqlashda xatolik.</b>", reply_markup=get_main_keyboard(is_admin), parse_mode="HTML")
    context.user_data.clear()
    return ConversationHandler.END


    return CONFIRM_POST


async def edit_confirm_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tahrirlash sub-menyusi."""
    query = update.callback_query
    await query.answer()
    data = query.data
    field = data.split(":", 1)[1] if ":" in data else ""

    if field == "back":
        await _show_confirmation(query.message, context)
        return CONFIRM_POST

    if field == "content":
        await query.message.reply_text("📝 <b>Yangi matn yuboring:</b>", reply_markup=get_cancel_keyboard(), parse_mode="HTML")
        return EDIT_CONFIRM_FIELD

    if field == "channel":
        user_id = query.from_user.id
        channels = await db.run_db(db.get_user_channels, user_id)
        if not channels:
            await query.message.reply_text("⚠️ Kanal topilmadi.")
            return EDIT_CONFIRM_FIELD
        channels_map = build_channel_labels(channels)
        keyboard = [[label] for label in channels_map]
        if len(channels) > 1:
            keyboard.append([BTN_ALL_CHANNELS_TARGET])
        keyboard.append(["🔙 Orqaga"])
        context.user_data["edit_channels_map"] = channels_map
        await query.message.reply_text("📢 <b>Qaysi kanal?</b>", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True), parse_mode="HTML")
        return EDIT_CONFIRM_FIELD

    if field == "time":
        now = datetime.now(tashkent_tz)
        example = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
        await query.message.reply_text(f"🕒 <b>Yangi vaqt:</b> <code>{example}</code>", reply_markup=get_time_keyboard(), parse_mode="HTML")
        return EDIT_CONFIRM_FIELD

    if field == "btn":
        await query.message.reply_text("🔘 <b>Tugma:</b> <code>Matn | https://havola.uz</code>\nO'chirish: <code>yo'q</code>", reply_markup=get_cancel_keyboard(), parse_mode="HTML")
        return EDIT_CONFIRM_FIELD

    return EDIT_CONFIRM_FIELD


async def edit_confirm_message_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """EDIT_CONFIRM_FIELD holatida matn qabul qilish."""
    text = (update.message.text or "").strip()

    if text in ("🔙 Orqaga", BTN_BACK, BTN_MAIN_MENU):
        await _show_confirmation(update.message, context)
        return CONFIRM_POST

    edit_channels_map = context.user_data.get("edit_channels_map")
    if edit_channels_map:
        if text == BTN_ALL_CHANNELS_TARGET:
            context.user_data["selected_channel_id"] = "ALL"
            context.user_data["selected_channel_title"] = "🌐 Barchasi"
            context.user_data.pop("edit_channels_map", None)
            await _show_confirmation(update.message, context)
            return CONFIRM_POST
        elif text in edit_channels_map:
            context.user_data["selected_channel_id"] = edit_channels_map[text]
            context.user_data["selected_channel_title"] = text
            context.user_data.pop("edit_channels_map", None)
            await _show_confirmation(update.message, context)
            return CONFIRM_POST

    now = datetime.now(tashkent_tz)
    new_time = None
    try:
        if text == BTN_T_5MIN:
            new_time = now + timedelta(minutes=5)
        elif text == BTN_T_15MIN:
            new_time = now + timedelta(minutes=15)
        elif text == BTN_T_1H:
            new_time = now + timedelta(hours=1)
        else:
            new_time = parse_future_time(text, now)
            if new_time is None:
                try:
                    naive_time = datetime.strptime(text, "%Y-%m-%d %H:%M")
                    new_time = tashkent_tz.localize(naive_time)
                except Exception:
                    pass
    except Exception:
        pass

    if new_time and new_time > now:
        context.user_data["confirm_post_time"] = new_time
        context.user_data["confirm_recurrence_type"] = "none"
        context.user_data["confirm_recurrence_day"] = None
        context.user_data["confirm_recurrence_time_str"] = None
        context.user_data["confirm_end_date"] = None
        await _show_confirmation(update.message, context)
        return CONFIRM_POST

    if "|" in text:
        parts = text.split("|", 1)
        btn_t = parts[0].strip()
        btn_u = parts[1].strip()
        if btn_u.startswith("@"):
            btn_u = f"https://t.me/{btn_u.lstrip('@')}"
        elif not btn_u.startswith(("http://", "https://", "t.me/")):
            btn_u = "https://" + btn_u if "." in btn_u else f"https://t.me/{btn_u.lstrip('@')}"
        context.user_data["btn_text"] = btn_t
        context.user_data["btn_url"] = btn_u
        await _show_confirmation(update.message, context)
        return CONFIRM_POST

    if text.lower() in ("yo'q", "yoq", "none", "-", "o'chir"):
        context.user_data["btn_text"] = None
        context.user_data["btn_url"] = None
        await _show_confirmation(update.message, context)
        return CONFIRM_POST

    if text and text not in (BTN_T_DAILY, BTN_T_WEEKLY, BTN_BACK, BTN_MAIN_MENU):
        context.user_data["post_type"] = "text"
        context.user_data["file_id"] = None
        context.user_data["content"] = text
        await _show_confirmation(update.message, context)
        return CONFIRM_POST

    await _show_confirmation(update.message, context)
    return CONFIRM_POST


async def edit_confirm_media_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """EDIT_CONFIRM_FIELD holatida media qabul qilish."""
    msg = update.message
    item = _media_item_from_message(msg)
    if item:
        _apply_single_media(context, item)
    await _show_confirmation(msg, context)
    return CONFIRM_POST


# ============================================================
# AI FORMATTING ACTIONS
# ============================================================
# ============================================================
# AI FORMATTING ACTIONS
# ============================================================

def _get_ai_action_keyboard():
    """AI harakatlari keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✍️ Imlo va uslub", callback_data="ai_act:grammar"),
            InlineKeyboardButton("🎨 Emojilar", callback_data="ai_act:emoji"),
        ],
        [
            InlineKeyboardButton("🏷 Hashtaglar", callback_data="ai_act:hashtags"),
            InlineKeyboardButton("✂️ Qisqartirish", callback_data="ai_act:tldr"),
        ],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="ai_act:back")],
    ])


def _get_ai_result_keyboard():
    """AI natijasidan keyin tasdiqlash keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Qabul qilish", callback_data="ai_res:accept"),
            InlineKeyboardButton("🔄 Qayta urinish", callback_data="ai_res:retry"),
        ],
        [InlineKeyboardButton("❌ Asl holatga qaytarish", callback_data="ai_res:revert")],
    ])


async def ai_action_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI harakatlari menyusini ko'rsatadi."""
    query = update.callback_query
    await query.answer()
    content = context.user_data.get("content", "")
    if not content:
        await query.message.reply_text(
            "⚠️ <b>Post matni bo'sh.</b>\nAvval matn kiriting.",
            parse_mode="HTML",
        )
        return GET_BTN_TITLE

    preview = content[:200]
    if len(content) > 200:
        preview += "…"
    await query.message.reply_text(
        f"✨ <b>AI Yordamchi</b>\n\n"
        f"📋 Joriy matn:\n<i>{html_escape(preview)}</i>\n\n"
        f"Qaysi amalni bajaramiz?",
        reply_markup=_get_ai_action_keyboard(),
        parse_mode="HTML",
    )
    return GET_BTN_TITLE


async def ai_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI harakati tugmasi bosilganda."""
    query = update.callback_query
    data = query.data
    action = data.split(":", 1)[1] if ":" in data else ""

    if action == "back":
        await query.answer()
        return GET_BTN_TITLE

    content = context.user_data.get("content", "")
    if not content:
        await query.answer("⚠️ Matn bo'sh!", show_alert=True)
        return GET_BTN_TITLE

    await query.answer("⏳ AI ishlayapti...")

    # Asl matnni saqlab qolish (revert uchun)
    context.user_data["ai_original_content"] = content

    from utils.ai_agent import format_post_text
    result = await format_post_text(content, action)

    if "error" in result:
        await query.message.reply_text(result["error"], parse_mode="HTML")
        return GET_BTN_TITLE

    formatted = result.get("formatted", "")
    if not formatted:
        await query.message.reply_text("⚠️ AI javobi bo'sh. Asl matn saqlab qolindi.", parse_mode="HTML")
        return GET_BTN_TITLE

    context.user_data["ai_proposed_content"] = formatted
    context.user_data["ai_last_action"] = action

    old_preview = content[:150]
    if len(content) > 150:
        old_preview += "…"
    new_preview = formatted[:300]
    if len(formatted) > 300:
        new_preview += "…"

    await query.message.reply_text(
        f"✨ <b>AI taklifi:</b>\n\n{safe_html(new_preview)}\n\n"
        f"📝 Asl: <i>{html_escape(old_preview)}</i>",
        reply_markup=_get_ai_result_keyboard(),
        parse_mode="HTML",
    )
    return GET_BTN_TITLE


async def ai_result_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI natijasini qabul qilish / rad etish."""
    query = update.callback_query
    data = query.data
    action = data.split(":", 1)[1] if ":" in data else ""

    if action == "accept":
        proposed = context.user_data.get("ai_proposed_content", "")
        if proposed:
            context.user_data["content"] = proposed
            context.user_data["post_type"] = "text"
            context.user_data["file_id"] = None
        context.user_data.pop("ai_original_content", None)
        context.user_data.pop("ai_proposed_content", None)
        context.user_data.pop("ai_last_action", None)
        await query.answer("✅ Qabul qilindi!")
        await query.message.reply_text(
            f"✅ <b>Yangi matn qabul qilindi!</b>\n\n{safe_html(proposed[:300])}",
            parse_mode="HTML",
        )
        return GET_BTN_TITLE

    if action == "revert":
        original = context.user_data.get("ai_original_content", "")
        if original:
            context.user_data["content"] = original
        context.user_data.pop("ai_original_content", None)
        context.user_data.pop("ai_proposed_content", None)
        context.user_data.pop("ai_last_action", None)
        await query.answer("❌ Asl holatga qaytarildi!")
        await query.message.reply_text(
            "❌ <b>Asl matn qaytarildi.</b>",
            parse_mode="HTML",
        )
        return GET_BTN_TITLE

    if action == "retry":
        await query.answer("🔄 Qayta urinilmoqda...")
        content = context.user_data.get("ai_original_content", context.user_data.get("content", ""))
        last_action = context.user_data.get("ai_last_action", "grammar")

        from utils.ai_agent import format_post_text
        result = await format_post_text(content, last_action)

        if "error" in result:
            await query.message.reply_text(result["error"], parse_mode="HTML")
            return GET_BTN_TITLE

        formatted = result.get("formatted", "")
        if formatted:
            context.user_data["ai_proposed_content"] = formatted
            new_preview = formatted[:300]
            if len(formatted) > 300:
                new_preview += "…"
            await query.message.reply_text(
                f"✨ <b>AI taklifi (qayta):</b>\n\n{safe_html(new_preview)}",
                reply_markup=_get_ai_result_keyboard(),
                parse_mode="HTML",
            )
        return GET_BTN_TITLE

    return GET_BTN_TITLE
