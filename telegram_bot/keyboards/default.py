"""Pastki (reply) klaviatura tugmalari, ularning matn konstantalari va
uchala til (uz/ru/en) uchun umumiy TANISH registrlari.

Bu modulning ikkita vazifasi bor:
  1. Klaviaturalarni foydalanuvchi TILIDA chizish (``get_main_keyboard``...);
  2. Bosilgan tugma matnini AMALGA bog'lash — buning uchun ``MENU_TEXTS``
     registry'da har bir tugmaning UCHALA TILDagi (va eski/variant)
     yorliqlari saqlanadi va ``exact()`` filtrlari shu registry orqali
     avtomatik kengaytiriladi.
"""

import re
from telegram import ReplyKeyboardMarkup
from telegram.ext import filters
from locales.translations import (
    get_text, get_lang, normalize_lang,
    button_texts, button_variants, normalize_button_text,
)
# ✨ MAGIC POST / 📊 POST SCORE — i18n `translations/` paketidan (uz/ru/en).
from translations import MAGIC_POST_I18N, POST_SCORE_I18N

# ============================================================
# STANDART MENYU TUGMALARI (Constants)
# ============================================================
BTN_NEW_POST = get_text("btn_new_post", "uz")
BTN_AI_STUDIO = get_text("btn_ai_studio", "uz")
BTN_PENDING = get_text("btn_pending", "uz")
BTN_PENDING_RU = get_text("btn_pending", "ru")
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
# 🆕 UX V2 — ASOSIY MENYU: QAT'IY 6 TUGMA STANDARTI (uz/ru/en)
# ============================================================
# Asosiy menyuda FAQAT va FAQAT quyidagi 6 ta tugma chiziladi:
#   [✨ Kontent yaratish]   [📢 Kanallarim]
#   [📅 Rejalashtirilgan]   [📊 Statistika]
#   [💎 PRO]                [⚙️ Sozlamalar]
# (+ oddiy foydalanuvchiga KO'RINMAS, faqat ADMIN_IDS uchun alohida
#   [⚙️ Admin Panel] qatori).
# Eski yorliqlar ("➕ Yangi post", "✨ AI Studio", "⭐️ Premium",
# "👤 Kabinet & Sozlamalar", "📖 Qo'llanma / Bot haqida", "⚙️ Qo'shimcha
# funksiyalar" ...) asosiy menyudan olib tashlandi, lekin routing'da alias
# sifatida saqlanadi — keshda qolgan eski klaviatura xabarlari xavfsiz mos
# bo'limga yo'naltiriladi (backward compatibility).
BTN_CREATE_CONTENT = get_text("btn_create_content", "uz")
BTN_CREATE_CONTENT_RU = get_text("btn_create_content", "ru")
BTN_CREATE_CONTENT_EN = get_text("btn_create_content", "en")
BTN_MY_CHANNELS = get_text("btn_my_channels", "uz")
BTN_MY_CHANNELS_RU = get_text("btn_my_channels", "ru")
BTN_MY_CHANNELS_EN = get_text("btn_my_channels", "en")
BTN_SCHEDULED = get_text("btn_scheduled", "uz")
BTN_SCHEDULED_RU = get_text("btn_scheduled", "ru")
BTN_SCHEDULED_EN = get_text("btn_scheduled", "en")
BTN_STATISTICS = get_text("btn_statistics", "uz")
BTN_STATISTICS_RU = get_text("btn_statistics", "ru")
BTN_STATISTICS_EN = get_text("btn_statistics", "en")

# ============================================================
# ✨ MAGIC POST — KILLER FEATURE #1 (asosiy menyu tugmasi)
# ============================================================
# Yorliqlar `translations/` paketidan olinadi (yagona manba). «✨ Magic Post»
# brend-nomi bo'lgani uchun uchala tilda bir xil, lekin routing uchun
# uchala til konstantasi ham saqlanadi (AI Studio tugmasi kabi).


