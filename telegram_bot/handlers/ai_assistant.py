import asyncio
import logging
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import (
    BTN_BACK, BTN_MAIN_MENU,
    get_cancel_keyboard, get_main_keyboard, get_ai_time_keyboard,
    # 🧩 KONTENT YARATISH submenu'si (PostAssist V2) — yorliqlar va
    # MENU_TEXTS registry bilan bir xil manbadan chiziladi.
    get_content_creation_keyboard,
    # Uch tilli tugma registry: "⚡ 5 minutes" / "🔁 Daily (same time)" kabi
    # EN/RU yorliqlari ham shu yerdan taniladi.
    is_menu_text,
)
from keyboards.callback_data import CB_PHOTO_VARIANT, cb
from keyboards.inline import (
    get_ai_studio_keyboard, get_ai_back_keyboard, get_ai_tone_keyboard,
    get_ai_photo_keyboard, get_ai_confirm_keyboard, AI_TONE_KEYS,
)
from utils.ai_agent import (
    analyze_user_prompt, extract_schedule_time, clear_ai_context,
    generate_ai_response, audit_post, pick_supported_kwargs,
    VisionError, download_telegram_media_to_temp, cleanup_temp_media,
    generate_vision_post,
    refine_post_pro, apply_pro_audit_stage,
    PRO_TWO_STAGE_ENABLED,
    _AUDIT_PRO_SYSTEM, _AUDIT_FREE_SYSTEM,
    _PRO_POST_ENHANCEMENT, _FREE_POST_HINT,
)
# 🧩 Kontent yaratish bo'limi matnlari (uz/ru/en, paritet auditlangan).
from translations import content_menu_t
from locales.translations import (
    clear_fsm_data, get_lang, safe_t, localize_service_error,
)
# 🧭 PostAssist V2 · 4-qadam — navigatsiya stacki (◀️ Orqaga / ❌ Bekor
# qilish / 🏠 Asosiy menyu standarti, handlers/navigation.py).
from handlers.navigation import (
    SECTION_AI_STUDIO, SECTION_CONTENT,
    remember_section, clear_section,
)
from utils.date_format import format_datetime
from utils.helpers import (
    html_escape, safe_html, check_ai_rate_limit, check_ai_daily_limit, parse_future_time,
    get_auto_ad_injection_async, parse_schedule_input,
)

logger = logging.getLogger(__name__)

# b2c01d1 compatibility: get_user_subscription fallback
async def _get_is_pro(user_id: int) -> bool:
    try:
        # Prefer is_premium if exists
        return await db.run_db(db.is_premium, user_id)
    except Exception:
        try:
            sub = await db.run_db(db.get_user_subscription, user_id)
            if isinstance(sub, dict):
                return bool(sub.get("is_pro") or sub.get("is_premium"))
            return False
        except Exception:
            return False

tashkent_tz = pytz.timezone("Asia/Tashkent")

# ============================================================
# AI YORDAMCHI HOLATLARI (FSM States)
# ============================================================
AI_INPUT = 401
AI_CONFIRM = 402
AI_GET_TIME = 403

# ✨ AI STUDIO — INLINE OQIM HOLATLARI
# Har bir holat ConversationHandler'da to'g'ri ro'yxatga olingan va holatlar
# jarayon tugamaguncha ConversationHandler.END ga tushmaydi.
AI_MENU_STATE = 404      # AI Studio inline menyusi (doimiy navigatsiya)
AI_PROMPT_INPUT = 405    # Foydalanuvchi post mavzusini/matnini kiritadi
AI_TONE_SELECT = 406     # Generatsiya qilingan post uchun uslub tanlash
AI_AUDIT_INPUT = 407     # Foydalanuvchi audit uchun post matnini yuboradi

# 🖼 VISION (Photo-to-Post) holatlari
AI_PHOTO_INPUT = 408     # Foydalanuvchi rasmdan post yaratish uchun rasm yuboradi
AI_PHOTO_RESULT = 409    # Vision natijasi: rejalashtirish / qayta yozish / tahrirlash
AI_PHOTO_EDIT_INPUT = 410  # Foydalanuvchi tahrirlash talabini matn sifatida yuboradi

# 🎨 Rasm → post: taklif qilinadigan 3 xil uslub (rasmiy / do'stona / qisqa).
PHOTO_VARIANT_STYLES = ("formal", "friendly", "concise")

# AI Studio menyusi matni (⬅️ Orqaga shu xabarga qaytadi)
AI_STUDIO_MENU_TEXT = (
    "🤖 <b>PostAssist AI Studio</b>\n\n"
    "Kanal kontentini yaratish uchun kerakli vositani tanlang:"
)

# 🖼 Rasmdan post yaratish (Vision) — yo'riqnoma ekrani
AI_PHOTO_INSTRUCTION = (
    "🖼 <b>Rasmdan post yaratish</b>\n\n"
    "Rasm yuboring — AI uni chuqur tahlil qilib, Telegram kanalingiz uchun "
    "professional SMM post yozadi:\n"
    "• ✨ Chiroyli formatlangan sarlavha (<b>...</b>)\n"
    "• 📝 Qiziqarli / sotuvchi matn\n"
    "• 😎 Emojilar va bandlar\n"
    "• 👉 Harakatga chaqiruv (CTA) va xeshteglar\n\n"
    "<i>Xohlasangiz rasm bilan birga izoh ham yuboring — masalan: "
    "«rasmdagi mahsulotni sotishga urg'u ber».</i>"
)

# Vision xizmati mavjud bo'lmaganda ko'rsatiladigan xabar.
# MUHIM: bu matn foydalanuvchiga KO'RSATILADI — shu sababli u qotirilgan
# o'zbekcha satr emas, ``ai_photo_unavailable`` lug'at kaliti (uz/ru/en).
# ``AI_PHOTO_UNAVAILABLE_MSG`` eski chaqiruvlar uchun saqlanadi.
AI_PHOTO_UNAVAILABLE_KEY = "ai_photo_unavailable"
AI_PHOTO_UNAVAILABLE_MSG = safe_t(AI_PHOTO_UNAVAILABLE_KEY, "uz")


def _photo_unavailable_msg(lang: str = "uz") -> str:
    """Rasm tahlili muvaffaqiyatsizligi — foydalanuvchi tilidagi xabar."""
    text = safe_t(AI_PHOTO_UNAVAILABLE_KEY, lang)
    return text if text and text != AI_PHOTO_UNAVAILABLE_KEY else AI_PHOTO_UNAVAILABLE_MSG

# ✏️ Tahrirlash (matn orqali) uchun system instruction — Vision natijasini
# bosqichsiz, faqat talab bo'yicha o'zgartiradi.
PHOTO_EDIT_SYSTEM = (
    "Siz professional Telegram post muharririsiz. AI rasm tahlili asosida "
    "tayyorlangan postni foydalanuvchi talabiga moslab tahrirlaysiz.\n\n"
    "QOIDALAR:\n"
    "- O'zbek tilida yozing.\n"
    "- Faqat SO'RALGAN o'zgarishni qiling; qolgan matn va faktlarni saqlang.\n"
    "- Sarlavha <b>...</b> HTML bilan qalin, bandlar (•) va emojilar saqlansin.\n"
    "- Oxirida harakatga chaqiruv (CTA) va hashtaglar saqlansin.\n"
    "Javobni FAQAT quyidagi JSON formatida qaytaring:\n"
    '{"post_text": "tahrirlangan to\'liq post matni"}'
)

#: ✏️ Tahrirlash system instruction — 3 tilda (uz varianti orqaga moslik
#: uchun ``PHOTO_EDIT_SYSTEM`` nomi bilan saqlanadi).
PHOTO_EDIT_SYSTEMS = {
    "uz": PHOTO_EDIT_SYSTEM,
    "ru": (
        "Вы — профессиональный редактор постов Telegram. Вы редактируете пост, "
        "созданный на основе анализа изображения ИИ, в соответствии с запросом "
        "пользователя.\n\n"
        "ПРАВИЛА:\n"
        "- Пишите на русском языке.\n"
        "- Вносите ТОЛЬКО ЗАПРОШЕННЫЕ изменения; сохраните остальной текст и факты.\n"
        "- Заголовок <b>...</b> жирным, пункты (•) и эмодзи сохраните.\n"
        "- В конце сохраните призыв к действию (CTA) и хэштеги.\n"
        "Верните ответ ТОЛЬКО в следующем формате JSON:\n"
        '{"post_text": "полностью отредактированный пост"}'
    ),
    "en": (
        "You are a professional Telegram post editor. You edit the post created "
        "from the AI image analysis according to the user's request.\n\n"
        "RULES:\n"
        "- Write in English.\n"
        "- Make ONLY THE REQUESTED changes; keep the rest of the text and the facts.\n"
        "- Keep the <b>...</b> bold headline, the (•) bullet points and the emojis.\n"
        "- Keep the call to action (CTA) and the hashtags at the end.\n"
        "Return the answer ONLY in the following JSON format:\n"
        '{"post_text": "the fully edited post"}'
    ),
}


def _photo_edit_system(lang: str = "uz") -> str:
    """Tahrirlash system instructionini foydalanuvchi tilida qaytaradi."""
    try:
        from locales.translations import normalize_lang
        code = normalize_lang(lang)
    except Exception:  # pragma: no cover - himoya
        code = str(lang or "uz").lower()
        code = "ru" if code.startswith("ru") else ("en" if code.startswith("en") else "uz")
    return PHOTO_EDIT_SYSTEMS.get(code) or PHOTO_EDIT_SYSTEM

# AI chaqiruv muvaffaqiyatsiz bo'lganda ko'rsatiladigan YAGONA xabar.
AI_UNAVAILABLE_MSG = (
    "⚠️ AI xizmatida vaqtinchalik uzilish yuz berdi. "
    "Iltimos, birozdan so'ng qayta urinib ko'ring."
)

