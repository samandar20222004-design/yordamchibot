"""Subscriptions, Limits & Monetization — tariflar va obuna boshqaruvi."""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import get_main_keyboard
from utils.helpers import html_escape

logger = logging.getLogger(__name__)

# States
SUBSCRIPTION_VIEW = 601
PROMO_INPUT = 602

# Stars to'lov paketlari
STARS_PLANS = {
    "stars_1m": {"label": "⭐️ 1 oylik (75 Stars)", "stars": 75, "days": 30, "description": "~$1.5"},
    "stars_3m": {"label": "⭐️ 3 oylik (175 Stars)", "stars": 175, "days": 90, "description": "~$3.5"},
    "stars_1y": {"label": "⭐️ 1 yillik (550 Stars)", "stars": 550, "days": 365, "description": "~$11.0 / -40% chegirma"},
}

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
            "",
            "💳 <b>PRO Tarif narxlari:</b>",
            "• 1 oy — ⭐️ 75 Stars (~$1.5)",
            "• 3 oy — ⭐️ 175 Stars (~$3.5)",
            "• 1 yil — ⭐️ 550 Stars (~$11.0 / -40% chegirma)",
            "",
            "👥 Referal: 3 ta do'stingizni taklif qiling va 1 oy bepul PRO oling!",
        ])

    return "\n".join(lines)


def _get_subscription_keyboard(plan: str) -> InlineKeyboardMarkup:
    """Obuna sahifasi tugmalari — Stars to'lov tugmalari to'g'ridan-to'g'ri ko'rsatiladi."""
    keyboard = []
    if plan == "free":
        keyboard.append([
            InlineKeyboardButton("⭐️ 1 oy (75 Stars)", callback_data="sub_pay:stars_1m"),
            InlineKeyboardButton("⭐️ 3 oy (175 Stars)", callback_data="sub_pay:stars_3m"),
        ])
        keyboard.append([
            InlineKeyboardButton("⭐️ 1 yil (550 Stars)", callback_data="sub_pay:stars_1y"),
        ])
    keyboard.append([InlineKeyboardButton("🎁 Promo-kod kiritish", callback_data="sub_promo")])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="sub_back_main")])
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

    if query.message is None:
        return SUBSCRIPTION_VIEW

    if data == "sub_close":
        await query.message.reply_text(
            "✅ Yopildi.",
            reply_markup=get_main_keyboard(is_admin),
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
            text="🏠 Asosiy menyu.",
            reply_markup=get_main_keyboard(is_admin),
        )
        return ConversationHandler.END

    if data == "sub_open":
        # Tarif limiti / reklama tugmasi orqali '⭐️ PRO tarifga o'tish' —
        # obuna kartasini ko'rsatadi.
        plan_info = await db.run_db(db.get_user_plan, user_id)
        card = _build_subscription_card(plan_info)
        plan = plan_info.get("plan_type", "free")
        try:
            await query.message.reply_text(
                card,
                reply_markup=_get_subscription_keyboard(plan),
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

    if data == "sub_back":
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

    if data == "sub_promo":
        await query.message.reply_text(
            "🎁 <b>Promo-kodni kiriting:</b>\n\n"
            "Promo-kodni yozing yoki '🔙 Orqaga' tugmasini bosing.",
            parse_mode="HTML",
        )
        return PROMO_INPUT

    if data == "sub_refresh":
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
    if user_id not in ADMIN_IDS_SET:
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


# ============================================================
# TELEGRAM STARS PAYMENT HANDLERS
# ============================================================

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """PreCheckoutQuery — Telegram to'lovni tasdiqlashdan oldin so'raydi.

    Eng birinchi ish — darhol javob berish (ok=True/False). Payload tekshiruvi
    sinxron, ya'ni answer() dan oldin hech qanday await yo'q.
    """
    query = update.pre_checkout_query
    if not query:
        return

    # Payload tekshirish — sub_stars_1m_USERID, sub_stars_3m_USERID, sub_stars_1y_USERID
    payload = query.invoice_payload or ""
    ok = payload.startswith("sub_stars_")
    await query.answer(ok=ok, error_message=None if ok else "Noto'g'ri to'lov so'rovi.")


async def create_promo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """SuperAdmin: /create_promo <KOD> <KUNLAR> <MAKS_ISHLATISH> — promo-kod yaratish."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS_SET:
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

    success = await db.run_db(db.create_promo_code, code, "pro", days, max_uses)
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
    """SuccessfulPayment — to'lov muvaffaqiyatli o'tganda."""
    payment = update.message.successful_payment
    if not payment:
        return

    user_id = update.effective_user.id
    total_stars = payment.total_amount
    payload = payment.invoice_payload or ""

    # PRO muddatini aniqlash
    if total_stars >= 550:
        days = 365  # 1 yillik
    elif total_stars >= 175:
        days = 90  # 3 oylik
    else:
        days = 30  # 1 oylik

    # PRO berish
    success = await db.run_db(db.set_user_plan, user_id, "pro", days)

    # To'lovni log qilash
    await db.run_db(
        db.log_stars_payment, user_id, total_stars, "XTR",
        payload, payment.telegram_payment_charge_id or ""
    )

    if success:
        await update.message.reply_text(
            f"🎉 <b>To'lov muvaffaqiyatli!</b>\n\n"
            f"⭐️ {total_stars} Stars qabul qilindi.\n"
            f"📅 <b>{days} kunlik PRO tarif</b> faollashtirildi!\n\n"
            f"Barcha PRO imkoniyatlardan foydalanishingiz mumkin:\n"
            f"• Cheksiz kanallar\n"
            f"• Cheksiz AI\n"
            f"• To'liq analitika",
            reply_markup=get_main_keyboard(update.effective_user.id in ADMIN_IDS_SET),
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            "⚠️ To'lov qabul qilindi, lekin tarifni faollashtirishda xatolik.\n"
            "Iltimos, admin bilan bog'laning.",
            parse_mode="HTML",
        )
