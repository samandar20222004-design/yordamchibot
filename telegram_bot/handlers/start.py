import logging
import time
from telegram import Update, InlineKeyboardMarkup
from telegram.error import TelegramError, Forbidden
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET, SUPPORT_USERNAME
import database as db
from handlers.onboarding import (
    main_menu_intro_suffix, resolve_main_keyboard, user_wants_simple_menu,
)
from keyboards.default import (
    get_main_keyboard, get_cabinet_keyboard, get_cancel_keyboard, get_simple_keyboard,
    get_refreshed_main_keyboard,
)
from keyboards.inline import (
    get_referral_share_keyboard, get_subscription_check_keyboard,
    get_cabinet_inline_keyboard, get_cabinet_back_keyboard,
    get_extras_inline_keyboard, get_language_keyboard,
    get_channels_manage_keyboard, render_channels_list, no_channels_hint,
    get_help_keyboard, get_help_back_keyboard,
    get_settings_back_keyboard, get_settings_hub_keyboard,
    unpack_sponsor,
)
from locales.translations import (
    get_text, safe_t, detect_language, get_lang, set_lang_cache, clear_fsm_data,
    localize_db_message, normalize_lang, LANG_KEY,
)
from utils.helpers import html_escape, get_smart_reply_ad_async

logger = logging.getLogger(__name__)


async def send_language_reply_keyboard(message, context, user_id: int, is_admin: bool,
                                       lang: str) -> None:
    """Til o'zgarganda pastki doimiy ReplyKeyboard'ni DARHOL yangi tilda yuboradi.

    Nima uchun alohida xabar? Telegram ``ReplyKeyboardMarkup`` faqat YANGI
    xabar bilan yuboriladi (eski xabarning klaviaturasini alohida
    o'zgartirib bo'lmaydi). Shuning uchun til tugmasi bosilishi bilan:

      1. inline menyu shu xabarning o'zida yangi tilda qayta chiziladi;
      2. shu yerdan keyin yangi tildagi reply-klaviatura yuboriladi —
         foydalanuvchi pastki menyuni bir zumda yangi tilda ko'radi
         (UZ: "➕ Yangi post", RU: "➕ Новый пост", EN: "➕ New post").

    Yangi foydalanuvchi (onboarding) uchun sodda 3 tugmali klaviatura
    qaytariladi (``resolve_main_keyboard`` qarorini o'zi beradi).
    """
    try:
        kb = await resolve_main_keyboard(user_id, is_admin, lang, context)
    except Exception as exc:  # pragma: no cover - himoya
        logger.warning("Til klaviaturasini tayyorlashda xato: %s", exc)
        kb = get_refreshed_main_keyboard(lang, is_admin=is_admin)
    await message.reply_text(
        safe_t("lang_changed", lang),
        reply_markup=kb,
        parse_mode="HTML",
    )


async def switch_user_language(context, user_id: int, lang: str) -> str:
    """Foydalanuvchi tilini bazada va keshda yangilaydi (uz/ru/en).

    Qaytargan qiymat — normallashtirilgan til kodi ('uz' | 'ru' | 'en').
    """
    code = normalize_lang(lang)
    await db.run_db(db.set_user_language, user_id, code)
    set_lang_cache(context, code)
    return code


async def ensure_user_lang(context, user_id: int) -> str:
    """Reply-tugma/inline orqali kelgan so'rovda foydalanuvchi tilini bazadan
    keshga yuklab oladi (``context.user_data['lang']``).

    Nima uchun kerak: bot qayta ishga tushganda PTBning ``user_data`` keshi
    bo'shab qoladi. Agar foydalanuvchi shu payt rus tilidagi reply-tugmani
    bossa, ``get_lang(context)`` hali hech narsa bilmaydi va default ``uz``
    qaytaradi — natijada RU foydalanuvchi kabinetini oʻzbekcha koʻradi (yoki
    notoʻgʻri tildagi kalitlar bilan ishlashga urinadi). Bu funksiya tilni
    Neon bazadan oʻqib, keshga yozadi va har doim toʻgʻri ``'uz'/'ru'``
    qiymatini qaytaradi.

    Returns: 'uz' | 'ru' (keshga ham yoziladi).
    """
    ud = getattr(context, "user_data", None)
    if ud is not None and ud.get(LANG_KEY):
        return normalize_lang(ud[LANG_KEY])
    if not user_id:
        # Update'da foydalanuvchi bo'lmasa (odatda test-fake'lar) — DB so'rovsiz
        # keshdagi/default til qaytadi.
        return set_lang_cache(context, get_lang(context))
    try:
        lang = await db.run_db(db.get_user_language, int(user_id))
    except Exception:
        logger.exception("Foydalanuvchi tilini olishda xato (user=%s)", user_id)
        lang = None
    return set_lang_cache(context, lang or "uz")

# Eslatma: 501-502 ANALYTICS bilan to'qnashgan edi — endi 511-512 unikal.
TRANSFER_TARGET = 511
TRANSFER_AMOUNT = 512

# Obuna holati keshi: (channel_id, user_id) -> (vaqt, a'zo_mi)
# Har /start da Telegram API'ga qayta-qayta so'rov yubormaslik uchun
# natija 60 soniya eslab qolinadi (ortiqcha yuklama kamayadi).
_membership_cache = {}
MEMBERSHIP_CACHE_TTL = 60
MEMBERSHIP_CACHE_MAX = 20000

