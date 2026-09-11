"""Subscriptions, Limits & Monetization — tariflar va obuna boshqaruvi."""
import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import ContextTypes, ConversationHandler
from config import (
    ADMIN_IDS_SET,
    CARD_NUMBER, CARD_HOLDER, PAYMENT_ADMIN_USERNAME,
    PAYMENT_PRICE_1M_UZS, PAYMENT_PRICE_3M_UZS, PAYMENT_PRICE_1Y_UZS,
)
import database as db
from keyboards.default import get_main_keyboard
from keyboards.callback_data import cb
from handlers.start import ensure_user_lang
from locales.translations import get_text, get_lang
from utils.helpers import html_escape
# 6-bosqich: RBAC — /grant_pro va /create_promo endi ruxsatga bog'langan.
from services.rbac_service import (
    PERM_MANAGE_PROMOS,
    PERM_MANAGE_USERS,
    has_permission,
    require_permission,
)

logger = logging.getLogger(__name__)

# States
SUBSCRIPTION_VIEW = 601
PROMO_INPUT = 602
# 💳 Karta to'lov chekini (rasm/PDF) kutuvchi holat — Admin Approval Flow
RECEIPT_WAIT = 603

# Stars to'lov paketlari
STARS_PLANS = {
    "stars_1m": {"label": "⭐️ 1 oylik (75 Stars)", "stars": 75, "days": 30, "description": "~$1.5"},
    "stars_3m": {"label": "⭐️ 3 oylik (175 Stars)", "stars": 175, "days": 90, "description": "~$3.5"},
    "stars_1y": {"label": "⭐️ 1 yillik (550 Stars)", "stars": 550, "days": 365, "description": "~$11.0 / -40% chegirma"},
}

# 💳 Karta orqali to'lov (Uzcard/Humo) tariflari.
# Tartib: CARD_TARIFF_ORDER dagi ketma-ketlikda tugmalar chiqadi.
CARD_TARIFFS = {
    "1m": {"days": 30, "amount": PAYMENT_PRICE_1M_UZS},
    "3m": {"days": 90, "amount": PAYMENT_PRICE_3M_UZS},
    "1y": {"days": 365, "amount": PAYMENT_PRICE_1Y_UZS},
}
CARD_TARIFF_ORDER = ("1m", "3m", "1y")
# Eski yozuvlar uchun days -> plan_key zaxira xaritasi (migratsiyasiz to'g'ri ishlaydi)
_DAYS_TO_PLAN = {30: "1m", 90: "3m", 365: "1y"}


def _fmt_uzs(amount: int) -> str:
    """19000 → '19 000' (so'm formatida)."""
    try:
        return f"{int(amount):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(amount)


def _fmt_card_number(card: str) -> str:
    """16 xonali raqamni 4 talab ajratadi: '1234567812345678' → '1234 5678 1234 5678'.

    Karta raqamining o'zi kodda saqlanmaydi — ``config.CARD_NUMBER`` (.env) dan keladi.
    """
    digits = "".join(ch for ch in str(card or "") if ch.isdigit())
    if not digits:
        return str(card or "")
    return " ".join(digits[i:i + 4] for i in range(0, len(digits), 4))


def _card_tariff_name(plan_key: str, lang: str = "uz") -> str:
    """'1m' → '1 oy' / '1 месяц' (tarif NOMI, narxsiz)."""
    return get_text(f"card_plan_{plan_key}", lang)


def _card_tariff_label(plan_key: str, lang: str = "uz") -> str:
    """Tarif tugmasi yorlig'i: '1 oy — 19 000 so'm' (yoki ruscha)."""
    plan = CARD_TARIFFS.get(plan_key) or CARD_TARIFFS["1m"]
    price = _fmt_uzs(plan["amount"])
    return get_text(f"card_tariff_{plan_key}", lang, price=price)


def _plan_key_for_days(days) -> str:
    """Berilgan kunlar uchun mos plan kalitini qaytaradi ('1m' default)."""
    try:
        return _DAYS_TO_PLAN.get(int(days), "1m")
    except (TypeError, ValueError):
        return "1m"

