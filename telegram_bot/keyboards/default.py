import re
from telegram import ReplyKeyboardMarkup
from telegram.ext import filters
from locales.translations import get_text, get_lang

# ============================================================
# STANDART MENYU TUGMALARI (Constants)
# ============================================================
BTN_NEW_POST = get_text("btn_new_post", "uz")
BTN_AI_STUDIO = get_text("btn_ai_studio", "uz")
BTN_PENDING = "⏳ Kutilayotgan postlar"
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

# --- Admin tugmalari ---
BTN_ADMIN_PANEL = "⚙️ Admin Panel"
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
BTN_QUEUE = "📚 Navbat (Queue)"
BTN_CONTENT_PLAN = "🧠 Kontent-reja"
BTN_ANALYTICS = "📊 Analitika"
BTN_PREMIUM = get_text("btn_premium", "uz")
BTN_CHANNEL_EXTRACT = "📢 Ochiq kanaldan olish"
BTN_ALL_CHANNELS_TARGET = "🌐 Barchasiga birdaniga"
BTN_SKIP_BUTTON = "➡️ Tugmasiz davom etish"
# Inline URL tugma quruvchi (yangi ixtiyoriy qadam)
BTN_ADD_URL_BUTTON = "🔗 URL tugma qo'shish"
BTN_SKIP_URL_BUTTON = "⏭ O'tkazib yuborish"
BTN_REACT_THUMBS_UP = "👍"
BTN_REACT_HEART = "❤️"
BTN_REACT_FIRE = "🔥"
BTN_REACT_CLAP = "👏"
BTN_REACT_DEFAULT = "👍 ❤️ 🔥 👏"
BTN_NO_REACT = "➡️ Reaksiyasiz davom etish"

# Auto-delete
BTN_DEL_NEVER = "❌ O'chirilmasin (Doimiy)"
BTN_DEL_12H = "⏳ 12 soat"
BTN_DEL_24H = "⏳ 24 soat (1 kun)"
BTN_DEL_48H = "⏳ 48 soat (2 kun)"
BTN_DEL_72H = "⏳ 72 soat (3 kun)"

# Vaqt turlari
BTN_T_5MIN = "⚡ 5 daqiqa"
BTN_T_15MIN = "⚡ 15 daqiqa"
BTN_T_1H = "⚡ 1 soat"
BTN_T_DAILY = "🔁 Har kuni (bir vaqtda)"
BTN_T_WEEKLY = "📅 Har hafta (ma'lum kuni)"

# Muddatlar
BTN_DUR_1W = "1 hafta"
BTN_DUR_1M = "1 oy"
BTN_DUR_3M = "3 oy"
BTN_DUR_6M = "6 oy"
BTN_DUR_1Y = "1 yil"
BTN_DUR_INF = "♾ Cheksiz"

WEEKDAY_BUTTONS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
WEEKDAY_MAP = {name: idx for idx, name in enumerate(WEEKDAY_BUTTONS)}
WEEKDAY_LABELS = {idx: name for name, idx in WEEKDAY_MAP.items()}


def exact(*texts):
    pattern = "^(" + "|".join(re.escape(t) for t in texts) + ")$"
    return filters.Regex(pattern)


def exact_i18n(*keys):
    """Asosiy menyu tugmalarini uz/ru tillarida taniydigan Regex filter."""
    texts = []
    for key in keys:
        for lang in ("uz", "ru"):
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


def get_button_prompt_keyboard():
    """Postga havola tugma qo'shish — ixtiyoriy qadam.

    Yangi: "[🔗 URL tugma qo'shish]" / "[⏭ O'tkazib yuborish]" tugmalari.
    Tezkor sarlavhalar va AI yordamchi tugmasi saqlab qolingan.
    """
    return ReplyKeyboardMarkup(
        [
            ["✨ AI Yordamchi"],
            ["Batafsil", "Kanalga a'zo bo'lish"],
            ["Saytga o'tish", "Bog'lanish"],
            [BTN_ADD_URL_BUTTON],
            [BTN_SKIP_URL_BUTTON],
            [BTN_BACK]
        ],
        resize_keyboard=True
    )


def get_reactions_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_REACT_THUMBS_UP, BTN_REACT_HEART, BTN_REACT_FIRE, BTN_REACT_CLAP],
            [BTN_NO_REACT],
            [BTN_BACK]
        ],
        resize_keyboard=True
    )


def get_auto_delete_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_DEL_NEVER],
            [BTN_DEL_12H, BTN_DEL_24H],
            [BTN_DEL_48H, BTN_DEL_72H],
            [BTN_BACK]
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


def get_time_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_T_5MIN, BTN_T_15MIN, BTN_T_1H],
            [BTN_T_DAILY],
            [BTN_T_WEEKLY],
            [BTN_BACK],
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


def get_duration_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_DUR_1W, BTN_DUR_1M, BTN_DUR_3M],
            [BTN_DUR_6M, BTN_DUR_1Y, BTN_DUR_INF],
            [BTN_BACK]
        ],
        resize_keyboard=True
    )


# --- Kanal uslubi (Tone of Voice) ---
TONE_LABELS = {
    "formal": "👔 Rasmiy / Biznes",
    "friendly": "😊 Do'stona / Samimiy",
    "concise": "⚡️ Qisqa / Yangiliklar",
    "engaging": "🎉 Ko'ngilochar / Emotsional",
}

BTN_TONE_FORMAL = TONE_LABELS["formal"]
BTN_TONE_FRIENDLY = TONE_LABELS["friendly"]
BTN_TONE_CONCISE = TONE_LABELS["concise"]
BTN_TONE_ENGAGING = TONE_LABELS["engaging"]


def get_tone_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_TONE_FORMAL, BTN_TONE_FRIENDLY],
            [BTN_TONE_CONCISE, BTN_TONE_ENGAGING],
            [BTN_BACK],
        ],
        resize_keyboard=True,
    )


def get_weekday_keyboard():
    rows = [[WEEKDAY_BUTTONS[i], WEEKDAY_BUTTONS[i + 1]] for i in range(0, 6, 2)]
    rows.append([WEEKDAY_BUTTONS[6]])
    rows.append([BTN_BACK])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)
