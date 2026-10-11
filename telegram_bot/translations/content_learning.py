"""📚 KONTENT O'RGANISH (CONTENT LEARNING) — i18n lug'ati (UZ / RU / EN).

STEP 3 (Channel DNA 2.0 & Content Learning Integration): AI Studio va Post
auditi ekranlaridagi **lokalizatsiya qilingan tavsiyalar** matnlari shu
modulda uchala tilda saqlanadi:

  * ``cl_title`` / ``cl_analyzed`` / ``cl_observed_*`` — hisobot bloki;
  * ``cl_format_<kod>`` — kontent formati yorliqlari (qa, tutorial,
    social_proof, news, tips, poll, offer, story);
  * ``cl_reco_<kod>`` — yetishmayotgan format bo'yicha aniq tavsiya;
  * ``cl_insufficient`` / ``cl_no_channels`` — HALOL "ma'lumot yo'q"
    xabarlari (NO FABRICATION: soxta metrikalar uydirmaydi, real {n}/{min}
    sonlarini ko'rsatadi);
  * ``cl_footer`` — tavsiyalar manbai haqidagi ochiq eslatma.

Nega alohida modul? ``translations/content_menu.py`` bilan bir xil sabab:
asosiy repo lug'ati (``locales/translations.py``) qat'iy audit-testlar bilan
qo'riqlanadi — yangi bo'lim matnlari o'z modulida yashaydi va
``content_learning_parity_report()`` bilan XUDDI SHU darajadagi UZ↔RU↔EN
paritet kafolatini beradi (regressiya xavfisiz).

Foydalanish:
    from translations import content_learning_t
    content_learning_t("cl_reco_qa", "ru")
"""

from locales.translations import format_args, normalize_lang, safe_t  # noqa: F401

# ============================================================
# 🌍 LUG'AT — uchala til (uz / ru / en) BIR XIL kalitlar to'plami
# ============================================================

