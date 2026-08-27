from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import get_main_keyboard
from keyboards.inline import get_referral_share_keyboard
from utils.helpers import md_escape

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
    is_admin = (user.id == ADMIN_ID)
    
    await update.message.reply_text(
        f"Salom, *{md_escape(user.first_name)}*! 👋\n\n"
        f"🤖 *PostAssistrobot* — Telegram kanal va guruhlaringizga postlarni rejalashtirib joylovchi aqlli yordamchi.\n\n"
        f"Quyidagi menyudan kerakli bo'limni tanlang 👇",
        reply_markup=get_main_keyboard(is_admin),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

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
