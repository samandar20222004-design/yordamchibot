"""📥 KONTENT MANBALARI — i18n lug'ati (UZ / RU / EN, 100% paritet).

PHASE D (11, 12, 13-bandlar) uchun yagona matn manbasi:

🔗 **HAVOLADAN POST (URL → POST)**
    Tarmoqdan maqola matni olinadi (SSRF himoyasi bilan) va AI Channel DNA
    asosida **4 xil format** taklif qiladi::

        [📰 Yangilik]  [⚡ Qisqa]
        [🧠 Ekspert]   [📢 Reklama]

    Format tanlangach tayyor post preview ko'rsatiladi:
    ``[📅 Rejalashtirish] [🚀 Hozir chiqarish] [🔄 Boshqa variant] [❌ Bekor]``.

📡 **RSS / ATOM OQIMI**
    Manba qo'shiladi (havola → interval), so'ngra har ``interval_minutes``
    daqiqada yangi elementlar tekshiriladi. Dublikat element QAYTA
    ishlanmaydi; har bir yangi element uchun Channel DNA asosida post
    loyihasi (draft) yaratiladi va tasdiqlash uchun ko'rsatiladi (yoki
    ``autopublish`` yoqilgan bo'lsa — reja navbatiga yuboriladi).

♻️ **CONTENT RECYCLE**
    14+ kun oldingi, yaxshi ko'rsatkichli postlar ro'yxati; AI ularni
    **yangi hook + yangi sarlavha + yangi CTA** bilan yangilaydi.
    Ko'r-ko'rona repost taqiqlanadi — foydalanuvchiga faqat yangilangan
    variant preview'i va rejalashtirish tugmalari beriladi.
"""

from __future__ import annotations

from locales.translations import normalize_lang, safe_t

