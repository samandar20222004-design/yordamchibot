"""💬 QO'LLAB-QUVVATLASH — i18n lug'ati (UZ / RU / EN, 100% paritet).

PostAssist V2 · 4-QISM (so'nggi qism) — **BIR MARTALIK MUROJAAT** (one-time
ticket) va **ADMIN REPLY** oqimining yagona matn manbasi:

  * ``sp_prompt`` — [💬 Qo'llab-quvvatlash] bosilganda chiqadigan yo'riqnoma
    («Savol yoki muammoingizni bitta xabarda to'liq yozib qoldiring…»);
  * ``sp_btn_back`` — shu ekrandagi [◀️ Orqaga] tugmasi;
  * ``sp_confirm`` — foydalanuvchiga murojaat adminga yetib borgani haqidagi
    tasdiq («✅ Murojaatingiz adminga yetkazildi. Javob shu yerda keladi.»);
  * ``sp_admin_new`` — adminga yuboriladigan murojaat sarlavhasi
    («📩 Yangi murojaat! … 👤 Kimdan: @username (ID: <code>…</code>) …»);
  * ``sp_reply_header`` — admin javobi foydalanuvchiga yetkazilganda
    qo'shiladigan sarlavha («💬 Qo'llab-quvvatlash xizmati javobi:»);
  * ``sp_admin_delivered`` — adminga tasdiq
    («✅ Javob foydalanuvchiga yetkazildi»);
  * xato/himoya matnlari (``sp_failed``, ``sp_no_admins``, ``sp_need_text_user``,
    ``sp_need_text``, ``sp_cannot_deliver``, ``sp_cooldown``).

Nega alohida modul?
    ``translations/settings_stats.py``, ``translations/sources.py`` bilan bir
    xil sabab: asosiy repo lug'ati (``locales/translations.py`` +
    ``locales/en_overlay.py``) qat'iy audit-testlar bilan qo'riqlanadi. Yangi
    bo'lim matnlari o'z modulida yashaydi va ``support_parity_report()``
    orqali XUDDI SHU darajadagi UZ↔RU↔EN kafolatini beradi — asosiy lug'atga
    tegmasdan (regressiya xavfisiz).

Foydalanish::

    from translations import support_t
    text = support_t("sp_prompt", "ru")
    admin_text = support_t("sp_admin_new", "uz", username="@ali", user_id=1,
                           message="Salom")
"""

from locales.translations import normalize_lang, safe_t

# ============================================================
# 🌍 LUG'AT — uchala til (uz / ru / en) BIR XIL kalitlar to'plami
# ============================================================

