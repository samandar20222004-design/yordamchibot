from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from utils.helpers import md_escape, format_post_code, format_schedule_line

def get_referral_share_keyboard(ref_link: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Do'stlarga ulashish", url=f"https://t.me/share/url?url={ref_link}&text=Telegram+kanallarga+postlarni+avtomatik+rejalashtiruvchi+aqlli+bot!")]
    ])

def get_subscription_check_keyboard(sponsors: list):
    buttons = []
    for s_id, ch_id, ch_title, ch_url in sponsors:
        buttons.append([InlineKeyboardButton(f"➕ {ch_title}", url=ch_url)])
    buttons.append([InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_subscription")])
    return InlineKeyboardMarkup(buttons)

def render_sponsors_list(sponsors):
    if not sponsors:
        return "📢 Hozircha majburiy obuna uchun homiy kanallar ulanmagan.", None
    text = "📢 Majburiy a'zolik homiy kanallari:\n\n"
    keyboard = []
    for s in sponsors:
        s_id, ch_id, ch_title, ch_url = s
        text += f"🔹 {ch_title}\n   🔗 {ch_url}\n"
        keyboard.append([InlineKeyboardButton(f"🗑 {ch_title} o'chirish", callback_data=f"del_sponsor:{s_id}")])
    return text, InlineKeyboardMarkup(keyboard)

def render_pending_list(posts, title, show_owner=False, user_code=None):
    if not posts:
        return "📭 Hozircha rejalashtirilgan postlaringiz yo'q.", None
    text = f"{title}\n\n"
    keyboard = []
    scope = "all" if show_owner else "mine"
    for p in posts:
        pid, c_title, p_type, s_time, user_post_number, rec_type, rec_day, rec_time = p
        code_label = format_post_code(user_code, user_post_number) if user_code else f"#{user_post_number or pid}"
        ch_title = c_title if c_title else "Kanal/Guruh"
        schedule_line = format_schedule_line(s_time, rec_type, rec_day, rec_time)
        
        text += f"📌 Post: {code_label} | {ch_title}\n{schedule_line} | Turi: {p_type}\n\n"
        
        keyboard.append([
            InlineKeyboardButton(f"✏️ {code_label} vaqtini o'zgartirish", callback_data=f"edit_time:{pid}"),
            InlineKeyboardButton(f"❌ {code_label} bekor qilish", callback_data=f"cancel_post:{pid}:{scope}")
        ])
    return text, InlineKeyboardMarkup(keyboard)

def render_channels_list(channels, show_owner=False):
    if not channels:
        return "📭 Hozircha ulangan kanal/guruh mavjud emas.", None
    text = "📢 Ulangan kanal/guruhlar:\n\n"
    keyboard = []
    scope = "all" if show_owner else "mine"
    for ch in channels:
        if show_owner:
            channel_id, channel_title, owner_id, owner_username = ch
        else:
            channel_id, channel_title = ch
        title = channel_title if channel_title else "Nomsiz"
        line = f"🔹 {title} (ID: {channel_id})"
        if show_owner:
            owner_label = f"@{owner_username}" if owner_username else str(owner_id)
            line += f"\n   👤 {owner_label}"
        text += line + "\n"
        keyboard.append([InlineKeyboardButton(f"🗑 {title} o'chirish", callback_data=f"remove_channel:{channel_id}:{scope}")])
    return text, InlineKeyboardMarkup(keyboard)
