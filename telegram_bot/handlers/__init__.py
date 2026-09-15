import logging
import re

from keyboards.callback_data import CB_CHANNEL_VOICE
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ChatMemberHandler,
    PreCheckoutQueryHandler,
    filters,
)
from config import ADMIN_IDS_SET
from keyboards.default import (
    exact,
    # 🆕 UX V2 — asosiy menyu QAT'IY 6 TUGMA standarti (uz/ru/en):
    #   [✨ Kontent yaratish] [📢 Kanallarim]
    #   [📅 Rejalashtirilgan] [📊 Statistika]
    #   [💎 PRO]              [⚙️ Sozlamalar]  (+ admin: ⚙️ Admin Panel)
    BTN_CREATE_CONTENT, BTN_CREATE_CONTENT_RU, BTN_CREATE_CONTENT_EN,
    BTN_MY_CHANNELS, BTN_MY_CHANNELS_RU, BTN_MY_CHANNELS_EN,
    BTN_SCHEDULED, BTN_SCHEDULED_RU, BTN_SCHEDULED_EN,
    BTN_STATISTICS, BTN_STATISTICS_RU, BTN_STATISTICS_EN,
    BTN_NEW_POST, BTN_NEW_POST_RU, BTN_AI_STUDIO, BTN_AI_STUDIO_RU,
    BTN_PENDING, BTN_PENDING_RU, BTN_SETTINGS, BTN_SETTINGS_RU, BTN_CABINET,
    BTN_HELP, BTN_HELP_RU, BTN_CONVERTER, BTN_CONVERTER_RU,
    BTN_EXTRAS, BTN_EXTRAS_RU,
    BTN_BACK, BTN_BACK_RU, BTN_MAIN_MENU, BTN_CANCEL, BTN_CANCEL_RU,
    BTN_CHANNELS, BTN_CHANNELS_RU,
    BTN_DAILY_BONUS, BTN_DAILY_BONUS_RU,
    BTN_INVITE, BTN_INVITE_RU,
    BTN_TRANSFER, BTN_TRANSFER_RU,
    BTN_ADMIN_PANEL, BTN_ALL_POSTS, BTN_ALL_CHANNELS,
    # 📊 STATISTIKA IZOLYATSIYASI: admin (bot bo'yicha) statistikaning o'ziga
    # xos yorlig'i va uning alias oilasi — asosiy menyudagi shaxsiy
    # «📊 Statistika» (BTN_STATISTICS) bilan matni bo'lishilmaydi.
    BTN_FULL_STATS, ADMIN_STATS_ALIASES,
    BTN_BROADCAST, BTN_SPONSORS, BTN_ADD_SPONSOR,
    BTN_ADS, BTN_CHANNEL_AD, BTN_BOT_REPLY_AD, BTN_POST_TAG, BTN_AI_SETTINGS, BTN_CACHE_DB,
    BTN_ADD_CHANNEL, BTN_QUEUE, BTN_QUEUE_RU, BTN_CONTENT_PLAN, BTN_ANALYTICS, BTN_PREMIUM, BTN_PREMIUM_RU,
    BTN_CHANNEL_EXTRACT,
    # 🆕 Yangi foydalanuvchilar uchun sodda (3 tugmali) klaviatura
    BTN_QUICK_AI_POST, BTN_QUICK_AI_POST_RU,
    BTN_QUICK_PHOTO_POST, BTN_QUICK_PHOTO_POST_RU,
    BTN_QUICK_ADD_CHANNEL, BTN_QUICK_ADD_CHANNEL_RU,
    BTN_OPEN_FULL_MENU, BTN_OPEN_FULL_MENU_RU,
    #  EN variantlar — asosiy menyu/kabinet/onboarding tugmalari inglizcha
    # klaviaturada bosilganda routing'da tanilishi uchun (uz/ru/en).
    BTN_NEW_POST_EN, BTN_AI_STUDIO_EN, BTN_PREMIUM_EN, BTN_SETTINGS_EN,
    BTN_HELP_EN, BTN_EXTRAS_EN, BTN_BACK_EN, BTN_CANCEL_EN,
    BTN_CHANNELS_EN, BTN_CONVERTER_EN, BTN_DAILY_BONUS_EN, BTN_INVITE_EN,
    BTN_TRANSFER_EN, BTN_ADMIN_PANEL_RU,
    BTN_QUICK_AI_POST_EN, BTN_QUICK_PHOTO_POST_EN,
    BTN_QUICK_ADD_CHANNEL_EN, BTN_OPEN_FULL_MENU_EN,
    # 📸 IMAGE → POST — yangi explicit entry label (legacy quick photo saqlanadi)
    BTN_IMAGE_POST, BTN_IMAGE_POST_RU, BTN_IMAGE_POST_EN,
    # ✨ MAGIC POST — killer feature tugmasi (uz/ru/en)
    BTN_MAGIC_POST, BTN_MAGIC_POST_RU, BTN_MAGIC_POST_EN,
    # 🧩 KONTENT YARATISH submenu'sining yangi yo'l tugmalari (uz/ru/en).
    # «✨ Magic Post» va «📸 Rasm → Post» esa yuqoridagi killer-featura
    # konstantalari bilan BITTA yorliqni ishlatadi — shu sababli bu yerda
    # takrorlanmaydi (bir yorliq — bitta amal = aniq routing).
    BTN_CONTENT_TEXT, BTN_CONTENT_TEXT_RU, BTN_CONTENT_TEXT_EN,
    BTN_CONTENT_VOICE, BTN_CONTENT_VOICE_RU, BTN_CONTENT_VOICE_EN,
    BTN_CONTENT_AI, BTN_CONTENT_AI_RU, BTN_CONTENT_AI_EN,
    BTN_CONTENT_BACK, BTN_CONTENT_BACK_RU, BTN_CONTENT_BACK_EN,
    BTN_POST_SCORE, BTN_POST_SCORE_RU, BTN_POST_SCORE_EN,
)
from locales.translations import clear_fsm_data, get_lang, get_text
from keyboards.inline import get_subscription_check_keyboard

# 1. START & ASOSIY MODUL
from handlers.start import (
    start, user_cabinet_menu, user_invite_menu, daily_bonus_handler, start_transfer_credits, transfer_target_received, transfer_amount_received,
    help_command, help_menu_callback, cancel_handler, subscription_check_callback, check_user_subscribed,
    cabinet_callback, extras_menu, extras_close_callback,
    # ⚙️ Sozlamalar menyusidagi [🔄 Ballar o'tkazish] inline kirishi
    # (PostAssist V2 · 3-qadam) — mavjud TRANSFER FSM oqimini ochadi.
    transfer_inline_entry,
    TRANSFER_TARGET, TRANSFER_AMOUNT
)

# 1b. 🆕 ONBOARDING — yangi foydalanuvchilar uchun sodda (3 tugmali) klaviatura
from handlers.onboarding import (
    quick_ai_post_entry, quick_photo_post_entry, quick_add_channel_entry,
    open_full_menu,
)

# 2. NEW POST MODULI
from handlers.new_post import (
    start_new_post, channel_chosen, content_received, btn_title_received,
    btn_url_received, reactions_received, auto_delete_received, time_received,
    daily_time_received, recur_day_chosen, recur_time_received, duration_chosen,
    confirm_post_callback, edit_confirm_field_callback, edit_confirm_message_received,
    edit_confirm_media_received,
    reaction_toggle_callback, reactions_done_callback, reactions_skip_callback,
    album_choice_callback,
    ai_action_menu_callback, ai_action_callback, ai_result_callback,
    skip_url_step, skip_reactions_step, SKIP_BUTTON_TEXTS, cancel_album_collections,
    CHOOSE_CHANNEL, GET_CONTENT, GET_BTN_TITLE, GET_BTN_URL,
    GET_REACTIONS, GET_AUTO_DELETE, GET_TIME, DAILY_TIME, RECUR_DAY, RECUR_TIME,
    GET_DURATION, CONFIRM_POST, EDIT_CONFIRM_FIELD
)

# 2b. 🛠 POST KUCHAYTIRGICH (Post Enhancer — qo'shimcha funksiyalar)
from handlers.post_enhancer import (
    post_enhancer_start, enh_message_received, enh_callback, enh_stale_callback,
    ENH_POST,
)

# 3. CHANNELS MODULI
from handlers.channels import (
    channels_menu, start_add_channel, channel_received, add_channel_retry,
    remove_channel_callback, on_bot_chat_member_update, add_channel_inline_entry,
    tone_menu_callback, tone_chosen, on_channel_post,
    channel_voice_analysis_callback,
    # 📢 KANALLARIM — kanal boshqaruv ekrani (PostAssist V2, 4-mikro qadam)
    channel_open_callback, channel_new_post_callback, channel_scheduled_callback,
    channel_stats_callback, channel_settings_callback, channels_list_callback,
    ADD_CHANNEL, SET_TONE
)

# 4. PENDING POSTS MODULI
from handlers.pending import (
    list_pending_posts, cancel_post_callback, refresh_pending_callback,
    edit_post_time_start, edit_post_time_received,
    edit_post_content_start, edit_post_content_received,
    edit_post_btn_start, edit_post_btn_received,
    edit_post_react_start, edit_post_react_received,
    EDIT_POST_TIME, EDIT_POST_CONTENT, EDIT_POST_BTN, EDIT_POST_REACT
)

# 5. CONVERTER MODULI
from handlers.converter import (
    start_converter, converter_received, converter_callback, converter_close_callback,
    converter_inline_entry, CONVERT_INPUT
)

# 6. ADMIN MODULI
from handlers.admin import (
    admin_panel_menu, show_statistics, admin_all_posts, admin_all_channels,
    broadcast_start, broadcast_send, sponsors_menu, start_add_sponsor,
    sponsor_channel_received, del_sponsor_callback,
    admin_ad_hub_entry, channel_ad_received, bot_reply_ad_received,
    ai_settings_menu, ai_settings_received, cache_db_menu, cache_clear_callback,
    start_set_post_tag, post_tag_received,
    admin_stats_command, admin_dashboard_callback, admin_inline_text_handler,
    admin_audit_command, admin_set_role_command, admin_del_role_command,
    ad_pool_callback,
    BROADCAST_MESSAGE, ADD_SPONSOR_CHANNEL, SET_CHANNEL_AD, SET_BOT_REPLY_AD,
    AI_SETTINGS, SET_POST_TAG, ADMIN_GRANT_PRO, ADMIN_PROMO_CREATE,
    ADMIN_SPONSOR_ADD,
)

# 7. AI ASSISTANT + AI STUDIO MODULI (ENG OXIRIDA)
from handlers.ai_assistant import (
    start_ai_assistant, ai_input_received, ai_confirm_callback, ai_time_received,
    ai_studio_menu_entry, ai_studio_hub_entry, ai_studio_nav_callback, ai_prompt_received,
    ai_tone_callback, ai_studio_schedule_callback, ai_audit_received,
    ai_back_to_menu, ai_close,
    ai_back_to_content, ai_exit_to_menu,
    ai_photo_received, ai_photo_result_callback, ai_photo_edit_received,
    AI_INPUT, AI_CONFIRM, AI_GET_TIME,
    AI_MENU_STATE, AI_PROMPT_INPUT, AI_TONE_SELECT, AI_AUDIT_INPUT,
    AI_PHOTO_INPUT, AI_PHOTO_RESULT, AI_PHOTO_EDIT_INPUT,
)

# 2c. ✨ MAGIC POST (Killer Feature #1 — matn → uslub → tayyor post)
# MUHIM: shu modul `handlers.ai_assistant` dan (AI_GET_TIME, _show_time_prompt)
# import oladi — shu sababli yuqoridagi ai_assistant importidan KEYIN turadi.
from handlers.magic_post import (
    magic_post_entry, magic_text_received, magic_style_callback,
    magic_send_now_callback, magic_channel_picked_callback,
    magic_schedule_callback, magic_restyle_callback, magic_stale_callback,
    magic_back_callback,
    MAGIC_INPUT, MAGIC_STYLE_SELECT, MAGIC_RESULT, MAGIC_SEND_CHOOSE,
)

