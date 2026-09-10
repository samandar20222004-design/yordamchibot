import re
from telegram import ReplyKeyboardMarkup
from telegram.ext import filters
from locales.translations import get_text, get_lang, normalize_lang

# ============================================================
# STANDART MENYU TUGMALARI (Constants)
# ============================================================
BTN_NEW_POST = get_text("btn_new_post", "uz")
BTN_AI_STUDIO = get_text("btn_ai_studio", "uz")
BTN_PENDING = get_text("btn_pending", "uz")
BTN_PENDING_RU = get_text("btn_pending", "ru")
BTN_PENDING_EN = get_text("btn_pending", "en")
BTN_SETTINGS = get_text("btn_settings", "uz")
BTN_CONVERTER = get_text("cab_btn_converter", "uz")
BTN_HELP = get_text("btn_help", "uz")
BTN_EXTRAS = get_text("btn_extras", "uz")
BTN_BACK = get_text("btn_main_menu", "uz")

# Rus tilidagi asosiy menyu (MessageHandler Regex ikkala tilni tanishi uchun)
BTN_NEW_POST_RU = get_text("btn_new_post", "ru")
BTN_AI_STUDIO_RU = get_text("btn_ai_studio", "ru")
BTN_SETTINGS_RU = get_text("btn_settings", "ru")
BTN_HELP_RU = get_text("btn_help", "ru")
BTN_EXTRAS_RU = get_text("btn_extras", "ru")
BTN_PREMIUM_RU = get_text("btn_premium", "ru")
# Har qanday ko'p bosqichli jarayonni (FSM) to'xtatuvchi umumiy tugma.
BTN_CANCEL = get_text("btn_cancel", "uz")
BTN_BACK_RU = get_text("btn_main_menu", "ru")
BTN_CANCEL_RU = get_text("btn_cancel", "ru")
BTN_CONVERTER_RU = get_text("cab_btn_converter", "ru")

# Inglizcha variantlar — MessageHandler regex'iga (uz/ru/en) qo'shiladi.
# EN klaviaturada bosilgan barcha asosiy menyu tugmalari routing'da tanilishi
# uchun (aks holda global fallback'ga tushib ketardi).
BTN_NEW_POST_EN = get_text("btn_new_post", "en")
BTN_AI_STUDIO_EN = get_text("btn_ai_studio", "en")
BTN_PREMIUM_EN = get_text("btn_premium", "en")
BTN_SETTINGS_EN = get_text("btn_settings", "en")
BTN_HELP_EN = get_text("btn_help", "en")
BTN_EXTRAS_EN = get_text("btn_extras", "en")
BTN_BACK_EN = get_text("btn_main_menu", "en")
BTN_CANCEL_EN = get_text("btn_cancel", "en")

# ============================================================
# 🆕 SODDA KLAVIATURA — yangi foydalanuvchilar (1-3 kun) uchun
# ============================================================
# Standart 6 talik menyu o'rniga 3 ta katta, harakatga undovchi tugma va
# pastda bitta kichik "to'liq menyu" tugmasi. Qachon ko'rsatilishi
# ``onboarding.should_show_simple_menu`` da hal qilinadi.
BTN_QUICK_AI_POST = get_text("quick_btn_ai_post", "uz")
BTN_QUICK_PHOTO_POST = get_text("quick_btn_photo_post", "uz")
BTN_QUICK_ADD_CHANNEL = get_text("quick_btn_add_channel", "uz")
BTN_OPEN_FULL_MENU = get_text("quick_btn_full_menu", "uz")

