"""✨ MAGIC POST — i18n lug'ati (UZ / RU / EN, 100% paritet).

"✨ Magic Post" killer funksiyasining BARCHA foydalanuvchiga ko'rinadigan
matnlari shu modulda saqlanadi:

  * asosiy menyu tugmasi (``btn_magic_post``);
  * yo'riqnomalar (``mp_intro``, ``mp_text_hint``, ...);
  * 5 ta uslub tugmasi va tushuntirishlari (``mp_style_*``);
  * generatsiya holati, natija ekrani va amallar tugmalari;
  * kanalga darhol yuborish / rejalashtirish / boshqa uslub oqimlari.

Nega alohida paket?
  Repo asosiy lug'ati (``locales/translations.py`` + ``locales/en_overlay.py``)
  repodagi eng katta fayl bo'lib, uning UZ↔RU↔EN pariteti bir necha qat'iy
  audit-test bilan qo'riqlanadi (``i18n_full_parity_test`` va boshqalar).
  Magic Post matnlari o'z paketida yashaydi va ``magic_post_parity_report()``
  bilan XUDDI SHU darajadagi paritet kafolatini beradi — asosiy lug'atga
  tegilmasdan (regressiya xavfisiz).

Foydalanish:
    from translations import magic_t
    text = magic_t("mp_intro", lang)          # tilga mos matn
    btn  = magic_t("mp_btn_schedule", "ru")   # «📅 Запланировать»
"""

from locales.translations import normalize_lang, safe_t

# ============================================================
# 🌍 LUG'AT — uchala til (uz / ru / en) BIR XIL kalitlar to'plami
# ============================================================

