import unicodedata
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from locales.translations import get_text
from keyboards.callback_data import (  # noqa: F401 — re-export (eski importlar uchun)
    CALLBACK_DATA_MAX_BYTES,
    CB_CHANNEL_AUTOPILOT,
    CB_CHANNEL_BACK,
    CB_CHANNEL_BEST_TIME,
    CB_CHANNEL_DELETE,
    CB_CHANNEL_DNA,
    CB_CHANNEL_NEW_POST,
    CB_CHANNEL_OPEN,
    CB_CHANNEL_SCHEDULED,
    CB_CHANNEL_SETTINGS,
    CB_CHANNEL_SOURCES,
    CB_CHANNEL_STATS,
    CB_CHANNEL_TEMPLATES,
    CB_CHANNEL_VOICE,
    CB_SCHED_BTN_REACT,
    CB_SCHED_DELETE,
    CB_SCHED_EDIT,
    CB_SCHED_TIME,
    CB_POST_BTN,
    CB_POST_CANCEL,
    CB_POST_EDIT,
    CB_POST_REACT,
    CB_POST_TIME,
    CB_POST_VIEW,
    CB_REACTION,
    CB_REACT_DONE,
    CB_REACT_SKIP,
    CB_REACT_TOGGLE,
    CB_SPONSOR_DELETE,
    callback_byte_len,
    cb,
    is_callback_safe,
)

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


def get_close_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Inline oynani yopish uchun universal tugma (uz/ru)."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(get_text("pend_close_btn", lang), callback_data="close_msg")
    ]])


def get_referral_share_keyboard(referral_link: str, lang: str = "uz") -> InlineKeyboardMarkup:
    share_text = get_text("ref_share_text", lang)
    # Ikkala query-parametrni ham encode qilamiz: bo'sh joy, apostrof va
    # maxsus belgilar Telegram share URL'ini buzib qo'ymasligi kerak.
    share_url = (
        "https://t.me/share/url?"
        f"url={quote(referral_link, safe='')}&text={quote(share_text, safe='')}"
    )
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(get_text("btn_share_referral", lang), url=share_url)
    ]])

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


def get_subscription_check_keyboard(unsubscribed_channels: list, lang: str = "uz") -> InlineKeyboardMarkup:
    keyboard = []
    sponsor_fallback = get_text("sub_sponsor_fallback", lang)
    for sponsor in (unsubscribed_channels or []):
        s_id, ch_id, ch_title, username, ch_url = unpack_sponsor(sponsor)
        url = ch_url or (f"https://t.me/{username}" if username else "")
        keyboard.append([
            InlineKeyboardButton(f"➕ {btn_label(ch_title, sponsor_fallback)}", url=url)
        ])
    keyboard.append([
        InlineKeyboardButton(
            get_text("btn_check_subscription", lang), callback_data="check_sub_status"
        )
    ])
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
            InlineKeyboardButton(f"❌ {label} (O'chirish)", callback_data=cb(CB_SPONSOR_DELETE, s_id))
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
            InlineKeyboardButton(f"🗑 {label} (O'chirish)", callback_data=cb(CB_SPONSOR_DELETE, s_id))
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


# ============================================================
# 👑 ADMIN DASHBOARD — YAGONA INLINE PANEL (3-bosqich)
# ============================================================
# Layoutning YAGONA MANBASI: (yorliq, callback_data) qatorlari. Klaviatura
# shu registrdan quriladi — testlar ham, hujjat ham shu yerdan o'qiydi.
#
#     [📊 Bot statistikasi]   [📢 Ommaviy xabar]
#     [🎯 Reklama markazi]    [📋 Kanallar ro'yxati]
#     [📋 Barcha postlar]     [🎁 Promo-kod yaratish]
#     [⭐️ PRO berish]        [🏷 Post nishoni]
#     [⚙️ AI parametrlari]    [🗄️ DB / Kesh holati]
#     [🩺 Tizim monitoringi]  [❌ Yopish]
ADMIN_DASHBOARD_ROWS = (
    (("📊 Bot statistikasi", "adm_stats"),
     ("📢 Ommaviy xabar", "adm_broadcast")),
    (("🎯 Reklama markazi", "adm_adhub"),
     ("📋 Kanallar ro'yxati", "adm_channels")),
    (("📋 Barcha postlar", "adm_posts"),
     ("🎁 Promo-kod yaratish", "adm_promo")),
    (("⭐️ PRO berish", "adm_grant_pro"),
     ("🏷 Post nishoni", "adm_tag")),
    (("⚙️ AI parametrlari", "adm_ai"),
     ("🗄️ DB / Kesh holati", "adm_dbcache")),
    (("🩺 Tizim monitoringi", "adm_health"),
     ("❌ Yopish", "close_msg")),
)

#: Dashboard'dagi barcha callback'lar (tartib saqlanadi, tekshiruvlar uchun).
ADMIN_DASHBOARD_CALLBACKS = tuple(
    cb for row in ADMIN_DASHBOARD_ROWS for _label, cb in row
)


