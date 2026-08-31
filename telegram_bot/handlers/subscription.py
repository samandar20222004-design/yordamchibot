"""Subscriptions, Limits & Monetization — tariflar va obuna boshqaruvi."""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID, ADMIN_IDS_SET
import database as db
from keyboards.default import get_main_keyboard
from utils.helpers import html_escape

logger = logging.getLogger(__name__)

# States
SUBSCRIPTION_VIEW = 601
PROMO_INPUT = 602

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


def _format_expires(expires_at) -> str:
    """Obuna tugash muddatini formatlaydi."""
    if expires_at is None:
        return "♾ Cheksiz"
    try:
        return expires_at.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(expires_at)


def _build_subscription_card(plan_info: dict) -> str:
    """Obuna holati kartasini yaratadi."""
    plan = plan_info.get("plan_type", "free")
    expires = plan_info.get("expires_at")
    ai_used = plan_info.get("ai_used", 0)

    plan_emoji = {"free": "🆓", "pro": "⭐️", "enterprise": "💎"}.get(plan, "🆓")
    plan_name = {"free": "Free", "pro": "PRO", "enterprise": "Enterprise"}.get(plan, "Free")

    limits = db.PLAN_LIMITS.get(plan, db.PLAN_LIMITS["free"])
    max_ch = limits["max_channels"]
    max_ai = limits["daily_ai_requests"]
    ch_str = str(max_ch) if max_ch < 999 else "Cheksiz"
    ai_str = str(max_ai) if max_ai < 999 else "Cheksiz"

    lines = [
        f"{plan_emoji} <b>Sizning tarifingiz: {plan_name}</b>",
        f"━━━━━━━━━━━━━━━━━",
        f"📅 Obuna muddati: <b>{_format_expires(expires)}</b>",
        f"📢 Kanallar limiti: <b>{ch_str}</b>",
        f"🤖 Kunlik AI so'rovlar: <b>{ai_used} / {ai_str}</b>",
        f"━━━━━━━━━━━━━━━━━",
    ]

    if plan == "free":
        lines.extend([
            "",
            "⭐️ <b>PRO Tarif imkoniyatlari:</b>",
            "• Cheksiz kanallar ulash",
            "• Cheksiz AI post yordamchisi va Kontent-reja",
            "• Cheksiz Queue (Navbat) postlari",
            "• To'liq analitika",
            "• Ustuvor yordam",
        ])

    return "\n".join(lines)


def _get_subscription_keyboard(plan: str) -> InlineKeyboardMarkup:
    """Obuna sahifasi tugmalari."""
    keyboard = []
    if plan == "free":
        keyboard.append([InlineKeyboardButton("💳 Obuna bo'lish", callback_data="sub_subscribe")])
    keyboard.append([InlineKeyboardButton("🎁 Promo-kod kiritish", callback_data="sub_promo")])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="sub_close")])
    return InlineKeyboardMarkup(keyboard)


async def start_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Premium / Tariflar bo'limini boshlash."""
    user_id = update.effective_user.id
    plan_info = await db.run_db(db.get_user_plan, user_id)
    card = _build_subscription_card(plan_info)
    plan = plan_info.get("plan_type", "free")

    await update.message.reply_text(
        card,
        reply_markup=_get_subscription_keyboard(plan),
        parse_mode="HTML",
    )
    return SUBSCRIPTION_VIEW


async def subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obuna sahifasi tugmalari."""
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS_SET

    if data == "sub_close":
        await query.answer()
        await query.message.reply_text(
            "✅ Yopildi.",
            reply_markup=get_main_keyboard(is_admin),
        )
        return ConversationHandler.END

    if data == "sub_subscribe":
        await query.answer()
        await query.message.reply_text(
            "💳 <b>Obuna bo'lish</b>\n\n"
            "Hozircha obuna to'lov tizimi orqali amalga oshiriladi.\n"
            "To'lov havolasi tez orada qo'shiladi.\n\n"
            "🎁 Agar promo-kodingiz bo'lsa, 'Promo-kod kiritish' tugmasini bosing.",
            parse_mode="HTML",
        )
        return SUBSCRIPTION_VIEW

    if data == "sub_promo":
        await query.answer()
        await query.message.reply_text(
            "🎁 <b>Promo-kodni kiriting:</b>\n\n"
            "Promo-kodni yozing yoki '🔙 Orqaga' tugmasini bosing.",
            parse_mode="HTML",
        )
        return PROMO_INPUT

    if data == "sub_refresh":
        await query.answer("🔄 Yangilanmoqda...")
        plan_info = await db.run_db(db.get_user_plan, user_id)
        card = _build_subscription_card(plan_info)
        plan = plan_info.get("plan_type", "free")
        try:
            await query.edit_message_text(
                card,
                reply_markup=_get_subscription_keyboard(plan),
                parse_mode="HTML",
            )
        except Exception:
            await query.message.reply_text(
                card,
                reply_markup=_get_subscription_keyboard(plan),
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
        card = _build_subscription_card(plan_info)
        plan = plan_info.get("plan_type", "free")
        await update.message.reply_text(
            card,
            reply_markup=_get_subscription_keyboard(plan),
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


async def grant_pro_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /grant_pro <user_id> <days> — foydalanuvchiga PRO berish."""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
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

    success = await db.run_db(db.set_user_plan, target_id, "pro", days)
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
