import logging
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import get_cancel_keyboard, get_main_keyboard
from keyboards.inline import render_channels_list
from utils.helpers import html_escape

logger = logging.getLogger(__name__)

ADD_CHANNEL = 301


async def channels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    channels = await db.run_db(db.get_user_channels, user_id)

    if not channels:
        await update.message.reply_text(
            "📢 <b>Sizda hali ulangan kanallar mavjud emas.</b>\n\n"
            "Kanal ulash uchun botni kanalingizga administrator qiling va <b>➕ Kanal/Guruh qo'shish</b> tugmasini bosing.",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"📢 <b>Sizning ulangan kanallaringiz ({len(channels)} ta):</b>\n\n"
        "Kanalni o'chirish uchun '❌ O'chirish' tugmasini bosing 👇",
        reply_markup=render_channels_list(channels),
        parse_mode="HTML"
    )
    return ConversationHandler.END


async def start_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_obj = await context.bot.get_me()
    await update.message.reply_text(
        f"➕ <b>Yangi kanal yoki guruh ulash:</b>\n\n"
        f"1. Botni (<code>@{bot_obj.username}</code>) kanalingizga yoki guruhingizga <b>Administrator</b> qilib qo'shing (xabar yuborish ruxsati bilan).\n"
        f"2. So'ngra o'sha kanaldan istalgan bir xabarni menga <b>Forward (Uzatish)</b> qiling yoki kanal ID raqamini (masalan: <code>-1001234567890</code>) yozib yuboring:\n\n"
        f"<i>Bekor qilish uchun '🔙 Asosiy menyu' tugmasini bosing.</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return ADD_CHANNEL


async def _verify_channel_permissions(bot, chat_id, user_id: int, is_admin_user: bool):
    """Bot va foydalanuvchi huquqlarini fail-closed tekshiradi.

    Qaytadi: (ok, error_html, real_channel_id, title)
    """
    try:
        chat = await bot.get_chat(chat_id)
    except TelegramError as e:
        logger.warning("Kanal topilmadi (%s): %s", chat_id, e)
        return False, "❌ Kanal yoki guruh topilmadi. Forward qiling yoki to'g'ri ID yuboring.", None, None

    real_id = str(chat.id)
    title = chat.title or "Telegram Kanal"

    try:
        bot_member = await bot.get_chat_member(chat.id, bot.id)
    except TelegramError as e:
        logger.warning("Bot a'zoligini tekshirib bo'lmadi (%s): %s", real_id, e)
        return False, (
            "⚠️ <b>Bot ushbu kanalda emas yoki huquqlarni tekshirib bo'lmadi.</b>\n\n"
            "Avval botni administrator qiling (xabar yuborish ruxsati bilan)."
        ), None, None

    if bot_member.status not in ("administrator", "creator"):
        return False, (
            "⚠️ <b>Bot ushbu kanalda administrator emas!</b>\n\n"
            "Iltimos, avval botga kanalda xabar yuborish ruxsatini bering."
        ), None, None

    if chat.type == "channel" and bot_member.status == "administrator":
        if not getattr(bot_member, "can_post_messages", False):
            return False, (
                "⚠️ <b>Botga kanalda xabar yuborish ruxsati berilmagan.</b>\n\n"
                "Administrator sozlamalarida <b>Post Messages</b> huquqini yoqing."
            ), None, None

    if not is_admin_user:
        try:
            user_member = await bot.get_chat_member(chat.id, user_id)
        except TelegramError as e:
            logger.warning("Foydalanuvchi huquqini tekshirib bo'lmadi (%s / %s): %s", real_id, user_id, e)
            return False, (
                "⚠️ <b>Sizning ushbu kanaldagi huquqingizni tekshirib bo'lmadi.</b>\n\n"
                "Faqat kanal/guruh administratori botga kanal ulashi mumkin."
            ), None, None
        if user_member.status not in ("administrator", "creator"):
            return False, (
                "🚫 <b>Ruxsat yo'q.</b>\n\n"
                "Faqat kanal yoki guruh <b>administratori</b> ushbu botga kanal ulashi mumkin."
            ), None, None

    return True, "", real_id, title


async def channel_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)

    raw_target = None
    if msg.forward_from_chat:
        raw_target = msg.forward_from_chat.id
    elif msg.text:
        text = msg.text.strip()
        if text.lstrip("-").isdigit() or text.startswith("@"):
            raw_target = int(text) if text.lstrip("-").isdigit() else text
        else:
            await update.message.reply_text(
                "❌ Kanal ma'lumotlari aniqlanmadi. Iltimos, kanaldan xabarni <b>forward</b> qiling "
                "yoki ID ni yuboring (masalan: <code>-1001234567890</code>).",
                parse_mode="HTML",
            )
            return ADD_CHANNEL
    else:
        await update.message.reply_text("❌ Kanal ma'lumotlari aniqlanmadi. Iltimos, kanaldan xabarni forward qiling:")
        return ADD_CHANNEL

    ok, err, channel_id, channel_title = await _verify_channel_permissions(
        context.bot, raw_target, user_id, is_admin
    )
    if not ok:
        await update.message.reply_text(err, parse_mode="HTML")
        return ADD_CHANNEL

    success, reason = await db.run_db(db.save_channel, user_id, channel_id, channel_title, is_admin)
    if success:
        await update.message.reply_text(
            f"✅ <b>Kanal muvaffaqiyatli ulandi!</b>\n\n📢 Nomi: <b>{html_escape(channel_title)}</b>\n🆔 ID: <code>{channel_id}</code>",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML"
        )
    elif reason == "taken":
        await update.message.reply_text(
            "🚫 <b>Bu kanal allaqachon boshqa foydalanuvchiga ulangan.</b>\n\n"
            "O'g'irlab bo'lmaydi. Agar bu sizning kanalingiz bo'lsa, avval egasi botdan o'chirishi kerak.",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text("❌ Kanalni saqlashda xatolik yuz berdi.", reply_markup=get_main_keyboard(is_admin))

    return ConversationHandler.END


async def remove_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    channel_id = query.data.split(":")[1]
    user_id = query.from_user.id
    is_admin = (user_id == ADMIN_ID)

    removed = await db.run_db(db.remove_channel, user_id, channel_id, is_admin)
    if removed:
        await query.edit_message_text("✅ Kanal muvaffaqiyatli o'chirildi.")
    else:
        await query.edit_message_text("❌ Kanal topilmadi yoki sizga tegishli emas.")


async def on_bot_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result:
        return
    chat = result.chat
    new_status = result.new_chat_member.status
    user_id = result.from_user.id

    if chat.type not in ("channel", "supergroup", "group"):
        return

    if new_status in ("administrator", "creator"):
        is_admin = (user_id == ADMIN_ID)
        success, reason = await db.run_db(
            db.save_channel, user_id, str(chat.id), chat.title or "Telegram Kanal", is_admin
        )
        if success:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"✅ <b>Kanal avtomatik ulandi:</b> {html_escape(chat.title or 'Kanal')}\n"
                        f"🆔 <code>{chat.id}</code>"
                    ),
                    parse_mode="HTML",
                )
            except TelegramError:
                pass
        elif reason == "taken":
            logger.info("Kanal %s boshqa foydalanuvchiga tegishli — avto-ulash o'tkazib yuborildi", chat.id)
        return

    if new_status in ("left", "kicked", "member", "restricted"):
        await db.run_db(db.deactivate_channel_by_id, str(chat.id))
