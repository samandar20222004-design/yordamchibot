"""Queue Management UI — navbatdagi postlarni ko'rish, boshqarish, slot sozlamalari."""
import json
import logging
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import get_main_keyboard, get_cancel_keyboard
from utils.helpers import html_escape

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

QUEUE_PAGE_SIZE = 5

# States
QUEUE_MENU = 200
SLOT_ADD = 201


def _post_type_icon(post_type: str) -> str:
    icons = {
        "text": "📝", "photo": "🖼", "video": "🎬",
        "document": "📄", "audio": "🎵", "voice": "🎙",
        "sticker": "😀", "album": "🖼", "animation": "🎞",
    }
    return icons.get(post_type, "📝")


def _content_preview(content: str, max_len: int = 40) -> str:
    if not content:
        return ""
    text = content.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


def _format_queue_item(row, index: int) -> str:
    """Bitta queue postni formatlaydi."""
    post_id, ch_title, post_type, content, sched_time, post_num, ch_id = row
    icon = _post_type_icon(post_type)
    preview = _content_preview(content)
    time_str = sched_time.astimezone(tashkent_tz).strftime("%d-%b %H:%M")
    ch_display = html_escape(ch_title or ch_id or "?")
    preview_part = f' "{html_escape(preview)}"' if preview else ""
    return f"{index}. 🗓 {time_str} | 📢 {ch_display} | {icon}{preview_part}"


def _get_queue_list_keyboard(posts, offset: int, total: int) -> InlineKeyboardMarkup:
    """Queue ro'yxati uchun inline keyboard."""
    rows = []
    for post in posts:
        pid = post[0]
        rows.append([
            InlineKeyboardButton(f"👁 #{pid}", callback_data=f"qview:{pid}"),
            InlineKeyboardButton("🗑", callback_data=f"qdel:{pid}"),
            InlineKeyboardButton("⏩", callback_data=f"qpush:{pid}"),
        ])

    # Pagination tugmalari
    nav = []
    if offset > 0:
        prev_off = max(0, offset - QUEUE_PAGE_SIZE)
        nav.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"qpage:{prev_off}"))
    if offset + QUEUE_PAGE_SIZE < total:
        next_off = offset + QUEUE_PAGE_SIZE
        nav.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"qpage:{next_off}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton("⚙️ Slotlarni sozlash", callback_data="qslots:show")])
    rows.append([InlineKeyboardButton("❌ Yopish", callback_data="qclose")])
    return InlineKeyboardMarkup(rows)


def _get_post_detail_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Bitta postni ko'rish uchun keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑 O'chirish", callback_data=f"qdel:{post_id}"),
            InlineKeyboardButton("⏩ Keyingi slot", callback_data=f"qpush:{post_id}"),
        ],
        [InlineKeyboardButton("⬅️ Ro'yxatga qaytish", callback_data="qpage:0")],
    ])


def _get_slots_keyboard(slots: list) -> InlineKeyboardMarkup:
    """Slot sozlamalari keyboard."""
    rows = []
    for i, slot in enumerate(slots):
        rows.append([
            InlineKeyboardButton(f"🕐 {slot}", callback_data="qslots:noop"),
            InlineKeyboardButton("❌", callback_data=f"qslots:rm:{i}"),
        ])
    rows.append([InlineKeyboardButton("➕ Yangi slot qo'shish", callback_data="qslots:add")])
    rows.append([InlineKeyboardButton("🔄 Default slotlar", callback_data="qslots:reset")])
    rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="qpage:0")])
    return InlineKeyboardMarkup(rows)


# ============================================================
# HANDLERS
# ============================================================

