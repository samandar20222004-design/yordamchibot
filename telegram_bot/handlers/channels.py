import logging
import re
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

# Kanal manbasini aniqlash: foydalanuvchi forward, @username, raqamli ID
# yoki t.me/havola yuborishi mumkin — oqim shu to'rt formatning birini
# qabul qiladi (avval faqat forward/ID/@username ishlagan).
_T_ME_LINK_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?t\.me/([A-Za-z][A-Za-z0-9_]{3,31})/?$", re.IGNORECASE
)
_T_ME_INVITE_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?t\.me/(?:\+|joinchat/)", re.IGNORECASE
)


def parse_channel_target(text: str):
    """Matndan kanal manbasini ajratadi: (target, xato_html|None).

    Qaytadi:
      * ``(-1001234567890, None)`` — raqamli ID;
      * ``("@kanal", None)`` — username (t.me/kanal ham shunga aylantiriladi);
      * ``(None, xato)`` — tushunarsiz yoki yopiq (invite) havola.
    """
    text = (text or "").strip()
    if not text:
        return None, (
            "❌ Bo'sh xabar qabul qilindi. Kanalni <b>forward</b> qiling, "
            "<code>@username</code>, ID yoki <code>t.me/kanal</code> havolasini yuboring."
        )
    if _T_ME_INVITE_RE.match(text):
        return None, (
            "🔒 <b>Yopiq kanal (invite) havolasi orqali ulab bo'lmaydi.</b>\n\n"
            "Bot kanalda administrator bo'lgani uchun <code>@username</code> "
            "yoki kanaldan istalgan xabarni <b>forward</b> qiling — shunda "
            "kanalni aniqlaymiz."
        )
    m = _T_ME_LINK_RE.match(text)
    if m:
        return f"@{m.group(1)}", None
    if text.startswith("@") and len(text) > 1:
        return text, None
    if text.lstrip("-").isdigit():
        return int(text), None
    return None, None  # noma'lum format — chaqiruvchi o'zi yo'naltiradi


def _retry_verify_keyboard() -> InlineKeyboardMarkup:
    """Tekshiruvdan o'tmagan kanal uchun 'qayta urinish' tugmasi.

    Foydalanuvchi botni admin qilgach xabarni qayta forward qilmasdan,
    shu tugmani bosish bilan tekshiruvni yangilaydi.
    """
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🔁 Botni admin qildim — qayta tekshirish",
            callback_data="add_channel_retry",
        ),
    ]])

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
            "2. So'ngra kanal manbasini yuboring — to'rt formatning birida:\n"
            "   • kanaldan istalgan xabarni <b>Forward (Uzatish)</b>;\n"
            "   • <code>@kanal_nomi</code>;\n"
            "   • <code>t.me/kanal_nomi</code> yoki <code>https://t.me/kanal_nomi</code>;\n"
            "   • kanal ID raqami (masalan: <code>-1001234567890</code>).\n\n"
            "<i>Bekor qilish uchun '🔙 Asosiy menyu' tugmasini bosing.</i>"
        ),
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML",
    )


async def start_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Yangi oqim: oldingi urinishdan qolgan "kutilayotgan kanal"ni tozalaymiz,
    # shunda 🔁 tugma eskirgan manzilni qayta tekshirmaydi.
    context.user_data.pop("add_channel_pending", None)
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
    context.user_data.pop("add_channel_pending", None)
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


def _extract_forward_chat_id(msg):
    """Forward qilingan xabardan manba kanal/chat ID sini xavfsiz ajratadi.

    Bot API 7.0+ / python-telegram-bot 20+ da ``Message.forward_from_chat``
    olib tashlangan (o'rniga ``forward_origin`` keldi) — eski atributga
    to'g'ridan-to'g'ri murojaat qilish ``AttributeError`` bilan tugaydi va
    butun ``ADD_CHANNEL`` holati "qotib" qoladi (foydalanuvchiga javob
    yubormay handler ichida yiqiladi). Shu sababli ikkala API'ni ham
    ``getattr`` bilan, xatosiz tekshiramiz.
    """
    origin = getattr(msg, "forward_origin", None)
    if origin is not None:
        chat = getattr(origin, "chat", None)
        if chat is not None:
            return chat.id
        sender_chat = getattr(origin, "sender_chat", None)
        if sender_chat is not None:
            return sender_chat.id
    # Orqaga moslik: juda eski python-telegram-bot versiyalari uchun.
    legacy_chat = getattr(msg, "forward_from_chat", None)
    if legacy_chat is not None:
        return legacy_chat.id
    return None


