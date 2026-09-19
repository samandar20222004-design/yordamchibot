"""📊 POST SCORE & IMPROVER — i18n lug'ati (UZ / RU / EN, 100% paritet).

Killer Feature #4 («📊 Post Score & Improver») ning BARCHA foydalanuvchiga
ko'rinadigan matnlari shu modulda saqlanadi:

  * asosiy menyu tugmasi (``ps_btn_menu``) va natija ekranidagi
    «📊 Baholash» tugmasi (``ps_btn_eval``);
  * 6 ta mezon nomi — Sarlavha / O'qilishi / CTA / Qiziqarlilik /
    Sotuv kuchi / Struktura (``ps_label_*``);
  * ball natijasi ekrani, baho darajalari (``ps_band_*``) va tavsiyalar;
  * «✨ 95/100 ga yaxshilash» / kanalga yuborish / rejalashtirish oqimlari;
  * bo'sh yoki yaroqsiz matn uchun xavfsiz ogohlantirishlar.

Nega alohida paket? Magic Post (``translations/magic_post.py``) va Voice
(``translations/voice_post.py``) bilan bir xil sabab: repo asosiy lug'ati
(``locales/translations.py``) qat'iy audit-testlar bilan qo'riqlanadi, yangi
feature esa o'z paketida XUDDI SHU darajadagi paritet kafolatini oladi
(``post_score_parity_report()``) — asosiy lug'atga tegilmasdan.

Foydalanish:
    from translations import post_score_t
    post_score_t("ps_btn_improve", "uz")      # «✨ 95/100 ga yaxshilash»
    post_score_t("ps_band_good", "ru")        # «👍 Хорошо»
"""

from locales.translations import normalize_lang, safe_t

# ============================================================
# 🌍 LUG'AT — uchala til (uz / ru / en) BIR XIL kalitlar to'plami
# ============================================================