def get_admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    """👑 Admin panel — YAGONA INLINE MARKAZ (3-bosqich).

    Pastdagi 10 talik oq reply-klaviatura BUTUNLAY olib tashlandi: endi
    admin panel ochilganda faqat shu INLINE panel chiziladi (reply
    klaviatura o'rnida asosiy menyu qoladi, hech qanday admin tugmasi
    qayta chizilmaydi).

        [📊 Bot statistikasi]   [📢 Ommaviy xabar]      ← /stats, /admin_stats
        [🎯 Reklama markazi]    [📋 Kanallar ro'yxati]  ← /channels boshqaruvi
        [📋 Barcha postlar]     [🎁 Promo-kod yaratish] ← /allposts
        [⭐️ PRO berish]        [🏷 Post nishoni]       ← /grant_pro
        [⚙️ AI parametrlari]    [🗄️ DB / Kesh holati]  ← /ai parametrlari
        [🩺 Tizim monitoringi]  [❌ Yopish]             ← /health (+ Audit|Rollar
                                                          shu ekran ichida)

    Har bir tugma ``admin_dashboard_callback`` orqali server-side RBAC bilan
    (fail-closed) ishlaydi. Eski reply-tugmalar matnlari va /buyruqlar esa
    routing ALIAS'i sifatida saqlanadi — lekin ular hech qanday klaviaturada
    CHIZILMAYDI (``keyboards.default.ADMIN_LEGACY_REPLY_TEXTS``).
    """
    keyboard = [
        [InlineKeyboardButton(label, callback_data=callback)
         for label, callback in row]
        for row in ADMIN_DASHBOARD_ROWS
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_monitoring_keyboard() -> InlineKeyboardMarkup:
    """🩺 Tizim monitoringi ekrani tugmalari (``adm_health``).

    ``📜 Audit | 👥 Rollar`` (``adm_audit_roles``) dashboard'dan shu ekranga
    ko'chirildi: monitoring = tizim holati + oxirgi admin harakatlari. Tugma
    o'z handlerga ega va faqat OWNER/SUPER_ADMIN uchun ochiladi (fail-closed).
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Audit | 👥 Rollar", callback_data="adm_audit_roles")],
        [
            InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_back"),
            InlineKeyboardButton("❌ Yopish", callback_data="close_msg"),
        ],
    ])


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
            InlineKeyboardButton(f"{badge} {label}", callback_data=cb(f"adp:{scope}:e:{ad_id}"))
        ])

    keyboard.append([InlineKeyboardButton("➕ Yangi reklama qo'shish", callback_data=cb(f"adp:{scope}:add"))])
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
    keyboard.append([InlineKeyboardButton(label, callback_data=cb(f"adp:{scope}:iv"))])
    keyboard.append([
        InlineKeyboardButton("🧹 Hammasini tozalash", callback_data=cb(f"adp:{scope}:clear")),
        InlineKeyboardButton("ℹ️ Rotatsiya haqida", callback_data=cb(f"adp:{scope}:info")),
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
        [InlineKeyboardButton("✏️ Matnni tahrirlash", callback_data=cb(f"adp:{scope}:et:{ad_id}"))],
        [InlineKeyboardButton(button_label, callback_data=cb(f"adp:{scope}:eb:{ad_id}"))],
    ]
    if has_button:
        keyboard.append([
            InlineKeyboardButton("🚫 Tugmani olib tashlash", callback_data=cb(f"adp:{scope}:bx:{ad_id}"))
        ])
    keyboard.append([InlineKeyboardButton(toggle_label, callback_data=cb(f"adp:{scope}:tg:{ad_id}"))])
    keyboard.append([InlineKeyboardButton("🗑 Reklamani o'chirish", callback_data=cb(f"adp:{scope}:rm:{ad_id}"))])
    keyboard.append([
        InlineKeyboardButton("⬅️ Menyuga", callback_data=cb(f"adp:{scope}:back")),
        InlineKeyboardButton("❌ Bekor qilish", callback_data="adm_cancel"),
    ])
    return InlineKeyboardMarkup(keyboard)


def get_ad_interval_keyboard(scope: str = "channel", current: int = None) -> InlineKeyboardMarkup:
    """Reklama oralig'ini tanlash: har 3-, 4- yoki 5-postda (yoki qo'lda)."""
    row = []
    for value in (3, 4, 5):
        mark = "✅ " if current == value else ""
        row.append(InlineKeyboardButton(f"{mark}Har {value}-post", callback_data=cb(f"adp:{scope}:iv:{value}")))
    return InlineKeyboardMarkup([
        row,
        [
            InlineKeyboardButton("⬅️ Menyuga", callback_data=cb(f"adp:{scope}:back")),
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
            InlineKeyboardButton(f"❌ {label}", callback_data=cb(f"adp:{scope}:rm:{ad_id}"))
        ])
    keyboard.append([
        InlineKeyboardButton("⬅️ Orqaga", callback_data=cb(f"adp:{scope}:back")),
        InlineKeyboardButton("❌ Bekor qilish", callback_data="adm_cancel"),
    ])
    return InlineKeyboardMarkup(keyboard)


def get_ad_pool_back_keyboard(scope: str) -> InlineKeyboardMarkup:
    """Qo'shish/ma'lumot ekranidan reklama menyusiga qaytish."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Menyuga", callback_data=cb(f"adp:{scope}:back")),
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


def _calendar_hub_label(lang: str = "uz") -> str:
    """🤖 AI Yordamchi submenu'sidagi [🧠 Kontent reja] yorlig'i (uz/ru/en).

    Yorliq ``translations/content_calendar.py`` dagi ``hub_button`` kalitidan
    olinadi (yagona i18n manbasi). Modul topilmasa — eski ``ai_studio_content_plan``
    yorlig'iga xavfsiz qaytamiz (klaviatura hech qachon bo'sh tugma bilan
    yiqilmaydi).
    """
    try:
        from translations.content_calendar import calendar_t
        return calendar_t("hub_button", lang)
    except Exception:  # pragma: no cover - i18n moduli yo'q bo'lsa
        return get_text("ai_studio_content_plan", lang)


def _content_back_label(lang: str = "uz") -> str:
    """🧭 [◀️ Orqaga] yorlig'i — Kontent yaratish submenyusi bilan bir xil.

    Yorliq ``translations/content_menu.py`` dagi ``cm_btn_back`` kalitidan
    olinadi (yagona i18n manbasi — submenu reply-tugmasi bilan AYNAN bir
    xil matn). Modul topilmasa — asosiy lug'atdagi ``btn_back`` ga xavfsiz
    qaytamiz (klaviatura hech qachon bo'sh tugma bilan yiqilmaydi).
    """
    try:
        from translations.content_menu import content_menu_t
        return content_menu_t("cm_btn_back", lang)
    except Exception:  # pragma: no cover - i18n moduli yo'q bo'lsa
        return get_text("btn_back", lang)


def get_ai_studio_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """AI Studio sub-menu inline keyboard.

    "🖼 Rasmdan post yaratish" — rasmni Gemini vision bilan tahlil qilib,
    professional Telegram SMM posti tayyorlanadi (Photo-to-Post).
    "🔍 AI Post auditi" — foydalanuvchi tayyor postini AI'ga tahlil qildiradi
    (imlo, jozibadorlik, CTA, 1-10 baho).

    Barcha yorliqlar foydalanuvchi tiliga (lang) mos tarjima qilinadi.

    🧭 PostAssist V2 · 4-qadam — NAVIGATSIYA STACKI: pastki qatorda endi
    IKKI alohida tugma bor:
      * [◀️ Orqaga] (``ai_back_to_content``) — foydalanuvchi shu bo'limga
        «✨ Kontent yaratish» submenyusidan kelgani uchun aynan SHU YERGA
        qaytadi (asosiy menyuga sakrab ketmaydi);
      * [🏠 Asosiy menyu] (``studio_close``) — istalgan holatda asosiy
        6 tugmali menyuga chiqadi.
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
            # 🧠 Kontent reja — PostAssist V2 · 2-qadam: tugma SMART CONTENT
            # CALENDAR (7/30 kunlik) oqimini ochadi (``studio_content_plan``
            # callback'i o'zgarmagan — chat tarixidagi eski tugmalar ham
            # shu yangi oqimga tushadi).
            InlineKeyboardButton(_calendar_hub_label(lang), callback_data="studio_content_plan"),
        ],
        [
            # 🧭 4-qadam: ◀️ Orqaga → Kontent yaratish submenyusi.
            InlineKeyboardButton(_content_back_label(lang), callback_data="ai_back_to_content"),
            # 🏠 Asosiy menyu → asosiy 6 tugmali menyu (eski studio_close).
            InlineKeyboardButton(get_text("ai_btn_main_menu", lang), callback_data="studio_close"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)




def get_ai_studio_plan_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """AI Studio Kontent-reja inline klaviaturasi.

    Tugmalar:
      • [🔄 Qayta urinish] — rechaberingizni yangilash (callback_data="plan_refresh")
      • Barcha matnlar foydalanuvchi tiliga (lang) mos tarjima qilinadi.
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
            InlineKeyboardButton(get_text("btn_back", lang), callback_data="plan_back"),
            InlineKeyboardButton(get_text("np_ai_btn_retry", lang), callback_data="plan_refresh"),
        ],
        [
            InlineKeyboardButton(get_text("btn_main_menu", lang), callback_data="studio_close"),
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
        buttons.append(InlineKeyboardButton(f"{get_text(tone_key, lang)}{mark}", callback_data=cb(f"ai_tone:{key}")))
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
            InlineKeyboardButton(get_text("cab_remove_channel", lang), callback_data=cb(CB_CHANNEL_DELETE, ch_id)),
        ])
        keyboard.append([
            InlineKeyboardButton(f"{tone_emoji} {get_text('cab_tone', lang)}", callback_data=cb(CB_CHANNEL_SETTINGS, ch_id)),
            InlineKeyboardButton(get_text("ch_voice_btn", lang), callback_data=cb(CB_CHANNEL_VOICE, ch_id)),
        ])
    # "Qo'shish bor, lekin bekor qilish/chiqish yo'q" kamchiligini tuzatish:
    # ro'yxat ostida yangi kanal ulash va oynani yopish tugmalari bo'ladi.
    keyboard.append([InlineKeyboardButton(get_text("cab_add_channel_alt", lang), callback_data="add_channel_start")])
    keyboard.append([InlineKeyboardButton(get_text("cab_close", lang), callback_data="close_msg")])
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# 📢 KANALLARIM — MASTER PLAN STANDARTI (PostAssist V2, 4-qadam)
# ============================================================
# Eski ``render_channels_list`` ATAYLAB o'z joyida qoldirildi: kabinet
# («👤 Sozlamalar» → kanallar) ekrani va chat tarixidagi eski xabarlar shu
# klaviatura bilan ishlaydi (``ch_del:`` / ``ch_set:`` / ``ch_voice:``
# callback'lari buzilmasin). Yangi «📢 Kanallarim» bo'limi esa quyidagi
# ikki funksiyani ishlatadi.


