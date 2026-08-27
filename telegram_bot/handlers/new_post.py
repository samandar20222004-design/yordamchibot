from datetime import datetime, timedelta
import re
import pytz
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import (
    BTN_ALL_CHANNELS_TARGET, BTN_MAIN_MENU, BTN_SKIP_BUTTON,
    BTN_T_5MIN, BTN_T_15MIN, BTN_T_30MIN, BTN_T_1H, BTN_T_2H,
    BTN_T_TOM_9, BTN_T_TOM_18, BTN_T_3D, BTN_T_RECURRING,
    WEEKDAY_MAP, WEEKDAY_LABELS,
    get_main_keyboard, get_cancel_keyboard, get_button_prompt_keyboard,
    get_time_keyboard, get_weekday_keyboard
)
from utils.helpers import md_escape

tashkent_tz = pytz.timezone("Asia/Tashkent")
CHOOSE_CHANNEL, GET_CONTENT, GET_BUTTON, GET_REACTIONS, GET_TIME, RECUR_DAY, RECUR_TIME = range(7)

BTN_REACT_DEFAULT = "👍 ❤️ 🔥 👏"
BTN_NO_REACT = "➡️ Reaksiyasiz davom etish"

def get_reactions_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_REACT_DEFAULT],
            [BTN_NO_REACT],
            [BTN_MAIN_MENU]
        ],
        resize_keyboard=True
    )

