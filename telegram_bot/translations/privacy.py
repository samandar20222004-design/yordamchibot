"""🔐 MAXFIYLIK SIYOSATI + MA'LUMOTLARNI O'CHIRISH — i18n lug'ati (UZ / RU / EN).

SPRINT 1 (Privacy & GDPR) talabi: bot qanday ma'lumotlarni saqlashini
foydalanuvchiga OCHIQ ko'rsatish va "Ma'lumotlarimni o'chirish" oqimini
uchala tilda (uz/ru/en) taqdim etish.

Bu modul — matnlarning YAGONA manbasi (``/privacy`` buyrug'i, Sozlamalar
hub'idagi «🔐 Maxfiylik siyosati» bo'limi va o'chirishni tasdiqlash
ekranlari shu yerdan oziqlanadi):

  * ``pv_title`` / ``pv_intro`` — siyosat sarlavhasi va kirish;
  * ``pv_data_*`` — qanday ma'lumotlar SAQLANADI (hisob, kanallar,
    post matnlari, AI tarixi, to'lovlar);
  * ``pv_not_*`` — nima SAQLANMAYDI (karta raqamlari, a'zolar ro'yxati,
    shaxsiy yozishmalar, media fayllar — faqat ``file_id``);
  * ``pv_use_*`` / ``pv_rights_*`` / ``pv_retention_*`` — maqsad, huquqlar va
    saqlash muddatlari;
  * ``pv_delete_*`` — "Ma'lumotlarimni o'chirish" oqimi (tasdiqlash,
    natija, bekor qilish, xato). To'lov tranzaksiyalari qonuniy audit
    uchun saqlanishi matnda OSHKORA aytiladi.

Nega alohida modul?
    ``translations/settings_stats.py`` / ``sources.py`` / ``support.py``
    bilan bir xil sabab: asosiy lug'at (``locales/translations.py`` +
    ``locales/en_overlay.py``) qat'iy audit-testlar bilan qo'riqlanadi.
    Yangi bo'lim matnlari o'z modulida yashaydi va
    ``privacy_parity_report()`` orqali UZ↔RU↔EN to'liq paritetni
    kafolatlaydi — asosiy lug'atga tegmasdan.

Foydalanish::

    from translations import privacy_t
    text = privacy_t("pv_data_account", "ru")
    done = privacy_t("pv_delete_done", "uz", channels=2, posts=14, ai_events=87)
"""

from locales.translations import normalize_lang, safe_t

# ============================================================
# 🌍 LUG'AT — uchala til (uz / ru / en) BIR XIL kalitlar to'plami
# ============================================================

