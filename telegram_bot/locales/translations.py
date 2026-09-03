"""Sodda i18n lug'ati: o'zbek (uz) va rus (ru).

Foydalanish:
    get_text("start_hello", lang="ru", name="Ivan")
"""

DEFAULT_LANG = "uz"
SUPPORTED_LANGS = ("uz", "ru")
LANG_KEY = "lang"

TRANSLATIONS = {
    "uz": {
        "btn_new_post": "➕ Yangi post",
        "btn_ai_studio": "✨ AI Studio",
        "btn_premium": "⭐️ Premium",
        "btn_settings": "👤 Kabinet & Sozlamalar",
        "btn_help": "📖 Qo'llanma / Bot haqida",
        "btn_extras": "⚙️ Qo'shimcha funksiyalar",
        "start_hello": (
            "Salom, <b>{name}</b>! 👋\n\n"
            "🤖 @PostAssistrobot — kanallarga postlarni vaqtida joylash, "
            "AI yordamida matnlar va kontent-reja tuzish bo'yicha aqlli yordamchingiz.\n\n"
            "Kerakli bo'limni tanlang 👇"
        ),
        "my_channels_title": "📢 <b>Mening kanallarim:</b>",
        "my_channels_empty": (
            "📢 <b>Mening kanallarim:</b>\n\n"
            "Hozircha hech qanday kanal ulanmagan.\n\n"
            "{hint}\n\n"
            "⚠️ <i>Botni kanal/guruhingizga administrator qilib (xabar "
            "yuborish ruxsati bilan) qo'shing, so'ng pastdagi "
            "<b>➕ Kanal qo'shish</b> tugmasini bosing.</i>"
        ),
        "my_channels_list": "📢 <b>Mening kanallarim ({count} ta):</b>\n\n",
        "my_channels_footer": "\nYangi kanal ulash yoki mavjudini o'chirish uchun 👇",
        "new_post_no_channels": (
            "⚠️ <b>Ulangan kanal yoki guruh topilmadi!</b>\n\n"
            "Avval '📢 Kanal/Guruhlar' bo'limidan kanal yoki guruhingizni ulang."
        ),
        "new_post_choose_channel": (
            "📢 <b>Qaysi kanal yoki guruhga post rejalashtiramiz?</b>\n"
            "Ro'yxatdan tanlang 👇"
        ),
        "lang_prompt": "🌐 <b>Tilni tanlang / Выберите язык:</b>",
        "lang_changed": "✅ Til o'zbekchaga o'zgartirildi.",
        "lang_button": "🌐 Til / Язык",
        "referral_reward_notice": (
            "🎉 <b>Yangi do'st taklif qilindi!</b>\n\n"
            "Hisobingizga <b>+{reward} ta AI ball</b> qo'shildi. "
            "Birinchi 3 do'st uchun +3 tadan, keyingilar uchun +1 tadan beriladi. 🚀"
        ),
        "referral_menu": (
            "🚀 <b>Do'stlarni taklif qiling va AI ball oling:</b>\n\n"
            "🎁 <i>1-, 2- va 3-do'st uchun +3 tadan; 4-do'stdan boshlab har biri uchun +1 AI ball.</i>\n\n"
            "💎 Mavjud AI ballaringiz: {credits}\n👥 Takliflar: <b>{count} ta</b>\n\n"
            "🔗 <b>Taklif havolangiz:</b>\n<code>{link}</code>"
        ),
        "daily_bonus_guide": (
            "🎁 Kunlik bepul AI ballaringizni olish uchun "
            "'Kabinet & Sozlamalar' → '🎁 Kunlik bonus' bo'limiga kiring."
        ),
        "no_credits": (
            "⚠️ <b>Sizda bepul AI so'rovlari soni tugadi!</b>\n\n"
            "Ko'proq so'rov olish uchun do'stlaringizni taklif qiling.\n"
            "🎁 <i>1-, 2- va 3-do'st uchun +3 tadan, 4-do'stdan boshlab har biri uchun +1 AI ball beriladi.</i>\n"
            "{guide}\n\n"
            "🔗 Sizning taklif havolangiz:\n<code>{link}</code>"
        ),
        "balance_card": (
            "💎 <b>Ballar & Reklama rejimi:</b>\n\n"
            "🤖 AI so'rovlar: {credits}\n"
            "📢 Reklama rejimi: {ad_mode}\n\n"
            "Ballarni ko'paytirish uchun:\n"
            "• 🎁 Kunlik bonus oling\n"
            "• 👥 Do'stlarni taklif qiling (1–3-do'st: +3, keyingilar: +1)\n"
            "• ⭐️ PRO tarifga o'ting (cheksiz AI, 100% reklamasiz postlar)"
        ),
        "ad_mode_admin": "👑 <b>Admin</b> — reklamasiz",
        "ad_mode_pro": "✨ <b>PRO</b> — postlar va bot javoblari avtomatik 100% reklamasiz",
        "ad_mode_free": "🆓 <b>Bepul</b> — belgilangan oraliqda reklama chiqadi (PRO'da avtomatik o'chadi)",
        "btn_card_payment": "💳 Karta orqali to'lov (Uzcard / Humo)",
        "btn_back": "⬅️ Orqaga",
        "card_payment_title": "💳 <b>Karta orqali to'lov (Uzcard / Humo)</b>",
        "card_payment_prices": (
            "💰 <b>To'lov summasi:</b>\n"
            "• 1 oy — <b>{p1m} so'm</b>\n"
            "• 3 oy — <b>{p3m} so'm</b>\n"
            "• 1 yil — <b>{p1y} so'm</b>"
        ),
        "card_payment_card": "💳 <b>Karta raqami:</b> <code>{card}</code>\n👤 <b>Karta egasi:</b> {holder}",
        "card_payment_no_card": "ℹ️ Karta rekvizitlarini olish uchun adminga murojaat qiling.",
        "card_payment_steps": (
            "📝 <b>Yo'riqnoma:</b>\n"
            "1️⃣ Tanlagan tarif summasini yuqoridagi kartaga o'tkazing.\n"
            "2️⃣ To'lov chekini (skrinshot) adminga yuboring: {admin}\n"
            "3️⃣ Xabarda o'z ID raqamingizni ko'rsating: <code>{user_id}</code>\n"
            "4️⃣ Admin tekshirgach PRO tarif 24 soat ichida faollashtiriladi.\n\n"
            "⚡️ Tezroq bo'lishi uchun ⭐️ Stars orqali to'lasangiz PRO darhol yoqiladi."
        ),
        "card_payment_admin_missing": "admin (Bot haqida bo'limidagi aloqa orqali)",
    },
    "ru": {
        "btn_new_post": "➕ Новый пост",
        "btn_ai_studio": "✨ AI Studio",
        "btn_premium": "⭐️ Premium",
        "btn_settings": "👤 Кабинет & Настройки",
        "btn_help": "📖 Руководство / О боте",
        "btn_extras": "⚙️ Дополнительные функции",
        "start_hello": (
            "Привет, <b>{name}</b>! 👋\n\n"
            "🤖 @PostAssistrobot — умный помощник для своевременной публикации "
            "постов в каналы, текстов и контент-плана с помощью ИИ.\n\n"
            "Выберите нужный раздел 👇"
        ),
        "my_channels_title": "📢 <b>Мои каналы:</b>",
        "my_channels_empty": (
            "📢 <b>Мои каналы:</b>\n\n"
            "Пока ни один канал не подключён.\n\n"
            "{hint}\n\n"
            "⚠️ <i>Сначала добавьте бота администратором канала/группы "
            "(с правом отправки сообщений), затем нажмите "
            "<b>➕ Добавить канал</b>.</i>"
        ),
        "my_channels_list": "📢 <b>Мои каналы ({count} шт.):</b>\n\n",
        "my_channels_footer": "\nЧтобы подключить новый канал или удалить существующий 👇",
        "new_post_no_channels": (
            "⚠️ <b>Подключённый канал или группа не найдены!</b>\n\n"
            "Сначала подключите канал или группу в разделе «📢 Каналы/Группы»."
        ),
        "new_post_choose_channel": (
            "📢 <b>В какой канал или группу запланируем пост?</b>\n"
            "Выберите из списка 👇"
        ),
        "lang_prompt": "🌐 <b>Tilni tanlang / Выберите язык:</b>",
        "lang_changed": "✅ Язык изменён на русский.",
        "lang_button": "🌐 Til / Язык",
        "referral_reward_notice": (
            "🎉 <b>Приглашён новый друг!</b>\n\n"
            "На ваш счёт начислено <b>+{reward} ИИ-балла</b>. "
            "За первых 3 друзей начисляется по +3, за каждого следующего — +1. 🚀"
        ),
        "referral_menu": (
            "🚀 <b>Приглашайте друзей и получайте ИИ-баллы:</b>\n\n"
            "🎁 <i>За 1-го, 2-го и 3-го друга — по +3; начиная с 4-го — по +1 ИИ-баллу.</i>\n\n"
            "💎 Ваши ИИ-баллы: {credits}\n👥 Приглашено: <b>{count}</b>\n\n"
            "🔗 <b>Ваша реферальная ссылка:</b>\n<code>{link}</code>"
        ),
        "daily_bonus_guide": (
            "🎁 Чтобы получить ежедневные бесплатные ИИ-баллы, откройте "
            "«Кабинет & Настройки» → «🎁 Ежедневный бонус»."
        ),
        "no_credits": (
            "⚠️ <b>У вас закончились бесплатные ИИ-запросы!</b>\n\n"
            "Чтобы получить больше, приглашайте друзей.\n"
            "🎁 <i>За 1-го, 2-го и 3-го друга — по +3, начиная с 4-го — по +1 ИИ-баллу.</i>\n"
            "{guide}\n\n"
            "🔗 Ваша реферальная ссылка:\n<code>{link}</code>"
        ),
        "balance_card": (
            "💎 <b>Баллы & Режим рекламы:</b>\n\n"
            "🤖 ИИ-запросы: {credits}\n"
            "📢 Режим рекламы: {ad_mode}\n\n"
            "Чтобы получить больше баллов:\n"
            "• 🎁 Забирайте ежедневный бонус\n"
            "• 👥 Приглашайте друзей (1–3-й друг: +3, далее: +1)\n"
            "• ⭐️ Перейдите на PRO (безлимитный ИИ, посты 100% без рекламы)"
        ),
        "ad_mode_admin": "👑 <b>Админ</b> — без рекламы",
        "ad_mode_pro": "✨ <b>PRO</b> — посты и ответы бота автоматически 100% без рекламы",
        "ad_mode_free": "🆓 <b>Бесплатный</b> — реклама показывается с заданным интервалом (в PRO отключается автоматически)",
        "btn_card_payment": "💳 Оплата картой (Uzcard / Humo)",
        "btn_back": "⬅️ Назад",
        "card_payment_title": "💳 <b>Оплата картой (Uzcard / Humo)</b>",
        "card_payment_prices": (
            "💰 <b>Сумма оплаты:</b>\n"
            "• 1 месяц — <b>{p1m} сум</b>\n"
            "• 3 месяца — <b>{p3m} сум</b>\n"
            "• 1 год — <b>{p1y} сум</b>"
        ),
        "card_payment_card": "💳 <b>Номер карты:</b> <code>{card}</code>\n👤 <b>Владелец:</b> {holder}",
        "card_payment_no_card": "ℹ️ Чтобы получить реквизиты карты, обратитесь к администратору.",
        "card_payment_steps": (
            "📝 <b>Инструкция:</b>\n"
            "1️⃣ Переведите сумму выбранного тарифа на карту выше.\n"
            "2️⃣ Отправьте чек (скриншот) администратору: {admin}\n"
            "3️⃣ Укажите в сообщении свой ID: <code>{user_id}</code>\n"
            "4️⃣ После проверки PRO активируется в течение 24 часов.\n\n"
            "⚡️ Для мгновенной активации оплатите через ⭐️ Stars."
        ),
        "card_payment_admin_missing": "администратор (контакты в разделе «О боте»)",
    },
}


