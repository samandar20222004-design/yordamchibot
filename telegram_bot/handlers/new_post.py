from datetime import datetime, timedelta
import pytz
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import (
    BTN_ALL_CHANNELS_TARGET, BTN_MAIN_MENU, BTN_SKIP_BUTTON,
    BTN_NO_REACT,
    BTN_T_5MIN, BTN_T_15MIN, BTN_T_1H, BTN_T_DAILY, BTN_T_WEEKLY,
    BTN_DUR_1M, BTN_DUR_3M, BTN_DUR_6M, BTN_DUR_1Y, BTN_DUR_INF,
    WEEKDAY_MAP, WEEKDAY_LABELS,
    get_main_keyboard, get_cancel_keyboard, get_button_prompt_keyboard,
    get_reactions_keyboard, get_time_keyboard, get_duration_keyboard, get_weekday_keyboard
)
from utils.helpers import md_escape

tashkent_tz = pytz.timezone("Asia/Tashkent")
(CHOOSE_CHANNEL, GET_CONTENT, GET_BTN_TITLE, 
 GET_BTN_URL, GET_REACTIONS, GET_TIME, 
 DAILY_TIME, RECUR_DAY, RECUR_TIME, GET_DURATION) = range(10)

async def start_new_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)

    channels = db.get_user_channels(user_id)
    if not channels:
        await update.message.reply_text(
            "⚠️ Ulangan kanal yoki guruh topilmadi!\n\n"
            "Avval '📢 Kanal/Guruhlar' bo'limidan kanal yoki guruhingizni ulang.",
            reply_markup=get_main_keyboard(is_admin)
        )
        return ConversationHandler.END

    keyboard = [[ch[1]] for ch in channels]
    if len(channels) > 1:
        keyboard.append([BTN_ALL_CHANNELS_TARGET])
    keyboard.append([BTN_MAIN_MENU])
    
    context.user_data["channels_map"] = {ch[1]: ch[0] for ch in channels}
    await update.message.reply_text(
        "📢 Qaysi kanal yoki guruhga post rejalashtiramiz?\nRo'yxatdan tanlang 👇",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
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
        f"✅ Tanlandi: {context.user_data['selected_channel_title']}\n\n"
        f"📝 Post uchun kontentni yuboring (Matn, rasm, video, audio yoki boshqa kanaldan forward qilingan xabar):",
        reply_markup=get_cancel_keyboard()
    )
    return GET_CONTENT

async def content_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    # Asl xabarning to'liq formatini (premium emojilar, stil) saqlab qolamiz
    context.user_data["post_type"] = "original_message"
    context.user_data["file_id"] = str(msg.message_id)
    context.user_data["content"] = msg.caption or msg.text or ""

    await msg.reply_text(
        "🔗 Post ostiga havola tugma qo'shilsinmi?\n\n"
        "Tugma ustidagi yozuvni tanlang yoki o'zingiz yozing:\n"
        "Kerak bo'lmasa, '➡️ Tugmasiz davom etish' ni bosing:",
        reply_markup=get_button_prompt_keyboard()
    )
    return GET_BTN_TITLE

async def btn_title_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == BTN_SKIP_BUTTON:
        context.user_data["btn_text"], context.user_data["btn_url"] = None, None
        await update.message.reply_text(
            "🔥 Post ostiga reaksiya tugmalari qo'shilsinmi?",
            reply_markup=get_reactions_keyboard()
        )
        return GET_REACTIONS

    context.user_data["btn_text"] = text
    await update.message.reply_text(
        f"🌐 '{text}' tugmasi bosilganda ochiladigan havola yoki kanal username'ini yuboring:\n\n"
        f"Masalan: @kanalim yoki https://sayt.uz",
        reply_markup=get_cancel_keyboard()
    )
    return GET_BTN_URL

async def btn_url_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    btn_link = text
    if btn_link.startswith("@"):
        btn_link = f"https://t.me/{btn_link.replace('@', '')}"
    elif not (btn_link.startswith("http://") or btn_link.startswith("https://") or btn_link.startswith("t.me/")):
        if "." in btn_link:
            btn_link = "https://" + btn_link
        else:
            btn_link = f"https://t.me/{btn_link}"

    context.user_data["btn_url"] = btn_link
    await update.message.reply_text(
        "🔥 Post ostiga reaksiya tugmalari qo'shilsinmi?",
        reply_markup=get_reactions_keyboard()
    )
    return GET_REACTIONS

async def reactions_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["enable_reactions"] = (text != BTN_NO_REACT)

    now = datetime.now(tashkent_tz)
    example = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    await update.message.reply_text(
        "🕒 Post qaysi vaqtda chiqsin?\n\n"
        "Tayyor tugmalardan tanlang yoki aniq vaqtni yozing:\n"
        f"Namuna: {example}",
        reply_markup=get_time_keyboard()
    )
    return GET_TIME