async def check_user_subscribed(bot, user_id: int) -> tuple[bool, list | None]:
    """Homiy obunasini tekshiradi (fail-closed).

    Qaytadi:
      (True, [])            — ruxsat (admin yoki homiy yo'q yoki hammaga obuna)
      (False, [sponsors])   — obuna yo'q, ro'yxatni ko'rsatish
      (False, None)         — tizim xatosi (bazaga ulanib bo'lmadi) — o'tkazib yuborilmaydi
    """
    if user_id in ADMIN_IDS_SET:
        return True, []
    sponsors = await db.run_db(db.get_sponsor_channels)
    if sponsors is None:
        return False, None
    if not sponsors:
        return True, []

    unsubscribed = []
    now = time.time()
    for s in sponsors:
        s_id, ch_id, ch_title, username, ch_url = unpack_sponsor(s)
        cache_key = (str(ch_id), user_id)
        cached = _membership_cache.get(cache_key)
        if cached and now - cached[0] < MEMBERSHIP_CACHE_TTL:
            if not cached[1]:
                unsubscribed.append(s)
            continue
        try:
            target_chat = int(ch_id) if str(ch_id).lstrip('-').isdigit() else ch_id
            member = await bot.get_chat_member(chat_id=target_chat, user_id=user_id)
            is_member = member.status in ("creator", "administrator", "member", "restricted")
        except Forbidden:
            # Bot homiy kanalga kira olmaydi (noto'g'ri sozlama) — bu sponsorni o'tkazib yuboramiz,
            # aks holda butun bot yopilib qoladi. Foydalanuvchi tekshiruvi emas.
            logger.error("Bot homiy kanalga kira olmaydi, o'tkazib yuborildi: %s", ch_id)
            is_member = True
        except TelegramError as e:
            err = str(e).lower()
            if "chat not found" in err or "bot was kicked" in err:
                logger.error("Homiy kanal noto'g'ri sozlangan (%s): %s", ch_id, e)
                is_member = True
            else:
                # Foydalanuvchi holatini aniqlab bo'lmasa — fail-closed (obuna emas).
                logger.warning("Obuna tekshiruvi fail-closed (%s / %s): %s", ch_id, user_id, e)
                is_member = False
        _membership_cache[cache_key] = (now, is_member)
        if not is_member:
            unsubscribed.append(s)

    # Kesh o'sishini cheklash
    if len(_membership_cache) > MEMBERSHIP_CACHE_MAX:
        cutoff = now - MEMBERSHIP_CACHE_TTL
        for k in [k for k, v in _membership_cache.items() if v[0] < cutoff]:
            _membership_cache.pop(k, None)

    return (len(unsubscribed) == 0), unsubscribed