async def channel_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal manba xabari: forward, @username, t.me/havola yoki ID.

    HARDENING: butun tanasi try/except bilan o'ralgan — kutilmagan xatolik
    (masalan, Telegram API'dagi kelajakdagi o'zgarish) botni "qotirmasligi",
    balki foydalanuvchiga tushunarli xabar bilan qayta urinishni taklif
    qilishi kerak (jim qolib ketish — eng yomon UX).
    """
    msg = update.effective_message
    try:
        raw_target = None
        forward_chat_id = _extract_forward_chat_id(msg)
        if forward_chat_id is not None:
            raw_target = forward_chat_id
        elif msg.text:
            target, err = parse_channel_target(msg.text)
            if err:
                await msg.reply_text(
                    err, reply_markup=get_cancel_keyboard(), parse_mode="HTML",
                )
                return ADD_CHANNEL
            if target is None:
                await msg.reply_text(
                    "❌ Kanal ma'lumotlari aniqlanmadi. Iltimos, kanaldan xabarni "
                    "<b>forward</b> qiling yoki <code>@username</code>, "
                    "<code>t.me/kanal_nomi</code> havolasi, ID raqamini "
                    "(masalan: <code>-1001234567890</code>) yuboring.",
                    reply_markup=get_cancel_keyboard(),
                    parse_mode="HTML",
                )
                return ADD_CHANNEL
            raw_target = target
        else:
            await msg.reply_text(
                "❌ Kanal ma'lumotlari aniqlanmadi. Iltimos, kanaldan xabarni forward qiling:",
                reply_markup=get_cancel_keyboard(),
            )
            return ADD_CHANNEL

        return await _link_channel(update, context, raw_target)
    except Exception:
        logger.exception("channel_received: kutilmagan xatolik — foydalanuvchi qayta urinishga yo'naltirilmoqda")
        try:
            await msg.reply_text(
                "⚠️ <b>Kutilmagan xatolik yuz berdi.</b>\n\n"
                "Iltimos, kanalni qaytadan forward qiling yoki "
                "<code>@username</code> / <code>t.me/kanal</code> havolasini yuboring.",
                reply_markup=get_cancel_keyboard(),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return ADD_CHANNEL


async def add_channel_retry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🔁 «Botni admin qildim — qayta tekshirish» tugmasi.

    Foydalanuvchi botni kanalda administrator qilgach, xabarni qaytadan
    forward qilmasdan shu tugma bilan tekshiruvni yangilaydi.
    """
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass
    raw_target = context.user_data.get("add_channel_pending")
    if raw_target is None:
        # Kutilayotgan manzil yo'q (masalan, sessiya muddati tugagan) —
        # oqimni boshidan so'raymiz.
        await _send_add_channel_instructions(context.bot, query.from_user.id)
        return ADD_CHANNEL
    return await _link_channel(update, context, raw_target)


