"""⚙️ SOZLAMALAR — 8 tugmali hub (4 qator × 2 tugma).

Asosiy menyudan [⚙️ Sozlamalar] bosilganda quyidagi SIMMETRIK menyu chiqadi
(hech bir tugma yolg'iz qatorda qolmaydi):

    [🌐 Til / Язык]         [✍️ Post sozlamalari]
    [🔔 Bildirishnomalar]   [👥 Do'stlarni taklif]
    [💳 To'lovlar tarixi]   [ℹ️ Bot haqida]
    [💬 Qo'llab-quvvatlash] [❌ Yopish]

«⚙️ Sozlamalar» / «👤 Shaxsiy kabinet» chalkashligi tugatildi: endi YAGONA
Sozlamalar ekran bor. Ichki [◀️ Orqaga] tugmalari ``stgs_hub`` orqali shu
asosiy Sozlamalar ekraniga qaytadi.

Qoidalar:
  * 3-qadam refaktori: eski kabinet tezkor tugmalari (📢 Mening kanallarim,
    📅 Rejalashtirilgan/Kutilayotgan, 📊 Analitika, 💎 Ballar & reklama rejimi)
    menyudan OLIB TASHLANDI — ular o'z asosiy menyularida bor. Ularning
    ``cab_*`` callback'lari O'CHIRILMAGAN: eski xabarlardagi tugmalar uchun
    xavfsiz alias/redirect sifatida ``handlers.start.cabinet_callback`` da
    ishlashda davom etadi (crash yo'q);
  * «👥 Do'stlarni taklif» asosiy menyudan SOZLAMALAR hub'iga ko'chirildi
    (stgs_referral — referral havolasi + kunlik bonus shu yerda ochiladi);
    «🎁 Bonuslar & Taklif», «🧰 Vositalar» va «❓ Yordam & Ma'lumot»
    guruhlari hub'dan OLIB TASHLANDI. Ularning oqimlari (stgs_rewards /
    stgs_tools / stgs_help_hub / stgs_credits / stgs_transfer /
    claim_bonus / referral_hub / stgs_about / help_hub) eski xabarlardagi
    tugmalar uchun saqlanadi;
  * mavjud PROFIL (kabinet) va TIL almashtirish oqimlari buzilmaydi:
    [⚙️ Sozlamalar] eski kabinet ekranini, [🌐 Til / Язык] esa avvalgi til
    klaviaturasini ochadi (cab_lang_* callback'lari o'zgarmagan);
  * [🔄 Ballar o'tkazish] mavjud TRANSFER_TARGET → TRANSFER_AMOUNT FSM
    oqimini ochadi (yangi holat yo'q — ``handlers.start.transfer_inline_entry``);
  * [🧰 Vositalar] — yordamchi vositalar submenyusi (``handlers.tools``):
    Konverter va Post Enhancer endi ko'rinadigan mantiqiy joyida;
  * 🔔 Bildirishnomalar va ✍️ Post sozlamalari — foydalanuvchi sozlamalari
    ``user_settings`` jadvaliga saqlanadi (kalitlar OQ RO'YXAT bilan
    cheklanadi — payload'dan ixtiyoriy kalit yozib bo'lmaydi);
  * barcha matnlar UZ/RU/EN — ``translations/settings_stats.py`` (paritet
    testlar bilan qo'riqlanadi).
"""

import logging
import time

from telegram import InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import ADMIN_IDS_SET, BOT_USERNAME, BOT_VERSION, SUPPORT_USERNAME
import database as db
from keyboards.callback_data import cb
from keyboards.default import get_main_keyboard
from keyboards.inline import (
    get_help_keyboard,
    get_language_keyboard,
    get_referral_share_keyboard,
    get_settings_back_keyboard,
    get_settings_help_hub_keyboard,
    get_profile_menu_keyboard,
    get_settings_hub_keyboard,
    get_settings_rewards_keyboard,
)
from locales.translations import (
    clear_fsm_data,
    get_text,
    localize_db_message,
    normalize_lang,
)
from translations import settings_stats_t
from utils.helpers import html_escape

from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

# ============================================================
# STATIK MATNLAR KESHI (qo'llanma/yordam/sozlamalar — ~0.2s ochilish)
# ============================================================
#: Kesh TTL (soniya). Statik matnlar deyarli o'zgarmaydi; konfig
#: (SUPPORT_USERNAME/BOT_VERSION) o'zgarsa kesh kalitining o'zi yangilanadi.
_STATIC_TEXT_TTL_SEC = 600
#: (nom, til, support_username, bot_version) → (matn, yozilgan_vaqt).
_STATIC_TEXT_CACHE: dict[tuple, tuple[str, float]] = {}


def _static_cache_key(name: str, lang: str) -> tuple:
    """Kesh kaliti — konfig qiymatlari bilan (patch/test xavfsizligi)."""
    try:
        username = str(SUPPORT_USERNAME or "")
    except Exception:
        username = ""
    try:
        version = str(BOT_VERSION or "")
    except Exception:
        version = ""
    return (str(name), normalize_lang(lang), username, version)


def _cached_static_text(name: str, lang: str, builder) -> str:
    """Statik matnni keshlab qaytaradi (``builder`` — ``() -> str``).

    Birinchi ochilishda quriladi, keyingi ochilishlarda xotiradan olinadi
    (~0.2 soniyada, DB/formatlashsiz). TTL tugasa yoki konfig o'zgarsa
    qayta quriladi. ``builder`` xatosi yuqoriga uzatiladi (fail-loud —
    renderer'ning o'z try/except'i uni ushlaydi).
    """
    key = _static_cache_key(name, lang)
    now = time.monotonic()
    hit = _STATIC_TEXT_CACHE.get(key)
    if hit is not None:
        text, ts = hit
        if now - ts < _STATIC_TEXT_TTL_SEC:
            return text
    text = str(builder() or "")
    if len(_STATIC_TEXT_CACHE) > 200:
        _STATIC_TEXT_CACHE.clear()
    _STATIC_TEXT_CACHE[key] = (text, now)
    return text


