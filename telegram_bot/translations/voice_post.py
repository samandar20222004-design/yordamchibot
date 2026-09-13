"""🎙 VOICE → POST — i18n lug'ati (UZ / RU / EN, 100% paritet).

"🎙 VOICE → POST" killer funksiyasining BARCHA foydalanuvchiga ko'rinadigan
matnlari shu modulda saqlanadi:

  * transkripsiya holati (``vp_listening``);
  * davomiylik/hajm cheklovlari (``vp_too_long``, ``vp_too_large``);
  * «Ovozingiz matnga o'girildi» menyusi (``vp_transcribed_header``);
  * bekor qilish, generatsiya, natija va amallar tugmalari;
  * kanalga yuborish / rejalashtirish / boshqa uslub oqimlari.

Nega alohida modul?
  ``translations/magic_post.py`` bilan bir xil sabab: asosiy repo lug'ati
  (``locales/translations.py``) qat'iy audit-testlar bilan qo'riqlanadi.
  Voice Post matnlari o'z modulida yashaydi va ``voice_post_parity_report()``
  bilan XUDDI SHU darajadagi UZ↔RU↔EN paritet kafolatini beradi — asosiy
  lug'atga tegilmasdan (regressiya xavfisiz).

Eslatma: 5 ta uslub tugmasi va tavsiflari Magic Post lug'atidan
(``MAGIC_STYLE_KEYS`` + ``magic_t``) QAYTA ISHLATILADI — interfeys
ikkala killer funksiyada bir xil ko'rinadi, tarjimalar dublikatsiz.

Foydalanish:
    from translations import voice_t
    text = voice_t("vp_listening", "ru")
"""

from locales.translations import normalize_lang, safe_t

# ============================================================
# 🌍 LUG'AT — uchala til (uz / ru / en) BIR XIL kalitlar to'plami
# ============================================================

