"""⚙️ SOZLAMALAR + 📊 STATISTIKA (PostAssist V2 — 5-mikro qadam) i18n lug'ati.

UZ / RU / EN — 100% paritet (``settings_stats_parity_report`` qo'riqlaydi).

Bo'limlar:
  * 📊 STATISTIKA — asosiy menyudagi «📊 Statistika» tugmasi ochadigan IXCHAM
    umumiy ko'rsatkichlar ekrani (ss_stats_*) va uning amallari
    [🔄 Yangilash] [◀️ Orqaga] (ss_btn_refresh / ss_btn_back);
  * ⚙️ SOZLAMALAR — IXCHAM 8 guruhli menyu (2-bosqich):
    👤 Profil, 🌐 Til / Язык, 🎁 Bonuslar & Ballar, 🎨 Post sozlamalari,
    🔔 Bildirishnomalar, 💳 To'lovlar tarixi, 🧰 Vositalar,
    ❓ Yordam & Ma'lumot + ◀️ Orqaga (ss_btn_*);
  * 🎁 BONUSLAR & BALLAR hub'i — 💎 Ballarim, 🔄 Ballar o'tkazish,
    🎁 Kunlik bonus, 👥 Do'stlarni taklif (ss_rewards_title);
  * ❓ YORDAM & MA'LUMOT hub'i — 📖 Qo'llanma & FAQ,
    💬 Qo'llab-quvvatlash, ℹ️ Bot haqida (ss_help_hub_title);
  * 🧰 VOSITALAR — yordamchi vositalar submenyusi (Konverter + Post Enhancer,
    ss_tools_*) — 3-qadam refaktorida avval yashirinib qolgan funksiyalar o'z
    aniq, ko'rinadigan joyiga qo'yildi;
  * 🔔 Bildirishnomalar va 🎨 Post sozlamalari ekranlari (ss_notif_* /
    ss_post_*) — foydalanuvchi sozlamalari (``user_settings`` jadvali);
  * 💳 To'lovlar tarixi ekrani (ss_pay_*);
  * ℹ️ Bot haqida ekrani (ss_about_text);
  * ⚙️ ADMIN PANEL — faqat adminlarga ko'rinadigan tizim monitoringi
    (Health status) bloki yorliqlari (ss_health_*).

Nega alohida modul?
  ``translations/content_menu.py`` va ``channels_queue.py`` bilan bir xil
  sabab: asosiy repo lug'ati (``locales/translations.py`` +
  ``locales/en_overlay.py``) qat'iy audit-testlar bilan qo'riqlanadi. Yangi
  bo'lim matnlari o'z modulida yashaydi va paritet hisoboti bilan XUDDI SHU
  darajadagi UZ↔RU↔EN kafolatini beradi — asosiy lug'atga tegmasdan.

Foydalanish:
    from translations import settings_stats_t
    text = settings_stats_t("ss_stats_title", "ru")
"""

from locales.translations import normalize_lang, safe_t

# ============================================================
# 🌍 LUG'AT — uchala til (uz / ru / en) BIR XIL kalitlar to'plami
# ============================================================