def clear_settings_static_cache() -> None:
    """Statik matnlar keshini tozalaydi (testlar/diagnostika uchun)."""
    _STATIC_TEXT_CACHE.clear()


# ============================================================
# SOZLAMALAR OQ RO'YXATI (payload'dan boshqa kalit yozilmaydi)
# ============================================================
#: 🔔 Bildirishnomalar kalitlari → ekrandagi yorliq i18n-kaliti.
NOTIF_SETTING_KEYS = {
    "notify_scheduled": "ss_notif_scheduled",
    "notify_news": "ss_notif_news",
    "notify_morning_digest": "ss_notif_morning_digest",
    "notify_uzbek_calendar": "ss_notif_uzbek_calendar",
}
#: 🎨 Post sozlamalari kalitlari → ekrandagi yorliq i18n-kaliti.
POST_SETTING_KEYS = {
    "post_watermark": "ss_post_watermark",
    "post_signature": "ss_post_signature",
}
#: 🧹 Auto-cleaner ekranida ko'rsatiladigan sozlama kalitlari. Asosiy post
#: toggles ham shu ekranda saqlanadi, shunda ixcham 4-button primary grid
#: mavjud imkoniyatlarni yashirmaydi.
#:
#: ``post_auto_clean`` — bosh kalit (standart O'CHIRILGAN, opt-in):
#: o'chirilganda dvigatel matnga UMUMAN tegmaydi. Qolganlari — nima
#: aynan o'chirilishini boshqaradi.
CLEANER_SETTING_KEYS = {
    "post_auto_clean": "ss_clean_title",
    "post_clean_mentions": "ss_post_watermark",
    "post_clean_links": "ss_post_watermark",
    "post_clean_promo": "ss_post_watermark",
    "post_watermark": "ss_post_watermark",
    "post_signature": "ss_post_signature",
}
#: Standart qiymatlar (sozlama hali saqlanmagan bo'lsa).
SETTING_DEFAULTS = {
    "notify_scheduled": True,
    "notify_news": False,
    "notify_morning_digest": True,
    "notify_uzbek_calendar": True,
    "post_watermark": True,
    "post_signature": False,
    # 🧹 Auto-cleaner — OPT-IN: yangi foydalanuvchi uchun o'chirilgan,
    # mavjud oqim hech qanday tarzda o'zgarmaydi (regressiya yo'q).
    "post_auto_clean": False,
    "post_clean_mentions": True,
    "post_clean_links": True,
    "post_clean_promo": True,
}
#: Callback'dagi scope → kalitlar oilasi.
_SETTING_SCOPES = {
    "notif": NOTIF_SETTING_KEYS,
    "post": POST_SETTING_KEYS,
    "clean": CLEANER_SETTING_KEYS,
}


COMPACT_TOGGLE_LABELS = {
    "uz": {
        "notify_scheduled": "Eslatmalar",
        "notify_news": "Takliflar",
        "notify_morning_digest": "Ertalabki g'oyalar",
        "notify_uzbek_calendar": "Bayram eslatmalari",
        "post_watermark": "Suv belgisi",
        "post_signature": "Muallif imzosi",
        # 🧹 Auto-cleaner (⚙️ Ko'proq sozlamalar ichida)
        "post_auto_clean": "Avto-tozalash",
        "post_clean_mentions": "@ Eslatmalar",
        "post_clean_links": "🔗 Havolalar",
        "post_clean_promo": "📢 Reklama",
    },
    "ru": {
        "notify_scheduled": "Напоминания",
        "notify_news": "Предложения",
        "notify_morning_digest": "Утренние идеи",
        "notify_uzbek_calendar": "Праздничные напоминания",
        "post_watermark": "Водяной знак",
        "post_signature": "Подпись автора",
        # 🧹 Автоочистка (внутри ⚙️ Дополнительные настройки)
        "post_auto_clean": "Автоочистка",
        "post_clean_mentions": "@ Упоминания",
        "post_clean_links": "🔗 Ссылки",
        "post_clean_promo": "📢 Реклама",
    },
    "en": {
        "notify_scheduled": "Reminders",
        "notify_news": "Offers",
        "notify_morning_digest": "Morning ideas",
        "notify_uzbek_calendar": "Holiday reminders",
        "post_watermark": "Watermark",
        "post_signature": "Author signature",
        # 🧹 Auto-cleaner (inside ⚙️ More settings)
        "post_auto_clean": "Auto-clean",
        "post_clean_mentions": "@ Mentions",
        "post_clean_links": "🔗 Links",
        "post_clean_promo": "📢 Ads",
    },
}


def settings_toggle_label(key: str, lang: str, enabled: bool) -> str:
    """Toggle tugma yorlig'i: ✅/⬜️ belgisi + ixcham sozlama nomi."""
    mark = "✅" if enabled else "⬜️"
    label = COMPACT_TOGGLE_LABELS.get(lang, COMPACT_TOGGLE_LABELS["uz"]).get(key)
    if not label:
        label = settings_stats_t(_scope_key_label(key), lang)
    return f"{mark} {label}"


def _scope_key_label(key: str) -> str:
    """Sozlama kaliti uchun i18n-yorliq kaliti (topilmasa o'zi)."""
    for keys in _SETTING_SCOPES.values():
        if key in keys:
            return keys[key]
    return key