POST_SCORE_I18N = {
    # ------------------------------------------------------------
    # 🇺🇿 O'ZBEK TILI
    # ------------------------------------------------------------
    "uz": {
        "ps_btn_menu": "📊 Post Score",
        "ps_btn_eval": "📊 Baholash",
        "ps_btn_improve": "✨ Yaxshilash",
        "ps_btn_send": "📢 Kanalga yuborish",
        "ps_btn_schedule": "📅 Rejalashtirish",
        "ps_btn_again": "📊 Boshqa post",
        "ps_intro": (
            "📊 <b>Post Score — post kuchini o'lchang!</b>\n\n"
            "Postingizni yuboring — AI uni <b>6 mezon</b> bo'yicha 1–10 ball "
            "bilan baholaydi va 100 ballik umumiy natija hamda aniq tavsiya "
            "beradi:\n\n"
            "🎯 Sarlavha kuchi\n"
            "📖 O'qilishi va abzaslar\n"
            "📣 CTA (harakatga chaqiruv) aniqligi\n"
            "💬 Qiziqarlilik va savollar\n"
            "💰 Sotuv / taklif kuchi\n"
            "🧩 Telegram formatlash, emojilar, hashtaglar\n\n"
            "ℹ️ Baholash <b>bepul</b> va bir necha soniyada bajariladi — "
            "kredit yechilmaydi. Faqat «✨ 95/100 ga yaxshilash» bosilganda "
            "1 kredit yechiladi.\n\n"
            "✍️ Postingizni yuboring:"
        ),
        "ps_warn_empty": (
            "⚠️ <b>Bo'sh post baholanmaydi.</b>\n\n"
            "Iltimos, baholash uchun <b>matn</b> yuboring (kamida 20 belgi)."
        ),
        "ps_warn_short": (
            "⚠️ <b>Matn juda qisqa.</b>\n\n"
            "Ballar xolis bo'lishi uchun kamida <b>20 belgi</b> (1–2 jumla) "
            "yuboring. Qayta urinib ko'ring:"
        ),
        "ps_warn_media": (
            "🖼 Baholash faqat <b>matnli</b> postlar uchun ishlaydi.\n\n"
            "Rasmli postni «📸 Rasm → Post» bo'limida yaratib, natijadan "
            "keyin «📊 Baholash» tugmasini bosing. Yoki matnni yozib yuboring:"
        ),
        "ps_scoring": (
            "📊 <b>Post baholanmoqda...</b>\n\n"
            "6 mezon bo'yicha tahlil qilinmoqda ⏳"
        ),
        "ps_result_header": "📊 <b>Post Score natijasi</b>\n\n",
        "ps_criteria_header": "🎯 <b>Mezonlar bo'yicha ballar:</b>\n",
        "ps_result_foot": "\n\n<i>Keyingi qadamni tanlang 👇</i>",
        "ps_overall_line": "\n━━━━━━━━━━━━━━━\n🏁 <b>Umumiy ball: {overall}/100</b> — {band}\n",
        "ps_recommendation_label": "💡 <b>Tavsiya:</b> {text}",
        "ps_fallback_note": (
            "\n<i>ℹ️ Nuqsonli tarmoq sababli ballar tezkor lokal tahlil "
            "asosida hisoblandi.</i>"
        ),
        "ps_label_headline": "🎯 Sarlavha",
        "ps_label_readability": "📖 O'qilishi",
        "ps_label_cta": "📣 CTA",
        "ps_label_engagement": "💬 Qiziqarlilik",
        "ps_label_sales_power": "💰 Sotuv kuchi",
        "ps_label_structure": "🧩 Struktura",
        "ps_band_excellent": "🏆 Ajoyib",
        "ps_band_good": "👍 Yaxshi",
        "ps_band_average": "⚠️ O'rtacha",
        "ps_band_weak": "🚨 Kuchsiz",
        "ps_advice_headline": (
            "Post boshiga 60 belgidan oshmaydigan aniq sarlavha qo'ying — "
            "birinchi qator o'quvchini ushlab qolishi kerak."
        ),
        "ps_advice_readability": (
            "Matnni 2–4 qisqa abzasga bo'ling, har bir abzas 2–3 qatordan "
            "oshmasin — uzun blok matnni o'qishni qiyinlashtiradi."
        ),
        "ps_advice_cta": (
            "Oxiriga aniq harakatga chaqiruv qo'shing: «Buyurtma uchun "
            "yozing», «Havolaga o'ting», «Hoziroq bog'laning»."
        ),
        "ps_advice_engagement": (
            "O'quvchiga savol bering yoki fikriga murojaat qiling — savol "
            "va emojilar izohlar sonini oshiradi."
        ),
        "ps_advice_sales_power": (
            "Taklifni kuchaytiring: aniq foyda, chegirma yoki kafolat "
            "haqida yozing — «nima olaman?» degan savolga javob bering."
        ),
        "ps_advice_structure": (
            "Telegram formatlashdan foydalaning: qalin sarlavha, emojilar, "
            "ro'yxat punktlari va oxirgi qatorda 3–5 hashtag."
        ),
        "ps_improving": (
            "✨ <b>Post 95+ ballga yaxshilanmoqda...</b>\n\n"
            "AI tavsiyalar asosida eng sara variantni tayyorlaydi ⏳"
        ),
        "ps_improved_header": (
            "✨ <b>Post yaxshilandi — yangi ball: {overall}/100</b>\n\n"
        ),
        "ps_improve_error": (
            "😔 <b>Yaxshilash bajarilmadi.</b>\n\n"
            "AI xizmatida vaqtinchalik xatolik — <b>1 kredit qaytarildi</b>. "
            "Birozdan so'ng qayta urinib ko'ring."
        ),
        "ps_score_error": (
            "😔 <b>Baholash bajarilmadi.</b>\n\n"
            "Iltimos, bir necha soniyadan so'ng qayta urinib ko'ring."
        ),
        "ps_no_credit": (
            "💳 <b>Kredit yetarli emas.</b>\n\n"
            "«✨ 95/100 ga yaxshilash» uchun 1 ta AI krediti kerak. "
            "Kreditni «👤 Kabinet & Sozlamalar» bo'limida to'ldirish mumkin."
        ),
        "ps_send_choose": "📢 <b>Postni qaysi kanalga yuboramiz?</b>\nKanalni tanlang 👇",
        "ps_send_all": "📣 Barcha kanallar",
        "ps_sent_ok": (
            "🚀 <b>Post muvaffaqiyatli yuborildi!</b>\n\n"
            "📢 Kanallar: {channels}\n"
            "📊 Yuborildi: <b>{count}</b> ta"
        ),
        "ps_sent_fail": (
            "⚠️ <b>Yuborishda xatolik yuz berdi.</b>\n\n"
            "Botga kanalda «xabar yuborish» ruxsati berilganini tekshiring "
            "va qayta urinib ko'ring."
        ),
        "ps_no_channels": (
            "📢 <b>Ulangan kanal topilmadi.</b>\n\n"
            "Avval «👤 Kabinet & Sozlamalar» → «📢 Kanallar/Guruhlar» "
            "bo'limidan kanalingizni ulang."
        ),
        "ps_stale": (
            "⌛️ <b>Sessiya eskirgan.</b>\n\n"
            "«📊 Post Score» tugmasini qayta bosing."
        ),
        "ps_eval_hint": (
            "📊 <b>Post topildi — baholaymiz!</b>\n\n"
            "6 mezon bo'yicha tahlil natijasi pastda 👇"
        ),
    },
    # ------------------------------------------------------------
    # 🇷🇺 RUS TILI
    # ------------------------------------------------------------
    "ru": {
        "ps_btn_menu": "📊 Post Score",
        "ps_btn_eval": "📊 Оценить",
        "ps_btn_improve": "✨ Улучшить",
        "ps_btn_send": "📢 Отправить",
        "ps_btn_schedule": "📅 Запланировать",
        "ps_btn_again": "📊 Другой пост",
        "ps_intro": (
            "📊 <b>Post Score — измерьте силу поста!</b>\n\n"
            "Отправьте пост — ИИ оценит его по <b>6 критериям</b> от 1 до 10 "
            "баллов и покажет общий результат из 100 баллов с конкретной "
            "рекомендацией:\n\n"
            "🎯 Сила заголовка\n"
            "📖 Читаемость и абзацы\n"
            "📣 Точность призыва к действию (CTA)\n"
            "💬 Вовлечённость и вопросы\n"
            "💰 Сила продажи / оффера\n"
            "🧩 Оформление в Telegram, эмодзи, хештеги\n\n"
            "ℹ️ Оценка <b>бесплатная</b> и занимает несколько секунд — "
            "кредит не списывается. Кредит списывается только при нажатии "
            "«✨ Улучшить до 95/100».\n\n"
            "✍️ Отправьте текст поста:"
        ),
        "ps_warn_empty": (
            "⚠️ <b>Пустой пост нельзя оценить.</b>\n\n"
            "Пожалуйста, отправьте <b>текст</b> (минимум 20 символов)."
        ),
        "ps_warn_short": (
            "⚠️ <b>Текст слишком короткий.</b>\n\n"
            "Для объективной оценки отправьте минимум <b>20 символов</b> "
            "(1–2 предложения). Попробуйте снова:"
        ),
        "ps_warn_media": (
            "🖼 Оценка работает только с <b>текстовыми</b> постами.\n\n"
            "Создайте пост с фото в разделе «📸 Фото → Пост» и нажмите "
            "«📊 Оценить» в результате. Либо отправьте текст:"
        ),
        "ps_scoring": (
            "📊 <b>Пост оценивается...</b>\n\n"
            "Анализ по 6 критериям ⏳"
        ),
        "ps_result_header": "📊 <b>Результат Post Score</b>\n\n",
        "ps_criteria_header": "🎯 <b>Баллы по критериям:</b>\n",
        "ps_result_foot": "\n\n<i>Выберите следующий шаг 👇</i>",
        "ps_overall_line": "\n━━━━━━━━━━━━━━━\n🏁 <b>Общий балл: {overall}/100</b> — {band}\n",
        "ps_recommendation_label": "💡 <b>Рекомендация:</b> {text}",
        "ps_fallback_note": (
            "\n<i>ℹ️ Из-за сбоя сети баллы рассчитаны быстрым локальным "
            "анализом.</i>"
        ),
        "ps_label_headline": "🎯 Заголовок",
        "ps_label_readability": "📖 Читаемость",
        "ps_label_cta": "📣 CTA",
        "ps_label_engagement": "💬 Вовлечённость",
        "ps_label_sales_power": "💰 Сила продажи",
        "ps_label_structure": "🧩 Структура",
        "ps_band_excellent": "🏆 Отлично",
        "ps_band_good": "👍 Хорошо",
        "ps_band_average": "⚠️ Средне",
        "ps_band_weak": "🚨 Слабо",
        "ps_advice_headline": (
            "Добавьте в начало короткий заголовок до 60 символов — первая "
            "строка должна удерживать внимание."
        ),
        "ps_advice_readability": (
            "Разбейте текст на 2–4 коротких абзаца по 2–3 строки — длинные "
            "блоки читать тяжело."
        ),
        "ps_advice_cta": (
            "Добавьте в конец чёткий призыв: «Напишите для заказа», «Перейдите "
            "по ссылке», «Свяжитесь сейчас»."
        ),
        "ps_advice_engagement": (
            "Задайте читателю вопрос или обратитесь к его мнению — вопросы и "
            "эмодзи повышают число комментариев."
        ),
        "ps_advice_sales_power": (
            "Усильте оффер: конкретная выгода, скидка или гарантия — ответьте "
            "на вопрос «что я получу?»."
        ),
        "ps_advice_structure": (
            "Используйте оформление Telegram: жирный заголовок, эмодзи, "
            "пункты списка и 3–5 хештегов в конце."
        ),
        "ps_improving": (
            "✨ <b>Пост улучшается до 95+ баллов...</b>\n\n"
            "ИИ готовит лучший вариант по своим рекомендациям ⏳"
        ),
        "ps_improved_header": (
            "✨ <b>Пост улучшен — новый балл: {overall}/100</b>\n\n"
        ),
        "ps_improve_error": (
            "😔 <b>Улучшение не выполнено.</b>\n\n"
            "Временная ошибка ИИ — <b>1 кредит возвращён</b>. "
            "Попробуйте снова через минуту."
        ),
        "ps_score_error": (
            "😔 <b>Оценка не выполнена.</b>\n\n"
            "Пожалуйста, попробуйте снова через несколько секунд."
        ),
        "ps_no_credit": (
            "💳 <b>Недостаточно кредитов.</b>\n\n"
            "Для «✨ Улучшить до 95/100» нужен 1 AI-кредит. Пополнить можно в "
            "разделе «👤 Кабинет & Настройки»."
        ),
        "ps_send_choose": "📢 <b>В какой канал отправим пост?</b>\nВыберите канал 👇",
        "ps_send_all": "📣 Все каналы",
        "ps_sent_ok": (
            "🚀 <b>Пост успешно отправлен!</b>\n\n"
            "📢 Каналы: {channels}\n"
            "📊 Отправлено: <b>{count}</b>"
        ),
        "ps_sent_fail": (
            "⚠️ <b>Ошибка при отправке.</b>\n\n"
            "Проверьте, что боту разрешено «публиковать сообщения» в канале, "
            "и попробуйте снова."
        ),
        "ps_no_channels": (
            "📢 <b>Подключённые каналы не найдены.</b>\n\n"
            "Сначала подключите канал в «👤 Кабинет & Настройки» → "
            "«📢 Каналы/Группы»."
        ),
        "ps_stale": (
            "⌛️ <b>Сессия устарела.</b>\n\n"
            "Нажмите «📊 Post Score» снова."
        ),
        "ps_eval_hint": (
            "📊 <b>Пост найден — оцениваем!</b>\n\n"
            "Результат анализа по 6 критериям ниже 👇"
        ),
    },
    # ------------------------------------------------------------
    # 🇬🇧 INGLIZ TILI
    # ------------------------------------------------------------
    "en": {
        "ps_btn_menu": "📊 Post Score",
        "ps_btn_eval": "📊 Rate post",
        "ps_btn_improve": "✨ Improve",
        "ps_btn_send": "📢 Send to channel",
        "ps_btn_schedule": "📅 Schedule",
        "ps_btn_again": "📊 Rate other",
        "ps_intro": (
            "📊 <b>Post Score — measure your post's power!</b>\n\n"
            "Send your post — AI rates it on <b>6 criteria</b> from 1 to 10 "
            "and shows an overall score out of 100 plus a clear "
            "recommendation:\n\n"
            "🎯 Headline strength\n"
            "📖 Readability and paragraphs\n"
            "📣 Call-to-action (CTA) clarity\n"
            "💬 Engagement and questions\n"
            "💰 Selling power of the offer\n"
            "🧩 Telegram formatting, emojis, hashtags\n\n"
            "ℹ️ Scoring is <b>free</b> and takes a few seconds — no credits "
            "are spent. A credit is charged only when you press "
            "«✨ Improve to 95/100».\n\n"
            "✍️ Send your post text:"
        ),
        "ps_warn_empty": (
            "⚠️ <b>An empty post cannot be scored.</b>\n\n"
            "Please send <b>text</b> (at least 20 characters)."
        ),
        "ps_warn_short": (
            "⚠️ <b>The text is too short.</b>\n\n"
            "For a fair score send at least <b>20 characters</b> "
            "(1–2 sentences). Please try again:"
        ),
        "ps_warn_media": (
            "🖼 Scoring works with <b>text</b> posts only.\n\n"
            "Create a photo post in «📸 Image → Post» and press "
            "«📊 Rate post» in the result. Or simply send the text:"
        ),
        "ps_scoring": (
            "📊 <b>Scoring your post...</b>\n\n"
            "Analysing 6 criteria ⏳"
        ),
        "ps_result_header": "📊 <b>Post Score result</b>\n\n",
        "ps_criteria_header": "🎯 <b>Criteria scores:</b>\n",
        "ps_result_foot": "\n\n<i>Choose your next step 👇</i>",
        "ps_overall_line": "\n━━━━━━━━━━━━━━━\n🏁 <b>Overall score: {overall}/100</b> — {band}\n",
        "ps_recommendation_label": "💡 <b>Recommendation:</b> {text}",
        "ps_fallback_note": (
            "\n<i>ℹ️ Network issue detected — scores were calculated by a fast "
            "local analysis.</i>"
        ),
        "ps_label_headline": "🎯 Headline",
        "ps_label_readability": "📖 Readability",
        "ps_label_cta": "📣 CTA",
        "ps_label_engagement": "💬 Engagement",
        "ps_label_sales_power": "💰 Selling power",
        "ps_label_structure": "🧩 Structure",
        "ps_band_excellent": "🏆 Excellent",
        "ps_band_good": "👍 Good",
        "ps_band_average": "⚠️ Average",
        "ps_band_weak": "🚨 Weak",
        "ps_advice_headline": (
            "Start with a short headline under 60 characters — the first line "
            "must hook the reader."
        ),
        "ps_advice_readability": (
            "Split the text into 2–4 short paragraphs of 2–3 lines each — long "
            "walls of text are hard to read."
        ),
        "ps_advice_cta": (
            "End with a clear call to action: \"DM to order\", \"Tap the "
            "link\", \"Contact us now\"."
        ),
        "ps_advice_engagement": (
            "Ask the reader a question or invite their opinion — questions and "
            "emojis boost comments."
        ),
        "ps_advice_sales_power": (
            "Strengthen the offer: concrete benefit, discount or guarantee — "
            "answer \"what do I get?\"."
        ),
        "ps_advice_structure": (
            "Use Telegram formatting: a bold headline, emojis, bullet points "
            "and 3–5 hashtags on the last line."
        ),
        "ps_improving": (
            "✨ <b>Improving your post to 95+...</b>\n\n"
            "AI is crafting the best version based on its advice ⏳"
        ),
        "ps_improved_header": (
            "✨ <b>Post improved — new score: {overall}/100</b>\n\n"
        ),
        "ps_improve_error": (
            "😔 <b>Improvement failed.</b>\n\n"
            "Temporary AI error — <b>1 credit has been refunded</b>. "
            "Please try again in a minute."
        ),
        "ps_score_error": (
            "😔 <b>Scoring failed.</b>\n\n"
            "Please try again in a few seconds."
        ),
        "ps_no_credit": (
            "💳 <b>Not enough credits.</b>\n\n"
            "«✨ Improve to 95/100» costs 1 AI credit. Top up in "
            "«👤 Account & Settings»."
        ),
        "ps_send_choose": "📢 <b>Which channel should we send it to?</b>\nPick a channel 👇",
        "ps_send_all": "📣 All channels",
        "ps_sent_ok": (
            "🚀 <b>Post sent successfully!</b>\n\n"
            "📢 Channels: {channels}\n"
            "📊 Sent: <b>{count}</b>"
        ),
        "ps_sent_fail": (
            "⚠️ <b>Failed to send the post.</b>\n\n"
            "Make sure the bot is allowed to «post messages» in the channel "
            "and try again."
        ),
        "ps_no_channels": (
            "📢 <b>No connected channels found.</b>\n\n"
            "Connect a channel in «👤 Account & Settings» → "
            "«📢 Channels/Groups» first."
        ),
        "ps_stale": (
            "⌛️ <b>The session has expired.</b>\n\n"
            "Press «📊 Post Score» again."
        ),
        "ps_eval_hint": (
            "📊 <b>Post found — scoring it!</b>\n\n"
            "The 6-criteria analysis is below 👇"
        ),
    },
}