VOICE_POST_I18N = {
    # ------------------------------------------------------------
    # 🇺🇿 O'ZBEK TILI
    # ------------------------------------------------------------
    "uz": {
        "vp_listening": (
            "🎙 <b>Ovozingiz tinglanmoqda...</b>\n\n"
            "Audio matnga aylantirilmoqda — bu bir necha soniya oladi ☕️"
        ),
        "vp_too_long": (
            "⏱ <b>Audio juda uzun.</b>\n\n"
            "Iltimos, g'oyangizni qisqaroq ({mins} daqiqa ichida) "
            "tushuntirib yuboring."
        ),
        "vp_too_large": (
            "📦 <b>Audio fayl juda katta.</b>\n\n"
            "Iltimos, 20 MB gacha bo'lgan ovozli xabar yoki audio yuboring."
        ),
        "vp_transcribed_header": (
            "🎙 <b>Sizning ovozingiz matnga o'girildi:</b>\n"
            "<i>«{text}»</i>\n\n"
            "<b>Qaysi uslubda post tayyorlaymiz?</b>"
        ),
        "vp_choose_foot": "\n\nUslubni tanlang 👇",
        "vp_btn_cancel": "❌ Bekor qilish",
        "vp_cancel_done": (
            "🎙 <b>Jarayon bekor qilindi.</b>\n\n"
            "Hech qanday AI limiti yoki ball sarflanmadi. "
            "Yana ovozli xabar yuborishingiz mumkin."
        ),
        "vp_generating": (
            "✨ <b>Post tayyorlanmoqda...</b>\n\n"
            "Uslub: <b>{style}</b>\n"
            "Odatda 10–30 soniya oladi ☕️"
        ),
        "vp_result_header": "🎙 <b>Ovozingizdan tayyor post ({style})!</b>\n\n",
        "vp_result_foot": "\n\n<i>Post bilan nima qilamiz?</i>",
        "vp_btn_send_channel": "📢 Kanalga yuborish",
        "vp_btn_schedule": "📅 Rejalashtirish",
        "vp_btn_restyle": "🔄 Boshqa uslub",
        "vp_send_choose": (
            "📢 <b>Postni qaysi kanalga yuboramiz?</b>\nKanalni tanlang 👇"
        ),
        "vp_send_all": "📣 Barcha kanallarga ({count})",
        "vp_sent_ok": (
            "🚀 <b>Post muvaffaqiyatli yuborildi!</b>\n\n"
            "📢 Kanallar: {channels}\n"
            "📊 Yuborildi: <b>{count}</b> ta"
        ),
        "vp_sent_fail": (
            "⚠️ <b>Yuborishda xatolik yuz berdi.</b>\n\n"
            "Botga kanalda «xabar yuborish» ruxsati berilganini tekshiring "
            "va qayta urinib ko'ring."
        ),
        "vp_no_channels": (
            "📢 <b>Ulangan kanal topilmadi.</b>\n\n"
            "Avval «👤 Kabinet & Sozlamalar» → «📢 Kanallar/Guruhlar» "
            "bo'limidan kanalingizni ulang, so'ng qayta urinib ko'ring."
        ),
        "vp_restyle_hint": (
            "🔄 <b>Matn saqlab qolindi</b> — ovozni qayta yuborish shart emas.\n\n"
            "Yangi uslubni tanlang 👇"
        ),
        "vp_stale": (
            "⌛️ <b>Sessiya eskirgan.</b>\n\n"
            "Yangi ovozli xabar yuboring — jarayon qaytadan boshlanadi."
        ),
        "vp_error": (
            "😔 <b>Post tayyorlanmadi.</b>\n\n"
            "AI xizmatida vaqtinchalik xatolik. Ball va kunlik limit "
            "qaytarildi — qayta urinib ko'ring."
        ),
        "vp_empty_text": (
            "🤔 <b>Ovozingizni tushunib bo'lmadi.</b>\n\n"
            "Audio sifati past yoki jitillagan bo'lishi mumkin. "
            "Iltimos, sokin muhitda aniqroq qayta yuboring."
        ),
        "vp_transcribe_error": (
            "😔 <b>Transkripsiya xizmati hozir ishlamayapti.</b>\n\n"
            "Bir necha soniyadan so'ng qayta urinib ko'ring yoki g'oyangizni "
            "matn ko'rinishida «✨ Magic Post» ga yuboring. Hech qanday "
            "limit sarflanmadi."
        ),
    },
    # ------------------------------------------------------------
    # 🇷🇺 RUS TILI
    # ------------------------------------------------------------
    "ru": {
        "vp_listening": (
            "🎙 <b>Ваш голос обрабатывается...</b>\n\n"
            "Аудио преобразуется в текст — это займёт несколько секунд ☕️"
        ),
        "vp_too_long": (
            "⏱ <b>Аудио слишком длинное.</b>\n\n"
            "Пожалуйста, объясните вашу идею короче — в пределах {mins} мин."
        ),
        "vp_too_large": (
            "📦 <b>Аудиофайл слишком большой.</b>\n\n"
            "Пожалуйста, отправьте голосовое сообщение или аудио до 20 МБ."
        ),
        "vp_transcribed_header": (
            "🎙 <b>Ваш голос преобразован в текст:</b>\n"
            "<i>«{text}»</i>\n\n"
            "<b>В каком стиле подготовим пост?</b>"
        ),
        "vp_choose_foot": "\n\nВыберите стиль 👇",
        "vp_btn_cancel": "❌ Отмена",
        "vp_cancel_done": (
            "🎙 <b>Процесс отменён.</b>\n\n"
            "Ни один AI-лимит или балл не списан. "
            "Можете отправить новое голосовое сообщение."
        ),
        "vp_generating": (
            "✨ <b>Пост готовится...</b>\n\n"
            "Стиль: <b>{style}</b>\n"
            "Обычно это занимает 10–30 секунд ☕️"
        ),
        "vp_result_header": "🎙 <b>Пост из вашего голоса готов ({style})!</b>\n\n",
        "vp_result_foot": "\n\n<i>Что делаем с постом?</i>",
        "vp_btn_send_channel": "📢 Отправить в канал",
        "vp_btn_schedule": "📅 Запланировать",
        "vp_btn_restyle": "🔄 Другой стиль",
        "vp_send_choose": (
            "📢 <b>В какой канал отправить пост?</b>\nВыберите канал 👇"
        ),
        "vp_send_all": "📣 Во все каналы ({count})",
        "vp_sent_ok": (
            "🚀 <b>Пост успешно отправлен!</b>\n\n"
            "📢 Каналы: {channels}\n"
            "📊 Отправлено: <b>{count}</b>"
        ),
        "vp_sent_fail": (
            "⚠️ <b>Не удалось отправить.</b>\n\n"
            "Проверьте, что у бота есть право «отправка сообщений» в канале, "
            "и попробуйте снова."
        ),
        "vp_no_channels": (
            "📢 <b>Подключённых каналов не найдено.</b>\n\n"
            "Сначала подключите канал в «👤 Кабинет & Настройки» → "
            "«📢 Каналы/Группы», затем попробуйте снова."
        ),
        "vp_restyle_hint": (
            "🔄 <b>Текст сохранён</b — отправлять голос заново не нужно.\n\n"
            "Выберите новый стиль 👇"
        ),
        "vp_stale": (
            "⌛️ <b>Сессия устарела.</b>\n\n"
            "Отправьте новое голосовое сообщение — процесс начнётся заново."
        ),
        "vp_error": (
            "😔 <b>Пост не подготовлен.</b>\n\n"
            "Временная ошибка AI-сервиса. Балл и дневной лимит возвращены — "
            "попробуйте ещё раз."
        ),
        "vp_empty_text": (
            "🤔 <b>Не удалось разобрать ваш голос.</b>\n\n"
            "Возможно, качество аудио низкое или много шума. "
            "Пожалуйста, запишите ещё раз в тихой обстановке."
        ),
        "vp_transcribe_error": (
            "😔 <b>Сервис транскрипции сейчас недоступен.</b>\n\n"
            "Попробуйте через несколько секунд или отправьте идею текстом "
            "в «✨ Magic Post». Ни один лимит не списан."
        ),
    },
    # ------------------------------------------------------------
    # 🇬🇧 INGLIZ TILI
    # ------------------------------------------------------------
    "en": {
        "vp_listening": (
            "🎙 <b>Listening to your voice...</b>\n\n"
            "Converting the audio to text — this takes a few seconds ☕️"
        ),
        "vp_too_long": (
            "⏱ <b>The audio is too long.</b>\n\n"
            "Please explain your idea more briefly — within {mins} min."
        ),
        "vp_too_large": (
            "📦 <b>The audio file is too large.</b>\n\n"
            "Please send a voice message or audio up to 20 MB."
        ),
        "vp_transcribed_header": (
            "🎙 <b>Your voice has been transcribed:</b>\n"
            "<i>“{text}”</i>\n\n"
            "<b>Which style shall we use for the post?</b>"
        ),
        "vp_choose_foot": "\n\nPick a style 👇",
        "vp_btn_cancel": "❌ Cancel",
        "vp_cancel_done": (
            "🎙 <b>Process cancelled.</b>\n\n"
            "No AI limit or credit was spent. "
            "You can send a new voice message anytime."
        ),
        "vp_generating": (
            "✨ <b>Preparing your post...</b>\n\n"
            "Style: <b>{style}</b>\n"
            "It usually takes 10–30 seconds ☕️"
        ),
        "vp_result_header": "🎙 <b>Your voice-to-post is ready ({style})!</b>\n\n",
        "vp_result_foot": "\n\n<i>What shall we do with it?</i>",
        "vp_btn_send_channel": "📢 Send to channel",
        "vp_btn_schedule": "📅 Schedule",
        "vp_btn_restyle": "🔄 Other style",
        "vp_send_choose": (
            "📢 <b>Which channel should we send it to?</b>\nPick a channel 👇"
        ),
        "vp_send_all": "📣 To all channels ({count})",
        "vp_sent_ok": (
            "🚀 <b>Post sent successfully!</b>\n\n"
            "📢 Channels: {channels}\n"
            "📊 Delivered: <b>{count}</b>"
        ),
        "vp_sent_fail": (
            "⚠️ <b>Failed to send.</b>\n\n"
            "Make sure the bot has the “send messages” permission in the "
            "channel, then try again."
        ),
        "vp_no_channels": (
            "📢 <b>No connected channels found.</b>\n\n"
            "First connect a channel in «👤 Account & Settings» → "
            "«📢 Channels/Groups», then try again."
        ),
        "vp_restyle_hint": (
            "🔄 <b>Your text is saved</b> — no need to record the voice again.\n\n"
            "Pick a new style 👇"
        ),
        "vp_stale": (
            "⌛️ <b>Session expired.</b>\n\n"
            "Send a new voice message — the flow will start over."
        ),
        "vp_error": (
            "😔 <b>The post was not generated.</b>\n\n"
            "Temporary AI service error. Your credit and daily limit were "
            "refunded — please try again."
        ),
        "vp_empty_text": (
            "🤔 <b>We couldn't understand your voice.</b>\n\n"
            "The audio quality may be low or noisy. "
            "Please record it again in a quiet place."
        ),
        "vp_transcribe_error": (
            "😔 <b>The transcription service is unavailable right now.</b>\n\n"
            "Try again in a few seconds, or send your idea as text to "
            "«✨ Magic Post». No limit was spent."
        ),
    },
}

