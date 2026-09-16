"""🧩 KONTENT YARATISH (submenu) — i18n lug'ati (UZ / RU / EN, 100% paritet).

PostAssist V2 · 1-2 mikro qadamlar: asosiy menyudagi «✨ Kontent yaratish»
tugmasi endi 5 ta yaratish yo'lini ochuvchi ICHKI MENYUni chizadi:

  * tugma yorliqlari (``cm_btn_*``) — Magic Post / Matn → Post / Rasm → Post /
    Ovoz → Post / AI Yordamchi / ◀️ Orqaga;
  * submenu yo'riqnomasi (``cm_menu_intro``) — har bir yo'l nima qilishi
    qisqacha tushuntiriladi (shu yerda «mahsulot rasmini yuboring» va
    «ovozli xabar (1 daqiqa ichida)» talablari ham beriladi);
  * ◀️ Orqaga tugmasi javobi (``cm_back_done``);
  * ACTION-FIRST taklif (``cm_offer_*``) — foydalanuvchi menyu tashqarisida
    xom matn yozib yuborganda «✨ Magic Post» oqimiga taklif qiladi.

Nega alohida modul?
  ``translations/magic_post.py``, ``voice_post.py`` va ``post_score.py`` bilan
  bir xil sabab: asosiy repo lug'ati (``locales/translations.py`` +
  ``locales/en_overlay.py``) qat'iy audit-testlar bilan qo'riqlanadi. Yangi
  bo'lim matnlari o'z modulida yashaydi va ``content_menu_parity_report()``
  bilan XUDDI SHU darajadagi UZ↔RU↔EN paritet kafolatini beradi — asosiy
  lug'atga tegilmasdan (regressiya xavfisiz).

Eslatma: «✨ Magic Post» va «📸 Rasm → Post» yorliqlari o'z killer
modullarining yagona manbasidan (_magic_post_label / BTN_IMAGE_POST_*) olinadi
— bu yerda faqat QAYTA ISHLATILADI, dublikat tarjima yaratilmaydi.

Foydalanish:
    from translations import content_menu_t
    text = content_menu_t("cm_menu_intro", "ru")
"""

from locales.translations import normalize_lang, safe_t

# ============================================================
# 🌍 LUG'AT — uchala til (uz / ru / en) BIR XIL kalitlar to'plami
# ============================================================

