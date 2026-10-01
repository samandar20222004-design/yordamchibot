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
from keyboards.inline import get_ai_back_keyboard, render_instant_plan_offer_keyboard
from locales.translations import get_lang, get_text
from utils.helpers import html_escape

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
        return get_main_keyboard(True, lang=lang, context=context)
    if await user_wants_simple_menu(user_id, context):
        return get_simple_keyboard(lang)
    return get_main_keyboard(False, lang=lang, context=context)


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
    """🖼 Rasmdan post olish — YAGONA «📸 Rasm → Post» oqimini ochadi (B2).

    PostAssist V2 · 2-qadam: bu tugma endi eski Vision oqimining nusxasini
    emas, ``handlers/image_post`` dagi yagona implementatsiyani ochadi —
    ``image_post_entry`` (Vision tahlili + Post Score + bir xil kredit/limit
    qoidalari, ``IMAGE_POST_INPUT`` holati). Shu tariqa botda bitta rasm
    oqimi qoladi; eski ``photo_`` callback'lari xavfsiz alias bo'lib yashaydi.
    """
    # Lokal import — modul sikli (onboarding ↔ image_post ↔ handlers/__init__)
    # oldini oladi.
    from handlers.image_post import image_post_entry

    # Yangi sessiya — eski studio/vision natijasi yangi rasmga aralashmasligi
    # kerak (image_post_entry o'z sessiya kalitlarini ham tozalaydi).
    for key in (
        "studio_topic", "studio_post_text", "studio_tone",
        "studio_file_id", "studio_post_type", "studio_photo_extra",
        "last_studio_media_group_id",
    ):
        context.user_data.pop(key, None)

    return await image_post_entry(update, context)


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


# ============================================================
# 3. PHASE 9 — 2 DAQIQALIK INSTANT-VALUE ONBOARDING (5 QADAM)
# ============================================================

def build_instant_onboarding_greeting(lang: str = "uz") -> str:
    """1- va 2-qadamlar: Qisqa salomlashuv + 'Telegram kanalingizni ulang' yo'riqnomasi."""
    return (
        get_text("start_onboarding", lang)
        + "\n\n"
        + get_text("onb_instant_steps", lang)
    )


async def analyze_quick_channel_dna(
    user_id: int,
    channel_id: str,
    channel_title: str = "",
    lang: str = "uz",
) -> dict:
    """3-qadam: Kanal ulangach — avtomatik tezkor Channel DNA tahlili.

    Mavjud postlar bo'lsa ``services.channels.dna.get_channel_dna`` orqali
    tahlil qilinadi; yangi/bo'sh kanal bo'lsa xavfsiz boshlang'ich DNA
    profili qaytariladi (xatolik hech qachon chiqmaydi).
    """
    style_label = {
        "uz": "Professional va foydali",
        "ru": "Профессиональный и полезный",
        "en": "Professional & helpful",
    }.get(lang, "Professional va foydali")
    length_label = {
        "uz": "O'rta (~550 belgi)",
        "ru": "Средняя (~550 симв.)",
        "en": "Medium (~550 chars)",
    }.get(lang, "O'rta (~550 belgi)")
    summary_label = {
        "uz": "Strukturali postlar, o'rtacha emoji va aniq CTA savollari tavsiya etiladi.",
        "ru": "Рекомендуются структурные посты, умеренные эмодзи и чёткие CTA-вопросы.",
        "en": "Structured posts, moderate emojis, and clear CTA questions are recommended.",
    }.get(lang, "Strukturali postlar, o'rtacha emoji va aniq CTA savollari tavsiya etiladi.")

    try:
        from services.channels.dna import get_channel_dna, label_for

        res = await get_channel_dna(str(channel_id), user_id=int(user_id))
        if isinstance(res, dict) and res.get("ok") and not res.get("insufficient"):
            profile = res.get("profile") or {}
            avg_len = int(profile.get("average_post_length") or 550)
            fmt = label_for("formatting_style", profile.get("formatting_style"), lang)
            cta = label_for("cta_style", profile.get("cta_style"), lang)
            emoji = label_for("emoji_level", profile.get("emoji_level"), lang)
            style_label = f"{fmt} · {cta}"
            length_label = f"~{avg_len}"
            summary_label = f"Emoji: {emoji} | CTA: {cta}"
    except Exception:
        logger.debug("Tezkor DNA tahlilida fallback ishlatildi (channel=%s)", channel_id, exc_info=True)

    return {
        "channel_id": str(channel_id),
        "channel_title": channel_title or str(channel_id),
        "style": style_label,
        "length": length_label,
        "summary": summary_label,
    }


async def run_instant_dna_onboarding(
    send,
    user_id: int,
    channel_id: str,
    channel_title: str = "",
    lang: str = "uz",
) -> bool:
    """3- va 4-qadamlar: Tezkor Channel DNA tahlili + Qisqa xulosa + '7 kunlik kontent reja tuzamizmi?' taklifi."""
    if send is None or not user_id or not channel_id:
        return False
    try:
        dna = await analyze_quick_channel_dna(
            user_id=user_id,
            channel_id=str(channel_id),
            channel_title=channel_title,
            lang=lang,
        )
        safe_title = html_escape(str(channel_title or channel_id))
        card_text = get_text(
            "onb_dna_summary_card",
            lang,
            channel=safe_title,
            style=html_escape(str(dna["style"])),
            length=html_escape(str(dna["length"])),
            summary=html_escape(str(dna["summary"])),
        )
        await send(
            card_text,
            parse_mode="HTML",
            reply_markup=render_instant_plan_offer_keyboard(channel_id, lang),
        )
        return True
    except Exception:
        logger.debug("run_instant_dna_onboarding ishlamadi (channel=%s)", channel_id, exc_info=True)
        return False


