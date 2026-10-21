"""Subscriptions, Limits & Monetization — tariflar va obuna boshqaruvi."""
import logging
import time
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import BaseHandler, ContextTypes, ConversationHandler
from config import (
    ADMIN_IDS_SET, BOT_USERNAME,
    CARD_NUMBER, CARD_HOLDER, PAYMENT_ADMIN_USERNAME,
    PLAN_PRO, PLAN_ULTRA, STARS_PLANS, TARIFF_CATALOG, TARIFF_KEYS, TIER_LIMITS,
    UNLIMITED_LIMIT, key_for_days, plan_discount_percent, tariff_keys_for, tier_of_key,
)
import database as db
from keyboards.default import get_main_keyboard
from keyboards.callback_data import cb
from keyboards.inline import (
    CB_PAY_INTL_PLAN,
    CB_PAY_REGION,
    PAYMENT_REGION_INTL,
    PAYMENT_REGION_UZ,
    get_intl_tariffs_keyboard,
    get_payment_region_keyboard,
    is_payment_region,
    payment_region_from_callback,
)
from handlers.start import ensure_user_lang
from locales.translations import (
    get_text, get_lang, is_main_menu_text, localize_db_message,
)
from utils.helpers import html_escape
from translations.admin_panel import admin_t
from services.promo_attempts import promo_limiter
from services.subscription_service import MAX_ADMIN_GRANT_DAYS
# RBAC — /grant_pro va /create_promo endi ruxsatga bog'langan.
from services.rbac_service import (
    PERM_MANAGE_PROMOS,
    PERM_MANAGE_USERS,
    has_permission,
    require_permission,
)

from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

# States
SUBSCRIPTION_VIEW = 601
PROMO_INPUT = 602
#: Promo-kod kutilayotganini ``user_data`` da eslab qoladi (suhbatdan tashqarida
#: bosilgan «Promo-kod» tugmasi holat qaytara olmaydi — kod «tushunmadim»ga tushardi).
UD_PROMO_WAIT = "promo_wait_ts"
PROMO_WAIT_SECONDS = 5 * 60
# 💳 Karta to'lov chekini (rasm/PDF) kutuvchi holat — Admin Approval Flow
RECEIPT_WAIT = 603

# Stars to'lov paketlari — YAGONA MANBA: config.STARS_PLANS (SSOT).
# Avval bu modulda lokal qattiq-kodlangan dict shadowing qilingan edi (F811):
# precheckout bu yerdan, payment_service esa config'dan o'qigan. Endi ikkala
# oqim ham import qilingan config.STARS_PLANS ni ulashadi — tarif o'zgarishi
# (.env: STARS_PRICE_1M/3M/1Y) avtomatik precheckout tekshiruvi va
# PaymentService.validate_payload ga tarqaladi.

# 💳 To'lov tariflari (karta / Payme / Stars) — YAGONA MANBA: config.TARIFF_CATALOG.
# Kalitlar: PRO — '1m' | '3m' | '6m' | '1y' (eski callback/payload/buyurtmalar bilan mos); ULTRA — 'u1m' | 'u3m' | 'u6m' | 'u1y'.
CARD_TARIFFS = {
    key: {"days": info["days"], "amount": info["uzs"], "tier": info["tier"]}
    for key, info in TARIFF_CATALOG.items()
}
CARD_TARIFF_ORDER = TARIFF_KEYS
# Eski yozuvlar uchun days -> plan_key zaxira xaritasi (PRO; migratsiyasiz to'g'ri ishlaydi)
_DAYS_TO_PLAN = {info["days"]: key for key, info in TARIFF_CATALOG.items() if info["tier"] == PLAN_PRO}

_TIER_EMOJI = {"free": "🆓", PLAN_PRO: "⭐️", PLAN_ULTRA: "👑", "enterprise": "💎"}
_TIER_NAME = {"free": "FREE", PLAN_PRO: "PRO", PLAN_ULTRA: "ULTRA", "enterprise": "Enterprise"}


def _fmt_limit(n, lang: str = "uz") -> str:
    """Limit qiymati: 999 va undan katta = 'cheksiz' (faqat enterprise / eski to'lagan PRO)."""
    try:
        value = int(n)
    except (TypeError, ValueError):
        return str(n)
    return get_text("tl_unlimited", lang) if value >= UNLIMITED_LIMIT else str(value)


def _cap_text(n, lang: str = "uz") -> str:
    """'<b>10</b> tagacha' yoki (999+) '<b>cheksiz</b>'."""
    try:
        value = int(n)
    except (TypeError, ValueError):
        return str(n)
    if value >= UNLIMITED_LIMIT:
        return f"<b>{get_text('tl_unlimited', lang)}</b>"
    return get_text("tl_upto", lang, n=value)


def _perday_text(n, lang: str = "uz") -> str:
    """'kuniga <b>40</b> ta' yoki (999+) '<b>cheksiz</b>'."""
    try:
        value = int(n)
    except (TypeError, ValueError):
        return str(n)
    if value >= UNLIMITED_LIMIT:
        return f"<b>{get_text('tl_unlimited', lang)}</b>"
    return get_text("tl_perday", lang, n=value)


def tier_limit_lines(limit_key: str, lang: str = "uz") -> list:
    """Tarif imkoniyatlari ro'yxati (HAQIQIY limitlar ``config.TIER_LIMITS`` dan; va'da qilinmagan narsa yo'q).

    ``limit_key``: 'free' | 'pro' | 'ultra' | 'pro_legacy' | 'enterprise'.
    """
    lim = TIER_LIMITS.get(limit_key) or TIER_LIMITS["free"]
    lines = [
        get_text("tl_channels", lang, n=_cap_text(lim["max_channels"], lang)),
        get_text("tl_ai", lang, n=_perday_text(lim["daily_ai_requests"], lang)),
        get_text("tl_queue", lang, n=_cap_text(lim["queued_posts"], lang)),
    ]
    if limit_key != "free":
        lines.append(get_text("tl_voice", lang, n=_perday_text(lim["voice_daily"], lang)))
        lines.append(get_text("tl_plans", lang))
        lines.append(get_text("tl_nosig", lang))
    if limit_key in (PLAN_ULTRA, "enterprise"):
        lines.append(get_text("tl_usage", lang))
    return lines


def pro_card_benefits_text(lang: str = "uz", plan_key: str = "1m") -> str:
    """To'lov ekrani uchun tanlangan tarif imkoniyatlari bloki (to'lovdan oldin; limitlar config'dan)."""
    tier = tier_of_key(plan_key)
    return "\n".join([get_text(f"tier_title_{tier}", lang), *tier_limit_lines(tier, lang)])


def _period_label(plan_key: str, lang: str = "uz") -> str:
    """'u3m' -> '3 oy' / '3 месяца' / '3 months'."""
    return get_text(f"period_{(TARIFF_CATALOG.get(plan_key) or TARIFF_CATALOG['1m'])['period']}", lang)


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
    """'u3m' -> 'ULTRA — 3 oy' (tarif NOMI, narxsiz)."""
    plan_key = plan_key if plan_key in TARIFF_CATALOG else "1m"
    return f"{_TIER_NAME[tier_of_key(plan_key)]} — {_period_label(plan_key, lang)}"


def _card_tariff_label(plan_key: str, lang: str = "uz") -> str:
    """Tarif tugmasi yorlig'i: '3 oy — 49 000 so'm' (davr + narx; tarif darajasi ekran sarlavhasida)."""
    plan = CARD_TARIFFS.get(plan_key) or CARD_TARIFFS["1m"]
    return get_text("tariff_btn_tpl", lang, period=_period_label(plan_key, lang), uzs=_fmt_uzs(plan["amount"]))


def _plan_key_for_days(days, tier: str = PLAN_PRO) -> str:
    """Berilgan kunlar uchun mos plan kalitini qaytaradi ('1m' default)."""
    return key_for_days(tier, days)


# ---------------------------------------------------------------------------
# 🌍 TO'LOV MINTAQASI (payment region) — HUDUDIY TANLOV, TILGA BOG'LIQ EMAS
# ---------------------------------------------------------------------------
# Foydalanuvchi tarifni tanlaganda to'lov rekvizitlari TO'G'RIdan-TO'G'RI
# ko'rsatilmaydi: avval ikkita mintaqa tugmasi chiqadi:
#   🇺🇿 PAYMENT_REGION_UZ   → mahalliy kartalar (Uzcard / Humo, so'm);
#   🌍 PAYMENT_REGION_INTL  → xalqaro usullar (Stars / Crypto / Card, $ ~).
# Tanlov tilga bog'liq emas — RU/EN foydalanuvchi ham Uzcard/Humo tanlaydi,
# UZ foydalanuvchi ham Stars. `context.user_data` kalitlari:
USERDATA_PAY_REGION = "pay_region"       # 'uz' | 'intl'
USERDATA_PENDING_PLAN = "pending_plan"   # '1m' | '3m' | '1y' | None