CONTENT_MENU_I18N = {
    # ------------------------------------------------------------
    # 🇺🇿 O'ZBEK TILI
    # ------------------------------------------------------------
    "uz": {
        # --- Submenu tugma yorliqlari (reply klaviatura) ---
        "ai_chat": '💬 AI Chat',
        "ai_audit": '🔍 Post auditi',
        "ai_improve": '✏️ Postni yaxshilash',
        "ai_ideas": "💡 Kontent g'oyalari",
        "ai_plan": '🧠 Kontent reja',
        "ai_analysis": '📊 Kanal tahlili',
        "cm_btn_magic": "✨ Magic Post",
        "cm_btn_text": "📝 Matn → Post",
        # 📸 Rasm → Post — yorliq bu yerda ham yashaydi (Image → Post oqimi
        # bilan BITTA manba): klaviatura, routing va submenu bir joydan
        # olinadi va keyingi qo'shimcha (eski) yorliqlar bilan birga taniladi.
        "cm_btn_image": "📸 Rasm → Post",
        "cm_btn_voice": "🎙 Ovoz → Post",
        "cm_btn_ai": "🤖 AI Yordamchi",
        "cm_btn_back": "◀️ Orqaga",
        # --- Submenu yo'riqnomasi ---
        "cm_menu_intro": (
            "🧩 <b>Kontent yaratish</b> — qaysi yo'ldan boshlaymiz?\n\n"
            "✨ <b>Magic Post</b> — g'oyani matn bilan yozing yoki ovozingizni "
            "yuboring, AI 5 uslubda professional post tayyorlaydi.\n"
            "📝 <b>Matn → Post</b> — tayyor matningizni to'g'ridan-to'g'ri "
            "kanalga chiqarish uchun.\n"
            "📸 <b>Rasm → Post</b> — iltimos, mahsulot rasmini yuboring: AI "
            "uni ko'rib chiqib, post yozadi.\n"
            "🎙 <b>Ovoz → Post</b> — iltimos, g'oyangizni ovozli xabar "
            "(1 daqiqa ichida) qilib yuboring.\n"
            "🤖 <b>AI Yordamchi</b> — matn yozish, qayta yozish, tarjima va "
            "g'oyalar uchun.\n\n"
            "<i>Yoki darhol rasm, ovoz yoki matn yuboring — oqim o'zi tanlaydi.</i>"
        ),
        # --- 🤖 AI Yordamchi (AI Studio bo'limi) yo'riqnomasi ---
        "cm_ai_hint": (
            "💬 Kerakli tugmani bosing yoki topiriqni erkin yozib yuboring: "
            "matn yozish, qayta yozish, tarjima va g'oya — barchasi bitta "
            "joyda."
        ),
        # --- ◀️ Orqaga ---
        "cm_back_done": "🧩 <b>Asosiy menyu</b> — kerakli bo'limni tanlang.",
        # --- ACTION-FIRST: xom matn → Magic Post taklifi ---
        "cm_offer_text": (
            "📝 <b>Matn yubordingiz.</b>\n\n"
            "Buni AI bir daqiqada professional postga aylantirsinmi? "
            "✨ — faqat uslubni tanlab qo'yasiz.\n\n"
            "<i>Masofadan: «📝 Matn → Post» — tayyor matnni o'zgarishsiz "
            "eshlaydi, «🎙 Ovoz → Post» — ovozni matnga o'giradi.</i>"
        ),
        "cm_offer_magic": "✨ Magic Post bilan tayyorlash",
        "cm_offer_menu": "🔙 Asosiy menyu",
    },
    # ------------------------------------------------------------
    # 🇷🇺 RUS TILI
    # ------------------------------------------------------------
    "ru": {
        "ai_chat": '💬 AI Чат',
        "ai_audit": '🔍 Аудит поста',
        "ai_improve": '✏️ Улучшить пост',
        "ai_ideas": '💡 Идеи контента',
        "ai_plan": '🧠 Контент-план',
        "ai_analysis": '📊 Анализ канала',
        "cm_btn_magic": "✨ Magic Post",
        "cm_btn_text": "📝 Текст → Пост",
        "cm_btn_image": "📸 Фото → Пост",
        "cm_btn_voice": "🎙 Голос → Пост",
        "cm_btn_ai": "🤖 AI-помощник",
        "cm_btn_back": "◀️ Назад",
        "cm_menu_intro": (
            "🧩 <b>Создание контента</b> — с какого способа начнём?\n\n"
            "✨ <b>Magic Post</b> — опишите идею текстом или голосом, AI "
            "подготовит профессиональный пост в 5 стилях.\n"
            "📝 <b>Текст → Пост</b> — чтобы опубликовать уже готовый текст.\n"
            "📸 <b>Фото → Пост</b> — пожалуйста, отправьте фото товара: AI "
            "рассмотрит его и напишет пост.\n"
            "🎙 <b>Голос → Пост</b> — отправьте голосовое сообщение с идеей "
            "(до 1 минуты).\n"
            "🤖 <b>AI-помощник</b> — написание, переписывание, перевод и идеи.\n\n"
            "<i>Или сразу отправьте фото, голос или текст — режим выберется сам.</i>"
        ),
        "cm_ai_hint": (
            "💬 Нажмите нужную кнопку или свободно напишите задачу: написание, "
            "переписывание, перевод и идеи — всё в одном месте."
        ),
        "cm_back_done": "🧩 <b>Главное меню</b> — выберите нужный раздел.",
        "cm_offer_text": (
            "📝 <b>Вы отправили текст.</b>\n\n"
            "Пусть AI превратит его в профессиональный пост за минуту? "
            "Останется только выбрать стиль.\n\n"
            "<i>Напоминание: «📝 Текст → Пост» публикует текст без изменений, "
            "«🎙 Голос → Пост» переводит голос в текст.</i>"
        ),
        "cm_offer_magic": "✨ Сделать Magic Post",
        "cm_offer_menu": "🔙 Главное меню",
    },
    # ------------------------------------------------------------
    # 🇬🇧 INGLIZ TILI
    # ------------------------------------------------------------
    "en": {
        "ai_chat": '💬 AI Chat',
        "ai_audit": '🔍 Post audit',
        "ai_improve": '✏️ Improve post',
        "ai_ideas": '💡 Content ideas',
        "ai_plan": '🧠 Content plan',
        "ai_analysis": '📊 Channel analysis',
        "cm_btn_magic": "✨ Magic Post",
        "cm_btn_text": "📝 Text → Post",
        "cm_btn_image": "📸 Image → Post",
        "cm_btn_voice": "🎙 Voice → Post",
        "cm_btn_ai": "🤖 AI Assistant",
        "cm_btn_back": "◀️ Back",
        "cm_menu_intro": (
            "🧩 <b>Create content</b> — which way do we start?\n\n"
            "✨ <b>Magic Post</b> — describe the idea in text or send a voice "
            "note, AI drafts a professional post in 5 styles.\n"
            "📝 <b>Text → Post</b> — publish your ready-made text as is.\n"
            "📸 <b>Image → Post</b> — please send the product photo: AI reads "
            "it and writes the post.\n"
            "🎙 <b>Voice → Post</b> — please send your idea as a voice message "
            "(within 1 minute).\n"
            "🤖 <b>AI Assistant</b> — writing, rewriting, translation and ideas.\n\n"
            "<i>Or just send a photo, voice note or text right now — the flow "
            "will be picked for you.</i>"
        ),
        "cm_ai_hint": (
            "💬 Press the tool you need or just write your task: writing, "
            "rewriting, translation and ideas — all in one place."
        ),
        "cm_back_done": "🧩 <b>Main menu</b> — choose the section you need.",
        "cm_offer_text": (
            "📝 <b>You sent raw text.</b>\n\n"
            "Should AI turn it into a professional post in a minute? "
            "You only pick the style.\n\n"
            "<i>Reminder: “📝 Text → Post” publishes the text unchanged, "
            "“🎙 Voice → Post” transcribes voice.</i>"
        ),
        "cm_offer_magic": "✨ Turn it into a Magic Post",
        "cm_offer_menu": "🔙 Main menu",
    },
}