def render_my_channels_list(channels: list, lang: str = "uz") -> InlineKeyboardMarkup:
    """📢 Kanallarim — ulangan kanallar RO'YXATI + [➕ Kanal qo'shish].

    Har bir kanal BITTA tugma: bosilganda ``ch_op:<channel_id>`` orqali
    o'sha kanalning boshqaruv ekrani ochiladi (ro'yxatda boshqa hech qanday
    amal tugmasi yo'q — "bir ekran, bir maqsad" qoidasi).
    """
    from translations import channels_queue_t

    keyboard = []
    for ch in channels:
        ch_id, ch_title = (list(ch) + [None, None])[:2]
        keyboard.append([InlineKeyboardButton(
            f"📢 {btn_label(ch_title)}",
            callback_data=cb(CB_CHANNEL_OPEN, ch_id),
        )])
    keyboard.append([InlineKeyboardButton(
        channels_queue_t("cq_ch_add_btn", lang), callback_data="add_channel_start")])
    keyboard.append([InlineKeyboardButton(
        channels_queue_t("cq_ch_close_btn", lang), callback_data="close_msg")])
    return InlineKeyboardMarkup(keyboard)


def render_channel_panel(channel_id, lang: str = "uz") -> InlineKeyboardMarkup:
    """📢 Kanal boshqaruv ekrani — master plan speksidagi QAT'IY layout::

        [➕ Post yaratish]
        [📅 Rejalashtirilgan]   [📊 Statistika]
        [🧠 Kanal DNA]          [⏰ Eng yaxshi vaqt]
        [🚀 AI Avtopilot]       [📋 Shablonlar]
        [⚙️ Kanal sozlamalari]  [◀️ Orqaga]

    Barcha tugmalar kanal KONTEKSTINI (``channel_id``) olib yuradi, shuning
    uchun ichki amallar asosiy menyuga chiqib ketmaydi; [◀️ Orqaga] esa
    kanallar ro'yxatiga qaytaradi (``ch_back``).

    🧠 PHASE B: yangi [🧠 Kanal DNA] va [⏰ Eng yaxshi vaqt] tugmalari —
    kanal uslubiy profili va optimal post vaqti (ownership himoyalangan).

    🚀 PHASE C: [🚀 AI Avtopilot] (7 kunlik reja, DNA + best time asosida)
    va [📋 Shablonlar] (post shablonlari menyusi) — ikkalasi ham kanal
    egaligi (IDOR) tekshiruvi bilan ochiladi.

    📥 PHASE D (2/2): [📥 Kontent manbalari] — 🔗 havoladan post (URL → 4
    format), 📡 RSS/ATOM oqimi va ♻️ eski postni yangilash (recycle). Hammasi
    shu kanal kontekstida, IDOR himoyasi bilan.
    """
    from translations import channels_queue_t

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(channels_queue_t("cq_ch_btn_create_post", lang),
                              callback_data=cb(CB_CHANNEL_NEW_POST, channel_id))],
        [
            InlineKeyboardButton(channels_queue_t("cq_ch_btn_scheduled", lang),
                                 callback_data=cb(CB_CHANNEL_SCHEDULED, channel_id)),
            InlineKeyboardButton(channels_queue_t("cq_ch_btn_stats", lang),
                                 callback_data=cb(CB_CHANNEL_STATS, channel_id)),
        ],
        [
            InlineKeyboardButton(channels_queue_t("cq_ch_btn_dna", lang),
                                 callback_data=cb(CB_CHANNEL_DNA, channel_id)),
            InlineKeyboardButton(channels_queue_t("cq_ch_btn_best_time", lang),
                                 callback_data=cb(CB_CHANNEL_BEST_TIME, channel_id)),
        ],
        [
            InlineKeyboardButton(channels_queue_t("cq_ch_btn_autopilot", lang),
                                 callback_data=cb(CB_CHANNEL_AUTOPILOT, channel_id)),
            InlineKeyboardButton(channels_queue_t("cq_ch_btn_templates", lang),
                                 callback_data=cb(CB_CHANNEL_TEMPLATES, channel_id)),
        ],
        # 📥 PHASE D (2/2) — kontent manbalari: URL→post, RSS/ATOM oqimi va
        # Content Recycle (kanal konteksti bilan, alohida qator — to'liq eni).
        [InlineKeyboardButton(channels_queue_t("cq_ch_btn_sources", lang),
                              callback_data=cb(CB_CHANNEL_SOURCES, channel_id))],
        [
            InlineKeyboardButton(channels_queue_t("cq_ch_btn_settings", lang),
                                 callback_data=cb(CB_CHANNEL_SETTINGS, channel_id)),
            InlineKeyboardButton(channels_queue_t("cq_ch_btn_back", lang),
                                 callback_data=CB_CHANNEL_BACK),
        ],
    ])


def render_channel_settings(channel_id, lang: str = "uz") -> InlineKeyboardMarkup:
    """⚙️ Kanal sozlamalari — uslub, AI ovoz tahlili, uzish + [◀️ Orqaga].

    Mavjud, sinovdan o'tgan amallarni QAYTA ISHLATADI: ``ch_set:`` (uslub),
    ``ch_voice:`` (AI tahlil) va ``ch_del:`` (kanalni uzish) — yangi oqim
    yozilmaydi, faqat ular kanal konteksti ichiga ko'chiriladi.
    """
    from translations import channels_queue_t

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(channels_queue_t("cq_ch_btn_tone", lang),
                                 callback_data=cb(CB_CHANNEL_SETTINGS, channel_id)),
            InlineKeyboardButton(channels_queue_t("cq_ch_btn_voice", lang),
                                 callback_data=cb(CB_CHANNEL_VOICE, channel_id)),
        ],
        [InlineKeyboardButton(channels_queue_t("cq_ch_btn_delete", lang),
                              callback_data=cb(CB_CHANNEL_DELETE, channel_id))],
        [InlineKeyboardButton(channels_queue_t("cq_ch_btn_back", lang),
                              callback_data=cb(CB_CHANNEL_OPEN, channel_id))],
    ])


