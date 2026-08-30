import asyncio
import logging
from telegram import Update
from telegram.error import TelegramError, RetryAfter, TimedOut, NetworkError, BadRequest
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import (
    get_admin_panel_keyboard,
    get_sponsors_keyboard,
    get_cancel_keyboard,
)
from keyboards.inline import get_sponsors_delete_keyboard
from utils.helpers import html_escape, format_post_type_label

logger = logging.getLogger(__name__)

BROADCAST_MESSAGE = 801
ADD_SPONSOR_CHANNEL = 802
SET_CHANNEL_AD = 803
SET_BOT_REPLY_AD = 804

# Broadcast har 20 xabardan keyin shuncha kutadi (Telegram ~30 msg/s limiti).
# 20 xabar / 0.7 s ≈ 28 msg/s — limitdan xavfsiz past.
BROADCAST_BATCH_SIZE = 20
BROADCAST_BATCH_DELAY = 0.7

# Bir vaqtda faqat bitta broadcast ishlashi uchun qulf
_broadcast_lock = asyncio.Lock()

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

async def admin_panel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text(
        "⚙️ <b>Admin Boshqaruv Paneli:</b>\n\nKerakli bo'limni tanlang 👇",
        reply_markup=get_admin_panel_keyboard(),
        parse_mode="HTML",
    )
    return ConversationHandler.END

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    stats = db.get_system_stats()
    text = (
        "📊 <b>Bot Statistikasi:</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{stats['users']} ta</b>\n"
        f"📢 Ulangan kanallar: <b>{stats['channels']} ta</b>\n"
        f"📢 Homiy kanallar: <b>{stats['sponsors']} ta</b>\n"
        f"⏳ Kutilayotgan postlar: <b>{stats['pending']} ta</b>\n"
        f"✅ Yuborilgan postlar: <b>{stats['sent']} ta</b>\n"
        f"🚫 Bekor qilingan postlar: <b>{stats['cancelled']} ta</b>\n"
        f"⚠️ Xatolik bilan tugagan: <b>{stats['failed']} ta</b>"
    )
    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="HTML")

async def admin_all_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    with db.db_cursor() as cur:
        cur.execute("""
            SELECT sp.id, sp.user_id, c.channel_title, sp.post_type, sp.scheduled_time, sp.status
            FROM scheduled_posts sp
            LEFT JOIN channels c ON sp.channel_id = c.channel_id
            ORDER BY sp.id DESC LIMIT 15
        """)
        recent_posts = cur.fetchall()

    if not recent_posts:
        await update.message.reply_text("Hozircha hech qanday post mavjud emas.", reply_markup=get_admin_panel_keyboard())
        return

    text = "📋 <b>Oxirgi 15 ta post:</b>\n\n"
    for p in recent_posts:
        pid, uid, title, ptype, stime, status = p
        title_str = title or "Noma'lum kanal"
        status_emoji = "⏳" if status == "pending" else ("✅" if status == "posted" else "🚫")
        text += f"{status_emoji} <b>#{pid}</b> | {html_escape(title_str)} | {format_post_type_label(ptype)} | {status}\n"

    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="HTML")

async def admin_all_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    channels = db.get_all_channels()
    if not channels:
        await update.message.reply_text("Hozircha ulangan kanallar yo'q.", reply_markup=get_admin_panel_keyboard())
        return

    text = f"📋 <b>Barcha ulangan kanallar ({len(channels)} ta):</b>\n\n"
    for c in channels:
        chid, title, uid, uname = c
        uname_str = f"@{uname}" if uname else f"ID:{uid}"
        text += f"📢 <b>{html_escape(title or 'Kanal')}</b> (<code>{chid}</code>)\n   👤 Egasi: {uname_str}\n\n"

    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="HTML")