# 2d. 🎙 VOICE → POST (Killer Feature — ovoz → matn → uslub → tayyor post)
# MUHIM: shu modul `handlers.magic_post` dan (_safe_edit, _magic_deliver_one),
# `handlers.ai_assistant` dan (AI_GET_TIME, _show_time_prompt) va
# `handlers.start` dan (check_user_subscribed, ensure_user_lang) import oladi —
# shu sababli yuqoridagi importlardan KEYIN turadi.
from handlers.voice_post import (
    voice_message_received, voice_style_callback, voice_cancel_callback,
    voice_send_now_callback, voice_channel_picked_callback,
    voice_schedule_callback, voice_restyle_callback, voice_stale_callback,
    voice_post_entry,
    set_application as set_voice_application,
    VoiceEntryHandler,
    VOICE_MESSAGE_FILTER, VOICE_AWAIT, VOICE_STYLE_SELECT, VOICE_RESULT,
    VOICE_SEND_CHOOSE,
)

# 2e. 📸 IMAGE → POST (Killer Feature #3)
# Legacy AI Studio Vision oqimi buzilmasligi uchun yangi oqim alohida FSM
# holatlari/callback prefikslari bilan ro'yxatdan o'tadi.
from handlers.image_post import (
    ImageEntryHandler,
    image_post_entry, image_photo_received, image_style_callback,
    image_cancel_callback, image_send_callback, image_channel_callback,
    image_schedule_callback, image_schedule_time_received,
    image_restyle_callback, image_back_callback, image_stale_callback,
    image_topic_received,
    set_application as set_image_application,
    IMAGE_POST_INPUT, IMAGE_STYLE_SELECT, IMAGE_POST_RESULT,
    IMAGE_SEND_CHOOSE, IMAGE_SCHEDULE_INPUT, IMAGE_TOPIC_INPUT,
)

# 2f. 📊 POST SCORE & IMPROVER (Killer Feature #4)
# MUHIM: modul Magic/Voice/Image oqimlaridan (natija holatlari va
# _safe_edit/_magic_deliver_one yordamchilari) import oladi — shu sababli
# ularning importlaridan KEYIN turadi.
from handlers.post_score import (
    POST_SCORE_INPUT, POST_SCORE_RESULT, POST_SCORE_SEND_CHOOSE,
    post_score_entry, post_score_text_received, post_score_eval_callback,
    post_score_improve_callback, post_score_new_callback,
    post_score_send_callback, post_score_channel_picked_callback,
    post_score_schedule_callback, post_score_stale_callback,
)

# 2g. 🧩 KONTENT YARATISH — submenu navigatsiyasi + ACTION-FIRST taklif
# (PostAssist V2). Modul Magic Post oqimiga tayanadi — shu sababli yuqoridagi
# killer-featura importlaridan KEYIN turadi.
from handlers.content_creation import (
    ContentOfferEntryHandler,
    content_creation_back, content_offer_callback,
    set_application as set_content_creation_application,
)

# 8. CONTENT PLAN MODULI
from handlers.content_plan import (
    start_content_plan, plan_channel_chosen, plan_topic_received, plan_view_callback,
    PLAN_CHOOSE_CHANNEL, PLAN_GET_TOPIC, PLAN_VIEW
)

# 8b. SMART CONTENT CALENDAR — 7/30 kunlik reja oqimi (PostAssist V2 · 2-qadam).
# «🤖 AI Yordamchi» → [🧠 Kontent reja] (``studio_content_plan``) shu modulga
# kiradi; eski ``content_plan`` oqimi (BTN_CONTENT_PLAN, ``plan_*``) tegilmaydi.
from handlers.content_calendar_flow import (
    CALENDAR_BUSINESS, CALENDAR_DURATION, CALENDAR_VIEW,
    calendar_business_received, calendar_cancel_callback, calendar_day_callback,
    calendar_duration_callback, calendar_stale_callback,
)

# 9. ANALYTICS MODULI
from handlers.analytics import (
    start_analytics, analytics_channel_chosen, analytics_view_callback,
    ANALYTICS_CHOOSE, ANALYTICS_VIEW
)

# 9b. 📊 SHAXSIY STATISTIKA — asosiy menyudagi «📊 Statistika» tugmasi.
# MUHIM: bu modul `handlers.analytics` dan ANALYTICS_VIEW oladi — shu sababli
# yuqoridagi analytics importidan KEYIN turadi.
# Izolyatsiya: asosiy menyu «📊 Statistika» FAQAT shu handlerga ulanadi
# (admin bo'ladimi, oddiy foydalanuvchimi — farqi yo'q). Admin (bot bo'yicha)
# statistikasi esa FAQAT ⚙️ Admin Panel → 📊 To'liq statistika ichida.
from handlers.statistics import show_user_statistics

# 10. SUBSCRIPTION MODULI
from handlers.subscription import (
    start_subscription, subscription_callback, promo_code_received,
    grant_pro_command, create_promo_command,
    precheckout_callback, successful_payment_callback,
    SUBSCRIPTION_VIEW, PROMO_INPUT, RECEIPT_WAIT
)

# 10b. 💳 KARTA CHEKLARI — Admin Approval Flow
from handlers.payment_receipt import (
    receipt_received, receipt_admin_callback,
)

# 10c. ⚙️ SOZLAMALAR — yagona tartibli menyu (PostAssist V2, 5-mikro qadam).
# «⚙️ Sozlamalar» bosilganda profil kartasi + 8 ta guruh chiqadi
# (stgs_* callback'lari); rewards/help hub callback'lari alohida patternlar
# bilan ham ro'yxatdan o'tkaziladi — generic legacy aliaslar saqlanadi.
from handlers.settings import (
    settings_help_hub_callback,
    settings_menu_callback,
    settings_rewards_callback,
)

# 11. CHANNEL EXTRACT MODULI
from handlers.channel_extract import (
    start_extract, extract_username_received, extract_post_chosen,
    EXTRACT_USERNAME, EXTRACT_CHOOSE_POST
)

# 12. QUEUE MODULI
from handlers.queue import (
    queue_menu, queue_page_callback, queue_view_callback,
    queue_delete_callback, queue_push_callback, queue_close_callback,
    queue_slots_callback, slot_add_message,
    # 🔗 Yagona «📅 Rejalashtirilgan» ro'yxatidagi 4-amal (Tugma/Reaksiya).
    scheduled_btn_react_callback,
    QUEUE_MENU, SLOT_ADD,
)

# 13. 🩺 TIZIM HOLATI MONITORINGI (7-BOSQICH)
from handlers.health import health_command

import database as db
from handlers.photo_check import (
    register as register_photo_check,
    PHOTO_CHECK_WAIT,
    handle_user_photo,
)
from utils.helpers import (
    check_rate_limit,
    NAV_RATE_LIMIT_MAX,
    ENTRY_RATE_LIMIT_MAX,
    REACTION_RATE_LIMIT_MAX,
)

logger = logging.getLogger(__name__)

CONVERSATION_TIMEOUT_SEC = 600


async def _deny_if_unsubscribed(update, context) -> bool:
    """True qaytsa — foydalanuvchi homiy obunasisiz, jarayon to'xtatiladi (fail-closed)."""
    user = update.effective_user
    if not user or not update.message:
        return False
    is_sub, unsubs = await check_user_subscribed(context.bot, user.id)
    if unsubs is None:
        await update.message.reply_text(
            get_text("sys_busy", get_lang(context)),
            parse_mode="HTML",
        )
        return True
    if not is_sub:
        lang = get_lang(context)
        await update.message.reply_text(
            get_text("sub_required", lang),
            reply_markup=get_subscription_check_keyboard(unsubs, lang),
            parse_mode="HTML",
        )
        return True
    return False


async def guard_entry(update, context, fn):
    user = update.effective_user
    if user:
        is_blocked, _ = check_rate_limit(user.id, max_requests=ENTRY_RATE_LIMIT_MAX, window_seconds=2.0)
        if is_blocked:
            wait_msg = get_text("pend_rate_limited", get_lang(context))
            if update.message:
                await update.message.reply_text(wait_msg, parse_mode="HTML")
            elif update.callback_query:
                try:
                    await update.callback_query.answer(wait_msg, show_alert=False)
                except Exception:
                    pass
            return ConversationHandler.END
        # Tugallanmagan albom yig'uvchi task'lari ham tozalanadi — ular yangi
        # konversatsiya user_data'iga eski postni yozib qo'ymasligi uchun.
        cancel_album_collections(user.id)

    if await _deny_if_unsubscribed(update, context):
        return ConversationHandler.END

    clear_fsm_data(context)
    return await fn(update, context)


async def guard_menu(update, context, fn):
    user = update.effective_user
    if user:
        is_blocked, _ = check_rate_limit(user.id, max_requests=NAV_RATE_LIMIT_MAX, window_seconds=2.0)
        if is_blocked:
            wait_msg = get_text("pend_rate_limited", get_lang(context))
            if update.message:
                await update.message.reply_text(wait_msg, parse_mode="HTML")
            elif update.callback_query:
                try:
                    await update.callback_query.answer(wait_msg, show_alert=False)
                except Exception:
                    pass
            return ConversationHandler.END
        cancel_album_collections(user.id)

    if await _deny_if_unsubscribed(update, context):
        return ConversationHandler.END

    clear_fsm_data(context)
    await fn(update, context)
    return ConversationHandler.END


async def statistics_button(update, context):
    """📊 Statistika — UX V2 asosiy menyudagi 6-tugma standarti statistikasi.

    STATISTIKA IZOLYATSIYASI (qat'iy): bu tugma — SHAXSIY hisobot va faqat
    shaxsiy hisobot. Foydalanuvchi ADMIN bo'ladimi yoki oddiy foydalanuvchi
    bo'ladimi, asosiy menyudan «📊 Statistika» bosilganda admin (bot
    bo'yicha) statistikasi — «Jami foydalanuvchilar», «Homiy kanallar»,
    «Bekor qilingan postlar» — HECH QACHON chiqmaydi.

    Admin (bot bo'yicha) statistikasi faqat bitta joydan ochiladi:
    ``⚙️ Admin Panel`` → ``📊 To'liq statistika`` (``adm_stats`` /
    ``handlers.admin.show_statistics``). Shu sababli bu yerda ``ADMIN_IDS``
    tekshiruvi ATAYLAB YO'Q — admin ham o'z shaxsiy hisobotini ko'radi.

    Chiqadigan ekran:
        📊 Sizning statistikangiz:
         📢 Ulangan kanallaringiz: X ta
         📝 Yaratilgan postlaringiz: X ta
         📅 Rejalashtirilgan postlar: X ta
         💎 Qolgan AI kreditlaringiz: X ta
    Amallar: [📈 Kanal bo'yicha batafsil] [◀️ Orqaga].
    """
    return await guard_entry(update, context, show_user_statistics)


async def reaction_callback(update, context):
    query = update.callback_query
    user_id = query.from_user.id

    is_blocked, _ = check_rate_limit(user_id, max_requests=REACTION_RATE_LIMIT_MAX, window_seconds=2.0)
    if is_blocked:
        # 🌐 Rate-limit toast'i foydalanuvchi tilida (uz/ru/en).
        await query.answer(
            get_text("pend_rate_limited", get_lang(context)), show_alert=False
        )
        return

    try:
        await query.answer()
        _, pid_str, emoji = query.data.split(":")
        post_id = int(pid_str)
        counts = await db.run_db(db.toggle_reaction, post_id, user_id, emoji)

        keyboard = []
        for row in query.message.reply_markup.inline_keyboard:
            new_row = []
            for btn in row:
                if btn.callback_data and btn.callback_data.startswith("react:"):
                    _, _, b_emoji = btn.callback_data.split(":")
                    cnt = counts.get(b_emoji, 0)
                    new_label = f"{b_emoji} {cnt}" if cnt > 0 else b_emoji
                    new_row.append(btn.__class__(new_label, callback_data=btn.callback_data))
                else:
                    new_row.append(btn)
            keyboard.append(new_row)
        await query.edit_message_reply_markup(reply_markup=query.message.reply_markup.__class__(keyboard))
    except Exception:
        pass


async def close_msg_callback(update, context):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        try:
            await query.edit_message_text(
                get_text("msg_closed", get_lang(context)), reply_markup=None
            )
        except Exception:
            pass


async def noop_callback(update, context):
    # 🌐 Ma'lumot tugmasi toast'i foydalanuvchi tilida (uz/ru/en).
    await update.callback_query.answer(
        get_text("noop_channel_info", get_lang(context)),
        show_alert=True,
    )


