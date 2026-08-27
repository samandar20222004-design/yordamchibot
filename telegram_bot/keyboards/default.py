import re
from telegram import ReplyKeyboardMarkup
from telegram.ext import filters

BTN_NEW_POST = "✍️ Yangi post rejalashtirish"
BTN_PENDING = "📋 Kutilayotgan postlar"
BTN_CHANNELS = "📢 Kanal/Guruhlar"
BTN_PROFILE = "👤 Profil & Taklif"
BTN_ADMIN_PANEL = "⚙️ Admin Panel"
BTN_STATS = "📊 Statistika"
BTN_MAIN_MENU = "🏠 Asosiy menyu"
BTN_ADD_CHANNEL = "➕ Kanal/Guruh qo'shish"
BTN_ALL_CHANNELS_TARGET = "🌐 Barchasiga birdaniga"
BTN_BROADCAST = "📨 Xabar yuborish"
BTN_ALL_POSTS = "🗂 Barcha postlar"
BTN_ALL_CHANNELS = "📡 Barcha kanal/guruhlar"
BTN_SKIP_BUTTON = "➡️ Tugmasiz davom etish"

# Admin yangi tugmalari
BTN_SPONSORS = "📢 Majburiy obuna"
BTN_ADD_SPONSOR = "➕ Homiy kanal qo'shish"
BTN_GLOBAL_AD = "📝 Reklama havolasi"

# Reaksiyalar tanlash tugmalari
BTN_REACTIONS_YES = "👍 Reaksiyalar qo'shilsin"
BTN_REACTIONS_NO = "➡️ Reaksiyasiz davom etish"

BTN_T_5MIN = "⚡️ 5 daqiqa"
BTN_T_15MIN = "⏱ 15 daqiqa"
BTN_T_30MIN = "⏳ 30 daqiqa"
BTN_T_1H = "🕒 1 soat"
BTN_T_2H = "🕕 2 soat"
BTN_T_TOM_9 = "🌅 Ertaga 09:00"
BTN_T_TOM_18 = "🌇 Ertaga 18:00"
BTN_T_3D = "📆 3 kundan keyin"
BTN_T_RECURRING = "🔄 Har hafta (takrorlanuvchi)"

WEEKDAY_BUTTONS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
WEEKDAY_MAP = {name: idx for idx, name in enumerate(WEEKDAY_BUTTONS)}
WEEKDAY_LABELS = {idx: name for name, idx in WEEKDAY_MAP.items()}

def exact(*texts):
    pattern = "^(" + "|".join(re.escape(t) for t in texts) + ")$"
    return filters.Regex(pattern)

def get_main_keyboard(is_admin=False):
    keyboard = [
        [BTN_NEW_POST],
        [BTN_PENDING, BTN_CHANNELS],
        [BTN_PROFILE]
    ]
    if is_admin:
        keyboard.append([BTN_ADMIN_PANEL])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup([[BTN_MAIN_MENU]], resize_keyboard=True)

def get_button_prompt_keyboard():
    return ReplyKeyboardMarkup([[BTN_SKIP_BUTTON], [BTN_MAIN_MENU]], resize_keyboard=True)

def get_reactions_prompt_keyboard():
    return ReplyKeyboardMarkup([[BTN_REACTIONS_YES, BTN_REACTIONS_NO], [BTN_MAIN_MENU]], resize_keyboard=True)

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
        [
            [BTN_ADD_SPONSOR],
            [BTN_ADMIN_PANEL, BTN_MAIN_MENU]
        ],
        resize_keyboard=True
    )

def get_time_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_T_5MIN, BTN_T_15MIN, BTN_T_30MIN],
            [BTN_T_1H, BTN_T_2H],
            [BTN_T_TOM_9, BTN_T_TOM_18],
            [BTN_T_3D],
            [BTN_T_RECURRING],
            [BTN_MAIN_MENU],
        ],
        resize_keyboard=True,
    )

def get_weekday_keyboard():
    rows = [[WEEKDAY_BUTTONS[i], WEEKDAY_BUTTONS[i + 1]] for i in range(0, 6, 2)]
    rows.append([WEEKDAY_BUTTONS[6]])
    rows.append([BTN_MAIN_MENU])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)