# ============================================================
# 📅 REJALASHTIRILGAN — post kartochkasi amallari (4-qadam)
# ============================================================
def render_scheduled_actions(post_id, lang: str = "uz") -> list:
    """Bitta rejalashtirilgan post ostidagi 3 ta amal (bitta tugma qatori).

    [✏️ Tahrirlash] [⏰ Vaqtni o'zgartirish] [🗑 O'chirish] — mavjud,
    xavfsiz oqimlarni (``p_edit:`` / ``p_time:`` / ``qdel:``) chaqiradi.
    Ro'yxat klaviaturasiga qator sifatida qo'shish uchun LIST qaytaradi.
    """
    from translations import channels_queue_t

    return [
        InlineKeyboardButton(channels_queue_t("cq_sch_btn_edit", lang),
                             callback_data=cb(CB_SCHED_EDIT, post_id)),
        InlineKeyboardButton(channels_queue_t("cq_sch_btn_time", lang),
                             callback_data=cb(CB_SCHED_TIME, post_id)),
        InlineKeyboardButton(channels_queue_t("cq_sch_btn_delete", lang),
                             callback_data=cb(CB_SCHED_DELETE, post_id)),
    ]


def render_scheduled_full_actions(post_id, lang: str = "uz") -> list:
    """📅 YAGONA rejalashtirilgan ro'yxati uchun TO'LIQ amal to'plami.

    PostAssist V2 · 2-qadam (B1 birlashtiruv): «Kutilayotgan postlar» va
    «Rejalashtirilgan postlar» bitta ekranga qo'shilgani uchun har bir post
    ostida BARCHA amallar ko'rinadi::

        [👁 Ko'rish]   [✏️ Tahrirlash]
        [⏰ Vaqt]      [🔗 Tugma/Reaksiya]
        [🗑 O'chirish] [⏩ Surish]

    Qaytaradi: QATORLAR ro'yxati (``_get_queue_list_keyboard`` ularni
    klaviaturaning keyingi qatorlari sifatida qo'shadi).

    Eslatma: bu funksiya ``render_scheduled_actions`` (kanal kartochkalari
    uchun qat'iy 3 tugma) ni O'ZGARTIRMAYDI — eski shartnoma va testlar
    o'z joyida qoladi. Har bir callback mavjud, sinovdan o'tgan oqimlarga
    boradi: ``qview:`` (ko'rish), ``p_edit:`` (tahrirlash), ``p_time:``
    (vaqt), ``sched_br:`` (tugma/reaksiya tanlagichi), ``qdel:`` (o'chirish),
    ``qpush:`` (surish — eski alias).
    """
    from translations import channels_queue_t

    # Ko'rish tugmasi — mavjud (sinovdan o'tgan) `queue_btn_view` kaliti:
    # yorliqda post ID ko'rinadi ("👁 Ko'rish #12"), shu tariqa 5 amalli
    # yagona ro'yxatda ham eski xatti-harakat saqlanadi.
    view_btn = InlineKeyboardButton(
        get_text("queue_btn_view", lang, id=post_id),
        callback_data=cb(CB_POST_VIEW, post_id),
    )
    edit_btn = InlineKeyboardButton(
        channels_queue_t("cq_sch_btn_edit", lang),
        callback_data=cb(CB_SCHED_EDIT, post_id),
    )
    time_btn = InlineKeyboardButton(
        channels_queue_t("cq_sch_btn_time_short", lang),
        callback_data=cb(CB_SCHED_TIME, post_id),
    )
    btn_react_btn = InlineKeyboardButton(
        channels_queue_t("cq_sch_btn_btn_react", lang),
        callback_data=cb(CB_SCHED_BTN_REACT, post_id),
    )
    delete_btn = InlineKeyboardButton(
        channels_queue_t("cq_sch_btn_delete", lang),
        callback_data=cb(CB_SCHED_DELETE, post_id),
    )
    push_btn = InlineKeyboardButton(
        get_text("queue_btn_push", lang),
        callback_data=cb(f"qpush:{post_id}"),
    )
    return [
        [view_btn, edit_btn],
        [time_btn, btn_react_btn],
        [delete_btn, push_btn],
    ]


def scheduled_btn_react_keyboard(post_id, lang: str = "uz") -> InlineKeyboardMarkup:
    """🔗 Tugma/Reaksiya tanlagichi (yagona ro'yxatdagi 4-amal).

    Ikkala tugma ham mavjud, sinovdan o'tgan oqimlarni ochadi
    (``p_btn:`` / ``p_react:``) — yangi FSM yaratilmaydi.
    """
    from translations import channels_queue_t

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                channels_queue_t("cq_sch_br_btn_link", lang),
                callback_data=cb(CB_POST_BTN, post_id),
            ),
            InlineKeyboardButton(
                channels_queue_t("cq_sch_br_btn_react", lang),
                callback_data=cb(CB_POST_REACT, post_id),
            ),
        ],
        [
            InlineKeyboardButton(
                channels_queue_t("cq_ch_btn_back", lang),
                callback_data="qpage:0",
            ),
        ],
    ])


def render_pending_list(posts: list, user_code: str, lang: str = "uz") -> InlineKeyboardMarkup:
    """Kutilayotgan postlar ro'yxati tugmalari (uz/ru).

    ``callback_data`` tilga bog'liq emas — hamma joyda bir xil qoladi.
    """
    keyboard = []
    for p in posts:
        pid, ch_title, p_type, s_time, p_num, r_type, r_day, r_time = p
        code_label = f"{user_code}-{p_num}" if p_num else f"#{pid}"
        # Har bir post uchun 2 qator tugma:
        # 1-qator: vaqt o'zgartirish, matn tahrirlash
        # 2-qator: tugma URL, reaksiya, bekor qilish
        keyboard.append([
            InlineKeyboardButton(get_text("pend_edit_time_btn", lang, code=code_label), callback_data=cb(CB_POST_TIME, pid)),
            InlineKeyboardButton(get_text("pend_edit_content_btn", lang, code=code_label), callback_data=cb(CB_POST_EDIT, pid)),
        ])
        keyboard.append([
            InlineKeyboardButton(get_text("pend_edit_btn_btn", lang), callback_data=cb(CB_POST_BTN, pid)),
            InlineKeyboardButton(get_text("pend_edit_react_btn", lang), callback_data=cb(CB_POST_REACT, pid)),
            InlineKeyboardButton(get_text("pend_cancel_btn", lang), callback_data=cb(CB_POST_CANCEL, pid)),
        ])
    # Ro'yxatni yangilash (amal bajargandan keyin holatni ko'rish) va yopish tugmalari
    keyboard.append([
        InlineKeyboardButton(get_text("pend_refresh_btn", lang), callback_data="pending_refresh"),
        InlineKeyboardButton(get_text("pend_close_btn", lang), callback_data="close_msg"),
    ])
    return InlineKeyboardMarkup(keyboard)


