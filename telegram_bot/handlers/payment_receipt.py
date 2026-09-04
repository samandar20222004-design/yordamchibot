"""💳 Karta to'lov cheklari — Admin Approval Flow handlerlari.

Foydalanuvchi ``subscription.py`` dagi "📸 Chek yuborish" tugmasini bosgach
``RECEIPT_WAIT`` holatiga o'tadi va bu yerda chek (rasm/PDF) qabul qilinadi:
  - chek ``payment_receipts`` jadvaliga ``pending`` holatida yoziladi,
  - barcha adminlarga [✅ Tasdiqlash] / [❌ Rad etish] inline tugmalari bilan
    yuboriladi,
  - admin ✅ bosganda DB'da ATOMIK ravishda status='approved' va PRO muddati
    uzaytiriladi, so'ng foydalanuvchiga o'z tilida tabrik xabari boradi.
"""
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from config import ADMIN_IDS_SET
import database as db
from keyboards.default import get_main_keyboard
from locales.translations import get_text, get_lang
from utils.helpers import html_escape
from handlers.subscription import RECEIPT_WAIT

logger = logging.getLogger(__name__)

# Inline callback prefikslari (har qanday tilda bir xil callback_data).
CB_RECEIPT_APPROVE = "receipt_appr:"
CB_RECEIPT_REJECT = "receipt_rej:"

# Qabul qilinadigan hujjat kengaytmalari/MIME'lar (chek: PDF yoki rasm).
_ACCEPT_DOC_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp")
_ACCEPT_DOC_MIME_PREFIXES = ("application/pdf", "image/")


def _document_acceptable(document) -> bool:
    """Document chek sifatida qabul qilinadimi (PDF yoki rasm)."""
    try:
        fname = (getattr(document, "file_name", "") or "").lower()
        mime = (getattr(document, "mime_type", "") or "").lower()
        if mime and (
            mime.startswith(_ACCEPT_DOC_MIME_PREFIXES[0])
            or mime.startswith(_ACCEPT_DOC_MIME_PREFIXES[1])
        ):
            return True
        return fname.endswith(_ACCEPT_DOC_EXT)
    except Exception:
        return False


def _pick_receipt_media(msg):
    """Xabardan chek media'ni oladi.

    Returns: (media_type, file_id, caption) yoki None (qabul qilinmaydi).
    media_type: 'photo' | 'document'.
    """
    try:
        if getattr(msg, "photo", None):
            return ("photo", msg.photo[-1].file_id, msg.caption or "")
        if getattr(msg, "document", None):
            doc = msg.document
            if not _document_acceptable(doc):
                return None
            return ("document", doc.file_id, msg.caption or "")
        # Stiker/voice va boshqa media — chek emas.
        return None
    except Exception:
        return None