# Ruscha variantlar — MessageHandler Regex ikkala tilni tanishi uchun
BTN_QUICK_AI_POST_RU = get_text("quick_btn_ai_post", "ru")
BTN_QUICK_PHOTO_POST_RU = get_text("quick_btn_photo_post", "ru")
BTN_QUICK_ADD_CHANNEL_RU = get_text("quick_btn_add_channel", "ru")
BTN_OPEN_FULL_MENU_RU = get_text("quick_btn_full_menu", "ru")
BTN_QUICK_AI_POST_EN = get_text("quick_btn_ai_post", "en")
BTN_QUICK_PHOTO_POST_EN = get_text("quick_btn_photo_post", "en")
BTN_QUICK_ADD_CHANNEL_EN = get_text("quick_btn_add_channel", "en")
BTN_OPEN_FULL_MENU_EN = get_text("quick_btn_full_menu", "en")

# Sodda menyudagi barcha tugmalar (uz + ru + en) — routing/audit uchun yagona manba.
QUICK_MENU_BUTTONS = (
    BTN_QUICK_AI_POST, BTN_QUICK_PHOTO_POST, BTN_QUICK_ADD_CHANNEL, BTN_OPEN_FULL_MENU,
    BTN_QUICK_AI_POST_RU, BTN_QUICK_PHOTO_POST_RU,
    BTN_QUICK_ADD_CHANNEL_RU, BTN_OPEN_FULL_MENU_RU,
    BTN_QUICK_AI_POST_EN, BTN_QUICK_PHOTO_POST_EN,
    BTN_QUICK_ADD_CHANNEL_EN, BTN_OPEN_FULL_MENU_EN,
)

# Orqaga moslik (Aliases)
BTN_AI_POST = "🤖 AI Post Yordamchi"
BTN_CABINET = BTN_SETTINGS
BTN_MAIN_MENU = BTN_BACK

# --- Kabinet ichidagi tugmalar (uz) ---
BTN_CHANNELS = get_text("cab_btn_channels", "uz")
BTN_DAILY_BONUS = get_text("cab_btn_daily_bonus", "uz")
BTN_INVITE = get_text("cab_btn_invite", "uz")
BTN_TRANSFER = get_text("cab_btn_transfer", "uz")

# --- Kabinet ichidagi tugmalar (ru) — Regex filter ikkala tilni tanishi uchun ---
BTN_CHANNELS_RU = get_text("cab_btn_channels", "ru")
BTN_DAILY_BONUS_RU = get_text("cab_btn_daily_bonus", "ru")
BTN_INVITE_RU = get_text("cab_btn_invite", "ru")
BTN_TRANSFER_RU = get_text("cab_btn_transfer", "ru")

# --- Kabinet ichidagi tugmalar (en) — Routing EN tilini ham taniydi ---
BTN_CHANNELS_EN = get_text("cab_btn_channels", "en")
BTN_CONVERTER_EN = get_text("cab_btn_converter", "en")
BTN_DAILY_BONUS_EN = get_text("cab_btn_daily_bonus", "en")
BTN_INVITE_EN = get_text("cab_btn_invite", "en")
BTN_TRANSFER_EN = get_text("cab_btn_transfer", "en")

# --- Admin tugmalari ---
BTN_ADMIN_PANEL = "⚙️ Admin Panel"
# RU variant — qo'lda yuborilgan ruscha matn ham admin panelga tushadi
BTN_ADMIN_PANEL_RU = "⚙️ Панель администратора"
BTN_STATS = "📊 Statistika"
BTN_BROADCAST = "✉️ Xabar yuborish"
BTN_ALL_POSTS = "📋 Barcha postlar"
BTN_ALL_CHANNELS = "📋 Barcha kanal/guruhlar"
BTN_SPONSORS = "📢 Majburiy obuna"
BTN_ADD_SPONSOR = "➕ Homiy kanal qo'shish"
# Yagona Reklama markazi: avvalgi "📢 Kanal posti reklamasi" va
# "🤖 Bot xabari reklamasi" tugmalari bitta hub menyusiga birlashtirildi.
# Ikkala eski nom routing'da alias sifatida qabul qilinadi (eski klaviatura
# bilan yozilgan xabarlar buzilmasligi uchun).
BTN_ADS = "🎯 Reklama markazi"
BTN_CHANNEL_AD = "📢 Kanal posti reklamasi"
BTN_BOT_REPLY_AD = "🤖 Bot xabari reklamasi"
BTN_POST_TAG = "🏷 Post nishoni"
BTN_AI_SETTINGS = "⚙️ AI parametrlar"
BTN_CACHE_DB = "🗄️ DB / Kesh holati"

