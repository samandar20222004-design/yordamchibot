import unicodedata
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from locales.translations import get_text

# Telegram tugma matni bo'sh bo'lishi mumkin emas (BadRequest) va juda uzun
# nom tugmani buzadi — shuning uchun barcha yorliqlar shu yerdan o'tkaziladi.
BUTTON_LABEL_MAX = 40


def btn_label(value, fallback: str = "Kanal", max_length: int = BUTTON_LABEL_MAX) -> str:
    """Tugma uchun xavfsiz yorliq: bo'sh/None bo'lsa fallback, uzun bo'lsa kesiladi."""
    text = str(value or "").strip()
    if not text or text.lower() in ("none", "null"):
        text = fallback
    if len(text) > max_length:
        text = f"{text[:max_length - 1]}…"
    return text


def get_close_keyboard() -> InlineKeyboardMarkup:
    """Inline oynani yopish uchun universal tugma."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Yopish", callback_data="close_msg")]])


def get_referral_share_keyboard(referral_link: str) -> InlineKeyboardMarkup:
    share_text = "Salom! Ushbu bot orqali Telegram kanallaringizga postlarni avtomatik va qulay rejalashtiring:"
    # Ikkala query-parametrni ham encode qilamiz: bo'sh joy, apostrof va
    # maxsus belgilar Telegram share URL'ini buzib qo'ymasligi kerak.
    share_url = (
        "https://t.me/share/url?"
        f"url={quote(referral_link, safe='')}&text={quote(share_text, safe='')}"
    )
    return InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Do'stlarga ulashish", url=share_url)]])

def unpack_sponsor(sponsor):
    """Sponsor ma'lumotlarini tuple yoki dict'dan xavfsiz ajratib beradi."""
    if isinstance(sponsor, dict):
        return (
            sponsor.get("id"),
            sponsor.get("channel_id"),
            sponsor.get("title") or sponsor.get("channel_title") or "Kanal",
            sponsor.get("username", ""),
            sponsor.get("invite_link") or sponsor.get("channel_url") or "",
        )
    if isinstance(sponsor, (list, tuple)):
        if len(sponsor) == 4:
            s_id, ch_id, ch_title, ch_url = sponsor
            return (s_id, ch_id, ch_title, "", ch_url)
        elif len(sponsor) >= 5:
            s_id, ch_id, ch_title, username, invite_link = sponsor[:5]
            ch_url = invite_link or (f"https://t.me/{username}" if username else "")
            return (s_id, ch_id, ch_title, username, ch_url)
    return (0, "", "Kanal", "", "")


def get_subscription_check_keyboard(unsubscribed_channels: list) -> InlineKeyboardMarkup:
    keyboard = []
    for sponsor in (unsubscribed_channels or []):
        s_id, ch_id, ch_title, username, ch_url = unpack_sponsor(sponsor)
        url = ch_url or (f"https://t.me/{username}" if username else "")
        keyboard.append([
            InlineKeyboardButton(f"➕ {btn_label(ch_title, 'Homiy kanal')}", url=url)
        ])
    keyboard.append([InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_sub_status")])
    return InlineKeyboardMarkup(keyboard)

def get_cache_actions_keyboard() -> InlineKeyboardMarkup:
    """DB/kesh holati oynasi uchun tugmalar."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Keshlarni tozalash", callback_data="cache_clear")],
        [InlineKeyboardButton("❌ Yopish", callback_data="close_msg")],
    ])


def get_sponsors_delete_keyboard(sponsors: list) -> InlineKeyboardMarkup:
    keyboard = []
    for sponsor in (sponsors or []):
        s_id, ch_id, ch_title, username, ch_url = unpack_sponsor(sponsor)
        label = btn_label(ch_title, "Homiy kanal", max_length=28)
        keyboard.append([
            InlineKeyboardButton(f"❌ {label} (O'chirish)", callback_data=f"del_sponsor:{s_id}")
        ])
    # Ro'yxat oynasini yopish tugmasi — admin ekranda keraksiz xabar qolib ketmasligi uchun
    keyboard.append([InlineKeyboardButton("❌ Yopish", callback_data="close_msg")])
    return InlineKeyboardMarkup(keyboard)


def get_admin_sponsors_keyboard(sponsors: list) -> InlineKeyboardMarkup:
    """Admin panel: Majburiy obuna kanallari boshqaruv klaviaturasi."""
    keyboard = []
    for sponsor in (sponsors or []):
        s_id, ch_id, ch_title, username, ch_url = unpack_sponsor(sponsor)
        label = btn_label(ch_title, "Kanal", max_length=24)
        keyboard.append([
            InlineKeyboardButton(f"🗑 {label} (O'chirish)", callback_data=f"del_sponsor:{s_id}")
        ])
    keyboard.append([
        InlineKeyboardButton("➕ Yangi kanal qo'shish", callback_data="adm_add_sponsor")
    ])
    keyboard.append([
        InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_back"),
        InlineKeyboardButton("❌ Yopish", callback_data="close_msg"),
    ])
    return InlineKeyboardMarkup(keyboard)