# Limit xabarlari
LIMIT_CHANNEL_MSG = (
    "🚫 <b>Kanal limiti tugadi!</b>\n\n"
    "Sizda hozir <b>{current}/{max}</b> ta kanal ulangan.\n"
    "Free tarifida maksimal <b>{max}</b> ta kanal ulash mumkin.\n\n"
    "⭐️ Ushbu imkoniyatdan cheksiz foydalanish uchun PRO tarifiga o'ting."
)

LIMIT_AI_MSG = (
    "🚫 <b>Kunlik AI limiti tugadi!</b>\n\n"
    "Bugun <b>{used}/{max}</b> ta AI so'rovi ishlatildi.\n"
    "Free tarifida kuniga maksimal <b>{max}</b> ta AI so'rovi.\n\n"
    "⭐️ Cheksiz AI uchun PRO tarifiga o'ting."
)


def _format_expires(expires_at, lang: str = "uz") -> str:
    """Obuna tugash muddatini formatlaydi."""
    if expires_at is None:
        if lang == "ru":
            return "♾ Безлимит"
        if lang == "en":
            return "♾ Unlimited"
        return "♾ Cheksiz"
    try:
        return expires_at.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(expires_at)


def _build_subscription_card(plan_info: dict, lang: str = "uz") -> str:
    """Obuna holati kartasini yaratadi (uz/ru/en)."""
    plan = plan_info.get("plan_type", "free")
    expires = plan_info.get("expires_at")
    ai_used = plan_info.get("ai_used", 0)

    plan_emoji = {"free": "🆓", "pro": "⭐️", "enterprise": "💎"}.get(plan, "🆓")
    plan_name = {"free": "Free", "pro": "PRO", "enterprise": "Enterprise"}.get(plan, "Free")

    limits = db.PLAN_LIMITS.get(plan, db.PLAN_LIMITS["free"])
    max_ch = limits["max_channels"]
    max_ai = limits["daily_ai_requests"]
    unlimited = {"uz": "Cheksiz", "ru": "Безлимит", "en": "Unlimited"}.get(lang, "Cheksiz")
    ch_str = str(max_ch) if max_ch < 999 else unlimited
    ai_str = str(max_ai) if max_ai < 999 else unlimited
    your = {
        "uz": f"{plan_emoji} <b>Sizning tarifingiz: {plan_name}</b>",
        "ru": f"{plan_emoji} <b>Ваш тариф: {plan_name}</b>",
        "en": f"{plan_emoji} <b>Your plan: {plan_name}</b>",
    }.get(lang, f"{plan_emoji} <b>Sizning tarifingiz: {plan_name}</b>")
    expires_l = {
        "uz": f"📅 Obuna muddati: <b>{_format_expires(expires, lang)}</b>",
        "ru": f"📅 Срок подписки: <b>{_format_expires(expires, lang)}</b>",
        "en": f"📅 Subscription: <b>{_format_expires(expires, lang)}</b>",
    }.get(lang)
    ch_l = {
        "uz": f"📢 Kanallar limiti: <b>{ch_str}</b>",
        "ru": f"📢 Лимит каналов: <b>{ch_str}</b>",
        "en": f"📢 Channel limit: <b>{ch_str}</b>",
    }.get(lang)
    ai_l = {
        "uz": f"🤖 Kunlik AI so'rovlar: <b>{ai_used} / {ai_str}</b>",
        "ru": f"🤖 ИИ-запросы за день: <b>{ai_used} / {ai_str}</b>",
        "en": f"🤖 Daily AI requests: <b>{ai_used} / {ai_str}</b>",
    }.get(lang)

    lines = [
        your,
        "━━━━━━━━━━━━━━━━━",
        expires_l,
        ch_l,
        ai_l,
        "━━━━━━━━━━━━━━━━━",
    ]

    if plan == "free":
        if lang == "ru":
            lines.extend([
                "",
                "⭐️ <b>Возможности тарифа PRO:</b>",
                "• Безлимитные каналы",
                "• Безлимитный ИИ и контент-план",
                "• Безлимитная очередь постов",
                "• Полная аналитика",
                "• Приоритетная поддержка",
            ])
        elif lang == "en":
            lines.extend([
                "",
                "⭐️ <b>PRO features:</b>",
                "• Unlimited channels",
                "• Unlimited AI posts and content plan",
                "• Unlimited queue",
                "• Full analytics",
                "• Priority support",
            ])
        else:
            lines.extend([
                "",
                "⭐️ <b>PRO Tarif imkoniyatlari:</b>",
                "• Cheksiz kanallar ulash",
                "• Cheksiz AI post yordamchisi va Kontent-reja",
                "• Cheksiz Queue (Navbat) postlari",
                "• To'liq analitika",
                "• Ustuvor yordam",
            ])
        lines.extend([
            "",
            "💳 <b>PRO:</b>",
            "• 1 oy — ⭐️ 75 Stars (~$1.5)",
            "• 3 oy — ⭐️ 175 Stars (~$3.5)",
            "• 1 yil — ⭐️ 550 Stars (~$11.0 / -40%)",
        ])

    return "\n".join(lines)


