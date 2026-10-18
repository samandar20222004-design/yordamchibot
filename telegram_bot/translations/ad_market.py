"""💰 REKLAMA BIRJASI — i18n lug'ati (UZ / RU / EN, 100% paritet).

Bot ichidagi kanallar o'rtasidagi reklama bozori matnlarining yagona manbasi
(``handlers/ad_market.py``). Boshqa ``translations/*`` modullari kabi asosiy lug'atga tegmaydi;
UZ↔RU↔EN pariteti ``ad_market_parity_report()`` orqali testda qo'riqlanadi.

Tugma yorlig'i (``mk_btn_*``) 18 belgidan oshmaydi (``tests/ad_market_test.py`` tekshiradi).
"""

from locales.translations import normalize_lang, safe_t

AD_MARKET_I18N = {
    "uz": {
        "mk_offer": (
            "💰 <b>Kanalingizga reklama beruvchi toping!</b>\n"
            "Kanalni Reklama birjasiga qo'ying: reklama beruvchilar ko'rsatkichlaringizni ko'rib, "
            "so'rovni shu bot orqali yuboradi. Bepul, 1 daqiqa."
        ),
        "mk_offer_btn": "💰 Birjaga qo'yish",
        "mk_peer_unreachable": "Xabar yetkazib bo'lmadi: qabul qiluvchi botni to'xtatgan bo'lishi mumkin.",
        "mk_stale": "Seans eskirgan. Qaytadan boshlang: /market",
        # --- Bosh ekran ---
        "mk_home": (
            "💰 <b>Reklama birjasi</b>\n\n"
            "Kanallar o'rtasida reklama: kanal ko'rsatkichlarini ko'ring va egasi bilan bot orqali kelishing.\n\n"
            "🔎 <b>Reklama beruvchi</b> — katalogdan kanal toping\n"
            "📢 <b>Kanal egasi</b> — kanalingizni qo'ying, so'rovlar shu yerga keladi\n\n"
            "📊 Birjada: <b>{listings}</b> ta kanal · <b>{inquiries}</b> ta so'rov"
        ),
        "mk_btn_catalog": "🔎 Katalog",
        "mk_btn_my": "📢 Kanal qo'yish",
        "mk_btn_inbox": "💬 Suhbatlar",
        "mk_btn_how": "ℹ️ Qanday ishlaydi",
        "mk_btn_close": "❌ Yopish",
        "mk_btn_back": "◀️ Orqaga",
        "mk_btn_channel": "💰 Reklama birjasi",
        "mk_how": (
            "ℹ️ <b>Birja qanday ishlaydi</b>\n\n"
            "1️⃣ Kanal egasi kanalini qo'yadi: mavzu, narx, tavsif. Obunachi, ko'rish va faollik (ER) botning "
            "o'z ma'lumotidan olinadi — qo'lda yozilmaydi.\n"
            "2️⃣ Reklama beruvchi katalogdan kanal tanlab, so'rov yozadi.\n"
            "3️⃣ Egasiga so'rov bot orqali boradi; ikkalasi shu yerda yozishadi. Xohlasangiz, kontaktingizni "
            "o'zingiz ulashasiz.\n\n"
            "🛡 <b>Xavfsizlik</b>\n"
            "• Pul bot orqali o'tmaydi — kelishuv tomonlar o'rtasida. Oldindan to'lovdan ehtiyot bo'ling.\n"
            "• Shubhali e'longa ⚠️ Shikoyat bering: 3 ta shikoyatdan keyin e'lon avtomatik yashiriladi.\n"
            "• Egasi istalmagan odamni ⛔ bloklashi mumkin."
        ),
        # --- Katalog ---
        "mk_cat_pick": "🔎 <b>Katalog</b>\nMavzuni tanlang:",
        "mk_cat_all": "🌐 Hammasi",
        "mk_cat_news": "📰 Yangiliklar",
        "mk_cat_tech": "💻 Texnologiya",
        "mk_cat_business": "💼 Biznes",
        "mk_cat_education": "🎓 Ta'lim",
        "mk_cat_entertainment": "🎬 Ko'ngilochar",
        "mk_cat_lifestyle": "🌿 Turmush tarzi",
        "mk_cat_sport": "⚽ Sport",
        "mk_cat_shop": "🛍 Savdo",
        "mk_cat_auto": "🚗 Avto va ko'chmas mulk",
        "mk_cat_other": "📌 Boshqa",
        "mk_list_title": "🔎 <b>Katalog</b> · {cat}\nTopildi: <b>{total}</b> ta · saralash: {sort} · {page}/{pages}",
        "mk_list_empty": (
            "Bu mavzuda hozircha kanal yo'q.\n"
            "Birinchi bo'lib kanalingizni qo'ying — reklama beruvchilar sizni birinchi ko'radi! 📢"
        ),
        "mk_sort_m": "👥 Obunachi",
        "mk_sort_p": "💲 Narx",
        "mk_sort_e": "📈 Faollik",
        "mk_price_negotiable": "kelishiladi",
        # --- Kanal kartasi ---
        "mk_f_members": "👥 Obunachi",
        "mk_f_growth": "30 kunda",
        "mk_f_views": "👁 O'rtacha ko'rish",
        "mk_f_er": "📈 Faollik (ER)",
        "mk_f_posts": "📝 30 kunda postlar",
        "mk_f_price": "💲 1 post narxi",
        "mk_currency": "so'm",
        "mk_views_unknown": "ma'lumot yetarli emas",
        "mk_badge_growing": "📈 O'smoqda",
        "mk_badge_engaged": "🔥 Faol auditoriya",
        "mk_badge_active": "⚡ Muntazam postlar",
        "mk_verified": "✅ Kanal egaligi bot orqali tekshirilgan",
        "mk_updated": "🕒 Ko'rsatkichlar yangilangan: {when}",
        "mk_stats_note": "ℹ️ Ko'rish va ER faqat bot ko'rgan postlar bo'yicha hisoblanadi.",
        "mk_btn_contact": "✉️ Reklama so'rovi",
        "mk_btn_open": "🔗 Kanalni ochish",
        "mk_btn_report": "⚠️ Shikoyat",
        "mk_gone": "Bu e'lon endi mavjud emas.",
        # --- So'rov va yozishma ---
        "mk_inq_prompt": (
            "✉️ <b>{title}</b> egasiga so'rov yozing:\n"
            "• qanday reklama (mahsulot/xizmat)\n• qachon chiqarmoqchisiz\n• byudjetingiz\n\n"
            "{min}–{max} belgi. Bekor qilish: /cancel"
        ),
        "mk_inq_short": "Juda qisqa. Kamida {min} belgi yozing (bekor qilish: /cancel).",
        "mk_inq_sent": "✅ So'rov yuborildi. Egasi javob bersa, xabar shu yerga keladi (💬 Suhbatlar).",
        "mk_inq_limit": "Kuniga {limit} tadan ko'p yangi so'rov yuborib bo'lmaydi. Ertaga urinib ko'ring.",
        "mk_inq_blocked": "Bu kanal egasi sizdan so'rov qabul qilmaydi.",
        "mk_inq_own": "Bu sizning kanalingiz.",
        "mk_inq_exists": "Bu kanal bilan ochiq suhbatingiz bor — 💬 Suhbatlar bo'limidan davom eting.",
        "mk_inq_owner_new": (
            "📩 <b>Yangi reklama so'rovi!</b>\nKanal: <b>{title}</b>\n\n{text}\n\n"
            "<i>Javob bering — xabar bot orqali yetkaziladi. Profilingiz faqat o'zingiz ruxsat bersangiz ulashiladi.</i>"
        ),
        "mk_btn_reply": "💬 Javob berish",
        "mk_btn_share": "👤 Kontakt berish",
        "mk_btn_end": "✅ Yopish",
        "mk_btn_block": "⛔ Bloklash",
        "mk_role_owner": "Kanal egasi",
        "mk_role_adv": "Reklama beruvchi",
        "mk_you": "Siz",
        "mk_thread": "💬 <b>{title}</b> · {role}\n\n{messages}",
        "mk_reply_prompt": "💬 Xabaringizni yozing (bekor qilish: /cancel).",
        "mk_msg_in": "💬 <b>{title}</b> — {role}:\n\n{text}",
        "mk_msg_sent": "✅ Yuborildi.",
        "mk_thread_closed": "Bu suhbat yopilgan.",
        "mk_thread_full": "Suhbat xabar limiti ({limit}) tugadi. 👤 Kontakt berish orqali shaxsiy gaplashing.",
        "mk_contact_in": "👤 {role} kontaktini ulashdi: {contact}",
        "mk_contact_sent": "✅ Kontaktingiz yuborildi.",
        "mk_closed_notice": "ℹ️ Suhbat yopildi: {title}",
        "mk_blocked_ok": "⛔ Foydalanuvchi bloklandi, suhbatlari yopildi.",
        "mk_inbox_title": "💬 <b>Suhbatlar</b>\nOchiq suhbatni tanlang:",
        "mk_inbox_empty": "Hozircha ochiq suhbat yo'q.",
        "mk_report_ok": "⚠️ Shikoyat qabul qilindi. Rahmat!",
        "mk_report_again": "Siz bu e'londan allaqachon shikoyat qilgansiz.",
        "mk_report_own": "O'z e'loningizdan shikoyat qilib bo'lmaydi.",
        "mk_admin_blocked": "⚠️ Birja: e'lon #{id} (@{username}) {count} ta shikoyat tufayli avtomatik bloklandi.",
        # --- Kanal egasi ---
        "mk_my_title": "📢 <b>Kanal qo'yish</b>\nKanalingizni tanlang:",
        "mk_my_empty": "Avval kanal qo'shing: 📢 Kanallarim → Kanal qo'shish.",
        "mk_st_active": "🟢",
        "mk_st_paused": "⏸",
        "mk_st_blocked": "⛔",
        "mk_st_none": "➕",
        "mk_new_intro": (
            "🚀 <b>{title}</b> — birjaga chiqarish\n\n"
            "Shartlar: kanal ochiq (username bor), bot kanalda admin, siz ham kanal adminisiz. "
            "Ko'rsatkichlar bot ma'lumotidan avtomatik olinadi.\n\n"
            "1/3 — mavzuni tanlang:"
        ),
        "mk_err_private": "Kanalda username yo'q (yopiq kanal). Birjada faqat ochiq kanallar bo'ladi — kanal sozlamasida username o'rnating.",
        "mk_err_admin": "Egalikni tasdiqlab bo'lmadi: siz kanalda admin bo'lishingiz va bot ham admin bo'lishi kerak.",
        "mk_err_limit": "Bitta hisobdan ko'pi bilan {limit} ta kanal qo'yish mumkin.",
        "mk_err_tg": "Telegram bilan bog'lanib bo'lmadi. Birozdan keyin urinib ko'ring.",
        "mk_err_generic": "Xatolik yuz berdi. Birozdan keyin urinib ko'ring.",
        "mk_price_prompt": (
            "2/3 — 1 ta post reklamasi narxi (so'mda).\n"
            "Masalan: <code>50000</code>, <code>50k</code>, <code>1.5 mln</code>. "
            "Kelishiladigan bo'lsa: «kelishiladi». Bekor qilish: /cancel"
        ),
        "mk_price_bad": "Narx tushunarsiz. Masalan: 50000, 50k yoki «kelishiladi» ({min}–{max} so'm).",
        "mk_desc_prompt": (
            "3/3 — kanal haqida qisqa tavsif (mavzu, auditoriya; {max} belgigacha). "
            "O'tkazib yuborish: «-». Bekor qilish: /cancel"
        ),
        "mk_published": (
            "🎉 <b>E'lon qilindi!</b>\nEndi reklama beruvchilar kanalingizni katalogda ko'radi, "
            "so'rovlar shu botga keladi."
        ),
        "mk_manage": "📊 Ko'rishlar: <b>{views}</b> · ✉️ So'rovlar: <b>{inquiries}</b>",
        "mk_btn_price": "💲 Narx",
        "mk_btn_desc": "📝 Tavsif",
        "mk_btn_cat": "🏷 Mavzu",
        "mk_btn_pause": "⏸ To'xtatish",
        "mk_btn_resume": "▶️ Faollashtirish",
        "mk_btn_refresh": "🔄 Yangilash",
        "mk_btn_delete": "🗑 Olib tashlash",
        "mk_btn_yes": "✅ Ha",
        "mk_btn_no": "❌ Yo'q",
        "mk_confirm_delete": "E'lonni birjadan olib tashlaysizmi? Ochiq suhbatlar ham o'chadi.",
        "mk_saved": "✅ Saqlandi.",
        "mk_paused": "⏸ E'lon to'xtatildi — katalogda ko'rinmaydi.",
        "mk_resumed": "▶️ E'lon yana katalogda.",
        "mk_deleted": "🗑 E'lon olib tashlandi.",
        "mk_listing_blocked": "⛔ E'lon shikoyatlar tufayli bloklangan. Tekshiruv uchun qo'llab-quvvatlashga yozing.",
        "mk_refreshed": "🔄 Ko'rsatkichlar yangilandi.",
        "mk_cancelled": "Bekor qilindi.",
    },
    "ru": {
        "mk_offer": (
            "💰 <b>Найдите рекламодателей для своего канала!</b>\n"
            "Разместите канал на Бирже рекламы: рекламодатели увидят ваши показатели "
            "и отправят заявку через этого бота. Бесплатно, 1 минута."
        ),
        "mk_offer_btn": "💰 На биржу",
        "mk_peer_unreachable": "Не удалось доставить сообщение: получатель мог остановить бота.",
        "mk_stale": "Сессия устарела. Начните заново: /market",
        "mk_home": (
            "💰 <b>Биржа рекламы</b>\n\n"
            "Реклама между каналами: смотрите показатели каналов и договаривайтесь с владельцем через бот.\n\n"
            "🔎 <b>Рекламодатель</b> — найдите канал в каталоге\n"
            "📢 <b>Владелец канала</b> — разместите канал, заявки придут сюда\n\n"
            "📊 На бирже: <b>{listings}</b> каналов · <b>{inquiries}</b> заявок"
        ),
        "mk_btn_catalog": "🔎 Каталог",
        "mk_btn_my": "📢 Разместить канал",
        "mk_btn_inbox": "💬 Диалоги",
        "mk_btn_how": "ℹ️ Как работает",
        "mk_btn_close": "❌ Закрыть",
        "mk_btn_back": "◀️ Назад",
        "mk_btn_channel": "💰 Биржа рекламы",
        "mk_how": (
            "ℹ️ <b>Как работает биржа</b>\n\n"
            "1️⃣ Владелец размещает канал: тема, цена, описание. Подписчики, просмотры и вовлечённость (ER) "
            "берутся из данных бота, а не вводятся вручную.\n"
            "2️⃣ Рекламодатель выбирает канал в каталоге и пишет заявку.\n"
            "3️⃣ Заявка доходит до владельца через бота; они переписываются здесь. Свой контакт вы "
            "передаёте сами, по желанию.\n\n"
            "🛡 <b>Безопасность</b>\n"
            "• Деньги через бота не проходят — договорённость между сторонами. Остерегайтесь предоплаты.\n"
            "• На подозрительное объявление нажмите ⚠️ Жалоба: после 3 жалоб объявление скрывается автоматически.\n"
            "• Владелец может ⛔ заблокировать нежелательного собеседника."
        ),
        "mk_cat_pick": "🔎 <b>Каталог</b>\nВыберите тему:",
        "mk_cat_all": "🌐 Все",
        "mk_cat_news": "📰 Новости",
        "mk_cat_tech": "💻 Технологии",
        "mk_cat_business": "💼 Бизнес",
        "mk_cat_education": "🎓 Образование",
        "mk_cat_entertainment": "🎬 Развлечения",
        "mk_cat_lifestyle": "🌿 Образ жизни",
        "mk_cat_sport": "⚽ Спорт",
        "mk_cat_shop": "🛍 Торговля",
        "mk_cat_auto": "🚗 Авто и недвижимость",
        "mk_cat_other": "📌 Другое",
        "mk_list_title": "🔎 <b>Каталог</b> · {cat}\nНайдено: <b>{total}</b> · сортировка: {sort} · {page}/{pages}",
        "mk_list_empty": (
            "В этой теме пока нет каналов.\n"
            "Разместите канал первым — рекламодатели увидят вас раньше всех! 📢"
        ),
        "mk_sort_m": "👥 Подписчики",
        "mk_sort_p": "💲 Цена",
        "mk_sort_e": "📈 Вовлечённость",
        "mk_price_negotiable": "договорная",
        "mk_f_members": "👥 Подписчики",
        "mk_f_growth": "за 30 дней",
        "mk_f_views": "👁 Средние просмотры",
        "mk_f_er": "📈 Вовлечённость (ER)",
        "mk_f_posts": "📝 Постов за 30 дней",
        "mk_f_price": "💲 Цена 1 поста",
        "mk_currency": "сум",
        "mk_views_unknown": "данных недостаточно",
        "mk_badge_growing": "📈 Растёт",
        "mk_badge_engaged": "🔥 Активная аудитория",
        "mk_badge_active": "⚡ Регулярные посты",
        "mk_verified": "✅ Владение каналом подтверждено ботом",
        "mk_updated": "🕒 Показатели обновлены: {when}",
        "mk_stats_note": "ℹ️ Просмотры и ER считаются только по постам, которые видел бот.",
        "mk_btn_contact": "✉️ Заявка",
        "mk_btn_open": "🔗 Открыть канал",
        "mk_btn_report": "⚠️ Жалоба",
        "mk_gone": "Это объявление больше не доступно.",
        "mk_inq_prompt": (
            "✉️ Напишите заявку владельцу <b>{title}</b>:\n"
            "• что рекламируете (товар/услуга)\n• когда хотите выйти\n• ваш бюджет\n\n"
            "{min}–{max} символов. Отмена: /cancel"
        ),
        "mk_inq_short": "Слишком коротко. Напишите минимум {min} символов (отмена: /cancel).",
        "mk_inq_sent": "✅ Заявка отправлена. Если владелец ответит, сообщение придёт сюда (💬 Диалоги).",
        "mk_inq_limit": "Нельзя отправлять больше {limit} новых заявок в сутки. Попробуйте завтра.",
        "mk_inq_blocked": "Владелец этого канала не принимает заявки от вас.",
        "mk_inq_own": "Это ваш канал.",
        "mk_inq_exists": "У вас уже есть открытый диалог с этим каналом — продолжите в разделе 💬 Диалоги.",
        "mk_inq_owner_new": (
            "📩 <b>Новая рекламная заявка!</b>\nКанал: <b>{title}</b>\n\n{text}\n\n"
            "<i>Ответьте — сообщение будет доставлено через бота. Ваш профиль передаётся только с вашего разрешения.</i>"
        ),
        "mk_btn_reply": "💬 Ответить",
        "mk_btn_share": "👤 Дать контакт",
        "mk_btn_end": "✅ Закрыть",
        "mk_btn_block": "⛔ Блок",
        "mk_role_owner": "Владелец канала",
        "mk_role_adv": "Рекламодатель",
        "mk_you": "Вы",
        "mk_thread": "💬 <b>{title}</b> · {role}\n\n{messages}",
        "mk_reply_prompt": "💬 Напишите сообщение (отмена: /cancel).",
        "mk_msg_in": "💬 <b>{title}</b> — {role}:\n\n{text}",
        "mk_msg_sent": "✅ Отправлено.",
        "mk_thread_closed": "Этот диалог закрыт.",
        "mk_thread_full": "Лимит сообщений в диалоге ({limit}) исчерпан. Передайте контакт через 👤 Дать контакт и общайтесь лично.",
        "mk_contact_in": "👤 {role} поделился контактом: {contact}",
        "mk_contact_sent": "✅ Ваш контакт отправлен.",
        "mk_closed_notice": "ℹ️ Диалог закрыт: {title}",
        "mk_blocked_ok": "⛔ Пользователь заблокирован, его диалоги закрыты.",
        "mk_inbox_title": "💬 <b>Диалоги</b>\nВыберите открытый диалог:",
        "mk_inbox_empty": "Открытых диалогов пока нет.",
        "mk_report_ok": "⚠️ Жалоба принята. Спасибо!",
        "mk_report_again": "Вы уже жаловались на это объявление.",
        "mk_report_own": "Нельзя жаловаться на своё объявление.",
        "mk_admin_blocked": "⚠️ Биржа: объявление #{id} (@{username}) автоматически заблокировано после {count} жалоб.",
        "mk_my_title": "📢 <b>Разместить канал</b>\nВыберите канал:",
        "mk_my_empty": "Сначала добавьте канал: 📢 Мои каналы → Добавить канал.",
        "mk_st_active": "🟢",
        "mk_st_paused": "⏸",
        "mk_st_blocked": "⛔",
        "mk_st_none": "➕",
        "mk_new_intro": (
            "🚀 <b>{title}</b> — размещение на бирже\n\n"
            "Условия: канал открытый (есть username), бот — админ канала, вы тоже админ. "
            "Показатели берутся из данных бота автоматически.\n\n"
            "1/3 — выберите тему:"
        ),
        "mk_err_private": "У канала нет username (закрытый канал). На бирже только открытые каналы — задайте username в настройках канала.",
        "mk_err_admin": "Не удалось подтвердить владение: вы должны быть админом канала, и бот тоже должен быть админом.",
        "mk_err_limit": "С одного аккаунта можно разместить не более {limit} каналов.",
        "mk_err_tg": "Не удалось связаться с Telegram. Попробуйте чуть позже.",
        "mk_err_generic": "Произошла ошибка. Попробуйте чуть позже.",
        "mk_price_prompt": (
            "2/3 — цена рекламы 1 поста (в сумах).\n"
            "Например: <code>50000</code>, <code>50k</code>, <code>1.5 млн</code>. "
            "Если договорная: «договорная». Отмена: /cancel"
        ),
        "mk_price_bad": "Цена непонятна. Например: 50000, 50k или «договорная» ({min}–{max} сум).",
        "mk_desc_prompt": (
            "3/3 — короткое описание канала (тема, аудитория; до {max} символов). "
            "Пропустить: «-». Отмена: /cancel"
        ),
        "mk_published": (
            "🎉 <b>Объявление опубликовано!</b>\nТеперь рекламодатели увидят ваш канал в каталоге, "
            "заявки будут приходить в этот бот."
        ),
        "mk_manage": "📊 Просмотры: <b>{views}</b> · ✉️ Заявки: <b>{inquiries}</b>",
        "mk_btn_price": "💲 Цена",
        "mk_btn_desc": "📝 Описание",
        "mk_btn_cat": "🏷 Тема",
        "mk_btn_pause": "⏸ Приостановить",
        "mk_btn_resume": "▶️ Включить",
        "mk_btn_refresh": "🔄 Обновить",
        "mk_btn_delete": "🗑 Снять",
        "mk_btn_yes": "✅ Да",
        "mk_btn_no": "❌ Нет",
        "mk_confirm_delete": "Снять объявление с биржи? Открытые диалоги тоже удалятся.",
        "mk_saved": "✅ Сохранено.",
        "mk_paused": "⏸ Объявление приостановлено — не видно в каталоге.",
        "mk_resumed": "▶️ Объявление снова в каталоге.",
        "mk_deleted": "🗑 Объявление снято.",
        "mk_listing_blocked": "⛔ Объявление заблокировано из-за жалоб. Для проверки напишите в поддержку.",
        "mk_refreshed": "🔄 Показатели обновлены.",
        "mk_cancelled": "Отменено.",
    },
    "en": {
        "mk_offer": (
            "💰 <b>Find advertisers for your channel!</b>\n"
            "List your channel on the Ad exchange: advertisers see your stats "
            "and send requests through this bot. Free, takes a minute."
        ),
        "mk_offer_btn": "💰 List channel",
        "mk_peer_unreachable": "Message not delivered: the recipient may have stopped the bot.",
        "mk_stale": "Session expired. Start again: /market",
        "mk_home": (
            "💰 <b>Ad exchange</b>\n\n"
            "Advertising between channels: see channel stats and agree with the owner through the bot.\n\n"
            "🔎 <b>Advertiser</b> — find a channel in the catalog\n"
            "📢 <b>Channel owner</b> — list your channel, requests arrive here\n\n"
            "📊 On the exchange: <b>{listings}</b> channels · <b>{inquiries}</b> requests"
        ),
        "mk_btn_catalog": "🔎 Catalog",
        "mk_btn_my": "📢 List channel",
        "mk_btn_inbox": "💬 Chats",
        "mk_btn_how": "ℹ️ How it works",
        "mk_btn_close": "❌ Close",
        "mk_btn_back": "◀️ Back",
        "mk_btn_channel": "💰 Ad exchange",
        "mk_how": (
            "ℹ️ <b>How the exchange works</b>\n\n"
            "1️⃣ A channel owner lists a channel: topic, price, description. Subscribers, views and engagement (ER) "
            "come from the bot's own data, not typed in by hand.\n"
            "2️⃣ An advertiser picks a channel in the catalog and writes a request.\n"
            "3️⃣ The request reaches the owner through the bot; they chat here. You share your contact "
            "yourself, only if you want to.\n\n"
            "🛡 <b>Safety</b>\n"
            "• Money does not go through the bot — the deal is between the parties. Beware of prepayment.\n"
            "• Report a suspicious listing with ⚠️ Report: after 3 reports it is hidden automatically.\n"
            "• An owner can ⛔ block an unwanted person."
        ),
        "mk_cat_pick": "🔎 <b>Catalog</b>\nPick a topic:",
        "mk_cat_all": "🌐 All",
        "mk_cat_news": "📰 News",
        "mk_cat_tech": "💻 Technology",
        "mk_cat_business": "💼 Business",
        "mk_cat_education": "🎓 Education",
        "mk_cat_entertainment": "🎬 Entertainment",
        "mk_cat_lifestyle": "🌿 Lifestyle",
        "mk_cat_sport": "⚽ Sports",
        "mk_cat_shop": "🛍 Shopping",
        "mk_cat_auto": "🚗 Auto & real estate",
        "mk_cat_other": "📌 Other",
        "mk_list_title": "🔎 <b>Catalog</b> · {cat}\nFound: <b>{total}</b> · sorted by: {sort} · {page}/{pages}",
        "mk_list_empty": (
            "No channels in this topic yet.\n"
            "List yours first — advertisers will see you before anyone else! 📢"
        ),
        "mk_sort_m": "👥 Subscribers",
        "mk_sort_p": "💲 Price",
        "mk_sort_e": "📈 Engagement",
        "mk_price_negotiable": "negotiable",
        "mk_f_members": "👥 Subscribers",
        "mk_f_growth": "in 30 days",
        "mk_f_views": "👁 Average views",
        "mk_f_er": "📈 Engagement (ER)",
        "mk_f_posts": "📝 Posts in 30 days",
        "mk_f_price": "💲 Price per post",
        "mk_currency": "UZS",
        "mk_views_unknown": "not enough data",
        "mk_badge_growing": "📈 Growing",
        "mk_badge_engaged": "🔥 Engaged audience",
        "mk_badge_active": "⚡ Regular posts",
        "mk_verified": "✅ Channel ownership verified by the bot",
        "mk_updated": "🕒 Stats updated: {when}",
        "mk_stats_note": "ℹ️ Views and ER are calculated only from posts the bot has seen.",
        "mk_btn_contact": "✉️ Send request",
        "mk_btn_open": "🔗 Open channel",
        "mk_btn_report": "⚠️ Report",
        "mk_gone": "This listing is no longer available.",
        "mk_inq_prompt": (
            "✉️ Write a request to the owner of <b>{title}</b>:\n"
            "• what you advertise (product/service)\n• when you want it to run\n• your budget\n\n"
            "{min}–{max} characters. Cancel: /cancel"
        ),
        "mk_inq_short": "Too short. Write at least {min} characters (cancel: /cancel).",
        "mk_inq_sent": "✅ Request sent. If the owner replies, the message will arrive here (💬 Chats).",
        "mk_inq_limit": "You can't send more than {limit} new requests per day. Try again tomorrow.",
        "mk_inq_blocked": "This channel's owner does not accept requests from you.",
        "mk_inq_own": "This is your channel.",
        "mk_inq_exists": "You already have an open chat with this channel — continue in 💬 Chats.",
        "mk_inq_owner_new": (
            "📩 <b>New ad request!</b>\nChannel: <b>{title}</b>\n\n{text}\n\n"
            "<i>Reply — your message is delivered through the bot. Your profile is shared only if you allow it.</i>"
        ),
        "mk_btn_reply": "💬 Reply",
        "mk_btn_share": "👤 Share contact",
        "mk_btn_end": "✅ Close",
        "mk_btn_block": "⛔ Block",
        "mk_role_owner": "Channel owner",
        "mk_role_adv": "Advertiser",
        "mk_you": "You",
        "mk_thread": "💬 <b>{title}</b> · {role}\n\n{messages}",
        "mk_reply_prompt": "💬 Write your message (cancel: /cancel).",
        "mk_msg_in": "💬 <b>{title}</b> — {role}:\n\n{text}",
        "mk_msg_sent": "✅ Sent.",
        "mk_thread_closed": "This chat is closed.",
        "mk_thread_full": "The chat message limit ({limit}) is reached. Use 👤 Share contact to continue privately.",
        "mk_contact_in": "👤 {role} shared their contact: {contact}",
        "mk_contact_sent": "✅ Your contact was sent.",
        "mk_closed_notice": "ℹ️ Chat closed: {title}",
        "mk_blocked_ok": "⛔ User blocked, their chats are closed.",
        "mk_inbox_title": "💬 <b>Chats</b>\nPick an open chat:",
        "mk_inbox_empty": "No open chats yet.",
        "mk_report_ok": "⚠️ Report received. Thank you!",
        "mk_report_again": "You have already reported this listing.",
        "mk_report_own": "You can't report your own listing.",
        "mk_admin_blocked": "⚠️ Exchange: listing #{id} (@{username}) was blocked automatically after {count} reports.",
        "mk_my_title": "📢 <b>List a channel</b>\nPick your channel:",
        "mk_my_empty": "Add a channel first: 📢 My channels → Add channel.",
        "mk_st_active": "🟢",
        "mk_st_paused": "⏸",
        "mk_st_blocked": "⛔",
        "mk_st_none": "➕",
        "mk_new_intro": (
            "🚀 <b>{title}</b> — list on the exchange\n\n"
            "Requirements: the channel is public (has a username), the bot is a channel admin, and you are an admin too. "
            "Stats are taken from the bot's data automatically.\n\n"
            "1/3 — pick a topic:"
        ),
        "mk_err_private": "The channel has no username (private). Only public channels can be listed — set a username in the channel settings.",
        "mk_err_admin": "Ownership could not be verified: you must be a channel admin and the bot must be an admin too.",
        "mk_err_limit": "One account can list at most {limit} channels.",
        "mk_err_tg": "Couldn't reach Telegram. Try again shortly.",
        "mk_err_generic": "Something went wrong. Try again shortly.",
        "mk_price_prompt": (
            "2/3 — price of a single-post ad (in UZS).\n"
            "For example: <code>50000</code>, <code>50k</code>, <code>1.5 mln</code>. "
            "If negotiable: «negotiable». Cancel: /cancel"
        ),
        "mk_price_bad": "Can't read that price. For example: 50000, 50k or «negotiable» ({min}–{max} UZS).",
        "mk_desc_prompt": (
            "3/3 — a short channel description (topic, audience; up to {max} characters). "
            "Skip: «-». Cancel: /cancel"
        ),
        "mk_published": (
            "🎉 <b>Listed!</b>\nAdvertisers can now see your channel in the catalog; "
            "requests will arrive in this bot."
        ),
        "mk_manage": "📊 Views: <b>{views}</b> · ✉️ Requests: <b>{inquiries}</b>",
        "mk_btn_price": "💲 Price",
        "mk_btn_desc": "📝 Description",
        "mk_btn_cat": "🏷 Topic",
        "mk_btn_pause": "⏸ Pause",
        "mk_btn_resume": "▶️ Resume",
        "mk_btn_refresh": "🔄 Refresh",
        "mk_btn_delete": "🗑 Remove",
        "mk_btn_yes": "✅ Yes",
        "mk_btn_no": "❌ No",
        "mk_confirm_delete": "Remove the listing from the exchange? Open chats will be deleted too.",
        "mk_saved": "✅ Saved.",
        "mk_paused": "⏸ Listing paused — hidden from the catalog.",
        "mk_resumed": "▶️ Listing is back in the catalog.",
        "mk_deleted": "🗑 Listing removed.",
        "mk_listing_blocked": "⛔ This listing was blocked because of reports. Contact support for a review.",
        "mk_refreshed": "🔄 Stats refreshed.",
        "mk_cancelled": "Cancelled.",
    },
}