def _magic_post_label(lang: str) -> str:
    """Magic Post tugma yorlig'i (tilga mos, hech qachon yiqilmaydi)."""
    table = MAGIC_POST_I18N.get(normalize_lang(lang)) or {}
    return table.get("btn_magic_post") or MAGIC_POST_I18N["uz"]["btn_magic_post"]


BTN_MAGIC_POST = _magic_post_label("uz")
BTN_MAGIC_POST_RU = _magic_post_label("ru")
BTN_MAGIC_POST_EN = _magic_post_label("en")
MAGIC_POST_ALIASES = (BTN_MAGIC_POST, BTN_MAGIC_POST_RU, BTN_MAGIC_POST_EN)

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

# 📸 IMAGE → POST — yangi oqimning aniq reply-label aliaslari. Legacy
# ``🖼 Rasmdan post olish`` oqimi o'z joyida qoladi; shu nomlar yangi
# feature'ni eski onboarding klaviaturasi soni/paritetini o'zgartirmasdan
# ochadi (handlers.image_post). To'liq production menyu bu label'ni context
# bilan chizadi; eski context'siz keyboard API va onboarding quick-photo
# klaviaturasi o'zgarmaydi.
BTN_IMAGE_POST = "📸 Rasm → Post"
BTN_IMAGE_POST_RU = "📸 Фото → Пост"
BTN_IMAGE_POST_EN = "📸 Image → Post"
IMAGE_POST_BUTTONS = (BTN_IMAGE_POST, BTN_IMAGE_POST_RU, BTN_IMAGE_POST_EN)

# ============================================================
# 📊 POST SCORE & IMPROVER — KILLER FEATURE #4 (asosiy menyu tugmasi)
# ============================================================
# Yorliq `translations/post_score.py` dan olinadi (yagona manba). «📊 Post
# Score» brend-nomi bo'lgani uchun uchala tilda bir xil, lekin routing uchun
# uchala til konstantasi ham saqlanadi (Magic Post / Image Post kabi).


def _post_score_label(lang: str) -> str:
    """📊 Post Score tugma yorlig'i (tilga mos, hech qachon yiqilmaydi)."""
    table = POST_SCORE_I18N.get(normalize_lang(lang)) or {}
    return table.get("ps_btn_menu") or POST_SCORE_I18N["uz"]["ps_btn_menu"]


BTN_POST_SCORE = _post_score_label("uz")
BTN_POST_SCORE_RU = _post_score_label("ru")
BTN_POST_SCORE_EN = _post_score_label("en")
POST_SCORE_ALIASES = (BTN_POST_SCORE, BTN_POST_SCORE_RU, BTN_POST_SCORE_EN)

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
#: Uchala tilning hafta kuni yorliqlari → indeks (klaviatura qaysi tilda
#: bo'lishidan qat'iy nazar "Juma"/"Пятница"/"Friday" — bittaning o'zi).
WEEKDAY_MAP_ALL = {}
for _names in (WEEKDAY_BUTTONS, WEEKDAY_BUTTONS_RU, WEEKDAY_BUTTONS_EN):
    for _idx, _name in enumerate(_names):
        WEEKDAY_MAP_ALL.setdefault(_name, _idx)


def weekday_index(text):
    """Matndan hafta kuni indeksini topadi (uz/ru/en, normallashtirilgan)."""
    if not text or not isinstance(text, str):
        return None
    needle = button_variants(text)
    if not needle:
        return None
    for name, idx in WEEKDAY_MAP_ALL.items():
        shapes = button_variants(name)
        if shapes and shapes[0] in needle:
            return idx
    return None


