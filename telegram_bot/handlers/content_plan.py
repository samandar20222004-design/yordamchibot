"""Content Plan Generator — AI yordamida haftalik kontent-reja tuzish."""
import logging
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import get_cancel_keyboard, get_main_keyboard
from keyboards.inline import btn_label
from keyboards.callback_data import cb
from locales.translations import (
    get_lang, safe_t, is_main_menu_text, localize_service_error,
)
from utils.date_format import format_datetime, weekday_label
from utils.helpers import html_escape, safe_html, get_auto_ad_injection_async, keep_typing

logger = logging.getLogger(__name__)

# States
# Eslatma: 401-403 AI_ASSISTANT bilan to'qnashgan edi — endi 411-413 unikal.
PLAN_CHOOSE_CHANNEL = 411
PLAN_GET_TOPIC = 412
PLAN_VIEW = 413

# ============================================================
# 🚀 7 KUNLIK REJANI BITTA TUGMA BILAN NAVBATGA QO'YISH
# ============================================================
# Butun bot uchun yagona vaqt zonasi (scheduler.TIMEZONE_NAME bilan bir xil) —
# shunda DB'ga yozilgan scheduled_time va APScheduler tick'lari mos keladi.
tashkent_tz = pytz.timezone("Asia/Tashkent")

#: Haftalik postlar har kuni shu soatda chiqadi (talab: 12:00).
PLAN_SCHEDULE_HOUR = 12
PLAN_SCHEDULE_MINUTE = 0
#: Rejadagi kunlar soni (dushanba → yakshanba).
PLAN_WEEK_DAYS = 7

#: "🚀 Barchasini 7 kunga rejalashtirish" tugmasining callback_data'si.
# ``plan_`` prefiksi bilan boshlanadi — PLAN_VIEW holatidagi
# ``CallbackQueryHandler(plan_view_callback, pattern=r"^plan_")`` uni ushlaydi.
CB_PLAN_SCHEDULE_ALL = "plan_sched_all"


def week_schedule_times(count: int = PLAN_WEEK_DAYS,
                        hour: int = PLAN_SCHEDULE_HOUR,
                        minute: int = PLAN_SCHEDULE_MINUTE,
                        now=None) -> list:
    """Dushanbadan boshlab ``count`` ta kun uchun soat ``hour:minute`` vaqtlarini qaytaradi.

    Qoidalar:
      * ro'yxat har doim **dushanba** (weekday 0) dan boshlanadi;
      * agar shu haftaning dushanba 12:00'i allaqachon o'tgan bo'lsa (yoki bugun
        dushanba va 12:00 dan kech bo'lsa) — **keyingi hafta** dushanbasidan
        boshlanadi. Shunday qilib hech bir post o'tmishga tushmaydi va
        scheduler uni darhol "muddati o'tgan" deb yubormaydi;
      * barcha vaqtlar Toshkent zonasida (aware ``datetime``) — Neon DB'dagi
        ``TIMESTAMP WITH TIME ZONE`` ustuniga to'g'ri yoziladi.
    """
    reference = now if now is not None else datetime.now(tashkent_tz)
    if reference.tzinfo is None:
        reference = tashkent_tz.localize(reference)
    reference = reference.astimezone(tashkent_tz)

    days_to_monday = (0 - reference.weekday()) % 7
    monday = (reference + timedelta(days=days_to_monday)).date()
    first = tashkent_tz.localize(datetime(monday.year, monday.month, monday.day, hour, minute))
    if first <= reference:
        first = first + timedelta(days=7)
    return [first + timedelta(days=i) for i in range(max(0, int(count)))]


def build_plan_post_text(item: dict, index: int = 0, lang: str = "uz") -> str:
    """Kontent-reja elementidan kanalga chiqadigan post matnini (HTML) quradi.

    Postlar ``parse_mode="HTML"`` bilan yuboriladi, shuning uchun AI matni
    ``html_escape`` orqali xavfsizlashtiriladi — aks holda matndagi ``<`` yoki
    ``&`` butun postni ``BadRequest`` bilan yiqitadi.
    """
    item = item or {}
    title = str(item.get("title") or "").strip()
    idea = str(item.get("idea") or "").strip()
    if not title:
        title = str(
            item.get("day") or safe_t("cp_day_fallback", lang, n=index + 1)
        ).strip()
    parts = [f"<b>{html_escape(title)}</b>"]
    if idea:
        parts.append(html_escape(idea))
    return "\n\n".join(parts)