#: Mezon kalitlari (scorer'dagi ``POST_SCORE_CRITERIA`` bilan bir xil tartib).
POST_SCORE_CRITERIA_KEYS = (
    "headline",
    "readability",
    "cta",
    "engagement",
    "sales_power",
    "structure",
)

#: Har bir mezon uchun i18n yorliq kaliti.
POST_SCORE_LABEL_KEYS = {
    criterion: f"ps_label_{criterion}" for criterion in POST_SCORE_CRITERIA_KEYS
}

#: Ball darajalari (100 ballik natija uchun) — chegaralar bilan.
#: (min_overall, i18n kaliti)
POST_SCORE_BANDS = (
    (85, "ps_band_excellent"),
    (70, "ps_band_good"),
    (50, "ps_band_average"),
    (0, "ps_band_weak"),
)


def post_score_t(key, lang="uz", **kwargs) -> str:
    """Post Score lug'atidan xavfsiz matn (hech qachon istisno bermaydi).

    Fallback zanjiri: so'ralgan til → ``uz`` → asosiy repo lug'ati
    (``locales.translations.safe_t``, masalan ``ai_limit_msg``) → kalitning o'zi.
    """
    code = normalize_lang(lang)
    table = POST_SCORE_I18N.get(code) or {}
    text = table.get(key)
    if text is None:
        text = (POST_SCORE_I18N.get("uz") or {}).get(key)
    if text is None:
        text = safe_t(key, code, **kwargs)
        return text if text and text != key else str(key)
    try:
        return text.format(**kwargs) if kwargs else text
    except Exception:  # pragma: no cover - format himoyasi
        return text