# ============================================================
# 🌐 HAR BIR DOIMIY TUGMA UCHUN UCHALA TIL MATNLARI (yagona manba)
# ============================================================
# Bu registry ikki ishni bajaradi:
#   1. ``exact()`` har bir filtr matnini shu to'plamdagi aliaslar bilan
#      KENGAYTIRADI — ya'ni barcha mavjud ``MessageHandler(exact(...))``
#      filtrlari avtomatik ravishda uz/ru/en (va eski yorliqlarni) taniydi;
#   2. handlerlar ichidagi qo'lda solishtiruvlar ``is_menu_text()`` orqali
#      shu to'plamdan foydalanadi.
#
# Qoida: TILGA BOG'LIQ MATN HECH QACHON handler ichida qotirilmaydi —
# klaviatura qaysi tilda chizilsa ham tugma bir xil ishlashi shart.
PROFILE_ALIASES = (
    # "Profil / Sozlamalar" — eski va alternative klaviatura yorliqlari.
    # Uchala til ham qabul qilinadi, chunki chat tarixidagi eski xabarlarda
    # aynan shu matnlar turgan bo'lishi mumkin. UX V2: asosiy menyu yorlig'i
    # endi "⚙️ Sozlamalar" — eski "👤 Kabinet & Sozlamalar" nomlari shu yerda
    # (orqaga moslik: eski klaviatura xabarlari buzilmasligi uchun).
    "👤 Kabinet & Sozlamalar", "👤 Кабинет & Настройки", "👤 Account & Settings",
    "👤 Profil / Sozlamalar", "👤 Профиль / Настройки", "👤 Profile & Settings",
    "👤 Profil", "👤 Профиль", "👤 Profile",
    "👤 Kabinet", "👤 Кабинет", "👤 Account",
    "⚙️ Sozlamalar", "⚙️ Настройки", "⚙️ Settings",
)
ADMIN_PANEL_ALIASES = ("⚙️ Admin panel", "⚙️ Админ панель", "⚙️ Админ-панель")
PENDING_ALIASES = ("⏳ Kutilayotgan", "⏳ Ожидающие", "⏳ Pending")
# UX V2: asosiy menyu "📅 Rejalashtirilgan" tugmasi ham navbat (queue)
# bo'limiga tushadi — eski "📚 Navbat" yorliqlari ham saqlanadi.
QUEUE_ALIASES = (
    "📚 Navbat", "📚 Очередь",
    "📅 Rejalashtirilgan", "📅 Запланированные", "📅 Scheduled",
)
CONVERTER_ALIASES = (
    "🔤 Konvertor", "🔤 Кирилл-Лотин", "🔤 Converter", "🔤 Latin", "🔤 Кириллица",
)
CHANNELS_ALIASES = (
    "📢 Kanallar", "📢 Каналлар", "📢 Kanallar/guruhlar",
    "📢 Каналы/группы", "📢 Channels",
    "📢 Kanallarim", "📢 Мои каналы", "📢 My channels",
)
ADD_CHANNEL_ALIASES = (
    "➕ Kanal qo'shish", "➕ Kanal/Guruh qo'shish",
    "➕ Добавить канал/группу", "➕ Добавить канал",
    "➕ Add channel/group", "➕ Add channel", "📢 Add channel",
)
BONUS_ALIASES = ("🎁 Bonus", "🎁 Бонус", "🎁 Daily bonus", "🎁 Kunlik bonus")
INVITE_ALIASES = (
    "🚀 Taklif qilish", "🚀 Пригласить", "🚀 Invite", "🚀 Invite friends",
)
TRANSFER_ALIASES = (
    "🔄 Ballar ulashish", "🔄 Передать баллы", "🔄 Transfer credits", "🔄 Transfer",
)
HELP_ALIASES = ("📖 Qo'llanma", "📖 Руководство", "📖 Guide", "📖 Help", "📖 About")
EXTRAS_ALIASES = (
    "⚙️ Qo'shimcha", "⚙️ Дополнительные", "⚙️ Extra features", "⚙️ Extras",
)
# UX V2: asosiy menyudagi "✨ Kontent yaratish" tugmasi AI Studio (kontent
# yaratish markazi) oqimini ochadi — "✨ AI Studio" yorlig'i ham saqlanadi.
AI_STUDIO_ALIASES = (
    "✨ AI Студия", "🤖 AI Studio", "✨ Studio",
    "✨ Kontent yaratish", "✨ Создать контент", "✨ Create content",
)
NEW_POST_ALIASES = (
    "➕ Post yaratish", "➕ Создать пост", "➕ Новый пост",
    "➕ Yangi post yozish", "➕ Create post",
)
# UX V2: asosiy menyu yorlig'i endi «💎 PRO» — eski «⭐️ Premium» nomi
# (keshdagi eski klaviatura xabarlari uchun) shu oilada saqlanadi.
PREMIUM_ALIASES = (
    "💎 PRO",
    "⭐️ Premium", "⭐️ Pro", "⭐️ PRO", "⭐️ Подписка", "⭐️ Upgrade", "⭐️ Premium tarif",
)
CONTENT_PLAN_ALIASES = (
    "🧠 Kontent-reja", "🧠 Контент-план", "🧠 Content plan", "🧠 Content-plan",
)
ANALYTICS_ALIASES = ("📊 Analitika", "📊 Аналитика", "📊 Analytics")
# UX V2: "📊 Statistika" asosiy menyudagi 6-tugma standartining yorlig'i —
# bir yagona "statistics" amali egasida (handlers/__init__.py dagi
# statistics_button: admin → bot statistikasi, oddiy foydalanuvchi → o'z
# kanallari analitikasi). Eski admin panel «📊 Statistika» tugmasi ham shu
# yagona yo'nalishga tushadi. "📊 Statistics" EN yorlig'i ham shu oilaga
# o'tdi (avval ANALYTICS tomonida edi — yagona egalik = aniq routing).
STATISTICS_ALIASES = ("📊 Statistika", "📊 Статистика", "📊 Statistics")
EXTRACT_ALIASES = (
    "📢 Ochiq kanaldan olish", "📢 Из открытого канала",
    "📢 Open channel import", "📢 Import from public channel",
)
# "📊 Statistics" EN aliasi ataylab ANALITIKA tomonida qoldirildi — ikkita
# tugma bir xil matnni olsа, registry'da qaysi biriga tegishli ligi
# noaniq bo'lardi (yagona egalik = aniq routing).
ADMIN_STATS_ALIASES = ("📊 Statistika", "📊 Статистика")
ADMIN_POSTS_ALIASES = ("📋 Barcha postlar", "📋 Все посты", "📋 All posts")
ADMIN_CHANNELS_ALIASES = (
    "📋 Barcha kanal/guruhlar", "📋 Все каналы/группы",
    "📋 All channels/groups", "📋 All channels",
)
BROADCAST_ALIASES = ("✉️ Xabar yuborish", "✉️ Рассылка", "✉️ Broadcast")
SPONSORS_ALIASES = (
    "📢 Majburiy obuna", "📢 Обязательная подписка", "📢 Required subscription",
)
ADD_SPONSOR_ALIASES = (
    "➕ Homiy kanal qo'shish", "➕ Добавить канал спонсора",
    "➕ Add sponsor channel", "➕ Add sponsor",
)
ADS_ALIASES = ("🎯 Reklama markazi", "🎯 Рекламный центр", "🎯 Ads center", "🎯 Ads")
POST_TAG_ALIASES = ("🏷 Post nishoni", "🏷 Метка поста", "🏷 Post tag")
AI_SETTINGS_ALIASES = ("⚙️ AI parametrlar", "⚙️ Параметры ИИ", "⚙️ AI settings")
CACHE_DB_ALIASES = (
    "🗄️ DB / Kesh holati", "🗄️ Состояние БД / кеша",
    "🗄️ DB / cache status", "🗄️ DB / Cache",
)
CANCEL_ALIASES = ("❌ Bekor qilish", "❌ Отмена", "❌ Cancel", "❌ Bekor", "❌ Yo'q")
MAIN_MENU_ALIASES = ("🔙 Asosiy menyu", "🔙 Главное меню", "🔙 Main menu")

