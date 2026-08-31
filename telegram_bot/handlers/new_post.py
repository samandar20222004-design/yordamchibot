import asyncio
import json
import time
from datetime import datetime, timedelta
import pytz
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID, ADMIN_IDS_SET
import database as db
from keyboards.default import (
    BTN_ALL_CHANNELS_TARGET, BTN_MAIN_MENU, BTN_SKIP_BUTTON,
    BTN_REACT_DEFAULT, BTN_NO_REACT,
    BTN_T_5MIN, BTN_T_15MIN, BTN_T_1H, BTN_T_DAILY, BTN_T_WEEKLY,
    BTN_DUR_1W, BTN_DUR_1M, BTN_DUR_3M, BTN_DUR_6M, BTN_DUR_1Y, BTN_DUR_INF,
    WEEKDAY_MAP, WEEKDAY_LABELS,
    get_main_keyboard, get_cancel_keyboard, get_button_prompt_keyboard,
    get_reactions_keyboard, get_auto_delete_keyboard, get_time_keyboard,
    get_duration_keyboard, get_weekday_keyboard
)
from keyboards.inline import btn_label
from utils.helpers import html_escape, parse_future_time

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
    text = update.message.text.strip()
    # Qat'iy tekshiruv: reaksiyalar FAQAT "👍 ❤️ 🔥 👏" tugmasi bosilganda qo'shiladi.
    # Boshqa har qanday matn (xato bosish, yozilgan so'z) reaksiya qo'shmaydi.
    if text == BTN_REACT_DEFAULT:
        context.user_data["enable_reactions"] = True
    elif text == BTN_NO_REACT:
        context.user_data["enable_reactions"] = False
    else:
        await update.message.reply_text(
            "⚠️ <b>Iltimos, quyidagi tugmalardan birini tanlang:</b>\n"
            "• <code>👍 ❤️ 🔥 👏</code> — reaksiya tugmalari bilan\n"
            "• <code>➡️ Reaksiyasiz davom etish</code> — reaksiyasiz",
            reply_markup=get_reactions_keyboard(),
            parse_mode="HTML"
        )
        return GET_REACTIONS

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

    await _save_and_finish(update, context, post_time, recurrence_type='none')
    return ConversationHandler.END

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

    await _save_and_finish(
        update, context,
        post_time=context.user_data["rec_first_run"],
        recurrence_type=context.user_data["rec_type"],
        recurrence_day=context.user_data["rec_day"],
        recurrence_time_str=context.user_data["rec_time_str"],
        end_date=end_date
    )
    return ConversationHandler.END