def normalize_lang(lang) -> str:
    """Faqat 'uz' yoki 'ru' qaytaradi."""
    if lang is None:
        return DEFAULT_LANG
    raw = str(lang).strip().lower()
    if raw.startswith("ru"):
        return "ru"
    return DEFAULT_LANG


def detect_language(telegram_language_code) -> str:
    """Telegram ``language_code`` dan bot tilini aniqlaydi.

    'ru', 'ru-RU', 'ru-UZ' → 'ru'; aks holda → 'uz'.
    """
    return normalize_lang(telegram_language_code)


def get_text(key, lang="uz", **kwargs) -> str:
    """Lug'atdan matn olish. Noma'lum kalit/til uchun o'zbekcha fallback."""
    lang = normalize_lang(lang)
    table = TRANSLATIONS.get(lang) or TRANSLATIONS[DEFAULT_LANG]
    text = table.get(key)
    if text is None:
        text = TRANSLATIONS[DEFAULT_LANG].get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text


def get_lang(context, default=DEFAULT_LANG) -> str:
    """``context.user_data['lang']`` dan tilni o'qiydi (kesh)."""
    try:
        ud = getattr(context, "user_data", None) or {}
        return normalize_lang(ud.get(LANG_KEY, default))
    except Exception:
        return normalize_lang(default)


def set_lang_cache(context, lang: str) -> str:
    """Tilni ``context.user_data['lang']`` ga yozadi (DB so'rovisiz)."""
    lang = normalize_lang(lang)
    try:
        if context is not None and getattr(context, "user_data", None) is not None:
            context.user_data[LANG_KEY] = lang
    except Exception:
        pass
    return lang


def clear_fsm_data(context) -> None:
    """FSM holatini tozalaydi, lekin til keshini saqlab qoladi."""
    if context is None:
        return
    ud = getattr(context, "user_data", None)
    if ud is None:
        return
    lang = ud.get(LANG_KEY) if hasattr(ud, "get") else None
    ud.clear()
    if lang in SUPPORTED_LANGS:
        ud[LANG_KEY] = lang
