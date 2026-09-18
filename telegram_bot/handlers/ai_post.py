"""🧭 AI POST — MAVZUNI ANIQLASHTIRISH WIZARD'I (3-qadam UI/UX polish).

Muammo: foydalanuvchi ``"yangiliklar"`` yoki ``"sport"`` deb 1 ta so'z
yozganda bot nima haqidaligini so'ramay, darhol quruq va umumiy gaplar
to'qirdi — ba'zida esa mavzuni xato ravishda "🛒 Sotuv" deb qabul qilib,
kanal a'zoligi haqida reklama yozardi.

Yechim — 3 bosqichli aniqlashtirish (kvota/kredit SARFLANMASDAN):

1. Qisqa (< 3 so'z) yoki umumiy mavzu → ``AI_POST_CLARIFY``: foydalanuvchiga
   yo'nalish tanlovi beriladi (``📌 Qaysi yo'nalish bo'yicha post
   tayyorlaymiz?``) — 5 ta inline tugma: 📰/💡/🔥/🛒/✍️.
2. ``🛒 Mahsulot / Sotuv`` tanlansa YOKI mavzuda sotuv kalit so'zi
   (``sotiladi``/``narxi``/``aksiya`` ...) bo'lib, aniq tafsilot bo'lmasa →
   ``AI_POST_SALES_INPUT``: mahsulot nomi/narxi/xususiyati so'raladi.
3. ``✍️ O'zim aniq yozaman`` → ``AI_POST_CUSTOM_INPUT``: aniq mavzu matni
   olinadi va oqim davom etadi.

Format ajratish (``services.ai.prompts`` — yagona manba):

* ``yangilik``/``xabar``/``sport``/``voqea`` → 📰 Axborot formati, HECH
  QACHON 🛒 Sotuv (INFO ustuvorligi qat'iy);
* sotuv so'zlari → 🛒 Sotuv (faqat axborot so'zi bo'lmaganda).

Integratsiya (mavjud oqimlar BUZILMAYDI):

* ✨ Magic Post — ``magic_text_received`` matnni uslublar menyusiga
  chiqarishdan OLDIN ``maybe_start_clarification()`` ni chaqiradi;
  aniq/batafsil mavzular eski yo'ldan (STYLE_SELECT) yurishda davom etadi;
* 🤖 AI Studio — ``ai_prompt_received`` kvota BRON QILINISHDAN OLDIN shu
  funksiyani chaqiradi; aniqlashtirishdan keyingi matn
  ``_studio_generate_and_preview()`` orqali standart generatsiyaga uzatiladi.

Qoidalar (repo konventsiyalari):

* har bir callback handler BOSHIDA ``await query.answer()``;
* barcha matnlar 3 til (uz/ru/en) — modul ichidagi lug'atlar (paritet
  ``tests/ai_clarification_and_intent_test.py`` bilan qo'riqlanadi);
* FSM holatlari noyob (434/435/436) — boshqa oqimlar bilan to'qnashmaydi;
* xatolikda foydalanuvchi hech qachon band holatda qolmaydi.
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from keyboards.callback_data import cb
from locales.translations import get_lang
from services.ai.prompts import (
    FORMAT_NEWS,
    FORMAT_SALES,
    FORMAT_SHORT,
    FORMAT_TIPS,
    detect_post_format,
    format_hint_line,
    map_format_to_magic_style,
    needs_clarification,
    should_ask_sales_params,
)

logger = logging.getLogger(__name__)

# ============================================================
# FSM HOLATLARI (noyob — 434/435/436 boshqa oqimlarda band emas)
# ============================================================
AI_POST_CLARIFY = 434      # yo'nalish tanlovi kutilmoqda (📰/💡/🔥/🛒/✍️)
AI_POST_SALES_INPUT = 435  # sotuv parametrlari (nom/narx/xususiyat) kutilmoqda
AI_POST_CUSTOM_INPUT = 436  # foydalanuvchi aniq mavzu yozishi kutilmoqda

# Callback data (``^aip_`` — global stale-handler bilan qo'riqlanadi).
AIP_FMT_PREFIX = "aip_fmt:"
AIP_FMT_CUSTOM = "custom"
AIP_BACK = "aip_back"
AIP_CANCEL = "aip_cancel"

#: Wizard qayerdan ochilgani (qaytish manzili).
AI_POST_ORIGIN_MAGIC = "magic"
AI_POST_ORIGIN_STUDIO = "studio"

#: user_data kalitlari (boshqa oqimlarnikiga o'xshamaydi — ``aip_`` prefiks).
AIP_TOPIC_KEY = "aip_topic"
AIP_ORIGIN_KEY = "aip_origin"
AIP_FORMAT_KEY = "aip_format"
AIP_HINT_KEY = "aip_format_hint"

#: Mavzu aks-sadosi chegarasi (belgi).
_AIP_TOPIC_ECHO_LIMIT = 120


# ============================================================
# MATNLAR (3 til — modul ichida, paritet test bilan qo'riqlanadi)
# ============================================================
_AIP_TEXTS: dict[str, dict[str, str]] = {
    "clarify_question": {
        "uz": "📌 Qaysi yo'nalish bo'yicha post tayyorlaymiz?",
        "ru": "📌 О чём готовим пост?",
        "en": "📌 What should the post be about?",
    },
    "topic_label": {
        "uz": "Mavzu",
        "ru": "Тема",
        "en": "Topic",
    },
    "fmt_news": {
        "uz": "📰 Yangiliklar / Voqea",
        "ru": "📰 Новости / Событие",
        "en": "📰 News / Event",
    },
    "fmt_tips": {
        "uz": "💡 Maslahat / Tahlil",
        "ru": "💡 Совет / Анализ",
        "en": "💡 Tips / Analysis",
    },
    "fmt_short": {
        "uz": "🔥 Qisqa / Faktlar",
        "ru": "🔥 Коротко / Факты",
        "en": "🔥 Short / Facts",
    },
    "fmt_sales": {
        "uz": "🛒 Mahsulot / Sotuv",
        "ru": "🛒 Товар / Продажи",
        "en": "🛒 Product / Sales",
    },
    "fmt_custom": {
        "uz": "✍️ O'zim aniq yozaman",
        "ru": "✍️ Напишу тему сам",
        "en": "✍️ I'll write it myself",
    },
    "sales_params": {
        "uz": (
            "Nimani sotyapmiz? Iltimos, mahsulot nomi, narxi va asosiy "
            "xususiyatini yozing (Masalan: Erkaklar krossovkasi, 250 000 "
            "so'm, yetkazib berish bepul)."
        ),
        "ru": (
            "Что продаём? Напишите название товара, цену и главную "
            "особенность (Например: Мужские кроссовки, 250 000 сум, "
            "доставка бесплатно)."
        ),
        "en": (
            "What are we selling? Please write the product name, price and "
            "key feature (E.g.: Men's sneakers, 250,000 UZS, free delivery)."
        ),
    },
    "custom_prompt": {
        "uz": (
            "✍️ Aniq mavzuni yozing — nima haqida post kerakligini 1-2 "
            "jumlada tushuntiring."
        ),
        "ru": (
            "✍️ Напишите точную тему — в 1-2 предложениях объясните, "
            "о чём нужен пост."
        ),
        "en": (
            "✍️ Write the exact topic — explain in 1-2 sentences what "
            "the post should be about."
        ),
    },
    "input_hint": {
        "uz": "Iltimos, javobingizni matn ko'rinishida yozing.",
        "ru": "Пожалуйста, напишите ответ текстом.",
        "en": "Please type your answer as text.",
    },
    "stale": {
        "uz": "⚠️ Sessiya eskirgan — mavzuni qayta yuboring.",
        "ru": "⚠️ Сессия устарела — отправьте тему заново.",
        "en": "⚠️ Session expired — please send the topic again.",
    },
    "cancel_button": {
        "uz": "❌ Bekor qilish",
        "ru": "❌ Отмена",
        "en": "❌ Cancel",
    },
    "cancel_done": {
        "uz": "❌ <b>Bekor qilindi.</b>\n\nKerak bo'lsa mavzuni qayta yuboring — wizard qaytadan boshlanadi.",
        "ru": "❌ <b>Отменено.</b>\n\nПри необходимости отправьте тему заново — мастер начнётся с начала.",
        "en": "❌ <b>Cancelled.</b>\n\nSend the topic again anytime — the wizard will restart.",
    },
}


def aip_t(key: str, lang: str = "uz") -> str:
    """Wizard matni (noma'lum kalit/til → uz, hech qachon yiqilmaydi)."""
    table = _AIP_TEXTS.get(str(key or "")) or {}
    code = str(lang or "uz").strip().lower().split("-")[0]
    if code not in ("uz", "ru", "en"):
        code = "uz"
    return table.get(code) or table.get("uz") or ""


def clarification_text(lang: str = "uz") -> str:
    """``📌 Qaysi yo'nalish ...`` savoli (spetsifikatsiya matni)."""
    return aip_t("clarify_question", lang)


def sales_params_text(lang: str = "uz") -> str:
    """Sotuv parametrlari so'rovi (spetsifikatsiya matni)."""
    return aip_t("sales_params", lang)


def _topic_echo(topic: str, lang: str = "uz") -> str:
    """Mavzu aks-sadosi (HTML-escape qilingan, qisqartirilgan)."""
    try:
        from utils.helpers import html_escape
    except ImportError:  # pragma: no cover - himoya
        from telegram_bot.utils.helpers import html_escape
    clean = " ".join(str(topic or "").split())
    if len(clean) > _AIP_TOPIC_ECHO_LIMIT:
        clean = clean[:_AIP_TOPIC_ECHO_LIMIT] + "…"
    label = aip_t("topic_label", lang)
    return f"{label}: <i>{html_escape(clean)}</i>"


# ============================================================
# KLAVIATURA
# ============================================================
def build_clarification_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Yo'nalish tanlovi: [📰|💡] [🔥|🛒] [✍️] + [❌ Bekor qilish] (2+2+1+1).

    DEEP AUDIT tuzatishi (dead-end trap): ilgari wizard'da HECH QANDAY
    chiqish tugmasi yo'q edi (``aip_back`` callback'i ro'yxatda bor, lekin
    unga bog'langan tugma YO'Q edi). Endi ``aip_cancel`` tugmasi wizard'ni
    to'liq yopadi — foydalanuvchi band holatda qolmaydi. Kvota/kredit
    tegilmaydi (wizard bron QILMAYDI).
    """
    news = InlineKeyboardButton(
        aip_t("fmt_news", lang), callback_data=cb(AIP_FMT_PREFIX, FORMAT_NEWS))
    tips = InlineKeyboardButton(
        aip_t("fmt_tips", lang), callback_data=cb(AIP_FMT_PREFIX, FORMAT_TIPS))
    short = InlineKeyboardButton(
        aip_t("fmt_short", lang), callback_data=cb(AIP_FMT_PREFIX, FORMAT_SHORT))
    sales = InlineKeyboardButton(
        aip_t("fmt_sales", lang), callback_data=cb(AIP_FMT_PREFIX, FORMAT_SALES))
    custom = InlineKeyboardButton(
        aip_t("fmt_custom", lang), callback_data=cb(AIP_FMT_PREFIX, AIP_FMT_CUSTOM))
    cancel = InlineKeyboardButton(aip_t("cancel_button", lang), callback_data=AIP_CANCEL)
    return InlineKeyboardMarkup([[news, tips], [short, sales], [custom], [cancel]])


def clarification_keyboard_buttons(lang: str = "uz") -> list[tuple[str, str]]:
    """Testlar uchun: ``[(label, callback_data), ...]`` ro'yxati."""
    markup = build_clarification_keyboard(lang)
    return [(btn.text, btn.callback_data)
            for row in markup.inline_keyboard for btn in row]


