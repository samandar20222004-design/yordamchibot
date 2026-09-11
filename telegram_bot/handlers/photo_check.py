import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ConversationHandler,
)

from config import ADMIN_IDS_SET
import database as db
from keyboards.callback_data import CB_PHOTO_APPROVE, CB_PHOTO_REJECT, cb
from utils.fsm_state import active_conversation_state
# 6-bosqich: rasm tekshiruvi orqali PRO berish — 'manage_users' ruxsati.
from services.rbac_service import PERM_MANAGE_USERS, has_permission

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# QAT'IY HOLAT GATE (spam tuzatish)
# ---------------------------------------------------------------------------
# Eski xato: ``handle_user_photo`` HAR QANDAY rasmni (foydalanuvchi yangi post
# rejalashtirayotganda albom yuborsa ham) ushlab, rasmni adminga yuborar va
# "📸 Rasmingiz adminga yuborildi. Tasdiqlanishi kutilmoqda." deb har bir
# rasm uchun javob qaytarardi.
#
# YANGI QOIDA: rasm adminga FAQAT foydalanuvchi ANIQ moderatsiya holatida
# bo'lganda yuboriladi:
#   * ConversationHandler holati ``PHOTO_CHECK_WAIT`` ("Moderatsiya"), yoki
#   * ``context.user_data[UD_PHOTO_CHECK_WAIT]`` belgisi (moderatsiya oqimini
#     boshlagan kod buni o'rnatadi).
# Boshqa BARCHA holatda — yangi post oqimi (new_post states), AI Studio,
# to'lov oqimi, oddiy chat — rasm hech qachon adminga bormaydi va foydalanuvchiga
# ortiqcha xabar chiqmaydi (update jim yutiladi).
# ---------------------------------------------------------------------------

# "Moderatsiya" (qo'lda rasm tekshiruvi) holati — main ConversationHandler'da
# ro'yxatdan o'tkaziladi (handlers/__init__.py).
PHOTO_CHECK_WAIT = 604

# user_data kaliti: moderatsiya oqimi boshqa kod orqali (masalan, inline entry)
# boshlanganda rasmlar shu belgi bilan qabul qilinadi.
UD_PHOTO_CHECK_WAIT = "photo_check_wait"

# Handler tanlash bosqichidayoq `/ai` captionli rasmlarni chiqarib tashlaymiz.
# Callback ichida shunchaki `return` qilish yetarli emas: bir handler group'ida
# birinchi mos MessageHandler keyingi Vision handleriga navbat bermaydi.
_AI_PHOTO_CAPTION = filters.CaptionRegex(r"(?i)^/ai(?:@[a-z0-9_]+)?(?:\s|$)")


# Helper: check if photo has /ai caption (avoid interfering with AI Studio)
def _is_ai_photo_command(msg) -> bool:
    caption = (getattr(msg, "caption", "") or "").strip().lower().split()
    if not caption:
        return False
    cmd = caption[0].split("@")[0]
    return cmd == "/ai"