async def start_new_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)

    channels = db.get_user_channels(user_id)
    if not channels:
        await update.message.reply_text(
            "⚠️ *Ulangan kanal yoki guruh topilmadi!*\n\n"
            "Avval **'📢 Kanal/Guruhlar'** bo'limidan kanal yoki guruhingizni ulang.",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    keyboard = [[ch[1]] for ch in channels]
    if len(channels) > 1:
        keyboard.append([BTN_ALL_CHANNELS_TARGET])
    keyboard.append([BTN_MAIN_MENU])
    
    context.user_data["channels_map"] = {ch[1]: ch[0] for ch in channels}
    await update.message.reply_text(
        "📢 *Qaysi kanal yoki guruhga post rejalashtiramiz?*\nRo'yxatdan tanlang 👇",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
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
        f"✅ Tanlandi: *{md_escape(context.user_data['selected_channel_title'])}*\n\n"
        f"📝 *Post uchun kontentni yuboring:* (Matn, rasm, video, audio yoki hujjat)",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    return GET_CONTENT

async def content_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    post_type, file_id, content = None, None, ""

    if msg.photo:
        post_type, file_id, content = "photo", msg.photo[-1].file_id, msg.caption or ""
    elif msg.video:
        post_type, file_id, content = "video", msg.video.file_id, msg.caption or ""
    elif msg.animation:
        post_type, file_id, content = "animation", msg.animation.file_id, msg.caption or ""
    elif msg.document:
        post_type, file_id, content = "document", msg.document.file_id, msg.caption or ""
    elif msg.audio:
        post_type, file_id, content = "audio", msg.audio.file_id, msg.caption or ""
    elif msg.voice:
        post_type, file_id = "voice", msg.voice.file_id
    elif msg.video_note:
        post_type, file_id = "video_note", msg.video_note.file_id
    elif msg.sticker:
        post_type, file_id = "sticker", msg.sticker.file_id
    elif msg.text:
        post_type, content = "text", msg.text

    if post_type is None:
        await msg.reply_text("⚠️ Noma'lum format. Rasm, video, matn yoki fayl yuboring.")
        return GET_CONTENT

    context.user_data["post_type"] = post_type
    context.user_data["file_id"] = file_id
    context.user_data["content"] = content

    await msg.reply_text(
        "🔗 *Post ostiga havola (URL) tugma qo'shilsinmi?*\n\n"
        "Shunchaki kanal username yoki havolasini yozing:\n"
        "• `@kanalim` yoki `https://t.me/kanalim`\n"
        "• `Batafsil - @kanalim` yoki `Saytga o'tish - https://sayt.uz`\n\n"
        "Tugma kerak bo'lmasa pastdagi **'➡️ Tugmasiz davom etish'** tugmasini bosing:",
        reply_markup=get_button_prompt_keyboard(),
        parse_mode="Markdown"
    )
    return GET_BUTTON

async def button_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == BTN_SKIP_BUTTON:
        context.user_data["btn_text"], context.user_data["btn_url"] = None, None
    else:
        btn_title, btn_link = "Batafsil", text
        if " - " in text:
            btn_title, btn_link = text.split(" - ", 1)
            btn_title, btn_link = btn_title.strip(), btn_link.strip()
        
        if btn_link.startswith("@"):
            btn_link = f"https://t.me/{btn_link.replace('@', '')}"
        elif not (btn_link.startswith("http://") or btn_link.startswith("https://") or btn_link.startswith("t.me/")):
            if "." in btn_link:
                btn_link = "https://" + btn_link
            else:
                btn_link = f"https://t.me/{btn_link}"

        context.user_data["btn_text"] = btn_title
        context.user_data["btn_url"] = btn_link

    await update.message.reply_text(
        "🔥 *Post ostiga reaksiya tugmalari qo'shilsinmi?*\n\n"
        "Tayyor variantni tanlang yoki xohlagan emojilaringizni probel bilan yuboring:\n"
        "Masalan: `👍 ❤️ 🔥 👏 ⚡️ 😍` (10 tagacha)",
        reply_markup=get_reactions_keyboard(),
        parse_mode="Markdown"
    )
    return GET_REACTIONS

async def reactions_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == BTN_NO_REACT:
        context.user_data["enable_reactions"] = False
        context.user_data["custom_reactions"] = None
    else:
        context.user_data["enable_reactions"] = True
        emojis = re.findall(r'[^\s\w,.-]', text)
        if not emojis:
            emojis = ["👍", "❤️", "🔥", "👏"]
        context.user_data["custom_reactions"] = emojis[:10]

    now = datetime.now(tashkent_tz)
    example = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    await update.message.reply_text(
        "🕒 *Post qaysi vaqtda chiqsin?*\n\n"
        "Tayyor tugmalardan tanlang yoki aniq vaqtni yozing:\n"
        f"Namuna: `{example}`",
        reply_markup=get_time_keyboard(),
        parse_mode="Markdown"
    )
    return GET_TIME

async def _finalize_post(update, context, post_time, is_recurring=False, recurrence_day=None, recurrence_time_str=None):
    is_admin = (update.effective_user.id == ADMIN_ID)
    user_id = update.effective_user.id
    selected_channel_id = context.user_data["selected_channel_id"]
    post_type = context.user_data["post_type"]
    content = context.user_data.get("content")
    file_id = context.user_data.get("file_id")
    btn_text = context.user_data.get("btn_text")
    btn_url = context.user_data.get("btn_url")
    enable_reactions = context.user_data.get("enable_reactions", False)
    recurrence_time_obj = recurrence_time_str if is_recurring else None

    post_time_tz = post_time.astimezone(tashkent_tz)

    if selected_channel_id == "ALL":
        channels = db.get_user_channels(user_id)
        ok_count = 0
        for ch_id, ch_title in channels:
            pid = db.add_post(user_id, ch_id, post_type, content, file_id, post_time_tz,
                              is_recurring, recurrence_day, recurrence_time_obj, btn_text, btn_url, enable_reactions)
            if pid:
                ok_count += 1
        if ok_count:
            when_text = f"🔄 Har {WEEKDAY_LABELS.get(recurrence_day)}, soat {recurrence_time_str[:5]}" if is_recurring else f"🕒 {post_time_tz.strftime('%Y-%m-%d %H:%M')}"
            await update.message.reply_text(
                f"✅ *Post {ok_count} ta kanal/guruhga rejalashtirildi!*\n\n{when_text}",
                reply_markup=get_main_keyboard(is_admin),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ Saqlashda xatolik yuz berdi.", reply_markup=get_main_keyboard(is_admin))
    else:
        pid = db.add_post(user_id, selected_channel_id, post_type, content, file_id, post_time_tz,
                          is_recurring, recurrence_day, recurrence_time_obj, btn_text, btn_url, enable_reactions)
        if pid:
            when_text = f"🔄 Har {WEEKDAY_LABELS.get(recurrence_day)}, soat {recurrence_time_str[:5]}" if is_recurring else f"🕒 {post_time_tz.strftime('%Y-%m-%d %H:%M')}"
            await update.message.reply_text(
                f"✅ *Post muvaffaqiyatli rejalashtirildi!*\n\n📢 Joylash: *{md_escape(context.user_data['selected_channel_title'])}*\n{when_text}",
                reply_markup=get_main_keyboard(is_admin),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ Saqlashda xatolik yuz berdi.", reply_markup=get_main_keyboard(is_admin))
    context.user_data.clear()

async def time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    now = datetime.now(tashkent_tz)
    if text == BTN_T_RECURRING:
        await update.message.reply_text("🔄 *Har hafta qaysi kuni chiqsin?*", reply_markup=get_weekday_keyboard(), parse_mode="Markdown")
        return RECUR_DAY

    post_time = None
    try:
        if text == BTN_T_5MIN:
            post_time = now + timedelta(minutes=5)
        elif text == BTN_T_15MIN:
            post_time = now + timedelta(minutes=15)
        elif text == BTN_T_30MIN:
            post_time = now + timedelta(minutes=30)
        elif text == BTN_T_1H:
            post_time = now + timedelta(hours=1)
        elif text == BTN_T_2H:
            post_time = now + timedelta(hours=2)
        elif text == BTN_T_TOM_9:
            post_time = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        elif text == BTN_T_TOM_18:
            post_time = (now + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        elif text == BTN_T_3D:
            post_time = (now + timedelta(days=3)).replace(hour=9, minute=0, second=0, microsecond=0)
        else:
            naive_time = datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
            post_time = tashkent_tz.localize(naive_time)
        if post_time <= now:
            await update.message.reply_text("⚠️ Kelajakdagi vaqtni kiriting:")
            return GET_TIME
    except Exception:
        await update.message.reply_text("⚠️ Format xato! `2026-08-28 18:00` shaklida yuboring.")
        return GET_TIME

    await _finalize_post(update, context, post_time)
    return ConversationHandler.END

async def recur_day_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text not in WEEKDAY_MAP:
        await update.message.reply_text("⚠️ Pastdagi kunlardan birini tanlang:")
        return RECUR_DAY
    context.user_data["recurrence_day"] = WEEKDAY_MAP[text]
    await update.message.reply_text(f"🕒 *Har {text} soat nechida chiqsin?*\nMasalan: `18:00`", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
    return RECUR_TIME

async def recur_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        hh, mm = text.split(":")
        hh, mm = int(hh), int(mm)
        assert 0 <= hh < 24 and 0 <= mm < 60
    except Exception:
        await update.message.reply_text("⚠️ Format xato! Masalan: `18:00`", parse_mode="Markdown")
        return RECUR_TIME

    now = datetime.now(tashkent_tz)
    target_weekday = context.user_data["recurrence_day"]
    days_ahead = (target_weekday - now.weekday() + 7) % 7
    candidate = (now + timedelta(days=days_ahead)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=7)
    recurrence_time_str = f"{hh:02d}:{mm:02d}:00"

    await _finalize_post(update, context, candidate, is_recurring=True, recurrence_day=target_weekday, recurrence_time_str=recurrence_time_str)
    return ConversationHandler.END
