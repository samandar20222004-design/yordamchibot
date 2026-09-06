"""🆕 Onboarding — yangi foydalanuvchilar uchun SODDA klaviatura oqimlari.

Bu modul ikki vazifani bajaradi:

1. **Menyu tanlash** — ``resolve_main_keyboard`` yangi foydalanuvchiga
   (ro'yxatdan o'tganiga 3 kundan kam YOKI hali 3 ta post chiqarmagan)
   3 tugmali sodda klaviatura, qolganlarga standart 6 talik bosh menyuni
   qaytaradi. Qaror ``onboarding.py`` dagi sof mantiq + Neon DB
   (``database.get_user_onboarding``) asosida qabul qilinadi va bir necha
   daqiqa keshlanadi — har tugma bosilishida bazaga so'rov ketmaydi.

2. **3 ta tezkor tugma** — sodda menyudagi tugmalar mavjud, sinovdan o'tgan
   oqimlarga yo'naltiradi (yangi logika ikki marta yozilmaydi):

   * 🚀 1 daqiqada post yaratish → ✨ AI Studio'ning "AI post" oqimi
     (``AI_PROMPT_INPUT``)
   * 🖼 Rasmdan post olish       → Vision oqimi (``AI_PHOTO_INPUT``)
   * 📢 Kanal ulash              → kanal ulash oqimi (``ADD_CHANNEL``)
   * ⚙️ To'liq menyuni ochish    → belgi bazaga yoziladi va standart menyu
     darhol ko'rsatiladi (qayta bot ishga tushganda ham saqlanadi)
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from config import ADMIN_IDS_SET
import database as db
import onboarding
from keyboards.default import get_main_keyboard, get_simple_keyboard
from keyboards.inline import get_ai_back_keyboard
from locales.translations import get_lang, get_text

logger = logging.getLogger(__name__)


async def _user_lang(context, user_id: int) -> str:
    """Foydalanuvchi tilini kesh → DB tartibida oladi (uz/ru).

    ``handlers.start.ensure_user_lang`` dan foydalanadi (lazy import —
    aylanma importning oldini oladi). Xatolikda ``get_lang(context)``.
    """
    try:
        from handlers.start import ensure_user_lang
        return await ensure_user_lang(context, user_id)
    except Exception:
        logger.debug("ensure_user_lang ishlamadi (user=%s)", user_id, exc_info=True)
        return get_lang(context)


# ============================================================
# 1. MENYU TANLASH
# ============================================================

async def user_wants_simple_menu(user_id: int, context=None) -> bool:
    """Foydalanuvchiga sodda (3 tugmali) klaviatura kerakmi?

    Tartib: qisqa muddatli kesh → Neon DB. Har qanday xatolik yoki
    ma'lumotning yo'qligi **to'liq menyu** degani (fail-open): baza
    javob bermasa ham foydalanuvchi hech qachon funksiyalardan
    chetlatilmaydi.
    """
    if not user_id:
        return False

    cached = onboarding.get_cached_simple_menu(user_id)
    if cached is not None:
        return cached

    try:
        data = await db.run_db(db.get_user_onboarding, int(user_id))
    except Exception:
        logger.debug("Onboarding ma'lumotini olishda xato (user=%s)", user_id, exc_info=True)
        return False

    if not data:
        # Foydalanuvchi topilmadi (yoki DB javob bermadi) → to'liq menyu.
        return False

    simple = onboarding.should_show_simple_menu(
        created_at=data.get("created_at"),
        posts_published=data.get("posts_published", 0),
        full_menu_unlocked=bool(data.get("full_menu_unlocked")),
    )
    onboarding.cache_simple_menu(user_id, simple)
    if simple:
        logger.info(
            "Sodda menyu ko'rsatilmoqda (user=%s, sabab=%s)",
            user_id,
            onboarding.simple_menu_reason(
                created_at=data.get("created_at"),
                posts_published=data.get("posts_published", 0),
                full_menu_unlocked=bool(data.get("full_menu_unlocked")),
            ),
        )
    return simple


async def resolve_main_keyboard(user_id: int, is_admin: bool, lang: str = "uz", context=None):
    """Asosiy reply-klaviaturani qaytaradi: sodda (3 tugma) yoki standart (6 tugma).

    Admin har doim to'liq menyuni ko'radi — sodda klaviaturada "⚙️ Admin
    Panel" tugmasi yo'q.
    """
    if is_admin:
        return get_main_keyboard(True, lang=lang)
    if await user_wants_simple_menu(user_id, context):
        return get_simple_keyboard(lang)
    return get_main_keyboard(False, lang=lang)


async def main_menu_intro_suffix(user_id: int, is_admin: bool, lang: str = "uz",
                                 context=None) -> str:
    """Sodda menyu ko'rsatilayotgan bo'lsa — qisqa yo'riqnoma qatori (aks holda '')."""
    if is_admin:
        return ""
    if await user_wants_simple_menu(user_id, context):
        return "\n\n" + get_text("quick_menu_hint", lang)
    return ""