def _get_subscription_keyboard(plan: str, lang: str = "uz") -> InlineKeyboardMarkup:
    """Obuna sahifasi tugmalari — Stars to'lov tugmalari to'g'ridan-to'g'ri ko'rsatiladi.

    Free tarifda Stars yoniga 💳 Karta orqali to'lov (Uzcard / Humo) tugmasi
    ham qo'shiladi — O'zbekiston foydalanuvchilari uchun qulaylik.
    """
    keyboard = []
    if plan == "free":
        keyboard.append([
            InlineKeyboardButton("⭐️ 1 oy (75 Stars)", callback_data="sub_pay:stars_1m"),
            InlineKeyboardButton("⭐️ 3 oy (175 Stars)", callback_data="sub_pay:stars_3m"),
        ])
        keyboard.append([
            InlineKeyboardButton("⭐️ 1 yil (550 Stars)", callback_data="sub_pay:stars_1y"),
        ])
        keyboard.append([
            InlineKeyboardButton(get_text("btn_card_payment", lang), callback_data="sub_card_pay"),
        ])
    promo = {"uz": "🎁 Promo-kod kiritish", "ru": "🎁 Ввести промокод", "en": "🎁 Enter promo code"}.get(lang, "🎁 Promo-kod kiritish")
    keyboard.append([InlineKeyboardButton(promo, callback_data="sub_promo")])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="sub_back_main")])
    return InlineKeyboardMarkup(keyboard)


def _build_card_payment_text(
    user_id: int, lang: str = "uz", plan_key: str = "1m"
) -> str:
    """💳 Karta orqali to'lov ekrani: tanlangan tarif, summa va karta rekvizitlari.

    ``plan_key`` — '1m' | '3m' | '1y' (CARD_TARIFFS kaliti). Eski chaqiruvlar
    ``plan_key`` siz ham ishlaydi (default '1m' = 19 000 so'm).
    """
    plan = CARD_TARIFFS.get(plan_key) or CARD_TARIFFS["1m"]
    plan_name = _card_tariff_name(plan_key, lang)
    price = _fmt_uzs(plan["amount"])
    parts = [
        get_text("card_payment_title", lang),
        "",
        get_text("card_payment_selected", lang, tarif=plan_name, summa=price),
        "",
    ]
    # Karta rekvizitlari FAQAT config/.env dan (CARD_NUMBER / CARD_HOLDER) —
    # kodda qattiq yozilgan raqam yo'q.
    if CARD_NUMBER:
        parts.append(get_text(
            "card_payment_card", lang,
            card=html_escape(_fmt_card_number(CARD_NUMBER)),
            holder=html_escape(CARD_HOLDER or "—"),
        ))
    else:
        parts.append(get_text("card_payment_no_card", lang))
    parts.append("")
    admin_ref = (
        f"@{html_escape(PAYMENT_ADMIN_USERNAME)}" if PAYMENT_ADMIN_USERNAME
        else get_text("card_payment_admin_missing", lang)
    )
    parts.append(get_text("card_payment_steps", lang, admin=admin_ref, user_id=user_id))
    return "\n".join(parts)