# ============================================================
# KIRISH FILTRI — Magic Post / AI Studio shu funksiyani chaqiradi
# ============================================================
async def maybe_start_clarification(msg, context, text, lang: str = "uz",
                                    origin: str = AI_POST_ORIGIN_MAGIC):
    """Qisqa/umumiy mavzuda wizard'ni boshlaydi, aks holda ``None``.

    * sotuv kalit so'zi + tafsilot yo'q → sotuv parametrlari so'rovi
      (``AI_POST_SALES_INPUT``);
    * qisqa/umumiy mavzu → yo'nalish tanlovi (``AI_POST_CLARIFY``);
    * aniq/batafsil mavzu → ``None`` (chaqiruvchi eski yo'ldan yuradi).

    Kvota/kreditga TEGILMAYDI — chaqiruvchilar buni bron oldidan chaqiradi.
    """
    topic = str(text or "").strip()
    if not topic:
        return None
    origin = origin if origin in (AI_POST_ORIGIN_MAGIC, AI_POST_ORIGIN_STUDIO) \
        else AI_POST_ORIGIN_MAGIC

    if should_ask_sales_params(topic):
        context.user_data[AIP_TOPIC_KEY] = topic
        context.user_data[AIP_ORIGIN_KEY] = origin
        context.user_data[AIP_FORMAT_KEY] = FORMAT_SALES
        context.user_data.pop(AIP_HINT_KEY, None)
        await msg.reply_text(
            f"🛒 {_topic_echo(topic, lang)}\n\n{sales_params_text(lang)}",
            parse_mode="HTML",
        )
        logger.info("AI Post wizard: sotuv parametrlari so'raldi (origin=%s)", origin)
        return AI_POST_SALES_INPUT

    if needs_clarification(topic):
        context.user_data[AIP_TOPIC_KEY] = topic
        context.user_data[AIP_ORIGIN_KEY] = origin
        context.user_data.pop(AIP_FORMAT_KEY, None)
        context.user_data.pop(AIP_HINT_KEY, None)
        await msg.reply_text(
            f"{clarification_text(lang)}\n{_topic_echo(topic, lang)}",
            reply_markup=build_clarification_keyboard(lang),
            parse_mode="HTML",
        )
        logger.info("AI Post wizard: yo'nalish tanlovi ko'rsatildi (origin=%s)", origin)
        return AI_POST_CLARIFY

    return None