def _get_plan_channel_keyboard(channels: list, lang: str = "uz") -> InlineKeyboardMarkup:
    """Kontent-reja uchun kanal tanlash keyboard."""
    keyboard = []
    for ch in channels:
        ch_id, ch_title = ch[:2]
        keyboard.append([
            InlineKeyboardButton(
                f"📢 {btn_label(ch_title)}",
                callback_data=cb(f"plan_ch:{ch_id}"),
            )
        ])
    keyboard.append([
        InlineKeyboardButton(safe_t("ai_btn_close", lang), callback_data="plan_cancel")
    ])
    return InlineKeyboardMarkup(keyboard)


def _get_plan_result_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Kontent-reja natijasi uchun keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(safe_t("cp_btn_create_post", lang), callback_data="plan_create_post")],
        [InlineKeyboardButton(safe_t("cp_btn_regenerate", lang), callback_data="plan_regenerate")],
        [InlineKeyboardButton(safe_t("pend_close_btn", lang), callback_data="plan_cancel")],
    ])


def _get_plan_day_keyboard(plan_items: list, lang: str = "uz") -> InlineKeyboardMarkup:
    """Kun tanlash keyboard (post yaratish uchun).

    Eslatma: bu keyboard FAQAT kunlar + "🔙 Orqaga" tugmalaridan iborat.
    "🚀 Barchasini 7 kunga rejalashtirish" tugmasi ustiga
    :func:`_get_plan_week_keyboard` orqali qo'shiladi.
    """
    keyboard = []
    for i, item in enumerate(plan_items):
        day = item.get("day", safe_t("cp_day_fallback", lang, n=i + 1))
        title = item.get("title", "")[:30]
        keyboard.append([
            InlineKeyboardButton(
                f"📅 {day}: {title}",
                callback_data=cb(f"plan_day:{i}"),
            )
        ])
    keyboard.append([
        InlineKeyboardButton(safe_t("cp_btn_back", lang), callback_data="plan_back")
    ])
    return InlineKeyboardMarkup(keyboard)


def _get_plan_week_keyboard(plan_items: list, lang: str = "uz") -> InlineKeyboardMarkup:
    """Reja ekrani keyboard'i: [🚀 Barchasini 7 kunga rejalashtirish] + kunlar.

    Birinchi qatorda — bitta tugma bilan butun haftani navbatga qo'yish.
    Pastda odatdagi kun tanlash tugmalari va "🔙 Orqaga".
    """
    rows = [[
        InlineKeyboardButton(
            safe_t("plan_btn_schedule_all", lang),
            callback_data=CB_PLAN_SCHEDULE_ALL,
        )
    ]]
    rows += [list(row) for row in _get_plan_day_keyboard(plan_items, lang).inline_keyboard]
    return InlineKeyboardMarkup(rows)


def _plan_list_keyboard(plan_items: list, context, lang: str = "uz") -> InlineKeyboardMarkup:
    """Reja ro'yxati keyboard'i — reja allaqachon navbatga qo'yilgan bo'lsa,
    "🚀 Barchasini 7 kunga rejalashtirish" tugmasi ko'rsatilmaydi (ikki marta
    rejalashtirishning oldini oladi).
    """
    if context is not None and getattr(context, "user_data", None) is not None \
            and context.user_data.get("plan_scheduled"):
        return _get_plan_day_keyboard(plan_items, lang)
    return _get_plan_week_keyboard(plan_items, lang)


async def start_content_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kontent-reja bo'limini boshlash."""
    user_id = update.effective_user.id
    lang = get_lang(context)
    channels = await db.run_db(db.get_user_channels, user_id)

    if not channels:
        await update.message.reply_text(
            safe_t("cp_no_channel", lang),
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang=lang),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    context.user_data["plan_channels"] = channels
    await update.message.reply_text(
        safe_t("cp_choose_channel", lang),
        reply_markup=_get_plan_channel_keyboard(channels, lang),
        parse_mode="HTML",
    )
    return PLAN_CHOOSE_CHANNEL