# Xalqaro ekvivalent narxlar (Stars + AQSH dollariga taxminan moslama).
INTL_STARS_AMOUNTS = {k: int(info["stars"]) for k, info in TARIFF_CATALOG.items()}
INTL_USD_EQUIV = {k: str(info["usd"]) for k, info in TARIFF_CATALOG.items()}


def _remember_payment_choice(context, region=None, plan_key=None) -> None:
    """Mintaqa/tarif tanlovini FSM-kontekstga yozadi (bo'sh user_data ham xavfsiz)."""
    ud = getattr(context, "user_data", None)
    if ud is None:
        return
    if region is not None:
        ud[USERDATA_PAY_REGION] = region
    if plan_key is not None:
        if plan_key:
            ud[USERDATA_PENDING_PLAN] = plan_key
        else:
            ud.pop(USERDATA_PENDING_PLAN, None)


def _clear_payment_choice(context) -> None:
    """Orqaga qaytishda mintaqa/tarif tanlovini tozalaydi."""
    ud = getattr(context, "user_data", None)
    if ud is None:
        return
    ud.pop(USERDATA_PAY_REGION, None)
    ud.pop(USERDATA_PENDING_PLAN, None)


def _get_payment_region(context) -> str:
    """Kontekstdagi tanlangan mintaqa ('uz' | 'intl' | '')."""
    ud = getattr(context, "user_data", None) or {}
    region = str(ud.get(USERDATA_PAY_REGION) or "")
    return region if is_payment_region(region) else ""


def _get_pending_plan(context) -> str:
    """Kontekstdagi kutilayotgan tarif ('1m'|'3m'|'1y') yoki ''."""
    ud = getattr(context, "user_data", None) or {}
    plan_key = str(ud.get(USERDATA_PENDING_PLAN) or "")
    return plan_key if plan_key in CARD_TARIFFS else ""


async def _user_region(user_id: int, lang: str = "") -> str:
    """Narx mintaqasi — TILGA BOG'LIQ EMAS: so'm ('uz') faqat tasdiqlangan O'zbekiston foydalanuvchisiga, qolganlarga dollar ('intl').

    Tilni istalgan odam almashtira oladi, shuning uchun u mintaqani belgilamaydi. ``lang`` faqat eski chaqiruvlar mosligi uchun.
    """
    try:
        region = await db.run_db(db.get_pay_region, user_id)
    except Exception as _silent_exc:  # noqa: BLE001
        log_silent_failure("handlers.subscription:_user_region", _silent_exc, user_id=user_id)
        region = ""
    return PAYMENT_REGION_UZ if region == PAYMENT_REGION_UZ else PAYMENT_REGION_INTL


async def _pay_ctx(user_id: int) -> tuple:
    """(region, so'm almashtirgich ko'rsatilsinmi): telefoni boshqa davlatniki deb tasdiqlangan foydalanuvchiga so'm taklif qilinmaydi."""
    try:
        profile = await db.run_db(db.get_pay_profile, user_id) or {}
    except Exception as _silent_exc:  # noqa: BLE001
        log_silent_failure("handlers.subscription:_pay_ctx", _silent_exc, user_id=user_id)
        profile = {}
    region = PAYMENT_REGION_UZ if profile.get("region") == PAYMENT_REGION_UZ else PAYMENT_REGION_INTL
    show_uz_toggle = not (profile.get("phone_verified") and not profile.get("uz_eligible"))
    return region, show_uz_toggle


async def _ask_verify(message, context, tier: str, lang: str, purpose: str = "uz") -> None:
    """Telefon tasdiqlashni so'raydi (``handlers.phone_verify``); tarif kartasiga qaytish uchun ``tier`` eslab qolinadi."""
    from handlers.phone_verify import ask_phone_verification

    await ask_phone_verification(message, context, lang, purpose=purpose, tier=tier)


async def _purchase_gate(query, context, user_id: int, lang: str, plan_key: str) -> bool:
    """Tarif sotib olishdan oldin telefon (mamlakat) tasdiqlanishi SHART (kirishda emas, faqat xarid paytida).

    ``True`` — o'tsin; ``False`` — tasdiqlash so'raldi (chaqiruvchi to'xtaydi).
    """
    from handlers.phone_verify import PURPOSE_BUY, is_phone_verified

    if await is_phone_verified(user_id):
        return True
    await _ask_verify(query.message, context, tier_of_key(plan_key), lang, PURPOSE_BUY)
    return False


def _usd_text(plan_key: str) -> str:
    """Tarifning xalqaro dollar narxi: '$3.90'."""
    return f"${(TARIFF_CATALOG.get(plan_key) or TARIFF_CATALOG['1m'])['usd']}"


def _plan_price_text(plan_key: str, region: str) -> str:
    """Narx matni mintaqaga qarab: UZ -> '29 000 so'm' (tilga mos birlik), xalqaro -> '$3.90'."""
    if region == PAYMENT_REGION_INTL:
        return _usd_text(plan_key)
    return _fmt_uzs((TARIFF_CATALOG.get(plan_key) or TARIFF_CATALOG["1m"])["uzs"])


def _build_pay_region_text(lang: str = "uz", plan_key: str = "") -> str:
    """Mintaqa tanlash ekrani matni (kerak bo'lsa tanlangan tarif bilan)."""
    parts = [get_text("pay_region_title", lang)]
    if plan_key and plan_key in CARD_TARIFFS:
        parts.append("")
        parts.append(
            get_text("pay_region_selected", lang, tarif=_card_tariff_name(plan_key, lang))
        )
    return "\n".join(parts)


def _build_intl_payment_text(lang: str = "uz", plan_key: str = "1m") -> str:
    """🌍 Xalqaro to'lov ekrani: ekvivalent valyuta (Stars / ~$) ko'rsatiladi.

    BU EKRANDA Uzcard / Humo rekvizitlari butunlay YO'Q — xalqaro mintaqa
    tanlangan foydalanuvchi mahalliy kartalarni umuman ko'rmaydi.
    """
    plan_key = plan_key if plan_key in CARD_TARIFFS else "1m"
    admin_ref = (
        f"@{html_escape(PAYMENT_ADMIN_USERNAME)}" if PAYMENT_ADMIN_USERNAME
        else get_text("card_payment_admin_missing", lang)
    )
    parts = [
        get_text("intl_payment_title", lang),
        "",
        get_text(
            "intl_payment_selected", lang,
            tarif=_card_tariff_name(plan_key, lang),
            stars=INTL_STARS_AMOUNTS[plan_key],
            usd=INTL_USD_EQUIV[plan_key],
        ),
        "",
        get_text("intl_payment_hint", lang, admin=admin_ref),
    ]
    return "\n".join(parts)


def _get_intl_payment_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Xalqaro ekran: orqaga — mintaqa tanlash menyusiga (region almashtirish)."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(get_text("btn_back", lang), callback_data=CB_PAY_REGION)
    ]])


async def _send_stars_invoice(
    context, chat_id: int, user_id: int, plan_suffix: str, lang: str = "uz"
) -> bool:
    """Telegram Stars (XTR) invoice'ini yuboradi. Muvaffaqiyat → True.

    Payload formati o'zgarmagan: ``sub_stars_<plan>_<user_id>`` —
    precheckout/successful_payment validatorlari shu formatni kutadi.
    """
    plan_stars = INTL_STARS_AMOUNTS.get(plan_suffix)
    if plan_stars is None:
        return False
    tier = tier_of_key(plan_suffix)
    lim = TIER_LIMITS[tier]
    title = get_text("sub_inv_title_tpl", lang, tier=_TIER_NAME[tier], period=_period_label(plan_suffix, lang))[:32]
    desc = get_text("sub_inv_desc_tpl", lang, tier=_TIER_NAME[tier], period=_period_label(plan_suffix, lang),
                    ch=lim["max_channels"], ai=lim["daily_ai_requests"], q=lim["queued_posts"])[:255]
    prices = [LabeledPrice(label=title, amount=plan_stars)]
    try:
        # Telegram Stars (XTR) uchun provider_token talab qilinmaydi,
        # lekin PTB 21.x da bo'sh satr (provider_token="") uzatilishi
        # talab etiladi — None qiymat ba'zi PTB versiyalarida so'rovdan
        # tashlab qo'yilib, Telegram Stars invoice'ni ocholmay qoladi.
        await context.bot.send_invoice(
            chat_id=chat_id,
            title=title,
            description=desc,
            payload=f"sub_stars_{plan_suffix}_{user_id}",
            provider_token="",
            currency="XTR",
            prices=prices,
            start_parameter="pro-sub",
        )
        return True
    except Exception as e:
        logger.warning("Invoice yaratish xatosi: %s", e)
        return False


