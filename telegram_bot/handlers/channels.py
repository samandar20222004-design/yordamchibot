import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import get_cancel_keyboard, get_main_keyboard, get_tone_keyboard, TONE_LABELS
from keyboards.inline import render_channels_list
from utils.helpers import html_escape

logger = logging.getLogger(__name__)

ADD_CHANNEL = 301
SET_TONE = 302

# Tarif limiti (FREE vs PRO) tugaganda ko'rsatiladigan xabar va PRO tugmasi.
CHANNEL_LIMIT_MSG = (
    "🚫 <b>Kanal limiti tugadi!</b>\n\n"
    "Sizda hozir <b>{current}/{max}</b> ta kanal ulangan.\n"
    "Free tarifida maksimal <b>{max}</b> ta kanal ulash mumkin.\n\n"
    "⭐️ Ushbu imkoniyatdan cheksiz foydalanish uchun PRO tarifiga o'ting."
)

PRO_UPGRADE_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("⭐️ PRO tarifga o'tish", callback_data="sub_open")],
])


def _empty_channels_keyboard() -> InlineKeyboardMarkup:
    """Kanal yo'q paytda ko'rsatiladigan tugmalar (qo'shish + yopish)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Kanal/Guruh ulash", callback_data="add_channel_start")],
        [InlineKeyboardButton("❌ Yopish", callback_data="close_msg")],
    ])


async def channels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    channels = await db.run_db(db.get_user_channels_with_tone, user_id)

    if not channels:
        await update.message.reply_text(
            "📢 <b>Sizda hali ulangan kanallar mavjud emas.</b>\n\n"
            "Kanal ulash uchun quyidagi tugmani bosing 👇\n\n"
            "<i>Botni kanalingizga administrator qilib (xabar yuborish ruxsati bilan) "
            "qo'shish kerak bo'ladi.</i>",
            reply_markup=_empty_channels_keyboard(),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"📢 <b>Sizning ulangan kanallaringiz ({len(channels)} ta):</b>\n\n"
        "Kanalni o'chirish uchun '❌ O'chirish' tugmasini bosing yoki yangi kanal ulang 👇",
        reply_markup=render_channels_list(channels),
        parse_mode="HTML"
    )
    return ConversationHandler.END


async def _send_add_channel_instructions(bot, chat_id: int):
    bot_obj = await bot.get_me()
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "➕ <b>Yangi kanal yoki guruh ulash:</b>\n\n"
            f"1. Botni (<code>@{bot_obj.username}</code>) kanalingizga yoki guruhingizga "
            "<b>Administrator</b> qilib qo'shing (xabar yuborish ruxsati bilan).\n"
            "2. So'ngra o'sha kanaldan istalgan bir xabarni menga <b>Forward (Uzatish)</b> "
            "qiling yoki kanal ID raqamini (masalan: <code>-1001234567890</code>) yozib yuboring.\n\n"
            "<i>Bekor qilish uchun '🔙 Asosiy menyu' tugmasini bosing.</i>"
        ),
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML",
    )


async def start_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_add_channel_instructions(context.bot, update.effective_chat.id)
    return ADD_CHANNEL


async def add_channel_inline_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline tugma orqali kanal ulash oqimini boshlash (ro'yxat/bo'sh ekran)."""
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _send_add_channel_instructions(context.bot, query.from_user.id)
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
    is_admin = (user_id in ADMIN_IDS_SET)

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

    # Tarif bo'yicha kanal limiti (FREE vs PRO) — yangi kanal qo'shishdan
    # oldin tekshiriladi. Limit to'lgan bo'lsa xushmuomala xabar va PRO
    # tarifga o'tish tugmasi ko'rsatiladi.
    if not is_admin:
        can_add, current, max_ch = await db.run_db(db.check_channel_limit, user_id)
        if not can_add:
            await update.message.reply_text(
                CHANNEL_LIMIT_MSG.format(current=current, max=max_ch),
                reply_markup=PRO_UPGRADE_KEYBOARD,
                parse_mode="HTML",
            )
            return ADD_CHANNEL

    success, reason = await db.run_db(db.save_channel, user_id, channel_id, channel_title, is_admin)
    if success:
        await update.message.reply_text(
            f"✅ <b>Kanal muvaffaqiyatli ulandi!</b>\n\n📢 Nomi: <b>{html_escape(channel_title)}</b>\n🆔 ID: <code>{channel_id}</code>",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML"
        )

        # Referal PRO mukofotini tekshirish (taklif qilgan foydalanuvchiga)
        referrer_row = await db.run_db(
            lambda cur: cur.execute(
                "SELECT referrer_id FROM users WHERE user_id = %s", (user_id,)
            ) or cur.fetchone()
        )
        if referrer_row and referrer_row[0]:
            referrer_id = referrer_row[0]
            pro_granted = await db.run_db(db.check_and_grant_referral_pro, referrer_id)
            if pro_granted:
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=(
                            "🎉 <b>Tabriklaymiz!</b>\n\n"
                            "3 ta do'stingiz kanal uladi va sizga <b>30 kunlik PRO tarif</b> berildi!\n\n"
                            "Barcha PRO imkoniyatlardan foydalaning: Cheksiz kanallar, AI va analitika."
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
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
    # Darhol javob — DB so'rovlaridan oldin, tugma muzlab qolmasligi uchun.
    try:
        await query.answer()
    except Exception:
        pass

    channel_id = query.data.split(":")[1]
    user_id = query.from_user.id
    is_admin = (user_id in ADMIN_IDS_SET)

    removed = await db.run_db(db.remove_channel, user_id, channel_id, is_admin)
    channels = await db.run_db(db.get_user_channels, user_id)
    if not removed:
        try:
            await query.message.reply_text(
                "❌ Kanal topilmadi yoki sizga tegishli emas.",
                parse_mode="HTML",
            )
        except Exception:
            pass

    # Ro'yxatni qayta chizamiz — qolgan kanallar va tugmalar ko'rinib tursin
    try:
        if channels:
            await query.edit_message_text(
                f"📢 <b>Sizning ulangan kanallaringiz ({len(channels)} ta):</b>\n\n"
                "Kanalni o'chirish uchun '❌ O'chirish' tugmasini bosing yoki yangi kanal ulang 👇",
                reply_markup=render_channels_list(channels),
                parse_mode="HTML",
            )
        else:
            await query.edit_message_text(
                "📢 <b>Barcha kanallar o'chirildi.</b>\n\nYangi kanal ulash uchun quyidagi tugmani bosing 👇",
                reply_markup=_empty_channels_keyboard(),
                parse_mode="HTML",
            )
    except TelegramError:
        pass


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
        is_admin = (user_id in ADMIN_IDS_SET)
        # Avtomatik ulashda ham tarif limiti tekshiriladi — free foydalanuvchi
        # maksimal kanal sonidan oshsa, kanal ulab bo'lmaydi.
        if not is_admin:
            can_add, current, max_ch = await db.run_db(db.check_channel_limit, user_id)
            if not can_add:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=CHANNEL_LIMIT_MSG.format(current=current, max=max_ch),
                        reply_markup=PRO_UPGRADE_KEYBOARD,
                        parse_mode="HTML",
                    )
                except TelegramError:
                    pass
                return
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