AI_TONE_LABELS = {
    "formal": "👔 Rasmiy",
    "friendly": "😊 Do'stona",
    "concise": "⚡️ Qisqa",
    "engaging": "🎉 Jozibali",
}

# 🔍 AI Post auditi uchun system instruction (toza JSON qaytaradi)
AI_AUDIT_SYSTEM = (
    "Siz professional Telegram kontent auditorisiz. Foydalanuvchi yuborgan post "
    "matnini chuqur tahlil qilasiz. Barcha javoblarni FAQAT O'ZBEK tilida yozing.\n\n"
    "Tahlil quyidagilarni o'z ichiga olsin:\n"
    "1. ✍️ Imlo va grammatika bahosi (topilgan xatolar bilan)\n"
    "2. 🎯 Jozibadorlik: sarlavha, CTA (chaqiriq), emotsionallik\n"
    "3. 🧩 Struktura va formatlash bo'yicha amaliy tavsiyalar (emoji, paragraflar)\n"
    "4. ⭐️ Umumiy baho (1 dan 10 gacha) va qisqa xulosa\n\n"
    "Javobni FAQAT quyidagi JSON formatida qaytaring:\n"
    '{"audit": "to\'liq audit matni (HTML formatlash mumkin: <b>, <i>)"}'
)

# AI postini saqlashdan keyin "yana post yaratish" uchun savol beriladi
AI_CONFIRM_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("✅ Kanalga rejalashtirish", callback_data="ai_post_schedule")],
    [InlineKeyboardButton("📝 Matnni tahrirlash", callback_data="ai_post_retry")],
    [InlineKeyboardButton("🚫 Bekor qilish", callback_data="ai_post_cancel")],
])

# Tarif limiti (FREE vs PRO) tugaganda ko'rsatiladigan PRO tugmasi.
# UZ standarti (testlar import qiladi); handler'lar tilga mos variantni ishlatadi.
PRO_UPGRADE_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("⭐️ PRO tarifga o'tish", callback_data="sub_open")],
])


