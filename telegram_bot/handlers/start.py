from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import get_main_keyboard, get_cabinet_keyboard, get_cancel_keyboard
from keyboards.inline import get_referral_share_keyboard, get_subscription_check_keyboard
from utils.helpers import html_escape

TRANSFER_TARGET = 500
TRANSFER_AMOUNT = 501

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
    user_code = db.get_user_code(user.id)
    
    credits_text = "♾ Cheksiz (Super Admin)" if is_admin else f"<b>{stats['ai_credits']} ta</b>"
    
    text = (
        f"👤 <b>Shaxsiy Kabinet:</b>\n\n"
        f"🆔 Sizning ID: <code>{user.id}</code>\n"
        f"🔑 Sizning kodingiz: <code>{user_code}</code>\n"
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

# --- BALLARNI ULASHISH (TRANSFER) ---
async def start_transfer_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ballarni boshqa do'stiga o'tkazishni boshlash."""
    context.user_data.clear()
    user_id = update.effective_user.id
    my_credits = db.get_user_credits(user_id)
    
    if my_credits < 3 and user_id != ADMIN_ID:
        await update.message.reply_text(
            f"⚠️ <b>Hisobingizda yetarli ball yo'q!</b>\n\n"
            f"Ball o'tkazish uchun hisobingizda kamida <b>3 ta ball</b> bo'lishi kerak. Sizda esa: <b>{my_credits} ta</b>.\n"
            f"Do'stlaringizni taklif qilib ko'proq ball to'plashingiz mumkin!",
            reply_markup=get_cabinet_keyboard(),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🎁 <b>Ballarni (AI so'rovlarni) ulashish:</b>\n\n"
        "Ballarni kimga yubormoqchisiz?\n"
        "Do'stingizning <b>ID raqamini</b>, <b>Telegram usernamesini (@ bilan)</b> yoki botdagi <b>maxsus kodini</b> yuboring:\n\n"
        "<i>(Bekor qilish uchun '🔙 Asosiy menyu' tugmasini bosing)</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return TRANSFER_TARGET

async def transfer_target_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_input = update.message.text
    target_user = db.find_user_by_target(target_input)
    
    if not target_user:
        await update.message.reply_text(
            "❌ <b>Foydalanuvchi topilmadi!</b>\n"
            "Iltimos, do'stingiz botga kamida bir marta kirganligiga ishonch hosil qiling va uning to'g'ri ID raqamini yoki kodini yuboring:",
            parse_mode="HTML"
        )
        return TRANSFER_TARGET

    t_id, t_name, t_user, t_code, t_cred = target_user
    if t_id == update.effective_user.id:
        await update.message.reply_text("⚠️ O'zingizga ball o'tkaza olmaysiz! Boshqa do'stingizning ID/kodini kiriting:")
        return TRANSFER_TARGET

    context.user_data["transfer_to_id"] = t_id
    context.user_data["transfer_to_name"] = t_name or t_user or str(t_id)
    
    await update.message.reply_text(
        f"✅ <b>Qabul qiluvchi:</b> <b>{html_escape(context.user_data['transfer_to_name'])}</b>\n\n"
        f"Nechta ball yubormoqchisiz? <i>(Kamida <b>3 ta</b>, ko'pi bilan <b>20 ta</b>)</i>:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return TRANSFER_AMOUNT

async def transfer_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Iltimos, miqdorni faqat raqamlarda yozing (masalan: 5):")
        return TRANSFER_AMOUNT
        
    amount = int(text)
    if amount < 3 or amount > 20:
        await update.message.reply_text("⚠️ O'tkazish miqdori kamida <b>3 ta</b> va ko'pi bilan <b>20 ta</b> bo'lishi kerak. Qaytadan kiriting:", parse_mode="HTML")
        return TRANSFER_AMOUNT

    from_id = update.effective_user.id
    to_id = context.user_data.get("transfer_to_id")
    to_name = context.user_data.get("transfer_to_name", "Do'stingiz")
    
    success, msg = db.transfer_user_credits(from_id, to_id, amount)
    
    if success:
        await update.message.reply_text(
            f"🎉 <b>Muvaffaqiyatli!</b>\n\n"
            f"<b>{html_escape(to_name)}</b> hisobiga <b>+{amount} ta AI so'rovi</b> o'tkazildi! 🚀",
            reply_markup=get_cabinet_keyboard(),
            parse_mode="HTML"
        )
        # Qabul qiluvchiga xushxabar yuboramiz
        try:
            sender_name = update.effective_user.first_name
            await context.bot.send_message(
                chat_id=to_id,
                text=f"🎁 <b>Sizga sovg'a!</b>\n\n<b>{html_escape(sender_name)}</b> sizga <b>+{amount} ta AI so'rovi</b> yubordi! 🎉",
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        await update.message.reply_text(f"❌ Xatolik: {msg}", reply_markup=get_cabinet_keyboard())
        
    context.user_data.clear()
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """To'liq qo'llanma va bot vazifalari."""
    is_admin = (update.effective_user.id == ADMIN_ID)
    text = (
        "📖 <b>PostAssistrobot — To'liq Qo'llanma:</b>\n\n"
        "🔹 <b>1. Yangi post rejalashtirish:</b>\n"
        "• Matn, rasm, video, audio yoki premium stikerli postlarni istalgan sanaga rejalashtirish.\n"
        "• Post ostiga havola tugmalar (URL button) va reaksiyalar qo'shish.\n"
        "• <b>Avto-o'chirish:</b> Reklama postlarini kanalda 12, 24, 48 yoki 72 soatdan so'ng avtomatik o'chirish.\n\n"
        "🔹 <b>2. AI Post Yordamchi (Sun'iy Intellekt):</b>\n"
        "• Istalgan mavzuni erkin yozing yoki rasm yuboring (masalan: <i>'Ertaga 18:50 ga sevgi haqida she'r yoz'</i>).\n"
        "• AI o'zbek tilidagi qisqartmalarni tushunib, post tayyorlaydi va chiqish vaqtini o'zi belgilaydi.\n\n"
        "🔹 <b>3. Ballar, Referal va Ulashish:</b>\n"
        "• Har bir yangi foydalanuvchiga <b>5 ta bepul AI so'rovi</b> beriladi.\n"
        "• Har bir do'stingizni taklif qilganingiz uchun <b>+3 ta bepul AI so'rovi</b> olasiz.\n"
        "• O'zingizdagi ballarni <b>'🎁 Ballarni ulashish'</b> orqali do'stlaringizga o'tkazib berishingiz mumkin (3 tadan 20 tagacha).\n\n"
        "🔹 <b>4. Matn O'girgich (Lotin ⇄ Kirill):</b>\n"
        "• Istalgan matn yoki fayl ostidagi izohlarni bir zumda xatosiz o'girib beradi.\n\n"
        "⚙️ <b>Tezkor buyruqlar:</b>\n"
        "/start — Bosh menyu\n"
        "/newpost — Yangi post\n"
        "/profile — Kabinet va sozlamalar\n"
        "/help — Ushbu yo'riqnoma\n"
        "/cancel — Bekor qilish"
    )
    if is_admin:
        text += "\n\n👑 <b>Admin buyruqlari:</b>\n/admin — Boshqaruv paneli\n/broadcast — Hammaga xabar yuborish\n/stats — Statistika"
    await update.message.reply_text(text, reply_markup=get_main_keyboard(is_admin), parse_mode="HTML")

async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = (update.effective_user.id == ADMIN_ID)
    context.user_data.clear()
    await update.message.reply_text("🚫 Jarayon bekor qilindi.", reply_markup=get_main_keyboard(is_admin), parse_mode="HTML")
    return ConversationHandler.END