def _uniq(*groups) -> tuple:
    """Matnlar to'plamini takrorlanishlarsiz, tartibni saqlab birlashtiradi."""
    out = []
    for group in groups:
        items = group if isinstance(group, (tuple, list)) else (group,)
        for value in items:
            text = value.strip() if isinstance(value, str) else str(value or "")
            if text and text not in out:
                out.append(text)
    return tuple(out)


MENU_TEXTS = {
    # --- Asosiy menyu (6 tugma + admin qatori) ---
    "new_post": button_texts("btn_new_post", extra=NEW_POST_ALIASES),
    "ai_studio": button_texts("btn_ai_studio", extra=AI_STUDIO_ALIASES),
    "magic_post": _uniq((BTN_MAGIC_POST, BTN_MAGIC_POST_RU, BTN_MAGIC_POST_EN),
                        MAGIC_POST_ALIASES),
    "post_score": _uniq((BTN_POST_SCORE, BTN_POST_SCORE_RU, BTN_POST_SCORE_EN),
                        POST_SCORE_ALIASES),
    "premium": button_texts("btn_premium", extra=PREMIUM_ALIASES),
    "settings": button_texts("btn_settings", extra=PROFILE_ALIASES),
    "help": button_texts("btn_help", extra=HELP_ALIASES),
    "extras": button_texts("btn_extras", extra=EXTRAS_ALIASES),
    "main_menu": button_texts("btn_main_menu", extra=MAIN_MENU_ALIASES),
    "cancel": button_texts("btn_cancel", extra=CANCEL_ALIASES),
    # --- Kabinet va ichki bo'limlar ---
    "back": button_texts("btn_back"),
    "pending": button_texts("btn_pending", extra=PENDING_ALIASES),
    "queue": button_texts("btn_queue", extra=QUEUE_ALIASES),
    "converter": button_texts("cab_btn_converter", extra=CONVERTER_ALIASES),
    "channels": button_texts("cab_btn_channels", extra=CHANNELS_ALIASES),
    "add_channel": _uniq((BTN_ADD_CHANNEL,), ADD_CHANNEL_ALIASES),
    "daily_bonus": button_texts("cab_btn_daily_bonus", extra=BONUS_ALIASES),
    "invite": button_texts("cab_btn_invite", extra=INVITE_ALIASES),
    "transfer": button_texts("cab_btn_transfer", extra=TRANSFER_ALIASES),
    "content_plan": _uniq((BTN_CONTENT_PLAN,), CONTENT_PLAN_ALIASES),
    "analytics": _uniq((BTN_ANALYTICS,), ANALYTICS_ALIASES),
    # UX V2: asosiy menyudagi "📊 Statistika" tugmasi — yagona statistics
    # amali (yukdagi statistics_button dispatcher orqali).
    "statistics": _uniq((BTN_STATISTICS, BTN_STATISTICS_RU, BTN_STATISTICS_EN),
                        STATISTICS_ALIASES),
    "channel_extract": _uniq((BTN_CHANNEL_EXTRACT,), EXTRACT_ALIASES),
    # --- Admin paneli (klaviatura UZ'da chiziladi, aliaslar ham taniladi) ---
    "admin_panel": _uniq((BTN_ADMIN_PANEL, BTN_ADMIN_PANEL_RU), ADMIN_PANEL_ALIASES),
    "admin_stats": _uniq((BTN_STATS,), ADMIN_STATS_ALIASES),
    "admin_all_posts": _uniq((BTN_ALL_POSTS,), ADMIN_POSTS_ALIASES),
    "admin_all_channels": _uniq((BTN_ALL_CHANNELS,), ADMIN_CHANNELS_ALIASES),
    "broadcast": _uniq((BTN_BROADCAST,), BROADCAST_ALIASES),
    "sponsors": _uniq((BTN_SPONSORS,), SPONSORS_ALIASES),
    "add_sponsor": _uniq((BTN_ADD_SPONSOR,), ADD_SPONSOR_ALIASES),
    "ads": _uniq((BTN_ADS, BTN_CHANNEL_AD, BTN_BOT_REPLY_AD), ADS_ALIASES),
    "post_tag": _uniq((BTN_POST_TAG,), POST_TAG_ALIASES),
    "ai_settings": _uniq((BTN_AI_SETTINGS,), AI_SETTINGS_ALIASES),
    "cache_db": _uniq((BTN_CACHE_DB,), CACHE_DB_ALIASES),
    # --- 🆕 Onboarding (sodda klaviatura) ---
    "quick_ai_post": button_texts("quick_btn_ai_post"),
    "quick_photo_post": button_texts("quick_btn_photo_post"),
    "quick_add_channel": button_texts("quick_btn_add_channel"),
    "quick_full_menu": button_texts("quick_btn_full_menu"),
    # --- ➕ Yangi post oqimidagi reply-tugmalar ---
    "np_all_channels": button_texts("np_btn_all_channels"),
    "np_skip": button_texts("np_btn_skip", "np_btn_skip_url", extra=(
        "⏩ O'tkazib yuborish", "⏩ Пропустить", "⏭ O'tkazib yuborish",
        "⏭ Пропустить", "⏭ Skip", "O'tkazib yuborish", "Пропустить", "Skip",
        "Continue", "Continue without button", "➡️ Continue without button",
    )),
    "np_url_add": button_texts("np_btn_url_add"),
    "np_no_reactions": button_texts("np_btn_no_reactions", extra=(
        "➡️ Reaksiyasiz", "➡️ Без реакций", "➡️ Without reactions",
        "Reaksiyasiz davom etish", "Продолжить без реакций",
        "Continue without reactions",
    )),
    "np_ai_assistant": button_texts("np_btn_ai_assistant"),
    "np_title_details": button_texts("np_btn_title_details"),
    "np_title_join": button_texts("np_btn_title_join"),
    "np_title_site": button_texts("np_btn_title_site"),
    "np_title_contact": button_texts("np_btn_title_contact"),
    "np_time_5m": button_texts("np_btn_time_5m"),
    "np_time_15m": button_texts("np_btn_time_15m"),
    "np_time_1h": button_texts("np_btn_time_1h"),
    "np_time_daily": button_texts("np_btn_time_daily"),
    "np_time_weekly": button_texts("np_btn_time_weekly"),
    "np_del_never": button_texts("np_btn_del_never", extra=("❌ Doimiy", "❌ Никогда", "❌ Never")),
    "np_del_12h": button_texts("np_btn_del_12h"),
    "np_del_24h": button_texts("np_btn_del_24h"),
    "np_del_48h": button_texts("np_btn_del_48h"),
    "np_del_72h": button_texts("np_btn_del_72h"),
    "np_dur_1w": button_texts("np_btn_dur_1w"),
    "np_dur_1m": button_texts("np_btn_dur_1m"),
    "np_dur_3m": button_texts("np_btn_dur_3m"),
    "np_dur_6m": button_texts("np_btn_dur_6m"),
    "np_dur_1y": button_texts("np_btn_dur_1y"),
    "np_dur_inf": button_texts("np_btn_dur_inf"),
    "np_back_confirm": button_texts("np_btn_back_confirm"),
    "np_weekday": _uniq(WEEKDAY_BUTTONS, WEEKDAY_BUTTONS_RU, WEEKDAY_BUTTONS_EN),
}

