# -*- coding: utf-8 -*-
"""📷 Qo'lda rasm tekshiruvi (admin tasdiqlashi) — moderatsiya oqimi.

Oqim: foydalanuvchi "Moderatsiya" holatida rasm yuboradi → bot rasmni
admin panelga ✅/❌ tugmalari bilan forward qiladi → admin qaroriga qarab
foydalanuvchiga natija xabari (va kerak bo'lsa 30 kunlik PRO) yuboriladi.

🌐 TIL (uz/ru/en): bu fayldagi barcha matn avval qotirilgan o'zbekcha
satrlar edi — shu sababli rus/ingliz foydalanuvchi va adminlar xabarni
tushunmasdi. Endi har bir matn ``locales`` lug'atidan foydalanuvchining
(yoki adminning) tiliga qarab olinadi: ``pc_*`` kalitlari.
"""
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
from locales.translations import get_lang, safe_t
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
async def _photo_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Rasm egasining tilini aniqlaydi (uz/ru/en).

    Ketma-ketlik: (1) ``context.user_data['lang']`` keshi — so'rovsiz, eng
    tez yo'l; (2) bo'lmasa DB'dan so'raladi va keshga yoziladi. DB stubi
    bo'lmagan test muhitida ikkinchi qadam jim o'tkazib yuboriladi va
    standart til qayadi — oqim hech qachon xato bilan uzilmasligi kerak.
    """
    cached = get_lang(context)
    ud = getattr(context, "user_data", None)
    if ud is not None and "lang" in ud:
        return cached
    try:
        user = update.effective_user
        if user is not None:
            from database import get_user_language  # local import: cycle yo'q
            lang = await db.run_db(get_user_language, user.id)
            if lang:
                from locales.translations import normalize_lang, set_lang_cache
                lang = normalize_lang(lang)
                set_lang_cache(context, lang)
                return lang
    except Exception:
        logger.debug("photo_check: til DB'dan o'qilmadi, standart til ishlatiladi",
                     exc_info=True)
    return cached


def _pc_text(key: str, lang: str, fallback_key: str = "") -> str:
    """``pc_*`` kalitini o'qiydi; kalit bo'sh/yo'q bo'lsa zaxira matn qaytadi.

    ``safe_t`` kalit yo'q bo'lsa kalit nomini qaytargani uchun foydalanuvchiga
    ``pc_sent_user`` ko'rinib qolmasligi kerak — shu sababli qo'shimcha tekshiruv.
    """
    text = safe_t(key, lang)
    if text and text != key:
        return text
    if fallback_key:
        fb = safe_t(fallback_key, lang)
        if fb and fb != fallback_key:
            return fb
    return text or key


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


def admin_photo_keyboard(user_id: int, lang: str = "uz") -> InlineKeyboardMarkup:
    """Admin uchun ✅/❌ klaviaturasi — tugma matnlari ADMIN tilida."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(_pc_text("pc_btn_approve", lang),
                             callback_data=cb(CB_PHOTO_APPROVE, user_id)),
        InlineKeyboardButton(_pc_text("pc_btn_reject", lang),
                             callback_data=cb(CB_PHOTO_REJECT, user_id)),
    ]])


def admin_photo_caption(user_id: int, lang: str = "uz") -> str:
    """Admin ko'radigan caption — foydalanuvchi ID si bilan, tilga mos."""
    return _pc_text("pc_admin_caption", lang).replace("{user_id}", str(user_id))


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

    # 🌐 Admin ham o'z tilida ko'radi: tugmalar va caption admin tilidan
    # (admin topilmagan bo'lsa — foydalanuvchi tilidan) olinadi.
    admin_lang = await _photo_lang(update, context)
    reply_markup = admin_photo_keyboard(user_id, admin_lang)
    caption_text = admin_photo_caption(user_id, admin_lang)

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

    # Foydalanuvchiga xabar — uning TILIDA (uz/ru/en).
    # MUHIM: UZ varianti "adminga yuborildi" va "Tasdiqlanishi kutilmoqda"
    # iboralarini saqlab qolishi shart (spam-regressiya testi shu iboralarni
    # izlaydi) — tarjima uzilmasin.
    user_lang = await _photo_lang(update, context)
    try:
        await update.message.reply_text(_pc_text("pc_sent_user", user_lang))
    except Exception:
        pass

    # Bitta moderatsiya so'rovi bitta rasm uchun — marker tozalanadi,
    # conversation (agar shu holatda bo'lsa) yakunlanadi.
    _clear_moderation_marker(context)
    return ConversationHandler.END


# 2. Admin callback: approve or reject PRO grant
async def handle_admin_check_photo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # Adminga qaratilgan barcha toast/edit matnlari ADMIN tilida bo'ladi.
    admin_lang = get_lang(context)
    if not query.from_user.id in ADMIN_IDS_SET:
        await query.answer(_pc_text("pc_no_permission", admin_lang), show_alert=True)
        return
    if not has_permission(query.from_user.id, PERM_MANAGE_USERS):
        await query.answer(_pc_text("pc_no_pro_permission", admin_lang),
                           show_alert=True)
        return

    data = query.data  # format: "cph:a:{user_id}" yoki "cph:r:{user_id}"
    parts = data.split(":")
    if len(parts) != 3:
        await query.answer(_pc_text("pc_bad_callback", admin_lang), show_alert=True)
        return

    action = parts[1]  # 'a' (tasdiq) yoki 'r' (rad)
    try:
        target_user_id = int(parts[2])
    except ValueError:
        await query.answer(_pc_text("pc_bad_user_id", admin_lang), show_alert=True)
        return
    # Foydalanuvchining qaror xabari uning TILIDA bo'lishi kerak.
    try:
        from database import get_user_language
        user_lang = await db.run_db(get_user_language, target_user_id) or admin_lang
    except Exception:
        user_lang = admin_lang

    if action == "a":
        # Activate PRO for user (30 days)
        success = await db.run_db(db.set_user_plan, target_user_id, "pro", days=30,
                                  admin_id=query.from_user.id)
        if success:
            # Notify user
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=_pc_text("pc_pro_granted", user_lang),
                    parse_mode="HTML",
                )
            except Exception:
                pass
            # Confirm to admin
            await query.edit_message_text(
                text=_pc_text("pc_approved_admin", admin_lang).replace(
                    "{user_id}", str(target_user_id)
                ),
                parse_mode="HTML",
            )
        else:
            await query.answer(_pc_text("pc_db_error", admin_lang), show_alert=True)
    elif action == "r":
        # Reject: adminga natija, foydalanuvchiga esa tilidagi ogohlantirish
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=_pc_text("pc_reject_notice", user_lang),
                parse_mode="HTML",
            )
        except Exception:
            logger.debug("photo_check: rad etish xabarini yuborib bo'lmadi")
        await query.edit_message_text(
            text=_pc_text("pc_rejected_admin", admin_lang),
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