CONTENT_LEARNING_I18N = {
    # ------------------------------------------------------------
    # 🇺🇿 O'ZBEK TILI
    # ------------------------------------------------------------
    "uz": {
        "cl_title": "<b>📚 KONTENT O'RGANISH</b>",
        "cl_analyzed": "Tahlil qilindi: {n} ta post ({channels} ta kanal).",
        "cl_observed_header": "Kuzatilgan formatlar:",
        "cl_observed_item": "• {label}: {count} ta postda",
        "cl_observed_none": "Hozircha aniq format belgilari topilmadi.",
        "cl_missing_header": "Yetishmayotgan formatlar — tavsiyalar:",
        "cl_all_covered": "Ajoyib: asosiy formatlarning barchasi kuzatilgan — muvozanatni saqlang.",
        # --- Format yorliqlari ---
        "cl_format_qa": "❓ Savol-javob (Q&A)",
        "cl_format_tutorial": "🎓 Qo'llanma (tutorial)",
        "cl_format_social_proof": "⭐ Ijtimoiy isbot",
        "cl_format_news": "📰 Yangilik",
        "cl_format_tips": "💡 Maslahat",
        "cl_format_poll": "📊 So'rovnoma",
        "cl_format_offer": "🛒 Taklif",
        "cl_format_story": "📖 Hikoya",
        # --- Yetishmayotgan format tavsiyalari ---
        "cl_reco_qa": "❓ Savol-javob (Q&A) posti topilmadi — auditoriya savollariga javob formati ishonch va faollikni oshiradi.",
        "cl_reco_tutorial": "🎓 Qo'llanma/tutorial posti topilmadi — bosqichma-bosqich foydali yo'riqnoma ekspertlikni ko'rsatadi.",
        "cl_reco_social_proof": "⭐ Ijtimoiy isbot (mijoz fikrlari, keyslar) topilmadi — real natijalar ishonchni mustahkamlaydi.",
        "cl_reco_news": "📰 Yangilik formati kam — soha yangiliklari kanalni dolzarb saqlaydi.",
        "cl_reco_tips": "💡 Maslahat/foydali ro'yxat formati topilmadi — amaliy maslahatlar ko'proq saqlanadi.",
        "cl_reco_poll": "📊 So'rovnoma/faollik posti topilmadi — savol bering va izohlar faolligini o'lchang.",
        "cl_reco_offer": "🛒 Taklif/sotuv posti topilmadi — aniq taklif bilan sotuvga chaqiriq qo'shing.",
        "cl_reco_story": "📖 Shaxsiy hikoya formati topilmadi — hikoya orqali auditoriya bilan yaqinroq aloqa qurasiz.",
        # --- Halol "ma'lumot yo'q" xabarlari (NO FABRICATION) ---
        "cl_insufficient": (
            "Tahlil uchun yetarli ma'lumot yo'q: kamida {min} ta post kerak "
            "(hozir {n} ta). Soxta ko'rsatkichlar uydirmaymiz — postlar "
            "ko'paygach tavsiyalar paydo bo'ladi."
        ),
        "cl_no_channels": (
            "Tavsiyalar uchun avval 📢 «Kanallarim» bo'limidan kamida bitta "
            "kanalni ulang — tahlil faqat real postlaringiz asosida qilinadi."
        ),
        "cl_footer": "💡 Tavsiyalar kanalingizning real postlari tahliliga asoslanadi (soxta metrikalar yo'q).",
    },
    # ------------------------------------------------------------
    # 🇷🇺 РУССКИЙ ЯЗЫК
    # ------------------------------------------------------------
    "ru": {
        "cl_title": "<b>📚 ОБУЧЕНИЕ КОНТЕНТА</b>",
        "cl_analyzed": "Проанализировано: {n} постов ({channels} канал(ов)).",
        "cl_observed_header": "Наблюдаемые форматы:",
        "cl_observed_item": "• {label}: в {count} постах",
        "cl_observed_none": "Пока явных признаков форматов не найдено.",
        "cl_missing_header": "Отсутствующие форматы — рекомендации:",
        "cl_all_covered": "Отлично: все основные форматы присутствуют — поддерживайте баланс.",
        # --- Ярлыки форматов ---
        "cl_format_qa": "❓ Вопрос-ответ (Q&A)",
        "cl_format_tutorial": "🎓 Туториал (обучение)",
        "cl_format_social_proof": "⭐ Социальное доказательство",
        "cl_format_news": "📰 Новость",
        "cl_format_tips": "💡 Совет",
        "cl_format_poll": "📊 Опрос",
        "cl_format_offer": "🛒 Оффер",
        "cl_format_story": "📖 История",
        # --- Рекомендации по отсутствующим форматам ---
        "cl_reco_qa": "❓ Постов в формате «вопрос-ответ» (Q&A) не найдено — ответы на вопросы аудитории повышают доверие и активность.",
        "cl_reco_tutorial": "🎓 Обучающих постов (туториалов) не найдено — пошаговые инструкции подчёркивают экспертность.",
        "cl_reco_social_proof": "⭐ Социальных доказательств (отзывы, кейсы) не найдено — реальные результаты укрепляют доверие.",
        "cl_reco_news": "📰 Новостных постов мало — новости отрасли держат канал актуальным.",
        "cl_reco_tips": "💡 Постов с советами/полезными списками не найдено — практические советы чаще сохраняют.",
        "cl_reco_poll": "📊 Опросов/постов вовлечения не найдено — задайте вопрос и измерьте активность в комментариях.",
        "cl_reco_offer": "🛒 Постов с предложением/продажей не найдено — добавьте чёткий оффер с призывом к действию.",
        "cl_reco_story": "📖 Личных историй не найдено — истории сближают вас с аудиторией.",
        # --- Честные сообщения «нет данных» (NO FABRICATION) ---
        "cl_insufficient": (
            "Недостаточно данных для анализа: нужно минимум {min} постов "
            "(сейчас {n}). Мы не выдумываем показатели — рекомендации "
            "появятся, когда постов станет больше."
        ),
        "cl_no_channels": (
            "Для рекомендаций сначала подключите хотя бы один канал в разделе "
            "📢 «Мои каналы» — анализ строится только на ваших реальных постах."
        ),
        "cl_footer": "💡 Рекомендации основаны на анализе реальных постов вашего канала (без выдуманных метрик).",
    },
    # ------------------------------------------------------------
    # 🇬🇧 ENGLISH
    # ------------------------------------------------------------
    "en": {
        "cl_title": "<b>📚 CONTENT LEARNING</b>",
        "cl_analyzed": "Analyzed: {n} posts ({channels} channel(s)).",
        "cl_observed_header": "Observed formats:",
        "cl_observed_item": "• {label}: in {count} posts",
        "cl_observed_none": "No clear format signals found yet.",
        "cl_missing_header": "Missing formats — recommendations:",
        "cl_all_covered": "Great: all core formats are present — keep the balance.",
        # --- Format labels ---
        "cl_format_qa": "❓ Q&A",
        "cl_format_tutorial": "🎓 Tutorial",
        "cl_format_social_proof": "⭐ Social proof",
        "cl_format_news": "📰 News",
        "cl_format_tips": "💡 Tips",
        "cl_format_poll": "📊 Poll",
        "cl_format_offer": "🛒 Offer",
        "cl_format_story": "📖 Story",
        # --- Missing-format recommendations ---
        "cl_reco_qa": "❓ No Q&A posts found — answering audience questions builds trust and engagement.",
        "cl_reco_tutorial": "🎓 No tutorial posts found — step-by-step guides showcase your expertise.",
        "cl_reco_social_proof": "⭐ No social proof found (reviews, case studies) — real results strengthen trust.",
        "cl_reco_news": "📰 Few news posts — industry news keeps the channel relevant.",
        "cl_reco_tips": "💡 No tips/useful-list posts found — practical advice gets saved more often.",
        "cl_reco_poll": "📊 No poll/engagement posts found — ask a question and measure comment activity.",
        "cl_reco_offer": "🛒 No offer/sales posts found — add a clear offer with a call to action.",
        "cl_reco_story": "📖 No personal-story posts found — stories bring you closer to the audience.",
        # --- Honest "no data" messages (NO FABRICATION) ---
        "cl_insufficient": (
            "Not enough data for analysis: at least {min} posts are required "
            "(currently {n}). We do not invent metrics — recommendations will "
            "appear as your post history grows."
        ),
        "cl_no_channels": (
            "For recommendations, first connect at least one channel in "
            "📢 My Channels — the analysis is based only on your real posts."
        ),
        "cl_footer": "💡 Recommendations are based on analyzing your channel's real posts (no fabricated metrics).",
    },
}