def get_cabinet_inline_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Kabinet & Sozlamalar asosiy menyusi — inline tugmalar (4x2).

    ``lang`` foydalanuvchi tili (uz/ru). Tugma matni tarjima qilinadi,
    ``callback_data`` o'zgarishsiz qoladi (routing tilga bog'liq emas).

    🧹 PROFIL TOZALANDI: «🌐 Til» tugmasi profildan OLIB TASHLANDI — til
    FAQAT Sozlamalar → «🌐 Til / Язык» (``stgs_lang``) ichida qoldi. Eski
    ``cab_lang`` callback'i esa chat tarixidagi xabarlar uchun routing'da
    saqlanadi (handlers.start.cabinet_callback).
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
    ]
    return InlineKeyboardMarkup(keyboard)


def get_settings_profile_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """👤 Profil ekranining compatibility klaviaturasi + Sozlamalarga qaytish.

    Eski kabinet amallari saqlanadi, lekin yangi settings oqimida aniq parent
    tugmasi ham ko'rsatiladi: [◀️ Orqaga] → ``stgs_hub``.
    """
    base = get_cabinet_inline_keyboard(lang)
    rows = [list(row) for row in base.inline_keyboard]
    from translations import settings_stats_t
    rows.append([
        InlineKeyboardButton(settings_stats_t("ss_btn_back", lang),
                             callback_data="stgs_hub")
    ])
    return InlineKeyboardMarkup(rows)


# ============================================================
# ⚙️ SOZLAMALAR — IXCHAM 8 GURUHLI HUB (PostAssist V2, 2-bosqich)
# ------------------------------------------------------------
# Asosiy Sozlamalar ekrani faqat yuqori darajadagi guruhlarni ko'rsatadi:
#
#     [👤 Profil]             [🌐 Til / Язык]
#     [🎁 Bonuslar & Ballar]  [🎨 Post sozlamalari]
#     [🔔 Bildirishnomalar]   [💳 To'lovlar tarixi]
#     [🧰 Vositalar]          [❓ Yordam & Ma'lumot]
#                    [◀️ Orqaga]
#
# Bonuslar/ballar va yordam/ma'lumot bo'limlari o'z submenu'lariga ega.
# Eski callback'lar alohida handlerlarda ham saqlanadi — Telegram chat
# tarixidagi eski inline tugmalar yangi oqimlarda "o'lik" bo'lib qolmaydi.
# ============================================================


def get_settings_hub_keyboard(lang: str = "uz", include_legacy: bool = False) -> InlineKeyboardMarkup:
    """⚙️ Sozlamalar asosiy hub'i: 8 ta guruh + [◀️ Orqaga].

    ``include_legacy`` avvalgi 12-tugmali API bilan chaqiruvchi kodlar uchun
    saqlangan. Legacy tugmalar endi yangi hub'da ko'rsatilmaydi; ularning
    callback'lari esa routing'da qo'llab-quvvatlanadi.
    """
    from translations import settings_stats_t  # lazy — aylanma importdan himoya

    keyboard = [
        [
            InlineKeyboardButton(settings_stats_t("ss_btn_profile", lang),
                                 callback_data="stgs_profile"),
            InlineKeyboardButton(settings_stats_t("ss_btn_lang", lang),
                                 callback_data="stgs_lang"),
        ],
        [
            InlineKeyboardButton(settings_stats_t("ss_btn_rewards", lang),
                                 callback_data="stgs_rewards"),
            InlineKeyboardButton(settings_stats_t("ss_btn_post_settings", lang),
                                 callback_data="stgs_post"),
        ],
        [
            InlineKeyboardButton(settings_stats_t("ss_btn_notif", lang),
                                 callback_data="stgs_notif"),
            InlineKeyboardButton(settings_stats_t("ss_btn_payments", lang),
                                 callback_data="stgs_pay"),
        ],
        [
            InlineKeyboardButton(settings_stats_t("ss_btn_tools", lang),
                                 callback_data="stgs_tools"),
            InlineKeyboardButton(settings_stats_t("ss_btn_help_hub", lang),
                                 callback_data="stgs_help_hub"),
        ],
        [
            InlineKeyboardButton(settings_stats_t("ss_btn_back", lang),
                                 callback_data="stgs_back"),
        ],
    ]
    # Imzoni buzmaslik uchun qabul qilinadi, lekin yangi hub doim bir xil.
    _ = include_legacy
    return InlineKeyboardMarkup(keyboard)


def get_settings_rewards_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """🎁 Bonuslar & Ballar submenu'si.

    Tugma callback'lari ataylab eski nomlar bilan ham mos: ``stgs_credits``,
    ``stgs_transfer``, ``claim_bonus`` va ``referral_hub`` eski xabarlarda
    uchrashi mumkin. [◀️ Orqaga] esa parent hub'ni (`stgs_hub`) qayta chizadi.
    """
    from translations import settings_stats_t

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(settings_stats_t("ss_rewards_points", lang),
                              callback_data="stgs_credits")],
        [InlineKeyboardButton(settings_stats_t("ss_rewards_transfer", lang),
                              callback_data="stgs_transfer")],
        [InlineKeyboardButton(settings_stats_t("ss_rewards_daily_bonus", lang),
                              callback_data="claim_bonus")],
        [InlineKeyboardButton(settings_stats_t("ss_rewards_referral", lang),
                              callback_data="referral_hub")],
        [InlineKeyboardButton(settings_stats_t("ss_btn_back", lang),
                              callback_data="stgs_hub")],
    ])


def get_settings_help_hub_keyboard(
    lang: str = "uz", support_username: str | None = None,
) -> InlineKeyboardMarkup:
    """❓ Yordam & Ma'lumot submenu'si.

    Qo'llab-quvvatlash uchun username bo'lsa Telegram URL tugmasi ishlatiladi;
    username sozlanmagan test/development muhitida esa ``help_support``
    callback'i xavfsiz ma'lumot ekranini ochadi.
    """
    from config import SUPPORT_USERNAME
    from translations import settings_stats_t

    username = str(
        SUPPORT_USERNAME if support_username is None else support_username
    ).strip().lstrip("@")
    support_kwargs = (
        {"url": f"https://t.me/{username}"} if username else
        {"callback_data": "help_support"}
    )
    support_button = InlineKeyboardButton(
        settings_stats_t("ss_help_hub_support", lang), **support_kwargs
    )
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(settings_stats_t("ss_help_hub_guide", lang),
                              callback_data="help_hub")],
        [support_button],
        [InlineKeyboardButton(settings_stats_t("ss_help_hub_about", lang),
                              callback_data="stgs_about")],
        [InlineKeyboardButton(settings_stats_t("ss_btn_back", lang),
                              callback_data="stgs_hub")],
    ])


# O'qilishi oson aliaslar: integratsiyalarda ikkala nomlash uslubi ishlatilgan.
def get_stgs_rewards_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    return get_settings_rewards_keyboard(lang)


def get_stgs_help_hub_keyboard(
    lang: str = "uz", support_username: str | None = None,
) -> InlineKeyboardMarkup:
    return get_settings_help_hub_keyboard(lang, support_username)


def get_rewards_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    return get_settings_rewards_keyboard(lang)


def get_help_hub_keyboard(
    lang: str = "uz", support_username: str | None = None,
) -> InlineKeyboardMarkup:
    return get_settings_help_hub_keyboard(lang, support_username)