# ---------------------------------------------------------------------------
# I18N LUG'ATI
# ---------------------------------------------------------------------------
SOURCES_I18N = {
    # ------------------------------------------------------------
    # 🇺🇿 O'ZBEK TILI (asos — paritet shu kalitlar bo'yicha o'lchanadi)
    # ------------------------------------------------------------
    "uz": {
        # --- Hub (kanal konteksti) ---
        "src_menu_title": (
            "📥 <b>KONTENT MANBALARI</b>\n\nKanal: <b>{channel}</b>\n\n"
            "🔗 <b>Havoladan post</b> — maqola havolasini tashlang, AI 4 xil "
            "format taklif qiladi.\n"
            "📡 <b>RSS oqim</b> — manba qo'shing, yangi materiallar o'zi "
            "qoralama bo'ladi.\n"
            "♻️ <b>Eski postni yangilash</b> — 14+ kun oldingi muvaffaqiyatli "
            "postni yangi hook va CTA bilan qayta ishlang."
        ),
        "src_btn_url": "🔗 Havoladan post",
        "src_btn_rss": "📡 RSS oqim",
        "src_btn_recycle": "♻️ Eski postni yangilash",
        "src_btn_drafts": "🗂 Qoralamalar ({count})",
        "src_btn_back": "◀️ Orqaga",
        "src_btn_cancel": "❌ Bekor qilish",
        "src_stale": "Sessiya eskirgan — manbalar bo'limini qaytadan oching.",
        "src_not_found": "⚠️ Kanal topilmadi (yoki sizga tegishli emas).",
        "src_cancel_done": "❌ Manbalar bo'limi yopildi.",
        "src_no_channels": (
            "📢 Avval kanal ulang — manbalar kanalga bog'lanadi."
        ),
        # --- URL → post ---
        "src_url_ask": (
            "🔗 <b>Maqola havolasini yuboring</b>\n\n"
            "Faqat ochiq (ommaviy) sahifalar: <code>https://...</code>\n"
            "<i>Yopiq/pullik (paywall) sahifalar chetlab o'tilmaydi.</i>"
        ),
        "src_url_checking": "🔎 Havola tekshirilmoqda — 5 MB / 10 soniya chegarasi...",
        "src_url_article": (
            "📄 <b>{title}</b>\n\n"
            "🌐 Manba: <code>{source}</code>\n"
            "📏 Matn: {chars} belgi\n"
            "🛡 Xavfsizlik: manba matni AI ga <b>ishonchsiz ma'lumot</b> "
            "sifatida uzatiladi (prompt-injection bloklangan: {signals})."
        ),
        "src_url_formats": (
            "🧩 <b>Qaysi formatda post tayyorlaymiz?</b>\n\n"
            "Kanal DNA uslubi hisobga olindi. Formatni tanlang 👇"
        ),
        "src_url_formats_ready": "🎛 <b>Formatlar</b> (kanal: {channel})",
        "src_url_ai_failed": (
            "⚠️ AI javob bera olmadi — kredit yechilmadi. Birozdan so'ng "
            "qayta urinib ko'ring."
        ),
        "src_url_local_note": (
            "<i>ℹ️ Bu variant AI'siz, manba matnidan tuzildi.</i>"
        ),
        "src_url_draft_title": "📝 <b>TAYYOR POST</b> ({label})\n\n",
        "src_url_draft_foot": (
            "\n\n👇 <b>Rejalashtirish</b> yoki <b>hozir chiqarish</b>ni "
            "tanlang."
        ),
        # --- Preview amallari (URL/RSS/Recycle uchun umumiy) ---
        "src_btn_schedule": "📅 Rejalashtirish",
        "src_btn_publish": "🚀 Hozir chiqarish",
        "src_btn_regen": "🔄 Boshqa variant",
        "src_schedule_prompt": (
            "📅 <b>Qachon chiqarilsin?</b>\n\n"
            "Vaqtni yozing: <code>19:30</code>, <code>ertaga 09:00</code> "
            "yoki <code>25.09.2026 18:00</code>."
        ),
        "src_regen_failed": "⚠️ Yangi variant yaratilmadi (AI javob bermadi).",
        "src_regen_done": "🔄 Yangi variant tayyor.",
        "src_bad_time": (
            "⚠️ Vaqtni tushunib bo'lmadi. Masalan: <code>19:30</code>, "
            "<code>ertaga 09:00</code> yoki <code>25.09.2026 18:00</code>."
        ),
        "src_publish_queued": (
            "🚀 Post navbatga qo'yildi — bir daqiqa ichida kanalga chiqadi."
        ),
        "src_scheduled_ok": "📅 Post rejalashtirildi: <b>{time}</b>",
        "src_write_failed": (
            "⚠️ Postni saqlab bo'lmadi. Keyinroq qayta urinib ko'ring."
        ),
        # --- RSS ---
        "src_rss_title": (
            "📡 <b>RSS / ATOM OQIMI</b>\n\nKanal: <b>{channel}</b>\n"
            "Manbalar: {count}/{limit}"
        ),
        "src_rss_empty": (
            "📭 Hozircha manba yo'q.\n\n"
            "[➕ Manba qo'shish] tugmasi bilan boshlang — yangi materiallar "
            "avtomatik qoralama bo'ladi."
        ),
        "src_rss_btn_add": "➕ Manba qo'shish",
        "src_rss_btn_check": "🔄 Hoziroq tekshirish",
        "src_rss_btn_toggle_on": "▶️ Yoqish",
        "src_rss_btn_toggle_off": "⏸ To'xtatish",
        "src_rss_btn_delete": "🗑 O'chirish",
        "src_rss_btn_auto_on": "🤖 Avtopublish: YOQILGAN",
        "src_rss_btn_auto_off": "🤖 Avtopublish: O'CHIQ",
        "src_rss_source_item": "{icon} {title} · har {minutes} daq.",
        "src_rss_ask_url": (
            "📡 <b>Manba havolasini yuboring</b>\n\n"
            "RSS yoki Atom oqimi manzili: <code>https://example.com/rss.xml</code>"
        ),
        "src_rss_ask_interval": (
            "⏱ <b>Tekshirish intervali?</b>\n\n"
            "Daqiqada yoki oson ko'rinishda yozing: <code>60</code>, "
            "<code>2 soat</code>, <code>30m</code>.\n"
            "Chegara: {min}–{max} daqiqa."
        ),
        "src_rss_added": (
            "✅ Manba qo'shildi: <b>{title}</b>\n⏱ Interval: {minutes} daqiqa"
        ),
        "src_rss_invalid_url": "⚠️ Havola noto'g'ri yoki qabul qilinmadi.",
        "src_rss_invalid_interval": "⚠️ Interval noto'g'ri. Masalan: <code>60</code>.",
        "src_rss_checking": "🔎 Manba tekshirilmoqda...",
        "src_rss_check_done": (
            "✅ Tekshirildi: <b>{new}</b> ta yangi element, <b>{duplicates}</b> "
            "dublikat o'tkazib yuborildi."
        ),
        "src_rss_check_empty": "📭 Yangi element yo'q (dublikatlar qayta ishlanmadi).",
        "src_rss_check_failed": "⚠️ Manba o'qilmadi: {reason}",
        "src_rss_no_channel": "⚠️ Manba kanalga bog'lanmagan.",
        "src_rss_drafts_title": (
            "🗂 <b>QORALAMALAR</b> — {count} ta tasdiqlash kutmoqda\n"
            "Kanal: <b>{channel}</b>"
        ),
        "src_rss_drafts_empty": (
            "📭 Tasdiqlash kutayotgan qoralama yo'q.\n\n"
            "Yangi material chiqqanda shu yerda paydo bo'ladi."
        ),
        "src_rss_draft_item": "📝 {title}",
        "src_rss_draft_btn_approve": "📅 Rejalashtirish",
        "src_rss_draft_btn_delete": "🗑 O'chirish",
        "src_rss_draft_deleted": "🗑 Qoralama o'chirildi.",
        "src_rss_draft_queued": "✅ Qoralama navbatga qo'yildi (post #{post_id}).",
        "src_rss_draft_notfound": "⚠️ Qoralama topilmadi.",
        "src_rss_new_draft_notice": (
            "📡 <b>Yangi qoralama tayyor!</b>\nKanal: <b>{channel}</b>\n\n"
            "📄 {title}\n\n{text}"
        ),
        "src_rss_auto_enabled": "🤖 Avtopublish yoqildi — yangi materiallar darhol navbatga tushadi.",
        "src_rss_auto_disabled": "🤖 Avtopublish o'chirildi — qoralamalar tasdiqlash kutadi.",
        "src_rss_deleted": "🗑 Manba o'chirildi.",
        "src_rss_enabled": "▶️ Manba yoqildi.",
        "src_rss_disabled": "⏸ Manba to'xtatildi.",
        "src_rss_limit": "⚠️ Manbalar limiti ({limit}) to'lgan.",
        # --- Recycle ---
        "src_rec_title": (
            "♻️ <b>ESKI POSTNI YANGILASH</b>\n\nKanal: <b>{channel}</b>\n"
            "14+ kun oldingi, yaxshi ko'rsatkichli postlar 👇\n"
            "<i>Ko'r-ko'rona repost taqiqlanadi — AI yangi hook, sarlavha va "
            "CTA yozadi.</i>"
        ),
        "src_rec_empty": (
            "📭 14+ kun oldingi, yaxshi ko'rsatkichli post topilmadi.\n\n"
            "<i>Ko'rsatkich ma'lumoti yo'q bo'lsa soxta baho berilmaydi.</i>"
        ),
        "src_rec_no_metrics": (
            "ℹ️ Kanalda ko'rish/reaksiya ma'lumoti kam — nomzodlar yoshi "
            "bo'yicha ko'rsatildi."
        ),
        "src_rec_item": "♻️ {views} ko'rish · {age} kun oldin · {preview}",
        "src_rec_generating": "♻️ Eski post yangilanmoqda...",
        "src_rec_done": (
            "♻️ <b>YANGILANGAN POST</b>\n\n{text}\n\n"
            "<i>Eski post bilan o'xshashlik: {similarity}% (chegara {threshold}% — "
            "undan yuqorisi repost hisoblanadi).</i>"
        ),
        "src_rec_blind_repost": (
            "⚠️ Yangi variant eski postga juda o'xshab qoldi — repost "
            "taqiqlanadi. Boshqa variant urinib ko'ring."
        ),
        "src_rec_failed": "⚠️ AI yangilangan postni bera olmadi. Keyinroq urinib ko'ring.",
        "src_rec_similarity": (
            "<i>♻️ Eski post bilan o'xshashlik: {similarity}% "
            "(chegara {threshold}% — undan yuqorisi repost).</i>"
        ),
        "src_rec_back": "◀️ Ro'yxatga qaytish",
    },
    # ------------------------------------------------------------
    # 🇷🇺 RUS TILI
    # ------------------------------------------------------------
    "ru": {
        "src_menu_title": (
            "📥 <b>ИСТОЧНИКИ КОНТЕНТА</b>\n\nКанал: <b>{channel}</b>\n\n"
            "🔗 <b>Пост из ссылки</b> — пришлите ссылку на статью, ИИ "
            "предложит 4 формата.\n"
            "📡 <b>RSS-поток</b> — добавьте источник, новые материалы сами "
            "станут черновиками.\n"
            "♻️ <b>Обновить старый пост</b> — удачный пост старше 14 дней "
            "перепишем с новым хуком и CTA."
        ),
        "src_btn_url": "🔗 Пост из ссылки",
        "src_btn_rss": "📡 RSS-поток",
        "src_btn_recycle": "♻️ Обновить старый пост",
        "src_btn_drafts": "🗂 Черновики ({count})",
        "src_btn_back": "◀️ Назад",
        "src_btn_cancel": "❌ Отмена",
        "src_stale": "Сессия устарела — откройте раздел источников заново.",
        "src_not_found": "⚠️ Канал не найден (или не принадлежит вам).",
        "src_cancel_done": "❌ Раздел источников закрыт.",
        "src_no_channels": (
            "📢 Сначала подключите канал — источники привязываются к каналу."
        ),
        "src_url_ask": (
            "🔗 <b>Отправьте ссылку на статью</b>\n\n"
            "Только открытые (публичные) страницы: <code>https://...</code>\n"
            "<i>Закрытые/платные (paywall) страницы не обходятся.</i>"
        ),
        "src_url_checking": "🔎 Проверяем ссылку — лимиты 5 МБ / 10 секунд...",
        "src_url_article": (
            "📄 <b>{title}</b>\n\n"
            "🌐 Источник: <code>{source}</code>\n"
            "📏 Текст: {chars} символов\n"
            "🛡 Безопасность: текст источника передаётся ИИ как "
            "<b>недоверенные данные</b> (prompt-injection заблокирован: "
            "{signals})."
        ),
        "src_url_formats": (
            "🧩 <b>В каком формате подготовить пост?</b>\n\n"
            "Стиль канала (Channel DNA) учтён. Выберите формат 👇"
        ),
        "src_url_formats_ready": "🎛 <b>Форматы</b> (канал: {channel})",
        "src_url_ai_failed": (
            "⚠️ ИИ не ответил — кредит не списан. Попробуйте чуть позже."
        ),
        "src_url_local_note": (
            "<i>ℹ️ Этот вариант собран без ИИ, из текста источника.</i>"
        ),
        "src_url_draft_title": "📝 <b>ГОТОВЫЙ ПОСТ</b> ({label})\n\n",
        "src_url_draft_foot": (
            "\n\n👇 Выберите <b>запланировать</b> или <b>опубликовать сейчас</b>."
        ),
        "src_btn_schedule": "📅 Запланировать",
        "src_btn_publish": "🚀 Опубликовать сейчас",
        "src_btn_regen": "🔄 Другой вариант",
        "src_schedule_prompt": (
            "📅 <b>Когда опубликовать?</b>\n\n"
            "Введите время: <code>19:30</code>, <code>завтра 09:00</code> или "
            "<code>25.09.2026 18:00</code>."
        ),
        "src_regen_failed": "⚠️ Новый вариант не создан (ИИ не ответил).",
        "src_regen_done": "🔄 Новый вариант готов.",
        "src_bad_time": (
            "⚠️ Не удалось понять время. Например: <code>19:30</code>, "
            "<code>ertaga 09:00</code> или <code>25.09.2026 18:00</code>."
        ),
        "src_publish_queued": (
            "🚀 Пост поставлен в очередь — выйдет в канале в течение минуты."
        ),
        "src_scheduled_ok": "📅 Пост запланирован: <b>{time}</b>",
        "src_write_failed": (
            "⚠️ Не удалось сохранить пост. Попробуйте позже."
        ),
        "src_rss_title": (
            "📡 <b>RSS / ATOM ПОТОК</b>\n\nКанал: <b>{channel}</b>\n"
            "Источники: {count}/{limit}"
        ),
        "src_rss_empty": (
            "📭 Источников пока нет.\n\n"
            "Начните с кнопки [➕ Добавить источник] — новые материалы "
            "автоматически станут черновиками."
        ),
        "src_rss_btn_add": "➕ Добавить источник",
        "src_rss_btn_check": "🔄 Проверить сейчас",
        "src_rss_btn_toggle_on": "▶️ Включить",
        "src_rss_btn_toggle_off": "⏸ Остановить",
        "src_rss_btn_delete": "🗑 Удалить",
        "src_rss_btn_auto_on": "🤖 Автопубликация: ВКЛ",
        "src_rss_btn_auto_off": "🤖 Автопубликация: ВЫКЛ",
        "src_rss_source_item": "{icon} {title} · каждые {minutes} мин.",
        "src_rss_ask_url": (
            "📡 <b>Отправьте ссылку источника</b>\n\n"
            "Адрес RSS или Atom потока: "
            "<code>https://example.com/rss.xml</code>"
        ),
        "src_rss_ask_interval": (
            "⏱ <b>Интервал проверки?</b>\n\n"
            "Введите в минутах или словами: <code>60</code>, "
            "<code>2 часа</code>, <code>30m</code>.\n"
            "Пределы: {min}–{max} минут."
        ),
        "src_rss_added": (
            "✅ Источник добавлен: <b>{title}</b>\n⏱ Интервал: {minutes} минут"
        ),
        "src_rss_invalid_url": "⚠️ Ссылка некорректна или отклонена.",
        "src_rss_invalid_interval": "⚠️ Интервал некорректен. Например: <code>60</code>.",
        "src_rss_checking": "🔎 Проверяем источник...",
        "src_rss_check_done": (
            "✅ Проверено: <b>{new}</b> новых элементов, <b>{duplicates}</b> "
            "дубликатов пропущено."
        ),
        "src_rss_check_empty": "📭 Новых элементов нет (дубликаты не обрабатывались).",
        "src_rss_check_failed": "⚠️ Источник не прочитан: {reason}",
        "src_rss_no_channel": "⚠️ Источник не привязан к каналу.",
        "src_rss_drafts_title": (
            "🗂 <b>ЧЕРНОВИКИ</b> — {count} ждут подтверждения\n"
            "Канал: <b>{channel}</b>"
        ),
        "src_rss_drafts_empty": (
            "📭 Черновиков на подтверждении нет.\n\n"
            "Они появятся здесь при выходе новых материалов."
        ),
        "src_rss_draft_item": "📝 {title}",
        "src_rss_draft_btn_approve": "📅 Запланировать",
        "src_rss_draft_btn_delete": "🗑 Удалить",
        "src_rss_draft_deleted": "🗑 Черновик удалён.",
        "src_rss_draft_queued": "✅ Черновик поставлен в очередь (пост #{post_id}).",
        "src_rss_draft_notfound": "⚠️ Черновик не найден.",
        "src_rss_new_draft_notice": (
            "📡 <b>Готов новый черновик!</b>\nКанал: <b>{channel}</b>\n\n"
            "📄 {title}\n\n{text}"
        ),
        "src_rss_auto_enabled": "🤖 Автопубликация включена — новые материалы сразу идут в очередь.",
        "src_rss_auto_disabled": "🤖 Автопубликация выключена — черновики ждут подтверждения.",
        "src_rss_deleted": "🗑 Источник удалён.",
        "src_rss_enabled": "▶️ Источник включён.",
        "src_rss_disabled": "⏸ Источник остановлен.",
        "src_rss_limit": "⚠️ Достигнут лимит источников ({limit}).",
        "src_rec_title": (
            "♻️ <b>ОБНОВИТЬ СТАРЫЙ ПОСТ</b>\n\nКанал: <b>{channel}</b>\n"
            "Посты старше 14 дней с хорошими показателями 👇\n"
            "<i>Слепой репост запрещён — ИИ напишет новый хук, заголовок и CTA.</i>"
        ),
        "src_rec_empty": (
            "📭 Не найдено постов старше 14 дней с хорошими показателями.\n\n"
            "<i>Если метрик нет, оценки не выдумываются.</i>"
        ),
        "src_rec_no_metrics": (
            "ℹ️ В канале мало данных о просмотрах/реакциях — кандидаты "
            "показаны по возрасту."
        ),
        "src_rec_item": "♻️ {views} просмотров · {age} дн. назад · {preview}",
        "src_rec_generating": "♻️ Обновляем старый пост...",
        "src_rec_done": (
            "♻️ <b>ОБНОВЛЁННЫЙ ПОСТ</b>\n\n{text}\n\n"
            "<i>Схожесть со старым постом: {similarity}% (порог {threshold}% — "
            "выше считается репостом).</i>"
        ),
        "src_rec_blind_repost": (
            "⚠️ Новый вариант слишком похож на старый — репост запрещён. "
            "Попробуйте другой вариант."
        ),
        "src_rec_failed": "⚠️ ИИ не смог обновить пост. Попробуйте позже.",
        "src_rec_similarity": (
            "<i>♻️ Сходство со старым постом: {similarity}% "
            "(порог {threshold}% — выше считается репостом).</i>"
        ),
        "src_rec_back": "◀️ К списку",
    },
    # ------------------------------------------------------------
    # 🇬🇧 INGLIZ TILI
    # ------------------------------------------------------------
    "en": {
        "src_menu_title": (
            "📥 <b>CONTENT SOURCES</b>\n\nChannel: <b>{channel}</b>\n\n"
            "🔗 <b>Post from link</b> — send an article link, the AI offers 4 "
            "formats.\n"
            "📡 <b>RSS feed</b> — add a source; new items become drafts "
            "automatically.\n"
            "♻️ <b>Refresh an old post</b> — turn a 14+ day old winner into a "
            "post with a new hook and CTA."
        ),
        "src_btn_url": "🔗 Post from link",
        "src_btn_rss": "📡 RSS feed",
        "src_btn_recycle": "♻️ Refresh an old post",
        "src_btn_drafts": "🗂 Drafts ({count})",
        "src_btn_back": "◀️ Back",
        "src_btn_cancel": "❌ Cancel",
        "src_stale": "Session expired — reopen the sources section.",
        "src_not_found": "⚠️ Channel not found (or not yours).",
        "src_cancel_done": "❌ Sources section closed.",
        "src_no_channels": (
            "📢 Connect a channel first — sources are bound to a channel."
        ),
        "src_url_ask": (
            "🔗 <b>Send the article link</b>\n\n"
            "Only open (public) pages: <code>https://...</code>\n"
            "<i>Closed/paywalled pages are not bypassed.</i>"
        ),
        "src_url_checking": "🔎 Checking the link — 5 MB / 10 second limits...",
        "src_url_article": (
            "📄 <b>{title}</b>\n\n"
            "🌐 Source: <code>{source}</code>\n"
            "📏 Text: {chars} characters\n"
            "🛡 Safety: the source text is passed to the AI as "
            "<b>untrusted data</b> (prompt injection blocked: {signals})."
        ),
        "src_url_formats": (
            "🧩 <b>Which format should I prepare?</b>\n\n"
            "The channel DNA style was taken into account. Pick a format 👇"
        ),
        "src_url_formats_ready": "🎛 <b>Formats</b> (channel: {channel})",
        "src_url_ai_failed": (
            "⚠️ The AI did not respond — no credit was spent. Try again "
            "shortly."
        ),
        "src_url_local_note": (
            "<i>ℹ️ This variant was built without AI, from the source text.</i>"
        ),
        "src_url_draft_title": "📝 <b>READY POST</b> ({label})\n\n",
        "src_url_draft_foot": (
            "\n\n👇 Choose <b>schedule</b> or <b>publish now</b>."
        ),
        "src_btn_schedule": "📅 Schedule",
        "src_btn_publish": "🚀 Publish now",
        "src_btn_regen": "🔄 Another variant",
        "src_schedule_prompt": (
            "📅 <b>When should it go out?</b>\n\n"
            "Enter a time: <code>19:30</code>, <code>tomorrow 09:00</code> or "
            "<code>25.09.2026 18:00</code>."
        ),
        "src_regen_failed": "⚠️ A new variant was not created (no AI reply).",
        "src_regen_done": "🔄 New variant is ready.",
        "src_bad_time": (
            "⚠️ Could not read the time. For example: <code>19:30</code>, "
            "<code>ertaga 09:00</code> or <code>25.09.2026 18:00</code>."
        ),
        "src_publish_queued": (
            "🚀 The post is queued — it will be published within a minute."
        ),
        "src_scheduled_ok": "📅 The post is scheduled for <b>{time}</b>",
        "src_write_failed": (
            "⚠️ Could not save the post. Please try again later."
        ),
        "src_rss_title": (
            "📡 <b>RSS / ATOM FEED</b>\n\nChannel: <b>{channel}</b>\n"
            "Sources: {count}/{limit}"
        ),
        "src_rss_empty": (
            "📭 No sources yet.\n\n"
            "Start with [➕ Add source] — new items become drafts automatically."
        ),
        "src_rss_btn_add": "➕ Add source",
        "src_rss_btn_check": "🔄 Check now",
        "src_rss_btn_toggle_on": "▶️ Enable",
        "src_rss_btn_toggle_off": "⏸ Pause",
        "src_rss_btn_delete": "🗑 Delete",
        "src_rss_btn_auto_on": "🤖 Autopublish: ON",
        "src_rss_btn_auto_off": "🤖 Autopublish: OFF",
        "src_rss_source_item": "{icon} {title} · every {minutes} min",
        "src_rss_ask_url": (
            "📡 <b>Send the source link</b>\n\n"
            "RSS or Atom feed address: <code>https://example.com/rss.xml</code>"
        ),
        "src_rss_ask_interval": (
            "⏱ <b>Check interval?</b>\n\n"
            "Enter minutes or a friendly form: <code>60</code>, "
            "<code>2 hours</code>, <code>30m</code>.\n"
            "Limits: {min}–{max} minutes."
        ),
        "src_rss_added": (
            "✅ Source added: <b>{title}</b>\n⏱ Interval: {minutes} minutes"
        ),
        "src_rss_invalid_url": "⚠️ The link is invalid or was rejected.",
        "src_rss_invalid_interval": "⚠️ Invalid interval. For example: <code>60</code>.",
        "src_rss_checking": "🔎 Checking the source...",
        "src_rss_check_done": (
            "✅ Checked: <b>{new}</b> new items, <b>{duplicates}</b> duplicates "
            "skipped."
        ),
        "src_rss_check_empty": "📭 No new items (duplicates were not reprocessed).",
        "src_rss_check_failed": "⚠️ Source could not be read: {reason}",
        "src_rss_no_channel": "⚠️ The source is not bound to a channel.",
        "src_rss_drafts_title": (
            "🗂 <b>DRAFTS</b> — {count} awaiting approval\n"
            "Channel: <b>{channel}</b>"
        ),
        "src_rss_drafts_empty": (
            "📭 No drafts awaiting approval.\n\n"
            "They will appear here when new items arrive."
        ),
        "src_rss_draft_item": "📝 {title}",
        "src_rss_draft_btn_approve": "📅 Schedule",
        "src_rss_draft_btn_delete": "🗑 Delete",
        "src_rss_draft_deleted": "🗑 Draft deleted.",
        "src_rss_draft_queued": "✅ Draft queued (post #{post_id}).",
        "src_rss_draft_notfound": "⚠️ Draft not found.",
        "src_rss_new_draft_notice": (
            "📡 <b>A new draft is ready!</b>\nChannel: <b>{channel}</b>\n\n"
            "📄 {title}\n\n{text}"
        ),
        "src_rss_auto_enabled": "🤖 Autopublish enabled — new items go straight to the queue.",
        "src_rss_auto_disabled": "🤖 Autopublish disabled — drafts wait for approval.",
        "src_rss_deleted": "🗑 Source deleted.",
        "src_rss_enabled": "▶️ Source enabled.",
        "src_rss_disabled": "⏸ Source paused.",
        "src_rss_limit": "⚠️ Source limit reached ({limit}).",
        "src_rec_title": (
            "♻️ <b>REFRESH AN OLD POST</b>\n\nChannel: <b>{channel}</b>\n"
            "Posts older than 14 days with good performance 👇\n"
            "<i>Blind reposting is forbidden — the AI writes a new hook, title "
            "and CTA.</i>"
        ),
        "src_rec_empty": (
            "📭 No posts older than 14 days with good performance were found.\n\n"
            "<i>When metrics are missing, no fake scores are produced.</i>"
        ),
        "src_rec_no_metrics": (
            "ℹ️ The channel has little views/reactions data — candidates are "
            "listed by age."
        ),
        "src_rec_item": "♻️ {views} views · {age} days ago · {preview}",
        "src_rec_generating": "♻️ Refreshing the old post...",
        "src_rec_done": (
            "♻️ <b>REFRESHED POST</b>\n\n{text}\n\n"
            "<i>Similarity to the old post: {similarity}% (threshold "
            "{threshold}% — above that counts as a repost).</i>"
        ),
        "src_rec_blind_repost": (
            "⚠️ The new variant is too similar to the old post — reposting is "
            "forbidden. Try another variant."
        ),
        "src_rec_failed": "⚠️ The AI could not refresh the post. Try later.",
        "src_rec_similarity": (
            "<i>♻️ Similarity to the old post: {similarity}% "
            "(threshold {threshold}% — above that is a repost).</i>"
        ),
        "src_rec_back": "◀️ Back to the list",
    },
}