def _get_card_tariffs_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """💳 Karta to'lovi uchun TARIF TANLASH klaviaturasi (1m/3m/1y + orqaga)."""
    keyboard = []
    for key in CARD_TARIFF_ORDER:
        keyboard.append([
            InlineKeyboardButton(
                _card_tariff_label(key, lang), callback_data=cb(f"sub_tarif:{key}")
            )
        ])
    keyboard.append([
        InlineKeyboardButton(get_text("btn_back", lang), callback_data="sub_back")
    ])
    return InlineKeyboardMarkup(keyboard)


def _get_card_payment_keyboard(
    lang: str = "uz", plan_key: str = "1m"
) -> InlineKeyboardMarkup:
    keyboard = []
    # 📸 Bot tugmasi: foydalanuvchi chekni to'g'ridan-to'g'ri botga yuboradi va
    # u Admin Approval Flow orqali barcha adminlarga yetkaziladi.
    keyboard.append([
        InlineKeyboardButton(get_text("btn_send_receipt", lang), callback_data="sub_send_receipt")
    ])
    if PAYMENT_ADMIN_USERNAME:
        keyboard.append([InlineKeyboardButton(
            "✉️ Adminga chek yuborish" if lang != "ru" else "✉️ Отправить чек администратору",
            url=f"https://t.me/{PAYMENT_ADMIN_USERNAME}",
        )])
    keyboard.append([InlineKeyboardButton(get_text("btn_back", lang), callback_data="sub_back")])
    return InlineKeyboardMarkup(keyboard)


def _get_stars_keyboard() -> InlineKeyboardMarkup:
    """Stars to'lov tanlash keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("⭐️ 1 oylik (75 Stars)", callback_data="sub_pay:stars_1m"),
            InlineKeyboardButton("⭐️ 3 oylik (175 Stars)", callback_data="sub_pay:stars_3m"),
        ],
        [InlineKeyboardButton("⭐️ 1 yillik (550 Stars)", callback_data="sub_pay:stars_1y")],
        [InlineKeyboardButton("🎁 Promo-kod kiritish", callback_data="sub_promo")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="sub_back")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def start_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Premium / Tariflar bo'limini boshlash."""
    user_id = update.effective_user.id
    lang = await ensure_user_lang(context, user_id)
    plan_info = await db.run_db(db.get_user_plan, user_id)
    card = _build_subscription_card(plan_info, lang)
    plan = plan_info.get("plan_type", "free")

    await update.message.reply_text(
        card,
        reply_markup=_get_subscription_keyboard(plan, lang),
        parse_mode="HTML",
    )
    return SUBSCRIPTION_VIEW


