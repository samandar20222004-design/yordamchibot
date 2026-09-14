"""🧩 KONTENT YARATISH — submenu navigatsiyasi va ACTION-FIRST kirish (PostAssist V2).

Bu modul «✨ Kontent yaratish» ichki menyusi (5 yaratish yo'li + ◀️ Orqaga)
uchun 2 qismni ushlaydi:

  1. ``content_creation_back`` — [◀️ Orqaga] tugmasi: foydalanuvchini asosiy
     6 tugmali menyuga qaytaradi (reply-klaviatura almashtiriladi, FSM
     ma'lumotlari tozalanadi).
  2. ACTION-FIRST (3-mikro qadam) — menyu tashqarisida xom MATN yuborilsa
     ``unknown_message_fallback`` shu modulga murojaat qiladi va foydalanuvchiga
     «✨ Magic Post» taklifi (inline tugmalar) ko'rsatiladi. Taklif bosilsa
     xom matn yo'qolmaydi: to'g'ridan-to'g'ri Magic Post uslub tanlash
     ekrani ochiladi (:func:`content_offer_callback`).

Nega alohida modul?
  * Magic Post / Voice / Image oqimlarining o'zi (killer featuralar) —
     o'z modullarida, bu yerda faqat MENU NAVIGATSIYASI va TAKLIF yashaydi;
  * submenu'ning o'zi ``handlers/ai_assistant.py:ai_studio_menu_entry`` ichida
     chiziladi — UX V2 dan beri «✨ Kontent yaratish» / «✨ AI Studio» tugmalari
     shu handler nomiga bog'langan (routing auditlari shu nomni tekshiradi),
     shu sababli nom saqlab qolindi, mantiq esa yangi UX'ga moslandi.

Himoya (muhim!): PTB ``ConversationHandler(allow_reentry=True)`` entry
point'larni FAOL dialog paytida ham tekshiradi. Shu sababli ``cc_`` taklif
handleri oddiy CallbackQueryHandler EMAS — u ``ContentOfferEntryHandler``
bo'lib, boshqa dialog faol bo'lsa UMUMAN mos kelmaydi (``image_post`` va
``voice_post`` dagi entry himoyasi bilan bir xil usul).
"""

from __future__ import annotations

import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
)

from config import ADMIN_IDS_SET
from keyboards.default import get_main_keyboard
from locales.translations import get_lang
from translations import content_menu_t

logger = logging.getLogger(__name__)

# ============================================================
# CALLBACK DATA (global stale-handler prefikslari bilan to'qnashmaydi:
# ``^mp_`` / ``^vp_`` / ``^image_`` / ``^ps_`` / ``^studio_`` dan keyin
# mustaqil «cc_» prefiksi tanlandi)
# ============================================================
CC_OFFER_PREFIX = "cc_"
CC_MAGIC = "cc_magic"          # ✨ Magic Post bilan tayyorlash
CC_MENU = "cc_menu"            # 🔙 Asosiy menyu

# ============================================================
# ACTION-FIRST CHEKLOVLARI — «xom matn post uchun materialmi?»
# ============================================================
# Qisqa/javob matnlar («???», «ha», «rahmat», «/command») Magic Post
# taklifiga tushmasligi kerak — ular uchun eski fallback xabari o'z kuchida
# qoladi (mavjud UX va regression testlar shu xulqni kutadi).
DIRECT_MIN_CHARS = 40
DIRECT_MIN_WORDS = 5

#: user_id -> (xom matn, unix vaqt). user_data'dan farqli: ``clear_fsm_data``
#: (guard_entry/guard_menu) butun user_data'ni tozalaydi — shu sababli
#: vaqtincha xom matn modul darajasidagi TTL keshida saqlanadi.
_DIRECT_TEXT: dict = {}
_DIRECT_TEXT_TTL = 20 * 60  # 20 daqiqa ichida bossa — matn hali «jonli»


def looks_like_post_material(text) -> bool:
    """Xom matn post yaratish uchun yetarli «material»mi (ACTION-FIRST gate)."""
    if not isinstance(text, str):
        return False
    value = text.strip()
    if not value or value.startswith("/"):
        return False
    return len(value) >= DIRECT_MIN_CHARS and len(value.split()) >= DIRECT_MIN_WORDS


def remember_direct_text(user_id: int, text: str) -> None:
    """Xom matnni vaqtincha saqlaydi (Magic Post taklifi uchun)."""
    if not user_id or not text:
        return
    _DIRECT_TEXT[user_id] = (text.strip(), time.time())


def take_direct_text(user_id: int) -> str:
    """Saqlangan xom matnni oladi (bir marta; TTL tekshiriladi)."""
    item = _DIRECT_TEXT.pop(user_id, None)
    if not item:
        return ""
    text, ts = item
    if time.time() - float(ts) > _DIRECT_TEXT_TTL:
        return ""
    return text or ""