SETTINGS_STATS_I18N = {
    # ------------------------------------------------------------
    # 🇺🇿 O'ZBEK TILI
    # ------------------------------------------------------------
    "uz": {
        # --- 📊 STATISTIKA: ixcham umumiy ko'rsatkichlar ekrani ---
        "ss_stats_title": "📊 <b>Statistika</b>",
        "ss_stats_channels": "📢 Ulangan kanallar: <b>{n} ta</b>",
        "ss_stats_created": "📝 Yaratilgan postlar: <b>{n} ta</b>",
        "ss_stats_scheduled": "📅 Rejalashtirilgan postlar: <b>{n} ta</b>",
        "ss_stats_ai": (
            "🤖 AI so'rovlar: <b>{ai} ta</b> • 💠 Sarflangan kreditlar: <b>{credits} ta</b>"
        ),
        "ss_stats_footer": (
            "<i>🔄 Yangilash — ko'rsatkichlarni hozirgi holatga keltiradi.</i>"
        ),
        "ss_btn_refresh": "🔄 Yangilash",
        "ss_btn_back": "◀️ Orqaga",
        "ss_stats_refreshing": "🔄 Yangilanmoqda…",

        # --- 📊 SHAXSIY STATISTIKA: asosiy menyudagi «📊 Statistika» ekrani.
        # MUHIM: bu kalitlar FAQAT foydalanuvchining O'Z ma'lumotlarini
        # chizadi. Admin (bot bo'yicha) statistikasi — handlers/admin.py
        # dagi ``_build_full_stats_text`` va u «⚙️ Admin Panel» ichidan
        # «📊 To'liq statistika» orqali ochiladi. Ikki ekran matnshunosligi
        # qat'iy ajratilgan (statistika izolyatsiyasi).
        "ss_my_title": "📊 <b>Sizning statistikangiz:</b>",
        "ss_my_channels": "📢 Ulangan kanallaringiz: <b>{n} ta</b>",
        "ss_my_created": "📝 Yaratilgan postlaringiz: <b>{n} ta</b>",
        "ss_my_scheduled": "📅 Rejalashtirilgan postlar: <b>{n} ta</b>",
        "ss_my_credits": "💎 Qolgan AI kreditlaringiz: <b>{n} ta</b>",
        "ss_btn_channel_detail": "📈 Kanal bo'yicha batafsil",

        # --- ⚙️ SOZLAMALAR: yagona tartibli menyu ---
        "ss_menu_title": (
            "⚙️ <b>Sozlamalar</b>\n\n"
            "Kerakli bo'limni tanlang 👇"
        ),
        "ss_btn_profile": "👤 Profil",
        "ss_btn_lang": "🌐 Til / Язык",
        # 👤 Profil kartasi: obuna holati (ID/balans kabi asosiy ma'lumotlar
        # cabinet_title'da; Til tugmasi profildan olib tashlangan).
        "ss_profile_sub_pro": "⭐️ Obuna: <b>PRO</b> (muddatigacha: {date})",
        "ss_profile_sub_free": "🆓 Obuna: <b>FREE</b>",
        "ss_btn_rewards": "🎁 Bonuslar & Ballar",
        "ss_btn_help_hub": "❓ Yordam & Ma'lumot",
        "ss_btn_notif": "🔔 Bildirishnomalar",
        "ss_btn_post_settings": "🎨 Post sozlamalari",
        "ss_btn_payments": "💳 To'lovlar tarixi",
        "ss_btn_referral": "🎁 Do'stlarni taklif qilish",
        "ss_btn_help": "❓ Yordam",
        "ss_btn_about": "ℹ️ Bot haqida",
        "ss_settings_legacy": "🗂 Tezkor bo'limlar",
        # --- 3-qadam: hub'ning yangi (to'liq) tugmalari ---
        # «🎁 Kunlik bonus» va «👥 Do'stlarni taklif» — asosiy lug'atdagi
        # yagona manbadan olinadi (``cab_btn_daily_bonus`` / ``cab_referral``),
        # shu sababli bu yerda TAKRORLANMAYDI (settings_stats_t fallback'i
        # ularni asosiy lug'atdan o'qib beradi).
        "ss_btn_points": "💎 Ballarim",
        "ss_btn_transfer": "🔄 Ballar o'tkazish",
        "ss_btn_tools": "🧰 Vositalar",

        # --- 🧰 Vositalar submenyusi (yordamchi vositalar) ---
        "ss_tools_title": (
            "🧰 <b>Vositalar</b>\n\n"
            "Asosiy oqimlardan tashqari yordamchi vositalar:\n"
            "🔤 <b>Kirill-Lotin Konvertor</b> — matnni ikki alifbo orasida o'giradi;\n"
            "✨ <b>Tugma &amp; Reaksiyalar</b> — tayyor postga URL tugma va reaksiya qo'shadi.\n\n"
            "Kerakli vositani tanlang 👇"
        ),
        "ss_tools_btn_converter": "🔤 Kirill-Lotin Konvertor",
        "ss_tools_btn_enhancer": "✨ Tugma & Reaksiyalar (Post Enhancer)",

        # --- 🎁 Bonuslar & Ballar submenu ---
        "ss_rewards_title": (
            "🎁 <b>Bonuslar &amp; Ballar</b>\n\n"
            "Kerakli bo'limni tanlang 👇"
        ),
        "ss_rewards_points": "💎 Ballarim",
        "ss_rewards_transfer": "🔄 Ballar o'tkazish",
        "ss_rewards_daily_bonus": "🎁 Kunlik bonus",
        "ss_rewards_referral": "👥 Do'stlarni taklif",

        # --- ❓ Yordam & Ma'lumot submenu ---
        "ss_help_hub_title": (
            "❓ <b>Yordam &amp; Ma'lumot</b>\n\n"
            "Kerakli bo'limni tanlang 👇"
        ),
        "ss_help_hub_guide": "📖 Qo'llanma & FAQ",
        "ss_help_hub_support": "💬 Qo'llab-quvvatlash",
        "ss_help_hub_about": "ℹ️ Bot haqida",

        # --- 🔔 Bildirishnomalar ekrani ---
        "ss_notif_title": (
            "🔔 <b>Bildirishnomalar</b>\n\n"
            "Qaysi xabarlarni olishni tanlang:"
        ),
        "ss_notif_scheduled": "📅 Rejalashtirilgan post eslatmalari",
        "ss_notif_news": "📣 Yangiliklar va PRO takliflari",
        "ss_notif_hint": (
            "<i>Sozlamalar darhol saqlanadi va istalgan payt o'zgartirilishi mumkin.</i>"
        ),

        # --- 🎨 Post sozlamalari ekrani ---
        "ss_post_title": (
            "🎨 <b>Post sozlamalari</b>\n\n"
            "Yangi postlarga qo'llaniladigan standartlar:"
        ),
        "ss_post_watermark": "🏷 Bot belgisini (watermark) qo'shish",
        "ss_post_signature": "✍️ Postga imzo qo'shish",
        "ss_post_hint": (
            "<i>Standartlar keyingi postlardan boshlab amal qiladi.</i>"
        ),

        # --- Saqlanish toast'i ---
        "ss_saved": "✅ Saqlandi",
        "ss_switched_on": "✅ Yoqildi",
        "ss_switched_off": "⬜️ O'chirildi",

        # --- 💳 To'lovlar tarixi ekrani ---
        "ss_pay_title": "💳 <b>To'lovlar tarixi</b>",
        "ss_pay_empty": (
            "💳 <b>To'lovlar tarixi</b>\n\n"
            "Hozircha to'lovlaringiz mavjud emas.\n"
            "PRO tarifga o'tish uchun 💎 PRO bo'limidan to'lov qilishingiz mumkin."
        ),
        "ss_pay_row": "{date} • <b>{amount}</b> • {method} {status}",
        "ss_pay_status_succeeded": "✅",
        "ss_pay_status_approved": "✅",
        "ss_pay_status_pending": "⏳",
        "ss_pay_method_stars": "Telegram Stars",
        "ss_pay_method_card": "Karta",
        "ss_pay_count": "Jami: <b>{n} ta</b>",

        # --- ℹ️ Bot haqida ekrani ---
        "ss_about_text": (
            "ℹ️ <b>PostAssist — Telegram kanallar uchun AI yordamchi</b>\n\n"
            "Bot imkoniyatlari:\n"
            "• ✨ Magic Post — g'oyadan 1 daqiqada professional post;\n"
            "• 🎙 Ovoz → Post va 📸 Rasm → Post (STT + Vision);\n"
            "• 📅 Rejalashtirish va avtomatik yuborish;\n"
            "• 📊 Statistika va kanal analitikasi.\n\n"
            "Savollar bo'lsa — ❓ Yordam bo'limiga o'ting yoki "
            "{support} bilan bog'laning."
        ),

        # --- ⚙️ ADMIN PANEL: tizim monitoringi (Health status) bloki ---
        "ss_health_title": "🩺 <b>Tizim monitoringi</b>",
        "ss_health_bot_db": "🖥 Bot & DB: {status}",
        "ss_health_db_latency": " • {ms} ms",
        "ss_health_scheduler": "⏰ Scheduler: {status}",
        "ss_health_jobs": " • {n} jobs",
        "ss_health_ai": "🤖 AI provayderlar",
        "ss_health_ai_row": "   • {name}: {status}",
        "ss_health_pending_pays": "💳 Pending manual to'lovlar: <b>{n} ta</b>",
        "ss_health_btn": "🩺 Tizim monitoringi",
    },

    # ------------------------------------------------------------
    # 🇷🇺 RUS TILI
    # ------------------------------------------------------------
    "ru": {
        # --- 📊 СТАТИСТИКА: компактный общий экран показателей ---
        "ss_stats_title": "📊 <b>Статистика</b>",
        "ss_stats_channels": "📢 Подключено каналов: <b>{n}</b>",
        "ss_stats_created": "📝 Создано постов: <b>{n}</b>",
        "ss_stats_scheduled": "📅 Запланировано постов: <b>{n}</b>",
        "ss_stats_ai": (
            "🤖 AI-запросы: <b>{ai}</b> • 💠 Потрачено кредитов: <b>{credits}</b>"
        ),
        "ss_stats_footer": (
            "<i>🔄 Обновить — показатели будут приведены к текущему состоянию.</i>"
        ),
        "ss_btn_refresh": "🔄 Обновить",
        "ss_btn_back": "◀️ Назад",
        "ss_stats_refreshing": "🔄 Обновляется…",

        # --- 📊 ЛИЧНАЯ СТАТИСТИКА: экран «📊 Статистика» главного меню.
        # Строго отделён от админ-статистики (см. uz-блок).
        "ss_my_title": "📊 <b>Ваша статистика:</b>",
        "ss_my_channels": "📢 Ваши подключённые каналы: <b>{n}</b>",
        "ss_my_created": "📝 Создано ваших постов: <b>{n}</b>",
        "ss_my_scheduled": "📅 Запланированные посты: <b>{n}</b>",
        "ss_my_credits": "💎 Осталось AI-кредитов: <b>{n}</b>",
        "ss_btn_channel_detail": "📈 Детали по каналу",

        # --- ⚙️ НАСТРОЙКИ: единое упорядоченное меню ---
        "ss_menu_title": (
            "⚙️ <b>Настройки</b>\n\n"
            "Выберите раздел 👇"
        ),
        "ss_btn_profile": "👤 Профиль",
        "ss_btn_lang": "🌐 Язык / Language",
        "ss_profile_sub_pro": "⭐️ Подписка: <b>PRO</b> (до {date})",
        "ss_profile_sub_free": "🆓 Подписка: <b>FREE</b>",
        "ss_btn_rewards": "🎁 Бонусы и баллы",
        "ss_btn_help_hub": "❓ Помощь и информация",
        "ss_btn_notif": "🔔 Уведомления",
        "ss_btn_post_settings": "🎨 Настройки постов",
        "ss_btn_payments": "💳 История платежей",
        "ss_btn_referral": "🎁 Пригласить друзей",
        "ss_btn_help": "❓ Помощь",
        "ss_btn_about": "ℹ️ О боте",
        "ss_settings_legacy": "🗂 Быстрые разделы",
        # --- Шаг 3: новые (полные) кнопки хаба ---
        # «🎁 Ежедневный бонус» и «👥 Пригласить друзей» берутся из основного
        # словаря (``cab_btn_daily_bonus`` / ``cab_referral``) — здесь НЕ
        # дублируются.
        "ss_btn_points": "💎 Мои баллы",
        "ss_btn_transfer": "🔄 Перевести баллы",
        "ss_btn_tools": "🧰 Инструменты",

        # --- 🧰 Подменю «Инструменты» ---
        "ss_tools_title": (
            "🧰 <b>Инструменты</b>\n\n"
            "Вспомогательные инструменты помимо основных потоков:\n"
            "🔤 <b>Конвертер Кириллица-Латиница</b> — переводит текст между алфавитами;\n"
            "✨ <b>Кнопки &amp; Реакции</b> — добавляет URL-кнопки и реакции к готовому посту.\n\n"
            "Выберите нужный инструмент 👇"
        ),
        "ss_tools_btn_converter": "🔤 Конвертер Кириллица-Латиница",
        "ss_tools_btn_enhancer": "✨ Кнопки & Реакции (Post Enhancer)",

        # --- 🎁 Подменю «Бонусы и баллы» ---
        "ss_rewards_title": (
            "🎁 <b>Бонусы и баллы</b>\n\n"
            "Выберите нужный раздел 👇"
        ),
        "ss_rewards_points": "💎 Мои баллы",
        "ss_rewards_transfer": "🔄 Перевести баллы",
        "ss_rewards_daily_bonus": "🎁 Ежедневный бонус",
        "ss_rewards_referral": "👥 Пригласить друзей",

        # --- ❓ Подменю «Помощь и информация» ---
        "ss_help_hub_title": (
            "❓ <b>Помощь и информация</b>\n\n"
            "Выберите нужный раздел 👇"
        ),
        "ss_help_hub_guide": "📖 Руководство и FAQ",
        "ss_help_hub_support": "💬 Поддержка",
        "ss_help_hub_about": "ℹ️ О боте",

        # --- 🔔 Уведомления ---
        "ss_notif_title": (
            "🔔 <b>Уведомления</b>\n\n"
            "Выберите, какие сообщения получать:"
        ),
        "ss_notif_scheduled": "📅 Напоминания о запланированных постах",
        "ss_notif_news": "📣 Новости и предложения PRO",
        "ss_notif_hint": (
            "<i>Настройки сохраняются сразу, изменить их можно в любой момент.</i>"
        ),

        # --- 🎨 Настройки постов ---
        "ss_post_title": (
            "🎨 <b>Настройки постов</b>\n\n"
            "Стандарты для новых постов:"
        ),
        "ss_post_watermark": "🏷 Добавлять метку бота (watermark)",
        "ss_post_signature": "✍️ Добавлять подпись к постам",
        "ss_post_hint": (
            "<i>Стандарты действуют начиная со следующих постов.</i>"
        ),

        # --- Тост сохранения ---
        "ss_saved": "✅ Сохранено",
        "ss_switched_on": "✅ Включено",
        "ss_switched_off": "⬜️ Выключено",

        # --- 💳 История платежей ---
        "ss_pay_title": "💳 <b>История платежей</b>",
        "ss_pay_empty": (
            "💳 <b>История платежей</b>\n\n"
            "Платежей пока нет.\n"
            "Перейти на PRO можно в разделе 💎 PRO."
        ),
        "ss_pay_row": "{date} • <b>{amount}</b> • {method} {status}",
        "ss_pay_status_succeeded": "✅",
        "ss_pay_status_approved": "✅",
        "ss_pay_status_pending": "⏳",
        "ss_pay_method_stars": "Telegram Stars",
        "ss_pay_method_card": "Карта",
        "ss_pay_count": "Всего: <b>{n}</b>",

        # --- ℹ️ О боте ---
        "ss_about_text": (
            "ℹ️ <b>PostAssist — AI-помощник для Telegram-каналов</b>\n\n"
            "Возможности бота:\n"
            "• ✨ Magic Post — профессиональный пост из идеи за 1 минуту;\n"
            "• 🎙 Голос → Пост и 📸 Фото → Пост (STT + Vision);\n"
            "• 📅 Планирование и автопубликация;\n"
            "• 📊 Статистика и аналитика каналов.\n\n"
            "Если есть вопросы — откройте раздел ❓ Помощь или "
            "напишите {support}."
        ),

        # --- ⚙️ АДМИН-ПАНЕЛЬ: блок мониторинга системы (Health) ---
        "ss_health_title": "🩺 <b>Мониторинг системы</b>",
        "ss_health_bot_db": "🖥 Бот & БД: {status}",
        "ss_health_db_latency": " • {ms} мс",
        "ss_health_scheduler": "⏰ Планировщик: {status}",
        "ss_health_jobs": " • {n} задач",
        "ss_health_ai": "🤖 AI-провайдеры",
        "ss_health_ai_row": "   • {name}: {status}",
        "ss_health_pending_pays": "💳 Ожидают ручной проверки: <b>{n}</b>",
        "ss_health_btn": "🩺 Мониторинг системы",
    },

    # ------------------------------------------------------------
    # 🇬🇧 ENGLISH
    # ------------------------------------------------------------
    "en": {
        # --- 📊 STATISTICS: compact overview screen ---
        "ss_stats_title": "📊 <b>Statistics</b>",
        "ss_stats_channels": "📢 Connected channels: <b>{n}</b>",
        "ss_stats_created": "📝 Posts created: <b>{n}</b>",
        "ss_stats_scheduled": "📅 Scheduled posts: <b>{n}</b>",
        "ss_stats_ai": (
            "🤖 AI requests: <b>{ai}</b> • 💠 Credits spent: <b>{credits}</b>"
        ),
        "ss_stats_footer": (
            "<i>🔄 Refresh — metrics will be updated to the current state.</i>"
        ),
        "ss_btn_refresh": "🔄 Refresh",
        "ss_btn_back": "◀️ Back",
        "ss_stats_refreshing": "🔄 Refreshing…",

        # --- 📊 PERSONAL STATISTICS: the main menu "📊 Statistics" screen.
        # Strictly separated from admin stats (see the uz block).
        "ss_my_title": "📊 <b>Your statistics:</b>",
        "ss_my_channels": "📢 Your connected channels: <b>{n}</b>",
        "ss_my_created": "📝 Your posts created: <b>{n}</b>",
        "ss_my_scheduled": "📅 Scheduled posts: <b>{n}</b>",
        "ss_my_credits": "💎 AI credits remaining: <b>{n}</b>",
        "ss_btn_channel_detail": "📈 Per-channel details",

        # --- ⚙️ SETTINGS: single ordered menu ---
        "ss_menu_title": (
            "⚙️ <b>Settings</b>\n\n"
            "Pick a section 👇"
        ),
        "ss_btn_profile": "👤 Profile",
        "ss_btn_lang": "🌐 Language",
        "ss_profile_sub_pro": "⭐️ Subscription: <b>PRO</b> (until {date})",
        "ss_profile_sub_free": "🆓 Subscription: <b>FREE</b>",
        "ss_btn_rewards": "🎁 Bonuses & Credits",
        "ss_btn_help_hub": "❓ Help & Info",
        "ss_btn_notif": "🔔 Notifications",
        "ss_btn_post_settings": "🎨 Post settings",
        "ss_btn_payments": "💳 Payment history",
        "ss_btn_referral": "🎁 Invite friends",
        "ss_btn_help": "❓ Help",
        "ss_btn_about": "ℹ️ About",
        "ss_settings_legacy": "🗂 Quick sections",
        # --- Step 3: new (full) hub buttons ---
        # "🎁 Daily bonus" and "👥 Invite friends" come from the main
        # dictionary (``cab_btn_daily_bonus`` / ``cab_referral``) — they are
        # NOT duplicated here.
        "ss_btn_points": "💎 My credits",
        "ss_btn_transfer": "🔄 Transfer credits",
        "ss_btn_tools": "🧰 Tools",

        # --- 🧰 Tools submenu ---
        "ss_tools_title": (
            "🧰 <b>Tools</b>\n\n"
            "Helper tools alongside the main flows:\n"
            "🔤 <b>Cyrillic-Latin Converter</b> — converts text between the two alphabets;\n"
            "✨ <b>Buttons &amp; Reactions</b> — adds URL buttons and reactions to a ready post.\n\n"
            "Pick a tool below 👇"
        ),
        "ss_tools_btn_converter": "🔤 Cyrillic-Latin Converter",
        "ss_tools_btn_enhancer": "✨ Buttons & Reactions (Post Enhancer)",

        # --- 🎁 Bonuses & Credits submenu ---
        "ss_rewards_title": (
            "🎁 <b>Bonuses &amp; Credits</b>\n\n"
            "Choose a section below 👇"
        ),
        "ss_rewards_points": "💎 My credits",
        "ss_rewards_transfer": "🔄 Transfer credits",
        "ss_rewards_daily_bonus": "🎁 Daily bonus",
        "ss_rewards_referral": "👥 Invite friends",

        # --- ❓ Help & Info submenu ---
        "ss_help_hub_title": (
            "❓ <b>Help &amp; Info</b>\n\n"
            "Choose a section below 👇"
        ),
        "ss_help_hub_guide": "📖 Guide & FAQ",
        "ss_help_hub_support": "💬 Contact support",
        "ss_help_hub_about": "ℹ️ About the bot",

        # --- 🔔 Notifications ---
        "ss_notif_title": (
            "🔔 <b>Notifications</b>\n\n"
            "Choose which messages to receive:"
        ),
        "ss_notif_scheduled": "📅 Scheduled post reminders",
        "ss_notif_news": "📣 News and PRO offers",
        "ss_notif_hint": (
            "<i>Settings are saved instantly and can be changed at any time.</i>"
        ),

        # --- 🎨 Post settings ---
        "ss_post_title": (
            "🎨 <b>Post settings</b>\n\n"
            "Defaults applied to new posts:"
        ),
        "ss_post_watermark": "🏷 Add bot watermark",
        "ss_post_signature": "✍️ Add signature to posts",
        "ss_post_hint": (
            "<i>Defaults apply starting from the next posts.</i>"
        ),

        # --- Saved toast ---
        "ss_saved": "✅ Saved",
        "ss_switched_on": "✅ Enabled",
        "ss_switched_off": "⬜️ Disabled",

        # --- 💳 Payment history ---
        "ss_pay_title": "💳 <b>Payment history</b>",
        "ss_pay_empty": (
            "💳 <b>Payment history</b>\n\n"
            "You have no payments yet.\n"
            "You can upgrade in the 💎 PRO section."
        ),
        "ss_pay_row": "{date} • <b>{amount}</b> • {method} {status}",
        "ss_pay_status_succeeded": "✅",
        "ss_pay_status_approved": "✅",
        "ss_pay_status_pending": "⏳",
        "ss_pay_method_stars": "Telegram Stars",
        "ss_pay_method_card": "Card",
        "ss_pay_count": "Total: <b>{n}</b>",

        # --- ℹ️ About ---
        "ss_about_text": (
            "ℹ️ <b>PostAssist — AI assistant for Telegram channels</b>\n\n"
            "What the bot can do:\n"
            "• ✨ Magic Post — a professional post from an idea in 1 minute;\n"
            "• 🎙 Voice → Post and 📸 Image → Post (STT + Vision);\n"
            "• 📅 Scheduling and auto-publishing;\n"
            "• 📊 Statistics and channel analytics.\n\n"
            "Questions? Open the ❓ Help section or contact {support}."
        ),

        # --- ⚙️ ADMIN PANEL: system monitoring (Health) block ---
        "ss_health_title": "🩺 <b>System monitoring</b>",
        "ss_health_bot_db": "🖥 Bot & DB: {status}",
        "ss_health_db_latency": " • {ms} ms",
        "ss_health_scheduler": "⏰ Scheduler: {status}",
        "ss_health_jobs": " • {n} jobs",
        "ss_health_ai": "🤖 AI providers",
        "ss_health_ai_row": "   • {name}: {status}",
        "ss_health_pending_pays": "💳 Pending manual payments: <b>{n}</b>",
        "ss_health_btn": "🩺 System monitoring",
    },
}