async def build_settings_hub_text(user_id: int, lang: str, is_admin: bool,
                                  user_code=None, channels=None,
                                  stats=None, ad_line: str = "") -> str:
    """⚙️ Sozlamalar hub'ining statik matni (DB/foydalanuvchi ma'lumoti yo'q).

    Profil ma'lumotlari `/profile` ichida ko'rsatiladi. Settings entry-point
    esa statik qoladi: bu cold-start/inline navigation'da DB round-trip'larni
    olib tashlaydi va ekran matnini/kb'ni har safar darhol qurish imkonini beradi.
    Parametrlar eski chaqiruvchilar uchun API mosligi sifatida qoldirilgan.
    """
    return "".join((
        settings_stats_t("ss_settings_hub_title", lang),
        settings_stats_t("ss_settings_hub_hint", lang),
    ))


async def render_settings_hub(update_message, context, user_id: int,
                              lang: str, is_admin: bool) -> None:
    """⚙️ Statik, to'rt tugmali Sozlamalar hub'ini yuboradi."""
    text = await build_settings_hub_text(user_id, lang, is_admin)
    await update_message.reply_text(
        text,
        reply_markup=get_settings_hub_keyboard(lang),
        parse_mode="HTML",
    )


async def _render_hub_screen(query, context, user_id: int, lang: str,
                             is_admin: bool) -> None:
    """⚙️ Sozlamalar hub'ini DB'siz qayta chizadi (stgs_hub → shu ekran)."""
    try:
        context.user_data.pop("settings_help_flow", None)
    except Exception as _silent_exc:
        log_silent_failure("handlers.settings:_render_hub_screen", _silent_exc,
                           user_id=user_id, lang=lang)
    text = await build_settings_hub_text(user_id, lang, is_admin)
    await _edit_or_reply(query, text, get_settings_hub_keyboard(lang))


async def _render_rewards_hub(query, lang: str) -> None:
    """🎁 Bonuslar & Ballar submenu'sini ko'rsatadi."""
    text = _cached_static_text(
        "rewards_title", lang,
        lambda: settings_stats_t("ss_rewards_title", lang),
    )
    await _edit_or_reply(
        query,
        text,
        get_settings_rewards_keyboard(lang),
    )


async def _render_help_hub(query, lang: str) -> None:
    """Bot haqida, qo'llanma va admin aloqasi — bitta xabarda."""
    from handlers.start import _help_support_line

    def _build() -> str:
        about = {
            "uz": "ℹ️ <b>PostAssist</b> — Telegram kanallari uchun post yaratish, "
                  "rejalashtirish va statistika bo'yicha AI yordamchi.",
            "ru": "ℹ️ <b>PostAssist</b> — AI-помощник для создания постов, "
                  "планирования и статистики Telegram-каналов.",
            "en": "ℹ️ <b>PostAssist</b> — an AI assistant for creating posts, "
                  "scheduling and statistics for Telegram channels.",
        }[normalize_lang(lang)]
        support = _help_support_line(lang)
        username = str(SUPPORT_USERNAME or "").strip().lstrip("@")
        if username:
            admin = html_escape(username)
            support = get_text(
                "help_support_line", lang,
                admin=f'<a href="https://t.me/{admin}">@{admin}</a>')
        return about + "\n\n" + get_text("help_guide", lang, support=support)

    text = _cached_static_text("help_hub", lang, _build)
    await _edit_or_reply(
        query,
        text,
        get_settings_help_hub_keyboard(lang),
    )


