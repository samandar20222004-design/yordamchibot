from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import get_main_keyboard, get_cabinet_keyboard
from keyboards.inline import get_referral_share_keyboard, get_subscription_check_keyboard
from utils.helpers import html_escape

async def check_user_subscribed(bot, user_id: int) -> tuple[bool, list]:
    if user_id == ADMIN_ID:
        return True, []
    sponsors = db.get_active_sponsors()
    if not sponsors:
        return True, []
        
    unsubscribed = []
    for s in sponsors:
        s_id, ch_id, ch_title, ch_url = s
        try:
            target_chat = int(ch_id) if str(ch_id).lstrip('-').isdigit() else ch_id
            member = await bot.get_chat_member(chat_id=target_chat, user_id=user_id)
            if member.status not in ("creator", "administrator", "member", "restricted"):
                unsubscribed.append(s)
        except TelegramError:
            pass
    return (len(unsubscribed) == 0), unsubscribed

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.effective_user
    
    referrer_id = None
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                referrer_id = int(arg.replace("ref_", ""))
            except ValueError:
                referrer_id = None
    
    is_new = db.save_user(user.id, user.username or "", user.full_name or "", referrer_id=referrer_id)
    
    if is_new and referrer_id:
        try:
            await context.bot.send_message(
                chat_id=referrer_id,
                text="🎉 <b>Yangi do'st taklif qilindi!</b>\n\nSizning taklif havolangiz orqali yangi foydalanuvchi qo'shildi va hisobingizga <b>+3 ta bepul AI so'rovi</b> qo'shildi! 🚀",
                parse_mode="HTML"
            )
        except Exception:
            pass
            
    is_sub, unsubs = await check_user_subscribed(context.bot, user.id)
    if not is_sub:
        await update.message.reply_text(
            "📢 <b>Botdan to'liq foydalanish uchun quyidagi homiy kanallarga obuna bo'ling:</b>",
            reply_markup=get_subscription_check_keyboard(unsubs),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    is_admin = (user.id == ADMIN_ID)
    await update.message.reply_text(
        f"Salom, <b>{html_escape(user.first_name)}</b>! 👋\n\n"
        f"🤖 <b>PostAssistrobot</b> — Telegram kanallaringizga postlarni rejalashtirib joylovchi aqlli yordamchingiz.\n\n"
        f"Quyidagi menyudan kerakli bo'limni tanlang 👇",
        reply_markup=get_main_keyboard(is_admin),
        parse_mode="HTML"
    )
    return ConversationHandler.END

async def subscription_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    is_sub, unsubs = await check_user_subscribed(context.bot, user.id)
    
    if is_sub:
        await query.answer("✅ Obuna tasdiqlandi!")
        await query.message.delete()
        is_admin = (user.id == ADMIN_ID)
        await context.bot.send_message(
            chat_id=user.id,
            text=f"Xush kelibsiz, <b>{html_escape(user.first_name)}</b>! Barcha imkoniyatlar siz uchun ochiq.",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML"
        )
    else:
        await query.answer("⚠️ Hali barcha kanallarga a'zo bo'lmadingiz!", show_alert=True)
        try:
            await query.edit_message_reply_markup(reply_markup=get_subscription_check_keyboard(unsubs))
        except TelegramError:
            pass

async def user_cabinet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shaxsiy kabinet menyusi."""
    context.user_data.clear()
    user = update.effective_user
    is_admin = (user.id == ADMIN_ID)
    stats = db.get_referral_stats(user.id)
    channels = db.get_user_channels(user.id)
    
    credits_text = "♾ Cheksiz (Super Admin)" if is_admin else f"<b>{stats['ai_credits']} ta</b>"
    
    text = (
        f"👤 <b>Shaxsiy Kabinet:</b>\n\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"💎 Mavjud AI so'rovlar soni: {credits_text}\n"
        f"📢 Ulangan kanallar: <b>{len(channels)} ta</b>\n"
        f"👥 Taklif qilgan do'stlaringiz: <b>{stats['referrals_count']} ta</b>\n\n"
        f"Quyidagi bo'limlardan birini tanlang 👇"
    )
    await update.message.reply_text(text, reply_markup=get_cabinet_keyboard(), parse_mode="HTML")

async def user_invite_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Do'stlarni taklif qilish bo'limi."""
    context.user_data.clear()
    user = update.effective_user
    is_admin = (user.id == ADMIN_ID)
    bot_obj = await context.bot.get_me()
    stats = db.get_referral_stats(user.id)
    ref_link = f"https://t.me/{bot_obj.username}?start=ref_{user.id}"
    
    credits_text = "♾ Cheksiz (Super Admin)" if is_admin else f"<b>{stats['ai_credits']} ta</b>"
    
    text = (
        f"🚀 <b>Do'stlarni taklif qiling va bepul AI so'rovlar oling:</b>\n\n"
        f"🎁 <i>Har bir yangi do'stingiz uchun hisobingizga <b>+3 ta bepul AI so'rovi</b> qo'shiladi!</i>\n\n"
        f"💎 Sizdagi mavjud AI so'rovlar soni: {credits_text}\n"
        f"👥 Taklif qilingan do'stlaringiz: <b>{stats['referrals_count']} ta</b>\n\n"
        f"🔗 <b>Sizning taklif havolangiz:</b>\n<code>{ref_link}</code>"
    )
    await update.message.reply_text(
        text,
        reply_markup=get_referral_share_keyboard(ref_link),
        parse_mode="HTML"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """To'liq qo'llanma va bot vazifalari."""
    is_admin = (update.effective_user.id == ADMIN_ID)
    text = (
        "📖 <b>PostAssistrobot — To'liq Qo'llanma:</b>\n\n"
        "🔹 <b>1. Yangi post rejalashtirish:</b>\n"
        "• Matn, rasm, video, audio yoki premium stikerli postlarni istalgan sanaga (bir marta, har kuni yoki haftalik) rejalashtirish.\n"
        "• Post ostiga havola tugmalar (URL button) va reaksiyalar qo'shish.\n"
        "• <b>Avto-o'chirish:</b> Reklama postlarini kanalda 12, 24, 48 yoki 72 soat turgandan so'ng avtomatik o'chirish.\n\n"
        "🔹 <b>2. AI Post Yordamchi (Sun'iy Intellekt):</b>\n"
        "• Istalgan mavzuni erkin yozing (masalan: <i>'Ertaga 18:00 ga chegirmalar haqida post yoz'</i>).\n"
        "• AI o'zbek tilidagi shevalar va qisqartmalarni tushunib, post tayyorlaydi va chiqish vaqtini o'zi belgilaydi.\n\n"
        "🔹 <b>3. Ballar va AI So'rovlar tizimi:</b>\n"
        "• Har bir yangi foydalanuvchiga <b>5 ta bepul AI so'rovi</b> beriladi.\n"
        "• Har bir do'stingizni taklif qilganingiz uchun <b>+3 ta bepul AI so'rovi</b> sovg'a qilinadi.\n\n"
        "🔹 <b>4. Matn O'girgich (Lotin ⇄ Kirill):</b>\n"
        "• Istalgan matn yoki rasm/video tagidagi izohlarni bir zumda ikki alifboga xatosiz o'girib beradi.\n\n"
        "⚙️ <b>Tezkor buyruqlar:</b>\n"
        "/start — Bosh menyu\n"
        "/newpost — Yangi post\n"
        "/profile — Kabinet va taklif havolasi\n"
        "/help — Ushbu yo'riqnoma\n"
        "/cancel — Joriy amalni bekor qilish"
    )
    if is_admin:
        text += "\n\n👑 <b>Admin buyruqlari:</b>\n/admin — Boshqaruv paneli\n/broadcast — Hammaga xabar yuborish\n/stats — Statistika"
    await update.message.reply_text(text, reply_markup=get_main_keyboard(is_admin), parse_mode="HTML")

async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = (update.effective_user.id == ADMIN_ID)
    context.user_data.clear()
    await update.message.reply_text("🚫 Jarayon bekor qilindi.", reply_markup=get_main_keyboard(is_admin), parse_mode="HTML")
    return ConversationHandler.END
