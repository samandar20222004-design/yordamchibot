"""⚙️ SOZLAMALAR — yagona tartibli menyu (PostAssist V2, 5-mikro qadam).

Asosiy menyudan [⚙️ Sozlamalar] bosilganda barcha foydali ichki opsiyalar
BITTA tartibli menyuda chiqadi (inline ``stgs_*`` callback'lari):

    [👤 Profil]             [🌐 Til / Язык]
    [🔔 Bildirishnomalar]   [🎨 Post sozlamalari]
    [💳 To'lovlar tarixi]   [🎁 Do'stlarni taklif qilish]
    [❓ Yordam]             [ℹ️ Bot haqida]
                 [◀️ Orqaga]

Qoidalar:
  * «Qo'llanma / Bot haqida» va «Do'stlarni taklif qilish» shu menyu
    orqali qulay ochiladi (stgs_help / stgs_about / stgs_referral);
  * mavjud PROFIL (kabinet) va TIL almashtirish oqimlari buzilmaydi:
    [👤 Profil] eski kabinet ekranini, [🌐 Til / Язык] esa avvalgi til
    klaviaturasini ochadi (cab_lang_* callback'lari o'zgarmagan);
  * 🔔 Bildirishnomalar va 🎨 Post sozlamalari — foydalanuvchi sozlamalari
    ``user_settings`` jadvaliga saqlanadi (kalitlar OQ RO'YXAT bilan
    cheklanadi — payload'dan ixtiyoriy kalit yozib bo'lmaydi);
  * barcha matnlar UZ/RU/EN — ``translations/settings_stats.py`` (paritet
    testlar bilan qo'riqlanadi).
"""

import logging

from telegram import InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import ADMIN_IDS_SET, SUPPORT_USERNAME
import database as db
from keyboards.callback_data import cb
from keyboards.default import get_main_keyboard
from keyboards.inline import (
    get_cabinet_inline_keyboard,
    get_help_keyboard,
    get_language_keyboard,
    get_referral_share_keyboard,
    get_settings_back_keyboard,
    get_settings_hub_keyboard,
)
from locales.translations import get_lang, get_text
from translations import settings_stats_t
from utils.helpers import html_escape

logger = logging.getLogger(__name__)

# ============================================================
# SOZLAMALAR OQ RO'YXATI (payload'dan boshqa kalit yozilmaydi)
# ============================================================
#: 🔔 Bildirishnomalar kalitlari → ekrandagi yorliq i18n-kaliti.
NOTIF_SETTING_KEYS = {
    "notify_scheduled": "ss_notif_scheduled",
    "notify_news": "ss_notif_news",
}
#: 🎨 Post sozlamalari kalitlari → ekrandagi yorliq i18n-kaliti.
POST_SETTING_KEYS = {
    "post_watermark": "ss_post_watermark",
    "post_signature": "ss_post_signature",
}
#: Standart qiymatlar (sozlama hali saqlanmagan bo'lsa).
SETTING_DEFAULTS = {
    "notify_scheduled": True,
    "notify_news": False,
    "post_watermark": True,
    "post_signature": False,
}
#: Callback'dagi scope → kalitlar oilasi.
_SETTING_SCOPES = {
    "notif": NOTIF_SETTING_KEYS,
    "post": POST_SETTING_KEYS,
}


def settings_toggle_label(key: str, lang: str, enabled: bool) -> str:
    """Toggle tugma yorlig'i: ✅/⬜️ belgisi + sozlama nomi."""
    mark = "✅" if enabled else "⬜️"
    return f"{mark} {settings_stats_t(_scope_key_label(key), lang)}"


def _scope_key_label(key: str) -> str:
    """Sozlama kaliti uchun i18n-yorliq kaliti (topilmasa o'zi)."""
    for keys in _SETTING_SCOPES.values():
        if key in keys:
            return keys[key]
    return key