async def plan_channel_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal tanlanganda."""
    query = update.callback_query
    await query.answer()
    data = query.data
    lang = get_lang(context)

    if data == "plan_cancel":
        await query.message.reply_text(
            safe_t("op_cancelled", lang),
            reply_markup=get_main_keyboard(query.from_user.id in ADMIN_IDS_SET, lang=lang),
        )
        return ConversationHandler.END

    if not data.startswith("plan_ch:"):
        return PLAN_CHOOSE_CHANNEL

    channel_id = data.split(":", 1)[1]
    channels = context.user_data.get("plan_channels", [])
    channel_title = safe_t("an_channel_fallback", lang)
    for ch in channels:
        if ch[0] == channel_id:
            channel_title = ch[1]
            break

    context.user_data["plan_channel_id"] = channel_id
    context.user_data["plan_channel_title"] = channel_title

    await query.message.reply_text(
        safe_t("cp_topic_ask", lang, channel=html_escape(channel_title)),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML",
    )
    return PLAN_GET_TOPIC


async def plan_topic_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mavzu qabul qilish va AI dan reja so'rash."""
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id
    lang = get_lang(context)

    if is_main_menu_text(text):
        await update.message.reply_text(
            safe_t("op_cancelled", lang),
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang=lang),
        )
        return ConversationHandler.END

    if len(text) < 3:
        await update.message.reply_text(
            safe_t("cp_topic_short", lang),
            reply_markup=get_cancel_keyboard(lang),
        )
        return PLAN_GET_TOPIC

    channel_id = context.user_data.get("plan_channel_id", "")
    channel_title = context.user_data.get(
        "plan_channel_title", safe_t("an_channel_fallback", lang)
    )
    tone = await db.run_db(db.get_channel_tone, channel_id) if channel_id else "friendly"

    # Kanalning real vaqtdagi postlar tarixini olamiz
    recent_posts = []
    if channel_id:
        history = await db.run_db(db.get_channel_posts_history, channel_id, 5)
        recent_posts = [p.get("text") for p in history if p.get("text") and not p.get("text").startswith("[")]

    await update.message.reply_text(safe_t("cp_ai_building", lang))

    from utils.ai_agent import generate_content_plan
    # Indikator darhol ko'rinsin, keyin uzoq AI so'rovi davomida yangilanib tursin.
    chat_id = update.effective_chat.id
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass
    async with keep_typing(context.bot, chat_id):
        # 🌐 Kontent-reja foydalanuvchi tilida (uz/ru/en).
        result = await generate_content_plan(
            text, channel_title, tone, recent_posts=recent_posts, lang=lang
        )

    if "error" in result:
        await update.message.reply_text(
            localize_service_error(result["error"], lang),
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang=lang),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    plan_items = result.get("plan", [])
    if not plan_items:
        await update.message.reply_text(
            safe_t("cp_ai_failed_retry", lang),
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang=lang),
        )
        return ConversationHandler.END

    context.user_data["plan_items"] = plan_items
    context.user_data["plan_topic"] = text
    # Yangi reja — eski "navbatga qo'yilgan" belgisi tozalanadi.
    context.user_data["plan_scheduled"] = False

    # Format plan as text
    plan_text = safe_t(
        "cp_plan_header", lang,
        channel=html_escape(channel_title), topic=html_escape(text),
    )

    for i, item in enumerate(plan_items):
        day = item.get("day", safe_t("cp_day_fallback", lang, n=i + 1))
        fmt = item.get("format", "")
        title = item.get("title", "")
        idea = item.get("idea", "")
        plan_text += safe_t(
            "cp_plan_day", lang, day=day,
            fmt=html_escape(fmt), title=html_escape(title),
        )
        if idea:
            plan_text += safe_t("cp_plan_idea", lang, idea=html_escape(idea[:150]))
        plan_text += "\n"

    ad_line = await get_auto_ad_injection_async(user_id)
    plan_text += f"{ad_line}" + safe_t("cp_plan_footer", lang)
    plan_text += safe_t("plan_week_hint", lang)

    await update.message.reply_text(
        plan_text,
        reply_markup=_plan_list_keyboard(plan_items, context, lang),
        parse_mode="HTML",
    )
    return PLAN_VIEW