MAGIC_POST_I18N = {
    # ------------------------------------------------------------
    # 🇺🇿 O'ZBEK TILI
    # ------------------------------------------------------------
    "uz": {
        "btn_magic_post": "✨ Magic Post",
        "mp_intro": (
            "✨ <b>Magic Post</b> — g'oyadan tayyor postgacha!\n\n"
            "Post mavzusini yozing, mahsulot tavsifini qoldiring yoki shunchaki "
            "ovoz/rasm yuboring:"
        ),
        "mp_text_hint": (
            "✍️ Iltimos, post uchun <b>matn yoki g'oya</b> yuboring.\n\n"
            "Masalan: «Yangi koffemiz endi 20% chegirma bilan sotilmoqda»"
        ),
        "mp_media_hint": (
            "🎙📸 Ovoz va rasm alohida oqimlarda ishlanadi: ularni <b>Magic Post</b>dan "
            "chiqib (◀️ Orqaga) to'g'ridan-to'g'ri yuboring — bot avtomatik "
            "«🎙 Ovoz → Post» / «📸 Rasm → Post» (AI Studio Vision) oqimini ochadi.\n\n"
            "Hozir esa post mavzusini <b>matn</b> bilan yozing:"
        ),
        "mp_choose_style": "🎯 <b>Qaysi uslubda tayyorlaymiz?</b>\n\n<b>Matningiz:</b>\n",
        "mp_choose_style_foot": "\n\nUslubni tanlang 👇",
        "mp_style_sales": "🔥 Sotuv",
        "mp_style_sales_desc": "AIDA/PAS formulasi, aniq CTA va narx/chegirmaga urg'u",
        "mp_style_premium": "💎 Premium",
        "mp_style_premium_desc": "Qisqa, nafis va estetik — baland ohangdagi premium post",
        "mp_style_casual": "😊 Oddiy",
        "mp_style_casual_desc": "Do'stona, samimiy, blogerona til",
        "mp_style_ads": "📢 Reklama",
        "mp_style_ads_desc": "Diqqatni jalb qiluvchi sarlavha, taklif va havola joyi",
        "mp_style_informative": "📰 Informativ",
        "mp_style_informative_desc": "Foydali maslahat, tushunarli punktlar va ekspert xulosasi",
        "mp_generating": (
            "✨ <b>Post tayyorlanmoqda...</b>\n\n"
            "Uslub: <b>{style}</b>\n"
            "Odatda 10–30 soniya oladi ☕️"
        ),
        "mp_result_header": "✨ <b>Magic Post tayyor ({style})!</b>\n\n",
        "mp_result_foot": "\n\n<i>Post bilan nima qilamiz?</i>",
        "mp_btn_send_channel": "📢 Kanalga yuborish",
        "mp_btn_schedule": "📅 Rejalashtirish",
        "mp_btn_restyle": "🔄 Boshqa uslub",
        "mp_btn_rewrite": "✏️ Qayta yozish / Uslub",
        "mp_btn_back": "◀️ Orqaga",
        "mp_send_choose": "📢 <b>Postni qaysi kanalga yuboramiz?</b>\nKanalni tanlang 👇",
        "mp_send_all": "📣 Barcha kanallarga ({count})",
        "mp_sent_ok": (
            "🚀 <b>Post muvaffaqiyatli yuborildi!</b>\n\n"
            "📢 Kanallar: {channels}\n"
            "📊 Yuborildi: <b>{count}</b> ta"
        ),
        "mp_sent_fail": (
            "⚠️ <b>Yuborishda xatolik yuz berdi.</b>\n\n"
            "Botga kanalda «xabar yuborish» ruxsati berilganini tekshiring "
            "va qayta urinib ko'ring."
        ),
        "mp_no_channels": (
            "📢 <b>Ulangan kanal topilmadi.</b>\n\n"
            "Avval «👤 Kabinet & Sozlamalar» → «📢 Kanallar/Guruhlar» "
            "bo'limidan kanalingizni ulang, so'ng qayta urinib ko'ring."
        ),
        "mp_restyle_hint": (
            "🔄 <b>Matn saqlab qolindi</b> — qayta yozib yuborish shart emas.\n\n"
            "Yangi uslubni tanlang 👇"
        ),
        "mp_stale": (
            "⌛️ <b>Sessiya eskirgan.</b>\n\n"
            "«✨ Magic Post» tugmasini qayta bosing."
        ),
        "mp_error": (
            "😔 <b>Post tayyorlanmadi.</b>\n\n"
            "AI xizmatida vaqtinchalik xatolik. Iltimos, bir necha soniyadan "
            "so'ng qayta urinib ko'ring."
        ),
        "mp_style_unknown": "🤔 Uslub tanlanmadi — iltimos, ro'yxatdan tanlang.",
    },
    # ------------------------------------------------------------
    # 🇷🇺 RUS TILI
    # ------------------------------------------------------------
    "ru": {
        "btn_magic_post": "✨ Magic Post",
        "mp_intro": (
            "✨ <b>Magic Post</b> — от идеи до готового поста!\n\n"
            "Напишите тему поста, оставьте описание товара или просто "
            "отправьте голос/фото:"
        ),
        "mp_text_hint": (
            "✍️ Пожалуйста, отправьте <b>текст или идею</b> для поста.\n\n"
            "Например: «Наш новый кофе продаётся со скидкой 20%»"
        ),
        "mp_media_hint": (
            "🎙📸 Голос и фото обрабатываются отдельными потоками: выйдите из "
            "<b>Magic Post</b> (◀️ Назад) и отправьте их напрямую — бот сам откроет "
            "«🎙 Голос → Пост» / «📸 Фото → Пост» (AI Studio Vision).\n\n"
            "А сейчас напишите тему поста <b>текстом</b>:"
        ),
        "mp_choose_style": "🎯 <b>В каком стиле подготовим?</b>\n\n<b>Ваш текст:</b>\n",
        "mp_choose_style_foot": "\n\nВыберите стиль 👇",
        "mp_style_sales": "🔥 Продажи",
        "mp_style_sales_desc": "Формула AIDA/PAS, чёткий CTA и акцент на цену/скидку",
        "mp_style_premium": "💎 Премиум",
        "mp_style_premium_desc": "Коротко, элегантно и эстетично — премиальный тон",
        "mp_style_casual": "😊 Обычный",
        "mp_style_casual_desc": "Дружелюбный, искренний, блогерский язык",
        "mp_style_ads": "📢 Реклама",
        "mp_style_ads_desc": "Цепляющий заголовок, оффер и место для ссылки",
        "mp_style_informative": "📰 Информативный",
        "mp_style_informative_desc": "Полезные советы, понятные пункты и экспертный вывод",
        "mp_generating": (
            "✨ <b>Пост готовится...</b>\n\n"
            "Стиль: <b>{style}</b>\n"
            "Обычно это занимает 10–30 секунд ☕️"
        ),
        "mp_result_header": "✨ <b>Magic Post готов ({style})!</b>\n\n",
        "mp_result_foot": "\n\n<i>Что делаем с постом?</i>",
        "mp_btn_send_channel": "📢 Отправить в канал",
        "mp_btn_schedule": "📅 Запланировать",
        "mp_btn_restyle": "🔄 Другой стиль",
        "mp_btn_rewrite": "✏️ Переписать / Стиль",
        "mp_btn_back": "◀️ Назад",
        "mp_send_choose": "📢 <b>В какой канал отправить пост?</b>\nВыберите канал 👇",
        "mp_send_all": "📣 Во все каналы ({count})",
        "mp_sent_ok": (
            "🚀 <b>Пост успешно отправлен!</b>\n\n"
            "📢 Каналы: {channels}\n"
            "📊 Отправлено: <b>{count}</b>"
        ),
        "mp_sent_fail": (
            "⚠️ <b>Не удалось отправить.</b>\n\n"
            "Проверьте, что у бота есть право «отправка сообщений» в канале, "
            "и попробуйте снова."
        ),
        "mp_no_channels": (
            "📢 <b>Подключённых каналов не найдено.</b>\n\n"
            "Сначала подключите канал в «👤 Кабинет & Настройки» → "
            "«📢 Каналы/Группы», затем попробуйте снова."
        ),
        "mp_restyle_hint": (
            "🔄 <b>Текст сохранён</b> — вводить его заново не нужно.\n\n"
            "Выберите новый стиль 👇"
        ),
        "mp_stale": (
            "⌛️ <b>Сессия устарела.</b>\n\n"
            "Нажмите кнопку «✨ Magic Post» ещё раз."
        ),
        "mp_error": (
            "😔 <b>Пост не подготовлен.</b>\n\n"
            "Временная ошибка AI-сервиса. Попробуйте ещё раз через "
            "несколько секунд."
        ),
        "mp_style_unknown": "🤔 Стиль не выбран — пожалуйста, выберите из списка.",
    },
    # ------------------------------------------------------------
    # 🇬🇧 INGLIZ TILI
    # ------------------------------------------------------------
    "en": {
        "btn_magic_post": "✨ Magic Post",
        "mp_intro": (
            "✨ <b>Magic Post</b> — from an idea to a ready post!\n\n"
            "Type a post topic, drop a product description or simply "
            "send a voice message/photo:"
        ),
        "mp_text_hint": (
            "✍️ Please send a <b>text or idea</b> for the post.\n\n"
            "Example: “Our new coffee is now on sale with 20% off”"
        ),
        "mp_media_hint": (
            "🎙📸 Voice and photos are handled by their own flows: leave "
            "<b>Magic Post</b> (◀️ Back) and send them directly — the bot opens "
            "«🎙 Voice → Post» / «📸 Image → Post» (AI Studio Vision) automatically.\n\n"
            "For now, type the post topic as <b>text</b>:"
        ),
        "mp_choose_style": "🎯 <b>Which style shall we use?</b>\n\n<b>Your text:</b>\n",
        "mp_choose_style_foot": "\n\nPick a style 👇",
        "mp_style_sales": "🔥 Sales",
        "mp_style_sales_desc": "AIDA/PAS formula, clear CTA, price/discount focus",
        "mp_style_premium": "💎 Premium",
        "mp_style_premium_desc": "Short, elegant and aesthetic — a premium tone",
        "mp_style_casual": "😊 Casual",
        "mp_style_casual_desc": "Friendly, sincere, blogger-style language",
        "mp_style_ads": "📢 Ads",
        "mp_style_ads_desc": "Catchy headline, offer and a place for your link",
        "mp_style_informative": "📰 Informative",
        "mp_style_informative_desc": "Useful tips, clear bullets and an expert conclusion",
        "mp_generating": (
            "✨ <b>Preparing your post...</b>\n\n"
            "Style: <b>{style}</b>\n"
            "It usually takes 10–30 seconds ☕️"
        ),
        "mp_result_header": "✨ <b>Magic Post is ready ({style})!</b>\n\n",
        "mp_result_foot": "\n\n<i>What shall we do with it?</i>",
        "mp_btn_send_channel": "📢 Send to channel",
        "mp_btn_schedule": "📅 Schedule",
        "mp_btn_restyle": "🔄 Other style",
        "mp_btn_rewrite": "✏️ Rewrite / Style",
        "mp_btn_back": "◀️ Back",
        "mp_send_choose": "📢 <b>Which channel should we send it to?</b>\nPick a channel 👇",
        "mp_send_all": "📣 To all channels ({count})",
        "mp_sent_ok": (
            "🚀 <b>Post sent successfully!</b>\n\n"
            "📢 Channels: {channels}\n"
            "📊 Delivered: <b>{count}</b>"
        ),
        "mp_sent_fail": (
            "⚠️ <b>Failed to send.</b>\n\n"
            "Make sure the bot has the “send messages” permission in the "
            "channel, then try again."
        ),
        "mp_no_channels": (
            "📢 <b>No connected channels found.</b>\n\n"
            "First connect a channel in «👤 Account & Settings» → "
            "«📢 Channels/Groups», then try again."
        ),
        "mp_restyle_hint": (
            "🔄 <b>Your text is saved</b> — no need to type it again.\n\n"
            "Pick a new style 👇"
        ),
        "mp_stale": (
            "⌛️ <b>Session expired.</b>\n\n"
            "Tap the «✨ Magic Post» button again."
        ),
        "mp_error": (
            "😔 <b>The post was not generated.</b>\n\n"
            "Temporary AI service error. Please try again in a few seconds."
        ),
        "mp_style_unknown": "🤔 No style selected — please pick one from the list.",
    },
}