async def _edit_or_reply(query, text: str, markup: InlineKeyboardMarkup) -> None:
    """Xabarni edit qiladi; imkon bo'lmasa yangi xabar yuboradi (eski uslub)."""
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        try:
            await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception as _silent_exc:
            log_silent_failure("handlers.subscription:_edit_or_reply", _silent_exc)


async def _show_local_card_payment(query, context, user_id: int, lang: str, plan_key: str) -> None:
    """🇺🇿 Mahalliy to'lov ekrani — FAQAT Uzcard / Humo rekvizitlari va so'm.

    Bu funksiya mintaqa 'uz' tanlanganligi TASDIqlangandan keyin chaqiriladi
    (yoki '💳 Karta orqali to'lov' tugmasi orqali — u o'zi mahalliy tanlov).
    """
    plan_key = plan_key if plan_key in CARD_TARIFFS else "1m"
    if not await _purchase_gate(query, context, user_id, lang, plan_key):
        return
    try:
        eligible = await db.run_db(db.is_uz_eligible, user_id)
    except Exception as _silent_exc:  # noqa: BLE001
        log_silent_failure("handlers.subscription:_show_local_card_payment", _silent_exc, user_id=user_id)
        eligible = False
    if not eligible:
        # So'mdagi (arzon) to'lov rekvizitlari FAQAT tasdiqlangan O'zbekiston foydalanuvchisiga; qolganlar uchun dollar/Stars.
        await _ask_verify(query.message, context, tier_of_key(plan_key), lang)
        return
    plan = CARD_TARIFFS[plan_key]
    order_id = await db.run_db(
        db.create_payment_order, user_id, plan_key, plan["days"], plan["amount"], "UZS",
    )
    ud = getattr(context, "user_data", None)
    if ud is not None:
        ud["card_plan"] = plan_key
        if order_id:
            ud["card_order_id"] = order_id
    text = _build_card_payment_text(user_id, lang, plan_key)
    payme_url = await _payme_checkout_url(user_id, lang, plan_key)
    markup = _get_card_payment_keyboard(lang, plan_key, payme_url=payme_url)
    await _edit_or_reply(query, text, markup)


async def _payme_checkout_url(user_id: int, lang: str, plan_key: str) -> str | None:
    """⚡️ Payme avtomatik to'lov havolasi (faqat PAYME_MERCHANT_ID + PAYME_KEY bo'lsa).

    Har safar YANGI bir martalik buyurtma yaratiladi (``payme_orders``) —
    to'lov Payme callback'i orqali avtomatik tasdiqlanadi va PRO darhol
    faollashadi (admin chekni ko'rishi shart emas). Sozlanmagan yoki DB
    xatosida ``None`` — ekran avvalgidek (karta + chek) ishlayveradi.
    """
    try:
        from services.payments.payme_provider import PaymeConfig, build_checkout_url
        config = PaymeConfig.from_env()
        if not config.checkout_enabled:
            return None
        from repositories.payme_repository import create_payme_order
        plan_key = plan_key if plan_key in CARD_TARIFFS else "1m"
        plan = CARD_TARIFFS[plan_key]
        order = await db.run_db(
            create_payme_order, user_id, plan_key, plan["days"], plan["amount"],
        )
        if order is None:
            return None
        bot_username = str(BOT_USERNAME or "").strip().lstrip("@")
        return build_checkout_url(
            config, order, lang=lang,
            return_url=f"https://t.me/{bot_username}" if bot_username else None,
        )
    except Exception as _silent_exc:
        log_silent_failure("handlers.subscription:_payme_checkout_url", _silent_exc, user_id=user_id)
        return None


async def _show_intl_payment(query, context, user_id: int, lang: str, plan_key: str) -> None:
    """🌍 Xalqaro oqim — Stars/Crypto/Card (~$ yoki Stars). Uzcard/Humo YO'Q.

    ``plan_key`` bo'sh bo'lsa Stars tarif tanlagichi ko'rsatiladi; tanlangan
    bo'lsa Telegram Stars invoice'si yuboriladi va xalqaro to'lov ekrani
    chiziladi. Invoice xatosida eski ``sub_invoice_error`` xabari qaytadi.
    """
    if plan_key not in CARD_TARIFFS:
        # 🌍 Tarif hali tanlanmagan — faqat xalqaro paketlar ro'yxati.
        text = get_text("intl_payment_title", lang)
        markup = get_intl_tariffs_keyboard(lang)
        await _edit_or_reply(query, text, markup)
        return
    if not await _purchase_gate(query, context, user_id, lang, plan_key):
        return

    chat_id = getattr(getattr(query, "message", None), "chat_id", None)
    if chat_id is None:
        chat_id = user_id
    ok = await _send_stars_invoice(context, chat_id, user_id, plan_key, lang)
    if not ok:
        try:
            await query.message.reply_text(get_text("sub_invoice_error", lang))
        except Exception as _silent_exc:
            log_silent_failure("handlers.subscription:_show_intl_payment", _silent_exc, user_id=user_id, lang=lang)
        return
    # Tanlov bajarildi — kutilayotgan tarifni tozalaymiz.
    _remember_payment_choice(context, PAYMENT_REGION_INTL, "")
    text = _build_intl_payment_text(lang, plan_key)
    markup = _get_intl_payment_keyboard(lang)
    await _edit_or_reply(query, text, markup)


# Limit xabarlari
LIMIT_CHANNEL_MSG = (
    "🚫 <b>Kanal limiti tugadi!</b>\n\n"
    "Sizda hozir <b>{current}/{max}</b> ta kanal ulangan.\n"
    "Tarifingiz bo'yicha maksimal <b>{max}</b> ta kanal ulash mumkin.\n\n"
    "⭐️ Ko'proq kanal uchun tarifni yangilang: PRO (10 tagacha) yoki ULTRA (30 tagacha)."
)