#: ``exact()`` kengaytiruvi uchun indeks: normallashtirilgan yorliq → action.
_LABEL_TO_ACTION = {}
for _action, _texts in MENU_TEXTS.items():
    for _label in _texts:
        _shapes = button_variants(_label)
        if _shapes:
            _LABEL_TO_ACTION.setdefault(_shapes[0], _action)
            for _shape in _shapes:
                _LABEL_TO_ACTION.setdefault(_shape, _action)


def menu_texts(*actions) -> tuple:
    """Tanlangan amallar (tugmalar) uchun barcha til variantlari."""
    out = []
    for action in actions:
        for text in MENU_TEXTS.get(action, ()):
            if text not in out:
                out.append(text)
    return tuple(out)


def is_menu_text(text, *actions) -> bool:
    """``text`` tanlangan tugmalarning biriga mosmi (uz/ru/en, qo'lda yozilgan
    holda ham — emoji va katta/kichik harf farqi hisobga olinmaydi)."""
    needle = button_variants(text)
    if not needle:
        return False
    for cand in menu_texts(*actions):
        shapes = button_variants(cand)
        if shapes and shapes[0] in needle:
            return True
    return False


def exact(*texts):
    """Aniq matn filtri — har bir matn UCHALA TIL aliaslari bilan kengayadi.

    ``exact(BTN_NEW_POST, BTN_NEW_POST_RU)`` yozuvi endi "➕ New post" ni ham
    taniydi: klaviatura qaysi tilda chizilganiga qaramay tugma ishlashi uchun
    filtr ``MENU_TEXTS`` registry'dagi barcha variantlar bilan to'ldiriladi.
    Qo'shimcha ravishda qator boshidagi/oxiridagi bo'shliqlar bardoshli.
    """
    expanded = []

    def _add(value):
        if not isinstance(value, str):
            value = str(value or "")
        value = value.strip()
        if value and value not in expanded:
            expanded.append(value)
            # Shu yorliqqa mos tugma oilasi (uz/ru/en + legacy) ham qo'shiladi.
            shapes = button_variants(value)
            action = _LABEL_TO_ACTION.get(shapes[0]) if shapes else None
            for alias in MENU_TEXTS.get(action or "", ()):
                _add(alias)

    for item in texts:
        _add(item)
    if not expanded:
        # Bo'sh filtr — hech narsa bilan mos kelmasligi kerak (crash emas).
        return filters.Regex(r"^(?!)$")
    pattern = r"^\s*(" + "|".join(re.escape(t) for t in expanded) + r")\s*$"
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



