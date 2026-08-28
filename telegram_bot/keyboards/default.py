import re
from telegram import ReplyKeyboardMarkup
from telegram.ext import filters

# --- Bosh menyu tugmalari ---
BTN_NEW_POST = "➕ Yangi post rejalashtirish"
BTN_AI_ASSISTANT = "🤖 AI Post Yordamchi"
BTN_PENDING = "⏳ Kutilayotgan postlar"
BTN_CABINET = "👤 Kabinet & Sozlamalar"
BTN_ADMIN_PANEL = "⚙️ Admin Panel"
BTN_MAIN_MENU = "🔙 Asosiy menyu"

# --- Kabinet ichidagi tugmalar ---
BTN_CHANNELS = "📢 Kanal/Guruhlar"
BTN_CONVERTER = "🔤 Matn o'girgich (Lotin ⇄ Kirill)"
BTN_INVITE = "🚀 Do'stlarni taklif qilish"

# --- Admin tugmalari ---
BTN_STATS = "📊 Statistika"
BTN_BROADCAST = "✉️ Xabar yuborish"
BTN_ALL_POSTS = "📋 Barcha postlar"
BTN_ALL_CHANNELS = "📋 Barcha kanal/guruhlar"
BTN_SPONSORS = "📢 Majburiy obuna"
BTN_ADD_SPONSOR = "➕ Homiy kanal qo'shish"
BTN_GLOBAL_AD = "🔗 Reklama havolasi"

# --- Kanal & Post yaratish tugmalari ---
BTN_ADD_CHANNEL = "➕ Kanal/Guruh qo'shish"
BTN_ALL_CHANNELS_TARGET = "🌐 Barchasiga birdaniga"
BTN_SKIP_BUTTON = "➡️ Tugmasiz davom etish"
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
    """Ixchamlashtirilgan asosiy menyu."""
    keyboard = [
        [BTN_NEW_POST, BTN_AI_ASSISTANT],
        [BTN_PENDING, BTN_CABINET]
    ]
    if is_admin:
        keyboard.append([BTN_ADMIN_PANEL])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_cabinet_keyboard():
    """Foydalanuvchining shaxsiy kabineti menyusi."""
    keyboard = [
        [BTN_CHANNELS, BTN_CONVERTER],
        [BTN_INVITE],
        [BTN_MAIN_MENU]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup([[BTN_MAIN_MENU]], resize_keyboard=True)

def get_button_prompt_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["Batafsil", "Kanalga a'zo bo'lish"],
            ["Saytga o'tish", "Bog'lanish"],
            [BTN_SKIP_BUTTON],
            [BTN_MAIN_MENU]
        ],
        resize_keyboard=True
    )

def get_reactions_keyboard():
    return ReplyKeyboardMarkup(
        [[BTN_REACT_DEFAULT], [BTN_NO_REACT], [BTN_MAIN_MENU]],
        resize_keyboard=True
    )

def get_auto_delete_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_DEL_NEVER],
            [BTN_DEL_12H, BTN_DEL_24H],
            [BTN_DEL_48H, BTN_DEL_72H],
            [BTN_MAIN_MENU]
        ],
        resize_keyboard=True
    )

def get_admin_panel_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_SPONSORS, BTN_GLOBAL_AD],
            [BTN_BROADCAST, BTN_STATS],
            [BTN_ALL_POSTS, BTN_ALL_CHANNELS],
            [BTN_MAIN_MENU],
        ],
        resize_keyboard=True,
    )

def get_sponsors_keyboard():
    return ReplyKeyboardMarkup(
        [[BTN_ADD_SPONSOR], [BTN_ADMIN_PANEL, BTN_MAIN_MENU]],
        resize_keyboard=True
    )

def get_time_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_T_5MIN, BTN_T_15MIN, BTN_T_1H],
            [BTN_T_DAILY],
            [BTN_T_WEEKLY],
            [BTN_MAIN_MENU],
        ],
        resize_keyboard=True,
    )

def get_duration_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_DUR_1M, BTN_DUR_3M, BTN_DUR_6M],
            [BTN_DUR_1Y, BTN_DUR_INF],
            [BTN_MAIN_MENU]
        ],
        resize_keyboard=True
    )

def get_weekday_keyboard():
    rows = [[WEEKDAY_BUTTONS[i], WEEKDAY_BUTTONS[i + 1]] for i in range(0, 6, 2)]
    rows.append([WEEKDAY_BUTTONS[6]])
    rows.append([BTN_MAIN_MENU])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)