def get_ad_hub_keyboard(channel_total: int = 0, channel_active: int = 0,
                        reply_total: int = 0, reply_active: int = 0,
                        auto_status: bool = False, auto_interval: int = 4,
                        channel_interval: int = 3,
                        channel_status: bool = True,
                        sponsors_count: int = 0) -> InlineKeyboardMarkup:
    """Admin panel: reklama boshqaruvi — FAQAT 3 ta asosiy bo'lim.

    Har bir bo'lim o'z ichiga oladi: <b>matn</b> (reklama puli),
    <b>oraliq</b> (har nechanchi post/so'rovda), <b>tugma</b> va
    <b>yoqish/o'chirish</b>.

    1) 📢 Majburiy obuna (Sponsor kanallar)      → ``adm_sponsors``
    2) 🤖 3-5 ta javobda chiqadigan reklama      → ``adp:reply:*`` + ``adm_ad_toggle``
    3) 📢 Kanal postlariga reklama qo'shish      → ``adp:channel:*`` + ``adm_channel_ad_toggle``

    Bir-biriga o'xshash/eskirgan tugmalar («✏️ Eski javob matni»,
    ``adm_ad_set_interval`` va ``adm_ad_int:*`` dublikat oraliqlari)
    olib tashlangan — oraliq endi faqat o'z bo'limida sozlanadi.
    """
    reply_status = "✅ Yoqilgan" if auto_status else "❌ O'chirilgan"
    ch_status = "✅ Yoqilgan" if channel_status else "❌ O'chirilgan"
    keyboard = [
        # --- 1) Majburiy obuna ---
        [InlineKeyboardButton(f"📢 Majburiy obuna ({sponsors_count} ta kanal)",
                              callback_data="adm_sponsors")],
        # --- 2) Bot javoblari reklamasi ---
        [InlineKeyboardButton(f"🤖 Javoblar reklamasi: matn ({reply_active}/{reply_total})",
                              callback_data="adp:reply:back")],
        [
            InlineKeyboardButton(f"⏱ Oraliq: har {auto_interval} javob",
                                 callback_data="adp:reply:iv"),
            InlineKeyboardButton(f"🔘 {reply_status}", callback_data="adm_ad_toggle"),
        ],
        # --- 3) Kanal postlari reklamasi ---
        [InlineKeyboardButton(f"📢 Kanal posti reklamasi: matn ({channel_active}/{channel_total})",
                              callback_data="adp:channel:back")],
        [
            InlineKeyboardButton(f"⏱ Oraliq: har {channel_interval}-post",
                                 callback_data="adp:channel:iv"),
            InlineKeyboardButton(f"🔘 {ch_status}", callback_data="adm_channel_ad_toggle"),
        ],
        [
            InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_back"),
            InlineKeyboardButton("❌ Bekor qilish", callback_data="adm_cancel"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_hub_back_keyboard() -> InlineKeyboardMarkup:
    """Reklama hub'iga qaytish + bekor qilish (matn kutish ekranlari uchun)."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🎯 Markazga", callback_data="adm_adhub"),
        InlineKeyboardButton("❌ Bekor qilish", callback_data="adm_cancel"),
    ]])


def get_admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    """Admin panel inline keyboard — ixchamlashtirilgan dashboard layout.

    Faqat 6 ta asosiy tugma + Yopish qoladi:
        [📊 To'liq statistika]      [📢 Ommaviy xabar]
        [🎯 Reklama markazi]         [📋 Kanallar ro'yxati]
        [🎁 Promo-kod yaratish]     [⭐ PRO obuna berish]
        [❌ Yopish]

    "🛠 Tizim sozlamalari" panel dan butunlay olib tashlangan, "📢 Majburiy
    obuna" esa endi mustaqil tugma emas — "🎯 Reklama markazi" (``adm_adhub``)
    hub ichidagi 1-bo'lim sifatida ko'rsatiladi (``_ad_hub_render``).
    """
    keyboard = [
        [
            InlineKeyboardButton("📊 To'liq statistika", callback_data="adm_stats"),
            InlineKeyboardButton("📢 Ommaviy xabar", callback_data="adm_broadcast"),
        ],
        [
            InlineKeyboardButton("🎯 Reklama markazi", callback_data="adm_adhub"),
            InlineKeyboardButton("📋 Kanallar ro'yxati", callback_data="adm_channels"),
        ],
        [
            InlineKeyboardButton("🎁 Promo-kod yaratish", callback_data="adm_promo"),
            InlineKeyboardButton("⭐️ PRO obuna berish", callback_data="adm_grant_pro"),
        ],
        [InlineKeyboardButton("❌ Yopish", callback_data="close_msg")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_back_keyboard(cancel: bool = True) -> InlineKeyboardMarkup:
    """Admin ichki bo'limlarida Orqaga + Bekor qilish tugmalari.

    ``adm_cancel`` — jarayonni (FSM holatini) to'liq bekor qiladi va admin
    panelga qaytaradi. Shu sababli har bir tahrirlash ekranida mavjud.
    """
    row = [InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_back")]
    if cancel:
        row.append(InlineKeyboardButton("❌ Bekor qilish", callback_data="adm_cancel"))
    else:
        row.append(InlineKeyboardButton("❌ Yopish", callback_data="close_msg"))
    return InlineKeyboardMarkup([row])


# ============================================================
# AVTOMATIK REKLAMA ROTATSIYA (ad_pool) TUGMALARI
# ============================================================
def get_ad_pool_menu_keyboard(scope: str, ads: list = None,
                              interval: int = None) -> InlineKeyboardMarkup:
    """Reklama rotatsiya puli boshqaruv menyusi (scope: 'channel' | 'reply').

    ``ads`` berilsa har bir reklama uchun alohida "tahrirlash" tugmasi va
    holat belgisi (🟢/🔴) chiqadi. ``interval`` faqat kanal postlari uchun —
    reklama har nechanchi postda chiqishini ko'rsatadi.
    """
    keyboard = []
    for ad in (ads or []):
        ad_id = ad.get("id") if isinstance(ad, dict) else ad[0]
        ad_text = ad.get("text") if isinstance(ad, dict) else ad[1]
        is_active = ad.get("is_active", True) if isinstance(ad, dict) else True
        badge = "🟢" if is_active else "🔴"
        label = btn_label(ad_text, "Reklama", max_length=24)
        keyboard.append([
            InlineKeyboardButton(f"{badge} {label}", callback_data=f"adp:{scope}:e:{ad_id}")
        ])

    keyboard.append([InlineKeyboardButton("➕ Yangi reklama qo'shish", callback_data=f"adp:{scope}:add")])
    # Oraliq har ikkala bo'limda ham shu yerdan sozlanadi (yagona joy).
    if scope == "channel":
        label = (
            f"⏱ Reklama oralig'i: har {interval}-post"
            if interval else "⏱ Reklama oralig'ini sozlash"
        )
    else:
        label = (
            f"⏱ Reklama oralig'i: har {interval} javob"
            if interval else "⏱ Reklama oralig'ini sozlash"
        )
    keyboard.append([InlineKeyboardButton(label, callback_data=f"adp:{scope}:iv")])
    keyboard.append([
        InlineKeyboardButton("🧹 Hammasini tozalash", callback_data=f"adp:{scope}:clear"),
        InlineKeyboardButton("ℹ️ Rotatsiya haqida", callback_data=f"adp:{scope}:info"),
    ])
    # Barcha reklama ekranlari endi yagona hub ostida ishlaydi: "Orqaga"
    # dashboard'ga emas, Reklama markaziga qaytadi (bitta yagona oqim).
    keyboard.append([
        InlineKeyboardButton("🎯 Markazga", callback_data="adm_adhub"),
        InlineKeyboardButton("❌ Bekor qilish", callback_data="adm_cancel"),
    ])
    return InlineKeyboardMarkup(keyboard)


def get_ad_edit_keyboard(ad: dict, scope: str) -> InlineKeyboardMarkup:
    """Bitta reklamani to'liq tahrirlash menyusi.

    Matn, inline URL tugma, faollik holati (Toggle Active/Inactive) va
    o'chirish tugmalari.
    """
    ad = ad or {}
    ad_id = ad.get("id", 0)
    is_active = bool(ad.get("is_active", True))
    has_button = bool((ad.get("button_text") or "").strip() and (ad.get("button_url") or "").strip())
    toggle_label = "🔴 O'chirish (Inactive)" if is_active else "🟢 Faollashtirish (Active)"
    button_label = "🔗 Tugmani tahrirlash" if has_button else "🔗 Inline tugma qo'shish"

    keyboard = [
        [InlineKeyboardButton("✏️ Matnni tahrirlash", callback_data=f"adp:{scope}:et:{ad_id}")],
        [InlineKeyboardButton(button_label, callback_data=f"adp:{scope}:eb:{ad_id}")],
    ]
    if has_button:
        keyboard.append([
            InlineKeyboardButton("🚫 Tugmani olib tashlash", callback_data=f"adp:{scope}:bx:{ad_id}")
        ])
    keyboard.append([InlineKeyboardButton(toggle_label, callback_data=f"adp:{scope}:tg:{ad_id}")])
    keyboard.append([InlineKeyboardButton("🗑 Reklamani o'chirish", callback_data=f"adp:{scope}:rm:{ad_id}")])
    keyboard.append([
        InlineKeyboardButton("⬅️ Menyuga", callback_data=f"adp:{scope}:back"),
        InlineKeyboardButton("❌ Bekor qilish", callback_data="adm_cancel"),
    ])
    return InlineKeyboardMarkup(keyboard)


def get_ad_interval_keyboard(scope: str = "channel", current: int = None) -> InlineKeyboardMarkup:
    """Reklama oralig'ini tanlash: har 3-, 4- yoki 5-postda (yoki qo'lda)."""
    row = []
    for value in (3, 4, 5):
        mark = "✅ " if current == value else ""
        row.append(InlineKeyboardButton(f"{mark}Har {value}-post", callback_data=f"adp:{scope}:iv:{value}"))
    return InlineKeyboardMarkup([
        row,
        [
            InlineKeyboardButton("⬅️ Menyuga", callback_data=f"adp:{scope}:back"),
            InlineKeyboardButton("❌ Bekor qilish", callback_data="adm_cancel"),
        ],
    ])


def get_ad_pool_delete_keyboard(ads: list, scope: str) -> InlineKeyboardMarkup:
    """Har bir reklamani o'chirish tugmasi bilan ko'rsatadi."""
    keyboard = []
    for ad in (ads or []):
        if isinstance(ad, dict):
            ad_id, text = ad.get("id"), ad.get("text")
        else:
            ad_id, text = ad[0], ad[1]
        label = btn_label(text, "Reklama", max_length=28)
        keyboard.append([
            InlineKeyboardButton(f"❌ {label}", callback_data=f"adp:{scope}:rm:{ad_id}")
        ])
    keyboard.append([
        InlineKeyboardButton("⬅️ Orqaga", callback_data=f"adp:{scope}:back"),
        InlineKeyboardButton("❌ Bekor qilish", callback_data="adm_cancel"),
    ])
    return InlineKeyboardMarkup(keyboard)


def get_ad_pool_back_keyboard(scope: str) -> InlineKeyboardMarkup:
    """Qo'shish/ma'lumot ekranidan reklama menyusiga qaytish."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Menyuga", callback_data=f"adp:{scope}:back"),
            InlineKeyboardButton("❌ Bekor qilish", callback_data="adm_cancel"),
        ],
    ])