PRIVACY_I18N = {
    # ------------------------------------------------------------
    # 🇺🇿 O'ZBEK TILI (asos — paritet shu kalitlar bo'yicha o'lchanadi)
    # ------------------------------------------------------------
    "uz": {
        # --- Sarlavha va kirish ---
        "pv_title": "🔐 <b>Maxfiylik siyosati</b>",
        "pv_intro": (
            "PostAssist sizning ishonchingizni qadrlaydi. Quyida qanday "
            "ma'lumotlar saqlanishi, nima uchun ishlatilishi va ularni "
            "qanday o'chirish mumkinligi ochiq ko'rsatilgan."
        ),
        # --- Saqlanadigan ma'lumotlar ---
        "pv_data_title": "📦 <b>Saqlanadigan ma'lumotlar</b>",
        "pv_data_account": (
            "• <b>Hisob:</b> Telegram ID, ism/username, til, ro'yxatdan "
            "o'tgan sana va oxirgi faollik vaqti"
        ),
        "pv_data_channels": (
            "• <b>Kanallar:</b> ulangan kanal ID, nomi, uslub (tone) va "
            "kanal statistikasi"
        ),
        "pv_data_posts": (
            "• <b>Postlar:</b> siz yaratgan/rejalashtirgan post matnlari, "
            "media <code>file_id</code> va yuborilish holati"
        ),
        "pv_data_ai": (
            "• <b>AI tarixi:</b> so'rov matni AI provayderiga yuboriladi; "
            "bizda so'rov turi, model, token/xarajat telemetriyasi va natija "
            "saqlanadi"
        ),
        "pv_data_payments": (
            "• <b>To'lovlar:</b> chek/order yozuvlari — qonuniy va "
            "buxgalteriya auditi uchun saqlanadi"
        ),
        # --- Saqlanmaydigan ma'lumotlar ---
        "pv_not_title": "🚫 <b>Saqlanmaydigan ma'lumotlar</b>",
        "pv_not_body": (
            "• Bank karta raqamlari va parollar\n"
            "• Kanalingiz a'zolari ro'yxati va shaxsiy yozishmalar\n"
            "• Shaxsiy chat xabarlari\n"
            "• Media fayllar (faqat Telegram <code>file_id</code> saqlanadi)"
        ),
        # --- Maqsad ---
        "pv_use_title": "⚙️ <b>Nima uchun ishlatiladi</b>",
        "pv_use_body": (
            "• Post yaratish, rejalashtirish va yuborish\n"
            "• Statistika, tahlil va tavsiyalar\n"
            "• Xavfsizlik, suiiste'molning oldini olish va xatolarni tuzatish"
        ),
        # --- Huquqlar ---
        "pv_rights_title": "🧾 <b>Sizning huquqlaringiz</b>",
        "pv_rights_body": (
            "• Ma'lumotlaringizni ko'rish va o'chirish\n"
            "• «🗑 O'chirish» tugmasi — hisob, kanal ulanishlari va "
            "AI tarixi tozalanadi\n"
            "• Savollar uchun: {support}"
        ),
        # --- Saqlash muddati ---
        "pv_retention_title": "🗓 <b>Saqlash muddati</b>",
        "pv_retention_body": (
            "• AI telemetriyasi — 180 kungacha\n"
            "• Post/navbat tarixi — siz o'chirmaguningizcha\n"
            "• To'lov yozuvlari — qonuniy talab bo'yicha"
        ),
        "pv_delete_hint": (
            "🗑 Ma'lumotlaringizni bir zumda «🗑 O'chirish» tugmasi orqali "
            "tozalashingiz mumkin."
        ),
        # --- Tugmalar ---
        "pv_btn_delete": "🗑 O'chirish",
        "pv_btn_confirm_delete": "✅ Ha, o'chirish",
        "pv_btn_cancel_delete": "❌ Bekor qilish",
        # --- O'chirish oqimi ---
        "pv_delete_title": "🗑 <b>Ma'lumotlarimni o'chirish</b>",
        "pv_delete_intro": "Tasdiqlasangiz quyidagilar <b>tozalanadi</b>:",
        "pv_delete_items": (
            "• Hisob profili (ism, username, til sozlamalari)\n"
            "• Kanallar bilan bog'lanish va kanal tahlil tarixi\n"
            "• Rejalashtirilgan/navbatdagi postlar, qoralamalar va shablonlar\n"
            "• AI tarixi (so'rov telemetriyasi)"
        ),
        "pv_delete_kept": (
            "ℹ️ To'lov tranzaksiyalari va kredit daftari qonuniy audit uchun "
            "saqlanadi (faqat sizga tegishli moliyaviy yozuvlar)."
        ),
        "pv_delete_ask": (
            "❓ Rostdan ham barcha ma'lumotlaringizni o'chirishni "
            "tasdiqlaysizmi? Bu amalni qaytarib bo'lmaydi."
        ),
        "pv_delete_done": (
            "✅ <b>Ma'lumotlaringiz o'chirildi.</b>\n"
            "🗑 Kanallar: {channels} ta\n"
            "🗑 Postlar: {posts} ta\n"
            "🗑 AI yozuvlari: {ai_events} ta\n\n"
            "Qaytadan boshlash uchun /start buyrug'ini yuboring."
        ),
        "pv_delete_cancelled": (
            "↩️ O'chirish bekor qilindi — ma'lumotlaringiz o'z joyida."
        ),
        "pv_delete_error": (
            "⚠️ O'chirishda xatolik yuz berdi. Birozdan so'ng qayta urinib "
            "ko'ring yoki qo'llab-quvvatlash bilan bog'laning: {support}"
        ),
        "pv_delete_already": "ℹ️ Hisobingiz allaqachon o'chirilgan.",
    },
    # ------------------------------------------------------------
    # 🇷🇺 РУССКИЙ ЯЗЫК
    # ------------------------------------------------------------
    "ru": {
        "pv_title": "🔐 <b>Политика конфиденциальности</b>",
        "pv_intro": (
            "PostAssist ценит ваше доверие. Ниже открыто показано, какие "
            "данные мы храним, зачем используем и как их удалить."
        ),
        "pv_data_title": "📦 <b>Какие данные мы храним</b>",
        "pv_data_account": (
            "• <b>Аккаунт:</b> Telegram ID, имя/username, язык, дата "
            "регистрации и время последней активности"
        ),
        "pv_data_channels": (
            "• <b>Каналы:</b> ID подключённого канала, название, стиль "
            "(tone) и статистика канала"
        ),
        "pv_data_posts": (
            "• <b>Посты:</b> тексты созданных/запланированных постов, "
            "media <code>file_id</code> и статус отправки"
        ),
        "pv_data_ai": (
            "• <b>История AI:</b> текст запроса отправляется AI-провайдеру; "
            "у нас хранятся тип запроса, модель, телеметрия "
            "токенов/стоимости и результат"
        ),
        "pv_data_payments": (
            "• <b>Платежи:</b> записи чеков/заказов — хранятся для "
            "законного и бухгалтерского аудита"
        ),
        "pv_not_title": "🚫 <b>Какие данные НЕ хранятся</b>",
        "pv_not_body": (
            "• Номера банковских карт и пароли\n"
            "• Список подписчиков канала и личная переписка\n"
            "• Сообщения личных чатов\n"
            "• Медиафайлы (хранится только Telegram <code>file_id</code>)"
        ),
        "pv_use_title": "⚙️ <b>Для чего используется</b>",
        "pv_use_body": (
            "• Создание, планирование и отправка постов\n"
            "• Статистика, аналитика и рекомендации\n"
            "• Безопасность, предотвращение злоупотреблений и исправление "
            "ошибок"
        ),
        "pv_rights_title": "🧾 <b>Ваши права</b>",
        "pv_rights_body": (
            "• Просматривать и удалять свои данные\n"
            "• «🗑 Удалить данные» — очищаются аккаунт, привязки "
            "каналов и история AI\n"
            "• По вопросам: {support}"
        ),
        "pv_retention_title": "🗓 <b>Сроки хранения</b>",
        "pv_retention_body": (
            "• AI-телеметрия — до 180 дней\n"
            "• История постов/очереди — до удаления вами\n"
            "• Платёжные записи — по требованию закона"
        ),
        "pv_delete_hint": (
            "🗑 Удалить свои данные можно мгновенно кнопкой "
            "«🗑 Удалить данные»."
        ),
        "pv_btn_delete": "🗑 Удалить данные",
        "pv_btn_confirm_delete": "✅ Да, удалить всё",
        "pv_btn_cancel_delete": "❌ Отмена",
        "pv_delete_title": "🗑 <b>Удаление моих данных</b>",
        "pv_delete_intro": "После подтверждения будут <b>очищены</b>:",
        "pv_delete_items": (
            "• Профиль аккаунта (имя, username, настройки языка)\n"
            "• Привязки каналов и история анализа каналов\n"
            "• Запланированные посты, черновики и шаблоны\n"
            "• История AI (телеметрия запросов)"
        ),
        "pv_delete_kept": (
            "ℹ️ Платёжные транзакции и кредитный реестр сохраняются для "
            "законного аудита (только финансовые записи, связанные с вами)."
        ),
        "pv_delete_ask": (
            "❓ Вы действительно подтверждаете удаление всех своих данных? "
            "Это действие необратимо."
        ),
        "pv_delete_done": (
            "✅ <b>Ваши данные удалены.</b>\n"
            "🗑 Каналы: {channels}\n"
            "🗑 Посты: {posts}\n"
            "🗑 Записи AI: {ai_events}\n\n"
            "Чтобы начать заново, отправьте /start."
        ),
        "pv_delete_cancelled": (
            "↩️ Удаление отменено — ваши данные на месте."
        ),
        "pv_delete_error": (
            "⚠️ Не удалось удалить данные. Попробуйте ещё раз позже или "
            "свяжитесь с поддержкой: {support}"
        ),
        "pv_delete_already": "ℹ️ Ваш аккаунт уже удалён.",
    },
    # ------------------------------------------------------------
    # 🇬🇧 ENGLISH
    # ------------------------------------------------------------
    "en": {
        "pv_title": "🔐 <b>Privacy policy</b>",
        "pv_intro": (
            "PostAssist values your trust. Below is a plain-language summary "
            "of what we store, why we use it, and how to delete it."
        ),
        "pv_data_title": "📦 <b>Data we store</b>",
        "pv_data_account": (
            "• <b>Account:</b> Telegram ID, name/username, language, signup "
            "date and last activity time"
        ),
        "pv_data_channels": (
            "• <b>Channels:</b> linked channel ID, title, tone of voice and "
            "channel statistics"
        ),
        "pv_data_posts": (
            "• <b>Posts:</b> texts of created/scheduled posts, media "
            "<code>file_id</code> and delivery status"
        ),
        "pv_data_ai": (
            "• <b>AI history:</b> the prompt text is sent to an AI provider; "
            "we keep the request type, model, token/cost telemetry and the "
            "result"
        ),
        "pv_data_payments": (
            "• <b>Payments:</b> receipt/order records — kept for legal and "
            "accounting audit"
        ),
        "pv_not_title": "🚫 <b>Data we do NOT store</b>",
        "pv_not_body": (
            "• Bank card numbers and passwords\n"
            "• Your channel subscriber list and private conversations\n"
            "• Private chat messages\n"
            "• Media files (only the Telegram <code>file_id</code> is stored)"
        ),
        "pv_use_title": "⚙️ <b>Why we use it</b>",
        "pv_use_body": (
            "• Creating, scheduling and publishing posts\n"
            "• Statistics, analytics and recommendations\n"
            "• Security, abuse prevention and bug fixing"
        ),
        "pv_rights_title": "🧾 <b>Your rights</b>",
        "pv_rights_body": (
            "• View and delete your data\n"
            "• “🗑 Delete data” wipes the account, channel links and AI "
            "history\n"
            "• Questions: {support}"
        ),
        "pv_retention_title": "🗓 <b>Retention</b>",
        "pv_retention_body": (
            "• AI telemetry — up to 180 days\n"
            "• Post/queue history — until you delete it\n"
            "• Payment records — as required by law"
        ),
        "pv_delete_hint": (
            "🗑 You can wipe your data instantly with the "
            "“🗑 Delete data” button."
        ),
        "pv_btn_delete": "🗑 Delete data",
        "pv_btn_confirm_delete": "✅ Yes, delete all",
        "pv_btn_cancel_delete": "❌ Cancel",
        "pv_delete_title": "🗑 <b>Delete my data</b>",
        "pv_delete_intro": "Once confirmed, the following will be <b>wiped</b>:",
        "pv_delete_items": (
            "• Account profile (name, username, language settings)\n"
            "• Channel links and channel analysis history\n"
            "• Scheduled posts, drafts and templates\n"
            "• AI history (request telemetry)"
        ),
        "pv_delete_kept": (
            "ℹ️ Payment transactions and the credit ledger are retained for "
            "legal audit (only the financial records linked to you)."
        ),
        "pv_delete_ask": (
            "❓ Do you really confirm deleting all of your data? This action "
            "cannot be undone."
        ),
        "pv_delete_done": (
            "✅ <b>Your data has been deleted.</b>\n"
            "🗑 Channels: {channels}\n"
            "🗑 Posts: {posts}\n"
            "🗑 AI records: {ai_events}\n\n"
            "Send /start to begin again."
        ),
        "pv_delete_cancelled": "↩️ Deletion cancelled — your data is intact.",
        "pv_delete_error": (
            "⚠️ Failed to delete your data. Please try again later or "
            "contact support: {support}"
        ),
        "pv_delete_already": "ℹ️ Your account has already been deleted.",
    },
}