async def render_settings_hub(update_message, context, user_id: int,
                              lang: str, is_admin: bool) -> None:
    """⚙️ Sozlamalar hub ekranini yuboradi (profil matni + yagona menyu)."""
    from handlers.start import build_cabinet_text, cabinet_credits_text

    stats = await db.run_db(db.get_referral_stats, user_id)
    channels = await db.run_db(db.get_user_channels, user_id)
    user_code = await db.run_db(db.get_user_code, user_id)
    credits_text = cabinet_credits_text(is_admin, stats["ai_credits"], lang)
    streak_text = get_text("cabinet_streak", lang, streak=stats.get("streak", 0))
    text = build_cabinet_text(
        user_id, user_code, credits_text, streak_text,
        len(channels), stats["referrals_count"], lang,
    )
    await update_message.reply_text(
        text,
        reply_markup=get_settings_hub_keyboard(lang),
        parse_mode="HTML",
    )


async def _render_profile_screen(query, context, user_id: int, lang: str,
                                 is_admin: bool) -> None:
    """👤 Profil — mavjud kabinet ekrani (matn + eski kabinet klaviaturasi)."""
    from handlers.start import build_cabinet_text, cabinet_credits_text
    from utils.helpers import get_smart_reply_ad_async

    stats = await db.run_db(db.get_referral_stats, user_id)
    channels = await db.run_db(db.get_user_channels, user_id)
    user_code = await db.run_db(db.get_user_code, user_id)
    credits_text = cabinet_credits_text(is_admin, stats["ai_credits"], lang)
    streak_text = get_text("cabinet_streak", lang, streak=stats.get("streak", 0))
    try:
        ad_line = await get_smart_reply_ad_async(user_id)
    except Exception:
        ad_line = ""
    text = build_cabinet_text(
        user_id, user_code, credits_text, streak_text,
        len(channels), stats["referrals_count"], lang, ad_line,
    )
    await _edit_or_reply(
        query, text, get_cabinet_inline_keyboard(lang),
    )


def _edit_or_reply(query, text: str, reply_markup=None) -> None:
    """Ekranni tahrirlaydi; iloji bo'lmasa yangi xabar yuboradi (sync wrapper).

    Qaytarish: awaitable (caller ``await`` qiladi) — PTB callback'larida
    xabar o'chgan bo'lsa ham foydalanuvchi javobsiz qolmaydi.
    """
    async def _run():
        try:
            await query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode="HTML",
            )
        except Exception:
            try:
                await query.message.reply_text(
                    text, reply_markup=reply_markup, parse_mode="HTML",
                )
            except Exception:
                logger.debug("Sozlamalar ekranini ko'rsatib bo'lmadi")
    return _run()


def _build_toggles_text(title_key: str, hint_key: str, keys: dict,
                        values: dict, lang: str) -> str:
    """Toggle ekrani matni: sarlavha + har sozlama holati."""
    lines = [settings_stats_t(title_key, lang), ""]
    for key, label_key in keys.items():
        mark = "✅" if values.get(key, False) else "⬜️"
        lines.append(f"{mark} {settings_stats_t(label_key, lang)}")
    lines += ["", settings_stats_t(hint_key, lang)]
    return "\n".join(lines)


def _build_toggles_keyboard(scope: str, keys: dict, values: dict,
                            lang: str) -> InlineKeyboardMarkup:
    """Toggle tugmalari (2 tadan qator) + [◀️ Orqaga]."""
    rows = []
    items = list(keys.items())
    for i in range(0, len(items), 2):
        row = []
        for key, _label in items[i:i + 2]:
            rows_label = settings_toggle_label(key, lang, values.get(key, False))
            row.append(_inline(
                rows_label, callback_data=cb("stgs_tgl", scope, key),
            ))
        rows.append(row)
    rows.append([_inline(
        settings_stats_t("ss_btn_back", lang), callback_data="stgs_back",
    )])
    return InlineKeyboardMarkup(rows)