async def _render_support(query, lang: str) -> None:
    """💬 Qo'llab-quvvatlash sahifasi (username bo'lmasa ham javob beradi)."""
    from handlers.start import _help_support_line

    text = _cached_static_text(
        "support", lang, lambda: _help_support_line(lang),
    )
    await _edit_or_reply(
        query,
        text,
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


# ============================================================
# ⚙️ KO'PROQ SOZLAMALAR (NESTED) + 🧹 POST AUTO-CLEANER & IMZO
# ============================================================
# Joylashuv (ataylab CHUQUR, hub'ga tegmasdan):
#
#   ⚙️ Sozlamalar (hub — 10 tugma, O'ZGARMAGAN)
#     └── ✍️ Post sozlamalari (stgs_post)
#           └── ⚙️ Ko'proq sozlamalar (stgs_more)      ← YANGI nested menyu
#                 └── 🧹 Avto-tozalash (stgs_clean)    ← YANGI funksiya
#
# Nega shunday? ⚙️ Sozlamalar hub'i 10 tugma / 5 qator × 2 bo'lib qat'iy
# standartlashtirilgan (simmetrik juft layout). Yangi tugma hub'ga qo'shilsa
# o'sha layout buziladi; shu sababli bo'lim post sozlamalarining O'Z ichiga,
# chuqurroqqa joylashtirildi. Post sozlamalari ekranidagi [⚙️ Ko'proq]
# tugmasi [◀️ Orqaga] bilan BIR qatorda — mavjud kontrakt saqlanadi.

#: ⚙️ Ko'proq sozlamalar menyusidagi bo'limlar (callback → i18n yorliq kaliti).
MORE_SETTINGS_ITEMS = (
    ("stgs_clean", "ss_btn_cleaner"),
)


async def _render_more_settings(query, lang: str) -> None:
    """⚙️ Ko'proq sozlamalar — nested submenyu (``stgs_more``).

    Hozircha bitta bo'lim: 🧹 Post Auto-Cleaner & Custom Signature. Ro'yxat
    ``MORE_SETTINGS_ITEMS`` da — yangi bo'lim qo'shish uchun shu tuple'ni
    kengaytirish kifoya (kod o'zgarmaydi).
    """
    rows = []
    for callback_data, label_key in MORE_SETTINGS_ITEMS:
        rows.append([_inline(
            settings_stats_t(label_key, lang), callback_data=callback_data,
        )])
    rows.append([_inline(
        settings_stats_t("ss_btn_back", lang), callback_data="stgs_post",
    )])
    text = "\n".join([
        settings_stats_t("ss_more_title", lang),
        "",
        settings_stats_t("ss_more_hint", lang),
    ])
    await _edit_or_reply(query, text, InlineKeyboardMarkup(rows))


def _cleaner_signature_line(user_id_signature: str, lang: str) -> str:
    """✍️ Imzo qatori (HTML-xavfsiz: foydalanuvchi matni escape qilinadi)."""
    from utils.telegram_sanitizer import escape_html

    value = (user_id_signature or "").strip()
    shown = (
        settings_stats_t("ss_clean_sig_value", lang, value=escape_html(value))
        if value else settings_stats_t("ss_clean_sig_empty", lang)
    )
    return settings_stats_t("ss_clean_sig_label", lang, value=shown)


async def _load_cleaner_state(user_id: int, values: dict | None = None) -> dict:
    """🧹 Auto-cleaner holatini o'qiydi (toggle'lar + ✍️ imzo).

    Repository qo'llasa sozlamalar va imzo bitta JOIN so'rovida olinadi;
    legacy/mock adapterlar uchun ikkita avvalgi getter bilan fallback bor.
    """
    keys = list(CLEANER_SETTING_KEYS)
    signature = ""
    combined_loaded = False
    combined = getattr(db, "get_user_settings_and_signature", None)
    if callable(combined):
        try:
            result = await db.run_db(
                combined, user_id, keys, SETTING_DEFAULTS,
            )
            if isinstance(result, tuple) and len(result) == 2:
                combined_values, signature = result
                combined_loaded = True
                if values is None:
                    values = combined_values
        except Exception:
            log_silent_failure("handlers.settings:_load_cleaner_state:combined",
                               None, user_id=user_id)
    if values is None:
        values = await db.run_db(
            db.get_user_settings_bulk, user_id, keys, SETTING_DEFAULTS,
        )
    if not combined_loaded:
        try:
            signature = await db.run_db(db.get_user_post_signature, user_id)
        except Exception:
            signature = ""
            log_silent_failure("handlers.settings:_load_cleaner_state:signature",
                               None, user_id=user_id)
    return {"values": values or {}, "signature": signature or ""}


def _build_cleaner_text(values: dict, signature: str, lang: str) -> str:
    """🧹 Auto-cleaner ekrani matni (holat + tavsif + ✍️ imzo)."""
    status = (
        settings_stats_t("ss_clean_on", lang)
        if values.get("post_auto_clean", False)
        else settings_stats_t("ss_clean_off", lang)
    )
    return "".join([
        settings_stats_t("ss_clean_title", lang),
        settings_stats_t("ss_clean_status", lang, status=status),
        settings_stats_t("ss_clean_body", lang),
        _cleaner_signature_line(signature, lang),
        settings_stats_t("ss_clean_hint", lang),
    ])


def _build_cleaner_keyboard(values: dict, lang: str) -> InlineKeyboardMarkup:
    """🧹 Auto-cleaner klaviaturasi — toggle'lar + ✍️ imzo + 🧪 namuna.

    Tugmalar ixcham qatorlarda; auto-cleaner va umumiy post toggle'lari
    bitta joyda saqlanadi:

        [✅/⬜️ Avto-tozalash]
        [✅/⬜️ @ Eslatmalar] [✅/⬜️ 🔗 Havolalar]
        [✅/⬜️ 📢 Reklama]   [✍️ Suv belgisi]
        [✍️ Muallif imzosi] [✍️ Imzo matni]
        [🧪 Namuna]         [🗑 Imzoni o'chir]
        [◀️ Orqaga]
    """
    def toggle(key: str):
        return _inline(
            settings_toggle_label(key, lang, values.get(key, False)),
            callback_data=cb("stgs_tgl", "clean", key),
        )

    return InlineKeyboardMarkup([
        [toggle("post_auto_clean")],
        [toggle("post_clean_mentions"), toggle("post_clean_links")],
        [toggle("post_clean_promo"), toggle("post_watermark")],
        [toggle("post_signature"), _inline(
            settings_stats_t("ss_btn_clean_sig", lang),
            callback_data="stgs_clean_sig",
        )],
        [_inline(settings_stats_t("ss_btn_clean_demo", lang),
                 callback_data="stgs_clean_demo"),
         _inline(settings_stats_t("ss_btn_clean_clear", lang),
                 callback_data="stgs_clean_sig_clear")],
        [_inline(settings_stats_t("ss_btn_back", lang),
                 callback_data="stgs_hub")],
    ])


async def _render_cleaner(query, user_id: int, lang: str,
                          values: dict | None = None, *,
                          allow_reply_fallback: bool = True) -> None:
    """🧹 Post Auto-Cleaner & Custom Signature sozlama ekrani (``stgs_clean``)."""
    state = await _load_cleaner_state(user_id, values)
    await _edit_toggle_screen(
        query,
        _build_cleaner_text(state["values"], state["signature"], lang),
        _build_cleaner_keyboard(state["values"], lang),
        allow_reply_fallback=allow_reply_fallback,
    )


async def _render_cleaner_demo(query, user_id: int, lang: str) -> None:
    """🧪 Namuna — tozalash dvigatelini real namunada ko'rsatadi.

    Foydalanuvchi sozlamalari ASOSIDA ishlaydi (DB'ga hech narsa yozilmaydi),
    shu sababli yoqishdan oldin natijani ko'rish mumkin.
    """
    from services.post_cleaner import (
        DEMO_SOURCE_HTML, clean_html, load_cleaner_config, own_channel_usernames,
    )
    from utils.telegram_sanitizer import html_to_text, sanitize_html

    config = await load_cleaner_config(
        user_id, own_usernames=await own_channel_usernames(user_id),
    )
    # Ekranda ko'rsatish uchun dvigatel doim YOQILGAN holatda hisoblanadi —
    # aks holda o'chirilgan sozlama bilan namuna hech narsa ko'rsatmaydi.
    from dataclasses import replace as _replace

    preview = _replace(config, enabled=True)
    result = clean_html(DEMO_SOURCE_HTML, preview)

    sig_note = (
        settings_stats_t("ss_clean_demo_sig_added", lang)
        if result.signature_added else ""
    )
    text = "".join([
        settings_stats_t("ss_clean_demo_title", lang),
        settings_stats_t(
            "ss_clean_demo_before", lang,
            before=sanitize_html(DEMO_SOURCE_HTML, 700),
        ),
        settings_stats_t(
            "ss_clean_demo_after", lang,
            after=sanitize_html(result.text, 700),
        ),
        settings_stats_t(
            "ss_clean_demo_stats", lang,
            mentions=result.removed_mentions,
            links=result.removed_links,
            promo=result.removed_promo_lines,
            sig=sig_note,
        ),
    ])
    if not result.changed:
        text += settings_stats_t("ss_clean_demo_nochange", lang)

    rows = [
        [_inline(settings_stats_t("ss_btn_cleaner", lang),
                 callback_data="stgs_clean")],
        [_inline(settings_stats_t("ss_btn_back", lang),
                 callback_data="stgs_hub")],
    ]
    # ``html_to_text`` — parse_mode=None fallback uchun (xavfsiz oddiy matn).
    await _edit_or_reply(
        query, text if "<" in text else html_to_text(text),
        InlineKeyboardMarkup(rows),
    )


async def _clear_cleaner_signature(query, context, user_id: int,
                                   lang: str) -> None:
    """🗑 Saqlangan imzoni o'chiradi va ekranni yangilaydi."""
    saved = await db.run_db(db.set_user_post_signature, user_id, "")
    toast = (
        settings_stats_t("ss_clean_sig_cleared", lang) if saved
        else settings_stats_t("ss_clean_sig_none", lang)
    )
    try:
        await query.answer(toast, show_alert=False)
    except Exception as _silent_exc:
        log_silent_failure("handlers.settings:_clear_cleaner_signature",
                           _silent_exc, user_id=user_id)
    await _render_cleaner(query, user_id, lang, allow_reply_fallback=False)


# ============================================================
# ✍️ IMZO KIRITISH FSM (bitta holat — matn kutiladi)
# ============================================================
#: FSM holati: foydalanuvchi ✍️ imzo/havola matnini yozishi kutilmoqda.
#:
#: 545 — TANLANGAN, chunki 5xx diapazoni band: 501–502 (analitika),
#: 511–512 (transfer), 520–525 (image post), **530–539 (manbalar/SRC_*)**,
#: 540 (support ticket). 541–599 bo'sh; 545 hech qaysi oqim bilan
#: to'qnashmaydi (``tests/sources_rss_and_recycle_test.py`` 530–539
#: blokini qat'iy qo'riqlaydi — shu sababli 530 ISHLATILMAYDI).
CLEANER_SIGNATURE_INPUT = 545


async def cleaner_signature_entry(update, context: ContextTypes.DEFAULT_TYPE):
    """✍️ Imzoni kiritish oqimini boshlaydi (``stgs_clean_sig`` entry point).

    ``main_conv`` entry point'i sifatida ro'yxatdan o'tadi — generic
    ``^stgs_`` handler'idan OLDIN ishlaydi (``main_conv`` app'ga avval
    qo'shiladi), shu sababli tugma "o'lik" qolmaydi.
    """
    from handlers.start import ensure_user_lang

    query = getattr(update, "callback_query", None)
    user_id = None
    if query is not None:
        user_id = query.from_user.id
        try:
            await query.answer()
        except Exception as _silent_exc:
            log_silent_failure("handlers.settings:cleaner_signature_entry",
                               _silent_exc, user_id=user_id)
    lang = await ensure_user_lang(context, user_id)
    context.user_data["cleaner_sig_chat"] = (
        query.message.chat_id if query is not None else update.effective_chat.id
    )
    context.user_data["cleaner_sig_msg"] = (
        query.message.message_id if query is not None else None
    )
    from utils.post_signature import MAX_SIGNATURE_LEN

    prompt = settings_stats_t("ss_clean_sig_prompt", lang,
                              max_len=MAX_SIGNATURE_LEN)
    if query is not None:
        try:
            await query.edit_message_text(prompt, parse_mode="HTML")
            return CLEANER_SIGNATURE_INPUT
        except Exception:
            pass
    await context.bot.send_message(
        context.user_data["cleaner_sig_chat"], prompt, parse_mode="HTML",
    )
    return CLEANER_SIGNATURE_INPUT


async def cleaner_signature_received(update, context: ContextTypes.DEFAULT_TYPE):
    """✍️ Yuborilgan imzo/havolani tekshiradi, saqlaydi va ekranni qaytaradi.

    Xavfsizlik: matn ``normalize_signature`` orqali tozalanadi (boshqaruv/
    yo'nalish belgilari yo'q, ≤10 qator, ≤500 belgi) va ekranda HTML-escape
    qilinadi — foydalanuvchi kiritgan ``<b>`` teg sifatida ishlamaydi.
    """
    from utils.post_signature import normalize_signature

    user_id = update.effective_user.id
    lang = await _user_lang(context, user_id)
    raw = update.message.text or "" if update.message else ""
    text = normalize_signature(raw)

    if not text:
        # Bo'sh/jim qabul qilinmaydi — lekin oqim YOPILMAYDI (qayta urinish).
        await update.message.reply_text(
            settings_stats_t("ss_clean_sig_rejected", lang), parse_mode="HTML",
        )
        return CLEANER_SIGNATURE_INPUT

    saved = await db.run_db(db.set_user_post_signature, user_id, text)
    if not saved:
        logger.warning("Imzoni saqlab bo'lmadi: user_id=%s", user_id)
        await update.message.reply_text(
            settings_stats_t("ss_clean_sig_rejected", lang), parse_mode="HTML",
        )
        return CLEANER_SIGNATURE_INPUT

    await update.message.reply_text(
        settings_stats_t("ss_clean_sig_saved", lang), parse_mode="HTML",
    )
    chat_id = context.user_data.pop("cleaner_sig_chat", None) or update.effective_chat.id
    message_id = context.user_data.pop("cleaner_sig_msg", None)
    # Sozlama ekranini joyida yangilaymiz (yangi xabar spam qilinmaydi).
    if message_id:
        try:
            state = await _load_cleaner_state(user_id)
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=_build_cleaner_text(state["values"], state["signature"], lang),
                reply_markup=_build_cleaner_keyboard(state["values"], lang),
                parse_mode="HTML",
            )
            return _end_state()
        except Exception as _silent_exc:
            log_silent_failure("handlers.settings:cleaner_signature_received",
                               _silent_exc, user_id=user_id)
    # Fallback: ekran topilmasa yangi xabar bilan ochiladi.
    await _send_cleaner_screen(context, user_id, chat_id, lang)
    return _end_state()