# ============================================================
# CHANNEL TONE OF VOICE
# ============================================================

async def tone_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline 'Uslub' tugmasi bosilganda — uslub tanlash menyusini ko'rsatadi."""
    query = update.callback_query
    await query.answer()
    channel_id = query.data.split(":", 1)[1] if ":" in query.data else ""
    if not channel_id:
        return ConversationHandler.END

    context.user_data["tone_channel_id"] = channel_id
    current_tone = await db.run_db(db.get_channel_tone, channel_id)
    current_label = TONE_LABELS.get(current_tone, TONE_LABELS["friendly"])

    await query.message.reply_text(
        f"🎭 <b>Kanal uslubini tanlang:</b>\n\n"
        f"Joriy uslub: <b>{current_label}</b>\n\n"
        f"Uslub postlarning ohangi va uslubini belgilaydi:",
        reply_markup=get_tone_keyboard(),
        parse_mode="HTML",
    )
    return SET_TONE


async def tone_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi uslub tugmasini bosganda."""
    text = update.message.text.strip()
    channel_id = context.user_data.get("tone_channel_id", "")
    is_admin = update.effective_user.id in ADMIN_IDS_SET

    # Ters mapping: label -> tone key
    label_to_tone = {v: k for k, v in TONE_LABELS.items()}

    if text in ("🔙 Asosiy menyu", "🔙 Orqaga"):
        await update.message.reply_text(
            "✅ Uslub o'zgartirish bekor qilindi.",
            reply_markup=get_main_keyboard(is_admin),
        )
        return ConversationHandler.END

    tone = label_to_tone.get(text)
    if not tone:
        await update.message.reply_text(
            "❌ Noto'g'ri uslub. Iltimos, tugmalardan birini bosing.",
            reply_markup=get_tone_keyboard(),
        )
        return SET_TONE

    success = await db.run_db(db.set_channel_tone, channel_id, tone)
    if success:
        await update.message.reply_text(
            f"✅ <b>Kanal uslubi yangilandi!</b>\n\n"
            f"🎭 Yangi uslub: <b>{TONE_LABELS[tone]}</b>\n\n"
            f"Endi AI postlarni shu uslubda tayyorlaydi.",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            "❌ Uslubni saqlashda xatolik. Qaytadan urinib ko'ring.",
            reply_markup=get_main_keyboard(is_admin),
        )

    context.user_data.pop("tone_channel_id", None)
    return ConversationHandler.END