#: Lug'at kalitlari (paritet auditida ishlatiladi).
MAGIC_POST_KEYS = tuple(sorted(MAGIC_POST_I18N["uz"].keys()))

#: Uslublar → (tugma kaliti, tavsif kaliti) — TARTIB interfeysda saqlanadi.
MAGIC_STYLE_KEYS = {
    "sales": ("mp_style_sales", "mp_style_sales_desc"),
    "premium": ("mp_style_premium", "mp_style_premium_desc"),
    "casual": ("mp_style_casual", "mp_style_casual_desc"),
    "ads": ("mp_style_ads", "mp_style_ads_desc"),
    "informative": ("mp_style_informative", "mp_style_informative_desc"),
}


def magic_t(key, lang="uz", **kwargs) -> str:
    """Magic Post lug'atidan xavfsiz matn (hech qachon istisno bermaydi).

    Fallback zanjiri:
      1. so'ralgan til (``uz`` | ``ru`` | ``en``);
      2. ``uz`` (``DEFAULT``);
      3. asosiy repo lug'ati (``locales.translations.safe_t``);
      4. kalitning o'zi.
    """
    code = normalize_lang(lang)
    table = MAGIC_POST_I18N.get(code) or {}
    text = table.get(key)
    if text is None:
        text = (MAGIC_POST_I18N.get("uz") or {}).get(key)
    if text is None:
        # Asosiy lug'atdagi umumiy kalitlar (masalan ai_rate_limit) ham ishlaydi.
        text = safe_t(key, code, **kwargs)
        return text if text and text != key else str(key)
    try:
        return text.format(**kwargs) if kwargs else text
    except Exception:  # pragma: no cover - format himoyasi
        return text