# ============================================================
# YORDAMCHILAR — kelib chiqish oqimiga qaytish
# ============================================================
def _origin_input_state(origin: str) -> int:
    """Wizard manbasining matn kiritish holati (stale uchun)."""
    if origin == AI_POST_ORIGIN_STUDIO:
        try:
            from handlers.ai_assistant import AI_PROMPT_INPUT
        except ImportError:
            from telegram_bot.handlers.ai_assistant import AI_PROMPT_INPUT
        return AI_PROMPT_INPUT
    try:
        from handlers.magic_post import MAGIC_INPUT
    except ImportError:
        from telegram_bot.handlers.magic_post import MAGIC_INPUT
    return MAGIC_INPUT


async def _resume_magic_style_menu(update: Update, context, topic: str, lang: str):
    """Magic Post uslublar menyusini chizadi (matn saqlanib qoladi)."""
    try:
        from handlers.magic_post import (
            MAGIC_STYLE_SELECT,
            _magic_style_keyboard,
            _magic_style_menu_text,
        )
    except ImportError:
        from telegram_bot.handlers.magic_post import (
            MAGIC_STYLE_SELECT,
            _magic_style_keyboard,
            _magic_style_menu_text,
        )
    context.user_data["magic_raw_text"] = topic
    text = _magic_style_menu_text(topic, lang)
    markup = _magic_style_keyboard(lang)
    query = update.callback_query if update is not None else None
    if query is not None:
        try:
            from utils.telegram_sanitizer import sanitize_html
        except ImportError:
            from telegram_bot.utils.telegram_sanitizer import sanitize_html
        try:
            await query.edit_message_text(
                sanitize_html(text), reply_markup=markup, parse_mode="HTML")
        except Exception:
            try:
                await query.message.reply_text(
                    sanitize_html(text), reply_markup=markup, parse_mode="HTML")
            except Exception:
                pass
    elif update is not None and update.message is not None:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
    return MAGIC_STYLE_SELECT