#: Barcha kalitlar (paritet auditi va testlar uchun yagona ro'yxat).
CONTENT_MENU_KEYS = tuple(sorted(CONTENT_MENU_I18N["uz"].keys()))


def content_menu_t(key: str, lang: str = "uz", **kwargs) -> str:
    """Kontent yaratish bo'limi matnini qaytaradi (uz / ru / en).

    Mantiq ``magic_t`` / ``voice_t`` bilan bir xil: kalit bu modulda bo'lmasa
    asosiy repo lug'atiga (``safe_t``) tushadi — shu sababli umumiy
    ``btn_*`` kalitlari ham shu yerdan ishlaydi.
    """
    code = normalize_lang(lang)
    table = CONTENT_MENU_I18N.get(code) or {}
    text = table.get(key)
    if text is None:
        text = (CONTENT_MENU_I18N.get("uz") or {}).get(key)
    if text is None:
        return safe_t(key, code, **kwargs)
    try:
        return text.format(**kwargs) if kwargs else text
    except Exception:  # pragma: no cover - format himoyasi
        return text


def content_menu_parity_report(langs=("uz", "ru", "en")) -> dict:
    """UZ ↔ RU ↔ EN kalit va format-argument pariteti hisoboti.

    ``magic_post_parity_report`` / ``voice_post_parity_report`` bilan bir xil
    struktura qaytaradi: ``{"keys", "missing", "extra", "format_mismatch",
    "empty", "in_sync"}``.
    """
    from locales.translations import format_args

    base = CONTENT_MENU_I18N.get("uz") or {}
    base_keys = set(base)
    missing, extra, fmt_mismatch, empty = {}, {}, [], []
    for lang in langs:
        if lang == "uz":
            continue
        table = CONTENT_MENU_I18N.get(lang) or {}
        lang_keys = set(table)
        missing[lang] = sorted(base_keys - lang_keys)
        extra[lang] = sorted(lang_keys - base_keys)
        for key in base_keys & lang_keys:
            if format_args(base[key]) != format_args(table[key]):
                fmt_mismatch.setdefault(
                    key, {"uz": format_args(base[key]), lang: format_args(table[key])}
                )
    for lang in langs:
        table = CONTENT_MENU_I18N.get(lang) or {}
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
