"""FSM Navigation Cleanup Middleware & Utilities.

PHASE 2 · 3-QADAM: FSM tozalash va Menyu xavfsizligi.

Foydalanuvchi har qanday oraliq holatda (MAGIC_INPUT, PHOTO_WAITING / IMAGE_POST_INPUT
va boshqalar) turganda asosiy menyu tugmalarini yoki /start, /cancel ni bossa:
1. context.user_data tozalanadi;
2. FSM Conversation holati bekor qilinadi (ConversationHandler.END);
3. "❌ Bekor qilish" barcha oqimlarda yagona standartda ishlaydi.
"""

from __future__ import annotations
import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Barcha tillardagi bekor qilish signallari
CANCEL_COMMANDS = {
    "/cancel",
    "❌ bekor qilish",
    "❌ отмена",
    "❌ cancel",
    "bekor qilish",
    "отмена",
    "cancel",
    "❌",
}

# Barcha tillardagi start va asosiy menyu navigatsiya signallari
START_AND_MENU_COMMANDS = {
    "/start",
    "/menu",
    "🏠 asosiy menyu",
    "🏠 главное меню",
    "🏠 main menu",
    "asosiy menyu",
    "главное меню",
    "main menu",
    "◀️ orqaga",
    "◀️ назад",
    "◀️ back",
    "orqaga",
    "назад",
    "back",
    # Asosiy menyu 6-talik tugmalari
    "➕ yangi post",
    "➕ новый пост",
    "➕ new post",
    "📢 kanallarim",
    "📢 мои каналы",
    "📢 my channels",
    "📅 rejalashtirilgan",
    "📅 запланированные",
    "📅 scheduled",
    "📊 statistika",
    "📊 статистика",
    "📊 statistics",
    "🤖 ai yordamchi",
    "🤖 ai помощник",
    "🤖 ai assistant",
    "⚙️ sozlamalar",
    "⚙️ настройки",
    "⚙️ settings",
    "✨ magic post",
    "🖼 rasmdan post",
    "🎙 ovoz → post",
}


def normalize_trigger_text(text: str | None) -> str:
    """Tekshirish uchun matnni tozalaydi (kichik harflar, bo'sh joylar)."""
    if not text:
        return ""
    return text.strip().lower()


def is_cancel_trigger(text: str | None) -> bool:
    """Matn '❌ Bekor qilish' yoki /cancel ekanligini tekshiradi."""
    norm = normalize_trigger_text(text)
    if not norm:
        return False
    if norm in CANCEL_COMMANDS or norm.startswith("/cancel"):
        return True
    return False


def is_start_or_menu_trigger(text: str | None) -> bool:
    """Matn /start, /menu yoki asosiy menyu tugmasi ekanligini tekshiradi."""
    norm = normalize_trigger_text(text)
    if not norm:
        return False
    if norm.startswith("/start") or norm.startswith("/menu"):
        return True
    if norm in START_AND_MENU_COMMANDS:
        return True
    return False


def is_navigation_trigger(text: str | None) -> bool:
    """Har qanday bekor qilish yoki navigatsiya buyrug'ini tekshiradi."""
    return is_cancel_trigger(text) or is_start_or_menu_trigger(text)


def clear_user_fsm(context: ContextTypes.DEFAULT_TYPE) -> None:
    """context.user_data ni to'liq tozalaydi (til keshidan tashqari).

    Oraliq FSM ma'lumotlari (magic_raw_text, image_post_file_id, vaqtinchalik
    kalitlar) xavfsiz tozalanishini kafolatlaydi.
    """
    if context is None:
        return
    ud = getattr(context, "user_data", None)
    if ud is None or not hasattr(ud, "clear"):
        return

    # Mavjud til keshini saqlab qolamiz (mavjud bo'lsa)
    lang = ud.get("lang") or ud.get("user_lang")
    ud.clear()
    if lang:
        ud["lang"] = lang


class FSMCleanerMiddleware:
    """Update darajasida FSM tozalash middleware'i.

    Oraliq holatda turganda asosiy menyu yoki bekor qilish bosilsa,
    user_data ni tozalaydi.
    """

    @staticmethod
    async def process_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        message = getattr(update, "message", None)
        text = getattr(message, "text", None) or getattr(message, "caption", None)
        if not text and getattr(update, "callback_query", None):
            text = getattr(update.callback_query, "data", None)

        if is_navigation_trigger(text):
            clear_user_fsm(context)
            user = getattr(update, "effective_user", None)
            if user and getattr(user, "id", None):
                try:
                    from services.ai.concurrency import ai_concurrency_manager
                    await ai_concurrency_manager.cancel_user_requests(user.id, reason="fsm_navigation")
                except Exception as e:
                    logger.debug("AI tasklarini bekor qilishda xatolik: %s", e)
            return True
        return False
