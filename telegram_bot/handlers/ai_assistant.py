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
from utils.ai_agent import analyze_user_prompt, extract_schedule_time, clear_ai_context
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


def _no_credits_text(bot_username: str, user_id: int) -> str:
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    return (
        "⚠️ <b>Sizda bepul AI so'rovlari soni tugadi!</b>\n\n"
        "Ko'proq so'rov olish uchun do'stlaringizni taklif qiling.\n"
        "🎁 <i>Har bir do'stingiz uchun sizga <b>+3 ta bepul AI so'rovi</b> beriladi!</i>\n"
        "Yoki kabinetdan <b>🎁 Kunlik bonus</b> ni oling.\n\n"
        f"🔗 Sizning taklif havolangiz:\n<code>{ref_link}</code>"
    )


async def start_ai_assistant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI yordamchisi holatini (AI_INPUT) boshlaydi."""
    context.user_data.clear()
    user_id = update.effective_user.id
    clear_ai_context(user_id)
    is_admin = (user_id in ADMIN_IDS_SET)
    is_pro = await db.run_db(db.is_premium, user_id)
    credits = await db.run_db(db.get_user_credits, user_id)

    # PRO/Enterprise foydalanuvchi cheksiz AI oladi — ball talab qilinmaydi.
    if not is_admin and not is_pro and credits <= 0:
        bot_obj = await context.bot.get_me()
        await update.message.reply_text(
            _no_credits_text(bot_obj.username, user_id),
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
            _no_credits_text(bot_obj.username, user_id),
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
        context.user_data.clear()
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
        context.user_data.clear()
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
            f"Yana post yaratish uchun <b>🤖 AI Post Yordamchi</b> ni bosing yoki menyuga qayting.{ad_line}",
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
    context.user_data.clear()
    return ConversationHandler.END
