import logging
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import (
    BTN_T_5MIN, BTN_T_15MIN, BTN_T_1H,
    get_cancel_keyboard, get_main_keyboard, get_time_keyboard
)
from utils.ai_agent import analyze_user_prompt
from utils.helpers import html_escape, check_ai_rate_limit, check_ai_daily_limit

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

AI_INPUT = 401
AI_CONFIRM = 402
AI_GET_TIME = 403

async def start_ai_assistant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)
    credits = await db.run_db(db.get_user_credits, user_id)
    
    if not is_admin and credits <= 0:
        bot_obj = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_obj.username}?start=ref_{user_id}"
        await update.message.reply_text(
            "⚠️ <b>Sizda bepul AI so'rovlari soni tugadi!</b>\n\n"
            "Ko'proq so'rov olish uchun do'stlaringizni taklif qiling.\n"
            "🎁 <i>Har bir do'stingiz uchun sizga <b>+3 ta bepul AI so'rovi</b> beriladi!</i>\n\n"
            f"🔗 Sizning taklif havolangiz:\n<code>{ref_link}</code>",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    limit_info = "♾ Cheksiz (Super Admin)" if is_admin else f"<b>{credits} ta</b>"

    await update.message.reply_text(
        f"🤖 <b>AI Post Yordamchisiga xush kelibsiz!</b>\n\n"
        f"💎 Sizdagi mavjud AI so'rovlar soni: {limit_info}\n\n"
        f"Istalgan post, matn, forward xabar yoki <b>rasm</b> yuboring:\n"
        f"👉 <i>Masalan: 'Ushbu postni bugun 13:00 ga kanalga rejalashtir' yoki shunchaki postning o'zini yuboring</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return AI_INPUT

async def ai_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)
    
    media_group_id = msg.media_group_id
    if media_group_id:
        if context.user_data.get("last_ai_media_group_id") == media_group_id:
            return AI_INPUT
        context.user_data["last_ai_media_group_id"] = media_group_id

    text_input = msg.text or msg.caption or ""
    file_id = None
    post_type = "text"
    
    if msg.photo:
        file_id = msg.photo[-1].file_id
        post_type = "photo"
    elif msg.video:
        file_id = msg.video.file_id
        post_type = "video"
    elif msg.document:
        file_id = msg.document.file_id
        post_type = "document"

    prev_instruction = context.user_data.get("last_user_instruction", "")
    
    if file_id and not text_input and prev_instruction:
        full_prompt = f"Foydalanuvchi buyrug'i: {prev_instruction}\nKontent: (Fayl/Rasm yuborildi)"
    elif prev_instruction and text_input:
        full_prompt = f"Foydalanuvchi buyrug'i: {prev_instruction}\nYuborilgan post matni:\n{text_input}"
    elif text_input:
        full_prompt = text_input
        context.user_data["last_user_instruction"] = text_input
    else:
        await msg.reply_text("Iltimos, post matni yoki mavzusini yuboring:")
        return AI_INPUT

    # AI so'rovlariga alohida rate-limit: daqiqasiga 4 tadan oshsa —
    # AI API'ga ortiqcha so'rov yubormaymiz (bepul balans va API limitlari saqlanadi).
    if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
        await msg.reply_text(
            "⏳ <i>AI so'rovlarini juda tez-tez yuboryapsiz. Iltimos, 1 daqiqa kuting...</i>",
            parse_mode="HTML"
        )
        return AI_INPUT

    # Kunlik AI limiti (24 soatda 30 ta) — bitta foydalanuvchi botning
    # AI byudjetini yeb qo'ymasligi uchun.
    if not is_admin and check_ai_daily_limit(user_id, max_per_day=30):
        await msg.reply_text(
            "⚠️ <i>Kunlik AI so'rovlar limiti tugadi (30 ta/kun). Ertaga qayta urinib ko'ring.</i>",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    # So'rov boshlanishidan oldin ballni atomik band qilamiz.
    # Aks holda bir nechta parallel AI so'rovi mavjud balansdan oshib ketishi mumkin.
    if not is_admin and not await db.run_db(db.use_user_credit, user_id):
        await msg.reply_text("⚠️ AI so'rovlari uchun ballaringiz yetarli emas.", reply_markup=get_main_keyboard(is_admin))
        return ConversationHandler.END

    msg_wait = await msg.reply_text("⏳ <i>AI tahlil qilmoqda, iltimos kuting...</i>", parse_mode="HTML")
    result = await analyze_user_prompt(full_prompt, user_id)
    
    try:
        await msg_wait.delete()
    except Exception:
        pass
    
    if "error" in result:
        if not is_admin:
            await db.run_db(db.add_user_credit, user_id)
        await msg.reply_text(
            f"⚠️ {result['error']}",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    post_text = result.get("post_text", "")
    sched_time = result.get("scheduled_time")
    has_explicit_time = result.get("has_explicit_time", False)
    target_all = result.get("target_all", False)
    
    context.user_data["ai_generated_post"] = post_text
    context.user_data["ai_scheduled_time"] = sched_time
    context.user_data["ai_post_type"] = post_type
    context.user_data["ai_file_id"] = file_id
    context.user_data["ai_target_all"] = target_all

    if not has_explicit_time or not sched_time:
        preview_text = (
            f"✨ <b>Qabul qilingan post:</b>\n\n"
            f"{html_escape(post_text)}\n\n"
            f"🕒 <b>Ushbu post qachon kanalga chiqsin?</b>\n"
            f"Quyidagi tayyor tugmalardan tanlang yoki aniq vaqtni yozing (Masalan: <code>2026-08-30 18:00</code>):"
        )
        if file_id:
            if post_type == "photo":
                await msg.reply_photo(photo=file_id, caption=preview_text[:1024], reply_markup=get_time_keyboard(), parse_mode="HTML")
            elif post_type == "video":
                await msg.reply_video(video=file_id, caption=preview_text[:1024], reply_markup=get_time_keyboard(), parse_mode="HTML")
            else:
                await msg.reply_document(document=file_id, caption=preview_text[:1024], reply_markup=get_time_keyboard(), parse_mode="HTML")
        else:
            await msg.reply_text(preview_text, reply_markup=get_time_keyboard(), parse_mode="HTML")
            
        return AI_GET_TIME

    time_info = f"\n\n🕒 <b>Rejalashtirilgan chiqish vaqti:</b> <code>{sched_time}</code>"
    target_info = "\n🌐 <b>Kanal:</b> Barcha ulangan kanallarga" if target_all else ""
    
    keyboard = [
        [InlineKeyboardButton("✅ Kanalga rejalashtirish", callback_data="ai_post_schedule")],
        [InlineKeyboardButton("🔄 Qaytadan yozish", callback_data="ai_post_retry")]
    ]
    
    preview_text = (
        f"✨ <b>Tayyorlangan post:</b>\n\n"
        f"{html_escape(post_text)}"
        f"{time_info}{target_info}\n\n"
        f"Ushbu postni rejalashtiramizmi?"
    )
    
    if file_id:
        if post_type == "photo":
            await msg.reply_photo(photo=file_id, caption=preview_text[:1024], reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        elif post_type == "video":
            await msg.reply_video(video=file_id, caption=preview_text[:1024], reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        else:
            await msg.reply_document(document=file_id, caption=preview_text[:1024], reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    else:
        await msg.reply_text(preview_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        
    return AI_CONFIRM

async def ai_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    now = datetime.now(tashkent_tz)
    post_time = None

    try:
        if text == BTN_T_5MIN:
            post_time = now + timedelta(minutes=5)
        elif text == BTN_T_15MIN:
            post_time = now + timedelta(minutes=15)
        elif text == BTN_T_1H:
            post_time = now + timedelta(hours=1)
        else:
            naive_time = datetime.strptime(text, "%Y-%m-%d %H:%M")
            post_time = tashkent_tz.localize(naive_time)
            
        if post_time <= now:
            await update.message.reply_text("⚠️ Kelajakdagi vaqtni kiriting:")
            return AI_GET_TIME
    except Exception:
        await update.message.reply_text("⚠️ Format xato! Masalan: <code>2026-08-30 18:00</code> shaklida yuboring.", parse_mode="HTML")
        return AI_GET_TIME

    context.user_data["ai_scheduled_time"] = post_time.strftime("%Y-%m-%d %H:%M")
    
    keyboard = [
        [InlineKeyboardButton("✅ Kanalga rejalashtirish", callback_data="ai_post_schedule")],
        [InlineKeyboardButton("🔄 Qaytadan yozish", callback_data="ai_post_retry")]
    ]
    
    await update.message.reply_text(
        f"🕒 <b>Chiqish vaqti belgilandi:</b> <code>{post_time.strftime('%Y-%m-%d %H:%M')}</code>\n\n"
        f"Postni kanalga rejalashtiramizmi?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return AI_CONFIRM

async def ai_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Post saqlanmoqda...")
    data = query.data
    user_id = query.from_user.id
    is_admin = (user_id == ADMIN_ID)
    
    if data == "ai_post_retry":
        context.user_data.clear()
        await query.message.reply_text("Yangi mavzu yoki buyruqni yozing:", reply_markup=get_cancel_keyboard())
        return AI_INPUT

    post_text = context.user_data.get("ai_generated_post", "")
    sched_time_str = context.user_data.get("ai_scheduled_time")
    post_type = context.user_data.get("ai_post_type", "text")
    file_id = context.user_data.get("ai_file_id")
    target_all = context.user_data.get("ai_target_all", False)
    
    channels = await db.run_db(db.get_user_channels, user_id)
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

    target_channels = channels if target_all else [channels[0]]
    ok_count = 0
    
    for ch_id, ch_title in target_channels:
        pid = await db.run_db(
            db.add_post,
            user_id=user_id,
            channel_id=ch_id,
            post_type=post_type,
            content=post_text,
            file_id=file_id,
            scheduled_time=post_time,
            recurrence_type='none'
        )
        if pid:
            ok_count += 1
            
    if ok_count > 0:
        target_name = "Barcha ulangan kanallarga" if target_all else channels[0][1]
        await query.message.reply_text(
            f"✅ <b>AI Posti muvaffaqiyatli rejalashtirildi!</b>\n\n"
            f"📢 Joylash: <b>{html_escape(target_name)}</b>\n"
            f"⏰ Chiqish vaqti: <b>{post_time.strftime('%Y-%m-%d %H:%M')}</b>",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML"
        )
    else:
        await query.message.reply_text("❌ Saqlashda xatolik yuz berdi.", reply_markup=get_main_keyboard(is_admin))
        
    context.user_data.clear()
    return ConversationHandler.END
