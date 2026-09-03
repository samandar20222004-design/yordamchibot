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
from keyboards.inline import (
    get_ai_studio_keyboard, get_ai_back_keyboard, get_ai_tone_keyboard,
    get_ai_photo_keyboard,
)
from utils.ai_agent import (
    analyze_user_prompt, extract_schedule_time, clear_ai_context,
    generate_ai_response,
    VisionError, download_telegram_media_to_temp, cleanup_temp_media,
    generate_vision_post,
)
from locales.translations import clear_fsm_data, get_lang, get_text
from utils.helpers import (
    html_escape, safe_html, check_ai_rate_limit, check_ai_daily_limit, parse_future_time,
    get_auto_ad_injection_async,
)

logger = logging.getLogger(__name__)
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


async def _send_preview(target_msg, text, file_id, post_type, reply_markup):
    """Postni (media bilan yoki matn) preview sifatida ko'rsatadi."""
    caption_note = "\n\n⬆️ Yuqoridagi media ushbu postga biriktiriladi."
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
            await target_msg.reply_text(f"📝 <b>Post matni (to'liq):</b>\n\n{text[:3500]}", parse_mode="HTML")
        return
    body = f"{text}{caption_note}" if file_id else text
    await target_msg.reply_text(body[:4000], reply_markup=reply_markup, parse_mode="HTML")


