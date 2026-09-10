import asyncio
import logging
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import (
    BTN_T_5MIN, BTN_T_15MIN, BTN_T_1H, BTN_T_DAILY, BTN_T_WEEKLY,
    BTN_BACK, BTN_MAIN_MENU,
    get_cancel_keyboard, get_main_keyboard, get_ai_time_keyboard,
)
from keyboards.callback_data import CB_PHOTO_VARIANT, cb
from keyboards.inline import (
    get_ai_studio_keyboard, get_ai_back_keyboard, get_ai_tone_keyboard,
    get_ai_photo_keyboard, get_ai_confirm_keyboard, AI_TONE_KEYS,
)
from utils.ai_agent import (
    analyze_user_prompt, extract_schedule_time, clear_ai_context,
    generate_ai_response, audit_post,
    VisionError, download_telegram_media_to_temp, cleanup_temp_media,
    generate_vision_post,
    _AUDIT_PRO_SYSTEM, _AUDIT_FREE_SYSTEM,
    _PRO_POST_ENHANCEMENT, _FREE_POST_HINT,
)
from locales.translations import clear_fsm_data, get_lang, get_text
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

# Vision xizmati mavjud bo'lmaganda ko'rsatiladigan xabar
AI_PHOTO_UNAVAILABLE_MSG = (
    "⚠️ AI rasmni tahlil qila olmadi. "
    "Iltimos, birozdan so'ng qayta urinib ko'ring."
)

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
PRO_UPGRADE_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("⭐️ PRO tarifga o'tish", callback_data="sub_open")],
])

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


def _no_credits_text(bot_username: str, user_id: int, lang: str = "uz") -> str:
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    return get_text("no_credits", lang, guide=get_text("daily_bonus_guide", lang), link=ref_link)


def _ai_tone_label(tone: str, lang: str = "uz") -> str:
    """Tanlangan Tone of Voice (AI post uslubi) tarjimasini qaytaradi."""
    tone_key = AI_TONE_KEYS.get(tone, "ai_tone_friendly")
    return get_text(tone_key, lang)


async def _studio_menu_text(user_id: int, lang: str) -> str:
    """AI Studio asosiy menyu matni (kirish yo'riqnomasi + AI ball ko'rsatkichi).

    Foydalanuvchi tiliga (lang) mos tarjima qilinadi; admin/PRO uchun
    „♾ Cheksiz“, oddiy foydalanuvchi uchun mavjud ballar ko'rsatiladi.
    """
    is_admin = user_id in ADMIN_IDS_SET
    if is_admin:
        credits_label = get_text("ai_credits_unlimited", lang)
    else:
        is_pro = await db.run_db(db.is_premium, user_id)
        if is_pro:
            credits_label = get_text("ai_credits_unlimited_pro", lang)
        else:
            credits = await db.run_db(db.get_user_credits, user_id)
            credits_label = get_text("credits_value", lang, n=credits)
    return get_text("ai_studio_menu", lang, credits=credits_label)


async def start_ai_assistant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI yordamchisi holatini (AI_INPUT) boshlaydi."""
    clear_fsm_data(context)
    user_id = update.effective_user.id
    clear_ai_context(user_id)
    is_admin = (user_id in ADMIN_IDS_SET)
    is_pro = await db.run_db(db.is_premium, user_id)
    credits = await db.run_db(db.get_user_credits, user_id)

    # PRO/Enterprise foydalanuvchi cheksiz AI oladi — ball talab qilinmaydi.
    if not is_admin and not is_pro and credits <= 0:
        bot_obj = await context.bot.get_me()
        await update.message.reply_text(
            _no_credits_text(bot_obj.username, user_id, get_lang(context)),
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    limit_info = (
        "♾ Cheksiz (Super Admin)" if is_admin else
        ("♾ Cheksiz (PRO)" if is_pro else f"<b>{credits} ta</b>")
    )

    await update.message.reply_text(
        "🤖 <b>AI Yordamchiga xush kelibsiz!</b>\n\n"
        f"💎 Mavjud AI so'rovlari: {limit_info}\n\n"
        "Men sizga quyidagi ishlarda yordam bera olaman:\n"
        "❓ <b>Savol-javob</b> — bot, postlar, ballar, kanallar haqida savol bering.\n"
        "📝 <b>Post yaratish</b> — post mavzusini yozing yoki tayyor post/rasm yuboring.\n"
        "🕒 <b>Erkin rejalashtirish</b> — masalan: <i>“bugun 15:45 ga hamma kanalga post tayyorla”</i>.\n\n"
        "👉 Post mavzusini yoki savolingizni yozing.\n"
        "<i>Chiqish uchun '🔙 Asosiy menyu' tugmasini bosing.</i>",
        reply_markup=get_cancel_keyboard(),
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
    caption_note = get_text("ai_media_caption_note", lang)
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
            await target_msg.reply_text(get_text("ai_full_post_text", lang, text=text[:3500]), parse_mode="HTML")
        return
    body = f"{text}{caption_note}" if file_id else text
    await target_msg.reply_text(body[:4000], reply_markup=reply_markup, parse_mode="HTML")


async def _show_time_prompt(msg, post_text: str, file_id, post_type: str, lang: str = "uz"):
    """Vaqt tanlash oynasini ko'rsatadi (tilga mos)."""
    header = (
        get_text("ai_schedule_header", lang)
        + safe_html(post_text[:1500])
        + get_text("ai_schedule_foot", lang)
    )
    await _send_preview(msg, header, file_id, post_type, get_ai_time_keyboard(), lang)


