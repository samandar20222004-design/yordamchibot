import logging
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import get_cancel_keyboard, get_main_keyboard
from utils.ai_agent import analyze_user_prompt
from utils.helpers import html_escape

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

AI_INPUT = 400
AI_CONFIRM = 401

async def start_ai_assistant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI yordamchisini ishga tushirish va so'rovlar sonini tekshirish."""
    context.user_data.clear()
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)
    credits = db.get_user_credits(user_id)
    
    if not is_admin and credits <= 0:
        bot_obj = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_obj.username}?start=ref_{user_id}"
        await update.message.reply_text(
            "⚠️ <b>Sizda bepul AI so'rovlari soni tugadi!</b>\n\n"
            "Ko'proq so'rov olish uchun do'stlaringizni taklif qiling.\n"
            "🎁 <i>Har bir do'stingiz uchun sizga <b>+3 ta bepul so'rov</b> beriladi!</i>\n\n"
            f"🔗 Sizning taklif havolangiz:\n<code>{ref_link}</code>",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    limit_info = "♾ Cheksiz (Super Admin)" if is_admin else f"<b>{credits} ta</b>"

    await update.message.reply_text(
        f"🤖 <b>AI Post Yordamchisiga xush kelibsiz!</b>\n\n"
        f"💎 Sizdagi mavjud so'rovlar soni: {limit_info}\n\n"
        f"Istalgan sohada qanday post tayyorlash kerakligini erkin yozing:\n"
        f"👉 <i>Masalan: 'Ertaga soat 15:00 ga chegirmalar haqida qiziqarli post yozib kanalga rejalashtir'</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return AI_INPUT

async def ai_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi matnini AI orqali tahlil qilish."""
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)
    prompt = update.message.text
    
    if not prompt:
        await update.message.reply_text("Iltimos, matnli buyruq yuboring:")
        return AI_INPUT

    msg_wait = await update.message.reply_text("⏳ <i>AI post tayyorlamoqda, iltimos kuting...</i>", parse_mode="HTML")
    
    result = analyze_user_prompt(prompt, user_id=user_id)
    await msg_wait.delete()
    
    if "error" in result:
        await update.message.reply_text(
            f"⚠️ {result['error']}",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    if not is_admin:
        db.use_user_credit(user_id)
    
    post_text = result.get("post_text", "")
    sched_time = result.get("scheduled_time")
    
    context.user_data["ai_generated_post"] = post_text
    context.user_data["ai_scheduled_time"] = sched_time
    
    time_info = f"\n\n🕒 <b>Rejalashtirilgan chiqish vaqti:</b> <code>{sched_time}</code>" if sched_time else "\n\n🕒 <b>Chiqish vaqti:</b> Ko'rsatilmadi (Tasdiqlansa hozir chiqadi)"
    
    keyboard = [
        [InlineKeyboardButton("✅ Kanalga rejalashtirish", callback_data="ai_post_schedule")],
        [InlineKeyboardButton("🔄 Qaytadan yozish", callback_data="ai_post_retry")]
    ]
    
    await update.message.reply_text(
        f"✨ <b>AI tomonidan tayyorlangan post:</b>\n\n"
        f"{html_escape(post_text)}"
        f"{time_info}\n\n"
        f"Ushbu postni kanalingizga rejalashtiramizmi?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return AI_CONFIRM

async def ai_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Postni kanalga saqlash."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    is_admin = (user_id == ADMIN_ID)
    
    if data == "ai_post_retry":
        await query.message.reply_text("Yangi buyruqni yozing:", reply_markup=get_cancel_keyboard())
        return AI_INPUT

    post_text = context.user_data.get("ai_generated_post", "")
    sched_time_str = context.user_data.get("ai_scheduled_time")
    
    channels = db.get_user_channels(user_id)
    if not channels:
        await query.message.reply_text(
            "⚠️ Sizda ulangan kanallar topilmadi. Avval 'Kanal/Guruhlar' bo'limidan kanal ulang.",
            reply_markup=get_main_keyboard(is_admin)
        )
        return ConversationHandler.END

    now = datetime.now(tashkent_tz)
    post_time = now
    if sched_time_str:
        try:
            naive = datetime.strptime(sched_time_str, "%Y-%m-%d %H:%M")
            post_time = tashkent_tz.localize(naive)
            if post_time <= now:
                post_time = now
        except Exception:
            post_time = now

    ch_id, ch_title = channels[0]
    pid = db.add_post(
        user_id=user_id,
        channel_id=ch_id,
        post_type="text",
        content=post_text,
        file_id=None,
        scheduled_time=post_time,
        recurrence_type='none'
    )
    
    if pid:
        await query.message.reply_text(
            f"✅ <b>AI Posti muvaffaqiyatli rejalashtirildi!</b>\n\n"
            f"📢 Kanal: <b>{html_escape(ch_title)}</b>\n"
            f"⏰ Chiqish vaqti: <b>{post_time.strftime('%Y-%m-%d %H:%M')}</b>",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML"
        )
    else:
        await query.message.reply_text("❌ Saqlashda xatolik yuz berdi.", reply_markup=get_main_keyboard(is_admin))
        
    context.user_data.clear()
    return ConversationHandler.END