def _image_post_label(lang: str) -> str:
    """Image → Post reply-labelini foydalanuvchi tilida chizadi."""
    code = normalize_lang(lang)
    return {
        "ru": BTN_IMAGE_POST_RU,
        "en": BTN_IMAGE_POST_EN,
    }.get(code, BTN_IMAGE_POST)


def get_main_keyboard(is_admin=False, lang="uz", context=None,
                      include_image_post=None, include_post_score=None):
    """Asosiy reply-klaviatura — UX V2: QAT'IY 6 TUGMA STANDARTI.

    Oddiy foydalanuvchi (3 qator × 2 tugma):

        [✨ Kontent yaratish]   [📢 Kanallarim]
        [📅 Rejalashtirilgan]   [📊 Statistika]
        [💎 PRO]                [⚙️ Sozlamalar]

    Admin foydalanuvchi (ADMIN_IDS) — shu 6 ta tugma + pastda alohida
    [⚙️ Admin Panel] qatori. Oddiy foydalanuvchiga "Admin Panel" HECH
    QACHON ko'rinmaydi.

    ``include_image_post`` / ``include_post_score`` parametrlari UX V2 dan
    beri DEPRECATED: asosiy menyuda Magic Post / Image Post / Post Score
    tugmalari chizilmaydi — ularning oqimlari hali ham ishlaydi (keshdagi
    eski klaviatura xabarlari, "✨ Kontent yaratish" ichidagi AI Studio
    sub-menyusi, to'g'ridan-to'g'ri rasm/ovoz yuborish). Parametrlar eski
    chaqiruvchilarni buzmaslik uchun API'da saqlanib qolgan (e'tibor
    qilinmaydi).
    """
    if context is not None:
        lang = get_lang(context, lang)
    keyboard = [
        [get_text("btn_create_content", lang), get_text("btn_my_channels", lang)],
        [get_text("btn_scheduled", lang), get_text("btn_statistics", lang)],
        [get_text("btn_premium", lang), get_text("btn_settings", lang)],
    ]
    if is_admin:
        keyboard.append([BTN_ADMIN_PANEL])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_refreshed_main_keyboard(lang="uz", is_admin=False, simple_menu=False,
                                context=None):
    """Til o'zgarganda yuboriladigan PASTKI DOIMIY menyu — YANGI tilda.

    Telegram ``ReplyKeyboardMarkup`` faqat yangi xabar bilan yuborilishi
    mumkinligi sababli til almashganda shu klaviatura alohida xabar bilan
    chiqariladi (:func:`handlers.start.send_language_reply_keyboard`).

    Args:
        lang: yangi til ('uz' | 'ru' | 'en')
        is_admin: admin uchun "⚙️ Admin Panel" qatori qo'shiladi
        simple_menu: yangi foydalanuvchi (onboarding) — 3 tugmali sodda menyu
        context: berilsa, til ``context.user_data['lang']`` dan olinadi

    Returns:
        UX V2 6-tugma standart klaviatura (tilga mos yorliqlar):
        UZ: "✨ Kontent yaratish", "📢 Kanallarim", "📅 Rejalashtirilgan",
        "📊 Statistika", "💎 PRO", "⚙️ Sozlamalar" ...
    """
    if context is not None:
        lang = get_lang(context, lang)
    if simple_menu and not is_admin:
        return get_simple_keyboard(lang)
    return get_main_keyboard(is_admin, lang=lang, context=context)


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


