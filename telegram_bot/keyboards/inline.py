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

def get_subscription_check_keyboard(unsubscribed_channels: list) -> InlineKeyboardMarkup:
    keyboard = []
    for sponsor in unsubscribed_channels:
        s_id, ch_id, ch_title, ch_url = sponsor
        keyboard.append([
            InlineKeyboardButton(f"➕ {btn_label(ch_title, 'Homiy kanal')}", url=ch_url)
        ])
    keyboard.append([InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_subscription")])
    return InlineKeyboardMarkup(keyboard)

def get_cache_actions_keyboard() -> InlineKeyboardMarkup:
    """DB/kesh holati oynasi uchun tugmalar."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Keshlarni tozalash", callback_data="cache_clear")],
        [InlineKeyboardButton("❌ Yopish", callback_data="close_msg")],
    ])


def get_sponsors_delete_keyboard(sponsors: list) -> InlineKeyboardMarkup:
    keyboard = []
    for sponsor in sponsors:
        s_id, ch_id, ch_title, ch_url = sponsor
        label = btn_label(ch_title, "Homiy kanal", max_length=28)
        keyboard.append([
            InlineKeyboardButton(f"❌ {label} (O'chirish)", callback_data=f"del_sponsor:{s_id}")
        ])
    # Ro'yxat oynasini yopish tugmasi — admin ekranda keraksiz xabar qolib ketmasligi uchun
    keyboard.append([InlineKeyboardButton("❌ Yopish", callback_data="close_msg")])
    return InlineKeyboardMarkup(keyboard)


def get_admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    """Admin panel inline keyboard — dashboard tugmalari."""
    keyboard = [
        [
            InlineKeyboardButton("📊 To'liq statistika", callback_data="adm_stats"),
            InlineKeyboardButton("🎁 Promo-kod yaratish", callback_data="adm_promo"),
        ],
        [
            InlineKeyboardButton("⭐️ Foydalanuvchiga PRO berish", callback_data="adm_grant_pro"),
            InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"),
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