def _inline(text: str, callback_data: str):
    from telegram import InlineKeyboardButton
    return InlineKeyboardButton(text, callback_data=callback_data)


async def _render_toggles(query, user_id: int, scope: str, lang: str) -> None:
    """🔔 Bildirishnomalar / 🎨 Post sozlamalari ekranini chizadi."""
    if scope == "notif":
        keys, title, hint = NOTIF_SETTING_KEYS, "ss_notif_title", "ss_notif_hint"
    else:
        keys, title, hint = POST_SETTING_KEYS, "ss_post_title", "ss_post_hint"
    values = await db.run_db(
        db.get_user_settings_bulk, user_id, list(keys), SETTING_DEFAULTS,
    )
    text = _build_toggles_text(title, hint, keys, values, lang)
    markup = _build_toggles_keyboard(scope, keys, values, lang)
    await _edit_or_reply(query, text, markup)


def _fmt_payment_date(value) -> str:
    """To'lov sanasini ixcham ko'rinishda qaytaradi (xato → '—')."""
    if value is None:
        return "—"
    try:
        return value.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)[:16]


async def _render_payments(query, user_id: int, lang: str) -> None:
    """💳 To'lovlar tarixi ekrani."""
    history = await db.run_db(db.get_user_payment_history, user_id, 10)
    if not history:
        await _edit_or_reply(
            query, settings_stats_t("ss_pay_empty", lang),
            get_settings_back_keyboard(lang),
        )
        return
    lines = [settings_stats_t("ss_pay_title", lang), ""]
    for row in history:
        method_key = (
            "ss_pay_method_card" if row.get("method") == "card"
            else "ss_pay_method_stars"
        )
        status_raw = str(row.get("status") or "succeeded").lower()
        status_key = f"ss_pay_status_{status_raw}"
        status_mark = settings_stats_t(status_key, lang)
        if status_mark == status_key:  # noma'lum holat — belgisiz chiqadi
            status_mark = ""
        amount = row.get("amount", 0)
        currency = row.get("currency", "")
        amount_text = f"{amount} {currency}".strip()
        lines.append(settings_stats_t(
            "ss_pay_row", lang,
            date=html_escape(_fmt_payment_date(row.get("date"))),
            amount=html_escape(amount_text),
            method=settings_stats_t(method_key, lang),
            status=status_mark,
        ))
    lines += ["", settings_stats_t("ss_pay_count", lang, n=len(history))]
    await _edit_or_reply(
        query, "\n".join(lines), get_settings_back_keyboard(lang),
    )


async def _render_referral(query, context, user_id: int, lang: str,
                           is_admin: bool) -> None:
    """🎁 Do'stlarni taklif qilish — referral menyu (share + orqaga)."""
    from handlers.start import cabinet_credits_text

    bot_obj = await context.bot.get_me()
    stats = await db.run_db(db.get_referral_stats, user_id)
    ref_link = f"https://t.me/{bot_obj.username}?start=ref_{user_id}"
    credits_text = cabinet_credits_text(is_admin, stats["ai_credits"], lang)
    text = get_text(
        "referral_menu", lang, credits=credits_text,
        count=stats["referrals_count"], link=ref_link,
    )
    share_kb = get_referral_share_keyboard(ref_link, lang)
    combined = InlineKeyboardMarkup(
        share_kb.inline_keyboard + get_settings_back_keyboard(lang).inline_keyboard
    )
    await _edit_or_reply(query, text, combined)


async def _render_help(query, lang: str) -> None:
    """❓ Yordam — qo'llanma + FAQ + orqaga."""
    from handlers.start import _help_support_line

    text = get_text("help_guide", lang, support=_help_support_line(lang))
    help_kb = get_help_keyboard(SUPPORT_USERNAME, lang)
    combined = InlineKeyboardMarkup(
        help_kb.inline_keyboard + get_settings_back_keyboard(lang).inline_keyboard
    )
    await _edit_or_reply(query, text, combined)


