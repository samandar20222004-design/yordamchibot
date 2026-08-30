from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


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
        keyboard.append([InlineKeyboardButton(f"➕ {ch_title}", url=ch_url)])
    keyboard.append([InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_subscription")])
    return InlineKeyboardMarkup(keyboard)

def get_sponsors_delete_keyboard(sponsors: list) -> InlineKeyboardMarkup:
    keyboard = []
    for sponsor in sponsors:
        s_id, ch_id, ch_title, ch_url = sponsor
        keyboard.append([InlineKeyboardButton(f"❌ {ch_title} (O'chirish)", callback_data=f"del_sponsor:{s_id}")])
    # Ro'yxat oynasini yopish tugmasi — admin ekranda keraksiz xabar qolib ketmasligi uchun
    keyboard.append([InlineKeyboardButton("❌ Yopish", callback_data="close_msg")])
    return InlineKeyboardMarkup(keyboard)

def render_channels_list(channels: list) -> InlineKeyboardMarkup:
    keyboard = []
    for ch in channels:
        ch_id, ch_title = ch
        keyboard.append([
            InlineKeyboardButton(f"📢 {ch_title}", callback_data="noop"),
            InlineKeyboardButton("❌ O'chirish", callback_data=f"remove_channel:{ch_id}")
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
        keyboard.append([
            InlineKeyboardButton(f"✏️ {code_label} vaqtini o'zgartirish", callback_data=f"edit_time:{pid}"),
            InlineKeyboardButton(f"❌ {code_label} bekor qilish", callback_data=f"cancel_post:{pid}")
        ])
    # Ro'yxatni yangilash (amal bajargandan keyin holatni ko'rish) va yopish tugmalari
    keyboard.append([
        InlineKeyboardButton("🔄 Yangilash", callback_data="pending_refresh"),
        InlineKeyboardButton("❌ Yopish", callback_data="close_msg"),
    ])
    return InlineKeyboardMarkup(keyboard)