def magic_post_parity_report(langs=("uz", "ru", "en")) -> dict:
    """UZ ↔ RU ↔ EN kalit va format-argument pariteti hisoboti.

    Qaytaradi::

        {
            "keys": 24,           # noyob kalitlar soni
            "missing": {"ru": [...], "en": [...]},
            "extra":   {"ru": [...], "en": [...]},
            "format_mismatch": {...},   # {placeholder} to'plami farqli kalitlar
            "empty": [...],             # bo'sh qiymatli kalitlar
            "in_sync": True,
        }
    """
    from locales.translations import format_args

    base = MAGIC_POST_I18N.get("uz") or {}
    base_keys = set(base)
    missing, extra, fmt_mismatch, empty = {}, {}, [], []
    for lang in langs:
        if lang == "uz":
            continue
        table = MAGIC_POST_I18N.get(lang) or {}
        lang_keys = set(table)
        missing[lang] = sorted(base_keys - lang_keys)
        extra[lang] = sorted(lang_keys - base_keys)
        for key in base_keys & lang_keys:
            if format_args(base[key]) != format_args(table[key]):
                fmt_mismatch.setdefault(key, {"uz": format_args(base[key]),
                                              lang: format_args(table[key])})
    for lang in langs:
        table = MAGIC_POST_I18N.get(lang) or {}
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