def get_ai_time_keyboard(lang: str = "uz"):
    lang = normalize_lang(lang)
    if lang == "uz":
        t_5min, t_15min, t_1h, back = BTN_T_5MIN, BTN_T_15MIN, BTN_T_1H, BTN_BACK
    else:
        t_5min = get_text("np_btn_time_5m", lang)
        t_15min = get_text("np_btn_time_15m", lang)
        t_1h = get_text("np_btn_time_1h", lang)
        back = get_text("btn_main_menu", lang)
    return ReplyKeyboardMarkup(
        [
            [t_5min, t_15min, t_1h],
            [back],
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

#: Uslub yorliqlari — til bo'yicha yagona kirish nuqtasi.
TONE_LABELS_BY_LANG = {"uz": TONE_LABELS, "ru": TONE_LABELS_RU, "en": TONE_LABELS_EN}


def tone_labels(lang="uz") -> dict:
    """Kanal uslubi (Tone of Voice) tugma yorliqlari — tilga mos (uz/ru/en).

    Avval har chaqiruv nuqtasida ``TONE_LABELS_RU if lang == "ru" else
    TONE_LABELS`` yozilgani uchun EN foydalanuvchi uslub nomlarini O'ZBEKCHA
    ko'rardi (va EN tugmasi umunan tanilmasdi).
    """
    return TONE_LABELS_BY_LANG.get(normalize_lang(lang), TONE_LABELS)


def tone_from_text(text):
    """Matn/yorliqdan uslub kodini topadi — uchala tilda ham.

    "👔 Formal / Business", "Rasmiy / Biznes" (emojisiz), "официальный / бизнес"
    (katta/kichik farqsiz) — barchasi ``formal`` ga olib keladi.
    """
    needle = normalize_button_text(text)
    if not needle:
        return None
    for table in (TONE_LABELS_EN, TONE_LABELS_RU, TONE_LABELS):
        for code, label in table.items():
            shapes = button_variants(label)
            if needle in shapes:
                return code
    return None


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