async def _render_about(query, lang: str) -> None:
    """ℹ️ Bot haqida — bot imkoniyatlari + qo'llab-quvvatlash."""
    support = f"@{SUPPORT_USERNAME}" if SUPPORT_USERNAME else get_text(
        "help_admin_fallback", lang
    )
    text = settings_stats_t("ss_about_text", lang, support=support)
    await _edit_or_reply(query, text, get_settings_back_keyboard(lang))


async def settings_menu_callback(update, context: ContextTypes.DEFAULT_TYPE):
    """⚙️ Sozlamalar ichki menyusi — barcha ``stgs_*`` inline callback'lar.

    Har bir bo'lim o'z ekranini ochadi; [◀️ Orqaga] asosiy menyuga qaytaradi.
    Mavjud kabinet (``cab_*``) callback'lari o'z joyida qoladi — bu handler
    faqat YANGI sozlamalar hub'iga xizmat qiladi.
    """
    from handlers.start import ensure_user_lang

    query = update.callback_query
    data = query.data or ""
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS_SET
    lang = await ensure_user_lang(context, user_id)

    try:
        await query.answer()
    except Exception:
        pass

    if data == "stgs_back":
        # ◀️ Orqaga — sozlamalar yopiladi va asosiy menyu qaytadi.
        try:
            await query.message.delete()
        except Exception:
            pass
        try:
            await query.message.reply_text(
                get_text("msg_closed", lang),
                reply_markup=get_main_keyboard(is_admin, lang=lang),
            )
        except Exception:
            pass
        return

    if data == "stgs_profile":
        await _render_profile_screen(query, context, user_id, lang, is_admin)
        return

    if data == "stgs_lang":
        # Mavjud til almashtirish oqimi (cab_lang bilan bir xil ekran).
        try:
            await query.edit_message_text(
                get_text("lang_prompt", lang),
                reply_markup=get_language_keyboard(lang),
                parse_mode="HTML",
            )
        except Exception:
            await query.message.reply_text(
                get_text("lang_prompt", lang),
                reply_markup=get_language_keyboard(lang),
                parse_mode="HTML",
            )
        return

    if data in ("stgs_notif", "stgs_post"):
        scope = "notif" if data == "stgs_notif" else "post"
        await _render_toggles(query, user_id, scope, lang)
        return

    if data.startswith("stgs_tgl:"):
        # stgs_tgl:<scope>:<key> — OQ RO'YXAT tekshiruvi bilan toggle.
        parts = data.split(":")
        if len(parts) != 3:
            return
        _, scope, key = parts
        keys = _SETTING_SCOPES.get(scope)
        if not keys or key not in keys:
            # Payload manipulyatsiyasi — jim rad (fail-closed).
            logger.warning("Sozlamalar: noma'lum toggle kaliti rad etildi: %r", data[:64])
            return
        current = await db.run_db(
            db.get_user_settings_bulk, user_id, [key], SETTING_DEFAULTS,
        )
        new_value = not bool(current.get(key, False))
        await db.run_db(db.set_user_setting, user_id, key, new_value)
        toast = settings_stats_t(
            "ss_switched_on" if new_value else "ss_switched_off", lang,
        )
        try:
            await query.answer(toast, show_alert=False)
        except Exception:
            pass
        await _render_toggles(query, user_id, scope, lang)
        return

    if data == "stgs_pay":
        await _render_payments(query, user_id, lang)
        return

    if data == "stgs_referral":
        await _render_referral(query, context, user_id, lang, is_admin)
        return

    if data == "stgs_help":
        await _render_help(query, lang)
        return

    if data == "stgs_about":
        await _render_about(query, lang)
        return

    # Noma'lum stgs_* callback — xavfsiz jim chiqish (crash yo'q).
    logger.debug("Sozlamalar: noma'lum callback: %r", data[:64])
