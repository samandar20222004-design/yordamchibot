import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import get_main_keyboard, get_cabinet_keyboard, get_cancel_keyboard
from keyboards.inline import get_referral_share_keyboard, get_subscription_check_keyboard
from utils.helpers import html_escape, get_smart_reply_ad

logger = logging.getLogger(__name__)

TRANSFER_TARGET = 501
TRANSFER_AMOUNT = 502

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
    ad_line = get_smart_reply_ad(user.id)
    await update.message.reply_text(
        f"Salom, <b>{html_escape(user.first_name)}</b>! 👋\n\n"
        f"🤖 <b>PostAssistrobot</b> — Telegram kanallaringizga postlarni rejalashtirib joylovchi aqlli yordamchingiz.\n\n"
        f"Quyidagi menyudan kerakli bo'limni tanlang 👇{ad_line}",
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
    context.user_data.clear()
    user = update.effective_user
    is_admin = (user.id == ADMIN_ID)
    stats = db.get_referral_stats(user.id)
    channels = db.get_user_channels(user.id)
    user_code = db.get_user_code(user.id)
    
    credits_text = "♾ Cheksiz (Super Admin)" if is_admin else f"<b>{stats['ai_credits']} ta</b>"
    
    if is_admin:
        ad_free_text = "♾ Cheksiz (Super Admin)"
    else:
        status_badge = "🟢 Yoqilgan" if stats.get('ad_free_active', True) else "🔴 O'chirilgan"
        ad_free_text = f"<b>{stats['ad_free_posts']} ta</b> ({status_badge})"
        
    streak_val = stats.get('streak', 0)
    streak_text = f"🔥 <b>{streak_val}/7 kun</b>"
    ad_line = get_smart_reply_ad(user.id)
    
    text = (
        f"👤 <b>Shaxsiy Kabinet:</b>\n\n"
        f"🆔 Sizning ID: <code>{user.id}</code>\n"
        f"🔑 Maxsus kodingiz: <code>{user_code}</code>\n"
        f"💎 Mavjud AI so'rovlar soni: {credits_text}\n"
        f"🔥 Ketma-ket kunlik seriya: {streak_text}\n"
        f"✨ Reklamasiz postlar litsenziyasi: {ad_free_text}\n"
        f"📢 Ulangan kanallar: <b>{len(channels)} ta</b>\n"
        f"👥 Taklif qilgan do'stlaringiz: <b>{stats['referrals_count']} ta</b>\n\n"
        f"Quyidagi bo'limlardan birini tanlang 👇{ad_line}"
    )
    await update.message.reply_text(text, reply_markup=get_cabinet_keyboard(), parse_mode="HTML")

async def daily_bonus_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin = (user.id == ADMIN_ID)
    
    if is_admin:
        await update.message.reply_text("👑 <b>Siz Super Adminsiz</b> — hisobingizda cheksiz so'rov mavjud!", parse_mode="HTML")
        return
        
    res = db.claim_daily_streak_bonus(user.id)
    if res.get("success"):
        streak = res["streak"]
        bonus = res["bonus_amount"]
        credits = res["credits"]
        
        progress_bar = "".join(["🟩" if i <= streak else "⬜" for i in range(1, 8)])
        reset_notice = "\n⚠️ <i>Orada kun o'tkazib yuborilgani sababli seriya 1-kundan qayta boshlandi.</i>\n" if res.get("is_reset") else ""
        
        text = (
            f"🎉 <b>Kunlik bonus qabul qilindi!</b>\n\n"
            f"{reset_notice}"
            f"🔥 Sizning ketma-ketlik seriyangiz: <b>{streak}/7 kun</b>\n"
            f"{progress_bar}\n\n"
            f"🎁 Bugungi sovg'a: <b>+{bonus} ta AI so'rovi</b>\n"
            f"💎 Jami balansingiz: <b>{credits} ta</b>\n\n"
            f"📌 <i>Eslatma: Ertaga ham botga kiring va 7-kunda <b>+4 ta super-bonus</b> oling!</i>"
        )
        await update.message.reply_text(text, reply_markup=get_cabinet_keyboard(), parse_mode="HTML")
    else:
        await update.message.reply_text(
            f"ℹ️ {res.get('msg')}\n\n💎 Sizdagi jami ballar: <b>{res.get('credits', 0)} ta</b>",
            reply_markup=get_cabinet_keyboard(),
            parse_mode="HTML"
        )

async def buy_ad_free_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin = (user.id == ADMIN_ID)
    
    if is_admin:
        await update.message.reply_text("👑 Siz Super Adminsiz — barcha postlaringiz doim reklamasiz chiqadi!", parse_mode="HTML")
        return
        
    stats = db.get_referral_stats(user.id)
    posts_count = stats['ad_free_posts']
    is_active = stats.get('ad_free_active', True)
    
    status_label = "🟢 Yoqilgan (Ishlatilmoqda)" if is_active else "🔴 O'chirilgan (Saqlanmoqda)"
    toggle_btn_text = "🔴 O'chirish (Tejash)" if is_active else "🟢 Yoqish (Ishlatish)"
    
    keyboard = [
        [InlineKeyboardButton(f"Holat: {toggle_btn_text}", callback_data="adfree_toggle")],
        [InlineKeyboardButton("➕ 5 ta post xarid qilish (1 ball)", callback_data="adfree_confirm")],
    ]
    if posts_count >= 5:
        keyboard.append([InlineKeyboardButton("🔄 Ballga qaytarish (5 post = 1 ball)", callback_data="adfree_refund")])
    keyboard.append([InlineKeyboardButton("❌ Yopish", callback_data="adfree_close")])
    
    await update.message.reply_text(
        f"💎 <b>Reklamasiz Toza Postlar Boshqaruvi:</b>\n\n"
        f"📊 Sizdagi mavjud toza postlar soni: <b>{posts_count} ta</b>\n"
        f"⚙️ Hozirgi holat: <b>{status_label}</b>\n\n"
        f"<i>Kerakli amalni tanlang:</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def ad_free_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    
    if data == "adfree_close":
        await query.message.delete()
        return

    if data == "adfree_toggle":
        success, new_status = db.toggle_ad_free_status(user_id)
        stats = db.get_referral_stats(user_id)
        posts_count = stats['ad_free_posts']
        status_label = "🟢 Yoqilgan (Ishlatilmoqda)" if new_status else "🔴 O'chirilgan (Saqlanmoqda)"
        toggle_btn_text = "🔴 O'chirish (Tejash)" if new_status else "🟢 Yoqish (Ishlatish)"
        
        keyboard = [
            [InlineKeyboardButton(f"Holat: {toggle_btn_text}", callback_data="adfree_toggle")],
            [InlineKeyboardButton("➕ 5 ta post xarid qilish (1 ball)", callback_data="adfree_confirm")],
        ]
        if posts_count >= 5:
            keyboard.append([InlineKeyboardButton("🔄 Ballga qaytarish (5 post = 1 ball)", callback_data="adfree_refund")])
        keyboard.append([InlineKeyboardButton("❌ Yopish", callback_data="adfree_close")])

        await query.edit_message_text(
            f"💎 <b>Reklamasiz Toza Postlar Boshqaruvi:</b>\n\n"
            f"📊 Sizdagi mavjud toza postlar soni: <b>{posts_count} ta</b>\n"
            f"⚙️ Hozirgi holat: <b>{status_label}</b>\n\n"
            f"<i>Holat muvaffaqiyatli yangilandi!</i>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        return

    if data == "adfree_confirm":
        success, msg = db.buy_ad_free_posts(user_id)
        await query.edit_message_text(msg, parse_mode="HTML")
        return

    if data == "adfree_refund":
        success, msg = db.refund_ad_free_posts(user_id)
        await query.edit_message_text(msg, parse_mode="HTML")
        return

async def user_invite_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def start_transfer_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    my_credits = db.get_user_credits(user_id)
    
    if my_credits < 3 and user_id != ADMIN_ID:
        await update.message.reply_text(
            f"⚠️ <b>Hisobingizda yetarli ball yo'q!</b>\n\n"
            f"Ball o'tkazish uchun kamida <b>3 ta ball</b> kerak. Sizda esa: <b>{my_credits} ta</b>.\n"
            f"Kunlik bonus yoki taklif havolasi orqali ball to'plashingiz mumkin!",
            reply_markup=get_cabinet_keyboard(),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🔄 <b>Ballarni (AI so'rovlarni) ulashish:</b>\n\n"
        "Do'stingizning <b>ID raqamini</b>, <b>Telegram usernamesini (@...)</b> yoki botdagi <b>maxsus kodini</b> yuboring:\n"
        "<i>(Eslatma: Faqat botdan ro'yxatdan o'tgan faol foydalanuvchilarga ball o'tkazish mumkin)</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return TRANSFER_TARGET

async def transfer_target_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_input = update.message.text
    target_user = db.find_user_by_target(target_input)
    
    # Ro'yxatdan o'tmagan foydalanuvchini qat'iy tekshirish
    if not target_user:
        await update.message.reply_text(
            "❌ <b>Foydalanuvchi topilmadi!</b>\n\n"
            "Ushbu foydalanuvchi hali botdan ro'yxatdan o'tmagan yoki ma'lumot xato kiritildi.\n"
            "Do'stingiz avval botga kirib <b>/start</b> bosishi kerak.\n\n"
            "Qaytadan to'g'ri ID raqam yoki kodni kiriting:",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return TRANSFER_TARGET

    t_id, t_name, t_user, t_code, t_cred = target_user
    if t_id == update.effective_user.id:
        await update.message.reply_text("⚠️ O'zingizga ball o'tkaza olmaysiz! Boshqa do'stingiz ma'lumotini kiriting:")
        return TRANSFER_TARGET

    context.user_data["transfer_to_id"] = t_id
    context.user_data["transfer_to_name"] = t_name or t_user or str(t_id)
    
    await update.message.reply_text(
        f"✅ <b>Qabul qiluvchi:</b> <b>{html_escape(context.user_data['transfer_to_name'])}</b> (ID: <code>{t_id}</code>)\n\n"
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
        await update.message.reply_text(f"❌ <b>Xatolik:</b> {msg}", reply_markup=get_cabinet_keyboard(), parse_mode="HTML")
        
    context.user_data.clear()
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = (update.effective_user.id == ADMIN_ID)
    ad_line = get_smart_reply_ad(update.effective_user.id)
    text = (
        "📖 <b>PostAssistrobot — To'liq Qo'llanma:</b>\n\n"
        "🔹 <b>1. Yangi post rejalashtirish:</b>\n"
        "• Matn, rasm, video yoki audio postlarni istalgan sanaga rejalashtirish.\n"
        "• Havola tugmalar (URL button), reaksiyalar va avto-o'chirish (12, 24, 48, 72 soat).\n"
        "• <i>Litsenziya bo'lsa reklamasiz toza post chiqadi!</i>\n\n"
        "🔹 <b>2. AI Post Yordamchi:</b>\n"
        "• Matn yoki rasm yuborib, professional post va she'rlar tayyorlash.\n\n"
        "🔹 <b>3. Ballar va Kunlik Seriya (Streak):</b>\n"
        "• Har kuni botga kiring va <b>'🎁 Kunlik bonus'</b> tugmasini bosing.\n"
        "• 1-kun (+1), 2-kun (+1), 3-kun (+2), ..., 7-kun (+4 ball) olasiz!\n\n"
        "🔹 <b>4. Matn O'girgich:</b>\n"
        "• Lotin ⇄ Kirill alifbolariga tezkor o'girish.\n\n"
        "⚙️ <b>Tezkor buyruqlar:</b>\n"
        "/start — Bosh menyu\n"
        "/newpost — Yangi post\n"
        "/profile — Kabinet\n"
        "/help — Qo'llanma\n"
        "/cancel — Bekor qilish"
    )
    if is_admin:
        text += "\n\n👑 <b>Admin buyruqlari:</b>\n/admin — Boshqaruv paneli\n/broadcast — Xabar yuborish\n/stats — Statistika"
    await update.message.reply_text(f"{text}{ad_line}", reply_markup=get_main_keyboard(is_admin), parse_mode="HTML")

async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = (update.effective_user.id == ADMIN_ID)
    context.user_data.clear()
    await update.message.reply_text("🚫 Jarayon bekor qilindi.", reply_markup=get_main_keyboard(is_admin), parse_mode="HTML")
    return ConversationHandler.END