async def queue_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Queue ro'yxatini ko'rsatadi."""
    user_id = update.effective_user.id
    is_admin = (user_id in ADMIN_IDS_SET)
    total = await db.run_db(db.get_queue_post_count, user_id)

    if total == 0:
        await update.message.reply_text(
            "📚 <b>Navbat (Queue)</b>\n\n"
            "Hozircha navbatda postlar yo'q.\n"
            "Yangi post yaratib, <b>⚡️ Navbatga qo'yish</b> tugmasini bosing.",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    posts = await db.run_db(db.get_queue_posts, user_id, 0, QUEUE_PAGE_SIZE)
    text_lines = [f"📚 <b>Navbatdagi postlar</b> ({total} ta):\n"]
    for i, post in enumerate(posts, 1):
        text_lines.append(_format_queue_item(post, i))
    text = "\n".join(text_lines)

    keyboard = _get_queue_list_keyboard(posts, 0, total)
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    return QUEUE_MENU


async def queue_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sahifalash tugmasi."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    offset = int(query.data.split(":")[1])

    total = await db.run_db(db.get_queue_post_count, user_id)
    if total == 0:
        try:
            await query.edit_message_text(
                "📚 <b>Navbat (Queue)</b>\n\nNavbatda postlar yo'q.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Yopish", callback_data="qclose")]]),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return QUEUE_MENU

    posts = await db.run_db(db.get_queue_posts, user_id, offset, QUEUE_PAGE_SIZE)
    text_lines = [f"📚 <b>Navbatdagi postlar</b> ({total} ta, {offset + 1}-{min(offset + QUEUE_PAGE_SIZE, total)}):\n"]
    for i, post in enumerate(posts, offset + 1):
        text_lines.append(_format_queue_item(post, i))
    text = "\n".join(text_lines)

    keyboard = _get_queue_list_keyboard(posts, offset, total)
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    return QUEUE_MENU


async def queue_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bitta postni ko'rish."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    post_id = int(query.data.split(":")[1])

    post = await db.run_db(db.get_queue_post_detail, post_id, user_id)
    if not post:
        try:
            await query.edit_message_text("⚠️ Post topilmadi yoki allaqachon o'chirilgan.")
        except Exception:
            pass
        return QUEUE_MENU

    (pid, uid, ch_id, ch_title, post_type, content, file_id,
     btn_text, btn_url, enable_reactions, delete_after_hours,
     sched_time, post_num) = post

    time_str = sched_time.astimezone(tashkent_tz).strftime("%Y-%m-%d %H:%M")
    ch_display = html_escape(ch_title or ch_id or "?")
    type_labels = {
        "text": "📝 Matn", "photo": "🖼 Rasm", "video": "🎬 Video",
        "document": "📄 Hujjat", "audio": "🎵 Audio", "voice": "🎙 Ovozli",
        "sticker": "😀 Stiker", "album": "🖼 Albom", "animation": "🎞 GIF",
    }
    type_text = type_labels.get(post_type, "📝 Xabar")

    text = (
        f"👁 <b>Post #{pid}</b>\n\n"
        f"📢 Kanal: {ch_display}\n"
        f"📦 Turi: {type_text}\n"
        f"⏰ Vaqt: {time_str}\n"
    )
    if content:
        preview = content[:300]
        if len(content) > 300:
            preview += "…"
        text += f"\n📋 Matn:\n{html_escape(preview)}"
    if btn_text and btn_url:
        text += f"\n🔘 Tugma: {html_escape(btn_text)}"
    if enable_reactions:
        text += "\n👍 Reaksiyalar: Yoqilgan"
    if delete_after_hours > 0:
        text += f"\n⏳ Auto-o'chirish: {delete_after_hours} soat"

    keyboard = _get_post_detail_keyboard(pid)
    try:
        await query.edit_message_text(text[:4096], reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    return QUEUE_MENU


async def queue_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Postni navbatdan o'chirish."""
    query = update.callback_query
    await query.answer("🗑 O'chirildi!")
    user_id = query.from_user.id
    post_id = int(query.data.split(":")[1])

    await db.run_db(db.cancel_post, post_id, user_id)

    # Ro'yxatni yangilash
    total = await db.run_db(db.get_queue_post_count, user_id)
    if total == 0:
        try:
            await query.edit_message_text(
                "📚 <b>Navbat (Queue)</b>\n\n"
                "Navbatda postlar yo'q.\n"
                "Yangi post yaratib, <b>⚡️ Navbatga qo'yish</b> tugmasini bosing.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Yopish", callback_data="qclose")]]),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return QUEUE_MENU

    posts = await db.run_db(db.get_queue_posts, user_id, 0, QUEUE_PAGE_SIZE)
    text_lines = [f"📚 <b>Navbatdagi postlar</b> ({total} ta):\n"]
    for i, post in enumerate(posts, 1):
        text_lines.append(_format_queue_item(post, i))
    text = "\n".join(text_lines)

    keyboard = _get_queue_list_keyboard(posts, 0, total)
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    return QUEUE_MENU