async def expired_session_callback(update, context):
    """Fallback: har qanday eskirgan (masalan, bot qayta ishga tushgandan keyingi)
    inline tugma — foydalanuvchi tilida (uz/ru) qisqa toast ko'rsatiladi.

    Chatda yangi xabar yuborILMAYDI: menyular orasida eski tugma bosilganda
    phantom xabarlar paydo bo'lmasligi uchun faqat callback toast.
    """
    query = update.callback_query
    try:
        await query.answer(get_text("sys_stale_button", get_lang(context)))
    except Exception:
        pass


async def ai_studio_callback(update, context):
    """AI Studio tugmalari uchun GLOBAL ZAXIRA handler (stale presses).

    Asosiy ishlov main_conv ichida (AI_MENU_STATE holati) bajariladi. Bu yerga
    faqat sessiya boshqa oqimda faol bo'lgan eski (stale) studio tugmasi bosilganda
    tushadi. HARDENING: xabar hech qachon O'CHIRILMAYDI — faqat eskirgani haqida
    edit qilinadi.
    """
    query = update.callback_query
    await query.answer()  # speks: har callback boshida darhol answer
    try:
        await query.edit_message_text(
            # 🌐 Eskirgan menyu xabari foydalanuvchi tilida (uz/ru/en).
            get_text("ai_menu_stale", get_lang(context)),
            reply_markup=None,
            parse_mode="HTML",
        )
    except Exception:
        pass


async def ai_photo_stale_callback(update, context):
    """🖼 Vision natijasi tugmalari uchun GLOBAL ZAXIRA handler (stale presses).

    Sessiya tugagach eski [Rejalashtirish]/[Qayta yozish]/[Tahrirlash] tugmasi
    bosilsa — xabar o'chirilmaydi, yo'riqnoma bilan almashtiriladi.
    """
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_text(
            # 🌐 Eskirgan Vision menyu xabari foydalanuvchi tilida (uz/ru/en).
            get_text("ai_photo_stale", get_lang(context)),
            reply_markup=None,
            parse_mode="HTML",
        )
    except Exception:
        pass


# Rasm/hujjat captionidagi `/ai` (yoki `/ai@Bot`) buyrug'i uchun filtr
_AI_CAPTION_FILTER = filters.CaptionRegex(r"(?i)^/ai(?:@[a-z0-9_]+)?(?:\s|$)")


def _is_ai_photo_command(msg) -> bool:
    """Rasm captioni `/ai` (yoki `/ai@Bot`) buyrug'i ekanini aniqlaydi.

    PTB'ning CommandHandler'i faqat `message.text` dagi buyruqlarni taniydi —
    rasm captioni bilan yuborilgan `/ai` ni global photo handler ushlaydi.
    """
    caption = (getattr(msg, "caption", "") or "").strip().lower().split()
    if not caption:
        return False
    cmd = caption[0].split("@")[0]
    return cmd == "/ai"


async def ai_photo_command_callback(update, context):
    """Rasm bilan birga `/ai` buyrug'i yuborilsa — Vision darhol ishlaydi.

    Sho'ng'ish nuqtasi: ConversationHandler boshqa holatda bu rasmni ushlamay
    qolsa, shu yerda vision oqimiga (ai_photo_received) yo'naltiriladi.
    """
    msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
    if msg is None or not _is_ai_photo_command(msg):
        return
    await guard_entry(update, context, ai_photo_received)


# ============================================================
# 🤷 KUTILMAGAN / NOTANISH XABARLAR FALLBACK'I (eng pastki prioritet)
# ============================================================
# PTB semantikasi: bitta guruh ichida faqat BIRINCHI mos kelgan handler ishlaydi.
# Shu sababli fallback ``register_all_handlers`` ning ENG OXIRIDA, 0-guruhga
# qo'shiladi — ConversationHandler (dialog holatlari + menyu sakrashlari),
# buyruqlar, to'lov, rasm handlerlari va boshqalar xabarni tanimagandagina
# navbat unga yetadi. Bu tekshiruv dialog holati O'ZGARMASDAN OLDIN amalga
# oshadi (hammasi bitta ``check_update`` o'tishida), shuning uchun "post
# saqlandi → END" kabi holatlardan keyin ham noto'g'ri ishga tushmaydi.
#
# Qamrov: faqat SHAXSIY chat (guruh/kanalda bot jim turadi), tahrirlangan
# xabarlar va servis (status) xabarlari chetlab o'tiladi. Buyruqlar
# (/nomalum) ham shu yerga tushadi — foydalanuvchiga asosiy menyu ko'rsatiladi.
UNKNOWN_MESSAGE_FILTER = (
    filters.ChatType.PRIVATE
    & ~filters.StatusUpdate.ALL
    & ~filters.SUCCESSFUL_PAYMENT
    & ~filters.UpdateType.EDITED
)

# Bir foydalanuvchiga fallback javobi ko'pi bilan shu oraliqda bir marta
# yuboriladi — voice/kontakt/fayl seriyasi (yoki albom) kelganda har biriga
# alohida "tushunmadim" chiqib spam bo'lmasligi uchun.
UNKNOWN_FALLBACK_COOLDOWN_SEC = 2.0
_UNKNOWN_FALLBACK_LAST: dict = {}
_UNKNOWN_FALLBACK_MAX_KEYS = 20000


def _unknown_fallback_allowed(user_id: int, now: float = None) -> bool:
    """Cooldown: bir foydalanuvchiga ketma-ket fallback javoblari cheklanadi."""
    import time as _time
    now = _time.time() if now is None else now
    if len(_UNKNOWN_FALLBACK_LAST) > _UNKNOWN_FALLBACK_MAX_KEYS:
        _UNKNOWN_FALLBACK_LAST.clear()
    last = _UNKNOWN_FALLBACK_LAST.get(user_id, 0.0)
    if now - last < UNKNOWN_FALLBACK_COOLDOWN_SEC:
        return False
    _UNKNOWN_FALLBACK_LAST[user_id] = now
    return True


def _active_conversation_state(app, update):
    """Foydalanuvchi hozir biror ConversationHandler dialogi ICHIDA bo'lsa —
    uning joriy holatini, aks holda ``None`` qaytaradi.

    PTB ``ConversationHandler`` faol suhbatlarni ``_conversations`` lug'atida
    (kalit: ``_get_key(update)`` → ``(chat_id, user_id)``) saqlaydi. Bu ichki
    atributlar PTB 13–22 oralig'ida barqaror; baribir har ehtimolga qarshi
    himoyalangan — mavjud bo'lmasa "dialogda emas" deb hisoblanadi.
    """
    handlers = getattr(app, "handlers", None) or {}
    try:
        groups = sorted(handlers)
    except Exception:
        groups = list(handlers)
    for group in groups:
        for handler in handlers.get(group) or ():
            if not isinstance(handler, ConversationHandler):
                continue
            try:
                key = handler._get_key(update)
                state = handler._conversations.get(key)
            except Exception:
                continue
            if state is not None:
                return state
    return None


async def unknown_message_fallback(update, context):
    """Eng pastki prioritetli fallback: bot hech qachon JIM qolmaydi.

    * Dialogdan TASHQARIDA (hech qanday ConversationHandler holati yo'q)
      tasodifiy matn, video, kontakt, joylashuv, fayl yoki stiker kelsa —
      foydalanuvchi tilida (uz/ru/en) xushmuomala xabar
      ``unknown_message_fallback`` va ASOSIY reply-menyu yuboriladi.
      (🎙 Ovozli xabar/audio endi bu yerga tushmaydi — ular ``VoiceEntryHandler``
      orqali VOICE → POST STT oqimini boshlaydi: ``handlers/voice_post.py``.)
    * Xom matn post yaratishga yetarli bo'lsa (uzun va so'zlar soni yetarli) —
      ``handlers/content_creation.py`` dagi «✨ Magic Post» taklifi ko'rsatiladi
      (ACTION-FIRST), aks holda oddiy yo'riqnomaviy javob qaytariladi.
    * Dialog ICHIDA bo'lsa-yu, joriy bosqich bu xabar turini qabul qilmasa —
      qisqa ``unknown_in_dialog`` eslatmasi (klaviatura o'zgartirilmaydi,
      dialog buzilmaydi). Bu ovozli xabarlarga ham taalluqli: VoiceEntryHandler
      dialog ichida mos kelmaydi (holat HECH QACHON buzilmaydi).

    Til: avval ``context.user_data['lang']`` keshi, bo'lmasa DB
    (``ensure_user_lang``) — bot qayta ishga tushgandan keyin ham RU
    foydalanuvchi ruscha javob oladi.
    """
    msg = getattr(update, "effective_message", None)
    user = getattr(update, "effective_user", None)
    if msg is None or user is None:
        return None
    user_id = getattr(user, "id", 0) or 0
    if user_id and not _unknown_fallback_allowed(user_id):
        return None
    try:
        from handlers.start import ensure_user_lang
        lang = await ensure_user_lang(context, user_id)
    except Exception:
        lang = get_lang(context)

    app = getattr(context, "application", None)
    in_dialog = _active_conversation_state(app, update) is not None if app is not None else False
    try:
        if in_dialog:
            await msg.reply_text(get_text("unknown_in_dialog", lang), parse_mode="HTML")
        else:
            from keyboards.default import get_main_keyboard
            is_admin = user_id in ADMIN_IDS_SET
            # 🧩 PostAssist V2 · 3-mikro qadam (ACTION-FIRST): foydalanuvchi
            # menyu tashqarisida JO'N matn (post uchun yetarli material) yozsa
            # — avval «✨ Magic Post» taklifi beriladi. Matn saqlanadi va
            # taklif bosilganda to'g'ridan-to'g'ri uslub tanlash ekrani ochiladi.
            # Qisqa/tushunarsiz xabarlar ("???", "/buyruq") uchun esa eski
            # xushmuomala javob + asosiy menyu O'Z KUCHIDA qoladi.
            from handlers.content_creation import offer_magic_post_for_direct_text
            if not await offer_magic_post_for_direct_text(msg, context, user_id, lang):
                await msg.reply_text(
                    get_text("unknown_message_fallback", lang),
                    reply_markup=get_main_keyboard(is_admin, lang=lang),
                    parse_mode="HTML",
                )
    except Exception:
        logger.debug("unknown_message_fallback: javob yuborib bo'lmadi", exc_info=True)
    return None


async def conversation_timeout_handler(update, context):
    is_admin = update.effective_user.id in ADMIN_IDS_SET if update.effective_user else False
    lang = get_lang(context)
    clear_fsm_data(context)
    if update.effective_user:
        cancel_album_collections(update.effective_user.id)
    if update.effective_message:
        try:
            await update.effective_message.reply_text(
                get_text("conv_timeout_msg", lang),
                reply_markup=__import__("keyboards.default", fromlist=["get_main_keyboard"]).get_main_keyboard(is_admin, lang=lang),
                parse_mode="HTML",
            )
        except Exception:
            pass


def _admin_flow_state(text_handler, menu_jumps):
    """Admin inline oqimi uchun standart holat ro'yxati.

    Har bir holatda: menyu sakrashlari, admin inline tugmalari
    (⬅️ Orqaga / ❌ Bekor qilish) va matn qabul qiluvchi handler.
    """
    return menu_jumps + [
        CallbackQueryHandler(admin_dashboard_callback, pattern=r"^adm_"),
        CallbackQueryHandler(ad_pool_callback, pattern=r"^adp:"),
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler),
    ]


