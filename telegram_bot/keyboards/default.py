import re
from telegram import ReplyKeyboardMarkup
from telegram.ext import filters

# ============================================================
# STANDART MENYU TUGMALARI (Constants)
# ============================================================
BTN_NEW_POST = "➕ Yangi post"
BTN_AI_STUDIO = "✨ AI Studio"
BTN_PENDING = "⏳ Kutilayotgan postlar"
BTN_SETTINGS = "👤 Kabinet & Sozlamalar"
BTN_CONVERTER = "🔤 Krill-Lotin konvertor"
BTN_HELP = "📖 Qo'llanma / Bot haqida"
BTN_EXTRAS = "⚙️ Qo'shimcha funksiyalar"
BTN_BACK = "🔙 Asosiy menyu"

# Orqaga moslik (Aliases)
BTN_AI_POST = "🤖 AI Post Yordamchi"
BTN_CABINET = BTN_SETTINGS
BTN_MAIN_MENU = BTN_BACK

# --- Kabinet ichidagi tugmalar ---
BTN_CHANNELS = "📢 Kanal/Guruhlar"
BTN_DAILY_BONUS = "🎁 Kunlik bonus"
BTN_BUY_AD_FREE = "💎 Reklamasiz postlar"
BTN_INVITE = "🚀 Do'stlarni taklif qilish"
BTN_TRANSFER = "🔄 Ballarni ulashish"

# --- Admin tugmalari ---
BTN_ADMIN_PANEL = "⚙️ Admin Panel"
BTN_STATS = "📊 Statistika"
BTN_BROADCAST = "✉️ Xabar yuborish"
BTN_ALL_POSTS = "📋 Barcha postlar"
BTN_ALL_CHANNELS = "📋 Barcha kanal/guruhlar"
BTN_SPONSORS = "📢 Majburiy obuna"
BTN_ADD_SPONSOR = "➕ Homiy kanal qo'shish"
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
BTN_PREMIUM = "⭐️ Premium"
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


def get_main_keyboard(is_admin=False):
    # Yangi tartib: ⭐️ Premium chapda, 👤 Kabinet & Sozlamalar o'ngda (2-qator).
    keyboard = [
        [BTN_NEW_POST, BTN_AI_STUDIO],
        [BTN_PREMIUM, BTN_SETTINGS],
        [BTN_HELP, BTN_EXTRAS],
    ]
    if is_admin:
        keyboard.append([BTN_ADMIN_PANEL])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_cabinet_keyboard():
    keyboard = [
        [BTN_CHANNELS, BTN_CONVERTER],
        [BTN_DAILY_BONUS, BTN_BUY_AD_FREE],
        [BTN_INVITE, BTN_TRANSFER],
        [BTN_BACK]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_cancel_keyboard():
    return ReplyKeyboardMarkup([[BTN_BACK]], resize_keyboard=True)


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
    return ReplyKeyboardMarkup(
        [
            [BTN_SPONSORS, BTN_STATS],
            [BTN_CHANNEL_AD, BTN_BOT_REPLY_AD, BTN_POST_TAG],
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