# ============================================================
# 2. SODDA MENYUNING 3 TA TEZKOR TUGMASI
# ============================================================

async def quick_ai_post_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🚀 1 daqiqada post yaratish — AI post yozish oqimini ochadi.

    ✨ AI Studio'dagi "✍️ AI Post yaratish" tugmasi bilan aynan bir xil
    holatga (``AI_PROMPT_INPUT``) o'tadi: foydalanuvchi mavzuni yozadi, AI
    postni tayyorlaydi, keyin uslub/rejalashtirish bosqichlari keladi.
    """
    from handlers.ai_assistant import AI_PROMPT_INPUT

    user_id = update.effective_user.id
    lang = await _user_lang(context, user_id)
    # Yangi sessiya — eski studio natijasi yangi postga aralashmasligi kerak.
    for key in (
        "studio_topic", "studio_post_text", "studio_tone",
        "studio_file_id", "studio_post_type", "studio_photo_extra",
        "last_studio_media_group_id",
    ):
        context.user_data.pop(key, None)

    await update.message.reply_text(
        get_text("ai_studio_post_intro", lang),
        reply_markup=get_ai_back_keyboard(lang),
        parse_mode="HTML",
    )
    return AI_PROMPT_INPUT


async def quick_photo_post_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🖼 Rasmdan post olish — Vision (rasm → post) oqimini ochadi."""
    from handlers.ai_assistant import AI_PHOTO_INPUT

    user_id = update.effective_user.id
    lang = await _user_lang(context, user_id)
    for key in (
        "studio_topic", "studio_post_text", "studio_tone",
        "studio_file_id", "studio_post_type", "studio_photo_extra",
        "last_studio_media_group_id",
    ):
        context.user_data.pop(key, None)

    await update.message.reply_text(
        get_text("ai_studio_photo_intro", lang),
        reply_markup=get_ai_back_keyboard(lang),
        parse_mode="HTML",
    )
    return AI_PHOTO_INPUT


async def quick_add_channel_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📢 Kanal ulash — mavjud kanal ulash oqimini (``ADD_CHANNEL``) boshlaydi."""
    from handlers.channels import start_add_channel

    return await start_add_channel(update, context)


async def open_full_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """⚙️ To'liq menyuni ochish — belgini bazaga yozadi va standart menyuni ko'rsatadi.

    Belgi ``users.full_menu_unlocked`` ustunida saqlanadi, shuning uchun bot
    qayta ishga tushgandan keyin ham foydalanuvchi yana sodda menyuga
    qaytarilmaydi.
    """
    user_id = update.effective_user.id
    is_admin = user_id in ADMIN_IDS_SET
    lang = await _user_lang(context, user_id)

    try:
        await db.run_db(db.set_user_full_menu_unlocked, user_id, True)
    except Exception:
        # Baza yozuvi muvaffaqiyatsiz bo'lsa ham menyu ochiladi — foydalanuvchi
        # hech qachon "qulflangan" holatda qolmasligi kerak.
        logger.exception("To'liq menyu belgisini yozishda xato (user=%s)", user_id)
    # Keshni ham tozalaymiz — keyingi menyu darhol to'liq ko'rinishda chiqadi.
    onboarding.cache_simple_menu(user_id, False)

    await update.message.reply_text(
        get_text("quick_full_menu_opened", lang),
        reply_markup=get_main_keyboard(is_admin, lang=lang),
        parse_mode="HTML",
    )
    return ConversationHandler.END