def _pro_upgrade_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """PRO tarifga o'tish tugmasi — foydalanuvchi tilida (uz/ru/en)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(safe_t("ch_pro_btn", lang), callback_data="sub_open")],
    ])


# AI vaqt tugmalarining 3 tildagi matnlari — RU/EN foydalanuvchi bosgan
# tugma ham to'g'ri tanilishi uchun (avval faqat UZ matn solishtirilardi).
_T_5MIN_ALL = frozenset(safe_t("np_btn_time_5m", _l) for _l in ("uz", "ru", "en"))
_T_15MIN_ALL = frozenset(safe_t("np_btn_time_15m", _l) for _l in ("uz", "ru", "en"))
_T_1H_ALL = frozenset(safe_t("np_btn_time_1h", _l) for _l in ("uz", "ru", "en"))
_T_REPEAT_ALL = frozenset(
    safe_t(_k, _l) for _k in ("np_btn_time_daily", "np_btn_time_weekly") for _l in ("uz", "ru", "en")
)

# Tarif asosidagi kunlik AI limiti xabari (database.PLAN_LIMITS).
AI_LIMIT_MSG = (
    "🚫 <b>Kunlik AI limiti tugadi!</b>\n\n"
    "Bugun <b>{used}/{max}</b> ta AI so'rovi ishlatildi.\n"
    "Free tarifida kuniga maksimal <b>{max}</b> ta AI so'rovi.\n\n"
    "⭐️ Cheksiz AI uchun PRO tarifiga o'ting."
)

# Typing animatsiyasi davomiyligi (soniya) — AI javob kelgunicha takrorlanadi
_TYPING_INTERVAL = 4.0


async def _keep_typing(bot, chat_id: int, stop_event: asyncio.Event):
    """Foydalanuvchiga 'yozmoqda...' animatsiyasini AI javob kelgunicha davom ettiradi."""
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            break
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=_TYPING_INTERVAL)
        except asyncio.TimeoutError:
            pass
        except Exception:
            break


def _ai_quota_temp_error_text(lang: str = "uz") -> str:
    """DB/pool xatosida AI kvotasini fail-closed rad etish uchun muloyim xabar."""
    code = str(lang or "uz").lower()
    if code == "ru":
        return "⏳ <b>AI временно недоступен.</b> Пожалуйста, попробуйте ещё раз через минуту."
    if code == "en":
        return "⏳ <b>AI is temporarily unavailable.</b> Please try again in a minute."
    return "⏳ <b>AI xizmati vaqtincha band.</b> Iltimos, bir daqiqadan so'ng qayta urinib ko'ring."


def _no_credits_text(bot_username: str, user_id: int, lang: str = "uz") -> str:
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    return safe_t("no_credits", lang, guide=safe_t("daily_bonus_guide", lang), link=ref_link)


def _ai_tone_label(tone: str, lang: str = "uz") -> str:
    """Tanlangan Tone of Voice (AI post uslubi) tarjimasini qaytaradi."""
    tone_key = AI_TONE_KEYS.get(tone, "ai_tone_friendly")
    return safe_t(tone_key, lang)


async def _studio_menu_text(user_id: int, lang: str) -> str:
    """AI Studio asosiy menyu matni (kirish yo'riqnomasi + AI ball ko'rsatkichi).

    Foydalanuvchi tiliga (lang) mos tarjima qilinadi; admin/PRO uchun
    „♾ Cheksiz“, oddiy foydalanuvchi uchun mavjud ballar ko'rsatiladi.
    """
    is_admin = user_id in ADMIN_IDS_SET
    if is_admin:
        credits_label = safe_t("ai_credits_unlimited", lang)
    else:
        is_pro = await db.run_db(db.is_premium, user_id)
        if is_pro:
            credits_label = safe_t("ai_credits_unlimited_pro", lang)
        else:
            credits = await db.run_db(db.get_user_credits, user_id)
            credits_label = safe_t("credits_value", lang, n=credits)
    return safe_t("ai_studio_menu", lang, credits=credits_label)


async def start_ai_assistant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI yordamchisi holatini (AI_INPUT) boshlaydi."""
    clear_fsm_data(context)
    user_id = update.effective_user.id
    clear_ai_context(user_id)
    is_admin = (user_id in ADMIN_IDS_SET)
    is_pro = await db.run_db(db.is_premium, user_id)
    credits = await db.run_db(db.get_user_credits, user_id)
    lang = get_lang(context)

    # PRO/Enterprise foydalanuvchi cheksiz AI oladi — ball talab qilinmaydi.
    if not is_admin and not is_pro and credits <= 0:
        bot_obj = await context.bot.get_me()
        await update.message.reply_text(
            _no_credits_text(bot_obj.username, user_id, lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    if is_admin:
        limit_info = safe_t("cabinet_credits_admin", lang)
    elif is_pro:
        limit_info = safe_t("ai_credits_unlimited_pro", lang)
    else:
        limit_info = safe_t("credits_value", lang, n=credits)

    await update.message.reply_text(
        safe_t(
            "ai_legacy_welcome", lang, credits=limit_info,
            main_menu=safe_t("btn_main_menu", lang),
        ),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML",
    )
    return AI_INPUT


def _extract_media(msg):
    """Xabardan (file_id, post_type) ni ajratadi; media bo'lmasa (None, 'text')."""
    if msg.photo:
        return msg.photo[-1].file_id, "photo"
    if msg.video:
        return msg.video.file_id, "video"
    if msg.document:
        return msg.document.file_id, "document"
    if msg.audio:
        return msg.audio.file_id, "audio"
    if msg.animation:
        return msg.animation.file_id, "animation"
    if msg.voice:
        return msg.voice.file_id, "voice"
    if msg.sticker:
        return msg.sticker.file_id, "sticker"
    return None, "text"


def _build_prompt(text_input: str, context) -> str:
    """AI uchun kontekstli prompt: oldingi post (tahrir uchun) + yangi xabar."""
    prev_post = context.user_data.get("ai_generated_post", "")
    if prev_post and text_input:
        return (
            f"Foydalanuvchining oldingi posti (tahrirlanishi mumkin):\n{prev_post}\n\n"
            f"Foydalanuvchining yangi xabari/buyrug'i:\n{text_input}"
        )
    if text_input:
        return text_input
    return "(Foydalanuvchi rasm/media yubordi)"


async def _send_preview(target_msg, text, file_id, post_type, reply_markup, lang: str = "uz"):
    """Postni (media bilan yoki matn) preview sifatida ko'rsatadi."""
    caption_note = safe_t("ai_media_caption_note", lang)
    if file_id and post_type in ("photo", "video", "document"):
        cap = text[:900]
        if len(text) > 900:
            cap = cap[:880] + "…"
        if post_type == "photo":
            await target_msg.reply_photo(photo=file_id, caption=cap, reply_markup=reply_markup, parse_mode="HTML")
        elif post_type == "video":
            await target_msg.reply_video(video=file_id, caption=cap, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await target_msg.reply_document(document=file_id, caption=cap, reply_markup=reply_markup, parse_mode="HTML")
        if len(text) > 900:
            await target_msg.reply_text(safe_t("ai_full_post_text", lang, text=text[:3500]), parse_mode="HTML")
        return
    body = f"{text}{caption_note}" if file_id else text
    await target_msg.reply_text(body[:4000], reply_markup=reply_markup, parse_mode="HTML")


async def _show_time_prompt(msg, post_text: str, file_id, post_type: str, lang: str = "uz"):
    """Vaqt tanlash oynasini ko'rsatadi (tilga mos)."""
    header = (
        safe_t("ai_schedule_header", lang)
        + safe_html(post_text[:1500])
        + safe_t("ai_schedule_foot", lang)
    )
    await _send_preview(
        msg, header, file_id, post_type, get_ai_time_keyboard(lang), lang
    )


async def ai_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Faqat AI_INPUT holatida kelgan xabarlarni qayta ishlaydi."""
    msg = update.message
    user_id = update.effective_user.id
    is_admin = (user_id in ADMIN_IDS_SET)
    lang = get_lang(context)

    # Albom (media_group) dublikatlarini bitta ishlov bilan cheklaymiz
    if msg.media_group_id:
        if context.user_data.get("last_ai_media_group_id") == msg.media_group_id:
            return AI_INPUT
        context.user_data["last_ai_media_group_id"] = msg.media_group_id

    text_input = (msg.text or msg.caption or "").strip()
    file_id, post_type = _extract_media(msg)

    if file_id:
        context.user_data["ai_file_id"] = file_id
        context.user_data["ai_post_type"] = post_type
    else:
        post_type = context.user_data.get("ai_post_type", "text")
        file_id = context.user_data.get("ai_file_id")

    prompt = _build_prompt(text_input, context)

    # Rate-limitlar
    if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
        await msg.reply_text(
            safe_t("ai_rate_limit", lang),
            parse_mode="HTML",
        )
        return AI_INPUT

    if file_id and not text_input:
        existing_post = context.user_data.get("ai_generated_post", "")
        if existing_post:
            await _show_time_prompt(msg, existing_post, file_id, post_type, lang)
            return AI_GET_TIME
        await msg.reply_text(
            safe_t("ai_legacy_media_hint", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return AI_INPUT

    if not text_input and not file_id:
        await msg.reply_text(
            safe_t("ai_legacy_input_hint", lang),
            reply_markup=get_cancel_keyboard(lang),
        )
        return AI_INPUT

    # PRO/Enterprise foydalanuvchi cheksiz AI oladi — kunlik limit va ball
    # cheklovlari ularga qo'llanilmaydi.
    is_pro = False
    if not is_admin:
        is_pro = await db.run_db(db.is_premium, user_id)

    # Kunlik limit (in-memory, tezkor himoya) — faqat free uchun.
    if not is_admin and not is_pro and check_ai_daily_limit(user_id, max_per_day=30):
        await msg.reply_text(
            safe_t("ai_daily_limit", lang),
            parse_mode="HTML",
        )
        return AI_INPUT

    # Tarif bo'yicha kunlik AI limiti (FREE vs PRO) — database.PLAN_LIMITS asosida.
    # Har bir AI so'rovidan oldin tekshiriladi; limit tugasa foydalanuvchiga
    # xabar va PRO tarifga o'tish tugmasi ko'rsatiladi.
    if not is_admin and not is_pro:
        can_use, used, max_ai = await db.run_db(db.check_ai_limit, user_id)
        if not can_use:
            if int(used or 0) < 0:
                await msg.reply_text(_ai_quota_temp_error_text(lang), parse_mode="HTML")
            else:
                await msg.reply_text(
                    safe_t("ai_limit_msg", lang, used=used, max=max_ai),
                    reply_markup=_pro_upgrade_keyboard(lang),
                    parse_mode="HTML",
                )
            return AI_INPUT

    # Ballni atomik band qilamiz (faqat free uchun; PRO cheksiz).
    if not is_admin and not is_pro and not await db.run_db(db.use_user_credit, user_id):
        bot_obj = await context.bot.get_me()
        await msg.reply_text(
            _no_credits_text(bot_obj.username, user_id, lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    msg_wait = await msg.reply_text(safe_t("ai_analyzing", lang), parse_mode="HTML")

    # Typing animatsiyasini fonda ishga tushiramiz
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(context.bot, msg.chat_id, stop_typing))

    try:
        # 🌐 AI faqat foydalanuvchi tilida javob qaytaradi (uz/ru/en).
        result = await analyze_user_prompt(prompt, user_id, is_pro=is_pro, lang=lang)
    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await msg_wait.delete()
        except Exception:
            pass

    if "error" in result:
        if not is_admin:
            await db.run_db(db.add_user_credit, user_id)
            if not is_pro and hasattr(db, "refund_ai_usage"):
                try:
                    await db.run_db(db.refund_ai_usage, user_id)
                except Exception:
                    pass
        await msg.reply_text(
            f"⚠️ {localize_service_error(result['error'], lang)}",
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return AI_INPUT

    intent = result.get("intent", "post")

    # A) SAVOL-JAVOB
    if intent == "faq":
        reply = result.get("reply", "") or safe_t("ai_legacy_faq_fallback", lang)
        ad_line = await get_auto_ad_injection_async(user_id)
        await msg.reply_text(
            f"🤖 {safe_html(reply)}"
            f"{safe_t('ai_legacy_faq_footer', lang)}{ad_line}",
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return AI_INPUT

    # B/C) POST yoki EDIT
    post_text = result.get("post_text", "") or ""
    if not post_text:
        reply = result.get("reply", "") or safe_t("ai_legacy_no_post", lang)
        await msg.reply_text(
            safe_html(reply), reply_markup=get_cancel_keyboard(lang), parse_mode="HTML"
        )
        return AI_INPUT

    sched_time = result.get("scheduled_time")
    has_explicit = result.get("has_explicit_time", False)
    target_all = result.get("target_all", False)

    context.user_data["ai_generated_post"] = post_text
    context.user_data["ai_scheduled_time"] = sched_time
    context.user_data["ai_target_all"] = target_all

    valid_time = None
    if has_explicit and sched_time:
        valid_time = parse_future_time(sched_time)
        if valid_time:
            sched_time = valid_time.strftime("%Y-%m-%d %H:%M")
        else:
            sched_time, has_explicit = None, False

    if not has_explicit or not sched_time:
        await _show_time_prompt(msg, post_text, file_id, post_type, lang)
        return AI_GET_TIME

    target_info = safe_t("ai_legacy_target_all", lang) if target_all else ""
    preview = safe_t(
        "ai_confirm_title", lang, post=safe_html(post_text[:3000]),
        time=sched_time, target=target_info,
    )
    await _send_preview(
        msg, preview, file_id, post_type, get_ai_confirm_keyboard(lang), lang
    )
    return AI_CONFIRM


async def ai_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vaqt kutish holati (AI_GET_TIME) — barcha javoblar foydalanuvchi tiliga mos."""
    lang = get_lang(context)
    if update.message and not update.message.text:
        file_id, post_type = _extract_media(update.message)
        if file_id:
            context.user_data["ai_file_id"] = file_id
            context.user_data["ai_post_type"] = post_type
            await update.message.reply_text(
                safe_t("ai_media_received_scheduled", lang),
                reply_markup=get_ai_time_keyboard(),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                safe_t("ai_time_prompt_hint", lang),
                reply_markup=get_ai_time_keyboard(),
                parse_mode="HTML",
            )
        return AI_GET_TIME

    text = (update.message.text or "").strip()
    now = datetime.now(tashkent_tz)
    user_id = update.effective_user.id
    is_admin = (user_id in ADMIN_IDS_SET)

    # 🔁/📅 tugmalari va "⚡ 5/15/60" tugmalari UCHALA tilda taniyladi —
    # klaviatura EN bo'lsa "⚡ 15 minutes" bosilganda avval vaqt o'qilmasdi.
    if is_menu_text(text, "np_time_daily", "np_time_weekly"):
        await update.message.reply_text(
            safe_t("ai_only_one_time", lang),
            reply_markup=get_ai_time_keyboard(),
            parse_mode="HTML",
        )
        return AI_GET_TIME

    post_time = None
    if is_menu_text(text, "np_time_5m"):
        post_time = now + timedelta(minutes=5)
    elif is_menu_text(text, "np_time_15m"):
        post_time = now + timedelta(minutes=15)
    elif is_menu_text(text, "np_time_1h"):
        post_time = now + timedelta(hours=1)
    else:
        post_time = parse_future_time(text)

        if post_time is None and text:
            if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
                await update.message.reply_text(
                    safe_t("ai_time_fast", lang),
                    parse_mode="HTML",
                )
                return AI_GET_TIME

            msg_wait = await update.message.reply_text(
                safe_t("ai_time_detecting", lang), parse_mode="HTML"
            )

            stop_typing2 = asyncio.Event()
            typing_task2 = asyncio.create_task(
                _keep_typing(context.bot, update.message.chat_id, stop_typing2)
            )
            try:
                ai_res = await extract_schedule_time(
                    f"Foydalanuvchining vaqt haqidagi xabari: {text}", user_id,
                    lang=lang,
                )
            finally:
                stop_typing2.set()
                typing_task2.cancel()
                try:
                    await msg_wait.delete()
                except Exception:
                    pass

            if "error" not in ai_res:
                if ai_res.get("has_explicit_time") and ai_res.get("scheduled_time"):
                    post_time = parse_future_time(str(ai_res["scheduled_time"]))
                    if ai_res.get("target_all"):
                        context.user_data["ai_target_all"] = True
                elif ai_res.get("reply"):
                    await update.message.reply_text(
                        safe_t("ai_time_ask", lang, reply=safe_html(ai_res["reply"])),
                        reply_markup=get_ai_time_keyboard(),
                        parse_mode="HTML",
                    )
                    return AI_GET_TIME

        if post_time is None:
            # Crash-proof: "31.12.2026 18:00", "18:00", "ertaga 5 da" — barchasi
            # bitta parserdan o'tadi, xato bo'lsa quyida yo'riqnoma ko'rsatiladi.
            candidate, _reason = parse_schedule_input(text, now)
            if candidate is not None:
                post_time = candidate

    if post_time is None or post_time <= now:
        await update.message.reply_text(
            safe_t("ai_time_unparsed", lang),
            reply_markup=get_ai_time_keyboard(),
            parse_mode="HTML",
        )
        return AI_GET_TIME

    # DB/user_data uchun ISO (qayta o'qiladigan), foydalanuvchi uchun esa
    # TILIGA MOS ko'rinish (en: "Sep 05, 2026 14:00").
    time_str = post_time.strftime("%Y-%m-%d %H:%M")
    context.user_data["ai_scheduled_time"] = time_str
    time_display = format_datetime(post_time, lang) or time_str

    post_text = context.user_data.get("ai_generated_post", "")
    target_all = context.user_data.get("ai_target_all", False)
    # 🌐 "Barcha ulangan kanallarga" qatori ham foydalanuvchi tilida.
    target_info = (
        "\n" + safe_t("ai_target_all_line", lang) if target_all else ""
    )
    await update.message.reply_text(
        safe_t("ai_post_ready", lang)
        + safe_html(post_text[:2500])
        + safe_t("ai_post_ready_foot", lang, time=time_display, target=target_info),
        reply_markup=get_ai_confirm_keyboard(lang),
        parse_mode="HTML",
    )
    return AI_CONFIRM

async def ai_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI tasdiqlash tugmalari (AI_CONFIRM)."""
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    is_admin = (user_id in ADMIN_IDS_SET)
    is_pro = await db.run_db(db.is_premium, user_id)
    lang = get_lang(context)

    if data == "ai_post_cancel":
        # 🧭 4-qadam: FSM ichida [🚫 Bekor qilish] — kontekst tozalanadi va
        # BO'LIM BOSHIGA (AI Studio hub) qaytadi, asosiy menyuga emas.
        await query.answer(safe_t("ai_close_session", lang))
        clear_ai_context(user_id)
        clear_fsm_data(context)
        from handlers.navigation import remember_section, SECTION_AI_STUDIO
        remember_section(context, SECTION_AI_STUDIO)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            safe_t("ai_post_cancelled", lang),
            reply_markup=get_ai_studio_keyboard(lang),
        )
        return AI_MENU_STATE

    if data == "ai_post_retry":
        await query.answer()
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            safe_t("ai_post_retry", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return AI_INPUT

    # data == "ai_post_schedule"
    await query.answer(safe_t("ai_saving", lang))

    post_text = context.user_data.get("ai_generated_post", "")
    sched_time_str = context.user_data.get("ai_scheduled_time")
    post_type = context.user_data.get("ai_post_type", "text")
    file_id = context.user_data.get("ai_file_id")
    target_all = context.user_data.get("ai_target_all", False)

    channels = await db.run_db(db.get_user_channels, user_id)
    if not channels:
        await query.message.reply_text(
            safe_t("ai_no_channel_schedule", lang),
            reply_markup=get_main_keyboard(is_admin, lang),
            parse_mode="HTML",
        )
        # AI sessiyasi shu yerda tugaydi — kontekst ham tozalanadi
        clear_ai_context(user_id)
        clear_fsm_data(context)
        return ConversationHandler.END

    now = datetime.now(tashkent_tz)
    post_time = now
    if sched_time_str:
        # Ichki (bot o'zi yozgan) "%Y-%m-%d %H:%M" formati — buzilgan bo'lsa
        # ham hech qachon yiqilmaydi, "hozir" ga tushib qoladi.
        candidate, _reason = parse_schedule_input(sched_time_str, now)
        post_time = candidate if candidate is not None else now

    target_channels = channels if target_all else [channels[0]]
    ok_count = 0

    for ch_id, ch_title in target_channels:
        pid = await db.run_db(
            db.add_post,
            user_id=user_id,
            channel_id=ch_id,
            post_type=post_type,
            content=post_text,
            file_id=file_id,
            scheduled_time=post_time,
            recurrence_type='none',
        )
        if pid:
            ok_count += 1

    if ok_count > 0:
        # Muvaffaqiyatli post yaratilgach kunlik AI sanagichini oshiramiz
        # (FREE tarif kunlik limitini yangilash uchun). PRO/Admin cheksiz —
        # ular uchun sanagich shart emas. Faqat muvaffaqiyatli yaratilganda
        # chaqiriladi.
        if not is_admin and not is_pro:
            await db.run_db(db.increment_ai_usage, user_id)
        first_title = (channels[0][1] or "").strip() or "Kanal"
        target_name = (
            safe_t("ai_target_all_name", lang) if target_all else first_title
        )
        ad_line = await get_auto_ad_injection_async(user_id)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            safe_t(
                "ai_scheduled_ok", lang,
                channel=html_escape(target_name),
                time=format_datetime(post_time, lang)
                or post_time.strftime("%Y-%m-%d %H:%M"),
            ) + ad_line,
            reply_markup=get_main_keyboard(is_admin, lang),
            parse_mode="HTML",
        )
    else:
        await query.message.reply_text(
            safe_t("ai_schedule_error", lang),
            reply_markup=get_main_keyboard(is_admin, lang),
        )

    # Post rejalashtirilgach yoki xato bo'lgach AI sessiyasi yopiladi
    clear_ai_context(user_id)
    clear_fsm_data(context)
    return ConversationHandler.END


# ============================================================
# ✨ AI STUDIO — INLINE OQIM (doimiy navigatsiya, hardening)
# ============================================================
# Qoidalar (bugfix kontrakti):
# 1) Har bir callback handler BOSHIDA darhol `await query.answer()` chaqiradi.
# 2) Tugma bosilganda xabar O'CHIRILMAYDI — `edit_message_text` orqali yangilanadi
#    va har doim [⬅️ Orqaga]/[❌ Bekor qilish] tugmalari biriktiriladi.
# 3) Holatlar jarayon tugamaguncha ConversationHandler.END ga tushmaydi —
#    xatolikda ham foydalanuvchi AI_MENU_STATE ga qaytadi.
# 4) Xato holatida AI_MENU_STATE qaytariladi va get_ai_back_keyboard() doimiy
#    navigatsiya tugmasi sifatida foydalanuvchiga biriktiriladi.


async def _safe_edit(query, text: str, reply_markup=None, parse_mode: str = "HTML"):
    """Xabarni edit qiladi; iloji bo'lmasa yangi xabar yuboradi.

    Hech qachon xabarni O'CHIRMAYDI — "tugma bossa xabar yo'qolib qolishi"
    bugining asosiy himoyasi shu.
    """
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    except Exception as e:
        # "Message is not modified" — foydalanuvchi bir tugmani ikki marta bosdi
        if "not modified" in str(e).lower():
            return
    try:
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.warning("AI Studio xabar yuborish xatosi: %s", e)


async def _studio_ai_preflight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI chaqiruvdan oldingi tekshiruvlar (eski AI_INPUT oqimi bilan bir xil).

    Qaytaradi: (ruxsat: bool, is_admin: bool, is_pro: bool).
    Ruxsat True bo'lsa — free foydalanuvchi balansi ATOMIK BAND QILINGAN;
    AI xato qilsa `_studio_ai_refund()` bilan qaytarish SHART.
    Barcha xabarlar/klaviaturalar foydalanuvchi tiliga (lang) mos.
    """
    msg = update.message
    user_id = update.effective_user.id
    is_admin = (user_id in ADMIN_IDS_SET)
    lang = get_lang(context)

    if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
        await msg.reply_text(
            safe_t("ai_rate_limit", lang),
            reply_markup=get_ai_back_keyboard(lang),
            parse_mode="HTML",
        )
        return False, is_admin, False

    is_pro = False
    if not is_admin:
        is_pro = await db.run_db(db.is_premium, user_id)

    # Kunlik limit (in-memory, tezkor himoya) — faqat free uchun.
    if not is_admin and not is_pro and check_ai_daily_limit(user_id, max_per_day=30):
        await msg.reply_text(
            safe_t("ai_daily_limit", lang),
            reply_markup=get_ai_back_keyboard(lang),
            parse_mode="HTML",
        )
        return False, is_admin, is_pro

    # Tarif bo'yicha kunlik AI limiti (FREE vs PRO).
    if not is_admin and not is_pro:
        can_use, used, max_ai = await db.run_db(db.check_ai_limit, user_id)
        if not can_use:
            if int(used or 0) < 0:
                await msg.reply_text(_ai_quota_temp_error_text(lang), parse_mode="HTML")
            else:
                await msg.reply_text(
                    safe_t("ai_limit_msg", lang, used=used, max=max_ai),
                    reply_markup=PRO_UPGRADE_KEYBOARD,
                    parse_mode="HTML",
                )
            return False, is_admin, is_pro

    # Ballni atomik band qilamiz (faqat free uchun; PRO/Admin cheksiz).
    if not is_admin and not is_pro and not await db.run_db(db.use_user_credit, user_id):
        bot_obj = await context.bot.get_me()
        await msg.reply_text(
            _no_credits_text(bot_obj.username, user_id, lang),
            reply_markup=get_ai_back_keyboard(lang),
            parse_mode="HTML",
        )
        return False, is_admin, is_pro

    return True, is_admin, is_pro


async def _studio_ai_refund(user_id: int, is_admin: bool, is_pro: bool):
    """Band qilingan AI ballini qaytaradi (AI xato/timeout bo'lganda)."""
    if not is_admin and not is_pro:
        await db.run_db(db.add_user_credit, user_id)
        if hasattr(db, "refund_ai_usage"):
            try:
                await db.run_db(db.refund_ai_usage, user_id)
            except Exception:
                # Eski test/fake DB adapterlari bu helperni bilmasligi mumkin;
                # kredit refund'i saqlanadi, production DB'da quota ham qaytariladi.
                pass


def _studio_preview_text(post_text: str, tone: str, file_id=None, lang: str = "uz") -> str:
    """AI_TONE_SELECT ekranidagi post preview matni (tilga mos)."""
    media_note = safe_t("ai_preview_media_note", lang) if file_id else ""
    return (
        safe_t("ai_preview_title", lang)
        + safe_html(post_text[:2400])
        + safe_t("ai_preview_foot", lang, tone=_ai_tone_label(tone, lang), media=media_note)
    )


async def ai_studio_menu_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🧩 KONTENT YARATISH — asosiy menyudagi ICHKI MENYU (message entry).

    PostAssist V2 · 1-2 qadamlar: «✨ Kontent yaratish» (va meros «✨ AI
    Studio») tugmasi endi 5 ta yaratish yo'lini ochadi::

        [✨ Magic Post]   [📝 Matn → Post]
        [📸 Rasm → Post]  [🎙 Ovoz → Post]
                [🤖 AI Yordamchi]
                    [◀️ Orqaga]

    SUBMENU FSM HOLATINI OCHMAYDI (``ConversationHandler.END``) — ataylab:
    shunda «action-first» xulq saqlanadi, ya'ni foydalanuvchi submenu'ni
    ochgach ham darhol rasm (📸 Image → Post oqimi), ovozli xabar (🎙 Voice →
    Post STT oqimi) yoki matn (✨ Magic Post taklifi) yubora oladi va uni
    hech qanday dialog holati to'sib qo'ymaydi. Har bir tugma esa o'z
    killer-featura oqimiga tushadi (``handlers/magic_post.py``,
    ``new_post``, ``image_post.py``, ``voice_post.py``).
    """
    msg = getattr(update, "message", None)
    if msg is None:
        return ConversationHandler.END
    lang = get_lang(context)
    # 🧭 4-qadam: foydalanuvchi endi «🧩 Kontent yaratish» bo'limida —
    # shu bo'limdan boshlangan FSM oqimlarida [❌ Bekor qilish] aynan
    # shu submenyuga qaytadi (asosiy menyuga emas).
    remember_section(context, SECTION_CONTENT)
    await msg.reply_text(
        content_menu_t("cm_menu_intro", lang),
        reply_markup=get_content_creation_keyboard(lang),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def ai_studio_hub_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🤖 AI Yordamchi — AI Studio vositalari bo'limi (message entry).

    «✨ Kontent yaratish» submenu'idagi 🤖 tugmasi shu bo'limni ochadi:
    matn yozish, qayta yozish (audit), tarjima va g'oya (kontent-reja)
    vositalari + mavjud AI ballari ko'rsatkichi. AI_MENU_STATE holatida
    qoladi — shu holatda rasm yuborilsa Vision oqimi darhol ishlaydi.
    """
    msg = getattr(update, "message", None)
    if msg is None:
        return ConversationHandler.END
    lang = get_lang(context)
    user_id = update.effective_user.id
    # 🧭 4-qadam: AI Yordamchi bo'limi ochildi — bu bo'limga kirish
    # «✨ Kontent yaratish» submenyusidan, shuning uchun [◀️ Orqaga] ham,
    # FSM [❌ Bekor qilish] ham shu bo'lim boshiga (AI Studio hub) qaytadi.
    remember_section(context, SECTION_AI_STUDIO)
    await msg.reply_text(
        await _studio_menu_text(user_id, lang)
        + "\n\n"
        + content_menu_t("cm_ai_hint", lang),
        reply_markup=get_ai_studio_keyboard(lang),
        parse_mode="HTML",
    )
    return AI_MENU_STATE


async def ai_studio_nav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI Studio menyusidagi vosita tugmalari (xabar EDIT qilinadi, o'chirilmaydi)."""
    query = update.callback_query
    await query.answer()  # SPEKS: har callback boshida darhol answer
    data = query.data
    lang = get_lang(context)

    if data == "studio_ai_post":
        # Yangi generatsiya — eski studio natijasini tozalaymiz
        for key in ("studio_topic", "studio_post_text", "studio_tone"):
            context.user_data.pop(key, None)
        await _safe_edit(
            query,
            safe_t("ai_studio_post_intro", lang),
            get_ai_back_keyboard(lang),
        )
        return AI_PROMPT_INPUT

    if data == "studio_ai_photo":
        # 📸 PostAssist V2 · 2-qadam (B2): AI Studio'dagi «🖼 Rasmdan post
        # yaratish» tugmasi endi YAGONA «📸 Rasm → Post» oqimini ochadi
        # (Vision tahlili + Post Score, ``IMAGE_POST_INPUT``). Eski Vision
        # oqimi (AI_PHOTO_INPUT=408 …) ALIAS sifatida saqlanadi — eski
        # ``photo_`` callback'lari va ularning handlerlari o'chirilmagan.
        for key in (
            "studio_topic", "studio_post_text", "studio_tone",
            "studio_file_id", "studio_post_type", "studio_photo_extra",
        ):
            context.user_data.pop(key, None)
        from handlers.image_post import IMAGE_POST_INPUT, image_post_entry
        # Menu xabari O'CHIRILMAYDI — edit qilinadi (studio uslubi).
        await image_post_entry(update, context)
        return IMAGE_POST_INPUT

    if data == "studio_ai_audit":
        await _safe_edit(
            query,
            safe_t("ai_studio_audit_intro", lang),
            get_ai_back_keyboard(lang),
        )
        return AI_AUDIT_INPUT

    if data == "studio_extract":
        await _safe_edit(
            query,
            safe_t("ai_studio_extract_intro", lang),
            get_ai_back_keyboard(lang),
        )
        # Lazy import (circular import himoyasi) — mavjud koduslubga mos
        from handlers.channel_extract import EXTRACT_USERNAME
        return EXTRACT_USERNAME

    if data == "studio_content_plan":
        # 🧠 PostAssist V2 · 2-qadam: [🧠 Kontent reja] tugmasi endi SMART
        # CONTENT CALENDAR (7/30 kunlik reja) oqimini boshlaydi —
        # ``handlers.content_calendar_flow`` (soha → davomiylik → AI reja →
        # kun tanlash → «✨ Magic Post»). Eski ``content_plan`` oqimi
        # (BTN_CONTENT_PLAN tugmasi, ``plan_*`` callback'lari) O'CHIRILMAGAN —
        # u alohida alias sifatida ishlayveradi.
        from handlers.content_calendar_flow import (
            CALENDAR_BUSINESS, content_calendar_entry,
        )
        await content_calendar_entry(update, context)
        return CALENDAR_BUSINESS

    if data == "studio_close":
        # 🏠 Asosiy menyu — AI bo'limidan chiqib, asosiy 6 tugmali menyuga
        # qaytadi (4-qadam: [◀️ Orqaga] va [🏠 Asosiy menyu] mantig'i ajratildi).
        return await ai_exit_to_menu(update, context)

    return AI_MENU_STATE


async def ai_prompt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI_PROMPT_INPUT: mavzu/matn (yoki media) qabul qilib AI post yozadi."""
    msg = update.message
    if msg is None:
        return AI_PROMPT_INPUT
    user_id = update.effective_user.id
    lang = get_lang(context)

    # Albom (media_group) dublikatlarini bitta ishlov bilan cheklaymiz
    if msg.media_group_id:
        if context.user_data.get("last_studio_media_group_id") == msg.media_group_id:
            return AI_PROMPT_INPUT
        context.user_data["last_studio_media_group_id"] = msg.media_group_id

    text_input = (msg.text or msg.caption or "").strip()
    file_id, post_type = _extract_media(msg)
    if file_id:
        context.user_data["studio_file_id"] = file_id
        context.user_data["studio_post_type"] = post_type

    if not text_input:
        if file_id:
            await msg.reply_text(
                safe_t("ai_media_received", lang),
                reply_markup=get_ai_back_keyboard(lang),
                parse_mode="HTML",
            )
        else:
            await msg.reply_text(
                safe_t("ai_prompt_hint", lang),
                reply_markup=get_ai_back_keyboard(lang),
            )
        return AI_PROMPT_INPUT

    ok, is_admin, is_pro = await _studio_ai_preflight(update, context)
    if not ok:
        # Limit/blok xabari allaqachon yuborildi — foydalanuvchi menyuga qaytadi
        return AI_MENU_STATE

    msg_wait = await msg.reply_text(safe_t("ai_wait_post", lang), parse_mode="HTML")
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(context.bot, msg.chat_id, stop_typing))
    try:
        # 25 soniyalik qat'iy timeout utils.ai_agent ichida o'rnatilgan
        # b2c01d1: FREE vs PRO post enhancement
        # 🌐 Til: AI post/javobni foydalanuvchi tilida yozadi.
        result = await generate_ai_response(text_input, is_pro=is_pro, lang=lang)
    except Exception as e:
        logger.error("AI Generation Error: %s", e)
        result = {"error": AI_UNAVAILABLE_MSG}
    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await msg_wait.delete()
        except Exception:
            pass

    if "error" in result:
        await _studio_ai_refund(user_id, is_admin, is_pro)
        await msg.reply_text(
            safe_t("ai_unavailable", lang),
            reply_markup=get_ai_back_keyboard(lang),
            parse_mode="HTML",
        )
        return AI_MENU_STATE

    intent = result.get("intent", "post")

    # Savol-javob — javobni ko'rsatib, menyuga qaytaramiz (flow uzilmaydi)
    if intent == "faq":
        reply = result.get("reply", "") or safe_t("ai_not_found", lang)
        await msg.reply_text(
            f"🤖 {safe_html(reply)}{safe_t('ai_faq_footer', lang)}",
            reply_markup=get_ai_back_keyboard(lang),
            parse_mode="HTML",
        )
        return AI_MENU_STATE

    post_text = (result.get("post_text") or "").strip()
    if not post_text:
        await _studio_ai_refund(user_id, is_admin, is_pro)
        await msg.reply_text(
            safe_t("ai_no_post_text", lang),
            reply_markup=get_ai_back_keyboard(lang),
        )
        return AI_MENU_STATE

    # ✨ PRO 2-bosqichli auto audit: foydalanuvchiga ko'rsatishdan OLDIN
    # AUDIT_PRO_SYSTEM orqali yaxshilangan final variant olinadi.
    # FREE: bitta bosqich — tezlik/xarajat.
    # Fallback: refine xato/timeout/bo'sh bo'lsa stage1 post saqlanadi.
    if is_pro and PRO_TWO_STAGE_ENABLED and post_text:
        try:
            refined = await refine_post_pro(post_text, lang=lang)
            improved = str((refined or {}).get("post_text") or "").strip()
            if improved:
                post_text = improved
        except Exception as _e:
            logger.warning("AI Studio auto audit (PRO) xatosi: %s", _e)

    context.user_data["studio_topic"] = text_input
    context.user_data["studio_post_text"] = post_text
    context.user_data["studio_tone"] = "friendly"

    await msg.reply_text(
        _studio_preview_text(post_text, "friendly", context.user_data.get("studio_file_id"), lang),
        reply_markup=get_ai_tone_keyboard("friendly", lang),
        parse_mode="HTML",
    )
    return AI_TONE_SELECT


async def ai_tone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI_TONE_SELECT: tanlangan uslubda postni QAYTA generatsiya qiladi."""
    query = update.callback_query
    await query.answer()  # SPEKS: darhol answer — tugma "yopishib" qolmaydi
    user_id = query.from_user.id
    is_admin = (user_id in ADMIN_IDS_SET)
    lang = get_lang(context)

    tone = (query.data or "").split(":", 1)[-1]
    if tone not in AI_TONE_KEYS:
        return AI_TONE_SELECT

    base_prompt = context.user_data.get("studio_topic") or ""
    current_post = context.user_data.get("studio_post_text") or ""
    if not base_prompt and not current_post:
        await _safe_edit(
            query,
            safe_t("ai_tone_unknown", lang),
            get_ai_back_keyboard(lang),
        )
        return AI_PROMPT_INPUT

    # Uslub almashtirish qo'shimcha ball YEMAYDI, lekin rate-limit bilan himoyalangan
    if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
        await query.answer(safe_t("ai_rate_limit_alert", lang), show_alert=True)
        return AI_TONE_SELECT

    prompt = base_prompt or (
        "Quyidagi post matnini tanlangan uslubda qayta yozing "
        f"(mazmun va faktlarni saqlang):\n\n{current_post}"
    )

    try:
        await query.edit_message_text(
            safe_t("ai_tone_applying", lang, tone=_ai_tone_label(tone, lang)),
            parse_mode="HTML",
        )
    except Exception:
        pass

    try:
        # b2c01d1: is_pro flag for enhancement
        is_pro_tone = await db.run_db(db.is_premium, user_id)
        result = await generate_ai_response(
            prompt, tone=tone, is_pro=is_pro_tone, lang=lang
        )
        post_text = (result.get("post_text") or "").strip()
        if not post_text:
            raise RuntimeError(result.get("reply") or "AI bo'sh javob qaytardi")

        # ✨ PRO 2-bosqichli auto audit (tone o'zgartirishda ham)
        if is_pro_tone and PRO_TWO_STAGE_ENABLED and post_text:
            try:
                refined = await refine_post_pro(post_text, lang=lang)
                improved = str((refined or {}).get("post_text") or "").strip()
                if improved:
                    post_text = improved
            except Exception as _e:
                logger.warning("AI Studio tone auto audit (PRO) xatosi: %s", _e)

    except Exception as e:
        # SPEKS: xato log'lanadi, foydalanuvchi doimiy nav-tugmaga qaytadi
        logger.error("AI Generation Error: %s", e)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            safe_t("ai_unavailable", lang),
            reply_markup=get_ai_back_keyboard(lang),
            parse_mode="HTML",
        )
        return AI_MENU_STATE

    context.user_data["studio_tone"] = tone
    context.user_data["studio_post_text"] = post_text
    await _safe_edit(
        query,
        _studio_preview_text(post_text, tone, context.user_data.get("studio_file_id"), lang),
        get_ai_tone_keyboard(tone, lang),
    )
    return AI_TONE_SELECT


async def ai_studio_schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI_TONE_SELECT → vaqt tanlash (AI_GET_TIME) ga o'tkazadi."""
    query = update.callback_query
    await query.answer()  # SPEKS: darhol answer
    lang = get_lang(context)

    post_text = context.user_data.get("studio_post_text", "")
    if not post_text:
        await _safe_edit(
            query,
            safe_t("ai_schedule_need_post", lang),
            get_ai_back_keyboard(lang),
        )
        return AI_PROMPT_INPUT

    # Mavjud tasdiqlash/rejalashtirish oqimiga (AI_GET_TIME → AI_CONFIRM) uzatamiz
    context.user_data["ai_generated_post"] = post_text
    context.user_data["ai_file_id"] = context.user_data.get("studio_file_id")
    context.user_data["ai_post_type"] = context.user_data.get("studio_post_type", "text")
    context.user_data.pop("ai_scheduled_time", None)
    context.user_data.pop("ai_target_all", None)

    # Eski tone tugmalari endi keraksiz — lekin xabar o'chirilmaydi
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    await _show_time_prompt(
        query.message,
        post_text,
        context.user_data["ai_file_id"],
        context.user_data["ai_post_type"],
        lang,
    )
    return AI_GET_TIME


async def ai_audit_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI_AUDIT_INPUT: yuborilgan post matnini AI bilan audit qiladi."""
    msg = update.message
    if msg is None:
        return AI_AUDIT_INPUT
    lang = get_lang(context)
    text = (msg.text or msg.caption or "").strip()
    if not text:
        await msg.reply_text(
            safe_t("ai_audit_prompt_hint", lang),
            reply_markup=get_ai_back_keyboard(lang),
        )
        return AI_AUDIT_INPUT

    user_id = update.effective_user.id
    ok, is_admin, is_pro = await _studio_ai_preflight(update, context)
    if not ok:
        return AI_MENU_STATE

    msg_wait = await msg.reply_text(safe_t("ai_wait_audit", lang), parse_mode="HTML")
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(context.bot, msg.chat_id, stop_typing))
    try:
        # b2c01d1: FREE vs PRO audit — audit_post with is_pro
        # 🌐 Audit natijasi foydalanuvchi tilida (uz/ru/en).
        result = await audit_post(text, is_pro=is_pro, lang=lang)
    except Exception as e:
        logger.error("AI Generation Error: %s", e)
        result = {"error": AI_UNAVAILABLE_MSG}
    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await msg_wait.delete()
        except Exception:
            pass

    if "error" in result:
        await _studio_ai_refund(user_id, is_admin, is_pro)
        await msg.reply_text(
            safe_t("ai_unavailable", lang),
            reply_markup=get_ai_back_keyboard(lang),
            parse_mode="HTML",
        )
        return AI_MENU_STATE

    audit = (
        result.get("audit")
        or result.get("reply")
        or result.get("post_text")
        or ""
    ).strip()
    if not audit:
        # Ba'zi modellar boshqa kalit bilan qaytaradi — eng uzun stringni olamiz
        for value in result.values():
            if isinstance(value, str) and len(value) > 20:
                audit = value.strip()
                break

    if not audit:
        await _studio_ai_refund(user_id, is_admin, is_pro)
        await msg.reply_text(
            safe_t("ai_audit_no_result", lang),
            reply_markup=get_ai_back_keyboard(lang),
        )
        return AI_MENU_STATE

    # Muvaffaqiyatli audit kunlik AI sanagichiga qo'shiladi (faqat free)
    if not is_admin and not is_pro:
        await db.run_db(db.increment_ai_usage, user_id)

    ad_line = await get_auto_ad_injection_async(user_id)
    await msg.reply_text(
        safe_t("ai_audit_result_title", lang) + safe_html(audit[:3500]) + ad_line,
        reply_markup=get_ai_back_keyboard(lang),
        parse_mode="HTML",
    )
    return AI_MENU_STATE


async def ai_back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """⬅️ Orqaga — AI Studio menyusiga qaytadi (xabar EDIT; AI xotira tozalanadi)."""
    query = update.callback_query
    await query.answer()  # SPEKS: darhol answer
    user_id = query.from_user.id
    # 🔄 Avval barcha AI/studio post kontekstini tozalaymiz
    clear_ai_context(user_id)
    clear_fsm_data(context)
    # 🧭 4-qadam: AI Studio hub'iga qaytdik — bo'lim yozuvi yangilanadi.
    remember_section(context, SECTION_AI_STUDIO)
    lang = get_lang(context)
    await _safe_edit(
        query,
        await _studio_menu_text(user_id, lang),
        get_ai_studio_keyboard(lang),
    )
    return AI_MENU_STATE


async def ai_back_to_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🧭 ◀️ Orqaga — AI Yordamchidan KONTENT YARATISH submenyusiga qaytadi.

    PostAssist V2 · 4-qadam navigatsiya stacki: foydalanuvchi «✨ Kontent
    yaratish» → «🤖 AI Yordamchi» yo'li bilan kelgani uchun [◀️ Orqaga] ham
    aynan shu yo'lni TESKARI yuradi — asosiy menyuga sakrab ketmaydi.
    AI xotira va FSM konteksti tozalanadi, submenu reply-klaviaturasi bilan
    qayta chiziladi.
    """
    query = update.callback_query
    await query.answer()  # SPEKS: darhol answer
    user_id = query.from_user.id
    clear_ai_context(user_id)
    clear_fsm_data(context)
    # Foydalanuvchi endi «🧩 Kontent yaratish» bo'limida.
    remember_section(context, SECTION_CONTENT)
    lang = get_lang(context)
    await _safe_edit(
        query,
        content_menu_t("cm_menu_intro", lang),
        get_content_creation_keyboard(lang),
    )
    return ConversationHandler.END


async def ai_exit_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🏠 Asosiy menyu — AI bo'limidan chiqib asosiy menyuga qaytadi (END).

    4-qadam standarti: [🏠 Asosiy menyu] — istalgan ichki ekrandan to'g'ridan
    -to'g'ri asosiy 6 tugmali menyuga chiqadi (``studio_close`` callback'i
    eski chat tarixidagi tugmalar uchun o'zgarmagan).
    """
    query = update.callback_query
    lang = get_lang(context)
    await query.answer(safe_t("ai_close_session", lang))  # SPEKS: darhol answer
    try:
        await query.edit_message_text(safe_t("ai_close_session", lang), reply_markup=None)
    except Exception:
        pass
    clear_ai_context(query.from_user.id)
    clear_fsm_data(context)
    # Asosiy menyuga chiqdik — bo'lim yozuvi tozalanadi.
    clear_section(context)
    await query.message.reply_text(
        safe_t("ai_close_main_menu", lang),
        reply_markup=get_main_keyboard(query.from_user.id in ADMIN_IDS_SET, lang),
    )
    return ConversationHandler.END


async def ai_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """❌ Bekor qilish — FSM tozalanadi va bo'lim boshiga (AI Studio hub) qaytadi."""
    query = update.callback_query
    lang = get_lang(context)
    await query.answer(safe_t("ai_close_session", lang))  # SPEKS: darhol answer
    user_id = query.from_user.id
    clear_ai_context(user_id)
    clear_fsm_data(context)
    # Bekor qilindi, lekin foydalanuvchi AI bo'limi boshida qoladi.
    remember_section(context, SECTION_AI_STUDIO)
    await _safe_edit(
        query,
        await _studio_menu_text(user_id, lang),
        get_ai_studio_keyboard(lang),
    )
    return AI_MENU_STATE


# ============================================================
# 🖼 VISION — RASMDAN POST YARATISH (Photo-to-Post)
# ============================================================
# Oqim: AI Studio → "🖼 Rasmdan post yaratish" → rasm yuborish →
# Gemini vision tahlil → natija ([Kanalga rejalashtirish] / [Qayta yozish] /
# [Tahrirlash]) → mavjud AI_GET_TIME/AI_CONFIRM oqimi orqali rejalashtirish.


def _extract_photo_file(msg):
    """Xabardan rasm (photo/document) file_id ni ajratadi.

    Faqat statik rasm qabul qilinadi — VIDEO tahlil QILINMAYDI (server
    resursini tejash uchun video/voice/audio/sticker rad etiladi).
    Qaytaradi: (file_id yoki None, extra mantiq bilan ishlatiladigan tur).
    """
    if getattr(msg, "photo", None):
        return msg.photo[-1].file_id, "photo"
    doc = getattr(msg, "document", None)
    if doc is not None:
        mime = (getattr(doc, "mime_type", "") or "").lower()
        if mime.startswith("video/"):
            return None, None
        # MIME ko'rsatilmagan hollarda ham rasm sifatida qabul qilamiz —
        # `generate_vision_post` magic-bytes bilan yakuniy tekshiradi.
        if not mime or mime.startswith("image/"):
            return doc.file_id, "photo"
    return None, None


def _is_non_image_media(msg) -> bool:
    """Xabar rasm bo'lmagan media (video/audio/voice/sticker) ekanini aniqlaydi.

    Foydalanuvchiga aniq izoh berish uchun: bot faqat rasmni tahlil qiladi.
    """
    for attr in ("video", "animation", "audio", "voice", "video_note", "sticker"):
        if getattr(msg, attr, None):
            return True
    doc = getattr(msg, "document", None)
    if doc is not None:
        mime = (getattr(doc, "mime_type", "") or "").lower()
        if mime.startswith(("video/", "audio/")):
            return True
    return False



def _photo_extra_from_caption(raw) -> str:
    """Rasm captioni'dan AI izohini ajratadi.

    - `"/ai"` yoki `"/ai@Bot"` captioni — izoh emas (buyruq).
    - `"/ai mahsulotni sot"` — qolgan qism izoh sifatida ishlatiladi.
    - Oddiy caption — to'g'ridan-to'g'ri izoh.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    if text.startswith("/ai"):
        parts = text.split(None, 1)
        cmd = parts[0].split("@")[0]
        if cmd == "/ai":
            return (parts[1] if len(parts) > 1 else "").strip()[:500]
    if text.startswith("/") and "\n" not in text:
        return ""
    return text[:500]


def _photo_result_text(post_text: str, lang: str = "uz") -> str:
    """Vision natijasi — to'liq post + keyingi qadam tugmalari (tilga mos)."""
    return (
        safe_t("ai_photo_result_title", lang)
        + safe_html(post_text[:3500])
        + safe_t("ai_photo_result_foot", lang)
    )


# Variantlarni taklif qilish tartibi va raqamlari (1-3).
_PHOTO_VARIANT_NUMBERS = ("1️⃣", "2️⃣", "3️⃣")


def _photo_variants_text(variants: dict, lang: str = "uz") -> str:
    """3 xil uslub variantlari tanlov ekrani matni (qisqa prevyu bilan)."""
    parts = [safe_t("ai_photo_variants_ask", lang), ""]
    for i, style in enumerate(PHOTO_VARIANT_STYLES):
        text = (variants.get(style) or "").strip()
        if not text:
            continue
        preview = text if len(text) <= 160 else text[:157].rstrip() + "…"
        label = f"{_PHOTO_VARIANT_NUMBERS[i]} {safe_t(AI_TONE_KEYS[style], lang)}"
        parts.append(f"<b>{label}</b>\n<i>{safe_html(preview)}</i>\n")
    return "\n".join(parts)


def _photo_variants_keyboard(variants: dict, lang: str = "uz") -> InlineKeyboardMarkup:
    """Variant tanlash tugmalari: faqat muvaffaqiyatli tayyorlangan uslublar."""
    rows = []
    for i, style in enumerate(PHOTO_VARIANT_STYLES):
        if (variants.get(style) or "").strip():
            label = f"{_PHOTO_VARIANT_NUMBERS[i]} {safe_t(AI_TONE_KEYS[style], lang)}"
            rows.append([InlineKeyboardButton(label, callback_data=cb(CB_PHOTO_VARIANT, style))])
    rows.append([
        InlineKeyboardButton(safe_t("ai_btn_back", lang), callback_data="ai_back_to_menu"),
        InlineKeyboardButton(safe_t("ai_btn_close", lang), callback_data="ai_close"),
    ])
    return InlineKeyboardMarkup(rows)


async def _vision_run(file_id: str, extra_prompt: str, rewrite_context="",
                      lang: str = "uz") -> dict:
    """Rasmni temp diskka stream qilib, Gemini vision orqali tahlil qiladi.

    RAM himoyasi: rasm hech qachon user_data'da/handler xotirasida saqlanmaydi —
    temp fayl ish tugagach `finally` blokida o'chiriladi.

    🌐 ``lang`` — post foydalanuvchi tilida (uz/ru/en) yoziladi.
    """
    tmp_path = None
    try:
        tmp_path = await download_telegram_media_to_temp(file_id)
        # ``lang`` — post foydalanuvchi tilida (uz/ru/en). Mock/eski imzolar
        # ``lang`` ni bilmasa, u shunchaki tashlab yuboriladi.
        gvp = globals().get("generate_vision_post") or generate_vision_post
        return await gvp(
            tmp_path,
            **pick_supported_kwargs(
                gvp, extra_prompt=extra_prompt,
                rewrite_context=rewrite_context, lang=lang,
            ),
        )
    except VisionError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error("Vision xatosi: %s", e)
        return {"error": _photo_unavailable_msg(lang)}
    finally:
        if tmp_path:
            cleanup_temp_media(tmp_path)


async def _vision_run_variants(file_id: str, extra_prompt: str, lang: str = "uz"):
    """Rasmni BIR MARTA yuklab, 3 xil uslub (rasmiy/do'stona/qisqa) bo'yicha
    post variantlarini tayyorlaydi.

    Returns:
        (variants, first_error). variants: ``{style: post_text}`` (1–3 ta,
        faqat muvaffaqiyatlilari); hammasi muvaffaqiyatsiz bo'lsa bo'sh dict va
        birinchi xato xabari qaytadi.
    """
    tmp_path = None
    variants: dict = {}
    errors = []
    try:
        tmp_path = await download_telegram_media_to_temp(file_id)

        async def _run(style):
            gvp = globals().get("generate_vision_post") or generate_vision_post
            res = await gvp(
                tmp_path,
                **pick_supported_kwargs(
                    gvp, extra_prompt=extra_prompt, tone=style, lang=lang
                ),
            )
            return style, res

        outcomes = await asyncio.gather(
            *(_run(s) for s in PHOTO_VARIANT_STYLES),
            return_exceptions=True,
        )
        for style, res in outcomes:
            if isinstance(res, Exception):
                logger.warning("Vision varianti xatosi (%s): %s", style, res)
                errors.append(_photo_unavailable_msg(lang))
                continue
            if isinstance(res, dict) and res.get("error"):
                errors.append(res["error"])
                continue
            text = ((res or {}).get("post_text") or "").strip()
            if text:
                variants[style] = text
    except Exception as e:
        logger.error("Vision variantlar xatosi: %s", e)
        errors.append(_photo_unavailable_msg(lang))
    finally:
        if tmp_path:
            cleanup_temp_media(tmp_path)

    first_error = errors[0] if errors else _photo_unavailable_msg(lang)
    return variants, first_error


async def ai_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI_PHOTO_INPUT / AI_MENU_STATE: rasm qabul qiladi va vision post yozadi."""
    msg = update.message
    if msg is None:
        return AI_PHOTO_INPUT
    user_id = update.effective_user.id
    lang = get_lang(context)

    # Albom (media_group) dublikatlarini bitta ishlov bilan cheklaymiz
    if getattr(msg, "media_group_id", None):
        if context.user_data.get("last_studio_photo_group_id") == msg.media_group_id:
            return AI_PHOTO_INPUT
        context.user_data["last_studio_photo_group_id"] = msg.media_group_id

    # Caption'dagi "/ai" kabi buyruq shaklidagi matn izoh emas — o'tkazib yuboramiz
    text_input = (msg.caption or msg.text or "").strip()
    extra_prompt = _photo_extra_from_caption(text_input)

    file_id, _post_type = _extract_photo_file(msg)
    if not file_id:
        if _is_non_image_media(msg):
            await msg.reply_text(
                safe_t("ai_video_rejected", lang),
                reply_markup=get_ai_back_keyboard(lang),
                parse_mode="HTML",
            )
        else:
            await msg.reply_text(
                safe_t("ai_photo_only", lang),
                reply_markup=get_ai_back_keyboard(lang),
                parse_mode="HTML",
            )
        return AI_PHOTO_INPUT

    ok, is_admin, is_pro = await _studio_ai_preflight(update, context)
    if not ok:
        return AI_MENU_STATE

    msg_wait = await msg.reply_text(safe_t("ai_wait_photo", lang), parse_mode="HTML")
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(context.bot, msg.chat_id, stop_typing))
    try:
        # 🎨 Rasm BIR marta yuklanadi va 3 xil uslub (rasmiy/do'stona/qisqa)
        # bo'yicha post variantlari tayyorlanadi — foydalanuvchi birini tanlaydi.
        variants, first_error = await _vision_run_variants(file_id, extra_prompt, lang)
    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await msg_wait.delete()
        except Exception:
            pass

    if not variants:
        await _studio_ai_refund(user_id, is_admin, is_pro)
        await msg.reply_text(
            f"{first_error}\n\n"
            f"{safe_t('ai_photo_retry_hint', lang)}",
            reply_markup=get_ai_back_keyboard(lang),
            parse_mode="HTML",
        )
        return AI_PHOTO_INPUT

    # Birlamchi variant: birinchi muvaffaqiyatli uslub (formal → friendly → concise)
    primary_style = next((s for s in PHOTO_VARIANT_STYLES if s in variants), None)
    post_text = variants[primary_style].strip()

    context.user_data["studio_post_text"] = post_text
    context.user_data["studio_file_id"] = file_id
    context.user_data["studio_post_type"] = "photo"
    context.user_data["studio_tone"] = primary_style
    context.user_data["studio_photo_extra"] = extra_prompt
    context.user_data["studio_photo_variants"] = dict(variants)

    # Muvaffaqiyatli vision so'rovi kunlik AI sanagichiga qo'shiladi (faqat free)
    if not is_admin and not is_pro:
        await db.run_db(db.increment_ai_usage, user_id)

    if len(variants) == 1:
        # Faqat bitta variant chiqdi (qolganlari xato) — darhol natija ekrani.
        await msg.reply_text(
            _photo_result_text(post_text, lang),
            reply_markup=get_ai_photo_keyboard(lang),
            parse_mode="HTML",
        )
        return AI_PHOTO_RESULT

    # 3 xil uslub tayyor — foydalanuvchi variantni tanlaydi.
    await msg.reply_text(
        _photo_variants_text(variants, lang),
        reply_markup=_photo_variants_keyboard(variants, lang),
        parse_mode="HTML",
    )
    return AI_PHOTO_RESULT


async def ai_photo_result_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI_PHOTO_RESULT: [Kanalga rejalashtirish] / [Qayta yozish] / [Tahrirlash]."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    user_id = query.from_user.id
    is_admin = (user_id in ADMIN_IDS_SET)
    lang = get_lang(context)

    post_text = context.user_data.get("studio_post_text", "")
    file_id = context.user_data.get("studio_file_id")
    if not post_text or not file_id:
        await _safe_edit(
            query,
            safe_t("ai_session_expired", lang),
            get_ai_back_keyboard(lang),
        )
        return AI_PHOTO_INPUT

    # --- 0) 🎨 Uslub variantini tanlash (photo_v:formal|friendly|concise) ---
    if data.startswith(CB_PHOTO_VARIANT):
        style = data[len(CB_PHOTO_VARIANT):]
        variants = context.user_data.get("studio_photo_variants") or {}
        picked = (variants.get(style) or "").strip()
        if not picked:
            # Variantlar yo'q (sessiya yangilangan) — tanlovni qayta ko'rsatamiz.
            if variants:
                await _safe_edit(
                    query,
                    _photo_variants_text(variants, lang),
                    _photo_variants_keyboard(variants, lang),
                )
            return AI_PHOTO_RESULT
        context.user_data["studio_post_text"] = picked
        context.user_data["studio_tone"] = style
        try:
            await query.edit_message_text(
                _photo_result_text(picked, lang),
                reply_markup=get_ai_photo_keyboard(lang),
                parse_mode="HTML",
            )
        except Exception:
            try:
                await query.message.reply_text(
                    _photo_result_text(picked, lang),
                    reply_markup=get_ai_photo_keyboard(lang),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        return AI_PHOTO_RESULT

    # --- 1) Kanalga rejalashtirish → mavjud AI_GET_TIME → AI_CONFIRM oqimi ---
    if data == "photo_schedule":
        context.user_data["ai_generated_post"] = post_text
        context.user_data["ai_file_id"] = file_id
        context.user_data["ai_post_type"] = "photo"
        context.user_data.pop("ai_scheduled_time", None)
        context.user_data.pop("ai_target_all", None)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await _show_time_prompt(query.message, post_text, file_id, "photo", lang)
        return AI_GET_TIME

    # --- 2) Tahrirlash → matn talabi holatiga o'tamiz ---
    if data == "photo_edit":
        await _safe_edit(
            query,
            safe_t("ai_photo_edit_intro", lang),
            get_ai_back_keyboard(lang),
        )
        return AI_PHOTO_EDIT_INPUT

    # --- 3) Qayta yozish → rasmni qayta tahlil qilib boshqa uslubda yozadi ---
    if data == "photo_rewrite":
        # Uslub almashtirish kabi qo'shimcha bal YEMAYDI (rate-limit saqlanadi)
        if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
            await query.answer(safe_t("ai_rate_limit_alert", lang), show_alert=True)
            return AI_PHOTO_RESULT

        extra = context.user_data.get("studio_photo_extra", "")
        rewrite_ctx = (
            "Quyidagi tayyor postni RASMNI QAYTA TAHLIL QILIB, butunlay boshqacha "
            "uslubda (yangi sarlavha, yangi CTA va yangi hashtaglar bilan) qayta yozing:\n\n"
            f"{post_text}"
        )
        try:
            await query.edit_message_text(
                safe_t("ai_photo_rewrite_wait", lang),
                parse_mode="HTML",
            )
        except Exception:
            pass
        result = await _vision_run(file_id, extra, rewrite_context=rewrite_ctx, lang=lang)
        if "error" in result:
            await _safe_edit(query, _photo_result_text(post_text, lang), get_ai_photo_keyboard(lang))
            await query.message.reply_text(
                f"⚠️ {result['error']}",
                reply_markup=get_ai_back_keyboard(lang),
                parse_mode="HTML",
            )
            return AI_PHOTO_RESULT

        new_text = (result.get("post_text") or "").strip()
        if not new_text:
            await _safe_edit(query, _photo_result_text(post_text, lang), get_ai_photo_keyboard(lang))
            await query.message.reply_text(
                safe_t("ai_photo_rewrite_keep", lang),
                reply_markup=get_ai_back_keyboard(lang),
            )
            return AI_PHOTO_RESULT

        context.user_data["studio_post_text"] = new_text
        await _safe_edit(query, _photo_result_text(new_text, lang), get_ai_photo_keyboard(lang))
        return AI_PHOTO_RESULT

    return AI_PHOTO_RESULT


async def ai_photo_edit_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI_PHOTO_EDIT_INPUT: tahrirlash talabini qabul qilib AI orqali qo'llaydi."""
    msg = update.message
    if msg is None:
        return AI_PHOTO_EDIT_INPUT
    user_id = update.effective_user.id
    lang = get_lang(context)

    text = (msg.text or msg.caption or "").strip()
    if not text:
        await msg.reply_text(
            safe_t("ai_photo_edit_hint", lang),
            reply_markup=get_ai_back_keyboard(lang),
        )
        return AI_PHOTO_EDIT_INPUT

    post_text = context.user_data.get("studio_post_text", "")
    if not post_text:
        await msg.reply_text(
            safe_t("ai_session_expired", lang),
            reply_markup=get_ai_back_keyboard(lang),
        )
        return AI_PHOTO_INPUT

    # Tahrirlash ham yangi AI chaqiruv — preflight (ball/limit) qo'llaniladi
    ok, is_admin, is_pro = await _studio_ai_preflight(update, context)
    if not ok:
        return AI_MENU_STATE

    msg_wait = await msg.reply_text(safe_t("ai_wait_edit", lang), parse_mode="HTML")
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(context.bot, msg.chat_id, stop_typing))
    try:
        result = await generate_ai_response(
            f"Tahrirlanadigan post:\n\n{post_text}\n\n"
            f"Foydalanuvchi talabi:\n{text}",
            system_instruction=_photo_edit_system(lang),
            is_pro=is_pro,
            lang=lang,
        )
    except Exception as e:
        logger.error("Vision edit xatosi: %s", e)
        result = {"error": _photo_unavailable_msg(lang)}
    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await msg_wait.delete()
        except Exception:
            pass

    if "error" in result:
        await _studio_ai_refund(user_id, is_admin, is_pro)
        await msg.reply_text(
            f"⚠️ {result['error']}",
            reply_markup=get_ai_back_keyboard(lang),
            parse_mode="HTML",
        )
        return AI_PHOTO_EDIT_INPUT

    new_text = (
        result.get("post_text")
        or result.get("text")
        or result.get("reply")
        or ""
    ).strip()
    if not new_text:
        for v in result.values():
            if isinstance(v, str) and len(v) > 20:
                new_text = v.strip()
                break

    if not new_text:
        await _studio_ai_refund(user_id, is_admin, is_pro)
        await msg.reply_text(
            safe_t("ai_photo_edit_no_result", lang),
            reply_markup=get_ai_back_keyboard(lang),
        )
        return AI_PHOTO_EDIT_INPUT

    context.user_data["studio_post_text"] = new_text
    if not is_admin and not is_pro:
        await db.run_db(db.increment_ai_usage, user_id)

    await msg.reply_text(
        _photo_result_text(new_text, lang),
        reply_markup=get_ai_photo_keyboard(lang),
        parse_mode="HTML",
    )
    return AI_PHOTO_RESULT
