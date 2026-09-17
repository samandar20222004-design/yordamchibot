"""✍️ ODDIY POST (AI'SIZ) — i18n lug'ati (UZ / RU / EN, 100% paritet).

Birlashtirilgan kontent menyusidagi «✍️ Oddiy post (AI'siz)» yo'nalishi
uchun barcha matnlar shu modulda yashaydi (``translations/content_menu.py``
bilan bir xil qoida): asosiy repo lug'atiga (``locales/translations.py``)
tegilmaydi, paritet esa ``manual_post_parity_report()`` bilan qo'riqlanadi.

Oqim (handlers/manual_post.py):
  1. foydalanuvchi tayyor matn / rasm / video yuboradi;
  2. bot HECH QANDAY AI savollarini bermasdan darhol PREVIEW chiqaradi;
  3. preview ostida UNIVERSAL boshqaruv paneli:
       [🚀 Hozir yuborish]
       [📅 Vaqtni belgilash]
       [🗑 24 soatlik e'lon]   [🔄 Takroriy e'lon]
       [✏️ Tahrirlash]         [❌ Bekor qilish]

Foydalanish:
    from translations import manual_post_t
    text = manual_post_t("mp_intro", "ru")
"""

from locales.translations import normalize_lang, safe_t

# ============================================================
# 🌍 LUG'AT — uchala til (uz / ru / en) BIR XIL kalitlar to'plami
# ============================================================

