"""📢 KANALLARIM + 📅 REJALASHTIRILGAN — i18n lug'ati (UZ / RU / EN, 100% paritet).

PostAssist V2 · 4-mikro qadam. Master plan standarti bo'yicha ikkita bo'lim
qayta tuzildi va ularning BARCHA yangi matnlari shu modulda uchala tilda
saqlanadi (``translations/content_menu.py`` bilan bir xil naqsh):

📢 **KANALLARIM**
    Asosiy menyudagi «📢 Kanallarim» tugmasi ulangan kanallar RO'YXATINI va
    [➕ Kanal qo'shish] tugmasini chizadi. Kanal tanlanganda esa o'sha kanalga
    tegishli BOSHQARUV EKRANI ochiladi::

        [➕ Post yaratish]
        [📅 Rejalashtirilgan]   [📊 Statistika]
        [⚙️ Kanal sozlamalari]  [◀️ Orqaga]

    Ichki amallar (rejalashtirilgan postlar, statistika, sozlamalar) shu
    ekran ICHIDA bajariladi — foydalanuvchi asosiy menyuga "otilib"
    chiqmaydi, [◀️ Orqaga] esa kanallar ro'yxatiga qaytaradi.

📅 **REJALASHTIRILGAN**
    Eskirgan texnik nom («Postlar navbati» / «Navbatdagi postlar» / «Queue»)
    o'rniga yagona, tushunarli nom: «📅 Rejalashtirilgan» (RU «📅
    Запланированные», EN «📅 Scheduled»). Postlar VAQT BO'YICHA tartiblangan
    ixcham inline qatorlarda ko'rsatiladi::

        1. 🕐 Bugun 18:00 — 📝 Yangi mahsulot chegirmasi | 📢 Mening kanalim

    Har bir post ostida esa [✏️ Tahrirlash] · [⏰ Vaqtni o'zgartirish] ·
    [🗑 O'chirish] amallari turadi.

Eslatma (orqaga moslik): eski ``queue_*`` lug'at kalitlari, ``btn_queue`` /
``cab_queue`` tugma yorliqlari va ``qview:`` / ``qdel:`` / ``qpush:``
callback'lari O'ZGARMAYDI — ular ALIAS sifatida yashab qoladi, shuning uchun
chat tarixidagi eski klaviatura va tugmalar buzilmaydi.
"""

from __future__ import annotations

from locales.translations import normalize_lang, safe_t