def _photo_moderation_allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Rasm adminga yuborilishi MUMKIN bo'lgan holatni tekshiradi.

    Faqat ikkita yo'l bor:
      1) foydalanuvchi ``PHOTO_CHECK_WAIT`` ("Moderatsiya") dialog holatida;
      2) ``user_data`` da moderatsiya belgisi qo'yilgan (context tekshiruvi).
    Boshqa hollarda (yangi post, AI, to'lov, dialogdan tashqari) → False.
    """
    ud = getattr(context, "user_data", None) or {}
    try:
        flag = ud.get(UD_PHOTO_CHECK_WAIT)
    except Exception:
        flag = None
    if flag:
        return True
    state = active_conversation_state(getattr(context, "application", None), update)
    return state == PHOTO_CHECK_WAIT


def _clear_moderation_marker(context) -> None:
    """Moderatsiya belgisini tozalaydi (bitta rasm — bitta tekshiruv)."""
    ud = getattr(context, "user_data", None)
    if ud is not None:
        try:
            ud.pop(UD_PHOTO_CHECK_WAIT, None)
        except Exception:
            pass


# 1. User photo handler: forwards photo to admin with approval buttons
async def handle_user_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Moderatsiya' holatida yuborilgan rasmni adminga yo'naltiradi.

    QAT'IY GATE: agar foydalanuvchi moderatsiya holatida/so'rovida bo'lmasa,
    funksiya JIM qaytadi — rasm adminga yuborilmaydi va foydalanuvchiga hech
    qanday xabar chiqmaydi. Bu yangi post rejalashtirish jarayonida (new_post
    states) albom rasmlari tasodifan adminga ketib qolishining oldini oladi.
    """
    user = update.effective_user
    if not user:
        return

    # Skip if photo has /ai caption (AI Studio flow)
    if _is_ai_photo_command(update.message):
        return

    photo = update.message.photo[-1] if update.message.photo else None
    if not photo:
        return

    # 🚦 QAT'IY HOLAT TEKSHIRUVI — faqat "Moderatsiya" holatida adminga yuboramiz.
    if not _photo_moderation_allowed(update, context):
        # Yangi post oqimi / AI Studio / to'lov / oddiy chat rasmi — JIM yutamiz:
        # hech qachon adminga bormaydi, ortiqcha xabarlar chiqmaydi.
        return

    user_id = user.id
    photo_file_id = photo.file_id

    # Send photo to admin with buttons
    admin_id = next(iter(ADMIN_IDS_SET)) if ADMIN_IDS_SET else None
    if not admin_id:
        logger.error("No admin ID configured")
        return

    keyboard = [
        [
            InlineKeyboardButton("✅ Tasdiqlash", callback_data=cb(CB_PHOTO_APPROVE, user_id)),
            InlineKeyboardButton("❌ Rad etish", callback_data=cb(CB_PHOTO_REJECT, user_id)),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    caption_text = f"🆔 Foydalanuvchi ID: {user_id}\n📷 Rasm yuborildi."

    try:
        await context.bot.send_photo(
            chat_id=admin_id,
            photo=photo_file_id,
            caption=caption_text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("Rasmni adminga yuborishda xato (user %s): %s", user_id, e)
        return

    # Reply to user that photo was sent to admin
    try:
        await update.message.reply_text(
            "📸 Rasmingiz adminga yuborildi. Tasdiqlanishi kutilmoqda."
        )
    except Exception:
        pass

    # Bitta moderatsiya so'rovi bitta rasm uchun — marker tozalanadi,
    # conversation (agar shu holatda bo'lsa) yakunlanadi.
    _clear_moderation_marker(context)
    return ConversationHandler.END


# 2. Admin callback: approve or reject PRO grant
async def handle_admin_check_photo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query.from_user.id in ADMIN_IDS_SET:
        await query.answer("Ruxsat yo'q.", show_alert=True)
        return
    if not has_permission(query.from_user.id, PERM_MANAGE_USERS):
        await query.answer("❌ Sizda foydalanuvchilarga PRO berish uchun ruxsat yo'q.",
                           show_alert=True)
        return

    data = query.data  # format: "cph:a:{user_id}" yoki "cph:r:{user_id}"
    parts = data.split(":")
    if len(parts) != 3:
        await query.answer("Noto'g'ri callback data.", show_alert=True)
        return

    action = parts[1]  # 'a' (tasdiq) yoki 'r' (rad)
    try:
        target_user_id = int(parts[2])
    except ValueError:
        await query.answer("User ID xatosi.", show_alert=True)
        return

    if action == "a":
        # Activate PRO for user (30 days)
        success = await db.run_db(db.set_user_plan, target_user_id, "pro", days=30,
                                  admin_id=query.from_user.id)
        if success:
            # Notify user
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=(
                        "🎉 <b>Tabriklaymiz!</b>\n\n"
                        f"Sizga <b>30 kunlik PRO tarif</b> berildi!\n"
                        "Barcha PRO imkoniyatlardan foydalanishingiz mumkin."
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
            # Confirm to admin
            await query.edit_message_text(
                text=f"✅ <b>Tasdiqlandi!</b>\n\n"
                f"Foydalanuvchi <code>{target_user_id}</code> ga PRO berildi.",
                parse_mode="HTML",
            )
        else:
            await query.answer("Xatolik yuz berdi.", show_alert=True)
    elif action == "r":
        # Reject: just inform admin, optionally notify user
        await query.edit_message_text(
            text="❌ <b>Rad etildi.</b>\n\n"
            "Foydalanuvchi PRO tarifi rad etildi.",
            parse_mode="HTML",
        )


# Register handlers with the application
def register(app):
    # User photo: any photo message (but skip /ai captions). Handler GLOBAL
    # bo'lib qoladi, lekin ICHIDA qat'iy holat gate'i bor — moderatsiya holatida
    # bo'lmagan rasm hech qachon adminga yuborilmaydi va hech qanday xabar
    # chiqarmaydi (yangi post oqimi, AI Studio va boshqa dialoglar uchun).
    app.add_handler(
        MessageHandler(
            filters.PHOTO & ~filters.COMMAND & ~_AI_PHOTO_CAPTION,
            handle_user_photo,
        )
    )
    # Admin callback for check photo
    app.add_handler(
        CallbackQueryHandler(
            handle_admin_check_photo_callback,
            pattern=r"^cph:a:|^cph:r:",
        )
    )
