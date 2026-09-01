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


def get_admin_auto_ad_keyboard(status: bool = False) -> InlineKeyboardMarkup:
    """Admin panel: Har 3-5 javob reklamasi boshqaruv klaviaturasi."""
    toggle_label = "🔴 O'chirish" if status else "🟢 Yoqish"
    keyboard = [
        [
            InlineKeyboardButton("✏️ Matnni o'zgartirish", callback_data="adm_ad_edit_text"),
            InlineKeyboardButton(f"🔄 {toggle_label}", callback_data="adm_ad_toggle"),
        ],
        [
            InlineKeyboardButton("⏱ Intervalni sozlash (3-5)", callback_data="adm_ad_set_interval"),
        ],
        [
            InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_back"),
            InlineKeyboardButton("❌ Yopish", callback_data="close_msg"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_ad_interval_keyboard() -> InlineKeyboardMarkup:
    """Reklama intervalini tezkor tanlash klaviaturasi."""
    keyboard = [
        [
            InlineKeyboardButton("3 ta so'rov", callback_data="adm_ad_int:3"),
            InlineKeyboardButton("4 ta so'rov", callback_data="adm_ad_int:4"),
            InlineKeyboardButton("5 ta so'rov", callback_data="adm_ad_int:5"),
        ],
        [
            InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_auto_ad"),
            InlineKeyboardButton("❌ Yopish", callback_data="close_msg"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    """Admin panel inline keyboard — dashboard tugmalari layout."""
    keyboard = [
        [
            InlineKeyboardButton("📊 To'liq statistika", callback_data="adm_stats"),
            InlineKeyboardButton("📣 Ommaviy xabar (Broadcast)", callback_data="adm_broadcast"),
        ],
        [
            InlineKeyboardButton("📢 Majburiy obuna", callback_data="adm_sponsors"),
            InlineKeyboardButton("🎯 Har 3-5 javob reklamasi", callback_data="adm_auto_ad"),
        ],
        [
            InlineKeyboardButton("🎁 Promo-kod yaratish", callback_data="adm_promo"),
            InlineKeyboardButton("⭐️ PRO obuna berish", callback_data="adm_grant_pro"),
        ],
        [InlineKeyboardButton("❌ Yopish", callback_data="close_msg")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_back_keyboard() -> InlineKeyboardMarkup:
    """Admin ichki bo'limlarida Orqaga + Yopish tugmalari."""
    keyboard = [
        [
            InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_back"),
            InlineKeyboardButton("❌ Yopish", callback_data="close_msg"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# AVTOMATIK REKLAMA ROTATSIYA (ad_pool) TUGMALARI
# ============================================================
def get_ad_pool_menu_keyboard(scope: str) -> InlineKeyboardMarkup:
    """Reklama rotatsiya puli boshqaruv menyusi (scope: 'channel' | 'reply')."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Yangi reklama qo'shish", callback_data=f"adp:{scope}:add")],
        [
            InlineKeyboardButton("🗑 Reklama o'chirish", callback_data=f"adp:{scope}:del"),
            InlineKeyboardButton("🧹 Hammasini tozalash", callback_data=f"adp:{scope}:clear"),
        ],
        [InlineKeyboardButton("ℹ️ Rotatsiya haqida", callback_data=f"adp:{scope}:info")],
        [
            InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_back"),
            InlineKeyboardButton("❌ Yopish", callback_data="close_msg"),
        ],
    ])


def get_ad_pool_delete_keyboard(ads: list, scope: str) -> InlineKeyboardMarkup:
    """Har bir reklamani o'chirish tugmasi bilan ko'rsatadi."""
    keyboard = []
    for ad_id, text in ads:
        label = btn_label(text, "Reklama", max_length=28)
        keyboard.append([
            InlineKeyboardButton(f"❌ {label}", callback_data=f"adp:{scope}:rm:{ad_id}")
        ])
    keyboard.append([
        InlineKeyboardButton("⬅️ Orqaga", callback_data=f"adp:{scope}:back"),
        InlineKeyboardButton("❌ Yopish", callback_data="close_msg"),
    ])
    return InlineKeyboardMarkup(keyboard)


def get_ad_pool_back_keyboard(scope: str) -> InlineKeyboardMarkup:
    """Qo'shish/ma'lumot ekranidan reklama menyusiga qaytish."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Menyuga", callback_data=f"adp:{scope}:back"),
            InlineKeyboardButton("❌ Yopish", callback_data="close_msg"),
        ],
    ])


def get_ai_studio_keyboard() -> InlineKeyboardMarkup:
    """AI Studio sub-menu inline keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("✍️ AI Post yaratish", callback_data="studio_ai_post"),
            InlineKeyboardButton("📢 Ochiq kanaldan olish", callback_data="studio_extract"),
        ],
        [
            InlineKeyboardButton("🧠 Kontent-reja", callback_data="studio_content_plan"),
            InlineKeyboardButton("⬅️ Asosiy menyu", callback_data="studio_close"),
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
    """Kabinet asosiy menyusi — inline tugmalar (6 tugma, 2x3 grid)."""
    keyboard = [
        [
            InlineKeyboardButton("📢 Mening kanallarim", callback_data="cab_channels"),
            InlineKeyboardButton("🔤 Krill-Lotin", callback_data="cab_converter"),
        ],
        [
            InlineKeyboardButton("🎁 Kunlik bonus", callback_data="cab_bonus"),
            InlineKeyboardButton("👥 Do'stlarni taklif", callback_data="cab_referral"),
        ],
        [
            InlineKeyboardButton("💎 Ballar & Litsenziya", callback_data="cab_balance"),
            InlineKeyboardButton("📖 Qo'llanma", callback_data="cab_guide"),
        ],
        [
            InlineKeyboardButton("❌ Yopish", callback_data="close_cabinet"),
        ],
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
