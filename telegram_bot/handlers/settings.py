"""⚙️ SOZLAMALAR — ixcham 8 guruhli hub (PostAssist V2, 2-bosqich).

Asosiy menyudan [⚙️ Sozlamalar] bosilganda quyidagi guruhlar chiqadi:

    [👤 Profil]             [🌐 Til / Язык]
    [🎁 Bonuslar & Ballar]  [🎨 Post sozlamalari]
    [🔔 Bildirishnomalar]   [💳 To'lovlar tarixi]
    [🧰 Vositalar]          [❓ Yordam & Ma'lumot]
                 [◀️ Orqaga]

Bonuslar/ballar va yordam/ma'lumot o'z submenu'lariga ega; barcha ichki
[◀️ Orqaga] tugmalari ``stgs_hub`` orqali shu asosiy settings ekraniga qaytadi.

Qoidalar:
  * 3-qadam refaktori: eski kabinet tezkor tugmalari (📢 Mening kanallarim,
    📅 Rejalashtirilgan/Kutilayotgan, 📊 Analitika, 💎 Ballar & reklama rejimi)
    menyudan OLIB TASHLANDI — ular o'z asosiy menyularida bor. Ularning
    ``cab_*`` callback'lari O'CHIRILMAGAN: eski xabarlardagi tugmalar uchun
    xavfsiz alias/redirect sifatida ``handlers.start.cabinet_callback`` da
    ishlashda davom etadi (crash yo'q);
  * «🎁 Bonuslar & Ballar» hamda «❓ Yordam & Ma'lumot» parent ekranlari
    alohida ochiladi; ichki oqimlar eski callback aliaslari bilan ishlaydi
    (stgs_credits / stgs_transfer / claim_bonus / referral_hub /
    stgs_about / help_hub);
  * mavjud PROFIL (kabinet) va TIL almashtirish oqimlari buzilmaydi:
    [👤 Profil] eski kabinet ekranini, [🌐 Til / Язык] esa avvalgi til
    klaviaturasini ochadi (cab_lang_* callback'lari o'zgarmagan);
  * [🔄 Ballar o'tkazish] mavjud TRANSFER_TARGET → TRANSFER_AMOUNT FSM
    oqimini ochadi (yangi holat yo'q — ``handlers.start.transfer_inline_entry``);
  * [🧰 Vositalar] — yordamchi vositalar submenyusi (``handlers.tools``):
    Konverter va Post Enhancer endi ko'rinadigan mantiqiy joyida;
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
    get_help_keyboard,
    get_language_keyboard,
    get_referral_share_keyboard,
    get_settings_back_keyboard,
    get_settings_help_hub_keyboard,
    get_settings_profile_keyboard,
    get_settings_hub_keyboard,
    get_settings_rewards_keyboard,
)
from locales.translations import get_text, localize_db_message
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


async def build_settings_hub_text(user_id: int, lang: str, is_admin: bool,
                                  user_code=None, channels=None,
                                  stats=None, ad_line: str = "") -> str:
    """⚙️ Sozlamalar hub ekranining matni (profil kartasi).

    Matn manbasi — ``handlers.start.build_cabinet_text`` (profil ekrani bilan
    AYNAN bir xil), shu sababli hub va [👤 Profil] bir-biridan farq qilmaydi.
    Agar ``user_code`` / ``channels`` / ``stats`` argumentlari berilmasa,
    ma'lumotlar bazadan o'qiladi (ekran qayta chizilganda qayta o'qish uchun).
    """
    from handlers.start import build_cabinet_text, cabinet_credits_text

    if stats is None:
        stats = await db.run_db(db.get_referral_stats, user_id)
    if channels is None:
        channels = await db.run_db(db.get_user_channels, user_id)
    if user_code is None:
        user_code = await db.run_db(db.get_user_code, user_id)
    credits_text = cabinet_credits_text(is_admin, stats["ai_credits"], lang)
    streak_text = get_text("cabinet_streak", lang, streak=stats.get("streak", 0))
    return build_cabinet_text(
        user_id, user_code, credits_text, streak_text,
        len(channels), stats["referrals_count"], lang, ad_line,
    )


async def render_settings_hub(update_message, context, user_id: int,
                              lang: str, is_admin: bool) -> None:
    """⚙️ Sozlamalar hub ekranini yuboradi (profil matni + yagona menyu)."""
    text = await build_settings_hub_text(user_id, lang, is_admin)
    await update_message.reply_text(
        text,
        reply_markup=get_settings_hub_keyboard(lang),
        parse_mode="HTML",
    )


async def _render_hub_screen(query, context, user_id: int, lang: str,
                             is_admin: bool) -> None:
    """⚙️ Sozlamalar hub'ini qayta chizadi (stgs_hub → shu ekran)."""
    try:
        context.user_data.pop("settings_help_flow", None)
    except Exception:
        pass
    text = await build_settings_hub_text(user_id, lang, is_admin)
    await _edit_or_reply(
        query, text, get_settings_hub_keyboard(lang),
    )


async def _render_rewards_hub(query, lang: str) -> None:
    """🎁 Bonuslar & Ballar submenu'sini ko'rsatadi."""
    await _edit_or_reply(
        query,
        settings_stats_t("ss_rewards_title", lang),
        get_settings_rewards_keyboard(lang),
    )


async def _render_help_hub(query, lang: str) -> None:
    """❓ Yordam & Ma'lumot submenu'sini ko'rsatadi."""
    await _edit_or_reply(
        query,
        settings_stats_t("ss_help_hub_title", lang),
        get_settings_help_hub_keyboard(lang),
    )


async def _render_support(query, lang: str) -> None:
    """💬 Qo'llab-quvvatlash sahifasi (username bo'lmasa ham javob beradi)."""
    from handlers.start import _help_support_line

    await _edit_or_reply(
        query,
        _help_support_line(lang),
        get_settings_back_keyboard(lang),
    )


async def _render_points(query, user_id: int, lang: str, is_admin: bool) -> None:
    """💎 Ballarim — kredit balansi va reklama rejimi kartasi.

    Mavjud kabinet ekrani (``cab_balance``) bilan bir xil manba
    (``balance_card`` matni) — yangi matn lug'atga qo'shilmagan.
    """
    from handlers.start import cabinet_credits_text

    stats = await db.run_db(db.get_referral_stats, user_id)
    credits_text = cabinet_credits_text(is_admin, stats["ai_credits"], lang)
    if is_admin:
        ad_mode = get_text("ad_mode_admin", lang)
    elif await db.run_db(db.is_premium, user_id):
        ad_mode = get_text("ad_mode_pro", lang)
    else:
        ad_mode = get_text("ad_mode_free", lang)
    text = get_text("balance_card", lang, credits=credits_text, ad_mode=ad_mode)
    await _edit_or_reply(query, text, get_settings_back_keyboard(lang))


async def _render_daily_bonus(query, user_id: int, lang: str,
                              is_admin: bool) -> None:
    """🎁 Kunlik bonus — streak bonusi shu ekranda olinadi (cab_bonus = manba)."""
    from handlers.start import build_daily_bonus_text

    if is_admin:
        text = get_text("daily_bonus_admin", lang)
    else:
        res = await db.run_db(db.claim_daily_streak_bonus, user_id)
        if res.get("success"):
            text = build_daily_bonus_text(res, lang)
        else:
            text = get_text(
                "daily_bonus_already", lang,
                msg=localize_db_message(res.get("msg", ""), lang),
                credits=res.get("credits", 0),
            )
    await _edit_or_reply(query, text, get_settings_back_keyboard(lang))


async def _render_tools(query, lang: str) -> None:
    """🧰 Vositalar — yordamchi vositalar submenyusi (``handlers.tools``)."""
    from handlers.tools import render_tools_menu

    await render_tools_menu(query, lang)


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
        query, text, get_settings_profile_keyboard(lang),
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
        settings_stats_t("ss_btn_back", lang), callback_data="stgs_hub",
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


async def _render_help(query, lang: str, context=None) -> None:
    """❓ Yordam — qo'llanma + FAQ + settings hub'iga qaytish.

    ``settings_help_flow`` flag'i FAQ ichki callback'i ham parent settings
    hub'iga qaytishini, oddiy /help oqimi esa o'zining legacy navigatsiyasini
    saqlashini ta'minlaydi.
    """
    from handlers.start import _help_support_line

    if context is not None:
        try:
            context.user_data["settings_help_flow"] = True
        except Exception:
            pass
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

    Har bir parent/submenu o'z ekranini ochadi; ichki [◀️ Orqaga]
    ``stgs_hub`` orqali settings hub'iga qaytadi. Hub'ning o'zidagi
    [◀️ Orqaga] esa asosiy reply menyuga chiqadi. Mavjud kabinet (``cab_*``)
    callback'lari o'z joyida qoladi — bu handler faqat settings oqimlariga
    xizmat qiladi.

    ``stgs_transfer`` ``main_conv`` entry point'i (``handlers.start``) orqali
    mavjud TRANSFER_TARGET FSM oqimini ochadi; fallback routing ham shu oqimga
    qayta ulanadi, shuning uchun eski inline tugmalar javobsiz qolmaydi.
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

    if data == "stgs_rewards":
        await _render_rewards_hub(query, lang)
        return

    if data == "stgs_help_hub":
        await _render_help_hub(query, lang)
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

    if data in ("stgs_points", "stgs_credits"):
        # 💎 Ballarim — yangi ``stgs_credits`` va mavjud ``stgs_points``
        # callback'lari bitta ekran/DB manbasiga ulanadi.
        await _render_points(query, user_id, lang, is_admin)
        return

    if data in ("stgs_bonus", "claim_bonus"):
        # 🎁 Kunlik bonus — eski ``claim_bonus`` callback'i ham saqlanadi.
        await _render_daily_bonus(query, user_id, lang, is_admin)
        return

    if data == "stgs_tools":
        # 🧰 Vositalar — Konverter + Post Enhancer submenyusi.
        # 🧭 4-qadam: foydalanuvchi endi «Vositalar» bo'limida — bu yerden
        # boshlangan FSM oqimlari bekor qilinsa shu submenyuga qaytadi.
        from handlers.navigation import remember_section, SECTION_TOOLS
        remember_section(context, SECTION_TOOLS)
        await _render_tools(query, lang)
        return

    if data == "stgs_hub":
        # ◀️ Orqaga (submenyudan) — ⚙️ Sozlamalar menyusi qayta chiziladi.
        # 🧭 4-qadam: bo'lim yozuvi Sozlamalarga qaytadi (cancel → hub).
        from handlers.navigation import remember_section, SECTION_SETTINGS
        remember_section(context, SECTION_SETTINGS)
        await _render_hub_screen(query, context, user_id, lang, is_admin)
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

    if data in ("stgs_referral", "referral_hub"):
        await _render_referral(query, context, user_id, lang, is_admin)
        return

    if data == "stgs_help":
        # 3-qadamdagi eski to'g'ridan-to'g'ri yordam callback'i.
        await _render_help(query, lang, context)
        return

    if data == "help_hub":
        # Legacy callback: yangi help hub ichidagi qo'llanma/FAQ sahifasi.
        await _render_help(query, lang, context)
        return

    if data == "help_support":
        await _render_support(query, lang)
        return

    if data == "stgs_about":
        await _render_about(query, lang)
        return

    if data == "stgs_transfer":
        # 🔄 Mavjud TRANSFER_TARGET → TRANSFER_AMOUNT oqimiga qayta ulanadi.
        # ``main_conv`` odatda bu callback'ni entry point sifatida ushlaydi;
        # bu fallback esa eski xabarlar/global callback va unit-test chaqiruvi
        # uchun kerak.
        from handlers.start import transfer_inline_entry
        return await transfer_inline_entry(update, context)

    # Noma'lum settings callback — xavfsiz jim chiqish (crash yo'q).
    logger.debug("Sozlamalar: noma'lum callback: %r", data[:64])


async def settings_rewards_callback(update, context: ContextTypes.DEFAULT_TYPE):
    """Global router uchun 🎁 Bonuslar & Ballar callback handleri."""
    return await settings_menu_callback(update, context)


async def settings_help_hub_callback(update, context: ContextTypes.DEFAULT_TYPE):
    """Global router uchun ❓ Yordam & Ma'lumot callback handleri."""
    return await settings_menu_callback(update, context)