def register_all_handlers(app):
    # 🎙 VoiceEntryHandler va 📸 ImageEntryHandler dialog holatini
    # tekshirishi uchun Application havolasi.
    set_voice_application(app)
    set_image_application(app)
    # 🧩 «cc_» taklif tugmalari ham faol dialogni buzmasligi uchun app kerak.
    set_content_creation_application(app)
    # ============================================================
    # QAT'IY NAVIGATSIYA HANDLERLARI RO'YXATI
    # ============================================================
    #
    # 🌐 UCH TILLI ROUTING QOIDASI (uz / ru / en)
    # Har bir pastki (reply) klaviatura tugmasi foydalanuvchi TILIDA
    # chiziladi: UZ "➕ Yangi post" | RU "➕ Новый пост" | EN "➕ New post".
    # Shu sababli quyidagi ``exact(...)`` filtrlar ham AYNAN shu uch matnni
    # tanishi shart — aks holda tugma bosilganda javob "kutilmagan xabar"
    # fallback'iga tushib qoladi.
    #
    # Buning uchun yagona manba — ``keyboards.default.MENU_TEXTS`` registry'i:
    # :func:`keyboards.default.exact` berilgan har bir matnni registry'dagi
    # o'z "tugma oilasi" bilan (uz + ru + en + eski/variant yorliqlar)
    # to'ldiradi. Ya'ni ``exact(BTN_NEW_POST, BTN_NEW_POST_RU)`` yozuvi
    # bugun "➕ New post" ni ham taniydi va yangi til qo'shilganda routing
    # o'zgartirishsiz ham ishlayveradi.
    #
    # Qo'shimcha (zaxira) qatorlar — masalan ``exact(BTN_CANCEL_EN)`` —
    # registry buzilsa ham EN tugmalar ishlashini kafolatlaydi.

    # 1. Start & Navigatsiya
    # Uch tilli routing: har bir reply tugma uz/ru/en variantlari bilan taniladi
    # (klaviatura foydalanuvchi tilida chiziladi — bosilgan tugma hech qachon
    # global fallback'ga tushib ketmasligi kerak).
    start_handlers = [
        # ❌ Bekor qilish — HAR QANDAY holatda FSM'ni to'xtatadi (all_menu_jumps
        # har bir state ro'yxatining boshida turgani uchun hamma joyda ishlaydi).
        # ❌ Bekor qilish / 🔙 Asosiy menyu — uchala tilda ham ishlaydi
        # (klaviatura foydalanuvchi tilida chiziladi).
        MessageHandler(exact(BTN_CANCEL, BTN_CANCEL_RU), cancel_handler),
        MessageHandler(exact(BTN_CANCEL_EN), cancel_handler),
        MessageHandler(exact(BTN_BACK, BTN_MAIN_MENU, BTN_BACK_RU), lambda u, c: guard_menu(u, c, start)),
        MessageHandler(exact(BTN_BACK_EN), lambda u, c: guard_menu(u, c, start)),
        MessageHandler(exact(BTN_SETTINGS, BTN_CABINET, BTN_SETTINGS_RU, BTN_SETTINGS_EN), lambda u, c: guard_menu(u, c, user_cabinet_menu)),
        MessageHandler(exact(BTN_HELP, BTN_HELP_RU, BTN_HELP_EN), lambda u, c: guard_menu(u, c, help_command)),
        MessageHandler(exact(BTN_EXTRAS, BTN_EXTRAS_RU, BTN_EXTRAS_EN), lambda u, c: guard_menu(u, c, extras_menu)),
        # --- Kabinet ichki tugmalari (uz/ru/en) ---
        MessageHandler(exact(BTN_DAILY_BONUS, BTN_DAILY_BONUS_RU), lambda u, c: guard_menu(u, c, daily_bonus_handler)),
        MessageHandler(exact(BTN_DAILY_BONUS_EN), lambda u, c: guard_menu(u, c, daily_bonus_handler)),
        MessageHandler(exact(BTN_INVITE, BTN_INVITE_RU), lambda u, c: guard_menu(u, c, user_invite_menu)),
        MessageHandler(exact(BTN_INVITE_EN), lambda u, c: guard_menu(u, c, user_invite_menu)),
        MessageHandler(exact(BTN_TRANSFER, BTN_TRANSFER_RU), lambda u, c: guard_entry(u, c, start_transfer_credits)),
        MessageHandler(exact(BTN_TRANSFER_EN), lambda u, c: guard_entry(u, c, start_transfer_credits)),
        # 🔄 Ballar o'tkazish — ⚙️ SOZLAMALAR menyusidagi inline tugma
        # (PostAssist V2 · 3-qadam). ``start_handlers`` ichida turgani uchun
        # u bir vaqtning o'zida: (1) main_conv entry point'i, (2) HAR BIR
        # faol holatda menyu sakrashi (all_menu_jumps) va (3) global reyestr
        # handleri. FSM o'zgarmaydi — oqim mavjud TRANSFER_TARGET →
        # TRANSFER_AMOUNT holatlariga kiradi, reply-tugma oqimi ham buzilmaydi.
        CallbackQueryHandler(
            lambda u, c: guard_entry(u, c, transfer_inline_entry),
            pattern=r"^stgs_transfer$",
        ),
    ]

    # 2. Yangi post
    new_post_handlers = [
        MessageHandler(exact(BTN_NEW_POST, BTN_NEW_POST_RU), lambda u, c: guard_entry(u, c, start_new_post)),
        # EN klaviaturadagi "➕ New post" — fallback'ga tushmasligi uchun alohida variant
        MessageHandler(exact(BTN_NEW_POST_EN), lambda u, c: guard_entry(u, c, start_new_post)),
    ]

    # 1b. 🆕 Yangi foydalanuvchi — SODDA (3 tugmali) klaviatura.
    # Bu tugmalar faqat yangi foydalanuvchiga ko'rsatiladi (onboarding.py),
    # lekin handlerlar HAR DOIM ro'yxatda turadi: eski klaviatura xabarlari
    # yoki qo'lda yuborilgan matn ham to'g'ri oqimni ochishi kerak.
    onboarding_handlers = [
        # 🚀 1 daqiqada post yaratish → AI post yozish (AI_PROMPT_INPUT)
        MessageHandler(exact(BTN_QUICK_AI_POST, BTN_QUICK_AI_POST_RU, BTN_QUICK_AI_POST_EN),
                       lambda u, c: guard_entry(u, c, quick_ai_post_entry)),
        # 🖼 Rasmdan post olish → Vision oqimi (AI_PHOTO_INPUT)
        MessageHandler(exact(BTN_QUICK_PHOTO_POST, BTN_QUICK_PHOTO_POST_RU, BTN_QUICK_PHOTO_POST_EN),
                       lambda u, c: guard_entry(u, c, quick_photo_post_entry)),
        # 📢 Kanal ulash → kanal ulash oqimi (ADD_CHANNEL)
        MessageHandler(exact(BTN_QUICK_ADD_CHANNEL, BTN_QUICK_ADD_CHANNEL_RU, BTN_QUICK_ADD_CHANNEL_EN),
                       lambda u, c: guard_entry(u, c, quick_add_channel_entry)),
        # ⚙️ To'liq menyuni ochish → belgi bazaga yoziladi, standart menyu chiqadi
        MessageHandler(exact(BTN_OPEN_FULL_MENU, BTN_OPEN_FULL_MENU_RU, BTN_OPEN_FULL_MENU_EN),
                       lambda u, c: guard_menu(u, c, open_full_menu)),
    ]

    # 3. Kanallar
    channels_handlers = [
        MessageHandler(exact(BTN_CHANNELS, BTN_CHANNELS_RU), lambda u, c: guard_menu(u, c, channels_menu)),
        MessageHandler(exact(BTN_CHANNELS_EN), lambda u, c: guard_menu(u, c, channels_menu)),
        # 🆕 UX V2: "📢 Kanallarim" — asosiy menyu 6-tugma standarti.
        MessageHandler(exact(BTN_MY_CHANNELS, BTN_MY_CHANNELS_RU, BTN_MY_CHANNELS_EN),
                       lambda u, c: guard_menu(u, c, channels_menu)),
        MessageHandler(exact(BTN_ADD_CHANNEL), lambda u, c: guard_entry(u, c, start_add_channel)),
    ]

    # 4. Kutilayotgan postlar
    pending_handlers = [
        MessageHandler(exact(BTN_PENDING, BTN_PENDING_RU), lambda u, c: guard_menu(u, c, list_pending_posts)),
    ]

    # 5. Konverter
    converter_handlers = [
        MessageHandler(exact(BTN_CONVERTER, BTN_CONVERTER_RU), lambda u, c: guard_entry(u, c, start_converter)),
        MessageHandler(exact(BTN_CONVERTER_EN), lambda u, c: guard_entry(u, c, start_converter)),
    ]

    # 6. Admin
    admin_handlers = [
        MessageHandler(exact(BTN_ADMIN_PANEL, BTN_ADMIN_PANEL_RU), lambda u, c: guard_menu(u, c, admin_panel_menu)),
        # 📊 STATISTIKA IZOLYATSIYASI — ikki ekran, ikki alohida yorliq:
        #
        #  1) «📊 Statistika» (BTN_STATISTICS uz/ru/en) — asosiy menyu 6-tugma
        #     standarti. FAQAT shaxsiy hisobot (show_user_statistics); admin
        #     bo'ladimi, oddiy foydalanuvchimi — farqi YO'Q. Admin panel
        #     statistikasi bu yerdan HECH QACHON chiqmaydi.
        MessageHandler(exact(BTN_STATISTICS, BTN_STATISTICS_RU, BTN_STATISTICS_EN),
                       lambda u, c: statistics_button(u, c)),
        #  2) «📊 To'liq statistika» (BTN_FULL_STATS + aliaslari) — FAQAT
        #     ⚙️ Admin Panel ichidagi bot bo'yicha statistika (show_statistics
        #     o'zi ham is_admin() bilan fail-closed).
        MessageHandler(exact(BTN_FULL_STATS, *ADMIN_STATS_ALIASES),
                       lambda u, c: guard_menu(u, c, show_statistics)),
        MessageHandler(exact(BTN_ALL_POSTS), lambda u, c: guard_menu(u, c, admin_all_posts)),
        MessageHandler(exact(BTN_ALL_CHANNELS), lambda u, c: guard_menu(u, c, admin_all_channels)),
        MessageHandler(exact(BTN_BROADCAST), lambda u, c: guard_entry(u, c, broadcast_start)),
        MessageHandler(exact(BTN_SPONSORS), lambda u, c: guard_menu(u, c, sponsors_menu)),
        MessageHandler(exact(BTN_ADD_SPONSOR), lambda u, c: guard_entry(u, c, start_add_sponsor)),
        # UX: ikki alohida reklama tugmasi bitta "🎯 Reklama markazi" hub'iga
        # birlashtirildi. Eski tugma nomlari ham shu yerga tushadi — chat
        # tarixidagi eski klaviatura xabarlari buzilmasligi uchun.
        MessageHandler(exact(BTN_ADS, BTN_CHANNEL_AD, BTN_BOT_REPLY_AD),
                       lambda u, c: guard_entry(u, c, admin_ad_hub_entry)),
        MessageHandler(exact(BTN_POST_TAG), lambda u, c: guard_entry(u, c, start_set_post_tag)),
        MessageHandler(exact(BTN_AI_SETTINGS), lambda u, c: guard_entry(u, c, ai_settings_menu)),
        MessageHandler(exact(BTN_CACHE_DB), lambda u, c: guard_entry(u, c, cache_db_menu)),
    ]

    # 7. AI Studio (inline sub-menu — conversation ICHIDA doimiy navigatsiya)
    # "✨ AI Studio" hozircha uchala tilda ham bir xil matn, lekin EN variant
    # alohida qator sifatida saqlanadi — keyinchalik tarjima farqlansa ham
    # routing buzilmaydi.
    ai_handlers = [
        MessageHandler(exact(BTN_AI_STUDIO, BTN_AI_STUDIO_RU), lambda u, c: guard_entry(u, c, ai_studio_menu_entry)),
        MessageHandler(exact(BTN_AI_STUDIO_EN), lambda u, c: guard_entry(u, c, ai_studio_menu_entry)),
        # 🆕 UX V2: "✨ Kontent yaratish" — asosiy menyu 6-tugma standarti
        # kirish nuqtasi (kontent yaratish markazi = AI Studio oqimi).
        MessageHandler(exact(BTN_CREATE_CONTENT, BTN_CREATE_CONTENT_RU, BTN_CREATE_CONTENT_EN),
                       lambda u, c: guard_entry(u, c, ai_studio_menu_entry)),
    ]

    # 7c. 🧩 KONTENT YARATISH submenu'sining yangi yo'llari (PostAssist V2).
    # Submenu'ning o'zi «✨ Kontent yaratish» / «✨ AI Studio» tugmasi orqali
    # ochiladi (ai_handlers'dagi yuqoridagi qator). Bu yerda faqat submenu'ning
    # 4 TA YANGI yorligi ro'yxatdan o'tadi: ✨ Magic Post va 📸 Rasm → Post
    # tugmalari allaqachon mavjud bo'limlarning o'z yorliqlari bilan bir xil —
    # ular magic_handlers / image_post_handlers qatorlariga tushadi.
    content_creation_handlers = [
        # 📝 Matn → Post — tayyor matnni oddiy (manual) post sifatida chiqarish.
        MessageHandler(exact(BTN_CONTENT_TEXT, BTN_CONTENT_TEXT_RU, BTN_CONTENT_TEXT_EN),
                       lambda u, c: guard_entry(u, c, start_new_post)),
        # 🎙 Ovoz → Post — «ovozli xabar (1 daqiqa ichida)» yo'riqnomasi + STT.
        MessageHandler(exact(BTN_CONTENT_VOICE, BTN_CONTENT_VOICE_RU, BTN_CONTENT_VOICE_EN),
                       lambda u, c: guard_entry(u, c, voice_post_entry)),
        # 🤖 AI Yordamchi — AI Studio bo'limi (matn yozish, qayta yozish,
        # tarjima va g'oya vositalari).
        MessageHandler(exact(BTN_CONTENT_AI, BTN_CONTENT_AI_RU, BTN_CONTENT_AI_EN),
                       lambda u, c: guard_entry(u, c, ai_studio_hub_entry)),
        # ◀️ Orqaga — asosiy 6 tugmali menyuga qaytish (submenu yopiladi).
        MessageHandler(exact(BTN_CONTENT_BACK, BTN_CONTENT_BACK_RU, BTN_CONTENT_BACK_EN),
                       lambda u, c: guard_menu(u, c, content_creation_back)),
    ]

    # 7d. ✨ MAGIC POST — asosiy menyudagi killer feature tugmasi
    # ("✨ Magic Post" brend-nomi uchala tilda bir xil, lekin uchala til
    # konstantasi ham routing'da aniq tanilishi uchun beriladi).
    magic_handlers = [
        MessageHandler(
            exact(BTN_MAGIC_POST, BTN_MAGIC_POST_RU, BTN_MAGIC_POST_EN),
            lambda u, c: guard_entry(u, c, magic_post_entry),
        ),
    ]

    # 7b. 📸 IMAGE → POST — explicit label. Oddiy, legacy photo messages
    # photo_check moderation oqimini buzmasligi uchun global catch-all emas:
    # foydalanuvchi shu bo'limni ochgach rasm yuboradi.
    image_post_handlers = [
        MessageHandler(
            exact(BTN_IMAGE_POST, BTN_IMAGE_POST_RU, BTN_IMAGE_POST_EN),
            lambda u, c: guard_entry(u, c, image_post_entry),
        ),
    ]

    # 7g. 📊 POST SCORE — asosiy menyudagi killer feature #4 tugmasi
    # (baholash BEPUL: kredit/kvota sarflanmaydi; «✨ 95/100 ga yaxshilash»
    # bosilgandagina 1 kredit atomik yechiladi).
    post_score_handlers = [
        MessageHandler(
            exact(BTN_POST_SCORE, BTN_POST_SCORE_RU, BTN_POST_SCORE_EN),
            lambda u, c: guard_entry(u, c, post_score_entry),
        ),
    ]

    # 8. Content Plan
    content_plan_handlers = [
        MessageHandler(exact(BTN_CONTENT_PLAN), lambda u, c: guard_entry(u, c, start_content_plan)),
    ]

    # 9. Analytics
    analytics_handlers = [
        MessageHandler(exact(BTN_ANALYTICS), lambda u, c: guard_entry(u, c, start_analytics)),
    ]

    # 10. Subscription
    # "⭐️ Premium" hozircha uchala tilda ham bir xil matn, lekin EN variant
    # alohida qator sifatida saqlanadi — keyinchalik tarjima farqlansa ham
    # routing buzilmaydi.
    subscription_handlers = [
        MessageHandler(exact(BTN_PREMIUM, BTN_PREMIUM_RU), lambda u, c: guard_entry(u, c, start_subscription)),
        MessageHandler(exact(BTN_PREMIUM_EN), lambda u, c: guard_entry(u, c, start_subscription)),
    ]

    # 11. Channel Extract
    extract_handlers = [
        MessageHandler(exact(BTN_CHANNEL_EXTRACT), lambda u, c: guard_entry(u, c, start_extract)),
    ]

    # 12. Queue
    queue_handlers = [
        MessageHandler(exact(BTN_QUEUE, BTN_QUEUE_RU), lambda u, c: guard_menu(u, c, queue_menu)),
        # 🆕 UX V2: "📅 Rejalashtirilgan" — asosiy menyu 6-tugma standarti.
        MessageHandler(exact(BTN_SCHEDULED, BTN_SCHEDULED_RU, BTN_SCHEDULED_EN),
                       lambda u, c: guard_menu(u, c, queue_menu)),
    ]

    # Barcha menyu sakrashlari
    all_menu_jumps = (
        start_handlers +
        new_post_handlers +
        onboarding_handlers +
        channels_handlers +
        pending_handlers +
        converter_handlers +
        admin_handlers +
        ai_handlers +
        content_creation_handlers +
        magic_handlers +
        image_post_handlers +
        post_score_handlers +
        content_plan_handlers +
        analytics_handlers +
        subscription_handlers +
        extract_handlers +
        queue_handlers
    )

    # ============================================================
    # CONVERSATION HANDLER (Asosiy FSM holatlar boshqaruvi)
    # ============================================================
    main_conv = ConversationHandler(
        entry_points=all_menu_jumps + [
            # 🎙 VOICE → POST: ovozli xabar/audio — dialog TASHQARISIDA ovoz
            # yuborilsa STT oqimi darhol boshlanadi (cheklovlar: FREE ≤60s,
            # PRO ≤180s, ≤20 MB; transkripsiya BEPUL — kredit yechilmaydi).
            # VoiceEntryHandler dialog ICHIDA mos KELMAYDI — ovoz eski xulq
            # bo'yicha unknown_message_fallback'ga tushadi (holat buzilmaydi).
            VoiceEntryHandler(VOICE_MESSAGE_FILTER, voice_message_received),
            # 📸 Oddiy private photo ham Image → Post oqimini boshlaydi.
            # Conversation ichidagi new-post/photo-check holatlari o'zining
            # state handlerlari bilan ustun turadi — legacy oqimlar buzilmaydi.
            ImageEntryHandler(filters.PHOTO & filters.ChatType.PRIVATE, image_photo_received),
            # 🧩 ACTION-FIRST (PostAssist V2, 3-qadam): menyu tashqarisida yozilgan
            # xom matn uchun yuboriladigan «✨ Magic Post» taklifining tugmalari.
            # ContentOfferEntryHandler dialog ICHIDA mos KELMAYDI — faol suhbat
            # holati buzilmaydi; tugma «o'lik» holatda bossa esa oddiy
            # yo'riqnoma ekrani qaytariladi (eski sessiya toast'i chiqmaydi).
            ContentOfferEntryHandler(content_offer_callback, pattern=r"^cc_"),
            CallbackQueryHandler(edit_post_time_start, pattern=r"^p_time:"),
            CallbackQueryHandler(edit_post_content_start, pattern=r"^p_edit:"),
            CallbackQueryHandler(edit_post_btn_start, pattern=r"^p_btn:"),
            CallbackQueryHandler(edit_post_react_start, pattern=r"^p_react:"),
            CallbackQueryHandler(add_channel_inline_entry, pattern=r"^add_channel_start$"),
            # 📢 Kanallarim → [➕ Post yaratish]: kanal ALLAQACHON tanlangan,
            # shuning uchun oqim to'g'ridan-to'g'ri GET_CONTENT holatiga
            # kiradi (entry point bo'lishi SHART — u FSM holati qaytaradi).
            CallbackQueryHandler(channel_new_post_callback, pattern=r"^ch_np:"),
            # 🔁 Qayta tekshirish: sessiya tugagan bo'lsa ham eski tugma
            # ishlasin — conversation qayta ochiladi yoki yo'riqnoma qaytariladi.
            CallbackQueryHandler(add_channel_retry, pattern=r"^add_channel_retry$"),
            # Admin panel inline tugmalari: matn kutuvchi bo'limlar FSM holatini
            # qaytaradi, shuning uchun ular entry point sifatida ro'yxatdan o'tadi.
            CallbackQueryHandler(admin_dashboard_callback, pattern=r"^adm_"),
            CallbackQueryHandler(ad_pool_callback, pattern=r"^adp:"),
            CallbackQueryHandler(converter_inline_entry, pattern=r"^extra_converter$"),
            # ✨ Postga Tugma & Reaksiya qo'shish — ⚙️ Qo'shimcha funksiyalar menyusidan
            CallbackQueryHandler(post_enhancer_start, pattern=r"^extra_enhancer$"),
            # ✨ AI Studio inline entry'lar — sessiya tugagach eski tugma bossa ham
            # conversation qayta ochiladi (menu xabari o'chirilmaydi, edit qilinadi)
            CallbackQueryHandler(
                lambda u, c: guard_entry(u, c, ai_studio_nav_callback),
                pattern=r"^studio_(ai_post|ai_audit|extract|content_plan|ai_photo|close)$",
            ),
            CallbackQueryHandler(
                lambda u, c: guard_entry(u, c, ai_back_to_menu),
                pattern=r"^ai_back_to_menu$",
            ),
            # 🧭 4-qadam: AI Yordamchi → [◀️ Orqaga] → Kontent yaratish
            # submenyusi (eski tugma sessiya tugagach bosilsa ham ishlaydi).
            CallbackQueryHandler(
                lambda u, c: guard_entry(u, c, ai_back_to_content),
                pattern=r"^ai_back_to_content$",
            ),
            CommandHandler("newpost", lambda u, c: guard_entry(u, c, start_new_post)),
            CommandHandler("imagepost", lambda u, c: guard_entry(u, c, image_post_entry)),
            CommandHandler("broadcast", lambda u, c: guard_entry(u, c, broadcast_start)),
            CommandHandler("queue", lambda u, c: guard_menu(u, c, queue_menu)),
        ],
        states={
            # 2. Yangi post holatlari
            CHOOSE_CHANNEL: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, channel_chosen)],
            GET_CONTENT: all_menu_jumps + [
                # 🖼 ALBOM cheklovi tanlovi: albom yig'uvchi (collector) ogohlantirishni
                # GET_CONTENT holatida yuboradi — tanlov callback'lari shu yerda.
                CallbackQueryHandler(album_choice_callback, pattern=r"^album_choice:"),
                MessageHandler(filters.ALL & ~filters.COMMAND, content_received),
            ],
            GET_BTN_TITLE: all_menu_jumps + [
                # 🚀 "⏩ O'tkazib yuborish" — pastki reply-klaviaturadan bosilsa
                # xuddi inline callback kabi xavfsiz keyingi bosqichga o'tadi.
                MessageHandler(filters.Text(SKIP_BUTTON_TEXTS), skip_url_step),
                # 🖼 ALBOM cheklovi tanlovi: albom yuborilganda tugma bosqichida
                # ogohlantirish + [🖼 1-rasm] / [⏩ Tugmalarsiz albom] tugmalari.
                CallbackQueryHandler(album_choice_callback, pattern=r"^album_choice:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, btn_title_received),
                CallbackQueryHandler(ai_action_menu_callback, pattern=r"^ai_menu$"),
                CallbackQueryHandler(ai_action_callback, pattern=r"^ai_act:"),
                CallbackQueryHandler(ai_result_callback, pattern=r"^ai_res:"),
            ],
            GET_BTN_URL: all_menu_jumps + [
                MessageHandler(filters.Text(SKIP_BUTTON_TEXTS), skip_url_step),
                MessageHandler(filters.TEXT & ~filters.COMMAND, btn_url_received),
            ],
            GET_REACTIONS: all_menu_jumps + [
                # 🖼 ALBOM cheklovi tanlovi: albom postida reaksiya bosqichida
                # ogohlantirish + [🖼 1-rasm] / [⏩ Tugmalarsiz albom] tugmalari.
                CallbackQueryHandler(album_choice_callback, pattern=r"^album_choice:"),
                # Multi-select reaksiya (toggle): emoji tanlash + Davom etish / O'tkazib yuborish
                CallbackQueryHandler(reaction_toggle_callback, pattern=r"^nprt:t:"),
                CallbackQueryHandler(reactions_done_callback, pattern=r"^nprt:done$"),
                CallbackQueryHandler(reactions_skip_callback, pattern=r"^nprt:skip$"),
                # 🚀 "⏩ O'tkazib yuborish" — oldingi bosqichdan qolgan reply
                # klaviatura bosilsa ham reaksiyasiz davom etadi (crash yo'q).
                MessageHandler(filters.Text(SKIP_BUTTON_TEXTS), skip_reactions_step),
                MessageHandler(filters.TEXT & ~filters.COMMAND, reactions_received),
                # 🎯 Stiker ham reaksiya sifatida qabul qilinadi: stiker
                # xabari alohida ``handle_reaction_sticker`` handlerga
                # yo'naltiriladi (reactions_received uni delegatsiya qiladi) —
                # stikerning emojisi (message.sticker.emoji) tanlovga
                # qo'shiladi, tasdiq xabari + inline klaviaturada ✅ belgilanadi
                # va reaksiya HECH QACHON post matniga qo'shilmaydi. Stiker
                # filtri TEXT handleridan keyin turadi, lekin stiker matn emas —
                # ikkalasi ham bir-biriga to'sqinlik qilmaydi. Shuning uchun
                # stiker hech qachon global "tushunmadim" fallback'iga
                # tushib ketmaydi.
                MessageHandler(filters.Sticker.ALL, reactions_received),
            ],
            # 2b. ✨ Postga Tugma & Reaksiya qo'shish: post qabul qilish + inline ekranlar
            # (reaksiya/tugma/kanal/tasdiq) — bitta holat, qadamlar user_data'da.
            ENH_POST: all_menu_jumps + [
                CallbackQueryHandler(enh_callback, pattern=r"^enh:"),
                MessageHandler(filters.ALL & ~filters.COMMAND, enh_message_received),
            ],
            GET_AUTO_DELETE: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, auto_delete_received)],
            GET_TIME: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, time_received)],
            DAILY_TIME: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, daily_time_received)],
            RECUR_DAY: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, recur_day_chosen)],
            RECUR_TIME: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, recur_time_received)],
            GET_DURATION: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, duration_chosen)],

            # Confirmation ekran holatlari
            CONFIRM_POST: all_menu_jumps + [
                CallbackQueryHandler(confirm_post_callback, pattern=r"^confirm_post:"),
                MessageHandler(filters.ALL & ~filters.COMMAND, edit_confirm_message_received),
            ],
            EDIT_CONFIRM_FIELD: all_menu_jumps + [
                CallbackQueryHandler(edit_confirm_field_callback, pattern=r"^edit_field:"),
                MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.ANIMATION, edit_confirm_media_received),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_confirm_message_received),
            ],

            # 3. Kanal holatlari
            ADD_CHANNEL: all_menu_jumps + [
                CallbackQueryHandler(add_channel_retry, pattern=r"^add_channel_retry$"),
                MessageHandler(filters.ALL & ~filters.COMMAND, channel_received),
            ],
            SET_TONE: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, tone_chosen)],

            # 8. Content Plan holatlari
            PLAN_CHOOSE_CHANNEL: all_menu_jumps + [
                CallbackQueryHandler(plan_channel_chosen, pattern=r"^plan_ch:"),
                CallbackQueryHandler(plan_view_callback, pattern=r"^plan_cancel$"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_back_to_content, pattern=r"^ai_back_to_content$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
            ],
            PLAN_GET_TOPIC: all_menu_jumps + [
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_back_to_content, pattern=r"^ai_back_to_content$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, plan_topic_received),
            ],
            PLAN_VIEW: all_menu_jumps + [
                CallbackQueryHandler(plan_view_callback, pattern=r"^plan_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_back_to_content, pattern=r"^ai_back_to_content$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
            ],

            # 8b. 🗓 SMART CONTENT CALENDAR holatlari (7/30 kunlik reja).
            # Eslatma: ``cal_cancel`` HAR UCH holatda ham ishlaydi (eski
            # tugma bosilganda ham oqim toza yopiladi, crash bo'lmaydi).
            CALENDAR_BUSINESS: all_menu_jumps + [
                CallbackQueryHandler(calendar_cancel_callback, pattern=r"^cal_cancel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, calendar_business_received),
            ],
            CALENDAR_DURATION: all_menu_jumps + [
                CallbackQueryHandler(calendar_duration_callback, pattern=r"^cal_days:"),
                CallbackQueryHandler(calendar_cancel_callback, pattern=r"^cal_cancel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, calendar_business_received),
            ],
            CALENDAR_VIEW: all_menu_jumps + [
                CallbackQueryHandler(calendar_day_callback, pattern=r"^cal_day:"),
                CallbackQueryHandler(calendar_duration_callback, pattern=r"^cal_days:"),
                CallbackQueryHandler(calendar_cancel_callback, pattern=r"^cal_cancel$"),
            ],

            # 9. Analytics holatlari
            # 📊 Kanal tanlash ro'yxatidagi [◀️ Orqaga] (an_overview) SHAXSIY
            # statistika ekraniga qaytaradi — shu sababli an_close bilan birga
            # ro'yxatdan o'tadi (analytics_view_callback ikkalasini ham biladi).
            ANALYTICS_CHOOSE: all_menu_jumps + [
                CallbackQueryHandler(analytics_channel_chosen, pattern=r"^an_ch:"),
                CallbackQueryHandler(
                    analytics_view_callback, pattern=r"^an_close$|^an_overview$"
                ),
            ],
            ANALYTICS_VIEW: all_menu_jumps + [
                CallbackQueryHandler(analytics_view_callback, pattern=r"^an_"),
            ],

            # 10. Subscription holatlari
            SUBSCRIPTION_VIEW: all_menu_jumps + [
                CallbackQueryHandler(subscription_callback, pattern=r"^sub_"),
            ],
            PROMO_INPUT: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_code_received)],
            # 💳 Karta cheki (rasm/PDF) kutish — Admin Approval Flow
            RECEIPT_WAIT: all_menu_jumps + [
                CallbackQueryHandler(subscription_callback, pattern=r"^sub_"),
                MessageHandler(filters.ALL & ~filters.COMMAND, receipt_received),
            ],

            # 10c. 🖼 Rasm moderatsiyasi (photo_check) — QAT'IY HOLAT
            # Rasm adminga FAQAT shu "Moderatsiya" holatida yuboriladi. Global
            # photo handler (register_photo_check) ichida ham xuddi shu holat/
            # user_data belgisi tekshiriladi — yangi post oqimi, AI Studio yoki
            # boshqa dialogda yuborilgan rasmlar hech qachon adminga bormaydi.
            PHOTO_CHECK_WAIT: all_menu_jumps + [
                MessageHandler(
                    filters.PHOTO & ~filters.COMMAND & ~_AI_CAPTION_FILTER,
                    handle_user_photo,
                ),
            ],

            # 11. Channel Extract holatlari
            EXTRACT_USERNAME: all_menu_jumps + [
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_back_to_content, pattern=r"^ai_back_to_content$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, extract_username_received),
            ],
            EXTRACT_CHOOSE_POST: all_menu_jumps + [
                CallbackQueryHandler(extract_post_chosen, pattern=r"^ext_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_back_to_content, pattern=r"^ai_back_to_content$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
            ],

            # 4. Kutilayotgan postlarni tahrirlash holatlari
            EDIT_POST_TIME: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_post_time_received)],
            EDIT_POST_CONTENT: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_post_content_received)],
            EDIT_POST_BTN: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_post_btn_received)],
            EDIT_POST_REACT: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_post_react_received)],

            # 5. Konverter holati (Maxsus State)
            CONVERT_INPUT: all_menu_jumps + [MessageHandler(filters.ALL & ~filters.COMMAND, converter_received)],

            # 6. Admin holatlari
            TRANSFER_TARGET: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_target_received)],
            TRANSFER_AMOUNT: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_amount_received)],
            BROADCAST_MESSAGE: all_menu_jumps + [
                CallbackQueryHandler(admin_dashboard_callback, pattern=r"^adm_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send),
            ],
            ADD_SPONSOR_CHANNEL: all_menu_jumps + [
                CallbackQueryHandler(admin_dashboard_callback, pattern=r"^adm_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, sponsor_channel_received),
            ],
            SET_CHANNEL_AD: all_menu_jumps + [
                CallbackQueryHandler(ad_pool_callback, pattern=r"^adp:"),
                CallbackQueryHandler(admin_dashboard_callback, pattern=r"^adm_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, channel_ad_received),
            ],
            SET_BOT_REPLY_AD: all_menu_jumps + [
                CallbackQueryHandler(ad_pool_callback, pattern=r"^adp:"),
                CallbackQueryHandler(admin_dashboard_callback, pattern=r"^adm_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot_reply_ad_received),
            ],
            SET_POST_TAG: all_menu_jumps + [
                # 🧭 4-qadam: [⬅️ Orqaga]/[❌ Bekor qilish] (adm_back/adm_cancel)
                # holat ICHIDA ham ishlaydi — FSM to'g'ri yopiladi.
                CallbackQueryHandler(admin_dashboard_callback, pattern=r"^adm_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, post_tag_received)],
            AI_SETTINGS: all_menu_jumps + [
                CallbackQueryHandler(admin_dashboard_callback, pattern=r"^adm_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ai_settings_received)],

            # Admin inline flow holatlari
            ADMIN_GRANT_PRO: _admin_flow_state(admin_inline_text_handler, all_menu_jumps),
            ADMIN_PROMO_CREATE: _admin_flow_state(admin_inline_text_handler, all_menu_jumps),
            ADMIN_SPONSOR_ADD: _admin_flow_state(admin_inline_text_handler, all_menu_jumps),

            # 7. AI Assistant holatlari (Faqat foydalanuvchi AI ga kirganda ishlaydi!)
            AI_INPUT: all_menu_jumps + [MessageHandler(filters.ALL & ~filters.COMMAND, ai_input_received)],
            AI_CONFIRM: all_menu_jumps + [
                CallbackQueryHandler(ai_confirm_callback, pattern=r"^ai_post_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_back_to_content, pattern=r"^ai_back_to_content$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
                MessageHandler(filters.ALL & ~filters.COMMAND, ai_input_received),
            ],
            AI_GET_TIME: all_menu_jumps + [
                MessageHandler(filters.ALL & ~filters.COMMAND, ai_time_received),
                CallbackQueryHandler(ai_confirm_callback, pattern=r"^ai_post_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_back_to_content, pattern=r"^ai_back_to_content$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
            ],

            # 7b. ✨ AI STUDIO inline oqimi (hardering: xabar edit, doimiy nav-tugmalar)
            # AI_MENU_STATE da rasm yuborilsa — Vision (rasmdan post) darhol ishlaydi
            AI_MENU_STATE: all_menu_jumps + [
                CallbackQueryHandler(ai_studio_nav_callback, pattern=r"^studio_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_back_to_content, pattern=r"^ai_back_to_content$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
                MessageHandler(filters.PHOTO | filters.Document.ALL, ai_photo_received),
            ],
            AI_PROMPT_INPUT: all_menu_jumps + [
                CallbackQueryHandler(ai_studio_nav_callback, pattern=r"^studio_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_back_to_content, pattern=r"^ai_back_to_content$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
                MessageHandler(filters.ALL & ~filters.COMMAND, ai_prompt_received),
            ],
            AI_TONE_SELECT: all_menu_jumps + [
                CallbackQueryHandler(ai_tone_callback, pattern=r"^ai_tone:"),
                CallbackQueryHandler(ai_studio_schedule_callback, pattern=r"^ai_studio_sched$"),
                CallbackQueryHandler(ai_studio_nav_callback, pattern=r"^studio_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_back_to_content, pattern=r"^ai_back_to_content$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
                # Yangi mavzu yozilsa — qayta generatsiya
                MessageHandler(filters.ALL & ~filters.COMMAND, ai_prompt_received),
            ],
            AI_AUDIT_INPUT: all_menu_jumps + [
                CallbackQueryHandler(ai_studio_nav_callback, pattern=r"^studio_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_back_to_content, pattern=r"^ai_back_to_content$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
                MessageHandler(filters.ALL & ~filters.COMMAND, ai_audit_received),
            ],

            # 7c. 🖼 AI STUDIO — RASMDAN POST YARATISH (Vision oqimi)
            # AI_MENU_STATE da rasm yuborilsa ham vision darhol ishlaydi
            # (foydalanuvchi /ai dan keyin rasm yuborsa ham).
            AI_PHOTO_INPUT: all_menu_jumps + [
                CallbackQueryHandler(ai_studio_nav_callback, pattern=r"^studio_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_back_to_content, pattern=r"^ai_back_to_content$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
                MessageHandler(filters.ALL & ~filters.COMMAND, ai_photo_received),
            ],
            AI_PHOTO_RESULT: all_menu_jumps + [
                CallbackQueryHandler(ai_photo_result_callback, pattern=r"^photo_"),
                CallbackQueryHandler(ai_studio_nav_callback, pattern=r"^studio_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_back_to_content, pattern=r"^ai_back_to_content$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
                MessageHandler(filters.ALL & ~filters.COMMAND, ai_photo_received),
            ],
            AI_PHOTO_EDIT_INPUT: all_menu_jumps + [
                CallbackQueryHandler(ai_studio_nav_callback, pattern=r"^studio_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_back_to_content, pattern=r"^ai_back_to_content$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
                MessageHandler(filters.PHOTO | filters.Document.ALL, ai_photo_received),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ai_photo_edit_received),
            ],

            # 7d. ✨ MAGIC POST holatlari (Killer Feature #1)
            MAGIC_INPUT: all_menu_jumps + [
                MessageHandler(filters.ALL & ~filters.COMMAND, magic_text_received),
            ],
            MAGIC_STYLE_SELECT: all_menu_jumps + [
                CallbackQueryHandler(magic_style_callback, pattern=r"^mp_style:"),
                CallbackQueryHandler(magic_restyle_callback, pattern=r"^mp_restyle$"),
            ],
            MAGIC_RESULT: all_menu_jumps + [
                CallbackQueryHandler(magic_send_now_callback, pattern=r"^mp_send$"),
                CallbackQueryHandler(magic_schedule_callback, pattern=r"^mp_sched$"),
                CallbackQueryHandler(magic_channel_picked_callback, pattern=r"^mp_ch"),
                CallbackQueryHandler(magic_restyle_callback, pattern=r"^mp_restyle$"),
                # ◀️ Orqaga — Kontent yaratish submenyusiga (sessiya yopiladi).
                CallbackQueryHandler(magic_back_callback, pattern=r"^mp_back$"),
                # 📊 Post Score (Killer Feature #4): natijani baholash va
                # yaxshilash tugmalari shu holatda ham ishlaydi.
                CallbackQueryHandler(post_score_eval_callback, pattern=r"^ps_eval:"),
                CallbackQueryHandler(post_score_improve_callback, pattern=r"^ps_improve$"),
                CallbackQueryHandler(post_score_send_callback, pattern=r"^ps_send$"),
                CallbackQueryHandler(post_score_schedule_callback, pattern=r"^ps_sched$"),
                CallbackQueryHandler(post_score_new_callback, pattern=r"^ps_new$"),
                CallbackQueryHandler(post_score_channel_picked_callback, pattern=r"^ps_ch"),
                # Yangi matn yuborilsa — yangi oqim (eski natija almashtiriladi)
                MessageHandler(filters.ALL & ~filters.COMMAND, magic_text_received),
            ],
            MAGIC_SEND_CHOOSE: all_menu_jumps + [
                CallbackQueryHandler(magic_channel_picked_callback, pattern=r"^mp_ch"),
                CallbackQueryHandler(magic_restyle_callback, pattern=r"^mp_restyle$"),
            ],

            # 7e-0. 🧩 «🎙 Ovoz → Post» bo'limi: ovozli xabar kutiladi.
            # Ovoz kelishi bilan STT oqimi boshlanadi — menyu tashqarisidagi
            # VoiceEntryHandler bilan BITTA handler (voice_message_received),
            # ya'ni ikki kirish yo'li ham bir xil oqimga olib kiradi.
            VOICE_AWAIT: all_menu_jumps + [
                MessageHandler(VOICE_MESSAGE_FILTER, voice_message_received),
            ],

            # 7e. 🎙 VOICE → POST holatlari (Killer Feature — resurs-tejamkor)
            # VOICE_STYLE_SELECT: transkripsiyalangan matn → 5 uslub + ❌ Bekor.
            # Uslub tanlanmaguncha HECH QANDAY kredit/limit yechilmaydi;
            # yangi ovoz kelib qolsa — oqim qaytadan boshlanadi (re-entry).
            VOICE_STYLE_SELECT: all_menu_jumps + [
                CallbackQueryHandler(voice_style_callback, pattern=r"^vp_style:"),
                CallbackQueryHandler(voice_cancel_callback, pattern=r"^vp_cancel$"),
                MessageHandler(VOICE_MESSAGE_FILTER, voice_message_received),
            ],
            VOICE_RESULT: all_menu_jumps + [
                CallbackQueryHandler(voice_send_now_callback, pattern=r"^vp_send$"),
                CallbackQueryHandler(voice_schedule_callback, pattern=r"^vp_sched$"),
                CallbackQueryHandler(voice_restyle_callback, pattern=r"^vp_restyle$"),
                CallbackQueryHandler(voice_cancel_callback, pattern=r"^vp_cancel$"),
                # 📊 Post Score (Killer Feature #4): natijani baholash va
                # yaxshilash tugmalari shu holatda ham ishlaydi.
                CallbackQueryHandler(post_score_eval_callback, pattern=r"^ps_eval:"),
                CallbackQueryHandler(post_score_improve_callback, pattern=r"^ps_improve$"),
                CallbackQueryHandler(post_score_send_callback, pattern=r"^ps_send$"),
                CallbackQueryHandler(post_score_schedule_callback, pattern=r"^ps_sched$"),
                CallbackQueryHandler(post_score_new_callback, pattern=r"^ps_new$"),
                CallbackQueryHandler(post_score_channel_picked_callback, pattern=r"^ps_ch"),
                MessageHandler(VOICE_MESSAGE_FILTER, voice_message_received),
            ],
            VOICE_SEND_CHOOSE: all_menu_jumps + [
                CallbackQueryHandler(voice_channel_picked_callback, pattern=r"^vp_ch"),
                MessageHandler(VOICE_MESSAGE_FILTER, voice_message_received),
            ],

            # 7f. 📸 IMAGE → POST holatlari
            IMAGE_POST_INPUT: all_menu_jumps + [
                MessageHandler(filters.PHOTO | filters.Document.ALL, image_photo_received),
            ],
            # 3-BOSQICH fallback: Vision ishlamadi va caption yo'q — mavzu matni
            # (yoki yangi rasm) kutiladi; jarayon to'xtab qolmaydi.
            IMAGE_TOPIC_INPUT: all_menu_jumps + [
                MessageHandler(filters.PHOTO | filters.Document.ALL, image_photo_received),
                MessageHandler(filters.TEXT & ~filters.COMMAND, image_topic_received),
            ],
            IMAGE_STYLE_SELECT: all_menu_jumps + [
                CallbackQueryHandler(image_style_callback, pattern=r"^(image_style:|img_style:|image_cancel$|img_cancel$)"),
                CallbackQueryHandler(image_cancel_callback, pattern=r"^image_cancel$"),
            ],
            IMAGE_POST_RESULT: all_menu_jumps + [
                CallbackQueryHandler(image_send_callback, pattern=r"^image_send$"),
                CallbackQueryHandler(image_schedule_callback, pattern=r"^image_schedule$"),
                CallbackQueryHandler(image_restyle_callback, pattern=r"^image_restyle$"),
                CallbackQueryHandler(image_back_callback, pattern=r"^image_back$"),
                CallbackQueryHandler(image_cancel_callback, pattern=r"^image_cancel$"),
                # 📊 Post Score (Killer Feature #4): natijani baholash va
                # yaxshilash tugmalari shu holatda ham ishlaydi.
                CallbackQueryHandler(post_score_eval_callback, pattern=r"^ps_eval:"),
                CallbackQueryHandler(post_score_improve_callback, pattern=r"^ps_improve$"),
                CallbackQueryHandler(post_score_send_callback, pattern=r"^ps_send$"),
                CallbackQueryHandler(post_score_schedule_callback, pattern=r"^ps_sched$"),
                CallbackQueryHandler(post_score_new_callback, pattern=r"^ps_new$"),
                CallbackQueryHandler(post_score_channel_picked_callback, pattern=r"^ps_ch"),
            ],
            IMAGE_SEND_CHOOSE: all_menu_jumps + [
                CallbackQueryHandler(image_channel_callback, pattern=r"^image_ch:"),
                CallbackQueryHandler(image_cancel_callback, pattern=r"^image_cancel$"),
            ],
            IMAGE_SCHEDULE_INPUT: all_menu_jumps + [
                MessageHandler(filters.TEXT & ~filters.COMMAND, image_schedule_time_received),
            ],

            # 7h. 📊 POST SCORE holatlari (Killer Feature #4)
            # Baholash BEPUL — kredit/kunlik kvota yechilmaydi; «✨ 95/100 ga
            # yaxshilash» bosilgandagina 1 kredit atomik yechiladi (+refund).
            POST_SCORE_INPUT: all_menu_jumps + [
                MessageHandler(filters.ALL & ~filters.COMMAND, post_score_text_received),
            ],
            POST_SCORE_RESULT: all_menu_jumps + [
                CallbackQueryHandler(post_score_improve_callback, pattern=r"^ps_improve$"),
                CallbackQueryHandler(post_score_send_callback, pattern=r"^ps_send$"),
                CallbackQueryHandler(post_score_schedule_callback, pattern=r"^ps_sched$"),
                CallbackQueryHandler(post_score_new_callback, pattern=r"^ps_new$"),
                CallbackQueryHandler(post_score_eval_callback, pattern=r"^ps_eval:"),
                CallbackQueryHandler(post_score_channel_picked_callback, pattern=r"^ps_ch"),
                # Yangi matn yuborilsa — darhol baholash (yangi sessiya).
                MessageHandler(filters.ALL & ~filters.COMMAND, post_score_text_received),
            ],
            POST_SCORE_SEND_CHOOSE: all_menu_jumps + [
                CallbackQueryHandler(post_score_channel_picked_callback, pattern=r"^ps_ch"),
                CallbackQueryHandler(post_score_new_callback, pattern=r"^ps_new$"),
            ],

            # 8. Queue holatlari
            QUEUE_MENU: all_menu_jumps + [
                CallbackQueryHandler(queue_page_callback, pattern=r"^qpage:"),
                CallbackQueryHandler(queue_view_callback, pattern=r"^qview:"),
                CallbackQueryHandler(queue_delete_callback, pattern=r"^qdel:"),
                # 📅 Rejalashtirilgan post amallari: [✏️ Tahrirlash] va
                # [⏰ Vaqtni o'zgartirish] — mavjud, xavfsiz pending oqimlari
                # (ular entry_points'da ham bor, bu yerda ATAYLAB oshkora).
                CallbackQueryHandler(edit_post_content_start, pattern=r"^p_edit:"),
                CallbackQueryHandler(edit_post_time_start, pattern=r"^p_time:"),
                CallbackQueryHandler(queue_push_callback, pattern=r"^qpush:"),
                # 🔗 [Tugma/Reaksiya] — mavjud `p_btn:` / `p_react:` oqimlari
                # tanlagichi (yangi FSM yaratilmaydi).
                CallbackQueryHandler(scheduled_btn_react_callback, pattern=r"^sched_br:"),
                CallbackQueryHandler(queue_slots_callback, pattern=r"^qslots:"),
                CallbackQueryHandler(queue_close_callback, pattern=r"^qclose$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, slot_add_message),
            ],
            SLOT_ADD: all_menu_jumps + [
                CallbackQueryHandler(queue_slots_callback, pattern=r"^qslots:"),
                CallbackQueryHandler(queue_page_callback, pattern=r"^qpage:"),
                CallbackQueryHandler(queue_close_callback, pattern=r"^qclose$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, slot_add_message),
            ],

            ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, conversation_timeout_handler)],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("cancel", cancel_handler),
            MessageHandler(exact(BTN_CANCEL, BTN_CANCEL_RU), cancel_handler),
            MessageHandler(exact(BTN_CANCEL_EN), cancel_handler),
            MessageHandler(exact(BTN_BACK, BTN_MAIN_MENU, BTN_BACK_RU), lambda u, c: guard_menu(u, c, start)),
            MessageHandler(exact(BTN_BACK_EN), lambda u, c: guard_menu(u, c, start)),
        ],
        allow_reentry=True,
        conversation_timeout=CONVERSATION_TIMEOUT_SEC,
    )

    # 1. Global Buyruqlar
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", user_cabinet_menu))
    # 👤 Profil / Sozlamalar — klaviatura matnini qo'lda yozish o'rniga
    # buyruq orqali ham kabinetga kirish mumkin (uz/ru/en — bitta yo'l).
    app.add_handler(CommandHandler("settings", user_cabinet_menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_panel_menu))
    app.add_handler(CommandHandler("stats", show_statistics))
    app.add_handler(CommandHandler("cancel", cancel_handler))
    app.add_handler(CommandHandler("grant_pro", grant_pro_command))
    app.add_handler(CommandHandler("create_promo", create_promo_command))
    app.add_handler(CommandHandler("admin_stats", admin_stats_command))
    # 📝 6-bosqich: audit jurnali (faqat OWNER/SUPER_ADMIN — RBAC dekoratori)
    app.add_handler(CommandHandler("audit", admin_audit_command))
    # 🩺 7-bosqich: tizim holati (faqat system_settings ruxsati — RBAC dekoratori)
    app.add_handler(CommandHandler("health", health_command))
    # 🎖 6-bosqich: rollarni boshqarish (faqat OWNER — RBAC dekoratori)
    app.add_handler(CommandHandler("setrole", admin_set_role_command))
    app.add_handler(CommandHandler("delrole", admin_del_role_command))
    # 🖼 /ai — AI Studio'ni ochadi; shundan keyin rasm yuborilsa Vision ishlaydi
    app.add_handler(CommandHandler("ai", lambda u, c: guard_entry(u, c, ai_studio_menu_entry)))

    # Stars to'lov handlerlari — Telegram Stars (XTR) to'lovlari uchun.
    # PreCheckoutQuery: foydalanuvchi to'lovni tasdiqlashidan oldin so'raladi.
    # SuccessfulPayment: to'lov muvaffaqiyatli o'tgach PRO tarifni faollashtiramiz.
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    # 2. Asosiy ConversationHandler
    app.add_handler(main_conv)

    # 3. Global menyu handlerlari (Conversation dan tashqarida bo'lsa darhol ishlashi uchun)
    for mh in all_menu_jumps:
        app.add_handler(mh)

    # 4. Inline Callback Handlerlar
    # Subscription (Premium) tugmalari — conversation faol bo'lmasa ham (masalan,
    # suhbat muddati tugagach eski karta tugmalari bosilsa) Stars invoice ochilishi
    # uchun global reyestr. Faol conversation bo'lsa main_conv birinchi ishlaydi.
    app.add_handler(CallbackQueryHandler(subscription_callback, pattern=r"^sub_"))
    app.add_handler(CallbackQueryHandler(converter_callback, pattern=r"^conv_show:"))
    app.add_handler(CallbackQueryHandler(converter_close_callback, pattern=r"^conv_close$"))
    app.add_handler(CallbackQueryHandler(subscription_check_callback, pattern=r"^(check_sub_status|check_subscription)$"))
    app.add_handler(CallbackQueryHandler(del_sponsor_callback, pattern=r"^sp_del:"))
    app.add_handler(CallbackQueryHandler(reaction_callback, pattern=r"^react:"))
    app.add_handler(CallbackQueryHandler(cancel_post_callback, pattern=r"^p_cancel:"))
    app.add_handler(CallbackQueryHandler(refresh_pending_callback, pattern=r"^pending_refresh$"))
    app.add_handler(CallbackQueryHandler(edit_post_content_start, pattern=r"^p_edit:"))
    app.add_handler(CallbackQueryHandler(edit_post_btn_start, pattern=r"^p_btn:"))
    app.add_handler(CallbackQueryHandler(edit_post_react_start, pattern=r"^p_react:"))
    # 📅 YAGONA «📅 Rejalashtirilgan» ro'yxati amallari (PostAssist V2 · 2-qadam,
    # B1): ro'yxat `guard_menu` orqali ochiladi (conversation darhol yopiladi),
    # shuning uchun bu tugmalar GLOBAL ro'yxatda bo'lishi SHART — aks holda
    # [👁 Ko'rish] / [🗑 O'chirish] / [⏩ Surish] eski xabarda "o'lik" bo'lib
    # qolardi. Har bir handler o'zi `query.answer()` qiladi va istisno
    # tashlamaydi (crash yo'q).
    app.add_handler(CallbackQueryHandler(queue_page_callback, pattern=r"^qpage:"))
    app.add_handler(CallbackQueryHandler(queue_view_callback, pattern=r"^qview:"))
    app.add_handler(CallbackQueryHandler(queue_delete_callback, pattern=r"^qdel:"))
    app.add_handler(CallbackQueryHandler(queue_push_callback, pattern=r"^qpush:"))
    app.add_handler(CallbackQueryHandler(queue_slots_callback, pattern=r"^qslots:"))
    app.add_handler(CallbackQueryHandler(queue_close_callback, pattern=r"^qclose$"))
    # 🔗 [Tugma/Reaksiya] tanlagichi: mavjud `p_btn:` / `p_react:` oqimlarini ochadi.
    app.add_handler(CallbackQueryHandler(scheduled_btn_react_callback, pattern=r"^sched_br:"))
    app.add_handler(CallbackQueryHandler(remove_channel_callback, pattern=r"^ch_del:"))
    # 📢 KANALLARIM — kanal boshqaruv ekrani (PostAssist V2, 4-mikro qadam).
    # ``ch_set:`` endi channel_settings_callback orqali o'tadi: kanal
    # boshqaruv ekranidan bosilsa SOZLAMALAR ekranini, eski (chat tarixidagi)
    # tugmadan bosilsa avvalgidek USLUB menyusini ochadi — orqaga moslik
    # buzilmaydi (ichida tone_menu_callback chaqiriladi).
    app.add_handler(CallbackQueryHandler(channel_settings_callback, pattern=r"^ch_set:"))
    app.add_handler(CallbackQueryHandler(channel_open_callback, pattern=r"^ch_op:"))
    app.add_handler(CallbackQueryHandler(channel_scheduled_callback, pattern=r"^ch_sch:"))
    app.add_handler(CallbackQueryHandler(channel_stats_callback, pattern=r"^ch_st:"))
    app.add_handler(CallbackQueryHandler(channels_list_callback, pattern=r"^ch_back$"))
    # 🎙 Kanal ovozi tahlili — kanal ro'yxatidagi profil tugmasi (AI tahlil +
    # natijani kanalning tone_of_voice profiliga saqlaydi).
    app.add_handler(CallbackQueryHandler(
        channel_voice_analysis_callback,
        pattern="^" + re.escape(CB_CHANNEL_VOICE),
    ))
    app.add_handler(CallbackQueryHandler(close_msg_callback, pattern=r"^close_msg$"))
    app.add_handler(CallbackQueryHandler(noop_callback, pattern=r"^noop$"))
    app.add_handler(CallbackQueryHandler(cache_clear_callback, pattern=r"^cache_clear$"))
    app.add_handler(CallbackQueryHandler(admin_dashboard_callback, pattern=r"^adm_"))
    app.add_handler(CallbackQueryHandler(ad_pool_callback, pattern=r"^adp:"))
    app.add_handler(CallbackQueryHandler(ai_studio_callback, pattern=r"^studio_"))
    # AI Studio stale ❌ tugmasi: conversation tashqarisida ham xabar edit qilinadi
    app.add_handler(CallbackQueryHandler(ai_close, pattern=r"^ai_close$"))
    # 🗓 SMART CONTENT CALENDAR stale tugmalari (cal_days: / cal_day: / cal_cancel):
    # sessiya tugagach yoki boshqa oqim ichida bosilsa — «sessiya eskirgan»
    # toast ko'rsatiladi (xabar o'chirilmaydi, hech qanday crash yo'q).
    app.add_handler(CallbackQueryHandler(calendar_stale_callback, pattern=r"^cal_"))
    # ✨ Magic Post stale tugmalari: sessiya tugagach eski natija/tanlov tugmasi
    # bosilsa — foydalanuvchiga «sessiya eskirgan» toast ko'rsatiladi.
    app.add_handler(CallbackQueryHandler(magic_stale_callback, pattern=r"^mp_"))
    # 📊 Post Score — sessiyadan tashqarida bosilgan eski `ps_` tugmalari.
    app.add_handler(CallbackQueryHandler(post_score_stale_callback, pattern=r"^ps_"))
    # 🎙 Voice Post stale tugmalari: sessiya tugagach eski uslub/amal tugmasi
    # bosilsa — foydalanuvchiga «sessiya eskirgan» toast ko'rsatiladi.
    app.add_handler(CallbackQueryHandler(voice_stale_callback, pattern=r"^vp_"))
    # 📸 Image → Post stale tugmalari.
    app.add_handler(CallbackQueryHandler(image_stale_callback, pattern=r"^image_|^img_"))
    # 🖼 Vision natijasi stale tugmalari: sessiya tugagach ham yo'riqnoma ko'rsatadi
    app.add_handler(CallbackQueryHandler(ai_photo_stale_callback, pattern=r"^photo_"))
    # 📷 Qo'lda rasm tekshirish (admin PRO tasdiqlashi): uning callback'i
    # catch-all stale handlerdan, photo handleri esa /ai Vision handleridan
    # oldin ro'yxatdan o'tishi kerak.
    register_photo_check(app)
    # 🖼 Rasm + `/ai` caption: CommandHandler caption'larni tanimaydi — shu yerda
    # rasm bilan birga yuborilgan /ai buyrug'i Vision oqimini ochadi
    # Filtr faqat `/ai` caption bo'lganda mos keladi — aks holda oddiy hujjat/
    # rasm keyingi handlerlarga (jumladan, pastdagi fallback'ga) o'tadi va bot
    # jim qolmaydi.
    app.add_handler(MessageHandler(
        (filters.PHOTO | filters.Document.ALL) & _AI_CAPTION_FILTER,
        ai_photo_command_callback,
    ))
    app.add_handler(CallbackQueryHandler(cabinet_callback, pattern=r"^cab_|^close_cabinet"))
    # ⚙️ SOZLAMALAR (PostAssist V2, 2-bosqich) — 8 guruhli hub:
    # stgs_rewards va stgs_help_hub alohida handler sifatida ro'yxatda;
    # boshqa stgs_* callback'lar hamda eski callback aliaslari generic
    # settings handler orqali xavfsiz yo'naltiriladi.
    app.add_handler(CallbackQueryHandler(
        settings_rewards_callback, pattern=r"^stgs_rewards$",
    ))
    app.add_handler(CallbackQueryHandler(
        settings_help_hub_callback, pattern=r"^stgs_help_hub$",
    ))
    app.add_handler(CallbackQueryHandler(
        settings_menu_callback,
        pattern=r"^(?:stgs_|claim_bonus$|referral_hub$|help_hub$|help_support$)",
    ))
    app.add_handler(CallbackQueryHandler(extras_close_callback, pattern=r"^extra_close$"))
    # 📖 Qo'llanma ichki navigatsiyasi: FAQ ↔ Qo'llanma (uz/ru)
    app.add_handler(CallbackQueryHandler(help_menu_callback, pattern=r"^help:"))
    # ✨ Postga Tugma & Reaksiya: sessiya tugagach eski prevyu/hub tugmalari bosilsa —
    # xabarni buzmasdan jim javob (edit qilinmaydi).
    app.add_handler(CallbackQueryHandler(enh_stale_callback, pattern=r"^enh:"))
    # 💳 Karta cheki Admin Approval Flow — admin ✅/❌ tugmalari. Conversation
    # faol bo'lmasa ham ishlashi uchun global reyestrda ro'yxatdan o'tadi.
    # MUHIM: catch-all ``expired_session_callback`` dan OLDIN turishi kerak —
    # aks holda har qanday bosilmagan tugma kabi admin chek tugmalari ham
    # "eskirgan tugma" toast'iga yutib yuboriladi (✅/❌ ishlamay qoladi).
    app.add_handler(CallbackQueryHandler(
        receipt_admin_callback,
        pattern=r"^(rc_ok|rc_no):",
    ))
    # 📢 Ulangan kanallardan yangi postlarni real vaqtda bazaga yozib borish
    app.add_handler(MessageHandler(
        filters.UpdateType.CHANNEL_POST | filters.UpdateType.EDITED_CHANNEL_POST,
        on_channel_post,
    ))
    app.add_handler(ChatMemberHandler(on_bot_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(expired_session_callback))

    # ============================================================
    # 🤷 ENG PASTKI PRIORITET: kutilmagan / notanish xabarlar fallback'i
    # ============================================================
    # MUHIM: bu handler HAR DOIM ro'yxatning ENG OXIRIDA turishi shart. PTB bir
    # guruhda faqat birinchi mos handlerni ishlatadi — yuqoridagi barcha
    # handlerlar (ConversationHandler holatlari, menyu tugmalari, buyruqlar,
    # rasm/to'lov handlerlari) xabarni tanimagandagina shu yerga tushadi.
    # Yangi handler qo'shsangiz — uni SHU QATORDAN YUQORIGA qo'ying.
    app.add_handler(MessageHandler(UNKNOWN_MESSAGE_FILTER, unknown_message_fallback))