# Alias
check_user_sponsorship = check_user_subscribed


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_fsm_data(context)
    user = update.effective_user
    detected = detect_language(getattr(user, "language_code", None))

    referrer_id = None
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                referrer_id = int(arg.replace("ref_", ""))
            except ValueError:
                referrer_id = None

    is_new = await db.run_db(
        db.save_user, user.id, user.username or "", user.full_name or "",
        referrer_id=referrer_id, language_code=detected,
    )
    if is_new:
        lang = detected
    else:
        lang = await db.run_db(db.get_user_language, user.id)
    set_lang_cache(context, lang)

    # 8-bosqich: self-referral rad etilgani uchun bonus YO'Q — "siz bonus
    # yutdingiz" xabarini ham yubormaymiz (referrer == user bo'lsa).
    if is_new and referrer_id and referrer_id != user.id:
        try:
            ref_stats = await db.run_db(db.get_referral_stats, referrer_id)
            ref_count = int((ref_stats or {}).get("referrals_count", 0))
            reward = db.referral_reward_for(ref_count)
            ref_lang = await db.run_db(db.get_user_language, referrer_id)
            await context.bot.send_message(
                chat_id=referrer_id,
                text=get_text("referral_reward_notice", ref_lang, reward=reward),
                parse_mode="HTML"
            )
        except Exception:
            pass

    is_sub, unsubs = await check_user_subscribed(context.bot, user.id)
    if unsubs is None:
        await update.message.reply_text(
            get_text("sys_busy", lang),
            parse_mode="HTML",
        )
        return ConversationHandler.END
    if not is_sub:
        await update.message.reply_text(
            get_text("sub_required", lang),
            reply_markup=get_subscription_check_keyboard(unsubs, lang),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    is_admin = (user.id in ADMIN_IDS_SET)
    ad_line = await get_smart_reply_ad_async(user.id)
    # 🚀 BIRINCHI MARTA kirgan foydalanuvchi (bazada yangi yozuv yaratildi) —
    # qisqa, harakatga undovchi onboarding matni ko'rsatiladi. Qayta kirganda
    # (/start) esa odatdagi standart salomlashish chiqadi.
    if is_new:
        greeting = get_text("start_onboarding", lang)
    else:
        greeting = get_text("start_hello", lang, name=html_escape(user.first_name))
    # 🆕 YANGI FOYDALANUVCHI (ro'yxatdan o'tganiga 3 kundan kam YOKI hali 3 ta
    # post chiqarmagan) — murakkab 6 talik menyu o'rniga 3 ta katta tugmali
    # sodda klaviatura + qisqa yo'riqnoma. "⚙️ To'liq menyuni ochish" bosilsa
    # yoki 3 kun o'tsa — avtomatik standart menyuga o'tiladi.
    reply_markup = await resolve_main_keyboard(user.id, is_admin, lang, context)
    greeting += await main_menu_intro_suffix(user.id, is_admin, lang, context)
    await update.message.reply_text(
        f"{greeting}{ad_line}",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    return ConversationHandler.END


async def send_main_menu(context, chat_id: int, lang: str, is_admin: bool,
                         text: str | None = None, simple_menu: bool = False):
    """Asosiy reply-menyuni ``main_menu_hint`` bilan yuboradi (uz/ru).

    Start/orqaga/fallback oqimlari uchun yagona yordamchi: ``text`` berilsa u
    xabar matni bo'ladi, aks holda faqat ``main_menu_hint`` chiqadi. Har doim
    foydalanuvchi tilidagi asosiy klaviatura biriktiriladi.

    ``simple_menu=True`` bo'lsa (yangi foydalanuvchi) — 6 talik menyu o'rniga
    3 tugmali sodda klaviatura biriktiriladi. Bu funksiya bazaga so'rov
    YUBORMAYDI: qarorni chaqiruvchi oldindan hisoblab beradi.
    """
    body = text if text else get_text("main_menu_hint", lang)
    if simple_menu and not is_admin:
        markup = get_simple_keyboard(lang)
    else:
        markup = get_main_keyboard(is_admin, lang=lang, context=context)
    return await context.bot.send_message(
        chat_id=chat_id,
        text=body,
        reply_markup=markup,
        parse_mode="HTML",
    )

async def subscription_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    # Darhol javob
    try:
        await query.answer()
    except Exception:
        pass

    is_sub, unsubs = await check_user_subscribed(context.bot, user.id)

    # Til: kesh → DB (bot qayta ishga tushgan bo'lsa ham RU foydalanuvchi
    # ruscha javob oladi).
    lang = await ensure_user_lang(context, user.id)

    if is_sub:
        try:
            await query.message.delete()
        except TelegramError:
            pass
        is_admin = (user.id in ADMIN_IDS_SET)
        # Obuna tasdiqlangach — tabrik + main_menu_hint + asosiy menyu (uz/ru).
        # Yangi foydalanuvchi bo'lsa sodda (3 tugmali) klaviatura biriktiriladi.
        await send_main_menu(
            context, user.id, lang, is_admin,
            text=get_text(
                "sub_confirmed", lang,
                name=html_escape(user.first_name or ""),
                hint=get_text("main_menu_hint", lang),
            ),
            simple_menu=await user_wants_simple_menu(user.id, context),
        )
    else:
        try:
            await query.answer(get_text("sub_not_yet_alert", lang), show_alert=True)
        except Exception:
            pass
        try:
            await query.edit_message_reply_markup(reply_markup=get_subscription_check_keyboard(unsubs, lang))
        except TelegramError:
            pass
        try:
            await query.message.reply_text(
                get_text("sub_not_yet_msg", lang),
                parse_mode="HTML",
            )
        except Exception:
            pass


def cabinet_credits_text(is_admin: bool, credits, lang: str = "uz") -> str:
    """AI ballari matni: admin uchun cheksiz, oddiy foydalanuvchi uchun son."""
    if is_admin:
        return get_text("cabinet_credits_admin", lang)
    return get_text("credits_value", lang, n=credits)


def build_cabinet_text(
    user_id, user_code, credits_text, streak_text,
    channels_count, referrals_count, lang="uz", ad_line="",
) -> str:
    """Kabinet ekrani matnini foydalanuvchi tilida (uz/ru) quradi."""
    return get_text(
        "cabinet_title", lang,
        user_id=user_id,
        user_code=user_code,
        credits=credits_text,
        streak=streak_text,
        channels=channels_count,
        referrals=referrals_count,
        ad_line=ad_line or "",
    )


def build_daily_bonus_text(res: dict, lang: str = "uz") -> str:
    """Kunlik bonus natijasi matnini foydalanuvchi tilida quradi."""
    streak = res["streak"]
    bonus = res["bonus_amount"]
    credits = res["credits"]
    progress_bar = "".join(
        ["\U0001f7e9" if i <= streak else "\u2b1c" for i in range(1, 8)]
    )
    reset_notice = (
        get_text("daily_bonus_reset_notice", lang) if res.get("is_reset") else ""
    )
    return get_text(
        "daily_bonus_claimed", lang,
        reset_notice=reset_notice, streak=streak, bar=progress_bar,
        bonus=bonus, credits=credits,
    )


async def user_cabinet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """👤 Profil — profil kartasi + IXCHAM 6 TUGMALI MENYU (3-QISM).

    Asosiy menyudagi [👤 Profil] tugmasi (eski nomi — «⚙️ Sozlamalar»)
    bosilganda foydalanuvchi ma'lumotlari (ID, maxsus kod, AI so'rovlar,
    kunlik seriya, kanallar, takliflar) bilan birga YAGONA ixcham menyu
    chiqadi (handlers/settings.py — ``stgs_*`` callback'lari):

        [🌐 Til / Язык]        [✍️ Post sozlamalari]
        [🔔 Bildirishnomalar]  [💳 To'lovlar tarixi]
        [💬 Qo'llab-quvvatlash]
        [❌ Yopish]

    «⚙️ Sozlamalar» va «👤 Shaxsiy kabinet» ikki xil profil chalkashligi
    tugatildi: endi BITTA «👤 Profil» ekran bor. Referral (👥 Do'stlarni
    taklif) asosiy menyuga ko'chdi; 🎁 Kunlik bonus referral ekranida.
    Mavjud kabinet oqimlari (``cab_*``) esa eski xabarlar uchun saqlanadi.
    """
    clear_fsm_data(context)
    user = update.effective_user
    # Reply-tugma orqali kelgan so'rovda til keshda bo'lmasa (masalan, bot
    # qayta ishga tushgach) — foydalanuvchi tilini DB'dan yuklaymiz. Aks holda
    # rus foydalanuvchi kabinetni o'zbekchada ko'rib qolardi (get_lang uz).
    lang = await ensure_user_lang(context, user.id)
    # 🧭 4-qadam: foydalanuvchi «⚙️ Sozlamalar» bo'limida — bu bo'limdan
    # boshlangan FSM oqimlari (Vositalar → Konvertor/Enhancer va h.k.)
    # bekor qilinsa, foydalanuvchi aynan shu menyuga qaytadi.
    from handlers.navigation import remember_section, SECTION_SETTINGS
    remember_section(context, SECTION_SETTINGS)
    is_admin = (user.id in ADMIN_IDS_SET)
    stats = await db.run_db(db.get_referral_stats, user.id)
    channels = await db.run_db(db.get_user_channels, user.id)
    user_code = await db.run_db(db.get_user_code, user.id)

    credits_text = cabinet_credits_text(is_admin, stats['ai_credits'], lang)
    streak_text = get_text("cabinet_streak", lang, streak=stats.get('streak', 0))
    ad_line = await get_smart_reply_ad_async(user.id)

    text = build_cabinet_text(
        user.id, user_code, credits_text, streak_text,
        len(channels), stats['referrals_count'], lang, ad_line,
    )
    await update.message.reply_text(text, reply_markup=get_settings_hub_keyboard(lang), parse_mode="HTML")

async def daily_bonus_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin = (user.id in ADMIN_IDS_SET)
    lang = await ensure_user_lang(context, user.id)

    if is_admin:
        await update.message.reply_text(get_text("daily_bonus_admin", lang), parse_mode="HTML")
        return

    res = await db.run_db(db.claim_daily_streak_bonus, user.id)
    if res.get("success"):
        text = build_daily_bonus_text(res, lang)
        await update.message.reply_text(text, reply_markup=get_cabinet_keyboard(lang), parse_mode="HTML")
    else:
        await update.message.reply_text(
            get_text(
                "daily_bonus_already", lang,
                msg=localize_db_message(res.get("msg", ""), lang),
                credits=res.get("credits", 0),
            ),
            reply_markup=get_cabinet_keyboard(lang),
            parse_mode="HTML"
        )

async def user_invite_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """👥 Do'stlarni taklif — ASOSIY MENYU tugmasi (3-QISM refaktori).

    Referral endi ichki «🎁 Bonuslar & Taklif» hub'ida yashirinib
    qolmaydi: asosiy menyudan to'g'ridan-to'g'ri ochiladi va ekranda
    darhol:
      * referal havolasi,
      * taklif qilingan do'stlar soni,
      * ishlangan AI ballar
    chiqadi. Inline tugmalar (``get_referral_share_keyboard``):
      * [📲 Do'stlarga ulashish] — ``switch_inline_query`` orqali chat
        tanlash oynasi ochiladi (inline natija — referal havola);
      * [🎁 Kunlik bonus] — mavjud ``claim_bonus`` oqimi.
    """
    clear_fsm_data(context)
    user = update.effective_user
    is_admin = (user.id in ADMIN_IDS_SET)
    lang = await ensure_user_lang(context, user.id)
    bot_obj = await context.bot.get_me()
    stats = await db.run_db(db.get_referral_stats, user.id)
    ref_link = f"https://t.me/{bot_obj.username}?start=ref_{user.id}"
    
    credits_text = cabinet_credits_text(is_admin, stats['ai_credits'], lang)

    text = get_text(
        "referral_menu", lang, credits=credits_text,
        count=stats["referrals_count"], link=ref_link,
    )
    await update.message.reply_text(
        text,
        reply_markup=get_referral_share_keyboard(ref_link, lang),
        parse_mode="HTML"
    )


async def referral_inline_query_handler(update: Update,
                                        context: ContextTypes.DEFAULT_TYPE):
    """📲 Do'stlarga ulashish — ``switch_inline_query`` inline natijasi.

    Referral ekranidagi [📲 Do'stlarga ulashish] tugmasi Telegram'da chat
    tanlash oynasini ochadi; foydalanuvchi chat tanlagach bot shu handler
    orqali JAVOB QAYTARADI — inline natija (referal havola + taklif matni)
    tanlangan chatga yuboriladi. Natija ``is_personal`` (har bir
    foydalanuvchi O'Z havolasini ko'radi) va ``cache_time=0``.
    """
    from telegram import (
        InlineQueryResultArticle,
        InputTextMessageContent,
    )

    query = getattr(update, "inline_query", None)
    if query is None:
        return
    user_id = query.from_user.id
    lang = await ensure_user_lang(context, user_id)
    try:
        bot_obj = await context.bot.get_me()
    except Exception:
        return
    ref_link = f"https://t.me/{bot_obj.username}?start=ref_{user_id}"
    share_text = get_text("ref_share_text", lang)
    try:
        await query.answer(
            [
                InlineQueryResultArticle(
                    id=f"ref_{user_id}",
                    title=get_text("btn_share_referral", lang),
                    description=ref_link,
                    input_message_content=InputTextMessageContent(
                        f"{share_text}\n{ref_link}"
                    ),
                )
            ],
            cache_time=0,
            is_personal=True,
        )
    except Exception:
        logger.exception("Referral inline query javobida xato")

async def _begin_transfer_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🔄 Ballar o'tkazish oqimining YAGONA kirish nuqtasi (uz/ru/en).

    Ikkala kirish yo'li ham (pastdagi reply-tugma va ⚙️ Sozlamalar menyusidagi
    [🔄 Ballar o'tkazish] inline tugmasi) shu yordamchidan foydalanadi —
    FSM (``TRANSFER_TARGET`` → ``TRANSFER_AMOUNT``) va barcha matnlar bir xil
    qoladi, mantiq takrorlanmaydi.

    ``update.effective_message`` ishlatiladi: u ham oddiy xabar (reply-tugma),
    ham callback query xabari uchun to'g'ri ishlaydi.
    """
    user_id = update.effective_user.id
    lang = await ensure_user_lang(context, user_id)
    message = update.effective_message
    my_credits = await db.run_db(db.get_user_credits, user_id)

    if my_credits < 3 and user_id not in ADMIN_IDS_SET:
        await message.reply_text(
            get_text(
                "transfer_insufficient", lang,
                credits=my_credits,
                guide=get_text("daily_bonus_guide", lang),
            ),
            reply_markup=get_cabinet_keyboard(lang),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    await message.reply_text(
        get_text("transfer_intro", lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML"
    )
    return TRANSFER_TARGET


async def start_transfer_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🔄 Ballar o'tkazish — pastdagi reply-tugma orqali kirish (o'zgarmagan)."""
    clear_fsm_data(context)
    return await _begin_transfer_flow(update, context)


async def transfer_inline_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🔄 Ballar o'tkazish — ⚙️ Sozlamalar menyusidagi inline tugma orqali kirish.

    PostAssist V2 · 3-qadam: menyudagi [🔄 Ballar o'tkazish] tugmasi mavjud
    FSM oqimini AYNAN ochadi (yangi holat yaratilmaydi, eski callback'lar
    o'chirilmaydi). ``handlers/__init__.py`` da ``start_handlers`` ro'yxatiga
    qo'shilgani uchun u ham entry point, ham HAR BIR faol holatda "menyu
    sakrashi" (all_menu_jumps) sifatida ishlaydi.
    """
    query = getattr(update, "callback_query", None)
    if query is not None:
        try:
            await query.answer()
        except Exception:
            pass
    clear_fsm_data(context)
    return await _begin_transfer_flow(update, context)

async def transfer_target_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_input = update.message.text
    target_user = await db.run_db(db.find_user_by_target, target_input)
    
    lang = get_lang(context)

    # Ro'yxatdan o'tmagan foydalanuvchini qat'iy tekshirish
    if not target_user:
        await update.message.reply_text(
            get_text("transfer_user_not_found", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML"
        )
        return TRANSFER_TARGET

    t_id, t_name, t_user, t_code, t_cred = target_user
    if t_id == update.effective_user.id:
        await update.message.reply_text(get_text("transfer_self", lang))
        return TRANSFER_TARGET

    context.user_data["transfer_to_id"] = t_id
    context.user_data["transfer_to_name"] = t_name or t_user or str(t_id)

    await update.message.reply_text(
        get_text(
            "transfer_target_ok", lang,
            name=html_escape(context.user_data['transfer_to_name']),
            user_id=t_id,
        ),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML"
    )
    return TRANSFER_AMOUNT

async def transfer_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text(get_text("transfer_amount_nan", lang))
        return TRANSFER_AMOUNT

    amount = int(text)
    if amount < 3 or amount > 20:
        await update.message.reply_text(get_text("transfer_amount_range", lang), parse_mode="HTML")
        return TRANSFER_AMOUNT

    from_id = update.effective_user.id
    to_id = context.user_data.get("transfer_to_id")
    to_name = context.user_data.get(
        "transfer_to_name", get_text("transfer_default_name", lang)
    )

    success, msg = await db.run_db(db.transfer_user_credits, from_id, to_id, amount)

    if success:
        await update.message.reply_text(
            get_text("transfer_success", lang, name=html_escape(to_name), amount=amount),
            reply_markup=get_cabinet_keyboard(lang),
            parse_mode="HTML"
        )
        try:
            sender_name = update.effective_user.first_name
            await context.bot.send_message(
                chat_id=to_id,
                text=get_text(
                    "transfer_gift_notice", lang,
                    name=html_escape(sender_name), amount=amount,
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        await update.message.reply_text(
            get_text("transfer_error", lang, msg=localize_db_message(msg, lang)),
            reply_markup=get_cabinet_keyboard(lang),
            parse_mode="HTML",
        )
        
    clear_fsm_data(context)
    return ConversationHandler.END

def _help_support_line(lang: str = "uz") -> str:
    """Qo'llanma/FAQ oxiridagi qo'llab-quvvatlash aloqasi qatori (uz/ru).

    SUPPORT_USERNAME sozlansa "… @username bilan bog'laning" ko'rinishida,
    aks holda umumiy "bot administratori bilan bog'laning" matni chiqadi.
    """
    admin = f"@{SUPPORT_USERNAME}" if SUPPORT_USERNAME else get_text("help_admin_fallback", lang)
    return get_text("help_support_line", lang, admin=admin)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📖 Qo'llanma / Bot haqida — to'liq yo'riqnoma + FAQ + qo'llab-quvvatlash (uz/ru)."""
    user_id = update.effective_user.id
    is_admin = (user_id in ADMIN_IDS_SET)
    lang = await ensure_user_lang(context, user_id)
    ad_line = await get_smart_reply_ad_async(user_id)
    text = get_text("help_guide", lang, support=_help_support_line(lang))
    if is_admin:
        text += get_text("help_guide_admin", lang)
    await update.message.reply_text(
        f"{text}{ad_line}",
        reply_markup=get_help_keyboard(SUPPORT_USERNAME, lang),
        parse_mode="HTML",
    )


async def help_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📖 Qo'llanma ichki tugmalari: help:faq ↔ help:guide (uz/ru)."""
    query = update.callback_query
    await query.answer()
    lang = await ensure_user_lang(context, query.from_user.id)
    try:
        settings_flow = bool(context.user_data.get("settings_help_flow"))
    except Exception:
        settings_flow = False
    if (query.data or "") == "help:faq":
        text = get_text("help_faq", lang, support=_help_support_line(lang))
        markup = (
            get_settings_back_keyboard(lang)
            if settings_flow else get_help_back_keyboard(lang)
        )
    else:  # "help:guide" — asosiy qo'llanma sahifasi
        text = get_text("help_guide", lang, support=_help_support_line(lang))
        help_kb = get_help_keyboard(SUPPORT_USERNAME, lang)
        if settings_flow:
            markup = InlineKeyboardMarkup(
                help_kb.inline_keyboard
                + get_settings_back_keyboard(lang).inline_keyboard
            )
        else:
            markup = help_kb
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")


async def extras_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """⚙️ Qo'shimcha funksiyalar — inline menyu ko'rsatadi (uz/ru)."""
    clear_fsm_data(context)
    user = getattr(update, "effective_user", None)
    user_id = user.id if user is not None else None
    lang = await ensure_user_lang(context, user_id)
    await update.message.reply_text(
        get_text("extras_menu_body", lang),
        reply_markup=get_extras_inline_keyboard(lang),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def extras_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Qo'shimcha funksiyalar oynasini yopadi (✅ Yopildi. / ✅ Закрыто.)."""
    query = update.callback_query
    await query.answer()
    is_admin = query.from_user.id in ADMIN_IDS_SET
    lang = await ensure_user_lang(context, query.from_user.id)
    try:
        await query.message.delete()
    except Exception:
        pass
    await query.message.reply_text(
        get_text("msg_closed", lang),
        reply_markup=get_main_keyboard(is_admin, lang=lang),
    )


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[❌ Bekor qilish] — FSM kontekst tozalanadi va BO'LIM BOSHIGA qaytadi.

    PostAssist V2 · 4-qadam navigatsiya stacki standarti: jarayon (FSM)
    ichida [❌ Bekor qilish] bosilsa kontekst tozalanadi va foydalanuvchi
    O'SHA BO'LIM BOSHIGA qaytadi (masalan, «✨ Kontent yaratish» submenyusi
    yoki «🤖 AI Yordamchi» hub'iga kirib ketgan bo'lsa). Bo'lim noma'lum
    bo'lsa — asosiy menyuga (eski xulq, to'liq orqaga moslik).
    """
    user_id = update.effective_user.id
    # Tugallanmagan albom yig'uvchi task'ini ham bekor qilamiz (leak/ustiga
    # yozilish oldini olish uchun).
    try:
        from handlers.new_post import cancel_album_collections
        cancel_album_collections(user_id)
    except Exception:
        pass
    is_admin = (user_id in ADMIN_IDS_SET)
    lang = await ensure_user_lang(context, user_id)
    # 🧭 Bo'limni FSM tozalanishidan OLDIN o'qib olamiz (clear_fsm_data
    # user_data ni tozalaydi, lekin nav_section endi omon qoladi).
    from handlers.navigation import (
        render_section_start_message, current_section, SECTION_MAIN,
    )
    section = current_section(context)
    clear_fsm_data(context)
    if section != SECTION_MAIN:
        # Bo'lim boshiga qaytish (Kontent submenu / AI Studio hub / ...).
        # Xato bo'lsa — asosiy menyuga fallback (fail-safe).
        try:
            rendered = await render_section_start_message(
                update.message, context, user_id, is_admin, lang,
            )
        except Exception:
            rendered = False
        if rendered:
            return ConversationHandler.END
    await update.message.reply_text(
        get_text("cancel_done", lang),
        # 🆕 Yangi foydalanuvchi bekor qilgandan keyin ham sodda (3 tugmali)
        # menyuga qaytadi — 6 talik menyu uni yana chalkashtirmaydi.
        reply_markup=await resolve_main_keyboard(user_id, is_admin, lang, context),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def cabinet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kabinet inline tugmalari — barcha ichki bo'limlar inline bilan."""
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS_SET
    # Tilni doim bazadan keshlangan holda olamiz: bot qayta ishga tushgach
    # eski kabinet tugmasi bosilsa ham foydalanuvchi tili (uz/ru) to'g'ri
    # aniqlanadi. Bu o'zgaruvchi quyidagi barcha bo'limlarda ishlatiladi.
    lang = await ensure_user_lang(context, user_id)

    if data == "close_cabinet":
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.message.reply_text(
            get_text("msg_closed", lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
        )
        return

    if data == "cab_lang":
        await query.answer()
        lang = get_lang(context)
        try:
            await query.edit_message_text(
                get_text("lang_prompt", lang),
                reply_markup=get_language_keyboard(lang),
                parse_mode="HTML",
            )
        except Exception:
            await query.message.reply_text(
                get_text("lang_prompt", lang),
                reply_markup=get_language_keyboard(lang),
                parse_mode="HTML",
            )
        return

    if data in ("cab_lang_uz", "cab_lang_ru", "cab_lang_en"):
        await query.answer()
        # 1) Til bazada + keshda yangilanadi (uz / ru / en).
        lang = await switch_user_language(context, user_id, data.rsplit("_", 1)[-1])

        # 2) Inline menyu TO'LIQ yangi tilda qayta chiziladi: avval Kabinet
        #    ekrani (barcha tugma va matnlar yangi tilda), bu iloji bo'lmasa
        #    hech bo'lmaganda til tanlash menyusi yangilanadi.
        try:
            stats = await db.run_db(db.get_referral_stats, user_id)
            channels = await db.run_db(db.get_user_channels, user_id)
            user_code = await db.run_db(db.get_user_code, user_id)
            credits_text = cabinet_credits_text(is_admin, stats["ai_credits"], lang)
            streak_text = safe_t("cabinet_streak", lang, streak=stats.get("streak", 0))
            text = build_cabinet_text(
                user_id, user_code, credits_text, streak_text,
                len(channels), stats["referrals_count"], lang,
            )
            await query.edit_message_text(
                text, reply_markup=get_cabinet_inline_keyboard(lang), parse_mode="HTML"
            )
        except Exception:
            try:
                await query.edit_message_text(
                    safe_t("lang_changed", lang),
                    reply_markup=get_language_keyboard(lang),
                    parse_mode="HTML",
                )
            except Exception:
                pass

        # 3) Pastki doimiy ReplyKeyboard DARHOL yangi tilda yuboriladi
        #    (UZ: "➕ Yangi post", RU: "➕ Новый пост", EN: "➕ New post").
        #    Sodda menyu rejimidagi foydalanuvchiga sodda klaviatura qaytadi.
        await send_language_reply_keyboard(
            query.message, context, user_id, is_admin, lang
        )
        return

    if data == "cab_main":
        await query.answer()
        lang = get_lang(context)
        stats = await db.run_db(db.get_referral_stats, user_id)
        channels = await db.run_db(db.get_user_channels, user_id)
        user_code = await db.run_db(db.get_user_code, user_id)

        credits_text = cabinet_credits_text(is_admin, stats['ai_credits'], lang)
        streak_text = get_text("cabinet_streak", lang, streak=stats.get('streak', 0))

        text = build_cabinet_text(
            user_id, user_code, credits_text, streak_text,
            len(channels), stats['referrals_count'], lang,
        )
        try:
            await query.edit_message_text(text, reply_markup=get_cabinet_inline_keyboard(lang), parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=get_cabinet_inline_keyboard(lang), parse_mode="HTML")
        return

    if data == "cab_channels":
        await query.answer()
        lang = get_lang(context)
        channels = await db.run_db(db.get_user_channels, user_id)
        if not channels:
            text = get_text("my_channels_empty", lang, hint=no_channels_hint(lang))
            markup = get_channels_manage_keyboard(lang)
        else:
            text = get_text("my_channels_list", lang, count=len(channels))
            for i, ch in enumerate(channels, 1):
                ch_id, ch_title = ch[:2]
                text += f"{i}. <b>{html_escape(ch_title or 'Kanal')}</b> (<code>{ch_id}</code>)\n"
            text += get_text("my_channels_footer", lang)
            markup = get_channels_manage_keyboard(lang)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
        return

    if data == "cab_channels_delete":
        await query.answer()
        lang = get_lang(context)
        channels = await db.run_db(db.get_user_channels, user_id)
        if not channels:
            text = get_text(
                "cab_channels_delete_empty", lang, hint=no_channels_hint(lang)
            )
            markup = get_channels_manage_keyboard(lang)
        else:
            text = get_text("cab_channels_delete_title", lang, count=len(channels))
            markup = render_channels_list(channels, lang)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
        return

    if data == "cab_analytics":
        await query.answer()
        lang = get_lang(context)
        from handlers.analytics import _build_dashboard
        stats = await db.run_db(db.get_channel_post_stats, user_id, None)
        text = _build_dashboard(
            stats, get_text("an_all_channels", lang), lang,
        )
        try:
            await query.edit_message_text(text, reply_markup=get_cabinet_back_keyboard(lang), parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=get_cabinet_back_keyboard(lang), parse_mode="HTML")
        return

    if data == "cab_converter":
        await query.answer()
        lang = get_lang(context)
        text = get_text("cab_converter_info", lang)
        try:
            await query.edit_message_text(text, reply_markup=get_cabinet_back_keyboard(lang), parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=get_cabinet_back_keyboard(lang), parse_mode="HTML")
        return

    if data == "cab_bonus":
        await query.answer()
        lang = get_lang(context)
        if is_admin:
            text = get_text("daily_bonus_admin", lang)
            try:
                await query.edit_message_text(text, reply_markup=get_cabinet_back_keyboard(lang), parse_mode="HTML")
            except Exception:
                await query.message.reply_text(text, reply_markup=get_cabinet_back_keyboard(lang), parse_mode="HTML")
            return

        res = await db.run_db(db.claim_daily_streak_bonus, user_id)
        if res.get("success"):
            text = build_daily_bonus_text(res, lang)
        else:
            text = get_text(
                "daily_bonus_already", lang,
                msg=localize_db_message(res.get("msg", ""), lang),
                credits=res.get("credits", 0),
            )
        try:
            await query.edit_message_text(text, reply_markup=get_cabinet_back_keyboard(lang), parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=get_cabinet_back_keyboard(lang), parse_mode="HTML")
        return

    if data == "cab_referral":
        await query.answer()
        bot_obj = await context.bot.get_me()
        stats = await db.run_db(db.get_referral_stats, user_id)
        ref_link = f"https://t.me/{bot_obj.username}?start=ref_{user_id}"
        lang = get_lang(context)
        credits_text = cabinet_credits_text(is_admin, stats['ai_credits'], lang)
        text = get_text(
            "referral_menu", lang, credits=credits_text,
            count=stats["referrals_count"], link=ref_link,
        )
        share_kb = get_referral_share_keyboard(ref_link, lang)
        combined_kb = InlineKeyboardMarkup(
            share_kb.inline_keyboard + get_cabinet_back_keyboard(lang).inline_keyboard
        )
        try:
            await query.edit_message_text(text, reply_markup=combined_kb, parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=combined_kb, parse_mode="HTML")
        return

    if data == "cab_balance":
        await query.answer()
        stats = await db.run_db(db.get_referral_stats, user_id)
        lang = get_lang(context)
        credits_text = cabinet_credits_text(is_admin, stats['ai_credits'], lang)
        if is_admin:
            ad_mode = get_text("ad_mode_admin", lang)
        elif await db.run_db(db.is_premium, user_id):
            ad_mode = get_text("ad_mode_pro", lang)
        else:
            ad_mode = get_text("ad_mode_free", lang)
        text = get_text("balance_card", lang, credits=credits_text, ad_mode=ad_mode)
        try:
            await query.edit_message_text(text, reply_markup=get_cabinet_back_keyboard(lang), parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=get_cabinet_back_keyboard(lang), parse_mode="HTML")
        return

    if data == "cab_pending":
        # PostAssist V2 · 2-qadam (B1): eski «Kutilayotgan postlar» kabinet
        # tugmasi endi YAGONA «📅 Rejalashtirilgan» ekranini ochadi —
        # `cab_queue` bilan AYNAN bir xil manba (handlers.queue.scheduled_view).
        await query.answer()
        # Kabinet xabarini o'chirib, yagona rejalashtirilgan ro'yxatni yangi
        # xabar sifatida yuboramiz (eski xatti-harakat saqlanadi).
        try:
            await query.message.delete()
        except Exception:
            pass
        from handlers.queue import scheduled_view
        text, markup = await scheduled_view(user_id, lang, is_admin)
        await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
        return

    if data == "cab_queue":
        await query.answer()
        # Eski (alias) `cab_queue` callback'i ham o'sha yagona ekranga boradi.
        try:
            await query.message.delete()
        except Exception:
            pass
        from handlers.queue import scheduled_view
        try:
            text, markup = await scheduled_view(user_id, lang, is_admin)
        except Exception:
            # Baza xatosi bo'lsa ham foydalanuvchi JAVOB olishi shart —
            # aks holda tugma "qotib qolgan" bo'lib ko'rinadi.
            # Log matni ataylab eski iborani saqlaydi (regressiya testi shu
            # qatorni tekshiradi): «Post navbati» — endi yagona «📅
            # Rejalashtirilgan» ko'rinishi.
            logger.exception(
                "Post navbati ekranini qurishda xato — «📅 Rejalashtirilgan» "
                "ko'rinishi qurilmadi (user=%s)", user_id)
            text = get_text("queue_db_error", lang)
            markup = get_cabinet_back_keyboard(lang)
        await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
        return

    if data == "cab_guide":
        await query.answer()
        lang = get_lang(context)
        text = get_text("cab_guide_text", lang, support=_help_support_line(lang))
        try:
            await query.edit_message_text(text, reply_markup=get_cabinet_back_keyboard(lang), parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=get_cabinet_back_keyboard(lang), parse_mode="HTML")
        return