async def sponsors_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    sponsors = db.get_active_sponsors()
    text = f"📢 <b>Majburiy a'zolik (Homiy) kanallari ({len(sponsors)} ta):</b>\n\n"
    if sponsors:
        for s in sponsors:
            s_id, ch_id, ch_title, ch_url = s
            text += f"🔹 <b>{html_escape(ch_title)}</b> (<code>{ch_id}</code>)\n   🔗 Havola: {ch_url}\n\n"
    else:
        text += "Hozircha hech qanday homiy kanal qo'shilmagan.\n\n"

    text += "O'chirish uchun pastdagi ro'yxatdan tanlang yoki yangi kanal qo'shing 👇"
    await update.message.reply_text(text, reply_markup=get_sponsors_keyboard(), parse_mode="HTML")
    if sponsors:
        await update.message.reply_text("O'chirish uchun tanlang:", reply_markup=get_sponsors_delete_keyboard(sponsors))

async def start_add_sponsor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text(
        "➕ <b>Homiy kanal qo'shish:</b>\n\n"
        "Kanal ma'lumotlarini quyidagi formatda yuboring:\n"
        "<code>KANAL_ID|KANAL_NOMI|HAVOLA</code>\n\n"
        "👉 <i>Masalan: -1001234567890|Mening Kanalim|[https://t.me/mening_kanalim](https://t.me/mening_kanalim)</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return ADD_SPONSOR_CHANNEL

async def sponsor_channel_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    text = update.message.text.strip()
    parts = text.split("|")
    if len(parts) != 3:
        await update.message.reply_text("❌ Noto'g'ri format. Qaytadan kiriting (KANAL_ID|KANAL_NOMI|HAVOLA):")
        return ADD_SPONSOR_CHANNEL

    ch_id, title, url = parts[0].strip(), parts[1].strip(), parts[2].strip()
    success = db.add_sponsor_channel(ch_id, title, url)
    if success:
        await update.message.reply_text(f"✅ Homiy kanal qo'shildi: <b>{html_escape(title)}</b>", reply_markup=get_admin_panel_keyboard(), parse_mode="HTML")
    else:
        await update.message.reply_text("❌ Saqlashda xatolik yuz berdi.", reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END

async def del_sponsor_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    s_id = int(query.data.split(":")[1])
    db.remove_sponsor_channel(s_id)
    await query.edit_message_text("✅ Homiy kanal ro'yxatdan o'chirildi.")

async def start_set_channel_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    current_ad = db.get_setting("channel_ad_text", "Mavjud emas")
    await update.message.reply_text(
        f"📢 <b>Kanal postlari ostiga chiquvchi reklama:</b>\n\n"
        f"Hozirgi matn:\n<i>{html_escape(current_ad)}</i>\n\n"
        f"Yangi reklama matnini yuboring (o'chirish uchun <code>clear</code> deb yozing):",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return SET_CHANNEL_AD

async def channel_ad_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    text = update.message.text.strip()
    if text.lower() == "clear":
        db.set_setting("channel_ad_text", "")
        await update.message.reply_text("✅ Kanal postlari reklamasi o'chirildi.", reply_markup=get_admin_panel_keyboard())
    else:
        db.set_setting("channel_ad_text", text)
        await update.message.reply_text("✅ Kanal postlari reklamasi muvaffaqiyatli saqlandi!", reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END

async def start_set_bot_reply_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    current_ad = db.get_setting("bot_reply_ad_text", "Mavjud emas")
    await update.message.reply_text(
        f"🤖 <b>Bot javoblari ostiga chiquvchi reklama:</b>\n\n"
        f"Hozirgi matn:\n<i>{html_escape(current_ad)}</i>\n\n"
        f"Yangi reklama matnini yuboring (o'chirish uchun <code>clear</code> deb yozing):",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return SET_BOT_REPLY_AD

async def bot_reply_ad_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    text = update.message.text.strip()
    if text.lower() == "clear":
        db.set_setting("bot_reply_ad_text", "")
        await update.message.reply_text("✅ Bot javoblari reklamasi o'chirildi.", reply_markup=get_admin_panel_keyboard())
    else:
        db.set_setting("bot_reply_ad_text", text)
        await update.message.reply_text("✅ Bot javoblari reklamasi muvaffaqiyatli saqlandi!", reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text(
        "✉️ <b>Barcha foydalanuvchilarga xabar yuborish:</b>\n\nYuboriladigan xabar matnini yozing:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return BROADCAST_MESSAGE

async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    # Avvalgi broadcast hali davom etayotgan bo'lsa — takroriy ishga tushirmaymiz
    if _broadcast_lock.locked():
        await update.message.reply_text(
            "⏳ <b>Avvalgi xabar yuborilishi hali davom etmoqda.</b>\n"
            "Iltimos, yakunlanishini kuting (natija haqida xabar keladi).",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    text = update.message.text
    # DB chaqiruvini event loop'ni bloklamasdan thread'da bajarish
    user_ids = await asyncio.to_thread(db.get_all_user_ids)

    await update.message.reply_text(
        f"⏳ Xabar <b>{len(user_ids)} ta</b> foydalanuvchiga yuborilmoqda...\n"
        f"<i>Bu fon rejimida, batch'lar bilan yuboriladi.</i>",
        parse_mode="HTML"
    )

    # Broadcast fon vazifasi sifatida ishlaydi — admin boshqa buyruqlarni
    # bemalol ishlatishi mumkin, Telegram esa rate-limitga tushmaydi.
    async def _broadcast_task():
        async with _broadcast_lock:
            await _run_broadcast(context.bot, user_ids, text, update.effective_user.id)

    asyncio.create_task(_broadcast_task())
    return ConversationHandler.END


async def _run_broadcast(bot, user_ids, text, admin_id):
    """Broadcastni batch'lar bilan, rate-limit va retry bilan yuborish."""
    sent = 0
    failed = 0
    parse_mode = "HTML"

    for i, uid in enumerate(user_ids):
        delivered = False
        for attempt in range(3):
            try:
                await bot.send_message(chat_id=uid, text=text, parse_mode=parse_mode)
                sent += 1
                delivered = True
                break
            except RetryAfter as e:
                # Telegram aytgan vaqtgacha kutamiz va qayta urinamiz
                wait = min(max(int(getattr(e, "retry_after", 2) or 2), 1), 30)
                await asyncio.sleep(wait)
            except BadRequest:
                # HTML xato bo'lsa — oddiy matn sifatida qayta yuboramiz
                try:
                    await bot.send_message(chat_id=uid, text=text)
                    sent += 1
                except TelegramError:
                    failed += 1
                delivered = True
                break
            except (TimedOut, NetworkError):
                if attempt == 2:
                    failed += 1
                    delivered = True  # 3 ta urinish ham tugadi
                else:
                    await asyncio.sleep(1 + attempt)
            except TelegramError:
                # Bot bloklangan / xabar qabul qilinmagan
                failed += 1
                delivered = True
                break
        # Barcha 3 urinish RetryAfter bilan tugasa ham foydalanuvchi
        # "yuborilmagan" hisobiga kiritilishi kerak (jim o'tib ketmasligi uchun).
        if not delivered:
            failed += 1

        # Har batch'da qisqa pauza — Telegram'ning 30 msg/s limitidan oshmaymiz
        if i and i % BROADCAST_BATCH_SIZE == 0:
            await asyncio.sleep(BROADCAST_BATCH_DELAY)

    try:
        await bot.send_message(
            chat_id=admin_id,
            text=(
                f"✅ <b>Xabar tarqatildi!</b>\n\n"
                f"Yetib bordi: <b>{sent} / {len(user_ids)}</b> ta foydalanuvchiga.\n"
                f"❌ Yuborilmagan: <b>{failed} ta</b>."
            ),
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("Broadcast yakuni haqida admin xabari yuborilmadi")
    logger.info("Broadcast yakunlandi: sent=%d, failed=%d, total=%d", sent, failed, len(user_ids))