async def subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obuna sahifasi tugmalari."""
    query = update.callback_query
    # ENG BIRINCHI QATORDI — har bir callback darhol answer() oladi, aks holda
    # Telegram tugmani "yuklanmoqda" holatida qoldiradi (tugma qotib qoladi),
    # ayniqsa send_invoice sekin ishlasa yoki xatolik bersa.
    try:
        await query.answer()
    except Exception:
        pass

    data = query.data
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS_SET
    # Reply-tugma / eski inline orqali kirishda ham til DB'dan to'g'ri olinadi
    # (context.user_data bo'sh bo'lsa 'uz'ga tushib qolmaslik uchun).
    lang = await ensure_user_lang(context, user_id)

    if query.message is None:
        return SUBSCRIPTION_VIEW

    if data == "sub_close":
        await query.message.reply_text(
            get_text("msg_closed", lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
        )
        return ConversationHandler.END

    if data == "sub_back_main":
        # Xabarni o'chirib, asosiy menyuni yuboramiz
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=get_text("main_menu_hint", lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
        )
        return ConversationHandler.END

    if data == "sub_open":
        # Tarif limiti / reklama tugmasi orqali '⭐️ PRO tarifga o'tish' —
        # obuna kartasini ko'rsatadi.
        plan_info = await db.run_db(db.get_user_plan, user_id)
        card = _build_subscription_card(plan_info, lang)
        plan = plan_info.get("plan_type", "free")
        try:
            await query.message.reply_text(
                card,
                reply_markup=_get_subscription_keyboard(plan, get_lang(context)),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return SUBSCRIPTION_VIEW

    if data.startswith("sub_pay:"):
        plan_key = data.split(":", 1)[1]
        # Telegram Stars (XTR) invoice ma'lumotlari: (miqdor, sarlavha, tavsif)
        plan_map = {
            "stars_1m": (75, "⭐️ PostAssist PRO (1 oy)", "1 oylik to'liq PRO imkoniyatlar"),
            "stars_3m": (175, "⭐️ PostAssist PRO (3 oy)", "3 oylik to'liq PRO imkoniyatlar"),
            "stars_1y": (550, "⭐️ PostAssist PRO (1 yil)", "1 yillik to'liq PRO imkoniyatlar (chegirma bilan)"),
        }
        if plan_key not in plan_map:
            await query.message.reply_text("❌ Noto'g'ri tarif tanlandi.")
            return SUBSCRIPTION_VIEW

        amount, title, desc = plan_map[plan_key]
        prices = [LabeledPrice(label=title, amount=amount)]

        try:
            # Telegram Stars (XTR) uchun provider_token talab qilinmaydi,
            # lekin PTB 21.x da bo'sh satr (provider_token="") uzatilishi
            # talab etiladi — None qiymat ba'zi PTB versiyalarida so'rovdan
            # tashlab qo'yilib, Telegram Stars invoice'ni ocholmay qoladi.
            await context.bot.send_invoice(
                chat_id=update.effective_chat.id,
                title=title,
                description=desc,
                payload=f"sub_{plan_key}_{user_id}",
                provider_token="",
                currency="XTR",
                prices=prices,
                start_parameter="pro-sub",
            )
        except Exception as e:
            logger.warning("Invoice yaratish xatosi: %s", e)
            try:
                await query.message.reply_text(
                    "⚠️ To'lov oynasini ochishda xatolik yuz berdi. Iltimos, qayta urinib ko'ring."
                )
            except Exception:
                pass
        return SUBSCRIPTION_VIEW

    if data == "sub_card_pay":
        # 1-qadam: 💳 Karta to'lovi — avval TARIF tanlanadi (1 oy / 3 oy / 1 yil).
        text = get_text("card_tariff_title", lang)
        markup = _get_card_tariffs_keyboard(lang)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
        return SUBSCRIPTION_VIEW

    if data.startswith("sub_tarif:"):
        # 2-qadam: tarif tanlandi — karta raqami, egasi va summa ko'rsatiladi.
        plan_key = data.split(":", 1)[1]
        if plan_key not in CARD_TARIFFS:
            return SUBSCRIPTION_VIEW
        # Tanlangan tarifni kontekstda saqlaymiz — chek kelganda admin xabarida
        # aynan shu tarif (nomi + summasi) ko'rsatiladi va PRO shu muddatga beriladi.
        context.user_data["card_plan"] = plan_key
        text = _build_card_payment_text(user_id, lang, plan_key)
        markup = _get_card_payment_keyboard(lang, plan_key)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
        return SUBSCRIPTION_VIEW

    if data == "sub_send_receipt":
        # 💳 Admin Approval Flow: chek (rasm/PDF) kutuvchi holatga o'tamiz.
        ud = getattr(context, "user_data", None) or {}
        plan_key = ud.get("card_plan") or "1m"
        plan = CARD_TARIFFS.get(plan_key) or CARD_TARIFFS["1m"]
        try:
            await query.message.reply_text(
                get_text(
                    "receipt_prompt", lang, user_id=user_id,
                    tarif=_card_tariff_name(plan_key, lang),
                    summa=_fmt_uzs(plan["amount"]),
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return RECEIPT_WAIT

    if data == "sub_back":
        plan_info = await db.run_db(db.get_user_plan, user_id)
        card = _build_subscription_card(plan_info, lang)
        plan = plan_info.get("plan_type", "free")
        try:
            await query.edit_message_text(
                card,
                reply_markup=_get_subscription_keyboard(plan, lang),
                parse_mode="HTML",
            )
        except Exception:
            await query.message.reply_text(
                card,
                reply_markup=_get_subscription_keyboard(plan, lang),
                parse_mode="HTML",
            )
        return SUBSCRIPTION_VIEW

    if data == "sub_promo":
        await query.message.reply_text(
            "🎁 <b>Promo-kodni kiriting:</b>\n\n"
            "Promo-kodni yozing yoki '🔙 Orqaga' tugmasini bosing.",
            parse_mode="HTML",
        )
        return PROMO_INPUT

    if data == "sub_refresh":
        plan_info = await db.run_db(db.get_user_plan, user_id)
        card = _build_subscription_card(plan_info, lang)
        plan = plan_info.get("plan_type", "free")
        try:
            await query.edit_message_text(
                card,
                reply_markup=_get_subscription_keyboard(plan, get_lang(context)),
                parse_mode="HTML",
            )
        except Exception:
            await query.message.reply_text(
                card,
                reply_markup=_get_subscription_keyboard(plan, get_lang(context)),
                parse_mode="HTML",
            )
        return SUBSCRIPTION_VIEW

    return SUBSCRIPTION_VIEW


async def promo_code_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Promo-kod qabul qilish."""
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id
    is_admin = user_id in ADMIN_IDS_SET

    if text in ("🔙 Asosiy menyu", "🔙 Orqaga"):
        # Qaytadan obuna kartasini ko'rsatamiz
        plan_info = await db.run_db(db.get_user_plan, user_id)
        card = _build_subscription_card(plan_info, lang)
        plan = plan_info.get("plan_type", "free")
        await update.message.reply_text(
            card,
            reply_markup=_get_subscription_keyboard(plan, get_lang(context)),
            parse_mode="HTML",
        )
        return SUBSCRIPTION_VIEW

    success, msg = await db.run_db(db.redeem_promo_code, user_id, text)

    if success:
        await update.message.reply_text(
            f"✅ <b>{html_escape(msg)}</b>\n\n"
            "Yangi tarif imkoniyatlaringiz faollashtirildi!",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML",
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            f"❌ <b>{html_escape(msg)}</b>\n\n"
            "Qaytadan urinib ko'ring yoki '🔙 Orqaga' tugmasini bosing.",
            parse_mode="HTML",
        )
        return PROMO_INPUT