def content_offer_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Magic Post taklifi tugmalari: [✨ Magic Post bilan tayyorlash] / [🔙 Asosiy menyu]."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            content_menu_t("cm_offer_magic", lang), callback_data=CC_MAGIC)],
        [InlineKeyboardButton(
            content_menu_t("cm_offer_menu", lang), callback_data=CC_MENU)],
    ])


async def offer_magic_post_for_direct_text(msg, context, user_id: int,
                                           lang: str) -> bool:
    """Menyu tashqarisidagi xom matn uchun «✨ Magic Post» taklifini chiqadi.

    Qaytaradi: ``True`` — taklif yuborildi (fallback xabari kerak emas),
    ``False`` — matn material emas (eski ``unknown_message_fallback`` xabari
    yuborilishi kerak).
    """
    text = (getattr(msg, "text", "") or "").strip()
    if not looks_like_post_material(text):
        return False
    remember_direct_text(user_id, text)
    await msg.reply_text(
        content_menu_t("cm_offer_text", lang),
        reply_markup=content_offer_keyboard(lang),
        parse_mode="HTML",
    )
    return True


# ============================================================
# DIALOG HIMYOYASI (image_post / voice_post bilan bir xil usul)
# ============================================================
_APPLICATION = None


def set_application(app) -> None:
    """``ContentOfferEntryHandler`` uchun Application havolasini o'rnatadi."""
    global _APPLICATION
    _APPLICATION = app


def _is_inside_dialog(update) -> bool:
    """Foydalanuvchi biror ConversationHandler dialogida bo'lsa True."""
    app = _APPLICATION
    if app is None:
        return False
    try:
        from handlers import _active_conversation_state

        return _active_conversation_state(app, update) is not None
    except Exception:  # pragma: no cover - xatoda entry'ni xavfsiz yopamiz
        return False


class ContentOfferEntryHandler(CallbackQueryHandler):
    """Eski «✨ Magic Post taklifi» tugmasi — faqat dialog TASHQARISIDA ishlaydi.

    Boshqa dialog (to'lov, kanal ulash, new_post...) faol bo'lsa tugma mos
    KELMAYDI: holat buzilmaydi, xabar o'sha dialogning o'z handlerlariga
    (yoki fallback'ga) qoladi.
    """

    def check_update(self, update):
        base = super().check_update(update)
        if not base or _is_inside_dialog(update):
            return None
        return base


# ============================================================
# HANDLERLAR
# ============================================================
async def content_creation_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[◀️ Orqaga] — asosiy 6 tugmali menyuga qaytadi (submenu yopiladi)."""
    msg = getattr(update, "message", None)
    if msg is None:
        return ConversationHandler.END
    lang = get_lang(context)
    user = getattr(update, "effective_user", None)
    user_id = getattr(user, "id", 0) or 0
    _DIRECT_TEXT.pop(user_id, None)
    await msg.reply_text(
        content_menu_t("cm_back_done", lang),
        reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang=lang),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def content_offer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Taklif tugmalari: ✨ Magic Post oqimini ochish yoki 🔙 asosiy menyu.

    ``cc_magic`` — saqlangan xom matn asosida darhol Magic Post uslub tanlash
    ekranini ochadi (``MAGIC_STYLE_SELECT``) va uslub bosilgandan keyin
    kredit/limit preflichti ``magic_style_callback`` ichida bajariladi.
    """
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()  # SPEKS: har callback boshida darhol answer
    lang = get_lang(context)
    user = getattr(update, "effective_user", None)
    user_id = getattr(user, "id", 0) or 0
    data = query.data or ""

    if data == CC_MENU:
        _DIRECT_TEXT.pop(user_id, None)
        try:
            await query.message.reply_text(
                content_menu_t("cm_back_done", lang),
                reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang=lang),
                parse_mode="HTML",
            )
        except Exception:  # pragma: no cover - xabar bo'lmasa jim o'tamiz
            logger.debug("cc_menu: asosiy menyu yuborib bo'lmadi", exc_info=True)
        return ConversationHandler.END

    if data != CC_MAGIC:
        return ConversationHandler.END

    # ✨ Magic Post — xom matn stil tanlash ekraniga o'tadi.
    # Lokal import: modul sikli (handlers/__init__ ↔ magic_post) oldini oladi.
    from handlers.magic_post import (
        MAGIC_INPUT, MAGIC_STYLE_SELECT, _magic_style_keyboard,
        _magic_style_menu_text, _safe_edit,
    )
    from translations import magic_t

    text = take_direct_text(user_id)
    if not text:
        # Matn TTL bo'yicha eskirgan yoki sessiya yangilangan — Magic Post
        # oqimini bo'sh holida ochamiz (foydalanuvchi matnni qayta yozadi).
        try:
            await query.message.reply_text(magic_t("mp_intro", lang), parse_mode="HTML")
        except Exception:  # pragma: no cover
            pass
        return MAGIC_INPUT

    context.user_data["magic_raw_text"] = text
    await _safe_edit(query, _magic_style_menu_text(text, lang), _magic_style_keyboard(lang))
    return MAGIC_STYLE_SELECT