MANUAL_POST_I18N = {
    # ------------------------------------------------------------
    # 🇺🇿 O'ZBEK TILI
    # ------------------------------------------------------------
    "uz": {
        # --- Kirish yo'riqnomasi (kontent kutilmoqda) ---
        "mp_intro": (
            "✍️ <b>Oddiy post (AI'siz)</b>\n\n"
            "Tayyor postingizni yuboring: <b>matn</b>, <b>rasm</b> yoki "
            "<b>video</b> (izoh bilan yoki izohsiz).\n\n"
            "Hech qanday AI aralashuvisiz — postingiz o'zgarishsiz, "
            "to'g'ridan-to'g'ri kanalga chiqadi.\n\n"
            "<i>❌ Bekor qilish — istalgan payt jarayonni to'xtatadi.</i>"
        ),
        # --- Kontent qabul qilindi: preview sarlavhasi ---
        "mp_preview_title": "👀 <b>Post preview — tayyor!</b>\n\n",
        "mp_preview_foot": (
            "\n\n<b>Endi nima qilamiz?</b>\n"
            "🚀 Hozir yuborish — darhol kanalga chiqadi\n"
            "📅 Vaqtni belgilash — masalan, 19:30 ga\n"
            "🗑 24 soatlik e'lon — chiqadi va 24 soatdan keyin avtomatik "
            "o'chadi\n"
            "🔄 Takroriy e'lon — har kuni bitta vaqtda qayta chiqadi"
        ),
        # --- Universal boshqaruv paneli tugmalari ---
        "mp_btn_send_now": "🚀 Hozir yuborish",
        "mp_btn_schedule": "📅 Vaqtni belgilash",
        "mp_btn_24h": "🗑 24 soatlik e'lon",
        "mp_btn_repeat": "🔄 Takroriy e'lon",
        "mp_btn_edit": "✏️ Tahrirlash",
        "mp_btn_cancel": "❌ Bekor qilish",
        "mp_btn_back_panel": "◀️ Orqaga",
        # --- Kanal tanlash ---
        "mp_choose_channel": "📢 <b>Qaysi kanalga chiqaramiz?</b>",
        # --- Vaqt so'rash ---
        "mp_time_prompt": (
            "📅 <b>Vaqtni belgilash.</b>\n\n"
            "Post qachon chiqsin? Masalan: <code>19:30</code>, "
            "<code>ertaga 09:00</code> yoki <code>25.09.2026 18:00</code>."
        ),
        "mp_time_invalid": (
            "⚠️ Vaqtni tushunmadim. Iltimos, boshqacha yozing — masalan, "
            "<code>19:30</code> yoki <code>ertaga 09:00</code>."
        ),
        # --- Takroriy e'lon uchun vaqt ---
        "mp_repeat_prompt": (
            "🔄 <b>Takroriy e'lon.</b>\n\n"
            "Har kuni soat nechida qayta chiqsin? Masalan: <code>19:30</code>."
        ),
        # --- Tahrirlash ---
        "mp_edit_prompt": (
            "✏️ <b>Tahrirlash.</b>\n\n"
            "Yangi matn yoki rasm/video yuboring — preview yangilanadi."
        ),
        # --- YAKUNIY natija xabarlari ---
        "mp_sent_now": (
            "✅ <b>Post kanalga yuborildi!</b>\n\n"
            "📢 Kanal: <b>{channel}</b>"
        ),
        "mp_scheduled": (
            "📅 <b>Post rejalashtirildi!</b>\n\n"
            "📢 Kanal: <b>{channel}</b>\n"
            "🕐 Vaqt: <b>{time}</b>"
        ),
        "mp_sent_24h": (
            "🗑 <b>24 soatlik e'lon sifatida yuborildi!</b>\n\n"
            "📢 Kanal: <b>{channel}</b>\n"
            "⏳ Post chiqdi va <b>24 soatdan keyin</b> avtomatik o'chadi."
        ),
        "mp_repeat_ok": (
            "🔄 <b>Takroriy e'lon yoqildi!</b>\n\n"
            "📢 Kanal: <b>{channel}</b>\n"
            "🕐 Har kuni soat <b>{time}</b> da qayta chiqadi."
        ),
        # --- Xatolar va tizim xabarlari ---
        "mp_no_channels": (
            "📢 <b>Birorta kanal ulanmagan.</b>\n\n"
            "Post chiqarish uchun avval «📢 Kanallarim» bo'limida kanal "
            "ulang."
        ),
        "mp_content_hint": (
            "✍️ Avval post kontentini yuboring: matn, rasm yoki video. "
            "Hozircha kontent qabul qilinmadi."
        ),
        "mp_unsupported": (
            "🤔 Bu turdagi xabarni oddiy post sifatida yubora olmayman. "
            "Iltimos, <b>matn</b>, <b>rasm</b> yoki <b>video</b> yuboring."
        ),
        "mp_cancelled": "❌ <b>Oddiy post bekor qilindi.</b> Hech narsa yuborilmadi.",
        # 🔁 PHASE C — dublikat detektori (post chiqarilishidan oldin).
        # DIQQAT: bu — istisnoiy ogohlantirish oynasi; oddiy oqimda AI
        # ishtirok etmaydi, [✨ AI bilan yangilash] faqat foydalanuvchi
        # o'zi bosganda ishlaydi.
        "mp_dup_warning": (
            "⚠️ O'xshash post topildi. Bu post yaqindagi postingizga juda "
            "o'xshaydi.\n\nO'xshashlik: <b>{score}%</b>\n\n"
            "<i>Kanalning oxirgi postidan parcha:</i>\n{preview}"
        ),
        "mp_dup_btn_force": "🚀 Baribir chiqarish",
        "mp_dup_btn_ai": "✨ AI bilan yangilash",
        "mp_dup_ai_failed": (
            "⚠️ AI bilan yangilash hozircha ishlamadi. Postni qo'lda "
            "tahrirlashingiz ([✏️ Tahrirlash]) yoki baribir chiqarishingiz "
            "mumkin."
        ),
        "mp_dup_ai_done": (
            "✨ Post AI bilan yangilandi — endi boshqacha. Pastdagi panel "
            "bilan davom eting."
        ),
        "mp_session_expired": (
            "⚠️ Sessiya eskirgan. Iltimos, «✍️ Oddiy post (AI'siz)» "
            "bo'limidan qayta boshlang."
        ),
        "mp_save_error": (
            "⚠️ Postni saqlashda xatolik yuz berdi. Iltimos, qayta urinib "
            "ko'ring."
        ),
    },
    # ------------------------------------------------------------
    # 🇷🇺 RUS TILI
    # ------------------------------------------------------------
    "ru": {
        "mp_intro": (
            "✍️ <b>Обычный пост (без AI)</b>\n\n"
            "Отправьте готовый пост: <b>текст</b>, <b>фото</b> или "
            "<b>видео</b> (с подписью или без).\n\n"
            "Без какого-либо вмешательства AI — пост выйдет в канал без "
            "изменений.\n\n"
            "<i>❌ Отмена — остановит процесс в любой момент.</i>"
        ),
        "mp_preview_title": "👀 <b>Предпросмотр поста — готово!</b>\n\n",
        "mp_preview_foot": (
            "\n\n<b>Что делаем дальше?</b>\n"
            "🚀 Отправить сейчас — сразу выйдет в канал\n"
            "📅 Указать время — например, на 19:30\n"
            "🗑 Объявление на 24 часа — выйдет и удалится через 24 часа\n"
            "🔄 Повторяемое объявление — выходит ежедневно в одно время"
        ),
        "mp_btn_send_now": "🚀 Отправить сейчас",
        "mp_btn_schedule": "📅 Указать время",
        "mp_btn_24h": "🗑 Объявление на 24 часа",
        "mp_btn_repeat": "🔄 Повторяемое объявление",
        "mp_btn_edit": "✏️ Редактировать",
        "mp_btn_cancel": "❌ Отмена",
        "mp_btn_back_panel": "◀️ Назад",
        "mp_choose_channel": "📢 <b>В какой канал публикуем?</b>",
        "mp_time_prompt": (
            "📅 <b>Указать время.</b>\n\n"
            "Когда должен выйти пост? Например: <code>19:30</code>, "
            "<code>завтра 09:00</code> или <code>25.09.2026 18:00</code>."
        ),
        "mp_time_invalid": (
            "⚠️ Не понял время. Напишите по-другому — например, "
            "<code>19:30</code> или <code>завтра 09:00</code>."
        ),
        "mp_repeat_prompt": (
            "🔄 <b>Повторяемое объявление.</b>\n\n"
            "Во сколько ежедневно публиковать? Например: <code>19:30</code>."
        ),
        "mp_edit_prompt": (
            "✏️ <b>Редактирование.</b>\n\n"
            "Отправьте новый текст или фото/видео — предпросмотр обновится."
        ),
        "mp_sent_now": (
            "✅ <b>Пост отправлен в канал!</b>\n\n"
            "📢 Канал: <b>{channel}</b>"
        ),
        "mp_scheduled": (
            "📅 <b>Пост запланирован!</b>\n\n"
            "📢 Канал: <b>{channel}</b>\n"
            "🕐 Время: <b>{time}</b>"
        ),
        "mp_sent_24h": (
            "🗑 <b>Отправлено как объявление на 24 часа!</b>\n\n"
            "📢 Канал: <b>{channel}</b>\n"
            "⏳ Пост вышел и будет автоматически удалён <b>через 24 часа</b>."
        ),
        "mp_repeat_ok": (
            "🔄 <b>Повторяемое объявление включено!</b>\n\n"
            "📢 Канал: <b>{channel}</b>\n"
            "🕐 Выходит ежедневно в <b>{time}</b>."
        ),
        "mp_no_channels": (
            "📢 <b>Не подключён ни один канал.</b>\n\n"
            "Сначала подключите канал в разделе «📢 Мои каналы»."
        ),
        "mp_content_hint": (
            "✍️ Сначала отправьте контент поста: текст, фото или видео. "
            "Пока контент не получен."
        ),
        "mp_unsupported": (
            "🤔 Не могу отправить такой тип сообщения как обычный пост. "
            "Отправьте <b>текст</b>, <b>фото</b> или <b>видео</b>."
        ),
        "mp_cancelled": "❌ <b>Обычный пост отменён.</b> Ничего не отправлено.",
        # 🔁 PHASE C — детектор дубликатов (перед публикацией поста).
        "mp_dup_warning": (
            "⚠️ Найден похожий пост. Этот пост очень похож на ваш недавний."
            "\n\nСходство: <b>{score}%</b>\n\n"
            "<i>Фрагмент последнего поста канала:</i>\n{preview}"
        ),
        "mp_dup_btn_force": "🚀 Всё равно опубликовать",
        "mp_dup_btn_ai": "✨ Обновить с помощью AI",
        "mp_dup_ai_failed": (
            "⚠️ Обновление через AI сейчас не сработало. Вы можете "
            "отредактировать пост вручную ([✏️ Изменить]) или опубликовать "
            "как есть."
        ),
        "mp_dup_ai_done": (
            "✨ Пост обновлён с помощью AI — теперь другой. Продолжайте с "
            "панелью ниже."
        ),
        "mp_session_expired": (
            "⚠️ Сессия устарела. Начните заново через раздел "
            "«✍️ Обычный пост (без AI)»."
        ),
        "mp_save_error": (
            "⚠️ Ошибка при сохранении поста. Попробуйте ещё раз."
        ),
    },
    # ------------------------------------------------------------
    # 🇬🇧 INGLIZ TILI
    # ------------------------------------------------------------
    "en": {
        "mp_intro": (
            "✍️ <b>Regular post (no AI)</b>\n\n"
            "Send your finished post: <b>text</b>, <b>photo</b> or "
            "<b>video</b> (with or without a caption).\n\n"
            "With zero AI involvement — your post goes to the channel "
            "exactly as is.\n\n"
            "<i>❌ Cancel stops the process at any time.</i>"
        ),
        "mp_preview_title": "👀 <b>Post preview — ready!</b>\n\n",
        "mp_preview_foot": (
            "\n\n<b>What's next?</b>\n"
            "🚀 Send now — published to the channel immediately\n"
            "📅 Set time — for example, 19:30\n"
            "🗑 24-hour announcement — published, then auto-deleted after "
            "24 hours\n"
            "🔄 Recurring announcement — republished daily at the same time"
        ),
        "mp_btn_send_now": "🚀 Send now",
        "mp_btn_schedule": "📅 Set time",
        "mp_btn_24h": "🗑 24-hour announcement",
        "mp_btn_repeat": "🔄 Recurring announcement",
        "mp_btn_edit": "✏️ Edit",
        "mp_btn_cancel": "❌ Cancel",
        "mp_btn_back_panel": "◀️ Back",
        "mp_choose_channel": "📢 <b>Which channel do we publish to?</b>",
        "mp_time_prompt": (
            "📅 <b>Set the time.</b>\n\n"
            "When should the post go out? For example: <code>19:30</code>, "
            "<code>tomorrow 09:00</code> or <code>09/25/2026 18:00</code>."
        ),
        "mp_time_invalid": (
            "⚠️ I didn't get the time. Please write it differently — e.g. "
            "<code>19:30</code> or <code>tomorrow 09:00</code>."
        ),
        "mp_repeat_prompt": (
            "🔄 <b>Recurring announcement.</b>\n\n"
            "At what time every day? For example: <code>19:30</code>."
        ),
        "mp_edit_prompt": (
            "✏️ <b>Edit.</b>\n\n"
            "Send the new text or photo/video — the preview will update."
        ),
        "mp_sent_now": (
            "✅ <b>Post sent to the channel!</b>\n\n"
            "📢 Channel: <b>{channel}</b>"
        ),
        "mp_scheduled": (
            "📅 <b>Post scheduled!</b>\n\n"
            "📢 Channel: <b>{channel}</b>\n"
            "🕐 Time: <b>{time}</b>"
        ),
        "mp_sent_24h": (
            "🗑 <b>Sent as a 24-hour announcement!</b>\n\n"
            "📢 Channel: <b>{channel}</b>\n"
            "⏳ The post is out and will be auto-deleted <b>in 24 hours</b>."
        ),
        "mp_repeat_ok": (
            "🔄 <b>Recurring announcement enabled!</b>\n\n"
            "📢 Channel: <b>{channel}</b>\n"
            "🕐 Published daily at <b>{time}</b>."
        ),
        "mp_no_channels": (
            "📢 <b>No channels connected.</b>\n\n"
            "Connect a channel in “📢 My channels” first."
        ),
        "mp_content_hint": (
            "✍️ Send the post content first: text, photo or video. "
            "No content received yet."
        ),
        "mp_unsupported": (
            "🤔 I can't publish this message type as a regular post. "
            "Please send <b>text</b>, a <b>photo</b> or a <b>video</b>."
        ),
        "mp_cancelled": "❌ <b>Regular post cancelled.</b> Nothing was sent.",
        # 🔁 PHASE C — duplicate detector (before publishing).
        "mp_dup_warning": (
            "⚠️ Similar post found. This post is very similar to your "
            "recent one.\n\nSimilarity: <b>{score}%</b>\n\n"
            "<i>Fragment of the channel's recent post:</i>\n{preview}"
        ),
        "mp_dup_btn_force": "🚀 Post anyway",
        "mp_dup_btn_ai": "✨ Refresh with AI",
        "mp_dup_ai_failed": (
            "⚠️ AI refresh is unavailable right now. You can edit the post "
            "manually ([✏️ Edit]) or post it as is."
        ),
        "mp_dup_ai_done": (
            "✨ The post was refreshed with AI — now different. Continue "
            "with the panel below."
        ),
        "mp_session_expired": (
            "⚠️ Session expired. Please start again via "
            "“✍️ Regular post (no AI)”."
        ),
        "mp_save_error": (
            "⚠️ An error occurred while saving the post. Please try again."
        ),
    },
}

