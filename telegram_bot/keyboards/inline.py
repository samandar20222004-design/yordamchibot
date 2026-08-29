from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_referral_share_keyboard(referral_link: str) -> InlineKeyboardMarkup:
    share_text = "Salom! Ushbu bot orqali Telegram kanallaringizga postlarni avtomatik va qulay rejalashtiring:"
    share_url = f"https://t.me/share/url?url={referral_link}&text={share_text}"
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
    return InlineKeyboardMarkup(keyboard)

def render_channels_list(channels: list) -> InlineKeyboardMarkup:
    keyboard = []
    for ch in channels:
        ch_id, ch_title = ch
        keyboard.append([
            InlineKeyboardButton(f"📢 {ch_title}", callback_data="noop"),
            InlineKeyboardButton("❌ O'chirish", callback_data=f"remove_channel:{ch_id}")
        ])
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
    return InlineKeyboardMarkup(keyboard)