@require_permission(PERM_MANAGE_USERS,
                    message="❌ Sizda foydalanuvchilarga PRO berish uchun ruxsat yo'q.")
async def grant_pro_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /grant_pro <user_id> <days> — foydalanuvchiga PRO berish."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS_SET and not has_permission(user_id, PERM_MANAGE_USERS):
        await update.message.reply_text("❌ Faqat admin bu buyruqni ishlatishi mumkin.")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "📝 Foydalanish: /grant_pro <user_id> <kunlar_soni>\n"
            "Masalan: /grant_pro 123456789 30"
        )
        return

    try:
        target_id = int(args[0])
        days = int(args[1])
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Noto'g'ri format. Masalan: /grant_pro 123456789 30")
        return

    if days <= 0:
        await update.message.reply_text("❌ Kunlar soni 0 dan katta bo'lishi kerak.")
        return

    success = await db.run_db(db.set_user_plan, target_id, "pro", days,
                              admin_id=user_id)
    if success:
        await update.message.reply_text(
            f"✅ <b>PRO tarif berildi!</b>\n\n"
            f"👤 Foydalanuvchi: <code>{target_id}</code>\n"
            f"📅 Muddat: <b>{days} kun</b>",
            parse_mode="HTML",
        )
        # Foydalanuvchiga xabar berishga harakat qilamiz
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"🎉 <b>Tabriklaymiz!</b>\n\n"
                    f"Sizga <b>{days} kunlik PRO tarif</b> berildi!\n"
                    f"Barcha PRO imkoniyatlardan foydalanishingiz mumkin."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass
    else:
        await update.message.reply_text("❌ Xatolik yuz berdi. User ID to'g'riligini tekshiring.")