async def _link_channel(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_target):
    """Umumiy ulash oqimi: tekshirish → limit → saqlash → natija ro'yxati.

    ``channel_received`` (yangi manba) va ``add_channel_retry`` (qayta
    tekshirish) shu bitta funksiyadan foydalanadi — ikkala yo'l bir xil
    xatolik/omad xabarlarini beradi.
    """
    msg = update.effective_message
    user_id = update.effective_user.id
    is_admin = (user_id in ADMIN_IDS_SET)

    ok, err, channel_id, channel_title = await _verify_channel_permissions(
        context.bot, raw_target, user_id, is_admin
    )
    if not ok:
        # Manzilni saqlab qo'yamiz: botga ruxsat berilgach 🔁 tugmasi bilan
        # tekshirish mumkin (xabarni qayta yuborish shart emas).
        context.user_data["add_channel_pending"] = raw_target
        await msg.reply_text(
            f"{err}\n\nBotga ruxsat berganingizdan so'ng quyidagi tugmani bosing "
            "yoki kanal manbasini qayta yuboring 👇",
            reply_markup=_retry_verify_keyboard(),
            parse_mode="HTML",
        )
        return ADD_CHANNEL

    # Tarif bo'yicha kanal limiti (FREE vs PRO) — yangi kanal qo'shishdan
    # oldin tekshiriladi. Limit to'lgan bo'lsa xushmuomala xabar va PRO
    # tarifga o'tish tugmasi ko'rsatiladi.
    if not is_admin:
        can_add, current, max_ch = await db.run_db(db.check_channel_limit, user_id)
        if not can_add:
            await msg.reply_text(
                CHANNEL_LIMIT_MSG.format(current=current, max=max_ch),
                reply_markup=PRO_UPGRADE_KEYBOARD,
                parse_mode="HTML",
            )
            return ADD_CHANNEL

    success, reason = await db.run_db(db.save_channel, user_id, channel_id, channel_title, is_admin)
    if success:
        context.user_data.pop("add_channel_pending", None)
        # Omad: darhol yangilangan kanal ro'yxatini ko'rsatamiz — foydalanuvchi
        # "ulandi, endi qayerda?" deb qidir maydi; ro'yxatdan qo'shimcha
        # kanal ulash yoki uslub/o'chirish ham mumkin.
        channels = await db.run_db(db.get_user_channels, user_id)
        list_markup = render_channels_list(channels) if channels else None
        # HARDENING: python-telegram-bot'ning Message.reply_text() metodi
        # "inline_keyboard" kalit-argumentini QABUL QILMAYDI (faqat bitta
        # reply_markup bo'ladi — u reply yoki inline klaviatura). Avval shu
        # yerda noto'g'ri kwarg TypeError bilan yiqilib, foydalanuvchiga
        # "✅ ulandi" xabari HECH QACHON yetib bormas edi (bot "qotib"
        # qolganday ko'rinardi). Endi ikkita alohida xabar yuboriladi:
        # 1) reply-klaviatura bilan tasdiq, 2) inline ro'yxat (agar bo'lsa).
        await msg.reply_text(
            "✅ <b>Kanal muvaffaqiyatli ulandi!</b>\n\n"
            f"📢 Nomi: <b>{html_escape(channel_title)}</b>\n"
            f"🆔 ID: <code>{channel_id}</code>\n\n"
            f"📋 <b>Sizning kanallaringiz ({len(channels or [])} ta):</b>",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML",
        )
        if list_markup:
            try:
                await msg.reply_text(
                    "Kanalni o'chirish yoki uslubini o'zgartirish uchun 👇",
                    reply_markup=list_markup,
                    parse_mode="HTML",
                )
            except TelegramError:
                pass

        # Referal PRO mukofotini tekshirish (taklif qilgan foydalanuvchiga)
        referrer_id = await db.run_db(db.get_referrer_id, user_id)
        if referrer_id:
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
        context.user_data.pop("add_channel_pending", None)
        await msg.reply_text(
            "🚫 <b>Bu kanal allaqachon boshqa foydalanuvchiga ulangan.</b>\n\n"
            "O'g'irlab bo'lmaydi. Agar bu sizning kanalingiz bo'lsa, avval egasi botdan o'chirishi kerak.",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML",
        )
    else:
        await msg.reply_text(
            "❌ Kanalni saqlashda xatolik yuz berdi.",
            reply_markup=get_main_keyboard(is_admin),
        )

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
    """Avtomatik aniqlash (Auto-detect): botni kanal/guruhga admin qilib
    qo'shish/olib tashlashni ``my_chat_member`` orqali kuzatadi.

    Foydalanuvchi botni o'z kanaliga ADMIN qilib qo'shishi bilan (xabar
    yuborish — ``can_post_messages`` — huquqi bilan) bot buni darhol
    aniqlaydi va kanal egasiga shaxsiy chatda tabrik xabarini yuboradi —
    forward/username yuborishga hojat qolmaydi.
    """
    result = update.my_chat_member
    if not result:
        return
    chat = result.chat
    new_member = result.new_chat_member
    new_status = new_member.status
    user_id = result.from_user.id

    if chat.type not in ("channel", "supergroup", "group"):
        return

    if new_status in ("administrator", "creator"):
        # Kanallarda xabar yuborish uchun aniq ruxsat (can_post_messages)
        # shart — ``result.new_chat_member`` allaqachon ``get_chat_member``
        # bilan bir xil ma'lumotni o'z ichiga oladi (Telegram shu update'da
        # yuboradi), shuning uchun qo'shimcha API chaqiruvisiz tekshiramiz.
        if chat.type == "channel" and new_status == "administrator":
            if not getattr(new_member, "can_post_messages", False):
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=(
                            "⚠️ <b>Bot administrator qilindi, lekin xabar yuborish "
                            "ruxsati (Post Messages) berilmagan!</b>\n\n"
                            f"📢 Kanal: <b>{html_escape(chat.title or 'Kanal')}</b>\n\n"
                            "Iltimos, kanal sozlamalarida botga <b>Post Messages</b> "
                            "huquqini yoqing — shundan so'ng kanal avtomatik ulanadi."
                        ),
                        parse_mode="HTML",
                    )
                except TelegramError:
                    pass
                return

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
                        f"🎉 <b>Siz botni {html_escape(chat.title or 'Kanal')} kanaliga "
                        f"admin qildingiz va kanal ulandi!</b>\n\n"
                        f"🆔 <code>{chat.id}</code>\n\n"
                        "Endi ushbu kanalga postlarni rejalashtirishingiz mumkin 👇"
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


# ============================================================
# REAL-TIME CHANNEL POST LISTENER
# ============================================================

async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot admin bo'lgan ulangan kanallarga yangi post kelganda channel_posts_history ga yozish."""
    msg = update.channel_post or update.edited_channel_post or update.effective_message
    if not msg or not msg.chat:
        return

    channel_id = str(msg.chat.id)
    message_id = getattr(msg, "message_id", None)
    text = (msg.text or msg.caption or "").strip()
    views = getattr(msg, "views", 0) or 0
    post_date = getattr(msg, "date", None)

    content = text
    if not content:
        if getattr(msg, "photo", None):
            content = "[Rasm]"
        elif getattr(msg, "video", None):
            content = "[Video]"
        elif getattr(msg, "document", None):
            content = "[Hujjat]"
        elif getattr(msg, "audio", None):
            content = "[Audio]"
        elif getattr(msg, "animation", None):
            content = "[GIF]"

    if not content:
        content = ""

    try:
        await db.run_db(
            db.save_channel_post_history,
            channel_id=channel_id,
            message_id=message_id,
            content=content,
            views=views,
            post_date=post_date,
        )
    except Exception as e:
        logger.warning("on_channel_post saqlashda xato (%s): %s", channel_id, e)