#: Barcha kalitlar (yagona manba — uz jadvali).
CONTENT_LEARNING_KEYS = tuple(sorted(CONTENT_LEARNING_I18N["uz"].keys()))


def content_learning_t(key: str, lang: str = "uz", **kwargs) -> str:
    """Kontent o'rganish matnini qaytaradi (uz / ru / en).

    Mantiq ``content_menu_t`` bilan bir xil: kalit bu modulda bo'lmasa
    asosiy repo lug'atiga (``safe_t``) tushadi.
    """
    code = normalize_lang(lang)
    table = CONTENT_LEARNING_I18N.get(code) or {}
    text = table.get(key)
    if text is None:
        text = (CONTENT_LEARNING_I18N.get("uz") or {}).get(key)
    if text is None:
        return safe_t(key, code, **kwargs)
    try:
        return text.format(**kwargs) if kwargs else text
    except Exception:  # pragma: no cover - format himoyasi
        return text


def content_learning_parity_report(langs=("uz", "ru", "en")) -> dict:
    """UZ ↔ RU ↔ EN kalit va format-argument pariteti hisoboti.

    ``content_menu_parity_report`` bilan bir xil struktura:
    ``{"keys", "missing", "extra", "format_mismatch", "empty", "in_sync"}``.
    """
    base = CONTENT_LEARNING_I18N.get("uz") or {}
    base_keys = set(base)
    missing, extra, fmt_mismatch, empty = {}, {}, [], []
    for lang in langs:
        if lang == "uz":
            continue
        table = CONTENT_LEARNING_I18N.get(lang) or {}
        lang_keys = set(table)
        missing[lang] = sorted(base_keys - lang_keys)
        extra[lang] = sorted(lang_keys - base_keys)
        for key in base_keys & lang_keys:
            if format_args(base[key]) != format_args(table[key]):
                fmt_mismatch.setdefault(
                    key, {"uz": format_args(base[key]), lang: format_args(table[key])}
                )
    for lang in langs:
        table = CONTENT_LEARNING_I18N.get(lang) or {}
        for key, value in table.items():
            if not isinstance(value, str) or not value.strip():
                empty.append(f"{lang}:{key}")
    return {
        "keys": len(base_keys),
        "missing": missing,
        "extra": extra,
        "format_mismatch": fmt_mismatch,
        "empty": empty,
        "in_sync": not any(missing.values()) and not any(extra.values())
        and not fmt_mismatch and not empty,
    }
