from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import get_main_keyboard
from keyboards.inline import get_referral_share_keyboard, get_subscription_check_keyboard
from utils.helpers import md_escape

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

    db.save_user(user.id, user.username or "", user.full_name or "", referrer_id=referrer_id)
    
    is_sub, unsubs = await check_user_subscribed(context.bot, user.id)
    if not is_sub:
        await update.message.reply_text(
            "⚠️ *Botdan to'liq foydalanish uchun quyidagi homiy kanallarga obuna bo'ling:*",
            reply_markup=get_subscription_check_keyboard(unsubs),
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    is_admin = (user.id == ADMIN_ID)
    await update.message.reply_text(
        f"Salom, *{md_escape(user.first_name)}*! 👋\n\n"
        f"🤖 *PostAssistrobot* — Telegram kanal va guruhlaringizga postlarni rejalashtirib joylovchi aqlli yordamchingiz.\n\n"
        f"Quyidagi menyudan kerakli bo'limni tanlang 👇",
        reply_markup=get_main_keyboard(is_admin),
        parse_mode="Markdown"
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
            text=f"Xush kelibsiz, *{md_escape(user.first_name)}*! Barcha imkoniyatlar siz uchun ochiq.",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="Markdown"
        )
    else:
        await query.answer("❌ Hali barcha kanallarga a'zo bo'lmadingiz!", show_alert=True)
        try:
            await query.edit_message_reply_markup(reply_markup=get_subscription_check_keyboard(unsubs))
        except TelegramError:
            pass

async def user_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.effective_user
    bot_obj = await context.bot.get_me()
    stats = db.get_referral_stats(user.id)
    ref_link = f"https://t.me/{bot_obj.username}?start=ref_{user.id}"
    
    text = (
        f"👤 *Sizning profilingiz:*\n\n"
        f"🆔 ID: `{user.id}`\n"
        f"👥 Taklif qilgan do'stlaringiz: *{stats['referrals_count']} ta*\n\n"
        f"🔗 *Sizning taklif havolangiz:*\n`{ref_link}`"
    )
    await update.message.reply_text(
        text,
        reply_markup=get_referral_share_keyboard(ref_link),
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = (update.effective_user.id == ADMIN_ID)
    text = (
        "📖 *Buyruqlar ro'yxati:*\n\n"
        "/start — Qayta ishga tushirish\n"
        "/newpost — Yangi post rejalashtirish\n"
        "/profile — Profil va taklif havolasi\n"
        "/cancel — Bekor qilish\n"
        "/help — Yordam"
    )
    if is_admin:
        text += "\n\n⚙️ *Admin:*\n/admin — Admin panel\n/broadcast — Xabar yuborish\n/stats — Statistika"
    await update.message.reply_text(text, reply_markup=get_main_keyboard(is_admin), parse_mode="Markdown")

async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = (update.effective_user.id == ADMIN_ID)
    context.user_data.clear()
    await update.message.reply_text("🚫 Jarayon bekor qilindi.", reply_markup=get_main_keyboard(is_admin))
    return ConversationHandler.END