def _fallback_7day_items(channel_title: str, lang: str = "uz") -> list[dict]:
    """AI xizmati band bo'lganda ham 1-click natija kafolatlanishi uchun 7 kunlik fallback reja."""
    topic = channel_title or "Kanal"
    if lang == "ru":
        templates = [
            ("Знакомство и ключевая ценность канала", "09:00"),
            ("Топ-3 частых ошибок в теме «{t}»", "12:00"),
            ("Практический чек-лист на каждый день", "18:00"),
            ("Разбор реального кейса и выводы", "10:00"),
            ("Ответы на главные вопросы подписчиков", "15:00"),
            ("Полезные инструменты и ресурсы по «{t}»", "11:00"),
            ("Итоги недели и опрос аудитории", "19:00"),
        ]
    elif lang == "en":
        templates = [
            ("Welcome & core value of the channel", "09:00"),
            ("Top 3 common mistakes in {t}", "12:00"),
            ("Actionable daily checklist for subscribers", "18:00"),
            ("Real-world case study & key takeaways", "10:00"),
            ("Q&A: answering top community questions", "15:00"),
            ("Best tools & resources for {t}", "11:00"),
            ("Weekly recap & audience poll", "19:00"),
        ]
    else:
        templates = [
            ("Kanal maqsadi va obunachilar uchun asosiy qiymat", "09:00"),
            ("«{t}» bo'yicha ko'pchilik qiladigan 3 ta xato", "12:00"),
            ("Har kuni qo'llash mumkin bo'lgan amaliy chek-list", "18:00"),
            ("Real keys tahlili va muhim xulosalar", "10:00"),
            ("Obunachilarning eng ko'p beriladigan savollariga javob", "15:00"),
            ("«{t}» bo'yicha eng foydali vositalar ro'yxati", "11:00"),
            ("Hafta sarhisobi va auditoriya so'rovnomasi", "19:00"),
        ]
    items = []
    for idx, (idea_tpl, hhmm) in enumerate(templates, start=1):
        idea = idea_tpl.format(t=topic)
        items.append({
            "index": idx - 1,
            "day": idx,
            "weekday": (idx - 1) % 7,
            "date": f"Kun {idx}",
            "time": hhmm,
            "format": "post",
            "idea": idea,
            "post": f"📌 {idea}",
            "post_text": f"📌 {idea}",
        })
    return items


async def onboarding_quick_plan_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """5-qadam: Bitta tugma (`onb_plan:<channel_id>`) bilan birinchi foydali natijani (7 kunlik reja) olish."""
    from handlers.autopilot import (
        AUTOPILOT_VIEW,
        UD_CHANNEL,
        UD_DAYS,
        UD_TITLE,
        UD_TOPIC,
        autopilot_confirm_keyboard,
        render_plan_text,
    )
    from handlers.channels import _owned_channel
    from services.autopilot import create_autopilot_plan

    query = getattr(update, "callback_query", None)
    if query is None:
        return ConversationHandler.END
    try:
        await query.answer()
    except Exception:
        pass

    user = getattr(update, "effective_user", None) or getattr(query, "from_user", None)
    user_id = user.id if user else 0
    lang = await _user_lang(context, user_id)
    data = str(getattr(query, "data", "") or "")
    channel_id = data.split(":", 1)[1] if ":" in data else ""

    channel = await _owned_channel(user_id, channel_id)
    if channel is None:
        msg = getattr(query, "message", None)
        if msg is not None:
            from translations import channels_queue_t
            await msg.reply_text(channels_queue_t("cq_ch_not_found", lang), parse_mode="HTML")
        return ConversationHandler.END

    ch_title = str(channel[1] or channel_id) if len(channel) > 1 else str(channel_id)
    ch_topic = (
        str(channel[3]).strip()
        if len(channel) > 3 and channel[3]
        else ch_title
    )

    res = None
    try:
        res = await create_autopilot_plan(
            user_id=user_id,
            channel_id=str(channel_id),
            topic=ch_topic,
            lang=lang,
        )
    except Exception:
        logger.debug("create_autopilot_plan fallback ishlatildi (channel=%s)", channel_id, exc_info=True)

    days = (res or {}).get("days") if isinstance(res, dict) and res.get("ok") else None
    if not days:
        days = _fallback_7day_items(ch_title, lang=lang)

    context.user_data[UD_CHANNEL] = str(channel_id)
    context.user_data[UD_TITLE] = ch_title
    context.user_data[UD_TOPIC] = ch_topic
    context.user_data[UD_DAYS] = days

    chunks = render_plan_text(
        days=days,
        topic=ch_topic,
        channel_title=ch_title,
        hour_source="default",
        best_window=None,
        hour=9,
        lang=lang,
    )
    plan_card = "\n\n".join(chunks)
    full_text = get_text(
        "onb_plan_ready_header",
        lang,
        channel=html_escape(ch_title),
        plan=plan_card,
    )

    msg = getattr(query, "message", None)
    if msg is not None:
        await msg.reply_text(
            full_text,
            parse_mode="HTML",
            reply_markup=autopilot_confirm_keyboard(lang),
        )
    return AUTOPILOT_VIEW