#: Barcha kalitlar (paritet auditi va testlar uchun yagona ro'yxat).
SETTINGS_STATS_KEYS = tuple(sorted(SETTINGS_STATS_I18N["uz"].keys()))

# ============================================================
# ⚙️ SOZLAMALAR MENYUSI — 8 GURUH + ORQAGA
# ============================================================
#: Asosiy hubdagi tugmalar — spetsifikatsiyadagi aniq tartib.
SETTINGS_MENU_BUTTON_KEYS = (
    "ss_btn_profile",
    "ss_btn_lang",
    "ss_btn_rewards",
    "ss_btn_post_settings",
    "ss_btn_notif",
    "ss_btn_payments",
    "ss_btn_tools",
    "ss_btn_help_hub",
    "ss_btn_back",
)

#: 🎁 Bonuslar & Ballar submenu'si tugma kalitlari.
SETTINGS_REWARDS_BUTTON_KEYS = (
    "ss_rewards_points",
    "ss_rewards_transfer",
    "ss_rewards_daily_bonus",
    "ss_rewards_referral",
    "ss_btn_back",
)
REWARDS_MENU_BUTTON_KEYS = SETTINGS_REWARDS_BUTTON_KEYS

#: ❓ Yordam & Ma'lumot submenu'si tugma kalitlari.
SETTINGS_HELP_HUB_BUTTON_KEYS = (
    "ss_help_hub_guide",
    "ss_help_hub_support",
    "ss_help_hub_about",
    "ss_btn_back",
)
HELP_HUB_BUTTON_KEYS = SETTINGS_HELP_HUB_BUTTON_KEYS

