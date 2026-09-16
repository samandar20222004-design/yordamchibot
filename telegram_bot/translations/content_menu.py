"""🧩 KONTENT YARATISH (submenu) — i18n lug'ati (UZ / RU / EN, 100% paritet).

PostAssist V2 · 1-2 mikro qadamlar: asosiy menyudagi «✨ Kontent yaratish»
tugmasi endi 5 ta yaratish yo'lini ochuvchi ICHKI MENYUni chizadi:

  * tugma yorliqlari (``cm_btn_*``) — birlashtirilgan menyu: ✍️ Oddiy post
    (AI'siz) / ✨ AI bilan yaratish (Magic Post) / 🤖 AI Studio / ◀️ Orqaga
    (+ eski 📝 Matn → Post, 📸 Rasm → Post, 🎙 Ovoz → Post, 🤖 AI Yordamchi
    yorliqlari FAQAT routing aliasi sifatida saqlanadi);
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
        # 🆕 BIRLASHTIRILGAN MENYU: bo'lingan va chalkash tugmalar 3 ta mantiqiy
        # yo'nalishga birlashtirildi (Oddiy post / AI bilan yaratish / AI Studio).
        "cm_btn_manual": "✍️ Oddiy post (AI'siz)",
        "cm_btn_magic": "✨ AI bilan yaratish (Magic Post)",
        "cm_btn_studio": "🤖 AI Studio",
        "cm_btn_back": "◀️ Orqaga",
        # --- ESKI (menyudan olib tashlangan, FAQAT routing alias) yorliqlar ---
        # Chat tarixidagi eski klaviatura xabarlari bosilsa ham foydalanuvchi
        # to'g'ri oqimga tushadi: 📝 Matn → Post endi Oddiy post oqimiga,
        # 📸 Rasm → Post va 🎙 Ovoz → Post o'z AI oqimlariga, 🤖 AI Yordamchi
        # esa AI Studio bo'limiga olib boradi.
        "cm_btn_text": "📝 Matn → Post",
        "cm_btn_image": "📸 Rasm → Post",
        "cm_btn_voice": "🎙 Ovoz → Post",
        "cm_btn_ai": "🤖 AI Yordamchi",
        # --- Submenu yo'riqnomasi ---
        "cm_menu_intro": (
            "🧩 <b>Kontent yaratish</b> — qaysi yo'ldan boshlaymiz?\n\n"
            "✍️ <b>Oddiy post (AI'siz)</b> — tayyor matn, rasm yoki "
            "postingizni yuboring; hech qanday AI aralashuvisiz, to'g'ridan-"
            "to'g'ri kanalga chiqariladi yoki rejalashtiriladi.\n"
            "✨ <b>AI bilan yaratish (Magic Post)</b> — g'oyani yozing yoki "
            "ovozingizni yuboring, AI noldan professional post generatsiya "
            "qiladi.\n"
            "🤖 <b>AI Studio</b> — audit, tahlil va boshqa intellektual "
            "vositalar.\n\n"
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
        "cm_btn_manual": "✍️ Обычный пост (без AI)",
        "cm_btn_magic": "✨ Создать с AI (Magic Post)",
        "cm_btn_studio": "🤖 AI Studio",
        "cm_btn_back": "◀️ Назад",
        # --- СТАРЫЕ (убраны из меню, только алиасы маршрутизации) ---
        "cm_btn_text": "📝 Текст → Пост",
        "cm_btn_image": "📸 Фото → Пост",
        "cm_btn_voice": "🎙 Голос → Пост",
        "cm_btn_ai": "🤖 AI-помощник",
        "cm_menu_intro": (
            "🧩 <b>Создание контента</b> — с какого способа начнём?\n\n"
            "✍️ <b>Обычный пост (без AI)</b> — отправьте готовый текст, фото "
            "или пост; без какого-либо вмешательства AI он сразу публикуется "
            "или планируется в канале.\n"
            "✨ <b>Создать с AI (Magic Post)</b> — опишите идею или отправьте "
            "голосовое: AI с нуля сгенерирует профессиональный пост.\n"
            "🤖 <b>AI Studio</b> — аудит, анализ и другие интеллектуальные "
            "инструменты.\n\n"
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
        "cm_btn_manual": "✍️ Regular post (no AI)",
        "cm_btn_magic": "✨ Create with AI (Magic Post)",
        "cm_btn_studio": "🤖 AI Studio",
        "cm_btn_back": "◀️ Back",
        # --- LEGACY (removed from the menu, routing aliases only) ---
        "cm_btn_text": "📝 Text → Post",
        "cm_btn_image": "📸 Image → Post",
        "cm_btn_voice": "🎙 Voice → Post",
        "cm_btn_ai": "🤖 AI Assistant",
        "cm_menu_intro": (
            "🧩 <b>Create content</b> — which way do we start?\n\n"
            "✍️ <b>Regular post (no AI)</b> — send your ready text, photo or "
            "post; with zero AI involvement it is published or scheduled in "
            "your channel right away.\n"
            "✨ <b>Create with AI (Magic Post)</b> — describe the idea or send "
            "a voice note: AI generates a professional post from scratch.\n"
            "🤖 <b>AI Studio</b> — audit, analysis and other smart tools.\n\n"
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