async def _resume_studio_generation(update: Update, context, topic: str, lang: str):
    """AI Studio generatsiyasini boyitilgan mavzu bilan ishga tushiradi."""
    try:
        from handlers.ai_assistant import _studio_generate_and_preview
    except ImportError:
        from telegram_bot.handlers.ai_assistant import _studio_generate_and_preview
    query = update.callback_query if update is not None else None
    if query is not None:
        # Wizard xabaridagi klaviaturani yopamiz (ikki marta bosilmaydi).
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        msg = query.message
    else:
        msg = update.message if update is not None else None
    return await _studio_generate_and_preview(update, context, msg, topic, lang)


async def _resume_origin(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         topic: str, lang: str, origin: str):
    """Boyitilgan mavzu bilan kelib chiqish oqimiga qaytadi."""
    if origin == AI_POST_ORIGIN_STUDIO:
        return await _resume_studio_generation(update, context, topic, lang)
    return await _resume_magic_style_menu(update, context, topic, lang)


def _enriched_topic(topic: str, context) -> str:
    """Format ko'rsatmasi qo'shilgan generatsiya materiali (hint iste'mol qilinadi)."""
    hint = str(context.user_data.pop(AIP_HINT_KEY, "") or "").strip()
    clean = str(topic or "").strip()
    if hint and hint not in clean:
        return f"{clean}\n\n{hint}"
    return clean