# ---------------------------------------------------------------------------
# I18N LUG'ATI
# ---------------------------------------------------------------------------
CHANNELS_QUEUE_I18N = {
    # ------------------------------------------------------------
    # 🇺🇿 O'ZBEK TILI (asos — paritet shu kalitlar bo'yicha o'lchanadi)
    # ------------------------------------------------------------
    "uz": {
        # --- 📢 Kanallarim: ro'yxat ekrani ---
        "cq_ch_list_title": (
            "📢 <b>Kanallarim</b> — {count} ta kanal ulangan.\n\n"
            "Boshqarish uchun kanalni tanlang 👇"
        ),
        "cq_ch_empty": (
            "📢 <b>Kanallarim</b>\n\n"
            "Hozircha birorta kanal ulanmagan.\n"
            "Botni kanalingizga <b>administrator</b> qilib qo'shing va "
            "quyidagi tugma orqali ulang."
        ),
        "cq_ch_add_btn": "➕ Kanal qo'shish",
        "cq_ch_close_btn": "❌ Yopish",
        # --- 📢 Kanallarim: kanal boshqaruv ekrani ---
        "cq_ch_panel_title": (
            "📢 <b>{channel}</b>\n\n"
            "Kanal bo'yicha kerakli amalni tanlang 👇"
        ),
        "cq_ch_btn_create_post": "➕ Post yaratish",
        "cq_ch_btn_scheduled": "📅 Rejalashtirilgan",
        "cq_ch_btn_stats": "📊 Statistika",
        "cq_ch_btn_settings": "⚙️ Kanal sozlamalari",
        "cq_ch_btn_back": "◀️ Orqaga",
        # --- 📢 Kanallarim: kanal sozlamalari ekrani ---
        "cq_ch_settings_title": (
            "⚙️ <b>{channel}</b> — kanal sozlamalari\n\n"
            "Uslub (tone of voice), AI tahlil va kanalni uzish shu yerda."
        ),
        "cq_ch_btn_tone": "🎨 Uslub",
        "cq_ch_btn_voice": "🎙 Kanal ovozi tahlili",
        "cq_ch_btn_delete": "🗑 Kanalni uzish",
        # --- 📢 Kanallarim: kanal statistikasi ---
        "cq_ch_stats_empty": (
            "📊 <b>{channel}</b>\n\n"
            "Bu kanal bo'yicha hali statistika yo'q — birinchi postni "
            "rejalashtiring."
        ),
        # --- 📢 Kanallarim: xatoliklar ---
        "cq_ch_not_found": (
            "⚠️ Kanal topilmadi yoki u sizga tegishli emas.\n"
            "Ro'yxatni yangilab, qaytadan urinib ko'ring."
        ),
        "cq_ch_post_intro": (
            "✍️ <b>{channel}</b> uchun post matnini yoki mediasini yuboring.\n\n"
            "<i>Matn, rasm, video, hujjat yoki albom — hammasi qabul qilinadi.</i>"
        ),
        # --- 📅 Rejalashtirilgan: ro'yxat ---
        "cq_sch_title": "📅 <b>Rejalashtirilgan</b> — {count} ta post:",
        "cq_sch_title_range": (
            "📅 <b>Rejalashtirilgan</b> — {count} ta post ({start}-{end}):"
        ),
        "cq_sch_channel_title": (
            "📅 <b>Rejalashtirilgan</b> — 📢 {channel} ({count} ta post):"
        ),
        "cq_sch_empty": (
            "📅 <b>Rejalashtirilgan</b>\n\n"
            "Hozircha rejalashtirilgan post yo'q.\n"
            "Yangi post yarating va chiqish vaqtini belgilang."
        ),
        "cq_sch_channel_empty": (
            "📅 <b>Rejalashtirilgan</b> — 📢 {channel}\n\n"
            "Bu kanal uchun rejalashtirilgan post yo'q."
        ),
        # --- 📅 Rejalashtirilgan: post amallari ---
        "cq_sch_btn_edit": "✏️ Tahrirlash",
        "cq_sch_btn_time": "⏰ Vaqtni o'zgartirish",
        "cq_sch_btn_delete": "🗑 O'chirish",
        "cq_sch_deleted_alert": "🗑 Post rejadan olib tashlandi.",
        "cq_sch_not_found": "⚠️ Post topilmadi — u allaqachon chiqib ketgan yoki o'chirilgan.",
    },
    # ------------------------------------------------------------
    # 🇷🇺 RUS TILI
    # ------------------------------------------------------------
    "ru": {
        "cq_ch_list_title": (
            "📢 <b>Мои каналы</b> — подключено каналов: {count}.\n\n"
            "Выберите канал для управления 👇"
        ),
        "cq_ch_empty": (
            "📢 <b>Мои каналы</b>\n\n"
            "Пока не подключён ни один канал.\n"
            "Добавьте бота в свой канал как <b>администратора</b> и "
            "подключите его кнопкой ниже."
        ),
        "cq_ch_add_btn": "➕ Добавить канал",
        "cq_ch_close_btn": "❌ Закрыть",
        "cq_ch_panel_title": (
            "📢 <b>{channel}</b>\n\n"
            "Выберите нужное действие по каналу 👇"
        ),
        "cq_ch_btn_create_post": "➕ Создать пост",
        "cq_ch_btn_scheduled": "📅 Запланированные",
        "cq_ch_btn_stats": "📊 Статистика",
        "cq_ch_btn_settings": "⚙️ Настройки канала",
        "cq_ch_btn_back": "◀️ Назад",
        "cq_ch_settings_title": (
            "⚙️ <b>{channel}</b> — настройки канала\n\n"
            "Стиль (tone of voice), AI-анализ и отключение канала — здесь."
        ),
        "cq_ch_btn_tone": "🎨 Стиль",
        "cq_ch_btn_voice": "🎙 Анализ голоса канала",
        "cq_ch_btn_delete": "🗑 Отключить канал",
        "cq_ch_stats_empty": (
            "📊 <b>{channel}</b>\n\n"
            "По этому каналу пока нет статистики — запланируйте первый пост."
        ),
        "cq_ch_not_found": (
            "⚠️ Канал не найден или не принадлежит вам.\n"
            "Обновите список и попробуйте снова."
        ),
        "cq_ch_post_intro": (
            "✍️ Отправьте текст или медиа поста для <b>{channel}</b>.\n\n"
            "<i>Текст, фото, видео, документ или альбом — принимается всё.</i>"
        ),
        "cq_sch_title": "📅 <b>Запланированные</b> — постов: {count}:",
        "cq_sch_title_range": (
            "📅 <b>Запланированные</b> — постов: {count} ({start}-{end}):"
        ),
        "cq_sch_channel_title": (
            "📅 <b>Запланированные</b> — 📢 {channel} (постов: {count}):"
        ),
        "cq_sch_empty": (
            "📅 <b>Запланированные</b>\n\n"
            "Пока нет запланированных постов.\n"
            "Создайте новый пост и укажите время публикации."
        ),
        "cq_sch_channel_empty": (
            "📅 <b>Запланированные</b> — 📢 {channel}\n\n"
            "Для этого канала нет запланированных постов."
        ),
        "cq_sch_btn_edit": "✏️ Редактировать",
        "cq_sch_btn_time": "⏰ Изменить время",
        "cq_sch_btn_delete": "🗑 Удалить",
        "cq_sch_deleted_alert": "🗑 Пост снят с расписания.",
        "cq_sch_not_found": "⚠️ Пост не найден — он уже опубликован или удалён.",
    },
    # ------------------------------------------------------------
    # 🇬🇧 INGLIZ TILI
    # ------------------------------------------------------------
    "en": {
        "cq_ch_list_title": (
            "📢 <b>My channels</b> — {count} channel(s) connected.\n\n"
            "Pick a channel to manage 👇"
        ),
        "cq_ch_empty": (
            "📢 <b>My channels</b>\n\n"
            "No channel connected yet.\n"
            "Add the bot to your channel as an <b>administrator</b> and "
            "connect it with the button below."
        ),
        "cq_ch_add_btn": "➕ Add channel",
        "cq_ch_close_btn": "❌ Close",
        "cq_ch_panel_title": (
            "📢 <b>{channel}</b>\n\n"
            "Choose what to do with this channel 👇"
        ),
        "cq_ch_btn_create_post": "➕ Create post",
        "cq_ch_btn_scheduled": "📅 Scheduled",
        "cq_ch_btn_stats": "📊 Statistics",
        "cq_ch_btn_settings": "⚙️ Channel settings",
        "cq_ch_btn_back": "◀️ Back",
        "cq_ch_settings_title": (
            "⚙️ <b>{channel}</b> — channel settings\n\n"
            "Tone of voice, AI analysis and disconnecting live here."
        ),
        "cq_ch_btn_tone": "🎨 Tone",
        "cq_ch_btn_voice": "🎙 Channel voice analysis",
        "cq_ch_btn_delete": "🗑 Disconnect channel",
        "cq_ch_stats_empty": (
            "📊 <b>{channel}</b>\n\n"
            "No statistics for this channel yet — schedule your first post."
        ),
        "cq_ch_not_found": (
            "⚠️ Channel not found or it does not belong to you.\n"
            "Refresh the list and try again."
        ),
        "cq_ch_post_intro": (
            "✍️ Send the post text or media for <b>{channel}</b>.\n\n"
            "<i>Text, photo, video, document or album — all are accepted.</i>"
        ),
        "cq_sch_title": "📅 <b>Scheduled</b> — {count} post(s):",
        "cq_sch_title_range": (
            "📅 <b>Scheduled</b> — {count} post(s) ({start}-{end}):"
        ),
        "cq_sch_channel_title": (
            "📅 <b>Scheduled</b> — 📢 {channel} ({count} post(s)):"
        ),
        "cq_sch_empty": (
            "📅 <b>Scheduled</b>\n\n"
            "No scheduled posts yet.\n"
            "Create a new post and set its publishing time."
        ),
        "cq_sch_channel_empty": (
            "📅 <b>Scheduled</b> — 📢 {channel}\n\n"
            "No scheduled posts for this channel."
        ),
        "cq_sch_btn_edit": "✏️ Edit",
        "cq_sch_btn_time": "⏰ Change time",
        "cq_sch_btn_delete": "🗑 Delete",
        "cq_sch_deleted_alert": "🗑 Post removed from the schedule.",
        "cq_sch_not_found": "⚠️ Post not found — it was already published or deleted.",
    },
}