# --- Kanal & Post yaratish tugmalari ---
BTN_ADD_CHANNEL = "➕ Kanal/Guruh qo'shish"
BTN_QUEUE = get_text("btn_queue", "uz")
BTN_QUEUE_RU = get_text("btn_queue", "ru")
BTN_QUEUE_EN = get_text("btn_queue", "en")
BTN_CONTENT_PLAN = "🧠 Kontent-reja"
BTN_ANALYTICS = "📊 Analitika"
BTN_PREMIUM = get_text("btn_premium", "uz")
BTN_CHANNEL_EXTRACT = "📢 Ochiq kanaldan olish"
BTN_ALL_CHANNELS_TARGET = get_text("np_btn_all_channels", "uz")
BTN_SKIP_BUTTON = get_text("np_btn_skip", "uz")
# Inline URL tugma quruvchi (yangi ixtiyoriy qadam)
BTN_ADD_URL_BUTTON = get_text("np_btn_url_add", "uz")
BTN_SKIP_URL_BUTTON = get_text("np_btn_skip_url", "uz")
BTN_REACT_THUMBS_UP = "👍"
BTN_REACT_HEART = "❤️"
BTN_REACT_FIRE = "🔥"
BTN_REACT_CLAP = "👏"
BTN_REACT_DEFAULT = "👍 ❤️ 🔥 👏"
BTN_NO_REACT = get_text("np_btn_no_reactions", "uz")

# Auto-delete
BTN_DEL_NEVER = get_text("np_btn_del_never", "uz")
BTN_DEL_12H = get_text("np_btn_del_12h", "uz")
BTN_DEL_24H = get_text("np_btn_del_24h", "uz")
BTN_DEL_48H = get_text("np_btn_del_48h", "uz")
BTN_DEL_72H = get_text("np_btn_del_72h", "uz")

# Vaqt turlari
BTN_T_5MIN = get_text("np_btn_time_5m", "uz")
BTN_T_15MIN = get_text("np_btn_time_15m", "uz")
BTN_T_1H = get_text("np_btn_time_1h", "uz")
BTN_T_DAILY = get_text("np_btn_time_daily", "uz")
BTN_T_WEEKLY = get_text("np_btn_time_weekly", "uz")

# Muddatlar
BTN_DUR_1W = get_text("np_btn_dur_1w", "uz")
BTN_DUR_1M = get_text("np_btn_dur_1m", "uz")
BTN_DUR_3M = get_text("np_btn_dur_3m", "uz")
BTN_DUR_6M = get_text("np_btn_dur_6m", "uz")
BTN_DUR_1Y = get_text("np_btn_dur_1y", "uz")
BTN_DUR_INF = get_text("np_btn_dur_inf", "uz")