def _resume_topic_for_origin(topic: str, context, origin: str) -> str:
    """Kelib chiqish oqimiga uzatiladigan mavzu.

    * studio → boyitilgan matn (format ko'rsatmasi bilan — generatsiya
      bevosita boshlanadi);
    * magic → toza matn (uslublar menyusi prevyusi toza ko'rinadi; hint
      ``magic_style_callback`` da generatsiya materialiga ulanadi).
    """
    if origin == AI_POST_ORIGIN_STUDIO:
        return _enriched_topic(topic, context)
    return str(topic or "").strip()


def _check_interrupt_triggers(text: str):
    """Bekor/menyu triggerlari (magic oqimi bilan bir xil kontrakt)."""
    try:
        from middlewares.fsm_cleaner import (
            clear_user_fsm,
            is_cancel_trigger,
            is_start_or_menu_trigger,
        )
    except ImportError:
        from telegram_bot.middlewares.fsm_cleaner import (
            clear_user_fsm,
            is_cancel_trigger,
            is_start_or_menu_trigger,
        )
    return clear_user_fsm, is_cancel_trigger, is_start_or_menu_trigger


# ============================================================
# CALLBACK: yo'nalish tanlandi (``aip_fmt:*``)
# ============================================================
async def ai_post_format_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``AI_POST_CLARIFY``: 📰/💡/🔥/🛒/✍️ tugmasi bosildi."""
    query = update.callback_query
    await query.answer()  # SPEKS: darhol answer — tugma "yopishib" qolmaydi
    lang = get_lang(context)

    data = str(query.data or "")
    fmt = data.split(":", 1)[-1].strip().lower() if ":" in data else ""
    origin = context.user_data.get(AIP_ORIGIN_KEY) or AI_POST_ORIGIN_MAGIC
    topic = str(context.user_data.get(AIP_TOPIC_KEY) or "").strip()

    if not topic:
        try:
            await query.answer(aip_t("stale", lang), show_alert=True)
        except Exception:
            pass
        return _origin_input_state(origin)

    if fmt == AIP_FMT_CUSTOM:
        context.user_data[AIP_FORMAT_KEY] = AIP_FMT_CUSTOM
        context.user_data.pop(AIP_HINT_KEY, None)
        try:
            await query.edit_message_text(
                f"{_topic_echo(topic, lang)}\n\n{aip_t('custom_prompt', lang)}",
                parse_mode="HTML",
            )
        except Exception:
            try:
                await query.message.reply_text(
                    aip_t("custom_prompt", lang), parse_mode="HTML")
            except Exception:
                pass
        return AI_POST_CUSTOM_INPUT

    if fmt == FORMAT_SALES:
        context.user_data[AIP_FORMAT_KEY] = FORMAT_SALES
        context.user_data.pop(AIP_HINT_KEY, None)
        try:
            await query.edit_message_text(
                f"🛒 {_topic_echo(topic, lang)}\n\n{sales_params_text(lang)}",
                parse_mode="HTML",
            )
        except Exception:
            try:
                await query.message.reply_text(
                    sales_params_text(lang), parse_mode="HTML")
            except Exception:
                pass
        return AI_POST_SALES_INPUT

    if fmt in (FORMAT_NEWS, FORMAT_TIPS, FORMAT_SHORT):
        context.user_data[AIP_FORMAT_KEY] = fmt
        # Xavfsizlik: axborot formatlari sotuv uslubiga tushmaydi.
        suggested = map_format_to_magic_style(fmt)
        if fmt in (FORMAT_NEWS, FORMAT_TIPS, FORMAT_SHORT) and suggested in (
                "sales", "ads"):
            suggested = "informative"  # pragma: no cover - himoya
        context.user_data[AIP_HINT_KEY] = format_hint_line(fmt, lang)
        logger.info("AI Post wizard: format=%s (magic taklif=%s, origin=%s)",
                    fmt, suggested, origin)
        resume_topic = _resume_topic_for_origin(topic, context, origin)
        return await _resume_origin(update, context, resume_topic, lang, origin)

    # Noma'lum callback — wizard ochiq qoladi.
    try:
        await query.answer(aip_t("stale", lang), show_alert=True)
    except Exception:
        pass
    return AI_POST_CLARIFY


async def ai_post_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``aip_back``: wizard'dan kelib chiqish oqimining boshiga qaytish."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    origin = context.user_data.get(AIP_ORIGIN_KEY) or AI_POST_ORIGIN_MAGIC
    for key in (AIP_TOPIC_KEY, AIP_FORMAT_KEY, AIP_HINT_KEY):
        context.user_data.pop(key, None)
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    try:
        await query.message.reply_text(aip_t("input_hint", lang))
    except Exception:
        pass
    return _origin_input_state(origin)


async def ai_post_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``aip_cancel``: [❌ Bekor qilish] — wizard TO'LIQ yopiladi.

    DEEP AUDIT tuzatishi: aniqlashtirish wizard'i ``❌`` tugmasiz "tuzoq"
    edi. Endi barcha wizard kalitlari tozalanadi, FSM yopiladi va
    foydalanuvchi erkin holatga qaytadi (``ConversationHandler.END``).
    Kvota/kredit tegilmaydi — wizard bron QILMAYDI.
    """
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    for key in (AIP_TOPIC_KEY, AIP_ORIGIN_KEY, AIP_FORMAT_KEY, AIP_HINT_KEY):
        context.user_data.pop(key, None)
    try:
        from middlewares.fsm_cleaner import clear_user_fsm
    except ImportError:
        from telegram_bot.middlewares.fsm_cleaner import clear_user_fsm
    clear_user_fsm(context)
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    try:
        await query.message.reply_text(aip_t("cancel_done", lang), parse_mode="HTML")
    except Exception:
        pass
    return ConversationHandler.END