async def plan_schedule_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🚀 "Barchasini 7 kunga rejalashtirish" — butun haftani navbatga qo'yadi.

    Nima qiladi:
      1. Rejadagi har bir kun (dushanba → yakshanba) uchun soat **12:00** ga
         post matnini tayyorlaydi (:func:`build_plan_post_text`);
      2. ``database.schedule_week_posts`` orqali 7 ta postni **BITTA
         tranzaksiyada** ``scheduled_posts`` jadvaliga yozadi (hammasi yoki
         hech narsa — yarim-yorti navbat qolmaydi);
      3. Mavjud APScheduler tick'lari (``scheduler.check_and_send_posts``)
         ularni muddati kelganda kanallarga avtomatik chiqaradi — alohida
         job yaratish shart emas;
      4. "✅ 7 kunlik postlar navbatga qo'yildi!" tasdig'ini ko'rsatadi va
         tugmani klaviaturadan olib tashlaydi (ikki marta bosish himoyasi).
    """
    query = update.callback_query
    lang = get_lang(context)
    user_id = query.from_user.id

    plan_items = context.user_data.get("plan_items") or []
    channel_id = context.user_data.get("plan_channel_id") or ""
    channel_title = context.user_data.get("plan_channel_title") or ""

    # 1) Sessiya eskirgan (bot qayta ishga tushgan) — reja xotirada yo'q.
    if not plan_items:
        try:
            await query.answer(safe_t("plan_sched_stale", lang), show_alert=True)
        except Exception:
            pass
        return PLAN_VIEW

    # 2) Ikki marta rejalashtirish himoyasi.
    if context.user_data.get("plan_scheduled"):
        try:
            await query.answer(safe_t("plan_sched_already", lang), show_alert=True)
        except Exception:
            pass
        return PLAN_VIEW

    # 3) Kanal foydalanuvchiga tegishli ekanini tekshiramiz (xavfsizlik:
    #    user_data'ga yozilgan id bazadagi kanallarga mos kelishi shart).
    channels = context.user_data.get("plan_channels")
    if not channels:
        try:
            channels = await db.run_db(db.get_user_channels, user_id)
        except Exception:
            logger.exception("Kanallar ro'yxatini olishda xato (user=%s)", user_id)
            channels = []
    owned = {str(ch[0]) for ch in (channels or [])}
    if not channel_id or str(channel_id) not in owned:
        try:
            await query.answer(safe_t("plan_sched_no_channel", lang), show_alert=True)
        except Exception:
            pass
        return PLAN_VIEW

    # Darhol javob — DB yozuvi tugaguncha tugma "yopishib" qolmaydi.
    try:
        await query.answer(safe_t("plan_sched_busy", lang))
    except Exception:
        pass

    # 4) Dushanba → yakshanba, har kuni 12:00 (Toshkent).
    times = week_schedule_times(len(plan_items))
    posts = [
        (moment, build_plan_post_text(item, i, lang))
        for i, (moment, item) in enumerate(zip(times, plan_items))
    ]

    # 5) BITTA tranzaksiyada navbatga yozamiz. Neon uzilishi yoki boshqa xato
    #    bo'lsa ham handler yiqilmaydi — foydalanuvchi aniq xabar oladi.
    try:
        result = await db.run_db(db.schedule_week_posts, user_id, channel_id, posts)
    except Exception as exc:
        logger.exception(
            "Haftalik reja navbatga qo'yilmadi (user=%s, kanal=%s): %s",
            user_id, channel_id, exc,
        )
        result = {"success": False, "count": 0, "ids": [], "times": [], "error": str(exc)}

    if not result.get("success"):
        logger.error(
            "Haftalik reja navbatga qo'yilmadi (user=%s, kanal=%s): %s",
            user_id, channel_id, result.get("error"),
        )
        await query.message.reply_text(
            safe_t("plan_sched_error", lang),
            reply_markup=_get_plan_day_keyboard(plan_items, lang),
            parse_mode="HTML",
        )
        return PLAN_VIEW

    context.user_data["plan_scheduled"] = True
    scheduled_times = result.get("times") or times

    # 6) Tasdiq: har bir kun va aniq vaqt ro'yxati bilan.
    day_lines = []
    for i, moment in enumerate(scheduled_times):
        moment_tz = moment.astimezone(tashkent_tz) if moment.tzinfo else tashkent_tz.localize(moment)
        day_lines.append(safe_t(
            "plan_sched_day_line", lang,
            day=weekday_label(moment_tz.weekday(), lang),
            time=format_datetime(moment_tz, lang, style="list"),
        ))

    confirm_text = safe_t(
        "plan_sched_done", lang,
        channel=html_escape(channel_title or channel_id),
        count=result.get("count", len(scheduled_times)),
        days="\n".join(day_lines),
    )
    await query.message.reply_text(confirm_text, parse_mode="HTML")

    # 7) Tugmani klaviaturadan olamiz — eski xabardan qayta bosib bo'lmaydi.
    try:
        await query.edit_message_reply_markup(
            reply_markup=_get_plan_day_keyboard(plan_items, lang)
        )
    except Exception:
        pass
    return PLAN_VIEW


async def plan_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kun tanlash yoki qayta generatsiya."""
    query = update.callback_query
    data = query.data
    is_admin = query.from_user.id in ADMIN_IDS_SET
    lang = get_lang(context)

    # 🚀 Bitta tugma bilan butun haftani navbatga qo'yish
    if data == CB_PLAN_SCHEDULE_ALL:
        return await plan_schedule_all(update, context)

    if data == "plan_cancel":
        await query.answer()
        await query.message.reply_text(
            safe_t("cp_closed", lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
        )
        return ConversationHandler.END

    if data == "plan_back":
        await query.answer()
        channels = context.user_data.get("plan_channels", [])
        await query.message.reply_text(
            safe_t("cp_back_title", lang),
            reply_markup=_get_plan_channel_keyboard(channels, lang),
            parse_mode="HTML",
        )
        return PLAN_CHOOSE_CHANNEL

    if data == "plan_regenerate":
        await query.answer(safe_t("cp_regenerating", lang))
        topic = context.user_data.get("plan_topic", "")
        channel_id = context.user_data.get("plan_channel_id", "")
        channel_title = context.user_data.get(
            "plan_channel_title", safe_t("an_channel_fallback", lang)
        )
        tone = await db.run_db(db.get_channel_tone, channel_id) if channel_id else "friendly"

        # Kanalning postlar tarixini olamiz
        recent_posts = []
        if channel_id:
            history = await db.run_db(db.get_channel_posts_history, channel_id, 5)
            recent_posts = [p.get("text") for p in history if p.get("text") and not p.get("text").startswith("[")]

        from utils.ai_agent import generate_content_plan
        # Indikator darhol ko'rinsin, keyin uzoq AI so'rovi davomida yangilanib tursin.
        chat_id = query.message.chat_id
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass
        async with keep_typing(context.bot, chat_id):
            result = await generate_content_plan(
                topic, channel_title, tone, recent_posts=recent_posts, lang=lang
            )

        if "error" in result:
            await query.message.reply_text(
                localize_service_error(result["error"], lang), parse_mode="HTML"
            )
            return PLAN_VIEW

        plan_items = result.get("plan", [])
        if not plan_items:
            await query.message.reply_text(safe_t("cp_ai_failed", lang))
            return PLAN_VIEW

        context.user_data["plan_items"] = plan_items
        # Yangi reja — eski "navbatga qo'yilgan" belgisi tozalanadi.
        context.user_data["plan_scheduled"] = False

        plan_text = safe_t(
            "cp_plan_header_new", lang,
            channel=html_escape(channel_title), topic=html_escape(topic),
        )

        for i, item in enumerate(plan_items):
            day = item.get("day", safe_t("cp_day_fallback", lang, n=i + 1))
            fmt = item.get("format", "")
            title = item.get("title", "")
            idea = item.get("idea", "")
            plan_text += safe_t(
                "cp_plan_day", lang, day=day,
                fmt=html_escape(fmt), title=html_escape(title),
            )
            if idea:
                plan_text += safe_t("cp_plan_idea", lang, idea=html_escape(idea[:150]))
            plan_text += "\n"

        await query.message.reply_text(
            plan_text,
            reply_markup=_plan_list_keyboard(plan_items, context, lang),
            parse_mode="HTML",
        )
        return PLAN_VIEW

    if data.startswith("plan_day:"):
        await query.answer()
        idx_str = data.split(":", 1)[1]
        try:
            idx = int(idx_str)
        except (ValueError, TypeError):
            return PLAN_VIEW

        plan_items = context.user_data.get("plan_items", [])
        if idx < 0 or idx >= len(plan_items):
            await query.message.reply_text(safe_t("cp_invalid_day", lang))
            return PLAN_VIEW

        item = plan_items[idx]
        day = item.get("day", safe_t("cp_day_fallback", lang, n=idx + 1))
        title = item.get("title", "")
        idea = item.get("idea", "")
        fmt = item.get("format", "")

        # Saqlaymiz — post yaratish oqimiga yo'naltirish uchun
        context.user_data["plan_selected_item"] = item

        detail = safe_t(
            "cp_day_detail", lang, day=html_escape(day), fmt=html_escape(fmt),
            title=html_escape(title), idea=html_escape(idea),
            ask=safe_t("cp_day_ask", lang),
        )

        confirm_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                safe_t("cp_btn_create_on_topic", lang), callback_data="plan_create_post"
            )],
            [InlineKeyboardButton(
                safe_t("cp_btn_back", lang), callback_data="plan_back_to_list"
            )],
        ])

        await query.message.reply_text(detail, reply_markup=confirm_kb, parse_mode="HTML")
        return PLAN_VIEW

    if data == "plan_create_post":
        await query.answer()
        item = context.user_data.get("plan_selected_item", {})
        if not item:
            # Agar kun tanlanmagan bo'lsa — kunlar ro'yxatini ko'rsatamiz
            plan_items = context.user_data.get("plan_items", [])
            if plan_items:
                await query.message.reply_text(
                    safe_t("cp_choose_day", lang),
                    reply_markup=_plan_list_keyboard(plan_items, context, lang),
                    parse_mode="HTML",
                )
            return PLAN_VIEW

        # Post yaratish oqimiga yo'naltirish
        topic = context.user_data.get("plan_topic", "")
        title = item.get("title", "")
        idea = item.get("idea", "")
        channel_id = context.user_data.get("plan_channel_id", "")
        channel_title = context.user_data.get("plan_channel_title", "")

        # AI dan to'liq post so'raymiz
        await query.message.reply_text(safe_t("cp_ai_writing", lang))

        from utils.ai_agent import generate_post_from_plan
        tone = await db.run_db(db.get_channel_tone, channel_id) if channel_id else "friendly"
        # Indikator darhol ko'rinsin, keyin uzoq AI so'rovi davomida yangilanib tursin.
        chat_id = query.message.chat_id
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass
        async with keep_typing(context.bot, chat_id):
            result = await generate_post_from_plan(topic, title, idea, tone, lang=lang)

        if "error" in result:
            await query.message.reply_text(
                localize_service_error(result["error"], lang), parse_mode="HTML"
            )
            return PLAN_VIEW

        post_text = result.get("post_text", "")
        if not post_text:
            await query.message.reply_text(safe_t("cp_ai_write_failed", lang))
            return PLAN_VIEW

        # Post matnini user_data ga saqlash va yangi post oqimiga o'tkazish
        context.user_data["content"] = post_text
        context.user_data["post_type"] = "text"
        context.user_data["file_id"] = None
        context.user_data["selected_channel_id"] = channel_id
        context.user_data["selected_channel_title"] = channel_title

        preview = post_text[:500]
        if len(post_text) > 500:
            preview += "…"

        await query.message.reply_text(
            safe_t(
                "cp_post_ready", lang, preview=safe_html(preview),
                channel=html_escape(channel_title),
            ),
            parse_mode="HTML",
        )

        # To'g'ridan-to'g'ri GET_BTN_TITLE ga o'tamiz (tugma bosish bosqichi)
        from keyboards.default import get_button_prompt_keyboard
        await query.message.reply_text(
            safe_t("cp_button_ask", lang),
            reply_markup=get_button_prompt_keyboard(lang),
            parse_mode="HTML",
        )
        from handlers.new_post import GET_BTN_TITLE
        return GET_BTN_TITLE

    if data == "plan_back_to_list":
        await query.answer()
        plan_items = context.user_data.get("plan_items", [])
        channel_title = context.user_data.get(
            "plan_channel_title", safe_t("an_channel_fallback", lang)
        )
        topic = context.user_data.get("plan_topic", "")

        plan_text = safe_t(
            "cp_plan_header", lang,
            channel=html_escape(channel_title), topic=html_escape(topic),
        )

        for i, item in enumerate(plan_items):
            day = item.get("day", safe_t("cp_day_fallback", lang, n=i + 1))
            fmt = item.get("format", "")
            title = item.get("title", "")
            idea = item.get("idea", "")
            plan_text += safe_t(
                "cp_plan_day", lang, day=day,
                fmt=html_escape(fmt), title=html_escape(title),
            )
            if idea:
                plan_text += safe_t("cp_plan_idea", lang, idea=html_escape(idea[:150]))
            plan_text += "\n"

        await query.message.reply_text(
            plan_text,
            reply_markup=_plan_list_keyboard(plan_items, context, lang),
            parse_mode="HTML",
        )
        return PLAN_VIEW

    return PLAN_VIEW