#: Barcha kalitlar (paritet auditi va testlar uchun yagona ro'yxat).
MANUAL_POST_KEYS = tuple(sorted(MANUAL_POST_I18N["uz"].keys()))


def manual_post_t(key: str, lang: str = "uz", **kwargs) -> str:
    """Oddiy post oqimi matnini qaytaradi (uz / ru / en).

    Kalit shu modulda bo'lmasa asosiy repo lug'atiga (``safe_t``) tushadi —
    ``content_menu_t`` / ``magic_t`` bilan bir xil mantiq.
    """
    code = normalize_lang(lang)
    table = MANUAL_POST_I18N.get(code) or {}
    text = table.get(key)
    if text is None:
        text = (MANUAL_POST_I18N.get("uz") or {}).get(key)
    if text is None:
        return safe_t(key, code, **kwargs)
    try:
        return text.format(**kwargs) if kwargs else text
    except Exception:  # pragma: no cover - format himoyasi
        return text


def manual_post_parity_report(langs=("uz", "ru", "en")) -> dict:
    """UZ ↔ RU ↔ EN kalit va format-argument pariteti hisoboti."""
    from locales.translations import format_args

    base = MANUAL_POST_I18N.get("uz") or {}
    base_keys = set(base)
    missing, extra, fmt_mismatch, empty = {}, {}, [], []
    for lang in langs:
        if lang == "uz":
            continue
        table = MANUAL_POST_I18N.get(lang) or {}
        lang_keys = set(table)
        missing[lang] = sorted(base_keys - lang_keys)
        extra[lang] = sorted(lang_keys - base_keys)
        for key in base_keys & lang_keys:
            if format_args(base[key]) != format_args(table[key]):
                fmt_mismatch.setdefault(
                    key, {"uz": format_args(base[key]), lang: format_args(table[key])}
                )
    for lang in langs:
        table = MANUAL_POST_I18N.get(lang) or {}
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