#: 🧰 Vositalar submenyusi tugma kalitlari.
TOOLS_MENU_BUTTON_KEYS = (
    "ss_tools_btn_converter",
    "ss_tools_btn_enhancer",
    "ss_btn_back",
)

#: Statistika ekranidagi 4 ta asosiy ko'rsatkich qatori — spek tartibida.
STATS_ROW_KEYS = (
    "ss_stats_channels",
    "ss_stats_created",
    "ss_stats_scheduled",
    "ss_stats_ai",
)

#: 📊 SHAXSIY statistika ekranidagi 4 ta ko'rsatkich qatori.
MY_STATS_ROW_KEYS = (
    "ss_my_channels",
    "ss_my_created",
    "ss_my_scheduled",
    "ss_my_credits",
)

#: Sozlamalar callback'lari (routing tilga bog'liq emas).
CB_SETTINGS_PREFIX = "stgs_"
CB_STATS_REFRESH = "an_refresh"
CB_STATS_BACK = "an_close"
CB_STATS_DETAIL = "an_detail"
CB_STATS_OVERVIEW = "an_overview"

#: Asosiy 8 guruhli Sozlamalar hub'i.
CB_SETTINGS_HUB = (
    "stgs_profile",
    "stgs_lang",
    "stgs_rewards",
    "stgs_post",
    "stgs_notif",
    "stgs_pay",
    "stgs_tools",
    "stgs_help_hub",
    "stgs_back",
)