def _end_state():
    """``ConversationHandler.END`` (import siklidan qochish uchun kech)."""
    from telegram.ext import ConversationHandler

    return ConversationHandler.END


async def _user_lang(context, user_id: int) -> str:
    """Foydalanuvchi tili (``handlers.start`` orqali — import sikli yo'q)."""
    from handlers.start import ensure_user_lang

    return await ensure_user_lang(context, user_id)


async def _send_cleaner_screen(context, user_id: int, chat_id: int,
                               lang: str) -> None:
    """🧹 Auto-cleaner ekranini YANGI xabar sifatida yuboradi (fallback)."""
    state = await _load_cleaner_state(user_id)
    await context.bot.send_message(
        chat_id,
        _build_cleaner_text(state["values"], state["signature"], lang),
        reply_markup=_build_cleaner_keyboard(state["values"], lang),
        parse_mode="HTML",
    )


async def cleaner_command(update, context: ContextTypes.DEFAULT_TYPE):
    """🧹 ``/cleaner`` — Post tozalagich va ✍️ Imzo ekranini DARHOL ochadi.

    ☰ «Menu» tugmasidagi ``/cleaner`` buyrug'i uchun (uz/ru/en). Ekran
    Sozlamalar ichida CHUQUR joylashgan (⚙️ Sozlamalar → ✍️ Post
    sozlamalari → ⚙️ Ko'proq → 🧹 Avto-tozalash) — buyruq esa uni BIR
    QADAMDA ochadi: oraliq menyular yo'q, foydalanuvchi darhol
    toggle'lar, ✍️ imzo, 🧪 namuna va [◀️ Orqaga] tugmalarini ko'radi.

    Ekran ``stgs_clean`` callback'i bilan AYNAN bir manbadan chiziladi
    (``_load_cleaner_state`` / ``_build_cleaner_text`` /
    ``_build_cleaner_keyboard``) — matn yoki klaviatura ikkinchi nusxasi
    yo'q. FSM tozalanadi (yarim tugagan eski oqim davom etmaydi), til
    foydalanuvchi profilidan olinadi va DB o'qish fail-soft (baza
    javob bermasa standart holat ko'rsatiladi).

    Handler global ``CommandHandler`` sifatida ro'yxatdan o'tadi
    (``/settings`` va ``/help`` bilan bir qatorda) — shu sababli buyruq
    faol FSM holatidan qat'i nazar DARHOL ishlaydi.
    """
    clear_fsm_data(context)
    user = getattr(update, "effective_user", None)
    user_id = getattr(user, "id", None)
    lang = await _user_lang(context, user_id)
    from handlers.navigation import SECTION_SETTINGS, remember_section

    remember_section(context, SECTION_SETTINGS)
    if user_id is None:
        # Foydalanuvchi aniqlanmagan (nazariy holat) — DB o'qilmaydi,
        # standart (o'chirilgan) holat ko'rsatiladi.
        values = {key: bool(SETTING_DEFAULTS.get(key, False))
                  for key in CLEANER_SETTING_KEYS}
        state = {"values": values, "signature": ""}
    else:
        state = await _load_cleaner_state(user_id)
    text = _build_cleaner_text(state["values"], state["signature"], lang)
    keyboard = _build_cleaner_keyboard(state["values"], lang)

    message = getattr(update, "message", None)
    if message is not None:
        await message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
        return _end_state()
    # Zaxira yo'l (masalan, buyruq rasm izohida kelganda ``message``
    # o'rniga faqat chat bo'ladi) — ekran baribir chiziladi.
    chat = getattr(update, "effective_chat", None)
    if chat is not None:
        await context.bot.send_message(
            chat.id, text, reply_markup=keyboard, parse_mode="HTML",
        )
    return _end_state()