# AI Studio — Tone of Voice (AI post uslublari) tarjima kalitlari.
# Har bir uslub translations.py dagi kalitga bog'lanadi (i18n uchun).
AI_TONE_KEYS = {
    "formal": "ai_tone_formal",
    "friendly": "ai_tone_friendly",
    "concise": "ai_tone_concise",
    "engaging": "ai_tone_engaging",
}


def get_ai_studio_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """AI Studio sub-menu inline keyboard.

    "🖼 Rasmdan post yaratish" — rasmni Gemini vision bilan tahlil qilib,
    professional Telegram SMM posti tayyorlanadi (Photo-to-Post).
    "🔍 AI Post auditi" — foydalanuvchi tayyor postini AI'ga tahlil qildiradi
    (imlo, jozibadorlik, CTA, 1-10 baho).

    Barcha yorliqlar foydalanuvchi tiliga (lang) mos tarjima qilinadi.
    """
    keyboard = [
        [
            InlineKeyboardButton(get_text("ai_studio_post", lang), callback_data="studio_ai_post"),
            InlineKeyboardButton(get_text("ai_studio_photo", lang), callback_data="studio_ai_photo"),
        ],
        [
            InlineKeyboardButton(get_text("ai_studio_extract", lang), callback_data="studio_extract"),
            InlineKeyboardButton(get_text("ai_studio_audit", lang), callback_data="studio_ai_audit"),
        ],
        [
            InlineKeyboardButton(get_text("ai_studio_content_plan", lang), callback_data="studio_content_plan"),
        ],
        [
            InlineKeyboardButton(get_text("ai_btn_main_menu", lang), callback_data="studio_close"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_ai_photo_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """🖼 Vision (Photo-to-Post) natijasi uchun inline tugmalar.

    [Kanalga rejalashtirish] [Qayta yozish] [Tahrirlash] + doimiy navigatsiya.
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text("ai_photo_schedule", lang), callback_data="photo_schedule")],
        [InlineKeyboardButton(get_text("ai_photo_rewrite", lang), callback_data="photo_rewrite")],
        [InlineKeyboardButton(get_text("ai_photo_edit", lang), callback_data="photo_edit")],
        [
            InlineKeyboardButton(get_text("ai_btn_back", lang), callback_data="ai_back_to_menu"),
            InlineKeyboardButton(get_text("ai_btn_close", lang), callback_data="ai_close"),
        ],
    ])


# ============================================================
# AI STUDIO — DOIMIY INLINE NAVIGATSIYA
# ============================================================
# Barcha AI Studio ekranlarida pasda shu ikki tugma turadi: xabar hech qachon
# "yo'qolib" ketmaydi, foydalanuvchi har doim menyuga qaytishi yoki sessiyani
# yopishi mumkin.
def get_ai_back_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """AI Studio ichki ekranlari: ⬅️ Orqaga + ❌ Bekor qilish."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(get_text("ai_btn_back", lang), callback_data="ai_back_to_menu"),
        InlineKeyboardButton(get_text("ai_btn_close", lang), callback_data="ai_close"),
    ]])