async def queue_push_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Postni keyingi slotga surish."""
    query = update.callback_query
    user_id = query.from_user.id
    post_id = int(query.data.split(":")[1])

    post = await db.run_db(db.get_queue_post_detail, post_id, user_id)
    if not post:
        await query.answer("⚠️ Post topilmadi!", show_alert=True)
        return QUEUE_MENU

    ch_id = post[2]
    now = datetime.now(tashkent_tz)
    slots = await db.run_db(db.get_queue_slots, user_id)

    # Hozirgi vaqtdan keyingi bo'sh slotni topish
    occupied = await db.run_db(db.get_queue_occupied_times, user_id, ch_id, now.date())
    # Hozirgi postning vaqtini occupied dan olib tashlash (chunki u suriladi)
    current_time = post[11].astimezone(tashkent_tz)
    occupied = [(h, m) for h, m in occupied if not (h == current_time.hour and m == current_time.minute)]

    slot_dt, label = db.find_next_queue_slot(slots, occupied, now)
    if not slot_dt:
        # Ertaga urinish
        tomorrow = now + timedelta(days=1)
        tomorrow_start = tashkent_tz.localize(
            datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0)
        )
        occ_tom = await db.run_db(db.get_queue_occupied_times, user_id, ch_id, tomorrow.date())
        slot_dt, label = db.find_next_queue_slot(slots, occ_tom, tomorrow_start)

    if not slot_dt:
        await query.answer("⚠️ Bo'sh slot topilmadi!", show_alert=True)
        return QUEUE_MENU

    await db.run_db(db.update_post_time, post_id, slot_dt, user_id=user_id)
    await query.answer(f"⏩ {label} {slot_dt.strftime('%H:%M')} ga surildi!")

    # Ro'yxatni yangilash
    total = await db.run_db(db.get_queue_post_count, user_id)
    posts = await db.run_db(db.get_queue_posts, user_id, 0, QUEUE_PAGE_SIZE)
    text_lines = [f"📚 <b>Navbatdagi postlar</b> ({total} ta):\n"]
    for i, p in enumerate(posts, 1):
        text_lines.append(_format_queue_item(p, i))
    text = "\n".join(text_lines)

    keyboard = _get_queue_list_keyboard(posts, 0, total)
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    return QUEUE_MENU


async def queue_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Queue oynasini yopish."""
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    return ConversationHandler.END


# ============================================================
# SLOT SETTINGS
# ============================================================