#: Barcha kalitlar (paritet auditi va testlar uchun yagona ro'yxat).
PRIVACY_KEYS = tuple(sorted(PRIVACY_I18N["uz"].keys()))

#: O'chirish oqimi ekranlarida ishlatiladigan matn kalitlari (testlar uchun).
PRIVACY_DELETE_KEYS = (
    "pv_delete_title",
    "pv_delete_intro",
    "pv_delete_items",
    "pv_delete_kept",
    "pv_delete_ask",
    "pv_delete_done",
    "pv_delete_cancelled",
    "pv_delete_error",
    "pv_delete_already",
)

#: Siyosat ekranidagi bo'lim kalitlari (hammasi ko'rsatilishi shart).
PRIVACY_POLICY_KEYS = (
    "pv_title",
    "pv_intro",
    "pv_data_title",
    "pv_data_account",
    "pv_data_channels",
    "pv_data_posts",
    "pv_data_ai",
    "pv_data_payments",
    "pv_not_title",
    "pv_not_body",
    "pv_use_title",
    "pv_use_body",
    "pv_rights_title",
    "pv_rights_body",
    "pv_retention_title",
    "pv_retention_body",
)


def privacy_t(key: str, lang: str = "uz", **kwargs) -> str:
    """Kalitni til bo'yicha qaytaradi (topilmasa — asosiy lug'atdan).

    ``support_t`` / ``settings_stats_t`` bilan bir xil xulq: noto'g'ri til
    ``uz`` ga tushadi, yetishmayotgan kalit avval ``uz`` dan, u ham bo'lmasa
    ``safe_t`` orqali asosiy lug'atdan olinadi (hech qachon ``KeyError``
    ko'tarilmaydi).
    """
    code = normalize_lang(lang)
    table = PRIVACY_I18N.get(code) or PRIVACY_I18N["uz"]
    text = table.get(key)
    if text is None:
        text = PRIVACY_I18N["uz"].get(key)
    if text is None:
        return safe_t(key, code, **kwargs)
    try:
        return text.format(**kwargs) if kwargs else text
    except (KeyError, IndexError):
        return text