# --- Rus tilidagi variantlar (3-QISM i18n) ---
BTN_ALL_CHANNELS_TARGET_RU = get_text("np_btn_all_channels", "ru")
BTN_SKIP_BUTTON_RU = get_text("np_btn_skip", "ru")
BTN_ADD_URL_BUTTON_RU = get_text("np_btn_url_add", "ru")
BTN_SKIP_URL_BUTTON_RU = get_text("np_btn_skip_url", "ru")
BTN_NO_REACT_RU = get_text("np_btn_no_reactions", "ru")
BTN_DEL_NEVER_RU = get_text("np_btn_del_never", "ru")
BTN_DEL_12H_RU = get_text("np_btn_del_12h", "ru")
BTN_DEL_24H_RU = get_text("np_btn_del_24h", "ru")
BTN_DEL_48H_RU = get_text("np_btn_del_48h", "ru")
BTN_DEL_72H_RU = get_text("np_btn_del_72h", "ru")
BTN_T_5MIN_RU = get_text("np_btn_time_5m", "ru")
BTN_T_15MIN_RU = get_text("np_btn_time_15m", "ru")
BTN_T_1H_RU = get_text("np_btn_time_1h", "ru")
BTN_T_DAILY_RU = get_text("np_btn_time_daily", "ru")
BTN_T_WEEKLY_RU = get_text("np_btn_time_weekly", "ru")
BTN_DUR_1W_RU = get_text("np_btn_dur_1w", "ru")
BTN_DUR_1M_RU = get_text("np_btn_dur_1m", "ru")
BTN_DUR_3M_RU = get_text("np_btn_dur_3m", "ru")
BTN_DUR_6M_RU = get_text("np_btn_dur_6m", "ru")
BTN_DUR_1Y_RU = get_text("np_btn_dur_1y", "ru")
BTN_DUR_INF_RU = get_text("np_btn_dur_inf", "ru")
BTN_BACK_TO_CONFIRM_RU = get_text("np_btn_back_confirm", "ru")

WEEKDAY_BUTTONS = [get_text(f"np_weekday_{i}", "uz") for i in range(7)]
WEEKDAY_BUTTONS_RU = [get_text(f"np_weekday_{i}", "ru") for i in range(7)]
WEEKDAY_BUTTONS_EN = [get_text(f"np_weekday_{i}", "en") for i in range(7)]
WEEKDAY_MAP = {name: idx for idx, name in enumerate(WEEKDAY_BUTTONS)}
WEEKDAY_MAP_RU = {name: idx for idx, name in enumerate(WEEKDAY_BUTTONS_RU)}
WEEKDAY_MAP_EN = {name: idx for idx, name in enumerate(WEEKDAY_BUTTONS_EN)}
WEEKDAY_LABELS = {idx: name for name, idx in WEEKDAY_MAP.items()}
WEEKDAY_LABELS_RU = {idx: name for name, idx in WEEKDAY_MAP_RU.items()}
WEEKDAY_LABELS_EN = {idx: name for name, idx in WEEKDAY_MAP_EN.items()}


def exact(*texts):
    pattern = "^(" + "|".join(re.escape(t) for t in texts) + ")$"
    return filters.Regex(pattern)


def exact_i18n(*keys):
    """Asosiy menyu tugmalarini uz/ru/en tillarida taniydigan Regex filter."""
    texts = []
    for key in keys:
        for lang in ("uz", "ru", "en"):
            t = get_text(key, lang)
            if t not in texts:
                texts.append(t)
    return exact(*texts)