SUPPORT_I18N = {
    # ------------------------------------------------------------
    # 🇺🇿 O'ZBEK TILI (asos — paritet shu kalitlar bo'yicha o'lchanadi)
    # ------------------------------------------------------------
    "uz": {
        # --- Foydalanuvchi ekrani ---
        # Topshiriq matni AYNAN saqlanadi (bir murojaat = bir xabar).
        "sp_prompt": (
            "✍️ Savol yoki muammoingizni bitta xabarda to'liq yozib qoldiring.\n"
            "(Adminlarimiz tez orada xabaringizni ko'rib chiqadi)."
        ),
        "sp_btn_back": "◀️ Orqaga",
        "sp_confirm": (
            "✅ Murojaatingiz adminga yetkazildi. Javob shu yerda keladi."
        ),
        "sp_need_text_user": (
            "✍️ Iltimos, savolingizni MATN ko'rinishida yozib qoldiring "
            "(rasm yuborsangiz, izoh ham qo'shing)."
        ),
        "sp_failed": (
            "⚠️ Murojaatni yuborishda xatolik yuz berdi. "
            "Iltimos, keyinroq qayta urinib ko'ring."
        ),
        "sp_no_admins": (
            "⚠️ Qo'llab-quvvatlash adminlari hozircha sozlanmagan. "
            "Iltimos, keyinroq qayta urinib ko'ring."
        ),
        "sp_cooldown": (
            "⏳ Iltimos, biroz kutib turing — oldingi murojaatingiz "
            "ko'rib chiqilmoqda."
        ),
        # --- Admin xabari ---
        "sp_admin_new": (
            "📩 Yangi murojaat!\n"
            "👤 Kimdan: {username} (ID: <code>{user_id}</code>)\n"
            "📝 Xabar:\n{message}"
        ),
        "sp_admin_photo": (
            "📩 Yangi murojaat! (rasm bilan)\n"
            "👤 Kimdan: {username} (ID: <code>{user_id}</code>)\n"
            "📝 Izoh:\n{message}"
        ),
        "sp_admin_new_no_text": "(matnsiz murojaat — rasm ilova qilingan)",
        "sp_admin_photo_attached": (
            "🖼 Yuqoridagi murojaatga ilova qilingan rasm."
        ),
        "sp_admin_hint": (
            "<i>Javob berish uchun shu xabarga Telegram'ning «Reply» "
            "(Javob berish) funksiyasi orqali yozing — javob avtomatik "
            "foydalanuvchiga yetkaziladi.</i>"
        ),
        # --- Admin javobi ---
        "sp_reply_header": "💬 Qo'llab-quvvatlash xizmati javobi:",
        "sp_admin_delivered": "✅ Javob foydalanuvchiga yetkazildi",
        "sp_need_text": (
            "✍️ Javobni MATN ko'rinishida yozing — rasm/stiker yuborilmaydi."
        ),
        "sp_cannot_deliver": (
            "⚠️ Javob foydalanuvchiga yetkazilmadi "
            "(u botni bloklagan bo'lishi mumkin)."
        ),
        "sp_unknown_user": "foydalanuvchi",
    },
    # ------------------------------------------------------------
    # 🇷🇺 RUS TILI
    # ------------------------------------------------------------
    "ru": {
        "sp_prompt": (
            "✍️ Напишите свой вопрос или проблему одним сообщением.\n"
            "(Наши администраторы скоро рассмотрят ваше сообщение)."
        ),
        "sp_btn_back": "◀️ Назад",
        "sp_confirm": (
            "✅ Ваше обращение доставлено администратору. "
            "Ответ придёт здесь."
        ),
        "sp_need_text_user": (
            "✍️ Пожалуйста, напишите вопрос ТЕКСТОМ "
            "(если отправляете фото — добавьте подпись)."
        ),
        "sp_failed": (
            "⚠️ Не удалось отправить обращение. "
            "Пожалуйста, попробуйте позже."
        ),
        "sp_no_admins": (
            "⚠️ Администраторы поддержки пока не настроены. "
            "Пожалуйста, попробуйте позже."
        ),
        "sp_cooldown": (
            "⏳ Подождите немного — ваше предыдущее обращение "
            "уже рассматривается."
        ),
        "sp_admin_new": (
            "📩 Новое обращение!\n"
            "👤 От: {username} (ID: <code>{user_id}</code>)\n"
            "📝 Сообщение:\n{message}"
        ),
        "sp_admin_photo": (
            "📩 Новое обращение! (с фото)\n"
            "👤 От: {username} (ID: <code>{user_id}</code>)\n"
            "📝 Подпись:\n{message}"
        ),
        "sp_admin_new_no_text": "(обращение без текста — приложено фото)",
        "sp_admin_photo_attached": (
            "🖼 Фото, приложенное к обращению выше."
        ),
        "sp_admin_hint": (
            "<i>Чтобы ответить, используйте «Reply» (Ответить) на это "
            "сообщение — ответ автоматически уйдёт пользователю.</i>"
        ),
        "sp_reply_header": "💬 Ответ службы поддержки:",
        "sp_admin_delivered": "✅ Ответ доставлен пользователю",
        "sp_need_text": (
            "✍️ Напишите ответ ТЕКСТОМ — фото/стикеры не отправляются."
        ),
        "sp_cannot_deliver": (
            "⚠️ Ответ не доставлен пользователю "
            "(возможно, он заблокировал бота)."
        ),
        "sp_unknown_user": "пользователь",
    },
    # ------------------------------------------------------------
    # 🇬🇧 INGLIZ TILI
    # ------------------------------------------------------------
    "en": {
        "sp_prompt": (
            "✍️ Please write your question or problem in one message.\n"
            "(Our admins will review your message shortly)."
        ),
        "sp_btn_back": "◀️ Back",
        "sp_confirm": (
            "✅ Your request has been delivered to the admin. "
            "The reply will arrive here."
        ),
        "sp_need_text_user": (
            "✍️ Please write your question as TEXT "
            "(if you send a photo, add a caption)."
        ),
        "sp_failed": (
            "⚠️ Failed to send your request. Please try again later."
        ),
        "sp_no_admins": (
            "⚠️ Support admins are not configured yet. "
            "Please try again later."
        ),
        "sp_cooldown": (
            "⏳ Please wait a moment — your previous request "
            "is already under review."
        ),
        "sp_admin_new": (
            "📩 New support request!\n"
            "👤 From: {username} (ID: <code>{user_id}</code>)\n"
            "📝 Message:\n{message}"
        ),
        "sp_admin_photo": (
            "📩 New support request! (with photo)\n"
            "👤 From: {username} (ID: <code>{user_id}</code>)\n"
            "📝 Caption:\n{message}"
        ),
        "sp_admin_new_no_text": "(no text — a photo is attached)",
        "sp_admin_photo_attached": (
            "🖼 Photo attached to the request above."
        ),
        "sp_admin_hint": (
            "<i>To answer, use Telegram's «Reply» on this message — your "
            "reply is delivered to the user automatically.</i>"
        ),
        "sp_reply_header": "💬 Support team reply:",
        "sp_admin_delivered": "✅ The reply has been delivered to the user",
        "sp_need_text": (
            "✍️ Please write your reply as TEXT — photos/stickers are not "
            "delivered."
        ),
        "sp_cannot_deliver": (
            "⚠️ The reply was not delivered "
            "(the user may have blocked the bot)."
        ),
        "sp_unknown_user": "user",
    },
}