def _get_admin_receipt_keyboard(receipt_id: int, lang: str) -> InlineKeyboardMarkup:
    """Admin [✅ Tasdiqlash] / [❌ Rad etish] klaviaturasi."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            get_text("receipt_btn_approve", lang),
            callback_data=f"{CB_RECEIPT_APPROVE}{receipt_id}",
        )],
        [InlineKeyboardButton(
            get_text("receipt_btn_reject", lang),
            callback_data=f"{CB_RECEIPT_REJECT}{receipt_id}",
        )],
    ])


def _build_receipt_caption(user_id: int, username: str, lang: str) -> str:
    """Adminga yuboriladigan chek xabari matni (admin tilida)."""
    parts = [get_text("receipt_admin_title", lang), ""]
    if username:
        parts.append(get_text("receipt_admin_username_line", lang,
                              username=html_escape(username)))
    parts.append(get_text("receipt_admin_user_line", lang, user_id=user_id))
    parts.append("")
    parts.append(get_text("receipt_admin_ask", lang))
    return "\n".join(parts)


async def receipt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi chek (rasm/PDF) yuborganida — RECEIPT_WAIT holati.

    Chekni DB'ga yozadi va barcha adminlarga inline tugmalar bilan yuboradi.
    Muvaffaqiyatda main menyu bilan tugatadi (ConversationHandler.END).
    """
    msg = update.message
    user = update.effective_user
    user_id = user.id if user else 0
    lang = get_lang(context)

    media = _pick_receipt_media(msg)
    if media is None:
        await msg.reply_text(get_text("receipt_bad_media", lang), parse_mode="HTML")
        return RECEIPT_WAIT  # qayta chek kutamiz

    media_type, file_id, caption = media
    username = (user.username or "") if user else ""
    full_name = (user.full_name or "") if user else ""

    receipt_id = await db.run_db(
        db.save_payment_receipt, user_id, media_type, file_id, caption,
        username, full_name, lang,
    )

    if not receipt_id:
        await msg.reply_text(
            "⚠️ Chekni saqlashda xatolik yuz berdi. Iltimos, qayta yuboring.",
            parse_mode="HTML",
        )
        return RECEIPT_WAIT

    # 📣 Barcha adminlarga yuboramiz (o'zini chetlab).
    for admin_id in ADMIN_IDS_SET:
        if admin_id == user_id:
            continue
        try:
            admin_lang = await db.run_db(db.get_user_language, admin_id)
            cap = _build_receipt_caption(user_id, username, admin_lang)
            markup = _get_admin_receipt_keyboard(receipt_id, admin_lang)
            if media_type == "photo":
                await context.bot.send_photo(
                    chat_id=admin_id, photo=file_id, caption=cap,
                    reply_markup=markup, parse_mode="HTML",
                )
            else:
                await context.bot.send_document(
                    chat_id=admin_id, document=file_id, caption=cap,
                    reply_markup=markup, parse_mode="HTML",
                )
        except Exception as e:
            logger.warning("Chekni adminga (%s) yuborishda xato: %s", admin_id, e)

    is_admin = user_id in ADMIN_IDS_SET
    await msg.reply_text(
        get_text("receipt_saved", lang),
        reply_markup=get_main_keyboard(is_admin),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def receipt_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin chekka [✅ Tasdiqlash] / [❌ Rad etish] bosganida.

    Faqat adminlarni qabul qiladi. Tasdiqlash ATOMIK: DB'da status='approved'
    bo'ladi va PRO muddati uzaytiriladi, so'ng foydalanuvchiga o'z tilida
    tabrik xabari yuboriladi.
    """
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    admin_id = query.from_user.id
    if admin_id not in ADMIN_IDS_SET:
        return None

    data = query.data or ""
    try:
        receipt_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return None

    lang = get_lang(context) or await db.run_db(db.get_user_language, admin_id)

    if data.startswith(CB_RECEIPT_APPROVE):
        res = await db.run_db(db.approve_payment_receipt, receipt_id, admin_id)
        if res.get("ok"):
            # Foydalanuvchiga O'Z TILIDA tabrik
            try:
                await context.bot.send_message(
                    chat_id=res["user_id"],
                    text=get_text("receipt_approved_user",
                                  res.get("language_code") or "uz",
                                  days=res.get("days") or 30),
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning("Tasdiqlash tabrigini yuborishda xato: %s", e)
            try:
                await query.answer(get_text("receipt_admin_done_ok", lang))
            except Exception:
                pass
        else:
            reason = res.get("reason", "")
            if reason == "already_approved":
                await _notify_already_reviewed(query, lang)
            else:
                try:
                    await query.answer("❌ Xatolik yuz berdi.", show_alert=False)
                except Exception:
                    pass
            await _clear_decision_markup(query)
            return None
    elif data.startswith(CB_RECEIPT_REJECT):
        res = await db.run_db(db.reject_payment_receipt, receipt_id, admin_id)
        if res.get("ok"):
            # Foydalanuvchiga O'Z TILIDA rad etish haqida
            try:
                user_lang = await db.run_db(db.get_user_language, res["user_id"])
                await context.bot.send_message(
                    chat_id=res["user_id"],
                    text=get_text("receipt_rejected_user", user_lang),
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning("Rad etish xabarini yuborishda xato: %s", e)
            try:
                await query.answer(get_text("receipt_admin_done_reject", lang))
            except Exception:
                pass
        else:
            await _clear_decision_markup(query)
            return None
    else:
        return None

    # Tugmalarni olib tashlaymiz (chek allaqachon ko'rib chiqildi)
    await _clear_decision_markup(query)
    return None


async def _notify_already_reviewed(query, lang: str):
    try:
        await query.answer(get_text("receipt_admin_already", lang), show_alert=True)
    except Exception:
        pass


async def _clear_decision_markup(query):
    """Admin xabaridan inline tugmalarni olib tashlaydi (idempotent)."""
    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