SOURCES_KEYS = tuple(sorted(SOURCES_I18N["uz"]))

#: Manbalar bo'limining tugma kalitlari (UI paritet tekshiruvlari uchun).
SOURCES_BUTTON_KEYS = (
    "src_btn_url",
    "src_btn_rss",
    "src_btn_recycle",
    "src_btn_drafts",
    "src_btn_back",
    "src_btn_cancel",
    "src_btn_schedule",
    "src_btn_publish",
    "src_btn_regen",
    "src_rss_btn_add",
    "src_rss_btn_check",
    "src_rss_btn_delete",
    "src_rss_draft_btn_approve",
    "src_rss_draft_btn_delete",
)


def sources_t(key: str, lang: str = "uz", **kwargs) -> str:
    """Tilga mos matn (noma'lum til → uz, noma'lum kalit → umumiy lug'at)."""
    code = normalize_lang(lang)
    table = SOURCES_I18N.get(code) or SOURCES_I18N["uz"]
    text = table.get(key)
    if text is None:
        text = SOURCES_I18N["uz"].get(key)
    if text is None:
        return safe_t(key, code, **kwargs)
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError):
        return text


def sources_parity_report(langs=("uz", "ru", "en")) -> dict:
    """UZ ↔ RU ↔ EN kalit va format-argument pariteti hisoboti.

    ``channels_queue_parity_report`` bilan bir xil struktura qaytaradi:
    ``{"keys", "missing", "extra", "format_mismatch", "empty", "in_sync"}``.
    """
    from locales.translations import format_args

    base = SOURCES_I18N.get("uz") or {}
    base_keys = set(base)
    missing, extra, fmt_mismatch, empty = {}, {}, {}, []
    for lang in langs:
        if lang == "uz":
            continue
        table = SOURCES_I18N.get(lang) or {}
        lang_keys = set(table)
        missing[lang] = sorted(base_keys - lang_keys)
        extra[lang] = sorted(lang_keys - base_keys)
        for key in base_keys & lang_keys:
            if format_args(base[key]) != format_args(table[key]):
                fmt_mismatch.setdefault(
                    key, {"uz": format_args(base[key]), lang: format_args(table[key])}
                )
    for lang in langs:
        table = SOURCES_I18N.get(lang) or {}
        for key, value in table.items():
            if not str(value or "").strip():
                empty.append(f"{lang}:{key}")
    in_sync = (not any(missing.values()) and not any(extra.values())
               and not fmt_mismatch and not empty)
    return {
        "keys": sorted(base_keys),
        "missing": missing,
        "extra": extra,
        "format_mismatch": fmt_mismatch,
        "empty": empty,
        "in_sync": in_sync,
    }


__all__ = [
    "SOURCES_I18N",
    "SOURCES_KEYS",
    "SOURCES_BUTTON_KEYS",
    "sources_t",
    "sources_parity_report",
]