async def _save_and_finish(update, context, post_time, recurrence_type='none', recurrence_day=None, recurrence_time_str=None, end_date=None):
    is_admin = (update.effective_user.id == ADMIN_ID)
    user_id = update.effective_user.id
    selected_channel_id = context.user_data["selected_channel_id"]
    post_type = context.user_data["post_type"]
    content = context.user_data.get("content")
    file_id = context.user_data.get("file_id")
    btn_text = context.user_data.get("btn_text")
    btn_url = context.user_data.get("btn_url")
    enable_reactions = context.user_data.get("enable_reactions", False)
    post_time_tz = post_time.astimezone(tashkent_tz)

    channels = db.get_user_channels(user_id) if selected_channel_id == "ALL" else [(selected_channel_id, context.user_data.get("selected_channel_title"))]
    ok_count = 0
    for ch_id, _ in channels:
        pid = db.add_post(
            user_id=user_id, channel_id=ch_id, post_type=post_type, content=content,
            file_id=file_id, scheduled_time=post_time_tz, recurrence_type=recurrence_type,
            recurrence_day=recurrence_day, recurrence_time=recurrence_time_str, end_date=end_date,
            btn_text=btn_text, btn_url=btn_url, enable_reactions=enable_reactions
        )
        if pid:
            ok_count += 1

    if ok_count:
        if recurrence_type == 'daily':
            when_text = f"🔄 Har kuni, soat {recurrence_time_str[:5]} da"
        elif recurrence_type == 'weekly':
            when_text = f"🔄 Har {WEEKDAY_LABELS.get(recurrence_day)}, soat {recurrence_time_str[:5]} da"
        else:
            when_text = f"🕒 {post_time_tz.strftime('%Y-%m-%d %H:%M')}"
            
        await update.message.reply_text(
            f"✅ Post muvaffaqiyatli rejalashtirildi!\n\n"
            f"📢 Joylash: {context.user_data['selected_channel_title']}\n"
            f"{when_text}",
            reply_markup=get_main_keyboard(is_admin)
        )
    else:
        await update.message.reply_text("❌ Saqlashda xatolik yuz berdi.", reply_markup=get_main_keyboard(is_admin))
    context.user_data.clear()

async def time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    now = datetime.now(tashkent_tz)
    
    if text == BTN_T_DAILY:
        await update.message.reply_text("🕒 Har kuni soat nechida chiqsin?\nMasalan: 10:00 yoki 18:30", reply_markup=get_cancel_keyboard())
        return DAILY_TIME
    elif text == BTN_T_WEEKLY:
        await update.message.reply_text("📅 Haftaning qaysi kuni chiqsin?", reply_markup=get_weekday_keyboard())
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
            naive_time = datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
            post_time = tashkent_tz.localize(naive_time)
        if post_time <= now:
            await update.message.reply_text("⚠️ Kelajakdagi vaqtni kiriting:")
            return GET_TIME
    except Exception:
        await update.message.reply_text("⚠️ Format xato! 2026-08-28 18:00 shaklida yuboring.")
        return GET_TIME

    await _save_and_finish(update, context, post_time, recurrence_type='none')
    return ConversationHandler.END

async def daily_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        hh, mm = map(int, text.split(":"))
        assert 0 <= hh < 24 and 0 <= mm < 60
    except Exception:
        await update.message.reply_text("⚠️ Noto'g'ri vaqt formati. Masalan: 10:00")
        return DAILY_TIME

    now = datetime.now(tashkent_tz)
    first_run = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if first_run <= now:
        first_run += timedelta(days=1)

    context.user_data["rec_first_run"] = first_run
    context.user_data["rec_type"] = "daily"
    context.user_data["rec_time_str"] = f"{hh:02d}:{mm:02d}:00"
    context.user_data["rec_day"] = None

    await update.message.reply_text("⏳ Post qancha muddat davomida har kuni chiqsin?", reply_markup=get_duration_keyboard())
    return GET_DURATION

async def recur_day_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text not in WEEKDAY_MAP:
        await update.message.reply_text("⚠️ Kunlardan birini tanlang:")
        return RECUR_DAY
    context.user_data["rec_day"] = WEEKDAY_MAP[text]
    await update.message.reply_text(f"🕒 Har {text} soat nechida chiqsin?\nMasalan: 10:00", reply_markup=get_cancel_keyboard())
    return RECUR_TIME

async def recur_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        hh, mm = map(int, text.split(":"))
        assert 0 <= hh < 24 and 0 <= mm < 60
    except Exception:
        await update.message.reply_text("⚠️ Noto'g'ri format! Masalan: 10:00")
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

    await update.message.reply_text("⏳ Ushbu post qancha muddat davomida chiqsin?", reply_markup=get_duration_keyboard())
    return GET_DURATION

async def duration_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    now = datetime.now(tashkent_tz)
    end_date = None

    if text == BTN_DUR_1M:
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