AD_MARKET_KEYS = tuple(AD_MARKET_I18N["uz"])


def market_t(key: str, lang: str = "uz", **kwargs) -> str:
    """Kalitni til bo'yicha qaytaradi (topilmasa — ``uz``, keyin asosiy lug'at; ``KeyError`` ko'tarilmaydi)."""
    code = normalize_lang(lang)
    table = AD_MARKET_I18N.get(code) or AD_MARKET_I18N["uz"]
    text = table.get(key)
    if text is None:
        text = AD_MARKET_I18N["uz"].get(key)
    if text is None:
        return safe_t(key, code, **kwargs)
    try:
        return text.format(**kwargs) if kwargs else text
    except (KeyError, IndexError, ValueError):
        return text


def ad_market_parity_report(langs=("uz", "ru", "en")) -> dict:
    """UZ ↔ RU ↔ EN kalit va format-argument pariteti (boshqa ``*_parity_report`` lar bilan bir xil struktura)."""
    from locales.translations import format_args

    base = AD_MARKET_I18N["uz"]
    base_keys = set(base)
    missing, extra, fmt_mismatch, empty = {}, {}, {}, []
    for lang in langs:
        table = AD_MARKET_I18N.get(lang) or {}
        if lang != "uz":
            missing[lang] = sorted(base_keys - set(table))
            extra[lang] = sorted(set(table) - base_keys)
            for key in base_keys & set(table):
                if format_args(base[key]) != format_args(table[key]):
                    fmt_mismatch.setdefault(key, {"uz": format_args(base[key]), lang: format_args(table[key])})
        empty.extend(f"{lang}:{k}" for k, v in table.items() if not str(v).strip())
    in_sync = (not any(missing.values()) and not any(extra.values()) and not fmt_mismatch and not empty)
    return {"keys": len(base_keys), "missing": missing, "extra": extra, "format_mismatch": fmt_mismatch,
            "empty": empty, "in_sync": in_sync}
