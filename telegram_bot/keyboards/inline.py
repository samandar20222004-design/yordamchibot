from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_referral_share_keyboard(referral_link: str) -> InlineKeyboardMarkup:
    """Do'stlarga ulashish uchun tugma."""
    share_text = "Salom! Ushbu bot orqali Telegram kanallaringizga postlarni avtomatik va qulay rejalashtiring:"
    share_url = f"https://t.me/share/url?url={referral_link}&text={share_text}"
    keyboard = [
        [InlineKeyboardButton("🚀 Do'stlarga ulashish", url=share_url)]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_subscription_check_keyboard(unsubscribed_channels: list) -> InlineKeyboardMarkup:
    """Majburiy a'zolik kanallari va tekshirish tugmasi."""
    keyboard = []
    for sponsor in unsubscribed_channels:
        s_id, ch_id, ch_title, ch_url = sponsor
        keyboard.append([InlineKeyboardButton(f"➕ {ch_title}", url=ch_url)])
    keyboard.append([InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_subscription")])
    return InlineKeyboardMarkup(keyboard)

def get_sponsors_delete_keyboard(sponsors: list) -> InlineKeyboardMarkup:
    """Admin uchun homiy kanallarni o'chirish tugmalari."""
    keyboard = []
    for sponsor in sponsors:
        s_id, ch_id, ch_title, ch_url = sponsor
        keyboard.append([InlineKeyboardButton(f"❌ {ch_title} (O'chirish)", callback_data=f"del_sponsor:{s_id}")])
    return InlineKeyboardMarkup(keyboard)