#: 🎁 Bonuslar & Ballar submenu'si.
CB_SETTINGS_REWARDS = (
    "stgs_credits",
    "stgs_transfer",
    "claim_bonus",
    "referral_hub",
    "stgs_hub",
)
CB_REWARDS_HUB = CB_SETTINGS_REWARDS

#: ❓ Yordam & Ma'lumot submenu'si.
CB_SETTINGS_HELP_HUB = (
    "help_hub",
    "help_support",
    "stgs_about",
    "stgs_hub",
)
CB_HELP_HUB = CB_SETTINGS_HELP_HUB

#: 🧰 Vositalar submenu'si.
CB_TOOLS_HUB = ("extra_converter", "extra_enhancer", "stgs_hub")


def settings_stats_t(key: str, lang: str = "uz", **kwargs) -> str:
    """⚙️ Sozlamalar / 📊 Statistika matnini qaytaradi (uz / ru / en).

    Mantiq ``channels_queue_t`` bilan bir xil: kalit bu modulda bo'lmasa
    asosiy repo lug'atiga (``safe_t``) tushadi — shu sababli ``lang_button``
    kabi umumiy kalitlar ham shu funksiya orqali ishlaydi.
    """
    code = normalize_lang(lang)
    table = SETTINGS_STATS_I18N.get(code) or {}
    text = table.get(key)
    if text is None:
        text = (SETTINGS_STATS_I18N.get("uz") or {}).get(key)
    if text is None:
        return safe_t(key, code, **kwargs)
    try:
        return text.format(**kwargs) if kwargs else text
    except Exception:  # pragma: no cover - format himoyasi
        return text