def privacy_parity_report(langs=("uz", "ru", "en")) -> dict:
    """UZ ↔ RU ↔ EN kalit va format-argument pariteti hisoboti.

    ``support_parity_report`` / ``settings_stats_parity_report`` bilan bir xil
    struktura: ``{"keys", "missing", "extra", "format_mismatch", "empty",
    "in_sync"}``.
    """
    from locales.translations import format_args

    base = PRIVACY_I18N.get("uz") or {}
    base_keys = set(base)
    missing, extra, fmt_mismatch, empty = {}, {}, {}, []
    for lang in langs:
        if lang == "uz":
            continue
        table = PRIVACY_I18N.get(lang) or {}
        lang_keys = set(table)
        missing[lang] = sorted(base_keys - lang_keys)
        extra[lang] = sorted(lang_keys - base_keys)
        for key in base_keys & lang_keys:
            if format_args(base[key]) != format_args(table[key]):
                fmt_mismatch.setdefault(
                    key, {"uz": format_args(base[key]), lang: format_args(table[key])}
                )
    for lang in langs:
        table = PRIVACY_I18N.get(lang) or {}
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
    "PRIVACY_I18N",
    "PRIVACY_KEYS",
    "PRIVACY_DELETE_KEYS",
    "PRIVACY_POLICY_KEYS",
    "privacy_t",
    "privacy_parity_report",
]