async def _show_time_prompt(msg, post_text: str, file_id, post_type: str):
    """Vaqt tanlash oynasini ko'rsatadi."""
    header = (
        "✨ <b>Post qabul qilindi!</b>\n\n"
        f"{safe_html(post_text[:1500])}\n\n"
        "🕒 <b>Ushbu post qachon kanalga chiqsin?</b>\n"
        "Quyidagi tugmalardan tanlang yoki erkin yozing:\n"
        "• <i>“ertaga ertalab 9 ga”</i>\n"
        "• <i>“bugun 15:45 ga hamma kanalga”</i>\n"
        "• <i>“1 soatdan keyin”</i>"
    )
    await _send_preview(msg, header, file_id, post_type, get_ai_time_keyboard())


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
        result = await analyze_user_prompt(prompt, user_id)
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
    """Vaqt kutish holati (AI_GET_TIME)."""
    if update.message and not update.message.text:
        file_id, post_type = _extract_media(update.message)
        if file_id:
            context.user_data["ai_file_id"] = file_id
            context.user_data["ai_post_type"] = post_type
            await update.message.reply_text(
                "🖼 <b>Media qabul qilindi va postga biriktirildi!</b>\n\n"
                "Endi chiqish vaqtini yozing (masalan: <i>“bugun 18:00 ga”</i>) yoki tugmani tanlang:",
                reply_markup=get_ai_time_keyboard(),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                "Iltimos, chiqish vaqtini yozing (masalan: <i>“ertaga 10:00 ga”</i>):",
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
            "ℹ️ <i>AI yordamchisi orqali faqat bir martalik post rejalashtiriladi.</i>\n"
            "Har kunlik/haftalik takrorlanuvchi postlar uchun <b>➕ Yangi post rejalashtirish</b> bo'limidan foydalaning.\n\n"
            "Vaqtni yozing (masalan: <i>“ertaga 10:00 ga”</i>) yoki tezkor tugmani tanlang:",
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
                    "⏳ <i>Juda tez-tez so'rov yuboryapsiz. 1 daqiqa kuting yoki vaqtni "
                    "aniq formatda yozing: <code>2026-08-30 18:00</code></i>",
                    parse_mode="HTML",
                )
                return AI_GET_TIME

            msg_wait = await update.message.reply_text("🤖 <i>Vaqt aniqlanmoqda...</i>", parse_mode="HTML")

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
                        f"🤖 {safe_html(ai_res['reply'])}\n\n"
                        "Post vaqtini esa quyidagicha yozing: <i>“ertaga 10:00 ga”</i> yoki tugmani tanlang:",
                        reply_markup=get_ai_time_keyboard(),
                        parse_mode="HTML",
                    )
                    return AI_GET_TIME

        if post_time is None:
            try:
                naive = datetime.strptime(text, "%Y-%m-%d %H:%M")
                candidate = tashkent_tz.localize(naive)
                if candidate > now:
                    post_time = candidate
            except Exception:
                pass

    if post_time is None or post_time <= now:
        await update.message.reply_text(
            "⚠️ <b>Vaqtni aniqlab bo'lmadi yoki u o'tib ketgan.</b>\n\n"
            "Quyidagicha yozing:\n"
            "• <i>“bugun 18:00 ga”</i>\n"
            "• <i>“ertaga ertalab 9 ga”</i>\n"
            "• <i>“30 daqiqadan keyin”</i>\n"
            "Yoki aniq format: <code>2026-08-30 18:00</code>",
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
        "✨ <b>Post tayyor!</b>\n\n"
        f"{safe_html(post_text[:2500])}\n\n"
        f"🕒 <b>Chiqish vaqti:</b> <code>{time_str}</code>{target_info}\n\n"
        "Rejalashtiramizmi?",
        reply_markup=AI_CONFIRM_KEYBOARD,
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

    if data == "ai_post_cancel":
        await query.answer("Bekor qilindi")
        clear_ai_context(user_id)
        clear_fsm_data(context)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            "🚫 Post bekor qilindi. Menyudan kerakli bo'limni tanlang.",
            reply_markup=get_main_keyboard(is_admin),
        )
        return ConversationHandler.END

    if data == "ai_post_retry":
        await query.answer()
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            "📝 <b>Postni qanday o'zgartiramiz?</b>\n\n"
            "Masalan: <i>“oxiriga telefon raqam qo'sh”</i>, <i>“matnni qisqartir”</i>, "
            "<i>“sarlavhani o'zgartir”</i> — yoki yangi post yuboring.",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
        return AI_INPUT

    # data == "ai_post_schedule"
    await query.answer("Post saqlanmoqda...")

    post_text = context.user_data.get("ai_generated_post", "")
    sched_time_str = context.user_data.get("ai_scheduled_time")
    post_type = context.user_data.get("ai_post_type", "text")
    file_id = context.user_data.get("ai_file_id")
    target_all = context.user_data.get("ai_target_all", False)

    channels = await db.run_db(db.get_user_channels, user_id)
    if not channels:
        await query.message.reply_text(
            "⚠️ <b>Sizda ulangan kanallar topilmadi.</b>\n\n"
            "Avval '📢 Kanal/Guruhlar' bo'limidan kanal ulang, keyin postni qayta rejalashtiring.",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML",
        )
        # AI sessiyasi shu yerda tugaydi — kontekst ham tozalanadi
        clear_ai_context(user_id)
        clear_fsm_data(context)
        return ConversationHandler.END

    now = datetime.now(tashkent_tz)
    post_time = now
    if sched_time_str:
        try:
            naive = datetime.strptime(sched_time_str, "%Y-%m-%d %H:%M")
            post_time = tashkent_tz.localize(naive)
            if post_time <= now:
                post_time = now
        except Exception:
            post_time = now

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
            "✅ <b>AI Posti muvaffaqiyatli rejalashtirildi!</b>\n\n"
            f"📢 Joylash: <b>{html_escape(target_name)}</b>\n"
            f"⏰ Chiqish vaqti: <b>{post_time.strftime('%Y-%m-%d %H:%M')}</b>\n\n"
            f"Yana post yaratish uchun <b>🤖 AI Yordamchi</b> ni bosing yoki menyuga qayting.{ad_line}",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML",
        )
    else:
        await query.message.reply_text(
            "❌ Saqlashda xatolik yuz berdi. Iltimos, keyinroq urinib ko'ring.",
            reply_markup=get_main_keyboard(is_admin),
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
    """
    msg = update.message
    user_id = update.effective_user.id
    is_admin = (user_id in ADMIN_IDS_SET)

    if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
        await msg.reply_text(
            "⏳ <i>AI so'rovlarini juda tez-tez yuboryapsiz. Iltimos, 1 daqiqa kuting...</i>",
            reply_markup=get_ai_back_keyboard(),
            parse_mode="HTML",
        )
        return False, is_admin, False

    is_pro = False
    if not is_admin:
        is_pro = await db.run_db(db.is_premium, user_id)

    # Kunlik limit (in-memory, tezkor himoya) — faqat free uchun.
    if not is_admin and not is_pro and check_ai_daily_limit(user_id, max_per_day=30):
        await msg.reply_text(
            "⚠️ <i>Kunlik AI so'rovlar limiti tugadi (30 ta/kun). Ertaga qayta urinib ko'ring.</i>",
            reply_markup=get_ai_back_keyboard(),
            parse_mode="HTML",
        )
        return False, is_admin, is_pro

    # Tarif bo'yicha kunlik AI limiti (FREE vs PRO).
    if not is_admin and not is_pro:
        can_use, used, max_ai = await db.run_db(db.check_ai_limit, user_id)
        if not can_use:
            await msg.reply_text(
                AI_LIMIT_MSG.format(used=used, max=max_ai),
                reply_markup=PRO_UPGRADE_KEYBOARD,
                parse_mode="HTML",
            )
            return False, is_admin, is_pro

    # Ballni atomik band qilamiz (faqat free uchun; PRO/Admin cheksiz).
    if not is_admin and not is_pro and not await db.run_db(db.use_user_credit, user_id):
        bot_obj = await context.bot.get_me()
        await msg.reply_text(
            _no_credits_text(bot_obj.username, user_id, get_lang(context)),
            reply_markup=get_ai_back_keyboard(),
            parse_mode="HTML",
        )
        return False, is_admin, is_pro

    return True, is_admin, is_pro


async def _studio_ai_refund(user_id: int, is_admin: bool, is_pro: bool):
    """Band qilingan AI ballini qaytaradi (AI xato/timeout bo'lganda)."""
    if not is_admin and not is_pro:
        await db.run_db(db.add_user_credit, user_id)


def _studio_preview_text(post_text: str, tone: str, file_id=None) -> str:
    """AI_TONE_SELECT ekranidagi post preview matni."""
    media_note = "\n🖼 <i>Media postga biriktiriladi.</i>" if file_id else ""
    return (
        "✨ <b>AI Post tayyor!</b>\n\n"
        f"{safe_html(post_text[:2400])}\n\n"
        f"🎨 <b>Uslub:</b> {AI_TONE_LABELS.get(tone, AI_TONE_LABELS['friendly'])}{media_note}\n\n"
        "Uslubni almashtiring yoki rejalashtirishga o'ting 👇"
    )


async def ai_studio_menu_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """✨ AI Studio — asosiy menyu (message entry). AI_MENU_STATE holatida qoladi."""
    await update.message.reply_text(
        AI_STUDIO_MENU_TEXT,
        reply_markup=get_ai_studio_keyboard(),
        parse_mode="HTML",
    )
    return AI_MENU_STATE


async def ai_studio_nav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI Studio menyusidagi vosita tugmalari (xabar EDIT qilinadi, o'chirilmaydi)."""
    query = update.callback_query
    await query.answer()  # SPEKS: har callback boshida darhol answer
    data = query.data

    if data == "studio_ai_post":
        # Yangi generatsiya — eski studio natijasini tozalaymiz
        for key in ("studio_topic", "studio_post_text", "studio_tone"):
            context.user_data.pop(key, None)
        await _safe_edit(
            query,
            "✍️ <b>AI Post yaratish</b>\n\n"
            "Post mavzusini yozing yoki rasm/fayl yuboring.\n"
            "<i>Masalan: «Sog'lom turmush tarzi haqida motivatsion post»</i>",
            get_ai_back_keyboard(),
        )
        return AI_PROMPT_INPUT

    if data == "studio_ai_photo":
        # 🖼 Vision: yangi sessiya — eski natija tozalanadi
        for key in (
            "studio_topic", "studio_post_text", "studio_tone",
            "studio_file_id", "studio_post_type", "studio_photo_extra",
        ):
            context.user_data.pop(key, None)
        await _safe_edit(query, AI_PHOTO_INSTRUCTION, get_ai_back_keyboard())
        return AI_PHOTO_INPUT

    if data == "studio_ai_audit":
        await _safe_edit(
            query,
            "🔍 <b>AI Post auditi</b>\n\n"
            "Tayyor post matningizni yuboring — AI uni tahlil qiladi:\n"
            "• ✍️ Imlo va grammatika\n"
            "• 🎯 Jozibadorlik va CTA\n"
            "• 🧩 Struktura tavsiyalari\n"
            "• ⭐️ Umumiy baho (1-10)",
            get_ai_back_keyboard(),
        )
        return AI_AUDIT_INPUT

    if data == "studio_extract":
        await _safe_edit(
            query,
            "📢 <b>Ochiq kanaldan olish</b>\n\n"
            "Kanal nikini kiriting (masalan: <code>@kunuzofficial</code> yoki <code>daryo</code>):\n\n"
            "<i>Faqat ochiq kanallar uchun ishlaydi.</i>",
            get_ai_back_keyboard(),
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
                "⚠️ <b>Avval kanal ulang.</b>\n\n"
                "Kontent-reja tuzish uchun kamida bitta kanal bo'lishi kerak.\n"
                "📢 Kanallar bo'limidan kanal ulang.",
                get_ai_back_keyboard(),
            )
            return AI_MENU_STATE
        context.user_data["plan_channels"] = channels
        plan_kb = _get_plan_channel_keyboard(channels)
        rows = [list(row) for row in plan_kb.inline_keyboard]
        rows.append([
            InlineKeyboardButton("⬅️ Orqaga", callback_data="ai_back_to_menu"),
            InlineKeyboardButton("❌ Bekor qilish", callback_data="ai_close"),
        ])
        await _safe_edit(
            query,
            "🧠 <b>Kontent-reja generatori</b>\n\nQaysi kanal uchun kontent-reja tuzamiz?",
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
                "🖼 <b>Media qabul qilindi!</b>\n\nEndi post mavzusini yoki matnini yozing.",
                reply_markup=get_ai_back_keyboard(),
                parse_mode="HTML",
            )
        else:
            await msg.reply_text(
                "✍️ Post mavzusini yozing yoki rasm/fayl yuboring:",
                reply_markup=get_ai_back_keyboard(),
            )
        return AI_PROMPT_INPUT

    ok, is_admin, is_pro = await _studio_ai_preflight(update, context)
    if not ok:
        # Limit/blok xabari allaqachon yuborildi — foydalanuvchi menyuga qaytadi
        return AI_MENU_STATE

    msg_wait = await msg.reply_text("🤖 <i>AI post yozmoqda...</i>", parse_mode="HTML")
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(context.bot, msg.chat_id, stop_typing))
    try:
        # 25 soniyalik qat'iy timeout utils.ai_agent ichida o'rnatilgan
        result = await generate_ai_response(text_input)
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
            AI_UNAVAILABLE_MSG,
            reply_markup=get_ai_back_keyboard(),
            parse_mode="HTML",
        )
        return AI_MENU_STATE

    intent = result.get("intent", "post")

    # Savol-javob — javobni ko'rsatib, menyuga qaytaramiz (flow uzilmaydi)
    if intent == "faq":
        reply = result.get("reply", "") or "Kechirasiz, javob topa olmadim."
        await msg.reply_text(
            f"🤖 {safe_html(reply)}\n\n<i>Yana mavzu yozing yoki orqaga qayting 👇</i>",
            reply_markup=get_ai_back_keyboard(),
            parse_mode="HTML",
        )
        return AI_MENU_STATE

    post_text = (result.get("post_text") or "").strip()
    if not post_text:
        await _studio_ai_refund(user_id, is_admin, is_pro)
        await msg.reply_text(
            "⚠️ Post matnini aniqlab bo'lmadi. Mavzuni boshqacharoq yozib ko'ring.",
            reply_markup=get_ai_back_keyboard(),
        )
        return AI_MENU_STATE

    context.user_data["studio_topic"] = text_input
    context.user_data["studio_post_text"] = post_text
    context.user_data["studio_tone"] = "friendly"

    await msg.reply_text(
        _studio_preview_text(post_text, "friendly", context.user_data.get("studio_file_id")),
        reply_markup=get_ai_tone_keyboard("friendly"),
        parse_mode="HTML",
    )
    return AI_TONE_SELECT


async def ai_tone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI_TONE_SELECT: tanlangan uslubda postni QAYTA generatsiya qiladi."""
    query = update.callback_query
    await query.answer()  # SPEKS: darhol answer — tugma "yopishib" qolmaydi
    user_id = query.from_user.id
    is_admin = (user_id in ADMIN_IDS_SET)

    tone = (query.data or "").split(":", 1)[-1]
    if tone not in AI_TONE_LABELS:
        return AI_TONE_SELECT

    base_prompt = context.user_data.get("studio_topic") or ""
    current_post = context.user_data.get("studio_post_text") or ""
    if not base_prompt and not current_post:
        await _safe_edit(
            query,
            "⚠️ Sessiya eskirgan. Mavzuni qaytadan yuboring.",
            get_ai_back_keyboard(),
        )
        return AI_PROMPT_INPUT

    # Uslub almashtirish qo'shimcha ball YEMAYDI, lekin rate-limit bilan himoyalangan
    if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
        await query.answer("⏳ Juda tez-tez so'rov. Iltimos, 1 daqiqa kuting.", show_alert=True)
        return AI_TONE_SELECT

    prompt = base_prompt or (
        "Quyidagi post matnini tanlangan uslubda qayta yozing "
        f"(mazmun va faktlarni saqlang):\n\n{current_post}"
    )

    try:
        await query.edit_message_text(
            f"🎨 <i>{AI_TONE_LABELS[tone]} uslubi qo'llanmoqda...</i>",
            parse_mode="HTML",
        )
    except Exception:
        pass

    try:
        result = await generate_ai_response(prompt, tone=tone)
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
            AI_UNAVAILABLE_MSG,
            reply_markup=get_ai_back_keyboard(),
            parse_mode="HTML",
        )
        return AI_MENU_STATE

    context.user_data["studio_tone"] = tone
    context.user_data["studio_post_text"] = post_text
    await _safe_edit(
        query,
        _studio_preview_text(post_text, tone, context.user_data.get("studio_file_id")),
        get_ai_tone_keyboard(tone),
    )
    return AI_TONE_SELECT


async def ai_studio_schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI_TONE_SELECT → vaqt tanlash (AI_GET_TIME) ga o'tkazadi."""
    query = update.callback_query
    await query.answer()  # SPEKS: darhol answer

    post_text = context.user_data.get("studio_post_text", "")
    if not post_text:
        await _safe_edit(
            query,
            "⚠️ Avval post yarating. Mavzuni yozing:",
            get_ai_back_keyboard(),
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
    )
    return AI_GET_TIME


async def ai_audit_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI_AUDIT_INPUT: yuborilgan post matnini AI bilan audit qiladi."""
    msg = update.message
    if msg is None:
        return AI_AUDIT_INPUT
    text = (msg.text or msg.caption or "").strip()
    if not text:
        await msg.reply_text(
            "🔍 Auditlash uchun post matnini yuboring:",
            reply_markup=get_ai_back_keyboard(),
        )
        return AI_AUDIT_INPUT

    user_id = update.effective_user.id
    ok, is_admin, is_pro = await _studio_ai_preflight(update, context)
    if not ok:
        return AI_MENU_STATE

    msg_wait = await msg.reply_text("🔍 <i>AI audit qilmoqda...</i>", parse_mode="HTML")
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(context.bot, msg.chat_id, stop_typing))
    try:
        result = await generate_ai_response(
            f"Auditlanadigan post matni:\n\n{text}",
            system_instruction=AI_AUDIT_SYSTEM,
        )
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
            AI_UNAVAILABLE_MSG,
            reply_markup=get_ai_back_keyboard(),
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
            "⚠️ AI audit natijasini qaytara olmadi. Qaytadan urinib ko'ring.",
            reply_markup=get_ai_back_keyboard(),
        )
        return AI_MENU_STATE

    # Muvaffaqiyatli audit kunlik AI sanagichiga qo'shiladi (faqat free)
    if not is_admin and not is_pro:
        await db.run_db(db.increment_ai_usage, user_id)

    ad_line = await get_auto_ad_injection_async(user_id)
    await msg.reply_text(
        f"🔍 <b>AI Audit natijasi:</b>\n\n{safe_html(audit[:3500])}{ad_line}",
        reply_markup=get_ai_back_keyboard(),
        parse_mode="HTML",
    )
    return AI_MENU_STATE


async def ai_back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """⬅️ Orqaga — AI Studio menyusiga qaytaradi (xabar EDIT, o'chirish YO'Q)."""
    query = update.callback_query
    await query.answer()  # SPEKS: darhol answer
    await _safe_edit(query, AI_STUDIO_MENU_TEXT, get_ai_studio_keyboard())
    return AI_MENU_STATE


async def ai_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """❌ Bekor qilish — faqat SHU yerda sessiya ataylab yakunlanadi (END)."""
    query = update.callback_query
    await query.answer("Bekor qilindi")  # SPEKS: darhol answer
    try:
        await query.edit_message_text("❌ AI Studio sessiyasi yakunlandi.", reply_markup=None)
    except Exception:
        pass
    clear_ai_context(query.from_user.id)
    clear_fsm_data(context)
    await query.message.reply_text(
        "🏠 Asosiy menyu.",
        reply_markup=get_main_keyboard(query.from_user.id in ADMIN_IDS_SET),
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


def _photo_result_text(post_text: str) -> str:
    """Vision natijasi — to'liq post + keyingi qadam tugmalari."""
    return (
        "🖼 <b>Rasmdan tayyorlangan post:</b>\n\n"
        f"{safe_html(post_text[:3500])}\n\n"
        "🖼 <i>Yuborilgan rasm ushbu postga biriktiriladi.</i>\n\n"
        "Keyingi qadamni tanlang 👇"
    )


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


async def ai_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI_PHOTO_INPUT / AI_MENU_STATE: rasm qabul qiladi va vision post yozadi."""
    msg = update.message
    if msg is None:
        return AI_PHOTO_INPUT
    user_id = update.effective_user.id

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
                "🎬 <b>Video tahlil qilinmaydi.</b>\n\n"
                "Server resursini tejash uchun faqat <b>rasm</b> tahlil qilinadi.\n"
                "Iltimos, tahlil qilinishi kerak bo'lgan <b>rasmni</b> "
                "(JPG/PNG/WEBP) yuboring.",
                reply_markup=get_ai_back_keyboard(),
                parse_mode="HTML",
            )
        else:
            await msg.reply_text(
                "🖼 Iltimos, rasm (JPG/PNG/WEBP) yuboring:\n"
                "• <i>Rasm bilan birga izoh yuborish mumkin</i>\n"
                "• <i>Video tahlil qilinmaydi — faqat rasm</i>",
                reply_markup=get_ai_back_keyboard(),
                parse_mode="HTML",
            )
        return AI_PHOTO_INPUT

    ok, is_admin, is_pro = await _studio_ai_preflight(update, context)
    if not ok:
        return AI_MENU_STATE

    msg_wait = await msg.reply_text("🖼 <i>AI rasmni tahlil qilmoqda...</i>", parse_mode="HTML")
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(context.bot, msg.chat_id, stop_typing))
    try:
        result = await _vision_run(file_id, extra_prompt)
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
            f"{result['error']}\n\n"
            "🖼 Yana rasm yuboring yoki menyuga qayting 👇",
            reply_markup=get_ai_back_keyboard(),
            parse_mode="HTML",
        )
        return AI_PHOTO_INPUT

    post_text = (result.get("post_text") or "").strip()
    if not post_text:
        await _studio_ai_refund(user_id, is_admin, is_pro)
        await msg.reply_text(
            "⚠️ AI post matnini tayyorlay olmadi. Rasmni qaytadan yuboring.",
            reply_markup=get_ai_back_keyboard(),
            parse_mode="HTML",
        )
        return AI_PHOTO_INPUT

    context.user_data["studio_post_text"] = post_text
    context.user_data["studio_file_id"] = file_id
    context.user_data["studio_post_type"] = "photo"
    context.user_data["studio_tone"] = "friendly"
    context.user_data["studio_photo_extra"] = extra_prompt

    # Muvaffaqiyatli vision so'rovi kunlik AI sanagichiga qo'shiladi (faqat free)
    if not is_admin and not is_pro:
        await db.run_db(db.increment_ai_usage, user_id)

    await msg.reply_text(
        _photo_result_text(post_text),
        reply_markup=get_ai_photo_keyboard(),
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

    post_text = context.user_data.get("studio_post_text", "")
    file_id = context.user_data.get("studio_file_id")
    if not post_text or not file_id:
        await _safe_edit(
            query,
            "⚠️ Sessiya eskirgan. Rasmni qaytadan yuboring.",
            get_ai_back_keyboard(),
        )
        return AI_PHOTO_INPUT

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
        await _show_time_prompt(query.message, post_text, file_id, "photo")
        return AI_GET_TIME

    # --- 2) Tahrirlash → matn talabi holatiga o'tamiz ---
    if data == "photo_edit":
        await _safe_edit(
            query,
            "✏️ <b>Postni tahrirlash</b>\n\n"
            "Qanday o'zgarish kerak? Matn yuboring:\n"
            "<i>Masalan: «sarlavhani boshqacha yoz», «qisqartir», "
            "«narxni qo'sh»</i>",
            get_ai_back_keyboard(),
        )
        return AI_PHOTO_EDIT_INPUT

    # --- 3) Qayta yozish → rasmni qayta tahlil qilib boshqa uslubda yozadi ---
    if data == "photo_rewrite":
        # Uslub almashtirish kabi qo'shimcha bal YEMAYDI (rate-limit saqlanadi)
        if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
            await query.answer("⏳ Juda tez-tez so'rov. Iltimos, 1 daqiqa kuting.", show_alert=True)
            return AI_PHOTO_RESULT

        extra = context.user_data.get("studio_photo_extra", "")
        rewrite_ctx = (
            "Quyidagi tayyor postni RASMNI QAYTA TAHLIL QILIB, butunlay boshqacha "
            "uslubda (yangi sarlavha, yangi CTA va yangi hashtaglar bilan) qayta yozing:\n\n"
            f"{post_text}"
        )
        try:
            await query.edit_message_text(
                "🔄 <i>AI rasmni qayta tahlil qilmoqda...</i>",
                parse_mode="HTML",
            )
        except Exception:
            pass
        result = await _vision_run(file_id, extra, rewrite_context=rewrite_ctx)
        if "error" in result:
            await _safe_edit(query, _photo_result_text(post_text), get_ai_photo_keyboard())
            await query.message.reply_text(
                f"⚠️ {result['error']}",
                reply_markup=get_ai_back_keyboard(),
                parse_mode="HTML",
            )
            return AI_PHOTO_RESULT

        new_text = (result.get("post_text") or "").strip()
        if not new_text:
            await _safe_edit(query, _photo_result_text(post_text), get_ai_photo_keyboard())
            await query.message.reply_text(
                "⚠️ AI qayta yozishda post tayyorlay olmadi. Asl post saqlanib qoldi.",
                reply_markup=get_ai_back_keyboard(),
            )
            return AI_PHOTO_RESULT

        context.user_data["studio_post_text"] = new_text
        await _safe_edit(query, _photo_result_text(new_text), get_ai_photo_keyboard())
        return AI_PHOTO_RESULT

    return AI_PHOTO_RESULT


async def ai_photo_edit_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI_PHOTO_EDIT_INPUT: tahrirlash talabini qabul qilib AI orqali qo'llaydi."""
    msg = update.message
    if msg is None:
        return AI_PHOTO_EDIT_INPUT
    user_id = update.effective_user.id

    text = (msg.text or msg.caption or "").strip()
    if not text:
        await msg.reply_text(
            "✏️ Tahrirlash uchun matn yuboring:",
            reply_markup=get_ai_back_keyboard(),
        )
        return AI_PHOTO_EDIT_INPUT

    post_text = context.user_data.get("studio_post_text", "")
    if not post_text:
        await msg.reply_text(
            "⚠️ Sessiya eskirgan. Rasmni qaytadan yuboring.",
            reply_markup=get_ai_back_keyboard(),
        )
        return AI_PHOTO_INPUT

    # Tahrirlash ham yangi AI chaqiruv — preflight (ball/limit) qo'llaniladi
    ok, is_admin, is_pro = await _studio_ai_preflight(update, context)
    if not ok:
        return AI_MENU_STATE

    msg_wait = await msg.reply_text("✏️ <i>AI postni tahrirlamoqda...</i>", parse_mode="HTML")
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(context.bot, msg.chat_id, stop_typing))
    try:
        result = await generate_ai_response(
            f"Tahrirlanadigan post:\n\n{post_text}\n\n"
            f"Foydalanuvchi talabi:\n{text}",
            system_instruction=PHOTO_EDIT_SYSTEM,
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
            reply_markup=get_ai_back_keyboard(),
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
            "⚠️ AI tahrirlangan matnni qaytara olmadi. Qaytadan urinib ko'ring.",
            reply_markup=get_ai_back_keyboard(),
        )
        return AI_PHOTO_EDIT_INPUT

    context.user_data["studio_post_text"] = new_text
    if not is_admin and not is_pro:
        await db.run_db(db.increment_ai_usage, user_id)

    await msg.reply_text(
        _photo_result_text(new_text),
        reply_markup=get_ai_photo_keyboard(),
        parse_mode="HTML",
    )
    return AI_PHOTO_RESULT