def get_tools_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """🧰 Vositalar — yordamchi vositalar submenyusi (PostAssist V2, 3-qadam).

        [🔤 Kirill-Lotin Konvertor]
        [✨ Tugma & Reaksiyalar (Post Enhancer)]
                    [◀️ Orqaga]

    Callback'lar YANGI EMAS — mavjud, sinovdan o'tgan oqimlarga ulanadi:
      * ``extra_converter`` → handlers.converter.converter_inline_entry
        (``CONVERT_INPUT`` holati — kirill/lotin o'girish, media caption ham);
      * ``extra_enhancer``  → handlers.post_enhancer.post_enhancer_start
        (``ENH_POST`` holati — postga URL tugma va reaksiya qo'shish);
      * ``stgs_hub``        → ⚙️ Sozlamalar menyusiga qaytish (ekran qayta
        chiziladi, yangi xabar yuborilmaydi).
    """
    from translations import settings_stats_t

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(settings_stats_t("ss_tools_btn_converter", lang),
                              callback_data="extra_converter")],
        [InlineKeyboardButton(settings_stats_t("ss_tools_btn_enhancer", lang),
                              callback_data="extra_enhancer")],
        [InlineKeyboardButton(settings_stats_t("ss_btn_back", lang),
                              callback_data="stgs_hub")],
    ])


def get_settings_back_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Sozlamalar ichki ekranidan parent hub'ga qaytish.

    Asosiy hub'ning o'zidagi [◀️ Orqaga] ``stgs_back`` orqali asosiy reply
    menyuga chiqadi; barcha ichki sahifalar esa ``stgs_hub`` bilan hub'ga
    qaytadi.
    """
    from translations import settings_stats_t

    return InlineKeyboardMarkup([[
        InlineKeyboardButton(settings_stats_t("ss_btn_back", lang),
                             callback_data="stgs_hub"),
    ]])


def get_user_stats_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """📊 Statistika ekrani amallari: [🔄 Yangilash] [◀️ Orqaga].

    Callback'lar eski analytics prefiksida (``an_refresh`` / ``an_close``) —
    mavjud FSM routing (ANALYTICS_VIEW holati) o'zgarishsiz qoladi.
    """
    from translations import settings_stats_t

    return InlineKeyboardMarkup([[
        InlineKeyboardButton(settings_stats_t("ss_btn_refresh", lang),
                             callback_data="an_refresh"),
        InlineKeyboardButton(settings_stats_t("ss_btn_back", lang),
                             callback_data="an_close"),
    ]])


def get_user_overview_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """📊 SHAXSIY statistika ekrani amallari (asosiy menyu «📊 Statistika»).

    Speks: ``[📈 Kanal bo'yicha batafsil]`` ``[◀️ Orqaga]``.

    * ``an_detail``  — mavjud kanal analitikasini ochadi (kanal tanlash →
      kanal dashboard'i);
    * ``an_close``   — asosiy 6 tugmali menyuga qaytadi (dialog yopiladi).

    ``get_user_stats_keyboard`` dan farqi: bu ekran SHAXSIY hisobot —
    unda admin (bot bo'yicha) statistikasiga hech qanday yo'l yo'q.
    """
    from translations import settings_stats_t

    return InlineKeyboardMarkup([[
        InlineKeyboardButton(settings_stats_t("ss_btn_channel_detail", lang),
                             callback_data="an_detail"),
        InlineKeyboardButton(settings_stats_t("ss_btn_back", lang),
                             callback_data="an_close"),
    ]])


def get_language_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Til tanlash: O'zbekcha / Русский / English.

    ``lang`` — foydalanuvchi joriy tili; "Orqaga" tugmasi shu tilga mos
    tarjima qilinadi (masalan ru → "⬅️ Назад", en → "⬅️ Back").
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="cab_lang_uz"),
            InlineKeyboardButton("🇷🇺 Русский", callback_data="cab_lang_ru"),
        ],
        [
            InlineKeyboardButton("🇬🇧 English", callback_data="cab_lang_en"),
        ],
        [
            InlineKeyboardButton(get_text("btn_back", lang), callback_data="cab_main"),
        ],
    ])


# ============================================================
# ✍️ ODDIY POST (AI'SIZ) — UNIVERSAL BOSHQARUV PANELI
# ------------------------------------------------------------
# Foydalanuvchi tayyor matn/rasm/video yuborgach preview ostida chiqadigan
# yagona panel. Callback prefiksi ``mnp_`` (manual post) — global stale
# handler prefikslari (``mp_`` Magic Post, ``vp_``, ``image_``, ``ps_``,
# ``studio_``, ``cc_``) bilan to'qnashmaydi.
# ============================================================
CB_MANUAL_PREFIX = "mnp_"
CB_MANUAL_NOW = "mnp_now"            # 🚀 Hozir yuborish
CB_MANUAL_TIME = "mnp_time"          # 📅 Vaqtni belgilash
CB_MANUAL_24H = "mnp_24h"            # 🗑 24 soatlik e'lon (auto-delete 24h)
CB_MANUAL_REPEAT = "mnp_repeat"      # 🔄 Takroriy e'lon (har kuni)
CB_MANUAL_EDIT = "mnp_edit"          # ✏️ Tahrirlash
CB_MANUAL_CANCEL = "mnp_cancel"      # ❌ Bekor qilish
CB_MANUAL_PANEL = "mnp_panel"        # ◀️ Orqaga (kanal tanlashdan panelga)
CB_MANUAL_CHANNEL = "mnp_ch:"        # mnp_ch:<channel_id> — kanal tanlash
# 🔁 PHASE C — dublikat detektori (post chiqarilishidan oldin): ogohlantirish
# oynasining 3 amali (SPEKS: [🚀 Baribir chiqarish] | [✨ AI bilan yangilash] |
# [❌ Bekor qilish]; bekor qilish mavjud CB_MANUAL_CANCEL orqali ishlaydi).
CB_MANUAL_DUP_FORCE = "mnp_dup_go"   # 🚀 Baribir chiqarish
CB_MANUAL_DUP_AI = "mnp_dup_ai"      # ✨ AI bilan yangilash


def manual_channel_callback(channel_id) -> str:
    """``mnp_ch:<channel_id>`` callback'i (64-bayt kafolatli ``cb`` orqali)."""
    return cb(CB_MANUAL_CHANNEL[:-1], str(channel_id))


def manual_channel_from_callback(data: str):
    """``mnp_ch:-100123`` → channel_id (int/str); yaroqsiz bo'lsa None."""
    prefix = CB_MANUAL_CHANNEL
    if not isinstance(data, str) or not data.startswith(prefix):
        return None
    raw = data[len(prefix):].strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


def get_manual_post_panel(lang: str = "uz") -> InlineKeyboardMarkup:
    """✍️ Oddiy post preview'si ostidagi UNIVERSAL boshqaruv paneli::

        [🚀 Hozir yuborish]
        [📅 Vaqtni belgilash]
        [🗑 24 soatlik e'lon]   [🔄 Takroriy e'lon]
        [✏️ Tahrirlash]         [❌ Bekor qilish]

    Yorliqlar ``translations/manual_post.py`` dan (uz/ru/en paritet);
    ``callback_data`` tilga bog'liq emas.
    """
    from translations import manual_post_t

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(manual_post_t("mp_btn_send_now", lang),
                              callback_data=CB_MANUAL_NOW)],
        [InlineKeyboardButton(manual_post_t("mp_btn_schedule", lang),
                              callback_data=CB_MANUAL_TIME)],
        [
            InlineKeyboardButton(manual_post_t("mp_btn_24h", lang),
                                 callback_data=CB_MANUAL_24H),
            InlineKeyboardButton(manual_post_t("mp_btn_repeat", lang),
                                 callback_data=CB_MANUAL_REPEAT),
        ],
        [
            InlineKeyboardButton(manual_post_t("mp_btn_edit", lang),
                                 callback_data=CB_MANUAL_EDIT),
            InlineKeyboardButton(manual_post_t("mp_btn_cancel", lang),
                                 callback_data=CB_MANUAL_CANCEL),
        ],
    ])