# ============================================================
# TELEGRAM STARS PAYMENT HANDLERS
# ============================================================

_STARS_PAYLOAD_RE = re.compile(r"^sub_(stars_1m|stars_3m|stars_1y)_([0-9]+)$")


def _validate_stars_payload(payload: str, user_id: int, amount=None, currency=None):
    """Invoice payload + summa + valuta'ni qat'iy tekshiradi.

    Payload oddiy prefix tekshiruvi bilan qabul qilinmaydi: user ID, plan va
    Telegram invoice'dagi kutilgan Stars miqdori bir-biriga mos bo'lishi shart.
    """
    match = _STARS_PAYLOAD_RE.fullmatch(str(payload or ""))
    if not match:
        return None, "Noto'g'ri to'lov payload'i."
    plan_key, payload_user = match.groups()
    try:
        if int(payload_user) != int(user_id):
            return None, "To'lov foydalanuvchiga mos emas."
    except (TypeError, ValueError):
        return None, "Noto'g'ri foydalanuvchi ID."
    plan = STARS_PLANS.get(plan_key)
    if not plan:
        return None, "Noto'g'ri tarif."
    if currency is not None and str(currency).upper() != "XTR":
        return None, "To'lov valyutasi noto'g'ri."
    if amount is not None:
        try:
            if int(amount) != int(plan["stars"]):
                return None, "To'lov summasi tarifga mos emas."
        except (TypeError, ValueError):
            return None, "To'lov summasi noto'g'ri."
    return {"plan_key": plan_key, "stars": plan["stars"], "days": plan["days"]}, None


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """PreCheckoutQuery — Telegram to'lovni tasdiqlashdan oldin so'raydi.

    Eng birinchi ish — darhol javob berish (ok=True/False). Payload tekshiruvi
    sinxron, ya'ni answer() dan oldin hech qanday await yo'q.
    """
    query = update.pre_checkout_query
    if not query:
        return

    # Telegram payment retry/qo'lda yuborilgan soxta invoice'ni qat'iy rad etamiz.
    payload = query.invoice_payload or ""
    query_user = getattr(getattr(query, "from_user", None), "id", None)
    query_amount = getattr(query, "total_amount", None)
    query_currency = getattr(query, "currency", None)
    plan, error = _validate_stars_payload(
        payload,
        query_user,
        query_amount,
        query_currency,
    )
    if query_user is None or query_amount is None or query_currency is None:
        plan, error = None, "To'lov rekvizitlari to'liq emas."
    await query.answer(
        ok=plan is not None,
        error_message=None if plan is not None else (error or "Noto'g'ri to'lov so'rovi."),
    )


@require_permission(PERM_MANAGE_PROMOS,
                    message="❌ Sizda promo-kod yaratish uchun ruxsat yo'q.")