async def _render_profile_screen(query, context, user_id: int, lang: str,
                                 is_admin: bool) -> None:
    """👤 Profil — ID, obuna holati, balans/kreditlar va asosiy hisob ma'lumotlari.

    3-QISM: Profil va Sozlamalar birlashdi — bu endi YAGONA Sozlamalar
    ekrani: cabinet_title (ID, so'rovlar, seriya) + obuna holati + 7
    tugmali inline menyu (Til / Post sozlamalari / Bildirishnomalar /
    Do'stlarni taklif / To'lovlar tarixi / Qo'llab-quvvatlash / Yopish).
    """
    from handlers.start import (
        build_cabinet_text, cabinet_credits_text, load_cabinet_data, peek_profile,
    )
    from utils.helpers import get_smart_reply_ad_async

    stats, channels_count, user_code = await load_cabinet_data(user_id)
    credits_text = cabinet_credits_text(is_admin, stats["ai_credits"], lang)
    streak_text = get_text("cabinet_streak", lang, streak=stats.get("streak", 0))
    try:
        ad_line = await get_smart_reply_ad_async(user_id)
    except Exception:
        ad_line = ""
    text = build_cabinet_text(
        user_id, user_code, credits_text, streak_text,
        channels_count, stats["referrals_count"], lang, ad_line,
    )

    # ⭐️ Obuna holati — profil kartasining majburiy qismi (spek: ID, obuna
    # holati, balans/kreditlar va asosiy hisob ma'lumotlari).
    prof = peek_profile(user_id)
    if prof is not None:  # RAM profil (0 DB); faqat ko'rsatish uchun
        plan = {"plan_type": prof["plan_type"], "expires_at": prof["expires_at"]}
    else:
        try:
            plan = await db.run_db(db.get_user_plan, user_id)
        except Exception:
            plan = {"plan_type": "free", "expires_at": None}
    plan_type = str((plan or {}).get("plan_type") or "free").lower()
    expires_at = (plan or {}).get("expires_at")
    if plan_type in ("pro", "enterprise") and expires_at:
        try:
            date_text = expires_at.strftime("%d.%m.%Y")
        except AttributeError:
            date_text = str(expires_at)[:10]
        sub_line = settings_stats_t("ss_profile_sub_pro", lang, date=date_text)
    else:
        sub_line = settings_stats_t("ss_profile_sub_free", lang)
    text = f"{text}\n{sub_line}"

    await _edit_or_reply(query, text, get_profile_menu_keyboard(lang))


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
    """Toggle tugmalari (2 tadan qator) + [◀️ Orqaga].

    🧹 NESTED «Ko'proq sozlamalar»: ``post`` doirasidagi [◀️ Orqaga]
    qatoriga IKKINCHI tugma sifatida [⚙️ Ko'proq] qo'shiladi. Tartib
    ataylab shunday — [◀️ Orqaga] qatordagi BIRINCHI tugma bo'lib qoladi
    (mavjud test kontrakti buzilmaydi), ⚙️ Sozlamalar hub'i esa 10 tugma
    bo'lib QOLADI: yangi bo'lim hub'ga emas, chuqurroqqa joylashadi.
    """
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
    back_row = [_inline(
        settings_stats_t("ss_btn_back", lang), callback_data="stgs_hub",
    )]
    if scope == "post":
        # ⚙️ Ko'proq sozlamalar — nested submenyu (🧹 Auto-cleaner shu yerda).
        back_row.append(_inline(
            settings_stats_t("ss_btn_more", lang), callback_data="stgs_more",
        ))
    rows.append(back_row)
    return InlineKeyboardMarkup(rows)


