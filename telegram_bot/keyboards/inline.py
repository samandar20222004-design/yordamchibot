import unicodedata
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

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
                        channel_interval: int = 3) -> InlineKeyboardMarkup:
    """Admin panel: YAGONA reklama boshqaruv markazi (hub) klaviaturasi.

    Avvallari uch alohida joyga sochilgan (dashboard'dagi "Har 3-5 javob
    reklamasi" ekrani, reply-klaviaturadagi "Kanal posti reklamasi" va "Bot
    xabari reklamasi" tugmalari) — endi hammasi shu bitta menyuda:

    • ikkala reklama puli (kanal postlari / bot javoblari) shu yerda ochiladi;
    • kanal postlari oralig'i (har nechanchi postda) — ``adp:channel:iv``;
    • bot javoblari holati (toggle) va javob intervali — ``adm_ad_*``.
    """
    status_label = "✅ Faol" if auto_status else "❌ O'chirilgan"
    keyboard = [
        [
            InlineKeyboardButton(f"📢 Kanal posti puli ({channel_active}/{channel_total})",
                                 callback_data="adp:channel:back"),
            InlineKeyboardButton(f"🤖 Javoblar puli ({reply_active}/{reply_total})",
                                 callback_data="adp:reply:back"),
        ],
        [
            InlineKeyboardButton(f"⏱ Kanal: har {channel_interval}-post",
                                 callback_data="adp:channel:iv"),
            InlineKeyboardButton(f"⏱ Javob: har {auto_interval} so'rov",
                                 callback_data="adm_ad_set_interval"),
        ],
        [
            InlineKeyboardButton(f"🔄 Bot javoblari reklamasi: {status_label}",
                                 callback_data="adm_ad_toggle"),
            InlineKeyboardButton("✏️ Eski javob matni", callback_data="adm_ad_edit_text"),
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


def get_admin_ad_interval_keyboard() -> InlineKeyboardMarkup:
    """Reklama intervalini tezkor tanlash klaviaturasi (orqaga — reklama hub'iga)."""
    keyboard = [
        [
            InlineKeyboardButton("3 ta so'rov", callback_data="adm_ad_int:3"),
            InlineKeyboardButton("4 ta so'rov", callback_data="adm_ad_int:4"),
            InlineKeyboardButton("5 ta so'rov", callback_data="adm_ad_int:5"),
        ],
        [
            InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_adhub"),
            InlineKeyboardButton("❌ Bekor qilish", callback_data="adm_cancel"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    """Admin panel inline keyboard — dashboard tugmalari layout.

    Reklama bilan bog'liq BARCHA boshqaruv endi bitta tugada —
    "🎯 Reklama markazi" (``adm_adhub``) hub menyuga olib kiradi.
    """
    keyboard = [
        [
            InlineKeyboardButton("📊 To'liq statistika", callback_data="adm_stats"),
            InlineKeyboardButton("📣 Ommaviy xabar (Broadcast)", callback_data="adm_broadcast"),
        ],
        [
            InlineKeyboardButton("📢 Majburiy obuna", callback_data="adm_sponsors"),
            InlineKeyboardButton("🎯 Reklama markazi", callback_data="adm_adhub"),
        ],
        [
            InlineKeyboardButton("📋 Kanallar ro'yxati", callback_data="adm_channels"),
            InlineKeyboardButton("🛠 Tizim sozlamalari", callback_data="adm_settings"),
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
    if scope == "channel":
        label = (
            f"⏱ Reklama oralig'i: har {interval}-post"
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


def get_ai_studio_keyboard() -> InlineKeyboardMarkup:
    """AI Studio sub-menu inline keyboard.

    "🔍 AI Post auditi" — foydalanuvchi tayyor postini AI'ga tahlil qildiradi
    (imlo, jozibadorlik, CTA, 1-10 baho).
    """
    keyboard = [
        [
            InlineKeyboardButton("✍️ AI Post yaratish", callback_data="studio_ai_post"),
            InlineKeyboardButton("📢 Ochiq kanaldan olish", callback_data="studio_extract"),
        ],
        [
            InlineKeyboardButton("🧠 Kontent-reja", callback_data="studio_content_plan"),
            InlineKeyboardButton("🔍 AI Post auditi", callback_data="studio_ai_audit"),
        ],
        [
            InlineKeyboardButton("⬅️ Asosiy menyu", callback_data="studio_close"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# AI STUDIO — DOIMIY INLINE NAVIGATSIYA
# ============================================================
# Barcha AI Studio ekranlarida pasda shu ikki tugma turadi: xabar hech qachon
# "yo'qolib" ketmaydi, foydalanuvchi har doim menyuga qaytishi yoki sessiyani
# yopishi mumkin.
def get_ai_back_keyboard() -> InlineKeyboardMarkup:
    """AI Studio ichki ekranlari: ⬅️ Orqaga + ❌ Bekor qilish."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Orqaga", callback_data="ai_back_to_menu"),
        InlineKeyboardButton("❌ Bekor qilish", callback_data="ai_close"),
    ]])


def get_ai_tone_keyboard(selected: str = None) -> InlineKeyboardMarkup:
    """AI post uslubini tanlash — tanlangan uslub ✅ bilan belgilanadi."""
    tones = [
        ("formal", "👔 Rasmiy"),
        ("friendly", "😊 Do'stona"),
        ("concise", "⚡️ Qisqa"),
        ("engaging", "🎉 Jozibali"),
    ]
    buttons = []
    for key, label in tones:
        mark = " ✅" if key == selected else ""
        buttons.append(InlineKeyboardButton(f"{label}{mark}", callback_data=f"ai_tone:{key}"))
    keyboard = [
        buttons[:2],
        buttons[2:],
        [InlineKeyboardButton("➡️ Rejalashtirishga o'tish", callback_data="ai_studio_sched")],
        [
            InlineKeyboardButton("⬅️ Orqaga", callback_data="ai_back_to_menu"),
            InlineKeyboardButton("❌ Bekor qilish", callback_data="ai_close"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def render_channels_list(channels: list) -> InlineKeyboardMarkup:
    keyboard = []
    for ch in channels:
        ch_id, ch_title = ch[:2]
        tone = ch[2] if len(ch) > 2 else "friendly"
        tone_emoji = {"formal": "👔", "friendly": "😊", "concise": "⚡️", "engaging": "🎉"}.get(tone, "😊")
        keyboard.append([
            InlineKeyboardButton(f"📢 {btn_label(ch_title)}", callback_data="noop"),
            InlineKeyboardButton("❌ O'chirish", callback_data=f"remove_channel:{ch_id}"),
        ])
        keyboard.append([
            InlineKeyboardButton(f"{tone_emoji} Uslub", callback_data=f"tone_menu:{ch_id}"),
        ])
    # "Qo'shish bor, lekin bekor qilish/chiqish yo'q" kamchiligini tuzatish:
    # ro'yxat ostida yangi kanal ulash va oynani yopish tugmalari bo'ladi.
    keyboard.append([InlineKeyboardButton("➕ Yangi kanal/guruh ulash", callback_data="add_channel_start")])
    keyboard.append([InlineKeyboardButton("❌ Yopish", callback_data="close_msg")])
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


def get_cabinet_inline_keyboard() -> InlineKeyboardMarkup:
    """Kabinet & Sozlamalar asosiy menyusi — inline tugmalar (4x2 grid)."""
    keyboard = [
        [
            InlineKeyboardButton("📢 Mening kanallarim", callback_data="cab_channels"),
            InlineKeyboardButton("📊 Kanallar analitikasi", callback_data="cab_analytics"),
        ],
        [
            InlineKeyboardButton("📅 Kutilayotgan postlar", callback_data="cab_pending"),
            InlineKeyboardButton("⏳ Postlar navbati (Queue)", callback_data="cab_queue"),
        ],
        [
            InlineKeyboardButton("💎 Ballar & Litsenziya", callback_data="cab_balance"),
            InlineKeyboardButton("🎁 Kunlik bonus", callback_data="cab_bonus"),
        ],
        [
            InlineKeyboardButton("👥 Do'stlarni taklif", callback_data="cab_referral"),
            InlineKeyboardButton("❌ Yopish", callback_data="close_cabinet"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_extras_inline_keyboard() -> InlineKeyboardMarkup:
    """⚙️ Qo'shimcha funksiyalar — inline menyu.

    Birinchi qator — ✨ Postga Tugma & Reaksiya qo'shish (Post Enhancer):
    tayyor postga 10 tagacha reaksiya va 10 tagacha URL tugma qo'shib,
    kanalga bir zumda yuborish. Konvertor va Tezkor tugmali post o'z
    o'rnida saqlanadi.
    """
    keyboard = [
        [InlineKeyboardButton("✨ Postga Tugma & Reaksiya qo'shish",
                              callback_data="extra_enhancer")],
        [InlineKeyboardButton("🔤 Krill-Lotin konvertor", callback_data="extra_converter")],
        [InlineKeyboardButton("🔗 Tezkor tugmali post", callback_data="extra_quick_btn")],
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


def get_cabinet_back_keyboard() -> InlineKeyboardMarkup:
    """Kabinet ichki sahifalari — Orqaga + Yopish."""
    keyboard = [
        [
            InlineKeyboardButton("⬅️ Orqaga", callback_data="cab_main"),
            InlineKeyboardButton("❌ Yopish", callback_data="close_cabinet"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