def get_ai_tone_keyboard(selected: str = None, lang: str = "uz") -> InlineKeyboardMarkup:
    """AI post uslubini tanlash — tanlangan uslub ✅ bilan belgilanadi."""
    buttons = []
    for key, tone_key in AI_TONE_KEYS.items():
        mark = " ✅" if key == selected else ""
        buttons.append(InlineKeyboardButton(f"{get_text(tone_key, lang)}{mark}", callback_data=f"ai_tone:{key}"))
    keyboard = [
        buttons[:2],
        buttons[2:],
        [InlineKeyboardButton(get_text("ai_tone_schedule", lang), callback_data="ai_studio_sched")],
        [
            InlineKeyboardButton(get_text("ai_btn_back", lang), callback_data="ai_back_to_menu"),
            InlineKeyboardButton(get_text("ai_btn_close", lang), callback_data="ai_close"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_ai_confirm_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """AI post tasdiqlash klaviaturasi (Kanalga rejalashtirish / Tahrirlash / Bekor).

    „Yana post yaratish“ oqimi uchun ishlatiladi; tilga mos tarjima qilinadi.
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text("ai_confirm_schedule", lang), callback_data="ai_post_schedule")],
        [InlineKeyboardButton(get_text("ai_confirm_edit", lang), callback_data="ai_post_retry")],
        [InlineKeyboardButton(get_text("ai_btn_close", lang), callback_data="ai_post_cancel")],
    ])


def render_channels_list(channels: list, lang: str = "uz") -> InlineKeyboardMarkup:
    keyboard = []
    for ch in channels:
        ch_id, ch_title = ch[:2]
        tone = ch[2] if len(ch) > 2 else "friendly"
        tone_emoji = {"formal": "👔", "friendly": "😊", "concise": "⚡️", "engaging": "🎉"}.get(tone, "😊")
        keyboard.append([
            InlineKeyboardButton(f"📢 {btn_label(ch_title)}", callback_data="noop"),
            InlineKeyboardButton(get_text("cab_remove_channel", lang), callback_data=f"remove_channel:{ch_id}"),
        ])
        keyboard.append([
            InlineKeyboardButton(f"{tone_emoji} {get_text('cab_tone', lang)}", callback_data=f"tone_menu:{ch_id}"),
        ])
    # "Qo'shish bor, lekin bekor qilish/chiqish yo'q" kamchiligini tuzatish:
    # ro'yxat ostida yangi kanal ulash va oynani yopish tugmalari bo'ladi.
    keyboard.append([InlineKeyboardButton(get_text("cab_add_channel_alt", lang), callback_data="add_channel_start")])
    keyboard.append([InlineKeyboardButton(get_text("cab_close", lang), callback_data="close_msg")])
    return InlineKeyboardMarkup(keyboard)

def render_pending_list(posts: list, user_code: str) -> InlineKeyboardMarkup:
    keyboard = []
    for p in posts:
        pid, ch_title, p_type, s_time, p_num, r_type, r_day, r_time = p
        code_label = f"{user_code}-{p_num}" if p_num else f"#{pid}"
        # Har bir post uchun 2 qator tugma:
        # 1-qator: vaqt o'zgartirish, matn tahrirlash
        # 2-qator: tugma URL, reaksiya, bekor qilish
        keyboard.append([
            InlineKeyboardButton(f"🕒 {code_label} vaqt", callback_data=f"edit_time:{pid}"),
            InlineKeyboardButton(f"✏️ {code_label} matn", callback_data=f"edit_content:{pid}"),
        ])
        keyboard.append([
            InlineKeyboardButton(f"🔗 Tugma", callback_data=f"edit_btn:{pid}"),
            InlineKeyboardButton(f"👍 Reaksiya", callback_data=f"edit_react:{pid}"),
            InlineKeyboardButton(f"❌ Bekor", callback_data=f"cancel_post:{pid}"),
        ])
    # Ro'yxatni yangilash (amal bajargandan keyin holatni ko'rish) va yopish tugmalari
    keyboard.append([
        InlineKeyboardButton("🔄 Yangilash", callback_data="pending_refresh"),
        InlineKeyboardButton("❌ Yopish", callback_data="close_msg"),
    ])
    return InlineKeyboardMarkup(keyboard)


def get_cabinet_inline_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Kabinet & Sozlamalar asosiy menyusi — inline tugmalar (4x2 + til).

    ``lang`` foydalanuvchi tili (uz/ru). Tugma matni tarjima qilinadi,
    ``callback_data`` o'zgarishsiz qoladi (routing tilga bog'liq emas).
    """
    keyboard = [
        [
            InlineKeyboardButton(get_text("cab_my_channels", lang), callback_data="cab_channels"),
            InlineKeyboardButton(get_text("cab_analytics", lang), callback_data="cab_analytics"),
        ],
        [
            InlineKeyboardButton(get_text("cab_pending", lang), callback_data="cab_pending"),
            InlineKeyboardButton(get_text("cab_queue", lang), callback_data="cab_queue"),
        ],
        [
            InlineKeyboardButton(get_text("cab_balance", lang), callback_data="cab_balance"),
            InlineKeyboardButton(get_text("cab_btn_daily_bonus", lang), callback_data="cab_bonus"),
        ],
        [
            InlineKeyboardButton(get_text("cab_referral", lang), callback_data="cab_referral"),
            InlineKeyboardButton(get_text("cab_close", lang), callback_data="close_cabinet"),
        ],
        [
            InlineKeyboardButton(get_text("lang_button", lang), callback_data="cab_lang"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_language_keyboard() -> InlineKeyboardMarkup:
    """Til tanlash: O'zbekcha / Русский."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="cab_lang_uz"),
            InlineKeyboardButton("🇷🇺 Русский", callback_data="cab_lang_ru"),
        ],
        [
            InlineKeyboardButton("⬅️ Orqaga", callback_data="cab_main"),
        ],
    ])


def get_extras_inline_keyboard() -> InlineKeyboardMarkup:
    """⚙️ Qo'shimcha funksiyalar — inline menyu.

    Birinchi qator — ✨ Postga Tugma & Reaksiya qo'shish (Post Enhancer):
    tayyor postga 10 tagacha reaksiya va 10 tagacha URL tugma qo'shib,
    kanalga bir zumda yuborish. Konvertor o'z o'rnida saqlanadi.
    """
    keyboard = [
        [InlineKeyboardButton("✨ Postga Tugma & Reaksiya qo'shish",
                              callback_data="extra_enhancer")],
        [InlineKeyboardButton("🔤 Krill-Lotin konvertor", callback_data="extra_converter")],
        [InlineKeyboardButton("❌ Yopish", callback_data="extra_close")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# MULTI-SELECT REAKSIYALAR (TOGGLE)
# ============================================================
# Post yaratishda reaksiya tanlash uchun ruxsat etilgan emojilar.
REACTION_EMOJIS = ("👍", "❤️", "🔥", "👏", "🎉", "🤔")
# Eski postlar (reaction_emojis saqlanmagan) uchun standart to'plam.
DEFAULT_REACTION_EMOJIS = ("👍", "❤️", "🔥", "👏")

# ✨ Postga Tugma & Reaksiya qo'shish uchun kengaytirilgan havza (pool): 20 ta emoji.
# Foydalanuvchi shundan 10 tasigachanini tanlaydi yoki istalgan emojini
# xabar qilib yubora oladi (extract_emoji_tokens). REACTION_EMOJIS boshida
# turadi — eski oqimlar (npreact:) faqat 6 tasini ko'rsatishda davom etadi.
REACTION_POOL = REACTION_EMOJIS + (
    "😍", "🤩", "😮", "😂",
    "🙏", "💯", "✅", "⭐️",
    "👀", "💪", "🎯", "🤝",
    "😢", "👎",
)


# Callback prefikslari: kanal postidagi reaksiya hisoblagich "react:" bilan
# aralashmasligi uchun "npreact:" (new-post reaction) ishlatiladi.
CB_REACT_TOGGLE = "npreact:tgl:"
CB_REACT_DONE = "npreact:done"
CB_REACT_SKIP = "npreact:skip"


def strip_variation_selector(value: str) -> str:
    """Variation Selector (\ufe0f/\ufe0e) ni olib tashlaydi — emoji taqqoslash uchun.

    \u2764\ufe0f (VS16 bilan ❤️) va \u2764 (VS16 siz) bir xil reaksiya deb hisoblanadi.
    Emoji ro'yxatlarida takrorlanishni oldini olish uchun "kalit" sifatida ishlatiladi.
    """
    return (value or "").replace("\ufe0f", "").replace("\ufe0e", "")


# Eski nom (modul ichida ishlatiladi) — orqaga moslik uchun saqlanadi.
_strip_vs16 = strip_variation_selector


def normalize_reaction_emojis(value) -> list:
    """Saqlangan reaksiya to'plamini toza ro'yxatga aylantiradi.

    Kirish: ro'yxat/tuple yoki bo'sh joy bilan ajratilgan satr (DB'dagi ko'rinish).
    Chiqish: REACTION_EMOJIS tartibiga moslangan, takrorlarsiz ro'yxat.
    Noma'lum/bo'm-bo'sh qiymatlar uchun bo'sh ro'yxat qaytadi.

    DIQQAT: Bu funksiya FAQAT tugma bilan taklif qilinadigan kanonik
    (REACTION_EMOJIS) emojilarni taniydi — toggle klaviatura shu 6 emoji
    bilan ishlaydi. Foydalanuvchi QO'LDA kiritgan boshqa emojilar
    (😍, 💯, 🙏 ...) bu yerdan o'tmaydi; ular uchun
    ``normalize_custom_reaction_emojis`` ishlatiladi.
    """
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_items = [str(v) for v in value]
    else:
        raw_items = str(value).split()
    selected = {_strip_vs16(v) for v in raw_items if v and v.strip()}
    # Tanlangan emojilarni doimiy (kanonik) tartibda qaytaramiz
    return [e for e in REACTION_EMOJIS if _strip_vs16(e) in selected]


# Foydalanuvchi qo'lda kiritishi mumkin bo'lgan reaksiya emojilari uchun
# yuqori chegara (Telegram bitta xabarga 100 tagacha inline tugma ruxsat
# beradi, lekin bir qatorga 8 tadan ko'p emoji sig'dirish noqulay).
CUSTOM_REACTION_MAX = 10

# Emoji bo'lishi mumkin bo'lmagan belgilar (harflar, raqamlar, tinish).
_EMOJI_TEXT_CATEGORIES = frozenset(("L", "N", "P", "Z", "C"))


def is_emoji_token(token: str) -> bool:
    """Bitta token haqiqiy emoji ekanini tekshiradi (harf/raqam/tinish emas).

    ZWJ (\\u200d), Variation Selector'lar va skin-tone modifier'lar
    (Cf/Mn/Sk kategoriyalari) ham ruxsat etiladi — tarkibiy emojilar
    (masalan 👨‍💻, 👍🏽) ham ishlaydi.
    """
    if not token:
        return False
    for ch in str(token):
        cat = unicodedata.category(ch)
        # Harf, raqam, tinish belgisi, bo'sh joy/boshqaruv — emoji emas
        if cat and cat[0] in _EMOJI_TEXT_CATEGORIES:
            return False
    return True


def normalize_custom_reaction_emojis(value, max_count: int = CUSTOM_REACTION_MAX) -> list:
    """Qo'lda kiritilgan reaksiya emojilarini saqlash uchun normallashtiradi.

    ``normalize_reaction_emojis``'dan farqi: kanonik ro'yxatga kirmaydigan
    emojilar (😍, 💯, 🙏, ⭐ ...) ham SAQLANIB QOLADI va kanal postida
    tugma sifatida chiqadi. Foydalanuvchi kiritgan TARTIB saqlanadi
    (kanonik emojilar boshida, qolganlari kiritish tartibida).

    Kirish: ro'yxat/tuple/set yoki bo'sh joy/vergul bilan ajratilgan satr.
    Chiqish: takrorlarsiz (Variation Selector hisobga olinmaydi), belgilangan
    sondan oshmaydigan emoji ro'yxati. Emoji bo'lmagan belgilar tashlanadi.
    """
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_items = [str(v) for v in value if v]
    else:
        import re as _re
        raw_items = [t for t in _re.split(r"[\s,;|/]+", str(value)) if t]

    result = []
    seen = set()
    # 1) Avval kanonik emojilar (doimiy tartibda) — eski xatti-harakat saqlanadi
    canonical = normalize_reaction_emojis(raw_items)
    for e in canonical:
        key = _strip_vs16(e)
        if key not in seen:
            seen.add(key)
            result.append(e)
    # 2) Qolgan (qo'lda kiritilgan) emojilar — kiritish tartibida
    for item in raw_items:
        if len(result) >= max_count:
            break
        key = _strip_vs16(item)
        if not key or key in seen:
            continue
        if not is_emoji_token(item):
            continue
        seen.add(key)
        result.append(item)
    return result[:max_count]


def build_reaction_button_rows(post_id: int, emojis: list,
                               per_row: int = 5, preview: bool = False) -> list:
    """Reaksiya emoji tugmalarini qatorlarga bo'lib beradi (scheduler/enhancer umumiy).

    - ``preview=True`` bo'lsa callback_data neytral (``enh:noop``) bo'ladi —
      tugma bosilganda hech narsa sodir bo'lmaydi (faqat ko'rinish).
    - Aks holda har tugma ``react:{post_id}:{emoji}`` hisoblagich callback'iga
      ega bo'ladi — bosilganda reaksiya sanaladi.
    - Emojilar ``per_row`` tadan qatorlarga joylanadi (bitta uzun qator
      Telegramda sig'masligi mumkin).
    """
    rows = []
    row = []
    for emoji in (emojis or []):
        if not emoji:
            continue
        if preview or not post_id:
            row.append(InlineKeyboardButton(emoji, callback_data="enh:noop"))
        else:
            row.append(InlineKeyboardButton(emoji, callback_data=f"react:{post_id}:{emoji}"))
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def extract_emoji_tokens(text, max_count: int = 10) -> list:
    """Matndan faqat emoji token'larini ajratib oladi (reaksiya batch kiritishi).

    \"👍 ❤️ 🔥\" → ['👍', '❤️', '🔥']; aralash matndan ham faqat emojilar
    olinadi; takrorlanishlar olib tashlanadi; soni ``max_count`` bilan
    chegaralanadi. Harflar/so'zlar e'tiborga olinmaydi.
    """
    if not text:
        return []
    raw = str(text).replace(",", " ").replace(";", " ").strip()
    out = []
    for token in raw.split():
        # Bitta emoji (ZWJ/terkibiy ketma-ketliklar ham) 8 belgidan oshmaydi.
        if not token or len(token) > 8:
            continue
        is_emoji = True
        for ch in token:
            if _strip_vs16(ch) and unicodedata.category(ch) not in ("So", "Sm", "Sk", "Mn", "Mc", "Me", "Cf"):
                is_emoji = False
                break
        if is_emoji and token not in out:
            out.append(token)
        if len(out) >= max_count:
            break
    return out


def get_reaction_toggle_keyboard(selected=None) -> InlineKeyboardMarkup:
    """Multi-select reaksiya klaviaturasi — emoji bosilganda ✅ belgilanadi/olib tashlanadi.

    Keyingi qadamga faqat "[➡️ Davom etish]" yoki "[⏭ Reaksiyasiz o'tish]"
    tugmasi bosilganda o'tiladi.
    """
    sel = set(normalize_reaction_emojis(selected)) if selected else set()
    emoji_row_1 = []
    emoji_row_2 = []
    for idx, emoji in enumerate(REACTION_EMOJIS):
        mark = "✅" if emoji in sel else ""
        button = InlineKeyboardButton(f"{emoji} {mark}".strip(), callback_data=f"{CB_REACT_TOGGLE}{emoji}")
        if idx < 3:
            emoji_row_1.append(button)
        else:
            emoji_row_2.append(button)

    count = len(sel)
    done_label = f"➡️ Davom etish ({count} ta)" if count else "➡️ Davom etish"
    keyboard = [
        emoji_row_1,
        emoji_row_2,
        [InlineKeyboardButton(done_label, callback_data=CB_REACT_DONE)],
        [InlineKeyboardButton("⏭ Reaksiyasiz o'tish", callback_data=CB_REACT_SKIP)],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_cabinet_back_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Kabinet ichki sahifalari — Orqaga + Yopish (uz/ru)."""
    keyboard = [
        [
            InlineKeyboardButton(get_text("btn_back", lang), callback_data="cab_main"),
            InlineKeyboardButton(get_text("cab_close", lang), callback_data="close_cabinet"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_channels_manage_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """📢 Mening kanallarim ekrani tugmalari — kanal qo'shish va o'chirish.

    ``add_channel_start`` — kanal ulash ConversationHandler'ini ISHGA
    TUSHIRADI (botni admin qilish → forward/ID yuborish oqimi).
    ``cab_channels_delete`` — o'chirish uchun kanal ro'yxatini ochadi
    (kanal bo'lmasa tushunarli xabar qaytadi).
    """
    keyboard = [
        [InlineKeyboardButton(get_text("cab_add_channel", lang), callback_data="add_channel_start")],
        [InlineKeyboardButton(get_text("cab_del_channel", lang), callback_data="cab_channels_delete")],
        [
            InlineKeyboardButton(get_text("btn_back", lang), callback_data="cab_main"),
            InlineKeyboardButton(get_text("cab_close", lang), callback_data="close_cabinet"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def no_channels_hint(lang: str = "uz") -> str:
    """Kanal ulanmaganida ko'rsatiladigan yo'naltiruvchi matn (uz/ru).

    Bir xil matn "Mening kanallarim" ekranida ham, kanal talab qilinadigan
    joylarda ham ishlatiladi.
    """
    return get_text("no_channels_hint", lang)


# Orqaga moslik: avvalgi importlar buzilmasligi uchun o'zbekcha matn saqlanadi.
NO_CHANNELS_HINT = no_channels_hint("uz")