def get_duplicate_warning_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """🔁 Dublikat ogohlantirishi klaviaturasi (PHASE C — SPEKS: 3 amal).

    [🚀 Baribir chiqarish] / [✨ AI bilan yangilash] / [❌ Bekor qilish].
    Bekor qilish — mavjud oddiy-post bekor qilish amali (``mnp_cancel``).
    """
    from translations import manual_post_t

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(manual_post_t("mp_dup_btn_force", lang),
                              callback_data=CB_MANUAL_DUP_FORCE)],
        [InlineKeyboardButton(manual_post_t("mp_dup_btn_ai", lang),
                              callback_data=CB_MANUAL_DUP_AI)],
        [InlineKeyboardButton(manual_post_t("mp_btn_cancel", lang),
                              callback_data=CB_MANUAL_CANCEL)],
    ])


def get_manual_channel_keyboard(channels: list, lang: str = "uz") -> InlineKeyboardMarkup:
    """📢 Kanal tanlash klaviaturasi (oddiy post oqimi).

    Har bir kanal bitta tugma: ``mnp_ch:<channel_id>``. Pastda panelga
    qaytish tugmasi (``mnp_panel``) — foydalanuvchi hech qachon boshi
    berk ko'chada qolmaydi.
    """
    from translations import manual_post_t

    keyboard = [
        [InlineKeyboardButton(f"📢 {btn_label(ch_title)}",
                              callback_data=manual_channel_callback(ch_id))]
        for ch_id, ch_title in [(c[0], c[1]) for c in (channels or [])]
    ]
    keyboard.append([InlineKeyboardButton(manual_post_t("mp_btn_back_panel", lang),
                                          callback_data=CB_MANUAL_PANEL)])
    return InlineKeyboardMarkup(keyboard)