def get_main_keyboard(is_admin=False, lang="uz", context=None):
    # Yangi tartib: ⭐️ Premium chapda, 👤 Kabinet & Sozlamalar o'ngda (2-qator).
    if context is not None:
        lang = get_lang(context, lang)
    keyboard = [
        [get_text("btn_new_post", lang), get_text("btn_ai_studio", lang)],
        [get_text("btn_premium", lang), get_text("btn_settings", lang)],
        [get_text("btn_help", lang), get_text("btn_extras", lang)],
    ]
    if is_admin:
        keyboard.append([BTN_ADMIN_PANEL])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_simple_keyboard(lang="uz", context=None):
    """🆕 Yangi foydalanuvchi uchun SODDA reply-klaviatura (uz/ru).

    Standart 6 talik menyu o'rniga 3 ta katta va tushunarli tugma:

        [🚀 1 daqiqada post yaratish]   — AI orqali post yozish
        [🖼 Rasmdan post olish]         — Vision (rasm → post) oqimi
        [📢 Kanal ulash]                — kanal/guruh ulash
        [⚙️ To'liq menyuni ochish]      — darhol to'liq menyuga o'tish

    Har bir tugma alohida qatorda (bitta ustun) — mobil ekranda maksimal
    katta va chalkashsiz ko'rinadi. ``context`` berilsa til
    ``context.user_data['lang']`` dan olinadi (``get_main_keyboard`` kabi).
    """
    if context is not None:
        lang = get_lang(context, lang)
    keyboard = [
        [get_text("quick_btn_ai_post", lang)],
        [get_text("quick_btn_photo_post", lang)],
        [get_text("quick_btn_add_channel", lang)],
        [get_text("quick_btn_full_menu", lang)],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_cabinet_keyboard(lang="uz", context=None):
    """Kabinet reply-klaviaturasi — foydalanuvchi tilida (uz/ru).

    ``context`` berilsa, til ``context.user_data['lang']`` dan olinadi
    (xuddi :func:`get_main_keyboard` kabi).
    """
    if context is not None:
        lang = get_lang(context, lang)
    keyboard = [
        [get_text("cab_btn_channels", lang), get_text("cab_btn_converter", lang)],
        [get_text("cab_btn_daily_bonus", lang)],
        [get_text("cab_btn_invite", lang), get_text("cab_btn_transfer", lang)],
        [get_text("btn_main_menu", lang)]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_cancel_keyboard(lang="uz", context=None):
    """Jarayonni to'xtatish klaviaturasi: Bekor qilish + Asosiy menyu.

    Ikkala tugma ham FSM holatini tozalaydi — foydalanuvchi hech qachon
    "band" holatda qolib ketmaydi. Til berilmasa o'zbekcha (eski chaqiruvlar
    uchun moslik saqlanadi).
    """
    if context is not None:
        lang = get_lang(context, lang)
    return ReplyKeyboardMarkup(
        [[get_text("btn_cancel", lang), get_text("btn_main_menu", lang)]],
        resize_keyboard=True,
    )


def get_button_prompt_keyboard(lang="uz"):
    """Postga havola tugma qo'shish — ixtiyoriy qadam.

    Yangi: "[🔗 URL tugma qo'shish]" / "[⏭ O'tkazib yuborish]" tugmalari.
    Tezkor sarlavhalar va AI yordamchi tugmasi saqlab qolingan.
    Barcha yorliqlar foydalanuvchi tilida (``lang``) chiqadi.
    """
    return ReplyKeyboardMarkup(
        [
            [get_text("np_btn_ai_assistant", lang)],
            [get_text("np_btn_title_details", lang), get_text("np_btn_title_join", lang)],
            [get_text("np_btn_title_site", lang), get_text("np_btn_title_contact", lang)],
            [get_text("np_btn_url_add", lang)],
            [get_text("np_btn_skip_url", lang)],
            [get_text("btn_main_menu", lang)]
        ],
        resize_keyboard=True
    )


def get_reactions_keyboard(lang="uz"):
    return ReplyKeyboardMarkup(
        [
            [BTN_REACT_THUMBS_UP, BTN_REACT_HEART, BTN_REACT_FIRE, BTN_REACT_CLAP],
            [get_text("np_btn_no_reactions", lang)],
            [get_text("btn_main_menu", lang)]
        ],
        resize_keyboard=True
    )


def get_auto_delete_keyboard(lang="uz"):
    return ReplyKeyboardMarkup(
        [
            [get_text("np_btn_del_never", lang)],
            [get_text("np_btn_del_12h", lang), get_text("np_btn_del_24h", lang)],
            [get_text("np_btn_del_48h", lang), get_text("np_btn_del_72h", lang)],
            [get_text("btn_main_menu", lang)]
        ],
        resize_keyboard=True
    )


def get_admin_panel_keyboard():
    """Admin panel reply-klaviaturasi.

    UX: reklama boshqaruvi endi BITTA tugada — "🎯 Reklama markazi".
    Avval shu qatorda kanallar/obotlar uchun alohida reklama tugmalari
    bor edi; ular hub menyusidagi bo'limlarga birlashtirildi.
    """
    return ReplyKeyboardMarkup(
        [
            [BTN_SPONSORS, BTN_STATS],
            [BTN_ADS, BTN_POST_TAG],
            [BTN_AI_SETTINGS, BTN_CACHE_DB],
            [BTN_BROADCAST, BTN_ALL_POSTS],
            [BTN_ALL_CHANNELS, BTN_BACK],
        ],
        resize_keyboard=True,
    )


def get_sponsors_keyboard():
    return ReplyKeyboardMarkup(
        [[BTN_ADD_SPONSOR], [BTN_ADMIN_PANEL, BTN_BACK]],
        resize_keyboard=True
    )


def get_time_keyboard(lang="uz"):
    return ReplyKeyboardMarkup(
        [
            [get_text("np_btn_time_5m", lang), get_text("np_btn_time_15m", lang), get_text("np_btn_time_1h", lang)],
            [get_text("np_btn_time_daily", lang)],
            [get_text("np_btn_time_weekly", lang)],
            [get_text("btn_main_menu", lang)],
        ],
        resize_keyboard=True,
    )


def get_ai_time_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_T_5MIN, BTN_T_15MIN, BTN_T_1H],
            [BTN_BACK],
        ],
        resize_keyboard=True,
    )