async def create_promo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """SuperAdmin: /create_promo <KOD> <KUNLAR> <MAKS_ISHLATISH> — promo-kod yaratish."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS_SET and not has_permission(user_id, PERM_MANAGE_PROMOS):
        await update.message.reply_text("❌ Faqat admin bu buyruqni ishlatishi mumkin.")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "📝 Foydalanish: /create_promo <KOD_NOMI> <KUNLAR> [MAKS_ISHLATISH]\n\n"
            "Masalan:\n"
            "• /create_promo MAXSUS30 30 50\n"
            "• /create_promo YANGI2026 30\n\n"
            "KUNLAR — obuna muddati (kun)\n"
            "MAKS_ISHLATISH — necha marta ishlatilishi mumkin (ixtiyoriy, cheksiz)"
        )
        return

    code = args[0].upper()
    try:
        days = int(args[1])
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Kunlar soni raqam bo'lishi kerak.")
        return

    max_uses = None
    if len(args) >= 3:
        try:
            max_uses = int(args[2])
        except ValueError:
            await update.message.reply_text("❌ Maks ishlatish soni raqam bo'lishi kerak.")
            return

    if days <= 0:
        await update.message.reply_text("❌ Kunlar soni 0 dan katta bo'lishi kerak.")
        return

    success = await db.run_db(db.create_promo_code, code, "pro", days, max_uses,
                              admin_id=user_id)
    if success:
        max_str = f"{max_uses} marta" if max_uses else "cheksiz"
        await update.message.reply_text(
            f"✅ <b>Promo-kod yaratildi!</b>\n\n"
            f"🏷 Kod: <code>{code}</code>\n"
            f"📅 Muddat: <b>{days} kun</b> PRO\n"
            f"🔢 Maks ishlatish: <b>{max_str}</b>\n\n"
            f"Foydalanuvchilar '🎁 Promo-kod kiritish' orqali faollashtirishi mumkin.",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            "❌ Promo-kod yaratishda xatolik. Bu kod allaqachon mavjud bo'lishi mumkin."
        )


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """SuccessfulPayment'ni qat'iy tekshiradi va atomik grant qiladi."""
    payment = getattr(getattr(update, "message", None), "successful_payment", None)
    if not payment:
        return

    user_id = update.effective_user.id
    total_stars = getattr(payment, "total_amount", None)
    payload = getattr(payment, "invoice_payload", "") or ""
    payment_currency = getattr(payment, "currency", None)
    plan, error = _validate_stars_payload(
        payload,
        user_id,
        total_stars,
        payment_currency,
    )
    if total_stars is None or payment_currency is None:
        plan, error = None, "To'lov rekvizitlari to'liq emas."
    charge_id = (getattr(payment, "telegram_payment_charge_id", "") or "").strip()
    if plan is None or not charge_id:
        logger.warning(
            "Stars payment rad etildi: user=%s payload=%r charge=%r sabab=%s",
            user_id, payload, charge_id, error or "charge_id yo'q",
        )
        return

    # Oldingi set_user_plan chaqiruvi o'rniga log_stars_payment audit yozuvi va
    # subscription UPDATE aynan shu
    # tranzaksiyada; bir xil charge_id qaytsa process_stars_payment duplicate
    # qaytaradi va obuna ikkinchi marta berilmaydi.
    result = await db.run_db(
        db.process_stars_payment,
        user_id,
        plan["stars"],
        "XTR",
        payload,
        charge_id,
        "pro",
        plan["days"],
    )
    if not isinstance(result, dict) or not result.get("ok"):
        await update.message.reply_text(
            "⚠️ To'lov qabul qilindi, lekin tarifni faollashtirishda xatolik.\n"
            "Iltimos, admin bilan bog'laning.",
            parse_mode="HTML",
        )
        return

    lang = await ensure_user_lang(context, user_id)
    if result.get("duplicate"):
        # Retry kelgan — grant allaqachon berilgan, yana subscription yozmaymiz.
        await update.message.reply_text(
            "✅ Bu to'lov avval qayta ishlangan. PRO tarifingiz allaqachon faol.",
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang=lang),
            parse_mode="HTML",
        )
        return

    days = plan["days"]
    await update.message.reply_text(
        f"🎉 <b>To'lov muvaffaqiyatli!</b>\n\n"
        f"⭐️ {total_stars} Stars qabul qilindi.\n"
        f"📅 <b>{days} kunlik PRO tarif</b> faollashtirildi!\n\n"
        f"Barcha PRO imkoniyatlardan foydalanishingiz mumkin:\n"
        f"• Cheksiz kanallar\n"
        f"• Cheksiz AI\n"
        f"• To'liq analitika",
        reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang=lang),
        parse_mode="HTML",
    )