def get_extras_inline_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """⚙️ Qo'shimcha funksiyalar — inline menyu (uz/ru).

    Birinchi qator — ✨ Postga Tugma & Reaksiya qo'shish (Post Enhancer):
    tayyor postga 10 tagacha reaksiya va 10 tagacha URL tugma qo'shib,
    kanalga bir zumda yuborish. Konvertor o'z o'rnida saqlanadi.

    Yorliqlar foydalanuvchi tilida (``lang``) chiziladi; ``callback_data``
    tilga bog'liq emas — ikkala tilda ham bir xil qoladi.
    """
    keyboard = [
        [InlineKeyboardButton(get_text("extras_btn_enhancer", lang),
                              callback_data="extra_enhancer")],
        [InlineKeyboardButton(get_text("extras_btn_converter", lang),
                              callback_data="extra_converter")],
        [InlineKeyboardButton(get_text("cab_close", lang), callback_data="extra_close")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_help_keyboard(support_username: str = "", lang: str = "uz") -> InlineKeyboardMarkup:
    """📖 Qo'llanma / Bot haqida — FAQ va qo'llab-quvvatlash tugmalari (uz/ru).

    - ``help_btn_support`` — admin/qo'llab-quvvatlash bilan bog'lanish
      (``support_username`` bosh bo'lmasa ``t.me`` havolasi chiqadi);
    - ``help_btn_faq`` — tez-tez beriladigan savollar sahifasiga o'tadi
      (``help:faq`` callback).
    """
    keyboard = []
    if support_username:
        username = str(support_username).strip().lstrip("@")
        if username:
            keyboard.append([InlineKeyboardButton(
                get_text("help_btn_support", lang), url=f"https://t.me/{username}"
            )])
    keyboard.append([InlineKeyboardButton(
        get_text("help_btn_faq", lang), callback_data="help:faq"
    )])
    return InlineKeyboardMarkup(keyboard)


def get_help_back_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """📖 FAQ sahifasidan qo'llanmaga qaytish (⬅️ Orqaga / ⬅️ Назад)."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(get_text("btn_back", lang), callback_data="help:guide")
    ]])


# ============================================================
# 💳 TO'LOV MINTAQASI (payment region) — HUDUDIY TANLOV
# ------------------------------------------------------------
# To'lov usuli TANLOVI HECH QACHON tilga bog'liq emas: rus/ingliz tilidagi
# foydalanuvchilar ham Uzcard/Humo'dan, o'zbek tilidagilar ham Telegram
# Stars'dan bemalol foydalana oladi. Shuning uchun FAQAT tugma yorliqlari
# ``lang`` bo'yicha tarjima qilinadi, ``callback_data`` esa tillardan
# mustaqil — bir xil (routing tilga bog'liq emas).
#
# Oqim: tarif tanlandi → [🇺🇿 O'zbekiston] / [🌍 Xalqaro] → rekvizitlar.
#   * uz   → faqat mahalliy usullar (Uzcard / Humo, so'mdagi narxlar);
#   * intl → faqat xalqaro usullar (Stars / Crypto / Card, $ yoki Stars);
#            Uzcard / Humo rekvizitlari BUTUNLAY ko'rsatilmaydi.
# ============================================================

PAYMENT_REGION_UZ = "uz"
PAYMENT_REGION_INTL = "intl"
PAYMENT_REGIONS = (PAYMENT_REGION_UZ, PAYMENT_REGION_INTL)

#: Callback prefikslari (handler'lardagi ``^sub_`` patterni ichida ishlaydi).
CB_PAY_REGION = "sub_region"
CB_PAY_INTL_PLAN = "sub_intl_plan"

_REGION_ALIASES = {
    "uz": PAYMENT_REGION_UZ,
    "uzb": PAYMENT_REGION_UZ,
    "uzbekistan": PAYMENT_REGION_UZ,
    "uzbekiston": PAYMENT_REGION_UZ,
    "intl": PAYMENT_REGION_INTL,
    "int": PAYMENT_REGION_INTL,
    "international": PAYMENT_REGION_INTL,
}


def normalize_payment_region(region) -> str:
    """Berilgan qiymatni 'uz' | 'intl' ga normallashtiradi; noma'lum → ''."""
    raw = str(region or "").strip().lower()
    return _REGION_ALIASES.get(raw, "")


def is_payment_region(region) -> bool:
    """Qiymat ruxsat etilgan to'lov mintaqasimi ('uz' | 'intl')."""
    return str(region or "").strip().lower() in PAYMENT_REGIONS


def payment_region_callback(region: str, plan_key: str = None) -> str:
    """``sub_region:uz`` / ``sub_region:intl:1y`` (64-bayt kafolatli ``cb``)."""
    return cb(CB_PAY_REGION, str(region or ""), plan_key)


def payment_region_from_callback(data: str, maxsplit: int = 2) -> tuple:
    """``sub_region:intl:1y`` → ``('intl', '1y')``; yaroqsiz → ``('', '')``.

    Handler testlari va klaviatura quruvchilari bir xil parserdan
    foydalanadi — format bir joyda yashaydi.
    """
    from keyboards.callback_data import split_callback

    parts = split_callback(data, maxsplit)
    if not parts or parts[0] != CB_PAY_REGION:
        return "", ""
    region = normalize_payment_region(parts[1]) if len(parts) > 1 else ""
    plan_key = parts[2] if len(parts) > 2 else ""
    return region, plan_key


def get_payment_region_keyboard(
    lang: str = "uz", plan_key: str = None
) -> InlineKeyboardMarkup:
    """To'lov mintaqasi tanlash klaviaturasi — 2 ta asosiy tugma + orqaga.

    ``lang`` — faqat YORLIQLARNI tarjima qiladi (uz/ru/en); tanlovning
    o'zi tilga bog'liq emas: uchala tilda ham callback_data bir xil.

    ``plan_key`` ('1m'|'3m'|'1y' yoki None) — oldindan tanlangan tarif;
    u holda mintaqani tanlagan zahoti shu tarifning to'lov ekrani ochiladi.
    """
    rows = [
        [InlineKeyboardButton(
            get_text("pay_region_uz", lang),
            callback_data=payment_region_callback(PAYMENT_REGION_UZ, plan_key),
        )],
        [InlineKeyboardButton(
            get_text("pay_region_intl", lang),
            callback_data=payment_region_callback(PAYMENT_REGION_INTL, plan_key),
        )],
        [InlineKeyboardButton(get_text("btn_back", lang), callback_data="sub_back")],
    ]
    return InlineKeyboardMarkup(rows)


def get_intl_tariffs_keyboard(
    lang: str = "uz", plan_order: tuple = ("1m", "3m", "1y")
) -> InlineKeyboardMarkup:
    """🌍 Xalqaro tarif tanlash — FAQAT Stars/Crypto paketlari.

    Bu klaviaturada Uzcard / Humo tugmalari va rekvizitlari UMUMAN
    mavjud emas (xalqaro tanlovda mahalliy kartalar butunlay yashiriladi).
    Orqa tugma ``sub_region``ga qaytadi — foydalanuvchi mintaqani
    almashtirishi mumkin.
    """
    rows = [
        [InlineKeyboardButton(
            get_text(f"intl_tariff_{key}", lang),
            callback_data=cb(CB_PAY_INTL_PLAN, key),
        )]
        for key in plan_order
    ]
    rows.append([InlineKeyboardButton(
        get_text("btn_back", lang), callback_data=CB_PAY_REGION
    )])
    return InlineKeyboardMarkup(rows)


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
# turadi — eski oqimlar (nprt:) faqat 6 tasini ko'rsatishda davom etadi.
REACTION_POOL = REACTION_EMOJIS + (
    "😍", "🤩", "😮", "😂",
    "🙏", "💯", "✅", "⭐️",
    "👀", "💪", "🎯", "🤝",
    "😢", "👎",
)


# Callback prefikslari kanonik ravishda ``keyboards/callback_data.py`` da
# saqlanadi (64-bayt kafolati bilan) va shu modulga import qilinadi:
#   CB_REACT_TOGGLE = "nprt:t:"  |  CB_REACT_DONE = "nprt:done"
#   CB_REACT_SKIP   = "nprt:skip"
# Kanal postidagi reaksiya hisoblagichi esa "react:" (CB_REACTION) — u
# allaqachon yuborilgan postlarda yashagani uchun ATAYLAB o'zgarmaydi.


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
            row.append(InlineKeyboardButton(emoji, callback_data=cb(CB_REACTION, post_id, emoji)))
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


def strip_leading_reaction_glyphs(content, reaction_emojis=None):
    """Caption/matn boshidagi sizib chiqqan reaksiya emojilarini olib tashlaydi.

    Stiker yoki qo'lda yozilgan emojilar faqat ``InlineKeyboardMarkup``
    tugmalari bo'lishi kerak — kanal postining matni/caption'iga hech
    qachon qo'shilmasligi kerak. Eski saqlangan postlarda
    ``👍 ❤️ 🔥\\n\\nSalom`` kabi prefix bo'lsa, u yuborishdan oldin
    tozalanadi.

    Moslik: birinchi qator tanlangan emojilarning bo'shliqli/bo'shliqsiz
    qo'shilmasi yoki token-to'plami bilan teng bo'lsa (Variation Selector
    hisobga olinmaydi). Qolgan matn bo'sh bo'lsa (faqat emojidan iborat
    post) — o'zgartirilmaydi.
    """
    if content is None:
        return content
    text = content if isinstance(content, str) else str(content)
    if not text:
        return text

    reactions = normalize_custom_reaction_emojis(reaction_emojis)
    if not reactions:
        return text

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\n" in normalized:
        first, rest = normalized.split("\n", 1)
    else:
        first, rest = normalized, ""

    first_stripped = first.strip()
    if not first_stripped:
        return text

    def _key(value: str) -> str:
        return _strip_vs16(value or "")

    first_key = _key(first_stripped)
    space_key = _key(" ".join(reactions))
    nospace_key = _key("".join(reactions))
    matched = first_key == space_key or first_key == nospace_key

    if not matched:
        tokens = extract_emoji_tokens(first_stripped)
        if tokens:
            compact_first = _key("".join(first_stripped.split()))
            compact_tokens = _key("".join(tokens))
            token_set = {_key(t) for t in tokens}
            reaction_set = {_key(e) for e in reactions}
            if compact_first == compact_tokens and token_set == reaction_set:
                matched = True

    if not matched:
        return text
    if not rest.strip():
        # Faqat emojidan iborat post — caption o'zi shu emojilar.
        return text
    return rest.lstrip("\n")


def get_reaction_toggle_keyboard(selected=None, lang: str = "uz") -> InlineKeyboardMarkup:
    """Multi-select reaksiya klaviaturasi — emoji bosilganda ✅ belgilanadi/olib tashlanadi.

    Keyingi qadamga faqat "[➡️ Davom etish]" yoki "[⏭ Reaksiyasiz o'tish]"
    tugmasi bosilganda o'tiladi. Yorliqlar ``lang`` ga mos tarjima qilinadi.
    """
    sel = set(normalize_reaction_emojis(selected)) if selected else set()
    emoji_row_1 = []
    emoji_row_2 = []
    for idx, emoji in enumerate(REACTION_EMOJIS):
        mark = "✅" if emoji in sel else ""
        button = InlineKeyboardButton(f"{emoji} {mark}".strip(), callback_data=cb(CB_REACT_TOGGLE, emoji))
        if idx < 3:
            emoji_row_1.append(button)
        else:
            emoji_row_2.append(button)

    count = len(sel)
    done_label = (
        get_text("np_react_done_count", lang, count=count)
        if count else get_text("np_react_done", lang)
    )
    keyboard = [
        emoji_row_1,
        emoji_row_2,
        [InlineKeyboardButton(done_label, callback_data=CB_REACT_DONE)],
        [InlineKeyboardButton(get_text("np_react_skip", lang), callback_data=CB_REACT_SKIP)],
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