LIMIT_AI_MSG = (
    "🚫 <b>Kunlik AI limiti tugadi!</b>\n\n"
    "Bugun <b>{used}/{max}</b> ta AI so'rovi ishlatildi.\n"
    "Tarifingiz bo'yicha kuniga maksimal <b>{max}</b> ta AI so'rovi.\n\n"
    "⭐️ Limit ertaga yangilanadi. Ko'proq uchun tarifni yangilang: PRO yoki ULTRA."
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


def _limit_key_for(plan_info: dict) -> str:
    """Obuna ma'lumotidan limit kaliti: eski (tarif yangilanishidan oldin to'langan) PRO muddati 'pro_legacy'."""
    plan = plan_info.get("plan_type", "free")
    if plan != "pro":
        return plan if plan in TIER_LIMITS else "free"
    legacy = plan_info.get("legacy_until")
    expires = plan_info.get("expires_at")
    now = datetime.now(timezone.utc)
    try:
        if legacy is not None and getattr(legacy, "tzinfo", None) is None:
            legacy = legacy.replace(tzinfo=timezone.utc)
        if expires is None or (legacy is not None and legacy > now):
            return "pro_legacy"
    except Exception:  # noqa: BLE001
        pass
    return "pro"


def _price_with_unit(plan_key: str, region: str, lang: str) -> str:
    """Kartadagi qisqa narx: UZ -> '29 000 so\'m' (til birligi bilan), xalqaro -> '$3.90'."""
    if region == PAYMENT_REGION_INTL:
        return _usd_text(plan_key)
    return get_text("price_uzs_tpl", lang, uzs=_fmt_uzs(TARIFF_CATALOG[plan_key]["uzs"]))


def _tier_price_lines(tier: str, lang: str, region: str = PAYMENT_REGION_UZ) -> list:
    """Tarifning 4 muddati: mintaqaga qarab narx (UZ: so'm; xalqaro: dollar + Stars) va 1 oylikka nisbatan HAQIQIY tejam foizi."""
    keys = tariff_keys_for(tier)
    monthly = TARIFF_CATALOG[keys[0]]
    lines = []
    for key in keys:
        info = TARIFF_CATALOG[key]
        if region == PAYMENT_REGION_INTL:
            pct = plan_discount_percent(info["stars"], monthly["stars"], info["months"]) if info["months"] > 1 else 0
            lines.append(get_text(
                "tier_price_line_usd", lang, period=_period_label(key, lang), usd=info["usd"],
                stars=info["stars"], save=f" (−{pct}%)" if pct > 0 else "",
            ))
        else:
            pct = plan_discount_percent(info["uzs"], monthly["uzs"], info["months"]) if info["months"] > 1 else 0
            lines.append(get_text(
                "tier_price_line_uz", lang, period=_period_label(key, lang), uzs=_fmt_uzs(info["uzs"]),
                save=f" (−{pct}%)" if pct > 0 else "",
            ))
    return lines


def _build_tier_card(tier: str, lang: str = "uz", region: str = PAYMENT_REGION_UZ) -> str:
    """Tarif tanlangach ko'rsatiladigan to'liq karta: kimlar uchun, imkoniyatlar, narxlar, shartlar (to'lovdan OLDIN)."""
    parts = [
        get_text(f"tier_title_{tier}", lang),
        get_text(f"tier_audience_{tier}", lang),
        "",
        *tier_limit_lines(tier, lang),
        "",
        get_text("tier_prices_head_usd" if region == PAYMENT_REGION_INTL else "tier_prices_head_uz", lang),
        *_tier_price_lines(tier, lang, region),
        get_text("tier_region_note_usd" if region == PAYMENT_REGION_INTL else "tier_region_note_uz", lang),
        "",
        get_text("tier_terms", lang),
        "",
        get_text("tier_pick_period", lang),
    ]
    return "\n".join(parts)


def _build_subscription_card(plan_info: dict, lang: str = "uz", region: str = PAYMENT_REGION_UZ) -> str:
    """Obuna holati kartasi: tarif nomi, tugash sanasi, HAQIQIY limitlar va keyingi tarifga o'tish (uz/ru/en)."""
    plan = plan_info.get("plan_type", "free")
    if plan not in _TIER_NAME:
        plan = "free"
    expires = plan_info.get("expires_at")
    ai_used = plan_info.get("ai_used", 0)
    limit_key = _limit_key_for(plan_info)
    lim = TIER_LIMITS.get(limit_key) or TIER_LIMITS["free"]

    lines = [
        get_text("plan_card_head", lang, emoji=_TIER_EMOJI.get(plan, "🆓"), name=_TIER_NAME[plan]),
        "━━━━━━━━━━━━━━━━━",
    ]
    if plan != "free":
        lines.append(get_text("plan_card_expires", lang, when=_format_expires(expires, lang)))
    limit_lines = tier_limit_lines(limit_key, lang)
    lines.extend([limit_lines[0], limit_lines[2]])  # kanallar, navbat (AI — quyida, sarf bilan)
    lines.append(get_text("plan_card_ai_used", lang, used=ai_used, max=_fmt_limit(lim["daily_ai_requests"], lang)))
    lines.append("━━━━━━━━━━━━━━━━━")
    if limit_key == "pro_legacy" and plan_info.get("legacy_until") is not None:
        lines.append(get_text("plan_card_legacy", lang, until=_format_expires(plan_info.get("legacy_until"), lang)))
    ctx = dict(
        pro_price=_price_with_unit("1m", region, lang), ultra_price=_price_with_unit("u1m", region, lang),
        pro_ch=TIER_LIMITS[PLAN_PRO]["max_channels"], pro_ai=TIER_LIMITS[PLAN_PRO]["daily_ai_requests"],
        ultra_ch=TIER_LIMITS[PLAN_ULTRA]["max_channels"], ultra_ai=TIER_LIMITS[PLAN_ULTRA]["daily_ai_requests"],
        ultra_q=TIER_LIMITS[PLAN_ULTRA]["queued_posts"],
        ultra_team=TIER_LIMITS[PLAN_ULTRA].get("team_seats", 0), ultra_accounts=TIER_LIMITS[PLAN_ULTRA].get("team_seats", 0) + 1,
    )
    if plan == "free":
        lines.extend(["", get_text("plan_card_upsell_free", lang, **ctx)])
    elif plan == PLAN_PRO:
        lines.extend(["", get_text("plan_card_upsell_pro", lang, **ctx)])
    lines.extend(["", get_text("plan_card_help", lang)])
    return "\n".join(lines)


def _get_subscription_keyboard(plan: str, lang: str = "uz") -> InlineKeyboardMarkup:
    """Obuna sahifasi tugmalari: tarif tanlash (PRO / ULTRA), tarix, promo-kod.

    Faol ULTRA / Enterprise foydalanuvchiga PRO sotib olish tugmasi ko'rsatilmaydi (to'langan yuqori tarif pasaymasligi uchun);
    Enterprise (muddatsiz) uchun sotib olish tugmalari umuman yo'q.
    """
    keyboard = []
    tier_row = []
    if plan in ("free", PLAN_PRO):
        tier_row.append(InlineKeyboardButton(get_text("btn_tier_pro", lang), callback_data=cb(f"sub_tier:{PLAN_PRO}")))
    if plan in ("free", PLAN_PRO, PLAN_ULTRA):
        tier_row.append(InlineKeyboardButton(get_text("btn_tier_ultra", lang), callback_data=cb(f"sub_tier:{PLAN_ULTRA}")))
    if tier_row:
        keyboard.append(tier_row)
    # Billing history belongs in the PRO hub, not in the primary settings grid.
    from translations import settings_stats_t

    keyboard.append([
        InlineKeyboardButton(settings_stats_t("ss_btn_payments", lang),
                             callback_data="sub_history")
    ])
    keyboard.append([
        InlineKeyboardButton(get_text("sub_btn_promo", lang), callback_data="sub_promo")
    ])
    keyboard.append([
        InlineKeyboardButton(get_text("btn_back", lang), callback_data="sub_back_main")
    ])
    return InlineKeyboardMarkup(keyboard)


def _get_tier_keyboard(tier: str, lang: str = "uz", region: str = PAYMENT_REGION_UZ, show_uz_toggle: bool = True) -> InlineKeyboardMarkup:
    """Tanlangan tarifning 4 muddati (mintaqaga qarab so'm/dollar; har biri -> to'lov) + mintaqa almashtirish + orqaga."""
    keyboard = []
    for key in tariff_keys_for(tier):
        if region == PAYMENT_REGION_INTL:
            label = get_text("tariff_btn_usd_tpl", lang, period=_period_label(key, lang), usd=TARIFF_CATALOG[key]["usd"])
        else:
            label = _card_tariff_label(key, lang)
        keyboard.append([InlineKeyboardButton(label, callback_data=cb(f"sub_pay:{TARIFF_CATALOG[key]['stars_key']}"))])
    if region == PAYMENT_REGION_INTL:  # so'm: tasdiqlangan O'zbekiston foydalanuvchisi yoki +998 tasdiqlash
        if show_uz_toggle:
            keyboard.append([InlineKeyboardButton(get_text("btn_region_uzs", lang), callback_data=cb("sub_setreg", PAYMENT_REGION_UZ, tier))])
    else:
        keyboard.append([InlineKeyboardButton(get_text("btn_region_usd", lang), callback_data=cb("sub_setreg", PAYMENT_REGION_INTL, tier))])
    keyboard.append([InlineKeyboardButton(get_text("btn_back", lang), callback_data="sub_back")])
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
        # To'lovdan OLDIN — to'liq PRO afzalliklari (nima uchun to'lashi aniq).
        pro_card_benefits_text(lang, plan_key),
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


def _get_card_tariffs_keyboard(
    lang: str = "uz", back_cb: str = "sub_back", tier: str = PLAN_PRO
) -> InlineKeyboardMarkup:
    """💳 Karta to'lovi uchun TARIF TANLASH klaviaturasi (1m/3m/1y + orqaga).

    ``back_cb`` — orqa tugma callback'i. Mintaqa oqimida u ``sub_region``ga
    qo'yiladi (foydalanuvchi mintaqani almashtira olishi uchun), standart —
    obuna kartasiga (``sub_back``).
    """
    keyboard = []
    for key in tariff_keys_for(tier):
        keyboard.append([
            InlineKeyboardButton(
                _card_tariff_label(key, lang), callback_data=cb(f"sub_tarif:{key}")
            )
        ])
    keyboard.append([
        InlineKeyboardButton(get_text("btn_back", lang), callback_data=back_cb)
    ])
    return InlineKeyboardMarkup(keyboard)


def _get_card_payment_keyboard(
    lang: str = "uz", plan_key: str = "1m", payme_url: str | None = None
) -> InlineKeyboardMarkup:
    keyboard = []
    # ⚡️ Payme (avtomatik) — faqat sozlangan bo'lsa; qo'lda chek oqimi saqlanadi.
    if payme_url:
        keyboard.append([
            InlineKeyboardButton(get_text("btn_pay_payme", lang), url=payme_url)
        ])
    # 📸 Bot tugmasi: foydalanuvchi chekni to'g'ridan-to'g'ri botga yuboradi va
    # u Admin Approval Flow orqali barcha adminlarga yetkaziladi.
    keyboard.append([
        InlineKeyboardButton(get_text("btn_send_receipt", lang), callback_data="sub_send_receipt")
    ])
    if PAYMENT_ADMIN_USERNAME:
        keyboard.append([InlineKeyboardButton(
            get_text("sub_btn_send_receipt_admin", lang),
            url=f"https://t.me/{PAYMENT_ADMIN_USERNAME}",
        )])
    keyboard.append([InlineKeyboardButton(get_text("btn_back", lang), callback_data="sub_back")])
    return InlineKeyboardMarkup(keyboard)


async def start_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Premium / Tariflar bo'limini boshlash."""
    user_id = update.effective_user.id
    lang = await ensure_user_lang(context, user_id)
    plan_info = await db.run_db(db.get_user_plan, user_id)
    card = _build_subscription_card(plan_info, lang, await _user_region(user_id, lang))
    plan = plan_info.get("plan_type", "free")

    await update.message.reply_text(
        card,
        reply_markup=_get_subscription_keyboard(plan, lang),
        parse_mode="HTML",
    )
    return SUBSCRIPTION_VIEW


async def send_subscription_card(message, context, user_id: int, lang: str) -> None:
    """PRO/ULTRA obuna kartasini yangi xabar sifatida yuboradi (``sub_open`` tugmasi va Mini App deep-link ``go_plans``)."""
    plan_info = await db.run_db(db.get_user_plan, user_id)
    card = _build_subscription_card(plan_info, lang, await _user_region(user_id, lang))
    plan = plan_info.get("plan_type", "free")
    try:
        await message.reply_text(
            card,
            reply_markup=_get_subscription_keyboard(plan, get_lang(context)),
            parse_mode="HTML",
        )
    except Exception as _silent_exc:
        log_silent_failure("handlers.subscription:send_subscription_card", _silent_exc)


async def subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obuna sahifasi tugmalari."""
    query = update.callback_query
    # ENG BIRINCHI QATORDI — har bir callback darhol answer() oladi, aks holda
    # Telegram tugmani "yuklanmoqda" holatida qoldiradi (tugma qotib qoladi),
    # ayniqsa send_invoice sekin ishlasa yoki xatolik bersa.
    try:
        await query.answer()
    except Exception as _silent_exc:
        log_silent_failure("handlers.subscription:subscription_callback:620", _silent_exc)

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
        # Chiqishda mintaqa/tarif tanlovini ham tozalaymiz.
        _clear_payment_choice(context)
        # Xabarni o'chirib, asosiy menyuni yuboramiz
        try:
            await query.message.delete()
        except Exception as _silent_exc:
            log_silent_failure("handlers.subscription:subscription_callback:646", _silent_exc)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=get_text("main_menu_hint", lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
        )
        return ConversationHandler.END

    if data == "sub_open":
        # Tarif limiti / reklama tugmasi orqali '⭐️ PRO tarifga o'tish' —
        # obuna kartasini ko'rsatadi.
        await send_subscription_card(query.message, context, user_id, lang)
        return SUBSCRIPTION_VIEW

    if data == "sub_history":
        # Billing history is a natural child of PRO & Tariffs and returns to
        # this same hub rather than back to the generic settings grid.
        from handlers.settings import _render_payments

        await _render_payments(query, user_id, lang, back_callback="sub_back")
        return SUBSCRIPTION_VIEW

    if data.startswith("sub_pay:"):
        # ⛔️ Rekvizitlar/DARHOL invoice ENDI YO'Q: tarif tanlangach avval
        # to'lov MINTAQASI so'raladi (🇺🇿 O'zbekiston / 🌍 Xalqaro). Bu tanlov
        # tilga bog'liq emas — RU/EN foydalanuvchi ham Uzcard/Humo tanlaydi.
        plan_key = data.split(":", 1)[1]
        # plan_key: stars_1m | stars_3m | stars_1y → tarif '1m'|'3m'|'1y'.
        plan_suffix = plan_key.split("_", 1)[1] if "_" in plan_key else ""
        if plan_suffix not in CARD_TARIFFS:
            await query.message.reply_text(get_text("sub_invalid_plan", lang))
            return SUBSCRIPTION_VIEW

        # To'lov oqimi TILGA BOG'LIQ EMAS: tasdiqlangan O'zbekiston foydalanuvchisi — so'm (karta/Payme), qolganlar — dollar (Stars).
        if await _user_region(user_id) == PAYMENT_REGION_UZ:
            _remember_payment_choice(context, PAYMENT_REGION_UZ, plan_suffix)
            await _show_local_card_payment(query, context, user_id, lang, plan_suffix)
        else:
            _remember_payment_choice(context, PAYMENT_REGION_INTL, plan_suffix)
            await _show_intl_payment(query, context, user_id, lang, plan_suffix)
        return SUBSCRIPTION_VIEW

    if data == CB_PAY_REGION or data.startswith(f"{CB_PAY_REGION}:"):
        # 🌍 Mintaqa tanlandi (yoki menyu qayta so'raldi):
        #   sub_region            → menyusini ko'rsatish
        #   sub_region:uz[:plan]  → mahalliy oqim (Uzcard/Humo, so'm)
        #   sub_region:intl[:plan]→ xalqaro oqim (Stars/Crypto, ~$)
        region, plan_key = payment_region_from_callback(data)
        if not plan_key:
            plan_key = _get_pending_plan(context)
        if region not in (PAYMENT_REGION_UZ, PAYMENT_REGION_INTL):
            # Noma'lum/bo'sq mintaqа tokeni — menyuni tarif eslatmasiz qayta
            # ko'rsatamiz (hech qanday rekvizit chiqmaydi).
            text = _build_pay_region_text(lang, plan_key)
            markup = get_payment_region_keyboard(lang, plan_key or None)
            await _edit_or_reply(query, text, markup)
            return SUBSCRIPTION_VIEW

        try:  # tanlov saqlanadi; 'uz' faqat tasdiqlangan foydalanuvchiga (aks holda False)
            saved = await db.run_db(db.set_pay_region, user_id, region)
        except Exception as _silent_exc:  # noqa: BLE001
            log_silent_failure("handlers.subscription:sub_region_save", _silent_exc, user_id=user_id)
            saved = False
        if region == PAYMENT_REGION_UZ and not saved:
            await _ask_verify(query.message, context, tier_of_key(plan_key or "1m"), lang)
            return SUBSCRIPTION_VIEW

        if region == PAYMENT_REGION_UZ:
            _remember_payment_choice(context, PAYMENT_REGION_UZ, plan_key)
            if plan_key in CARD_TARIFFS:
                await _show_local_card_payment(
                    query, context, user_id, lang, plan_key
                )
            else:
                # 🇺🇿 Faqat mahalliy usullar: so'mdagi narxlar bilan tarif
                # tanlash (Uzcard / Humo). Xalqaro Stars tugmalari yo'q.
                text = get_text("card_tariff_title", lang)
                markup = _get_card_tariffs_keyboard(lang, back_cb=CB_PAY_REGION)
                await _edit_or_reply(query, text, markup)
            return SUBSCRIPTION_VIEW

        # 🌍 Xalqaro: Uzcard / Humo BUTUNLAY yashirilgan.
        _remember_payment_choice(context, PAYMENT_REGION_INTL, plan_key)
        await _show_intl_payment(query, context, user_id, lang, plan_key)
        return SUBSCRIPTION_VIEW

    if data.startswith(f"{CB_PAY_INTL_PLAN}:"):
        # 🌍 Xalqaro tarif tanlagichidagi bosish — invoice + xalqaro ekran.
        plan_key = data.split(":", 1)[1]
        if plan_key not in CARD_TARIFFS:
            await query.message.reply_text(get_text("sub_invalid_plan", lang))
            return SUBSCRIPTION_VIEW
        _remember_payment_choice(context, PAYMENT_REGION_INTL, plan_key)
        await _show_intl_payment(query, context, user_id, lang, plan_key)
        return SUBSCRIPTION_VIEW

    if data.startswith("sub_tier:"):
        # Tarif tanlandi (PRO / ULTRA): imkoniyatlar, narxlar, shartlar va 4 muddat tugmasi (to'lovdan OLDIN).
        tier = data.split(":", 1)[1]
        if tier not in (PLAN_PRO, PLAN_ULTRA):
            await query.message.reply_text(get_text("sub_invalid_plan", lang))
            return SUBSCRIPTION_VIEW
        _clear_payment_choice(context)
        region, show_uz = await _pay_ctx(user_id)
        await _edit_or_reply(query, _build_tier_card(tier, lang, region), _get_tier_keyboard(tier, lang, region, show_uz))
        return SUBSCRIPTION_VIEW

    if data.startswith("sub_setreg:"):
        # Narx mintaqasini almashtirish (🇺🇿 so'm <-> 🌍 dollar): tanlov saqlanadi va tarif kartasi qayta chiziladi.
        parts = data.split(":")
        region = parts[1] if len(parts) > 1 else ""
        tier = parts[2] if len(parts) > 2 else ""
        if region not in (PAYMENT_REGION_UZ, PAYMENT_REGION_INTL) or tier not in (PLAN_PRO, PLAN_ULTRA):
            await query.message.reply_text(get_text("sub_invalid_plan", lang))
            return SUBSCRIPTION_VIEW
        try:
            saved = await db.run_db(db.set_pay_region, user_id, region)
        except Exception as _silent_exc:  # noqa: BLE001
            log_silent_failure("handlers.subscription:sub_setreg", _silent_exc, user_id=user_id)
            saved = False
        if region == PAYMENT_REGION_UZ and not saved:
            # So'm narxi/to'lovi — faqat O'zbekiston raqami (+998) tasdiqlangandan keyin; boshqa davlat raqami bo'lsa — tushuntirish.
            _, show_uz = await _pay_ctx(user_id)
            if not show_uz:
                await query.message.reply_text(get_text("uz_only_note", lang), parse_mode="HTML")
            else:
                await _ask_verify(query.message, context, tier, lang, "uz")
            return SUBSCRIPTION_VIEW
        _clear_payment_choice(context)
        region, show_uz = await _pay_ctx(user_id)
        await _edit_or_reply(query, _build_tier_card(tier, lang, region), _get_tier_keyboard(tier, lang, region, show_uz))
        return SUBSCRIPTION_VIEW

    if data == "sub_card_pay":
        # Eski tugma (karta orqali to'lov): endi tarif va muddat avval tanlanadi — obuna kartasiga qaytamiz.
        _clear_payment_choice(context)
        plan_info = await db.run_db(db.get_user_plan, user_id)
        await _edit_or_reply(query, _build_subscription_card(plan_info, lang, await _user_region(user_id, lang)),
                             _get_subscription_keyboard(plan_info.get("plan_type", "free"), lang))
        return SUBSCRIPTION_VIEW

    if data.startswith("sub_tarif:"):
        # tarif tanlandi — LEKIN rekvizitlar faqat mintaqa tanlangan
        # bo'lsa chiqadi; mintaqa tanlanmagan bo'lsa avval 2 tugma menyusimiz.
        plan_key = data.split(":", 1)[1]
        if plan_key not in CARD_TARIFFS:
            return SUBSCRIPTION_VIEW
        if _get_payment_region(context) != PAYMENT_REGION_UZ:
            _remember_payment_choice(context, "", plan_key)
            text = _build_pay_region_text(lang, plan_key)
            markup = get_payment_region_keyboard(lang, plan_key)
            await _edit_or_reply(query, text, markup)
            return SUBSCRIPTION_VIEW
        await _show_local_card_payment(query, context, user_id, lang, plan_key)
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
        except Exception as _silent_exc:
            log_silent_failure("handlers.subscription:subscription_callback:775", _silent_exc)
        return RECEIPT_WAIT

    if data == "sub_back":
        # Obuna kartasiga qaytish — mintaqa/tarif tanlovi bekor qilinadi.
        _clear_payment_choice(context)
        plan_info = await db.run_db(db.get_user_plan, user_id)
        card = _build_subscription_card(plan_info, lang, await _user_region(user_id, lang))
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
        context.user_data[UD_PROMO_WAIT] = time.time()
        await query.message.reply_text(
            get_text(
                "sub_promo_ask", lang,
                back=get_text("btn_main_menu", lang),
            ),
            parse_mode="HTML",
        )
        return PROMO_INPUT

    if data == "sub_refresh":
        plan_info = await db.run_db(db.get_user_plan, user_id)
        card = _build_subscription_card(plan_info, lang, await _user_region(user_id, lang))
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
    lang = get_lang(context)

    if is_main_menu_text(text):
        context.user_data.pop(UD_PROMO_WAIT, None)
        # Qaytadan obuna kartasini ko'rsatamiz
        plan_info = await db.run_db(db.get_user_plan, user_id)
        card = _build_subscription_card(plan_info, lang, await _user_region(user_id, lang))
        plan = plan_info.get("plan_type", "free")
        await update.message.reply_text(
            card,
            reply_markup=_get_subscription_keyboard(plan, lang),
            parse_mode="HTML",
        )
        return SUBSCRIPTION_VIEW

    # Kod taxmin qilishga qarshi: ko'p xatodan keyin DB'ga tegmasdan rad etamiz.
    wait = promo_limiter.retry_after(user_id)
    if wait:
        await update.message.reply_text(
            get_text("sub_promo_blocked", lang, minutes=max(1, -(-wait // 60))),
            parse_mode="HTML",
        )
        return PROMO_INPUT

    success, msg = await db.run_db(db.redeem_promo_code, user_id, text)
    msg_localized = html_escape(localize_db_message(msg, lang))
    back_label = get_text("btn_main_menu", lang)

    if success:
        promo_limiter.reset(user_id)
        context.user_data.pop(UD_PROMO_WAIT, None)
        await update.message.reply_text(
            get_text("sub_promo_success", lang, msg=msg_localized),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
            parse_mode="HTML",
        )
        return ConversationHandler.END
    else:
        promo_limiter.record_failure(user_id)
        await update.message.reply_text(
            get_text("sub_promo_fail", lang, msg=msg_localized, back=back_label),
            parse_mode="HTML",
        )
        return PROMO_INPUT


def promo_wait_active(context) -> bool:
    """Foydalanuvchi «Promo-kod» tugmasini yaqinda bosganmi (kod kutilyaptimi)."""
    ts = (getattr(context, "user_data", None) or {}).get(UD_PROMO_WAIT)
    return isinstance(ts, (int, float)) and time.time() - ts < PROMO_WAIT_SECONDS


async def promo_wait_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Suhbat holati yo'qolgan bo'lsa ham, «Promo-kod»dan keyingi matnni promo sifatida qabul qiladi."""
    if not promo_wait_active(context):
        return None
    await promo_code_received(update, context)
    return None


@require_permission(PERM_MANAGE_USERS,
                    message="❌ Sizda foydalanuvchilarga PRO berish uchun ruxsat yo'q.")
async def grant_pro_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /grant_pro <user_id> <days> [pro|ultra] — foydalanuvchiga PRO (standart) yoki ULTRA berish."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS_SET and not has_permission(user_id, PERM_MANAGE_USERS):
        # 🌐 Admin bo'lmagan foydalanuvchiga tiliga mos rad javobi.
        await update.message.reply_text(
            get_text("admin_only_cmd", get_lang(context))
        )
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "📝 Foydalanish: /grant_pro <user_id> <kunlar_soni> [pro|ultra]\n"
            "Masalan: /grant_pro 123456789 30 ultra"
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
    if days > MAX_ADMIN_GRANT_DAYS:
        await update.message.reply_text(admin_t("days_too_large", get_lang(context), max=MAX_ADMIN_GRANT_DAYS))
        return
    tier = (args[2].strip().lower() if len(args) > 2 else PLAN_PRO)
    if tier not in (PLAN_PRO, PLAN_ULTRA):
        await update.message.reply_text("❌ Tarif: pro yoki ultra. Masalan: /grant_pro 123456789 30 ultra")
        return

    success = await db.run_db(db.set_user_plan, target_id, tier, days,
                              admin_id=user_id)
    if success:
        await update.message.reply_text(
            f"✅ <b>{_TIER_NAME[tier]} tarif berildi!</b>\n\n"
            f"👤 Foydalanuvchi: <code>{target_id}</code>\n"
            f"📅 Muddat: <b>{days} kun</b>",
            parse_mode="HTML",
        )
        # Foydalanuvchiga xabar berishga harakat qilamiz (o'z tilida).
        try:
            target_lang = await db.run_db(db.get_user_language, target_id)
            if tier == PLAN_PRO:
                notice = get_text("sub_pro_granted", target_lang, days=days)
            else:
                notice = await payment_success_text(target_id, tier, target_lang or "uz")
            await context.bot.send_message(chat_id=target_id, text=notice, parse_mode="HTML")
        except Exception as _silent_exc:
            log_silent_failure("handlers.subscription:grant_pro_command", _silent_exc)
    else:
        await update.message.reply_text("❌ Xatolik yuz berdi. User ID to'g'riligini tekshiring.")


# ============================================================
# TELEGRAM STARS PAYMENT HANDLERS
# ============================================================

_STARS_PAYLOAD_RE = re.compile(r"^sub_(stars_u?(?:1m|3m|6m|1y))_([0-9]+)$")


def _validate_stars_payload(payload: str, user_id: int, amount=None, currency=None,
                            lang: str = "uz"):
    """Invoice payload + summa + valuta'ni qat'iy tekshiradi.

    Payload oddiy prefix tekshiruvi bilan qabul qilinmaydi: user ID, plan va
    Telegram invoice'dagi kutilgan Stars miqdori bir-biriga mos bo'lishi shart.
    Xatolik matnlari foydalanuvchi tilida (uz/ru/en) qaytariladi.
    """
    match = _STARS_PAYLOAD_RE.fullmatch(str(payload or ""))
    if not match:
        return None, get_text("sub_pay_err_payload", lang)
    plan_key, payload_user = match.groups()
    try:
        if int(payload_user) != int(user_id):
            return None, get_text("sub_pay_err_user", lang)
    except (TypeError, ValueError):
        return None, get_text("sub_pay_err_user_id", lang)
    plan = STARS_PLANS.get(plan_key)
    if not plan:
        return None, get_text("sub_pay_err_plan", lang)
    if currency is not None and str(currency).upper() != "XTR":
        return None, get_text("sub_pay_err_currency", lang)
    if amount is not None:
        try:
            if int(amount) != int(plan["stars"]):
                return None, get_text("sub_pay_err_amount", lang)
        except (TypeError, ValueError):
            return None, get_text("sub_pay_err_amount_bad", lang)
    return {"plan_key": plan_key, "stars": plan["stars"], "days": plan["days"], "tier": plan.get("tier", PLAN_PRO)}, None


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """PreCheckoutQuery — Telegram to'lovni tasdiqlashdan oldin so'raydi.

    Eng birinchi ish — darhol javob berish (ok=True/False). Payload tekshiruvi
    sinxron, ya'ni answer() dan oldin hech qanday await yo'q.
    """
    query = update.pre_checkout_query
    if not query:
        return

    # Telegram payment retry/qo'lda yuborilgan soxta invoice'ni qat'iy rad etamiz.
    # Til keshdan sinxron olinadi — answer() dan oldin await yo'q (tezlik).
    lang = get_lang(context)
    payload = query.invoice_payload or ""
    query_user = getattr(getattr(query, "from_user", None), "id", None)
    query_amount = getattr(query, "total_amount", None)
    query_currency = getattr(query, "currency", None)
    plan, error = _validate_stars_payload(
        payload,
        query_user,
        query_amount,
        query_currency,
        lang,
    )
    if query_user is None or query_amount is None or query_currency is None:
        plan, error = None, get_text("sub_pay_err_incomplete", lang)
    await query.answer(
        ok=plan is not None,
        error_message=None if plan is not None else (
            error or get_text("sub_pay_err_bad_request", lang)
        ),
    )


@require_permission(PERM_MANAGE_PROMOS,
                    message="❌ Sizda promo-kod yaratish uchun ruxsat yo'q.")
async def create_promo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """SuperAdmin: /create_promo <KOD> <KUNLAR> <MAKS_ISHLATISH> — promo-kod yaratish."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS_SET and not has_permission(user_id, PERM_MANAGE_PROMOS):
        # 🌐 Admin bo'lmagan foydalanuvchiga tiliga mos rad javobi.
        await update.message.reply_text(
            get_text("admin_only_cmd", get_lang(context))
        )
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


_ACTIVATION_REASON_MAX = 60


def _safe_reason(reason) -> str:
    """Xato sababini logga/adminga xavfsiz qisqa ko'rinishda beradi (kod, matn emas)."""
    text = re.sub(r"[^A-Za-z0-9_.:-]", "", str(reason or ""))[:_ACTIVATION_REASON_MAX]
    return text or "unknown"


def refunded_payment_filter():
    """PTB filtri (``StatusUpdate.REFUNDED_PAYMENT``); eski PTB'da yo'q bo'lsa ``None`` (handler ulanmaydi, bot qulamaydi)."""
    from telegram.ext import filters

    return getattr(filters.StatusUpdate, "REFUNDED_PAYMENT", None)


async def refunded_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stars to'lovi qaytarilganda (``Message.refunded_payment``): to'lov ``refunded`` bo'ladi, shu to'lovning kunlari PRO'dan
    ayriladi (idempotent, muddatsiz tarifga tegilmaydi), foydalanuvchiga va adminlarga xabar ketadi. Hech qachon istisno tashlamaydi.
    """
    message = getattr(update, "message", None)
    refund = getattr(message, "refunded_payment", None)
    if refund is None:
        return
    user = getattr(update, "effective_user", None) or getattr(message, "from_user", None)
    user_id = getattr(user, "id", None)
    charge_id = str(getattr(refund, "telegram_payment_charge_id", "") or "-")
    amount = getattr(refund, "total_amount", "?")
    currency = str(getattr(refund, "currency", "") or "")
    try:
        outcome = await db.run_db(db.refund_stars_payment, charge_id)
    except Exception as exc:  # noqa: BLE001 — DB xatosi handler'ni qulatmasin; adminga baribir xabar ketadi
        log_silent_failure("handlers.subscription:stars_refund_apply", exc, user_id=user_id)
        outcome = {"result": "error", "user_id": user_id, "days": 0}
    result = str((outcome or {}).get("result") or "error")
    days = int((outcome or {}).get("days") or 0)
    logger.warning(
        "Stars to'lovi QAYTARILDI (refund): user=%s charge_id=%s summa=%s %s natija=%s kun=%s",
        user_id, charge_id, amount, currency, result, days,
    )
    bot = getattr(context, "bot", None)
    for admin_id in ADMIN_IDS_SET:
        try:
            try:
                admin_lang = await db.run_db(db.get_user_language, admin_id)
            except Exception:  # noqa: BLE001 — til aniqlanmasa uz
                admin_lang = "uz"
            lang = admin_lang or "uz"
            outcome_text = admin_t(f"stars_refund_outcome_{result}", lang, days=days)
            text = admin_t(
                "stars_refund_admin", lang,
                user_id=user_id, charge_id=html_escape(charge_id),
                amount=amount, currency=html_escape(currency), outcome=outcome_text,
            )
            await bot.send_message(chat_id=admin_id, text=text, parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001 — bitta admin xatosi boshqasini to'xtatmasin
            log_silent_failure("handlers.subscription:stars_refund_alert", exc, user_id=admin_id)
    if result == "revoked" and user_id:
        try:
            lang = await db.run_db(db.get_user_language, user_id) or "uz"
            await bot.send_message(chat_id=user_id, text=get_text("stars_refund_user", lang, days=days), parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001
            log_silent_failure("handlers.subscription:stars_refund_user_notice", exc, user_id=user_id)


async def _report_stars_activation_failure(context, user_id, charge_id, days, reason) -> None:
    """Stars to'lovi o'tgan, lekin PRO faollashmadi: log + adminlarga xabar.

    To'lov QAYTA ISHLANMAYDI (ikki marta PRO berish xavfi): faqat kuzatuv.
    Admin xabari yuborilmasa ham asosiy handler yiqilmaydi.
    """
    reason = _safe_reason(reason)
    logger.error(
        "Stars to'lovi qabul qilindi, lekin PRO faollashmadi: "
        "user=%s charge_id=%s days=%s sabab=%s",
        user_id, charge_id, days, reason,
    )
    bot = getattr(context, "bot", None)
    for admin_id in ADMIN_IDS_SET:
        try:
            try:
                admin_lang = await db.run_db(db.get_user_language, admin_id)
            except Exception:  # noqa: BLE001 — til aniqlanmasa uz
                admin_lang = "uz"
            text = admin_t(
                "stars_activation_failed_admin", admin_lang or "uz",
                user_id=user_id, charge_id=html_escape(str(charge_id)),
                days=days, reason=reason,
            )
            await bot.send_message(chat_id=admin_id, text=text, parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001 — bitta admin xatosi boshqasini to'xtatmasin
            log_silent_failure("handlers.subscription:stars_activation_alert", exc,
                               user_id=admin_id)


async def payment_success_text(user_id: int, tier: str, lang: str) -> str:
    """To'lov muvaffaqiyatli bo'lgach: tarif nomi, amal qilish muddati va ochilgan imkoniyatlar (haqiqiy holatdan)."""
    plan_info = await db.run_db(db.get_user_plan, user_id)
    if not isinstance(plan_info, dict):
        plan_info = {}
    plan = plan_info.get("plan_type") or tier
    if plan not in _TIER_NAME or plan == "free":
        plan = tier  # eski/kechikkan o'qish: ko'rsatiladigan tarif — xarid qilingani
    return get_text(
        "sub_pay_success_v2", lang, emoji=_TIER_EMOJI.get(plan, "⭐️"), name=_TIER_NAME[plan],
        when=_format_expires(plan_info.get("expires_at"), lang), limits="\n".join(tier_limit_lines(_limit_key_for(plan_info), lang)),
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
        get_lang(context),
    )
    if total_stars is None or payment_currency is None:
        plan, error = None, get_text("sub_pay_err_incomplete", get_lang(context))
    charge_id = (getattr(payment, "telegram_payment_charge_id", "") or "").strip()
    if plan is None or not charge_id:
        # To'lov Telegram tomonidan ALLAQACHON olingan (pre_checkout dan o'tgan). Bu yerda tekshiruv rad etsa
        # PRO BERILMAYDI (noto'g'ri summa/payload — qaror adminda) va refund ham boshlanmaydi, lekin
        # jim qolinmaydi: log + adminlarga ogohlantirish + foydalanuvchiga "admin bilan bog'laning" xabari (AUDIT-005).
        logger.warning(
            "Stars payment rad etildi: user=%s payload=%r charge=%r sabab=%s",
            user_id, payload, charge_id, error or "charge_id yo'q",
        )
        await _report_stars_activation_failure(
            context, user_id, charge_id or "-", "?",
            "validation_rejected" if plan is None else "missing_charge_id")
        rejected_lang = await ensure_user_lang(context, user_id)
        await update.message.reply_text(
            get_text("sub_pay_activate_error", rejected_lang),
            parse_mode="HTML",
        )
        return

    # Oldingi set_user_plan chaqiruvi o'rniga log_stars_payment audit yozuvi va
    # subscription UPDATE aynan shu
    # tranzaksiyada; bir xil charge_id qaytsa process_stars_payment duplicate
    # qaytaradi va obuna ikkinchi marta berilmaydi.
    failure_reason = None
    try:
        result = await db.run_db(
            db.process_stars_payment,
            user_id,
            plan["stars"],
            "XTR",
            payload,
            charge_id,
            plan.get("tier", PLAN_PRO),
            plan["days"],
        )
    except Exception as exc:  # noqa: BLE001 — to'lov o'tgan: jim qolmaslik kerak
        result = None
        failure_reason = type(exc).__name__
    if not isinstance(result, dict) or not result.get("ok"):
        if failure_reason is None:
            failure_reason = (result or {}).get("reason") if isinstance(result, dict) else None
        await _report_stars_activation_failure(
            context, user_id, charge_id, plan["days"], failure_reason)
    lang = await ensure_user_lang(context, user_id)
    if not isinstance(result, dict) or not result.get("ok"):
        await update.message.reply_text(
            get_text("sub_pay_activate_error", lang),
            parse_mode="HTML",
        )
        return

    if result.get("duplicate"):
        # Retry kelgan — grant allaqachon berilgan, yana subscription yozmaymiz.
        await update.message.reply_text(
            get_text("sub_pay_duplicate", lang),
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang=lang),
            parse_mode="HTML",
        )
        return

    # Telegram's recurring payment event is the source of truth for the paid
    # period's exact end; the daily/monthly day-count above remains the fallback
    # for legacy one-off invoices and API versions omitting the timestamp.
    expiration_raw = getattr(payment, "subscription_expiration_date", None)
    is_recurring = bool(getattr(payment, "is_recurring", False) or expiration_raw)
    if is_recurring:
        expiration = None
        if expiration_raw is not None:
            try:
                expiration = datetime.fromtimestamp(int(expiration_raw), tz=timezone.utc)
            except (TypeError, ValueError, OverflowError, OSError):
                logger.warning("Invalid Stars subscription expiration timestamp (user=%s)", user_id)
        try:
            await db.run_db(db.sync_stars_subscription, user_id, "active", expiration)
        except Exception:
            # Payment has already been granted atomically. Keep the receipt
            # success path intact and let the regular subscription sweep repair
            # an expired plan if this best-effort metadata sync fails.
            logger.exception("Recurring Stars subscription metadata sync failed (user=%s)", user_id)

    await update.message.reply_text(
        await payment_success_text(user_id, plan.get("tier", PLAN_PRO), lang),
        reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang=lang),
        parse_mode="HTML",
    )


async def bot_subscription_updated_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Apply Telegram's BotSubscriptionUpdated state without over-granting time.

    Telegram sends this update when a user enables/disables recurring Stars
    billing. It is distinct from a successful renewal payment: only a
    SuccessfulPayment extends expiry. Cancellation therefore stops renewal but
    retains already-paid PRO access through the stored expiration date.
    """
    subscription = getattr(update, "subscription", None)
    if subscription is None:
        # python-telegram-bot versions predating Bot API 9.2 retain unknown
        # Update fields under api_kwargs rather than as typed attributes.
        api_kwargs = getattr(update, "api_kwargs", None) or {}
        subscription = api_kwargs.get("subscription") if isinstance(api_kwargs, Mapping) else None
    if subscription is None:
        return False

    if isinstance(subscription, Mapping):
        user = subscription.get("user") or {}
        user_id = user.get("id") if isinstance(user, Mapping) else getattr(user, "id", None)
        payload = subscription.get("invoice_payload", "") or ""
        state = str(subscription.get("state", "") or "").strip().lower()
    else:
        user = getattr(subscription, "user", None)
        user_id = getattr(user, "id", None)
        payload = getattr(subscription, "invoice_payload", "") or ""
        state = str(getattr(subscription, "state", "") or "").strip().lower()
    if not user_id or state not in {"active", "canceled", "failed"}:
        logger.warning(
            "Stars subscription update ignored: user=%r state=%r",
            user_id, state,
        )
        return False

    lang = await ensure_user_lang(context, user_id)
    plan, error = _validate_stars_payload(payload, user_id, lang=lang)
    if plan is None:
        logger.warning(
            "Stars subscription update rejected: user=%s payload=%r reason=%s",
            user_id, str(payload)[:80], error or "invalid payload",
        )
        return False

    try:
        synchronized = await db.run_db(
            db.sync_stars_subscription, int(user_id), state, None,
        )
    except Exception:
        logger.exception("Stars subscription DB synchronization failed (user=%s)", user_id)
        return False
    if not synchronized:
        logger.warning(
            "Stars subscription state was not synchronized (user=%s state=%s)",
            user_id, state,
        )
    else:
        logger.info(
            "Stars subscription state synchronized (user=%s state=%s plan=%s)",
            user_id, state, plan["plan_key"],
        )
    return bool(synchronized)


class BotSubscriptionUpdatedHandler(BaseHandler):
    """PTB handler that only consumes Updates carrying ``subscription``.

    A plain TypeHandler(Update, ...) would shadow every other handler in its
    group, so this small BaseHandler predicate keeps unrelated messages and
    callbacks on their normal routing paths.
    """

    def __init__(self):
        super().__init__(bot_subscription_updated_callback)

    def check_update(self, update):
        if getattr(update, "subscription", None) is not None:
            return True
        api_kwargs = getattr(update, "api_kwargs", None) or {}
        return isinstance(api_kwargs, Mapping) and api_kwargs.get("subscription") is not None