async def queue_slots_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Slot sozlamalari: ko'rish, qo'shish, o'chirish, reset."""
    query = update.callback_query
    data = query.data  # "qslots:show", "qslots:add", "qslots:rm:2", "qslots:reset", "qslots:noop"
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else "show"
    user_id = query.from_user.id

    if action == "noop":
        await query.answer()
        return SLOT_ADD

    if action == "show":
        await query.answer()
        slots = await db.run_db(db.get_queue_slots, user_id)
        text = (
            f"⚙️ <b>Slot sozlamalari</b>\n\n"
            f"Mavjud slotlar: <code>{', '.join(slots)}</code>\n\n"
            f"Har kuni shu vaqtlarda postlar avtomatik rejalashtiriladi."
        )
        keyboard = _get_slots_keyboard(slots)
        try:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass
        return SLOT_ADD

    if action == "rm":
        await query.answer("❌ O'chirildi!")
        idx = int(parts[2])
        slots = await db.run_db(db.get_queue_slots, user_id)
        if 0 <= idx < len(slots):
            removed = slots.pop(idx)
            if slots:  # Kamida bitta slot qolishi kerak
                await db.run_db(db.set_queue_slots, user_id, slots)
            else:
                # Oxirgi slotni o'chirib bo'lmaydi — default qaytaramiz
                await query.answer("⚠️ Kamida bitta slot bo'lishi kerak!", show_alert=True)
                slots = await db.run_db(db.get_queue_slots, user_id)

        text = (
            f"⚙️ <b>Slot sozlamalari</b>\n\n"
            f"Mavjud slotlar: <code>{', '.join(slots)}</code>\n\n"
            f"Har kuni shu vaqtlarda postlar avtomatik rejalashtiriladi."
        )
        keyboard = _get_slots_keyboard(slots)
        try:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass
        return SLOT_ADD

    if action == "add":
        await query.answer()
        await query.message.reply_text(
            "➕ <b>Yangi slot qo'shish</b>\n\n"
            "Vaqt formati: <code>HH:MM</code>\n"
            "Masalan: <code>22:00</code>",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
        context.user_data["slot_add_pending"] = True
        return SLOT_ADD

    if action == "reset":
        await query.answer("🔄 Default slotlar qaytarildi!")
        await db.run_db(db.set_queue_slots, user_id, list(db.DEFAULT_QUEUE_SLOTS))
        slots = list(db.DEFAULT_QUEUE_SLOTS)
        text = (
            f"⚙️ <b>Slot sozlamalari</b>\n\n"
            f"Mavjud slotlar: <code>{', '.join(slots)}</code>\n\n"
            f"Default slotlar qaytarildi."
        )
        keyboard = _get_slots_keyboard(slots)
        try:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass
        return SLOT_ADD

    return SLOT_ADD


async def slot_add_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yangi slot qo'shish uchun matn qabul qilish."""
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id

    if text in ("🔙 Orqaga", "🏠 Bosh menyu"):
        context.user_data.pop("slot_add_pending", None)
        slots = await db.run_db(db.get_queue_slots, user_id)
        slot_text = (
            f"⚙️ <b>Slot sozlamalari</b>\n\n"
            f"Mavjud slotlar: <code>{', '.join(slots)}</code>"
        )
        keyboard = _get_slots_keyboard(slots)
        await update.message.reply_text(slot_text, reply_markup=keyboard, parse_mode="HTML")
        return SLOT_ADD

    # Vaqt formatini tekshirish
    try:
        hh, mm = text.split(":")
        hh, mm = int(hh), int(mm)
        assert 0 <= hh < 24 and 0 <= mm < 60
    except Exception:
        await update.message.reply_text(
            "⚠️ Noto'g'ri format! <code>HH:MM</code> shaklida yozing.\nMasalan: <code>22:00</code>",
            parse_mode="HTML",
        )
        return SLOT_ADD

    new_slot = f"{hh:02d}:{mm:02d}"
    slots = await db.run_db(db.get_queue_slots, user_id)

    if new_slot in slots:
        await update.message.reply_text(f"⚠️ <code>{new_slot}</code> allaqachon mavjud!", parse_mode="HTML")
        return SLOT_ADD

    if len(slots) >= 10:
        await update.message.reply_text("⚠️ Maksimal 10 ta slot qo'shish mumkin!", parse_mode="HTML")
        return SLOT_ADD

    slots.append(new_slot)
    slots.sort()
    await db.run_db(db.set_queue_slots, user_id, slots)
    context.user_data.pop("slot_add_pending", None)

    slot_text = (
        f"✅ Slot qo'shildi: <code>{new_slot}</code>\n\n"
        f"⚙️ <b>Slot sozlamalari</b>\n\n"
        f"Mavjud slotlar: <code>{', '.join(slots)}</code>"
    )
    keyboard = _get_slots_keyboard(slots)
    await update.message.reply_text(slot_text, reply_markup=keyboard, parse_mode="HTML")
    return SLOT_ADD