def get_duration_keyboard(lang="uz"):
    return ReplyKeyboardMarkup(
        [
            [get_text("np_btn_dur_1w", lang), get_text("np_btn_dur_1m", lang), get_text("np_btn_dur_3m", lang)],
            [get_text("np_btn_dur_6m", lang), get_text("np_btn_dur_1y", lang), get_text("np_btn_dur_inf", lang)],
            [get_text("btn_main_menu", lang)]
        ],
        resize_keyboard=True
    )


# --- Kanal uslubi (Tone of Voice) ---
TONE_LABELS = {
    "formal": get_text("ch_tone_formal", "uz"),
    "friendly": get_text("ch_tone_friendly", "uz"),
    "concise": get_text("ch_tone_concise", "uz"),
    "engaging": get_text("ch_tone_engaging", "uz"),
}
TONE_LABELS_RU = {
    "formal": get_text("ch_tone_formal", "ru"),
    "friendly": get_text("ch_tone_friendly", "ru"),
    "concise": get_text("ch_tone_concise", "ru"),
    "engaging": get_text("ch_tone_engaging", "ru"),
}

BTN_TONE_FORMAL = TONE_LABELS["formal"]
BTN_TONE_FRIENDLY = TONE_LABELS["friendly"]
BTN_TONE_CONCISE = TONE_LABELS["concise"]
BTN_TONE_ENGAGING = TONE_LABELS["engaging"]


TONE_LABELS_EN = {
    "formal": get_text("ch_tone_formal", "en"),
    "friendly": get_text("ch_tone_friendly", "en"),
    "concise": get_text("ch_tone_concise", "en"),
    "engaging": get_text("ch_tone_engaging", "en"),
}


def get_tone_keyboard(lang="uz"):
    code = normalize_lang(lang)
    labels = TONE_LABELS_RU if code == "ru" else (TONE_LABELS_EN if code == "en" else TONE_LABELS)
    return ReplyKeyboardMarkup(
        [
            [labels["formal"], labels["friendly"]],
            [labels["concise"], labels["engaging"]],
            [get_text("btn_main_menu", lang)],
        ],
        resize_keyboard=True,
    )


def get_weekday_keyboard(lang="uz"):
    code = normalize_lang(lang)
    buttons = WEEKDAY_BUTTONS_RU if code == "ru" else (WEEKDAY_BUTTONS_EN if code == "en" else WEEKDAY_BUTTONS)
    rows = [[buttons[i], buttons[i + 1]] for i in range(0, 6, 2)]
    rows.append([buttons[6]])
    rows.append([get_text("btn_main_menu", lang)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)