# ============================================================
# MATN: sotuv parametrlari / aniq mavzu qabul qilindi
# ============================================================
async def ai_post_sales_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``AI_POST_SALES_INPUT``: mahsulot nomi/narxi/xususiyati keldi."""
    msg = update.message
    if msg is None:
        return AI_POST_SALES_INPUT
    lang = get_lang(context)

    text = (msg.text or "").strip()
    if text:
        clear_user_fsm, is_cancel_trigger, is_start_or_menu_trigger = \
            _check_interrupt_triggers(text)
        if is_cancel_trigger(text):
            clear_user_fsm(context)
            try:
                from handlers.start import cancel_handler
            except ImportError:
                from telegram_bot.handlers.start import cancel_handler
            return await cancel_handler(update, context)
        if is_start_or_menu_trigger(text):
            clear_user_fsm(context)
            try:
                from handlers.start import start
            except ImportError:
                from telegram_bot.handlers.start import start
            return await start(update, context)

    if not text or len(text) < 2:
        await msg.reply_text(aip_t("input_hint", lang))
        return AI_POST_SALES_INPUT

    origin = context.user_data.get(AIP_ORIGIN_KEY) or AI_POST_ORIGIN_MAGIC
    topic = str(context.user_data.get(AIP_TOPIC_KEY) or "").strip()
    combined = f"{topic}: {text}" if topic else text
    context.user_data[AIP_FORMAT_KEY] = FORMAT_SALES
    context.user_data[AIP_HINT_KEY] = format_hint_line(FORMAT_SALES, lang)
    logger.info("AI Post wizard: sotuv parametrlari qabul qilindi (origin=%s)", origin)
    resume_topic = _resume_topic_for_origin(combined, context, origin)
    return await _resume_origin(update, context, resume_topic, lang, origin)


async def ai_post_custom_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``AI_POST_CUSTOM_INPUT``: foydalanuvchi aniq mavzuni yozdi."""
    msg = update.message
    if msg is None:
        return AI_POST_CUSTOM_INPUT
    lang = get_lang(context)

    text = (msg.text or "").strip()
    if text:
        clear_user_fsm, is_cancel_trigger, is_start_or_menu_trigger = \
            _check_interrupt_triggers(text)
        if is_cancel_trigger(text):
            clear_user_fsm(context)
            try:
                from handlers.start import cancel_handler
            except ImportError:
                from telegram_bot.handlers.start import cancel_handler
            return await cancel_handler(update, context)
        if is_start_or_menu_trigger(text):
            clear_user_fsm(context)
            try:
                from handlers.start import start
            except ImportError:
                from telegram_bot.handlers.start import start
            return await start(update, context)

    if not text or len(text) < 2:
        await msg.reply_text(aip_t("input_hint", lang))
        return AI_POST_CUSTOM_INPUT

    origin = context.user_data.get(AIP_ORIGIN_KEY) or AI_POST_ORIGIN_MAGIC
    # Aniq yozilgan matn — yangi mavzu (takroriy wizard YO'Q: foydalanuvchi
    # tanlovi hurmat qilinadi, cheksiz sikl bo'lmaydi).
    context.user_data[AIP_TOPIC_KEY] = text
    detected = detect_post_format(text)
    if detected == FORMAT_SALES and should_ask_sales_params(text):
        # Sotuv, lekin tafsilotsiz → parametrlar so'raladi (bitta qo'shimcha qadam).
        context.user_data[AIP_FORMAT_KEY] = FORMAT_SALES
        context.user_data.pop(AIP_HINT_KEY, None)
        await msg.reply_text(
            f"🛒 {_topic_echo(text, lang)}\n\n{sales_params_text(lang)}",
            parse_mode="HTML",
        )
        return AI_POST_SALES_INPUT

    if detected in (FORMAT_NEWS, FORMAT_TIPS, FORMAT_SHORT):
        context.user_data[AIP_FORMAT_KEY] = detected
        context.user_data[AIP_HINT_KEY] = format_hint_line(detected, lang)
    else:
        context.user_data.pop(AIP_FORMAT_KEY, None)
        context.user_data.pop(AIP_HINT_KEY, None)
    logger.info("AI Post wizard: aniq mavzu qabul qilindi (origin=%s)", origin)
    resume_topic = _resume_topic_for_origin(text, context, origin)
    return await _resume_origin(update, context, resume_topic, lang, origin)


