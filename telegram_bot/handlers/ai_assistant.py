import logging
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import (
    BTN_T_5MIN, BTN_T_15MIN, BTN_T_1H, BTN_T_DAILY, BTN_T_WEEKLY,
    get_cancel_keyboard, get_main_keyboard, get_ai_time_keyboard,
)
from utils.ai_agent import analyze_user_prompt, extract_schedule_time
from utils.helpers import (
    html_escape, check_ai_rate_limit, check_ai_daily_limit, parse_future_time,
)

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

AI_INPUT = 401
AI_CONFIRM = 402
AI_GET_TIME = 403

# AI postini saqlashdan keyin "yana post yaratish" uchun savol beriladi
AI_CONFIRM_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("✅ Kanalga rejalashtirish", callback_data="ai_post_schedule")],
    [InlineKeyboardButton("📝 Matnni tahrirlash", callback_data="ai_post_retry")],
    [InlineKeyboardButton("🚫 Bekor qilish", callback_data="ai_post_cancel")],
])


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
    """AI yordamchisi: suhbat, savol-javob VA post rejalashtirish (intent routing)."""
    context.user_data.clear()
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)
    credits = await db.run_db(db.get_user_credits, user_id)

    if not is_admin and credits <= 0:
        bot_obj = await context.bot.get_me()
        await update.message.reply_text(
            _no_credits_text(bot_obj.username, user_id),
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    limit_info = "♾ Cheksiz (Super Admin)" if is_admin else f"<b>{credits} ta</b>"

    await update.message.reply_text(
        "🤖 <b>AI Yordamchiga xush kelibsiz!</b>\n\n"
        f"💎 Mavjud AI so'rovlari: {limit_info}\n\n"
        "Men sizga 3 xil yordam bera olaman:\n"
        "❓ <b>Savol-javob</b> — bot, postlar, ballar, kanallar haqida istalgan savol bering.\n"
        "📝 <b>Post yaratish</b> — post mavzusini yozing yoki tayyor post/forward/rasm yuboring.\n"
        "🕒 <b>Erkin buyruq</b> — masalan: <i>“bugun 15:45 ga hamma kanalga rejalashtir”</i>.\n\n"
        "👉 Post yuboring, savol bering yoki buyruq yozing. Bekor qilish uchun pastdagi tugmani bosing.",
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
        # Caption limiti 1024 — qisqartiriladi, to'liq matn alohida yuboriladi
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
    """Vaqt tanlash oynasini ko'rsatadi (post qayta yuborilmaydi)."""
    header = (
        "✨ <b>Post qabul qilindi!</b>\n\n"
        f"{html_escape(post_text[:1500])}\n\n"
        "🕒 <b>Ushbu post qachon kanalga chiqsin?</b>\n"
        "Quyidagi tugmalardan tanlang yoki erkin yozing:\n"
        "• <i>“ertaga ertalab 9 ga”</i>\n"
        "• <i>“bugun 15:45 ga hamma kanalga”</i>\n"
        "• <i>“1 soatdan keyin”</i>"
    )
    await _send_preview(msg, header, file_id, post_type, get_ai_time_keyboard())


async def ai_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)

    # Albom (media_group) dublikatlarini bitta ishlov bilan cheklaymiz
    if msg.media_group_id:
        if context.user_data.get("last_ai_media_group_id") == msg.media_group_id:
            return AI_INPUT
        context.user_data["last_ai_media_group_id"] = msg.media_group_id

    text_input = (msg.text or msg.caption or "").strip()
    file_id, post_type = _extract_media(msg)

    # Yangi media yuborilsa — eskisini almashtiramiz
    if file_id:
        context.user_data["ai_file_id"] = file_id
        context.user_data["ai_post_type"] = post_type
    else:
        post_type = context.user_data.get("ai_post_type", "text")
        file_id = context.user_data.get("ai_file_id")

    prompt = _build_prompt(text_input, context)

    # Rate-limitlar (faqat AI API'ga murojaat qilinganda)
    if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
        await msg.reply_text(
            "⏳ <i>AI so'rovlarini juda tez-tez yuboryapsiz. Iltimos, 1 daqiqa kuting...</i>",
            parse_mode="HTML",
        )
        return AI_INPUT

    # Media-only (matnsiz rasm/hujjat) va o'zi post bo'lishi mumkin bo'lgan xabar:
    # AI'ga so'rov yubormasdan vaqt so'rash (ball tejaladi, post takrorlanmaydi).
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

    # Kunlik limit
    if not is_admin and check_ai_daily_limit(user_id, max_per_day=30):
        await msg.reply_text(
            "⚠️ <i>Kunlik AI so'rovlar limiti tugadi (30 ta/kun). Ertaga qayta urinib ko'ring.</i>",
            parse_mode="HTML",
        )
        return AI_INPUT

    # Ballni atomik band qilamiz (parallel so'rovlar balansdan oshib ketmasligi uchun)
    if not is_admin and not await db.run_db(db.use_user_credit, user_id):
        bot_obj = await context.bot.get_me()
        await msg.reply_text(
            _no_credits_text(bot_obj.username, user_id),
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    msg_wait = await msg.reply_text("⏳ <i>AI tahlil qilmoqda, iltimos kuting...</i>", parse_mode="HTML")
    result = await analyze_user_prompt(prompt, user_id)

    try:
        await msg_wait.delete()
    except Exception:
        pass

    if "error" in result:
        # Xato bo'lsa — sarflangan ballni qaytaramiz
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
        await msg.reply_text(
            f"🤖 {html_escape(reply)}\n\n<i>Yana savol bering yoki post yuboring 👇</i>",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
        return AI_INPUT

    # B/C) POST yoki EDIT
    post_text = result.get("post_text", "") or ""
    if not post_text:
        # Model post matnini bermasa — javob sifatida ko'rsatamiz
        reply = result.get("reply", "") or "Post matnini aniqlab bo'lmadi. Iltimos, qaytadan yuboring."
        await msg.reply_text(html_escape(reply), reply_markup=get_cancel_keyboard(), parse_mode="HTML")
        return AI_INPUT

    sched_time = result.get("scheduled_time")
    has_explicit = result.get("has_explicit_time", False)
    target_all = result.get("target_all", False)

    context.user_data["ai_generated_post"] = post_text
    context.user_data["ai_scheduled_time"] = sched_time
    context.user_data["ai_target_all"] = target_all

    # Vaqt tekshiruvi: o'tib ketgan bo'lsa — qaytadan so'raymiz
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
        f"{html_escape(post_text[:3000])}\n\n"
        f"🕒 <b>Chiqish vaqti:</b> <code>{sched_time}</code>{target_info}\n\n"
        "Ushbu postni rejalashtiramizmi?"
    )
    await _send_preview(msg, preview, file_id, post_type, AI_CONFIRM_KEYBOARD)
    return AI_CONFIRM


async def ai_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vaqt kutish holati: erkin til ham, tugmalar ham, savollar ham qabul qilinadi."""
    # Matnsiz media (rasm/fayl) yuborilsa — postga biriktiramiz va vaqtni so'rashda davom etamiz
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
    is_admin = (user_id == ADMIN_ID)

    # Takrorlanuvchi post tugmalari AI oqimida qo'llanmaydi
    if text in (BTN_T_DAILY, BTN_T_WEEKLY):
        await update.message.reply_text(
            "ℹ️ <i>AI yordamchisi orqali faqat bir martalik post rejalashtiriladi.</i>\n"
            "Har kunlik/haftalik takrorlanuvchi postlar uchun <b>➕ Yangi post rejalashtirish</b> bo'limidan foydalaning.\n\n"
            "Vaqtni yozing (masalan: <i>“ertaga 10:00 ga”</i>) yoki tezkor tugmani tanlang:",
            reply_markup=get_ai_time_keyboard(),
            parse_mode="HTML",
        )
        return AI_GET_TIME

    # Tezkor tugmalar
    post_time = None
    if text == BTN_T_5MIN:
        post_time = now + timedelta(minutes=5)
    elif text == BTN_T_15MIN:
        post_time = now + timedelta(minutes=15)
    elif text == BTN_T_1H:
        post_time = now + timedelta(hours=1)
    else:
        # 1) Avval lokal parser (tekin, bir zumda)
        post_time = parse_future_time(text)

        # 2) Lokal parser aniqlay olmasa — AI orqali (savol bo'lsa javob ham qaytishi mumkin)
        if post_time is None and text:
            if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
                await update.message.reply_text(
                    "⏳ <i>Juda tez-tez so'rov yuboryapsiz. 1 daqiqa kuting yoki vaqtni "
                    "aniq formatda yozing: <code>2026-08-30 18:00</code></i>",
                    parse_mode="HTML",
                )
                return AI_GET_TIME

            msg_wait = await update.message.reply_text("⏳ <i>Vaqt aniqlanmoqda...</i>", parse_mode="HTML")
            ai_res = await extract_schedule_time(
                f"Foydalanuvchining vaqt haqidagi xabari: {text}", user_id
            )
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
                    # Foydalanuvchi savol bergan — AI javobini ko'rsatamiz va vaqtni yana so'raymiz
                    await update.message.reply_text(
                        f"🤖 {html_escape(ai_res['reply'])}\n\n"
                        "Post vaqtini esa quyidagicha yozing: <i>“ertaga 10:00 ga”</i> yoki tugmani tanlang:",
                        reply_markup=get_ai_time_keyboard(),
                        parse_mode="HTML",
                    )
                    return AI_GET_TIME

        # 3) Aniq format (oxirgi zaxira)
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
        f"{html_escape(post_text[:2500])}\n\n"
        f"🕒 <b>Chiqish vaqti:</b> <code>{time_str}</code>{target_info}\n\n"
        "Rejalashtiramizmi?",
        reply_markup=AI_CONFIRM_KEYBOARD,
        parse_mode="HTML",
    )
    return AI_CONFIRM


async def ai_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    is_admin = (user_id == ADMIN_ID)

    if data == "ai_post_cancel":
        await query.answer("Bekor qilindi")
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
        target_name = "Barcha ulangan kanallarga" if target_all else channels[0][1]
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            "✅ <b>AI Posti muvaffaqiyatli rejalashtirildi!</b>\n\n"
            f"📢 Joylash: <b>{html_escape(target_name)}</b>\n"
            f"⏰ Chiqish vaqti: <b>{post_time.strftime('%Y-%m-%d %H:%M')}</b>\n\n"
            "Yana post yaratish uchun <b>🤖 AI Yordamchi</b> ni bosing yoki menyuga qayting.",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML",
        )
    else:
        await query.message.reply_text(
            "❌ Saqlashda xatolik yuz berdi. Iltimos, keyinroq urinib ko'ring.",
            reply_markup=get_main_keyboard(is_admin),
        )

    context.user_data.clear()
    return ConversationHandler.END