def score_band_key(overall) -> str:
    """100 ballik natija uchun daraja kaliti (``ps_band_*``)."""
    try:
        value = int(round(float(overall)))
    except (TypeError, ValueError):
        value = 0
    for threshold, key in POST_SCORE_BANDS:
        if value >= threshold:
            return key
    return POST_SCORE_BANDS[-1][1]


def post_score_band(overall, lang="uz") -> str:
    """Tilga mos daraja matni (masalan «👍 Yaxshi»)."""
    return post_score_t(score_band_key(overall), lang)


def post_score_criterion_label(criterion, lang="uz") -> str:
    """Mezon nomi (tilga mos). Noma'lum mezon — kalitning o'zi emas, bo'sh."""
    key = POST_SCORE_LABEL_KEYS.get(criterion)
    return post_score_t(key, lang) if key else str(criterion or "")


def post_score_advice(criterion, lang="uz") -> str:
    """Kuchsiz mezon uchun tayyor (lokalizatsiya qilingan) tavsiya."""
    key = f"ps_advice_{criterion}" if criterion in POST_SCORE_LABEL_KEYS else "ps_advice_structure"
    return post_score_t(key, lang)


def post_score_parity_report(langs=("uz", "ru", "en")) -> dict:
    """UZ ↔ RU ↔ EN kalit va format-argument pariteti hisoboti.

    Qaytaradi::

        {
            "keys": 40,               # noyob kalitlar soni
            "missing": {"ru": [...], "en": [...]},
            "extra":   {"ru": [...], "en": [...]},
            "format_mismatch": {...},  # {placeholder} to'plami farqli kalitlar
            "empty": [...],            # bo'sh qiymatli kalitlar
            "in_sync": True,
        }
    """
    from locales.translations import format_args

    base = POST_SCORE_I18N.get("uz") or {}
    base_keys = set(base)
    missing, extra, fmt_mismatch, empty = {}, {}, {}, []
    for lang in langs:
        if lang == "uz":
            continue
        table = POST_SCORE_I18N.get(lang) or {}
        lang_keys = set(table)
        missing[lang] = sorted(base_keys - lang_keys)
        extra[lang] = sorted(lang_keys - base_keys)
        for key in base_keys & lang_keys:
            if format_args(base[key]) != format_args(table[key]):
                fmt_mismatch.setdefault(key, {
                    "uz": sorted(format_args(base[key])),
                    lang: sorted(format_args(table[key])),
                })
    for lang in langs:
        table = POST_SCORE_I18N.get(lang) or {}
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