def _inline(text: str, callback_data: str):
    from telegram import InlineKeyboardButton
    return InlineKeyboardButton(text, callback_data=callback_data)


def _toggle_screen_meta(scope: str):
    """Toggle scope uchun kalitlar va matn kalitlarini qaytaradi."""
    if scope == "notif":
        return NOTIF_SETTING_KEYS, "ss_notif_title", "ss_notif_hint"
    if scope == "clean":
        return CLEANER_SETTING_KEYS, "ss_clean_title", "ss_clean_hint"
    return POST_SETTING_KEYS, "ss_post_title", "ss_post_hint"


async def _edit_toggle_screen(query, text: str, markup: InlineKeyboardMarkup,
                              *, allow_reply_fallback: bool = True) -> None:
    """Toggle ekranini tahrirlaydi.

    Parent ekran ochilishida eski xavfsiz fallback saqlanadi. Toggle bosilganda
    esa qat'iy talab bo'yicha yangi ``reply_text/send_message`` yuborilmaydi:
    mavjud xabar joyida yangilanadi, ``MESSAGE_NOT_MODIFIED`` kabi holatda ham
    faqat reply markup yangilashga uriniladi.
    """
    if allow_reply_fallback:
        await _edit_or_reply(query, text, markup)
        return
    try:
        await query.edit_message_text(
            text, reply_markup=markup, parse_mode="HTML",
        )
    except Exception:
        try:
            await query.edit_message_reply_markup(reply_markup=markup)
        except Exception:
            logger.debug("Toggle ekranini joyida tahrirlab bo'lmadi", exc_info=True)


async def _render_toggles(query, user_id: int, scope: str, lang: str,
                          *, allow_reply_fallback: bool = True,
                          values: dict | None = None) -> None:
    """🔔 Bildirishnomalar / 🎨 Post sozlamalari / 🧹 Auto-cleaner ekrani.

    ``clean`` doirasi BOY ekranga yo'naltiriladi (toggle'lar + ✍️ imzo
    boshqaruvi + 🧪 namuna) — shu sababli ``stgs_tgl:clean:*`` callback'lari
    mavjud OQ RO'YXAT/fail-closed mantiqidan o'tib, o'z ekraniga qaytadi.
    """
    keys, title, hint = _toggle_screen_meta(scope)
    if values is None:
        values = await db.run_db(
            db.get_user_settings_bulk, user_id, list(keys), SETTING_DEFAULTS,
        )
    if scope == "clean":
        await _render_cleaner(
            query, user_id, lang, values,
            allow_reply_fallback=allow_reply_fallback,
        )
        return
    text = _build_toggles_text(title, hint, keys, values, lang)
    markup = _build_toggles_keyboard(scope, keys, values, lang)
    await _edit_toggle_screen(
        query, text, markup, allow_reply_fallback=allow_reply_fallback,
    )


async def _toggle_setting_and_edit(query, user_id: int, scope: str,
                                   key: str, lang: str) -> tuple[bool, bool]:
    """Sozlamani teskari holatga o'tkazadi va xabarni joyida yangilaydi."""
    keys, _title, _hint = _toggle_screen_meta(scope)
    values = await db.run_db(
        db.get_user_settings_bulk, user_id, list(keys), SETTING_DEFAULTS,
    )
    new_value = not bool(values.get(key, SETTING_DEFAULTS.get(key, False)))
    saved = await db.run_db(db.set_user_setting, user_id, key, new_value)
    if saved:
        values[key] = new_value
    await _render_toggles(
        query, user_id, scope, lang,
        allow_reply_fallback=False,
        values=values,
    )
    return bool(saved), new_value