def settings_stats_parity_report(langs=("uz", "ru", "en")) -> dict:
    """UZ ↔ RU ↔ EN kalit va format-argument pariteti hisoboti.

    ``channels_queue_parity_report`` bilan bir xil struktura:
    ``{"keys", "missing", "extra", "format_mismatch", "empty", "in_sync"}``.
    """
    from locales.translations import format_args

    base = SETTINGS_STATS_I18N.get("uz") or {}
    base_keys = set(base)
    missing, extra, fmt_mismatch, empty = {}, {}, {}, []
    for lang in langs:
        if lang == "uz":
            continue
        table = SETTINGS_STATS_I18N.get(lang) or {}
        lang_keys = set(table)
        missing[lang] = sorted(base_keys - lang_keys)
        extra[lang] = sorted(lang_keys - base_keys)
        for key in base_keys & lang_keys:
            if format_args(base[key]) != format_args(table[key]):
                fmt_mismatch.setdefault(
                    key, {"uz": format_args(base[key]), lang: format_args(table[key])}
                )
    for lang in langs:
        table = SETTINGS_STATS_I18N.get(lang) or {}
        for key, value in table.items():
            if not isinstance(value, str) or not value.strip():
                empty.append(f"{lang}:{key}")
    return {
        "keys": len(base_keys),
        "missing": missing,
        "extra": extra,
        "format_mismatch": fmt_mismatch,
        "empty": empty,
        "in_sync": (
            not any(missing.values())
            and not any(extra.values())
            and not fmt_mismatch
            and not empty
        ),
    }