async def ai_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Faqat AI_INPUT holatida kelgan xabarlarni qayta ishlaydi."""
    msg = update.message
    user_id = update.effective_user.id
    is_admin = (user_id in ADMIN_IDS_SET)

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
            "⏳ <i>AI so'rovlarini juda tez-tez yuboryapsiz. Iltimos, 1 daqiqa kuting...</i>",
            parse_mode="HTML",
        )
        return AI_INPUT

    if file_id and not text_input:
        existing_post = context.user_data.get("ai_generated_post", "")
        if existing_post:
            await _show_time_prompt(msg, existing_post, file_id, post_type)
            return AI_GET_TIME
        await msg.reply_text(
            "🖼 <b>Rasm/media qabul qilindi!</b>\n\n"
            "Endi post matnini yuboring yoki vaqtni yozing, masalan: <i>“bugun 18:00 ga”</i>.",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
        return AI_INPUT

    if not text_input and not file_id:
        await msg.reply_text(
            "Iltimos, post matnini, savolingizni yoki rasm/fayl yuboring:",
            reply_markup=get_cancel_keyboard(),
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
            "⚠️ <i>Kunlik AI so'rovlar limiti tugadi (30 ta/kun). Ertaga qayta urinib ko'ring.</i>",
            parse_mode="HTML",
        )
        return AI_INPUT

    # Tarif bo'yicha kunlik AI limiti (FREE vs PRO) — database.PLAN_LIMITS asosida.
    # Har bir AI so'rovidan oldin tekshiriladi; limit tugasa foydalanuvchiga
    # xabar va PRO tarifga o'tish tugmasi ko'rsatiladi.
    if not is_admin and not is_pro:
        can_use, used, max_ai = await db.run_db(db.check_ai_limit, user_id)
        if not can_use:
            await msg.reply_text(
                AI_LIMIT_MSG.format(used=used, max=max_ai),
                reply_markup=PRO_UPGRADE_KEYBOARD,
                parse_mode="HTML",
            )
            return AI_INPUT

    # Ballni atomik band qilamiz (faqat free uchun; PRO cheksiz).
    if not is_admin and not is_pro and not await db.run_db(db.use_user_credit, user_id):
        bot_obj = await context.bot.get_me()
        await msg.reply_text(
            _no_credits_text(bot_obj.username, user_id, get_lang(context)),
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    msg_wait = await msg.reply_text("🤖 <i>AI tahlil qilmoqda...</i>", parse_mode="HTML")

    # Typing animatsiyasini fonda ishga tushiramiz
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(context.bot, msg.chat_id, stop_typing))

    try:
        result = await analyze_user_prompt(prompt, user_id, is_pro=is_pro)
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
        await msg.reply_text(
            f"⚠️ {result['error']}",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
        return AI_INPUT

    intent = result.get("intent", "post")

    # A) SAVOL-JAVOB
    if intent == "faq":
        reply = result.get("reply", "") or (
            "Kechirasiz, men faqat Telegram kanallarni boshqarish va postlarni "
            "rejalashtirish bo'yicha yordam bera olaman."
        )
        ad_line = await get_auto_ad_injection_async(user_id)
        await msg.reply_text(
            f"🤖 {safe_html(reply)}\n\n<i>Yana savol bering yoki post mavzusini yuboring 👇</i>{ad_line}",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
        return AI_INPUT

    # B/C) POST yoki EDIT
    post_text = result.get("post_text", "") or ""
    if not post_text:
        reply = result.get("reply", "") or "Post matnini aniqlab bo'lmadi. Iltimos, qaytadan yuboring."
        await msg.reply_text(safe_html(reply), reply_markup=get_cancel_keyboard(), parse_mode="HTML")
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
        await _show_time_prompt(msg, post_text, file_id, post_type)
        return AI_GET_TIME

    target_info = "\n🌐 <b>Kanal:</b> Barcha ulangan kanallarga" if target_all else ""
    preview = (
        "✨ <b>Tayyorlangan post:</b>\n\n"
        f"{safe_html(post_text[:3000])}\n\n"
        f"🕒 <b>Chiqish vaqti:</b> <code>{sched_time}</code>{target_info}\n\n"
        "Ushbu postni rejalashtiramizmi?"
    )
    await _send_preview(msg, preview, file_id, post_type, AI_CONFIRM_KEYBOARD)
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
                get_text("ai_media_received_scheduled", lang),
                reply_markup=get_ai_time_keyboard(),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                get_text("ai_time_prompt_hint", lang),
                reply_markup=get_ai_time_keyboard(),
                parse_mode="HTML",
            )
        return AI_GET_TIME

    text = (update.message.text or "").strip()
    now = datetime.now(tashkent_tz)
    user_id = update.effective_user.id
    is_admin = (user_id in ADMIN_IDS_SET)

    if text in (BTN_T_DAILY, BTN_T_WEEKLY):
        await update.message.reply_text(
            get_text("ai_only_one_time", lang),
            reply_markup=get_ai_time_keyboard(),
            parse_mode="HTML",
        )
        return AI_GET_TIME

    post_time = None
    if text == BTN_T_5MIN:
        post_time = now + timedelta(minutes=5)
    elif text == BTN_T_15MIN:
        post_time = now + timedelta(minutes=15)
    elif text == BTN_T_1H:
        post_time = now + timedelta(hours=1)
    else:
        post_time = parse_future_time(text)

        if post_time is None and text:
            if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
                await update.message.reply_text(
                    get_text("ai_time_fast", lang),
                    parse_mode="HTML",
                )
                return AI_GET_TIME

            msg_wait = await update.message.reply_text(
                get_text("ai_time_detecting", lang), parse_mode="HTML"
            )

            stop_typing2 = asyncio.Event()
            typing_task2 = asyncio.create_task(
                _keep_typing(context.bot, update.message.chat_id, stop_typing2)
            )
            try:
                ai_res = await extract_schedule_time(
                    f"Foydalanuvchining vaqt haqidagi xabari: {text}", user_id
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
                        get_text("ai_time_ask", lang, reply=safe_html(ai_res["reply"])),
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
            get_text("ai_time_unparsed", lang),
            reply_markup=get_ai_time_keyboard(),
            parse_mode="HTML",
        )
        return AI_GET_TIME

    time_str = post_time.strftime("%Y-%m-%d %H:%M")
    context.user_data["ai_scheduled_time"] = time_str

    post_text = context.user_data.get("ai_generated_post", "")
    target_all = context.user_data.get("ai_target_all", False)
    target_info = "\n🌐 <b>Kanal:</b> Barcha ulangan kanallarga" if target_all else ""
    await update.message.reply_text(
        get_text("ai_post_ready", lang)
        + safe_html(post_text[:2500])
        + get_text("ai_post_ready_foot", lang, time=time_str, target=target_info),
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
        await query.answer(get_text("ai_close_session", lang))
        clear_ai_context(user_id)
        clear_fsm_data(context)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            get_text("ai_post_cancelled", lang),
            reply_markup=get_main_keyboard(is_admin, lang),
        )
        return ConversationHandler.END

    if data == "ai_post_retry":
        await query.answer()
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            get_text("ai_post_retry", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return AI_INPUT

    # data == "ai_post_schedule"
    await query.answer(get_text("ai_saving", lang))

    post_text = context.user_data.get("ai_generated_post", "")
    sched_time_str = context.user_data.get("ai_scheduled_time")
    post_type = context.user_data.get("ai_post_type", "text")
    file_id = context.user_data.get("ai_file_id")
    target_all = context.user_data.get("ai_target_all", False)

    channels = await db.run_db(db.get_user_channels, user_id)
    if not channels:
        await query.message.reply_text(
            get_text("ai_no_channel_schedule", lang),
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
        target_name = "Barcha ulangan kanallarga" if target_all else first_title
        ad_line = await get_auto_ad_injection_async(user_id)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            get_text(
                "ai_scheduled_ok", lang,
                channel=html_escape(target_name),
                time=post_time.strftime("%Y-%m-%d %H:%M"),
            ) + ad_line,
            reply_markup=get_main_keyboard(is_admin, lang),
            parse_mode="HTML",
        )
    else:
        await query.message.reply_text(
            get_text("ai_schedule_error", lang),
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
            get_text("ai_rate_limit", lang),
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
            get_text("ai_daily_limit", lang),
            reply_markup=get_ai_back_keyboard(lang),
            parse_mode="HTML",
        )
        return False, is_admin, is_pro

    # Tarif bo'yicha kunlik AI limiti (FREE vs PRO).
    if not is_admin and not is_pro:
        can_use, used, max_ai = await db.run_db(db.check_ai_limit, user_id)
        if not can_use:
            await msg.reply_text(
                get_text("ai_limit_msg", lang, used=used, max=max_ai),
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


def _studio_preview_text(post_text: str, tone: str, file_id=None, lang: str = "uz") -> str:
    """AI_TONE_SELECT ekranidagi post preview matni (tilga mos)."""
    media_note = get_text("ai_preview_media_note", lang) if file_id else ""
    return (
        get_text("ai_preview_title", lang)
        + safe_html(post_text[:2400])
        + get_text("ai_preview_foot", lang, tone=_ai_tone_label(tone, lang), media=media_note)
    )


async def ai_studio_menu_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """✨ AI Studio — asosiy menyu (message entry). AI_MENU_STATE holatida qoladi."""
    lang = get_lang(context)
    user_id = update.effective_user.id
    await update.message.reply_text(
        await _studio_menu_text(user_id, lang),
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
            get_text("ai_studio_post_intro", lang),
            get_ai_back_keyboard(lang),
        )
        return AI_PROMPT_INPUT

    if data == "studio_ai_photo":
        # 🖼 Vision: yangi sessiya — eski natija tozalanadi
        for key in (
            "studio_topic", "studio_post_text", "studio_tone",
            "studio_file_id", "studio_post_type", "studio_photo_extra",
        ):
            context.user_data.pop(key, None)
        await _safe_edit(query, get_text("ai_studio_photo_intro", lang), get_ai_back_keyboard(lang))
        return AI_PHOTO_INPUT

    if data == "studio_ai_audit":
        await _safe_edit(
            query,
            get_text("ai_studio_audit_intro", lang),
            get_ai_back_keyboard(lang),
        )
        return AI_AUDIT_INPUT

    if data == "studio_extract":
        await _safe_edit(
            query,
            get_text("ai_studio_extract_intro", lang),
            get_ai_back_keyboard(lang),
        )
        # Lazy import (circular import himoyasi) — mavjud koduslubga mos
        from handlers.channel_extract import EXTRACT_USERNAME
        return EXTRACT_USERNAME

    if data == "studio_content_plan":
        from handlers.content_plan import PLAN_CHOOSE_CHANNEL, _get_plan_channel_keyboard
        channels = await db.run_db(db.get_user_channels, query.from_user.id)
        if not channels:
            await _safe_edit(
                query,
                get_text("ai_studio_no_channel", lang),
                get_ai_back_keyboard(lang),
            )
            return AI_MENU_STATE
        context.user_data["plan_channels"] = channels
        plan_kb = _get_plan_channel_keyboard(channels)
        rows = [list(row) for row in plan_kb.inline_keyboard]
        rows.append([
            InlineKeyboardButton(get_text("ai_btn_back", lang), callback_data="ai_back_to_menu"),
            InlineKeyboardButton(get_text("ai_btn_close", lang), callback_data="ai_close"),
        ])
        await _safe_edit(
            query,
            get_text("ai_studio_content_plan_intro", lang),
            InlineKeyboardMarkup(rows),
        )
        return PLAN_CHOOSE_CHANNEL

    if data == "studio_close":
        return await ai_close(update, context)

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
                get_text("ai_media_received", lang),
                reply_markup=get_ai_back_keyboard(lang),
                parse_mode="HTML",
            )
        else:
            await msg.reply_text(
                get_text("ai_prompt_hint", lang),
                reply_markup=get_ai_back_keyboard(lang),
            )
        return AI_PROMPT_INPUT

    ok, is_admin, is_pro = await _studio_ai_preflight(update, context)
    if not ok:
        # Limit/blok xabari allaqachon yuborildi — foydalanuvchi menyuga qaytadi
        return AI_MENU_STATE

    msg_wait = await msg.reply_text(get_text("ai_wait_post", lang), parse_mode="HTML")
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(context.bot, msg.chat_id, stop_typing))
    try:
        # 25 soniyalik qat'iy timeout utils.ai_agent ichida o'rnatilgan
        # b2c01d1: FREE vs PRO post enhancement
        result = await generate_ai_response(text_input, is_pro=is_pro)
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
            get_text("ai_unavailable", lang),
            reply_markup=get_ai_back_keyboard(lang),
            parse_mode="HTML",
        )
        return AI_MENU_STATE

    intent = result.get("intent", "post")

    # Savol-javob — javobni ko'rsatib, menyuga qaytaramiz (flow uzilmaydi)
    if intent == "faq":
        reply = result.get("reply", "") or get_text("ai_not_found", lang)
        await msg.reply_text(
            f"🤖 {safe_html(reply)}{get_text('ai_faq_footer', lang)}",
            reply_markup=get_ai_back_keyboard(lang),
            parse_mode="HTML",
        )
        return AI_MENU_STATE

    post_text = (result.get("post_text") or "").strip()
    if not post_text:
        await _studio_ai_refund(user_id, is_admin, is_pro)
        await msg.reply_text(
            get_text("ai_no_post_text", lang),
            reply_markup=get_ai_back_keyboard(lang),
        )
        return AI_MENU_STATE

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
            get_text("ai_tone_unknown", lang),
            get_ai_back_keyboard(lang),
        )
        return AI_PROMPT_INPUT

    # Uslub almashtirish qo'shimcha ball YEMAYDI, lekin rate-limit bilan himoyalangan
    if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
        await query.answer(get_text("ai_rate_limit_alert", lang), show_alert=True)
        return AI_TONE_SELECT

    prompt = base_prompt or (
        "Quyidagi post matnini tanlangan uslubda qayta yozing "
        f"(mazmun va faktlarni saqlang):\n\n{current_post}"
    )

    try:
        await query.edit_message_text(
            get_text("ai_tone_applying", lang, tone=_ai_tone_label(tone, lang)),
            parse_mode="HTML",
        )
    except Exception:
        pass

    try:
        # b2c01d1: is_pro flag for enhancement
        is_pro_tone = await db.run_db(db.is_premium, user_id)
        result = await generate_ai_response(prompt, tone=tone, is_pro=is_pro_tone)
        post_text = (result.get("post_text") or "").strip()
        if not post_text:
            raise RuntimeError(result.get("reply") or "AI bo'sh javob qaytardi")
    except Exception as e:
        # SPEKS: xato log'lanadi, foydalanuvchi doimiy nav-tugmaga qaytadi
        logger.error("AI Generation Error: %s", e)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            get_text("ai_unavailable", lang),
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
            get_text("ai_schedule_need_post", lang),
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
            get_text("ai_audit_prompt_hint", lang),
            reply_markup=get_ai_back_keyboard(lang),
        )
        return AI_AUDIT_INPUT

    user_id = update.effective_user.id
    ok, is_admin, is_pro = await _studio_ai_preflight(update, context)
    if not ok:
        return AI_MENU_STATE

    msg_wait = await msg.reply_text(get_text("ai_wait_audit", lang), parse_mode="HTML")
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(context.bot, msg.chat_id, stop_typing))
    try:
        # b2c01d1: FREE vs PRO audit — audit_post with is_pro
        result = await audit_post(text, is_pro=is_pro)
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
            get_text("ai_unavailable", lang),
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
            get_text("ai_audit_no_result", lang),
            reply_markup=get_ai_back_keyboard(lang),
        )
        return AI_MENU_STATE

    # Muvaffaqiyatli audit kunlik AI sanagichiga qo'shiladi (faqat free)
    if not is_admin and not is_pro:
        await db.run_db(db.increment_ai_usage, user_id)

    ad_line = await get_auto_ad_injection_async(user_id)
    await msg.reply_text(
        get_text("ai_audit_result_title", lang) + safe_html(audit[:3500]) + ad_line,
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
    lang = get_lang(context)
    await _safe_edit(
        query,
        await _studio_menu_text(user_id, lang),
        get_ai_studio_keyboard(lang),
    )
    return AI_MENU_STATE


async def ai_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """❌ Bekor qilish — faqat SHU yerda sessiya ataylab yakunlanadi (END)."""
    query = update.callback_query
    lang = get_lang(context)
    await query.answer(get_text("ai_close_session", lang))  # SPEKS: darhol answer
    try:
        await query.edit_message_text(get_text("ai_close_session", lang), reply_markup=None)
    except Exception:
        pass
    clear_ai_context(query.from_user.id)
    clear_fsm_data(context)
    await query.message.reply_text(
        get_text("ai_close_main_menu", lang),
        reply_markup=get_main_keyboard(query.from_user.id in ADMIN_IDS_SET, lang),
    )
    return ConversationHandler.END


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
        get_text("ai_photo_result_title", lang)
        + safe_html(post_text[:3500])
        + get_text("ai_photo_result_foot", lang)
    )


# Variantlarni taklif qilish tartibi va raqamlari (1-3).
_PHOTO_VARIANT_NUMBERS = ("1️⃣", "2️⃣", "3️⃣")


def _photo_variants_text(variants: dict, lang: str = "uz") -> str:
    """3 xil uslub variantlari tanlov ekrani matni (qisqa prevyu bilan)."""
    parts = [get_text("ai_photo_variants_ask", lang), ""]
    for i, style in enumerate(PHOTO_VARIANT_STYLES):
        text = (variants.get(style) or "").strip()
        if not text:
            continue
        preview = text if len(text) <= 160 else text[:157].rstrip() + "…"
        label = f"{_PHOTO_VARIANT_NUMBERS[i]} {get_text(AI_TONE_KEYS[style], lang)}"
        parts.append(f"<b>{label}</b>\n<i>{safe_html(preview)}</i>\n")
    return "\n".join(parts)


def _photo_variants_keyboard(variants: dict, lang: str = "uz") -> InlineKeyboardMarkup:
    """Variant tanlash tugmalari: faqat muvaffaqiyatli tayyorlangan uslublar."""
    rows = []
    for i, style in enumerate(PHOTO_VARIANT_STYLES):
        if (variants.get(style) or "").strip():
            label = f"{_PHOTO_VARIANT_NUMBERS[i]} {get_text(AI_TONE_KEYS[style], lang)}"
            rows.append([InlineKeyboardButton(label, callback_data=cb(CB_PHOTO_VARIANT, style))])
    rows.append([
        InlineKeyboardButton(get_text("ai_btn_back", lang), callback_data="ai_back_to_menu"),
        InlineKeyboardButton(get_text("ai_btn_close", lang), callback_data="ai_close"),
    ])
    return InlineKeyboardMarkup(rows)


async def _vision_run(file_id: str, extra_prompt: str, rewrite_context="") -> dict:
    """Rasmni temp diskka stream qilib, Gemini vision orqali tahlil qiladi.

    RAM himoyasi: rasm hech qachon user_data'da/handler xotirasida saqlanmaydi —
    temp fayl ish tugagach `finally` blokida o'chiriladi.
    """
    tmp_path = None
    try:
        tmp_path = await download_telegram_media_to_temp(file_id)
        return await generate_vision_post(
            tmp_path,
            extra_prompt=extra_prompt,
            rewrite_context=rewrite_context,
        )
    except VisionError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error("Vision xatosi: %s", e)
        return {"error": AI_PHOTO_UNAVAILABLE_MSG}
    finally:
        if tmp_path:
            cleanup_temp_media(tmp_path)


async def _vision_run_variants(file_id: str, extra_prompt: str):
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
            res = await generate_vision_post(
                tmp_path, extra_prompt=extra_prompt, tone=style
            )
            return style, res

        outcomes = await asyncio.gather(
            *(_run(s) for s in PHOTO_VARIANT_STYLES),
            return_exceptions=True,
        )
        for style, res in outcomes:
            if isinstance(res, Exception):
                logger.warning("Vision varianti xatosi (%s): %s", style, res)
                errors.append(AI_PHOTO_UNAVAILABLE_MSG)
                continue
            if isinstance(res, dict) and res.get("error"):
                errors.append(res["error"])
                continue
            text = ((res or {}).get("post_text") or "").strip()
            if text:
                variants[style] = text
    except Exception as e:
        logger.error("Vision variantlar xatosi: %s", e)
        errors.append(AI_PHOTO_UNAVAILABLE_MSG)
    finally:
        if tmp_path:
            cleanup_temp_media(tmp_path)

    first_error = errors[0] if errors else AI_PHOTO_UNAVAILABLE_MSG
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
                get_text("ai_video_rejected", lang),
                reply_markup=get_ai_back_keyboard(lang),
                parse_mode="HTML",
            )
        else:
            await msg.reply_text(
                get_text("ai_photo_only", lang),
                reply_markup=get_ai_back_keyboard(lang),
                parse_mode="HTML",
            )
        return AI_PHOTO_INPUT

    ok, is_admin, is_pro = await _studio_ai_preflight(update, context)
    if not ok:
        return AI_MENU_STATE

    msg_wait = await msg.reply_text(get_text("ai_wait_photo", lang), parse_mode="HTML")
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(context.bot, msg.chat_id, stop_typing))
    try:
        # 🎨 Rasm BIR marta yuklanadi va 3 xil uslub (rasmiy/do'stona/qisqa)
        # bo'yicha post variantlari tayyorlanadi — foydalanuvchi birini tanlaydi.
        variants, first_error = await _vision_run_variants(file_id, extra_prompt)
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
            f"{get_text('ai_photo_retry_hint', lang)}",
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
            get_text("ai_session_expired", lang),
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
            get_text("ai_photo_edit_intro", lang),
            get_ai_back_keyboard(lang),
        )
        return AI_PHOTO_EDIT_INPUT

    # --- 3) Qayta yozish → rasmni qayta tahlil qilib boshqa uslubda yozadi ---
    if data == "photo_rewrite":
        # Uslub almashtirish kabi qo'shimcha bal YEMAYDI (rate-limit saqlanadi)
        if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
            await query.answer(get_text("ai_rate_limit_alert", lang), show_alert=True)
            return AI_PHOTO_RESULT

        extra = context.user_data.get("studio_photo_extra", "")
        rewrite_ctx = (
            "Quyidagi tayyor postni RASMNI QAYTA TAHLIL QILIB, butunlay boshqacha "
            "uslubda (yangi sarlavha, yangi CTA va yangi hashtaglar bilan) qayta yozing:\n\n"
            f"{post_text}"
        )
        try:
            await query.edit_message_text(
                get_text("ai_photo_rewrite_wait", lang),
                parse_mode="HTML",
            )
        except Exception:
            pass
        result = await _vision_run(file_id, extra, rewrite_context=rewrite_ctx)
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
                get_text("ai_photo_rewrite_keep", lang),
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
            get_text("ai_photo_edit_hint", lang),
            reply_markup=get_ai_back_keyboard(lang),
        )
        return AI_PHOTO_EDIT_INPUT

    post_text = context.user_data.get("studio_post_text", "")
    if not post_text:
        await msg.reply_text(
            get_text("ai_session_expired", lang),
            reply_markup=get_ai_back_keyboard(lang),
        )
        return AI_PHOTO_INPUT

    # Tahrirlash ham yangi AI chaqiruv — preflight (ball/limit) qo'llaniladi
    ok, is_admin, is_pro = await _studio_ai_preflight(update, context)
    if not ok:
        return AI_MENU_STATE

    msg_wait = await msg.reply_text(get_text("ai_wait_edit", lang), parse_mode="HTML")
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(context.bot, msg.chat_id, stop_typing))
    try:
        result = await generate_ai_response(
            f"Tahrirlanadigan post:\n\n{post_text}\n\n"
            f"Foydalanuvchi talabi:\n{text}",
            system_instruction=PHOTO_EDIT_SYSTEM,
            is_pro=is_pro,
        )
    except Exception as e:
        logger.error("Vision edit xatosi: %s", e)
        result = {"error": AI_PHOTO_UNAVAILABLE_MSG}
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
            get_text("ai_photo_edit_no_result", lang),
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