def _fmt_payment_date(value) -> str:
    """To'lov sanasini ixcham ko'rinishda qaytaradi (xato → '—')."""
    if value is None:
        return "—"
    try:
        return value.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)[:16]


async def _render_payments(query, user_id: int, lang: str,
                           *, back_callback: str = "stgs_hub") -> None:
    """💳 To'lovlar tarixi ekrani (settings yoki PRO parentiga qaytadi)."""
    history = await db.run_db(db.get_user_payment_history, user_id, 10)
    back_markup = InlineKeyboardMarkup([[
        _inline(settings_stats_t("ss_btn_back", lang), callback_data=back_callback),
    ]])
    if not history:
        await _edit_or_reply(
            query, settings_stats_t("ss_pay_empty", lang), back_markup,
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
    await _edit_or_reply(query, "\n".join(lines), back_markup)


async def _render_referral(query, context, user_id: int, lang: str,
                           is_admin: bool) -> None:
    """👥 Do'stlarni taklif qilish — referral menyu (ulashish + kunlik bonus)."""
    from handlers.start import cabinet_credits_text

    # Username config/cache'dan olinadi; Telegram getMe round-trip'i referral
    # ekranini ochishni bloklamasin. Test/embedded botlarda bot.username ustun.
    bot_username = (getattr(context.bot, "username", None) or BOT_USERNAME or "").strip().lstrip("@")
    stats = await db.run_db(db.get_referral_stats, user_id)
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
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
        except Exception as _silent_exc:
            log_silent_failure("handlers.settings:_render_help", _silent_exc, lang=lang)
    text = _cached_static_text(
        "help", lang,
        lambda: get_text("help_guide", lang,
                         support=_help_support_line(lang)),
    )
    help_kb = get_help_keyboard(SUPPORT_USERNAME, lang)
    combined = InlineKeyboardMarkup(
        help_kb.inline_keyboard + get_settings_back_keyboard(lang).inline_keyboard
    )
    await _edit_or_reply(query, text, combined)


async def _render_about(query, lang: str) -> None:
    """ℹ️ Bot haqida — bot versiyasi, maqsadi va qisqa yo'riqnoma."""
    def _build() -> str:
        support = f"@{SUPPORT_USERNAME}" if SUPPORT_USERNAME else get_text(
            "help_admin_fallback", lang
        )
        return settings_stats_t(
            "ss_about_text", lang, support=support, version=BOT_VERSION,
        )

    text = _cached_static_text("about", lang, _build)
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
    # ⚡ DARHOL JAVOB: tugma spinner'i til (DB) o'qishdan OLDIN to'xtatiladi.
    try:
        await query.answer()
    except Exception as _silent_exc:
        log_silent_failure("handlers.settings:settings_menu_callback:647", _silent_exc, user_id=query.from_user.id)
    data = query.data or ""
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS_SET
    lang = await ensure_user_lang(context, user_id)

    if data == "stgs_back":
        # ◀️ Orqaga — sozlamalar yopiladi va asosiy menyu qaytadi.
        try:
            await query.message.delete()
        except Exception as _silent_exc:
            log_silent_failure("handlers.settings:settings_menu_callback:654", _silent_exc)
        try:
            await query.message.reply_text(
                get_text("msg_closed", lang),
                reply_markup=get_main_keyboard(is_admin, lang=lang),
            )
        except Exception as _silent_exc:
            log_silent_failure("handlers.settings:settings_menu_callback:661", _silent_exc)
        return

    if data == "stgs_rewards":
        await _render_rewards_hub(query, lang)
        return

    if data == "stgs_help_hub":
        await _render_help_hub(query, lang)
        return

    if data == "stgs_privacy":
        # 🔐 SPRINT 1: maxfiylik siyosati ekrani (matn — translations/privacy.py).
        from handlers.privacy import _render_policy

        await _render_policy(query, context, user_id, lang)
        return

    if data in ("stgs_delete_data", "stgs_privacy_del"):
        # 🗑 O'chirish oqimi: AVVAL tasdiq ekrani (ma'lumot hali tegilmaydi),
        # bajarish esa alohida handlerda (``stgs_privacy_del_ok``).
        from handlers.privacy import _render_delete_confirm

        await _render_delete_confirm(query, context, user_id, lang)
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

    if data == "stgs_more":
        # ⚙️ Ko'proq sozlamalar — NESTED submenyu (🧹 Auto-cleaner shu yerda).
        # Joylashuv ataylab chuqur: ⚙️ Sozlamalar hub'i 10 tugma bo'lib qoladi.
        await _render_more_settings(query, lang)
        return

    if data == "stgs_clean":
        # 🧹 Post Auto-Cleaner & Custom Signature sozlama ekrani.
        await _render_cleaner(query, user_id, lang)
        return

    if data == "stgs_clean_demo":
        # 🧪 Namuna — tozalash natijasini real namunada ko'rsatish.
        await _render_cleaner_demo(query, user_id, lang)
        return

    if data == "stgs_clean_sig_clear":
        # 🗑 Saqlangan imzoni o'chirish.
        await _clear_cleaner_signature(query, context, user_id, lang)
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
        saved, new_value = await _toggle_setting_and_edit(query, user_id, scope, key, lang)
        # ``_toggle_setting_and_edit`` DB'dan oldingi qiymatlarni olib, bosilgan
        # kalitni teskari holatga o'tkazadi va xabarni FAQAT joyida tahrirlaydi
        # (reply_text/send_message fallback yo'q).
        toast_key = "ss_switched_on" if new_value else "ss_switched_off"
        if not saved:
            logger.warning("Sozlamani saqlab bo'lmadi: user_id=%s key=%s", user_id, key)
        try:
            await query.answer(settings_stats_t(toast_key, lang), show_alert=False)
        except Exception as _silent_exc:
            log_silent_failure("handlers.settings:settings_menu_callback:746", _silent_exc)
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