#: Barcha kalitlar (paritet auditi va testlar uchun yagona ro'yxat).
SUPPORT_KEYS = tuple(sorted(SUPPORT_I18N["uz"]))

#: Murojaat oqimidagi tugma kalitlari (UI paritet tekshiruvlari uchun).
SUPPORT_BUTTON_KEYS = ("sp_btn_back",)

#: Admin xabarida matnsiz murojaat uchun zaxira kalit.
SUPPORT_EMPTY_MESSAGE_KEYS = ("sp_admin_new_no_text",)


def support_t(key: str, lang: str = "uz", **kwargs) -> str:
    """Tilga mos matn (noma'lum til → uz, noma'lum kalit → umumiy lug'at)."""
    code = normalize_lang(lang)
    table = SUPPORT_I18N.get(code) or SUPPORT_I18N["uz"]
    text = table.get(key)
    if text is None:
        text = SUPPORT_I18N["uz"].get(key)
    if text is None:
        return safe_t(key, code, **kwargs)
    try:
        return text.format(**kwargs) if kwargs else text
    except (KeyError, IndexError):
        return text


def support_parity_report(langs=("uz", "ru", "en")) -> dict:
    """UZ ↔ RU ↔ EN kalit va format-argument pariteti hisoboti.

    ``settings_stats_parity_report`` / ``sources_parity_report`` bilan bir xil
    struktura qaytaradi:
    ``{"keys", "missing", "extra", "format_mismatch", "empty", "in_sync"}``.
    """
    from locales.translations import format_args

    base = SUPPORT_I18N.get("uz") or {}
    base_keys = set(base)
    missing, extra, fmt_mismatch, empty = {}, {}, {}, []
    for lang in langs:
        if lang == "uz":
            continue
        table = SUPPORT_I18N.get(lang) or {}
        lang_keys = set(table)
        missing[lang] = sorted(base_keys - lang_keys)
        extra[lang] = sorted(lang_keys - base_keys)
        for key in base_keys & lang_keys:
            if format_args(base[key]) != format_args(table[key]):
                fmt_mismatch.setdefault(
                    key, {"uz": format_args(base[key]), lang: format_args(table[key])}
                )
    for lang in langs:
        table = SUPPORT_I18N.get(lang) or {}
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
    "SUPPORT_I18N",
    "SUPPORT_KEYS",
    "SUPPORT_BUTTON_KEYS",
    "SUPPORT_EMPTY_MESSAGE_KEYS",
    "support_t",
    "support_parity_report",
]