#: Barcha kalitlar (paritet auditi va testlar uchun yagona ro'yxat).
CHANNELS_QUEUE_KEYS = tuple(sorted(CHANNELS_QUEUE_I18N["uz"].keys()))

#: Kanal boshqaruv ekranidagi 5 ta amal tugmasi — SPEKS tartibida.
CHANNEL_PANEL_BUTTON_KEYS = (
    "cq_ch_btn_create_post",
    "cq_ch_btn_scheduled",
    "cq_ch_btn_stats",
    "cq_ch_btn_settings",
    "cq_ch_btn_back",
)

#: Rejalashtirilgan postning 3 ta amali — SPEKS tartibida.
SCHEDULED_ACTION_KEYS = (
    "cq_sch_btn_edit",
    "cq_sch_btn_time",
    "cq_sch_btn_delete",
)


def channels_queue_t(key: str, lang: str = "uz", **kwargs) -> str:
    """📢 Kanallarim / 📅 Rejalashtirilgan matnini qaytaradi (uz / ru / en).

    Mantiq ``content_menu_t`` bilan bir xil: kalit bu modulda bo'lmasa
    asosiy repo lug'atiga (``safe_t``) tushadi — shu sababli umumiy
    ``ch_*`` / ``queue_*`` kalitlari ham shu funksiya orqali ishlaydi va
    handlerlar bitta i18n kirish nuqtasidan foydalanadi.
    """
    code = normalize_lang(lang)
    table = CHANNELS_QUEUE_I18N.get(code) or {}
    text = table.get(key)
    if text is None:
        text = (CHANNELS_QUEUE_I18N.get("uz") or {}).get(key)
    if text is None:
        return safe_t(key, code, **kwargs)
    try:
        return text.format(**kwargs) if kwargs else text
    except Exception:  # pragma: no cover - format himoyasi
        return text


def channels_queue_parity_report(langs=("uz", "ru", "en")) -> dict:
    """UZ ↔ RU ↔ EN kalit va format-argument pariteti hisoboti.

    ``content_menu_parity_report`` bilan bir xil struktura qaytaradi:
    ``{"keys", "missing", "extra", "format_mismatch", "empty", "in_sync"}``.
    """
    from locales.translations import format_args

    base = CHANNELS_QUEUE_I18N.get("uz") or {}
    base_keys = set(base)
    missing, extra, fmt_mismatch, empty = {}, {}, {}, []
    for lang in langs:
        if lang == "uz":
            continue
        table = CHANNELS_QUEUE_I18N.get(lang) or {}
        lang_keys = set(table)
        missing[lang] = sorted(base_keys - lang_keys)
        extra[lang] = sorted(lang_keys - base_keys)
        for key in base_keys & lang_keys:
            if format_args(base[key]) != format_args(table[key]):
                fmt_mismatch.setdefault(
                    key, {"uz": format_args(base[key]), lang: format_args(table[key])}
                )
    for lang in langs:
        table = CHANNELS_QUEUE_I18N.get(lang) or {}
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