#: Lug'at kalitlari (paritet auditida ishlatiladi).
VOICE_POST_KEYS = tuple(sorted(VOICE_POST_I18N["uz"].keys()))


def voice_t(key, lang="uz", **kwargs) -> str:
    """Voice Post lug'atidan xavfsiz matn (hech qachon istisno bermaydi).

    Fallback zanjiri:
      1. so'ralgan til (``uz`` | ``ru`` | ``en``);
      2. ``uz`` (``DEFAULT``);
      3. asosiy repo lug'ati (``locales.translations.safe_t``);
      4. kalitning o'zi.
    """
    code = normalize_lang(lang)
    table = VOICE_POST_I18N.get(code) or {}
    text = table.get(key)
    if text is None:
        text = (VOICE_POST_I18N.get("uz") or {}).get(key)
    if text is None:
        # Asosiy lug'atdagi umumiy kalitlar (masalan ai_limit_msg) ham ishlaydi.
        text = safe_t(key, code, **kwargs)
        return text if text and text != key else str(key)
    try:
        return text.format(**kwargs) if kwargs else text
    except Exception:  # pragma: no cover - format himoyasi
        return text


def voice_post_parity_report(langs=("uz", "ru", "en")) -> dict:
    """UZ ↔ RU ↔ EN kalit va format-argument pariteti hisoboti.

    Qaytaradi (``magic_post_parity_report`` bilan bir xil struktura)::

        {"keys": 23, "missing": {...}, "extra": {...},
         "format_mismatch": {...}, "empty": [...], "in_sync": True}
    """
    from locales.translations import format_args

    base = VOICE_POST_I18N.get("uz") or {}
    base_keys = set(base)
    missing, extra, fmt_mismatch, empty = {}, {}, [], []
    for lang in langs:
        if lang == "uz":
            continue
        table = VOICE_POST_I18N.get(lang) or {}
        lang_keys = set(table)
        missing[lang] = sorted(base_keys - lang_keys)
        extra[lang] = sorted(lang_keys - base_keys)
        for key in base_keys & lang_keys:
            if format_args(base[key]) != format_args(table[key]):
                fmt_mismatch.setdefault(key, {"uz": format_args(base[key]),
                                              lang: format_args(table[key])})
    for lang in langs:
        table = VOICE_POST_I18N.get(lang) or {}
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