# ============================================================
# STALE (sessiyadan tashqarida bosilgan eski ``aip_`` tugmalar)
# ============================================================
async def ai_post_stale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``^aip_`` tugmalari sessiya tugagach bosilsa — jim toast ko'rsatadi."""
    query = update.callback_query
    try:
        lang = get_lang(context)
        await query.answer(aip_t("stale", lang), show_alert=True)
    except Exception:
        try:
            await query.answer()
        except Exception:
            pass


__all__ = [
    "AI_POST_CLARIFY",
    "AI_POST_SALES_INPUT",
    "AI_POST_CUSTOM_INPUT",
    "AIP_FMT_PREFIX",
    "AIP_FMT_CUSTOM",
    "AIP_BACK",
    "AI_POST_ORIGIN_MAGIC",
    "AI_POST_ORIGIN_STUDIO",
    "AIP_TOPIC_KEY",
    "AIP_ORIGIN_KEY",
    "AIP_FORMAT_KEY",
    "AIP_HINT_KEY",
    "aip_t",
    "clarification_text",
    "sales_params_text",
    "build_clarification_keyboard",
    "clarification_keyboard_buttons",
    "maybe_start_clarification",
    "ai_post_format_callback",
    "ai_post_back_callback",
    "ai_post_cancel_callback",
    "AIP_CANCEL",
    "ai_post_sales_input_received",
    "ai_post_custom_input_received",
    "ai_post_stale_callback",
]
