import logging
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
    BTN_NEW_POST, BTN_AI_STUDIO, BTN_PENDING, BTN_SETTINGS, BTN_CABINET,
    BTN_HELP, BTN_CONVERTER, BTN_EXTRAS, BTN_BACK, BTN_MAIN_MENU,
    BTN_CHANNELS, BTN_DAILY_BONUS, BTN_BUY_AD_FREE, BTN_INVITE, BTN_TRANSFER,
    BTN_ADMIN_PANEL, BTN_STATS, BTN_ALL_POSTS, BTN_ALL_CHANNELS,
    BTN_BROADCAST, BTN_SPONSORS, BTN_ADD_SPONSOR,
    BTN_CHANNEL_AD, BTN_BOT_REPLY_AD, BTN_POST_TAG, BTN_AI_SETTINGS, BTN_CACHE_DB,
    BTN_ADD_CHANNEL, BTN_QUEUE, BTN_CONTENT_PLAN, BTN_ANALYTICS, BTN_PREMIUM,
    BTN_CHANNEL_EXTRACT,
)
from keyboards.inline import get_subscription_check_keyboard

# 1. START & ASOSIY MODUL
from handlers.start import (
    start, user_cabinet_menu, user_invite_menu, daily_bonus_handler, buy_ad_free_handler,
    ad_free_callback, start_transfer_credits, transfer_target_received, transfer_amount_received,
    help_command, cancel_handler, subscription_check_callback, check_user_subscribed,
    cabinet_callback, extras_menu, extras_close_callback,
    TRANSFER_TARGET, TRANSFER_AMOUNT
)

# 2. NEW POST MODULI
from handlers.new_post import (
    start_new_post, channel_chosen, content_received, btn_title_received,
    btn_url_received, reactions_received, auto_delete_received, time_received,
    daily_time_received, recur_day_chosen, recur_time_received, duration_chosen,
    confirm_post_callback, edit_confirm_field_callback, edit_confirm_message_received,
    edit_confirm_media_received,
    reaction_toggle_callback, reactions_done_callback, reactions_skip_callback,
    quick_button_post_start, quick_btn_content_received,
    ai_action_menu_callback, ai_action_callback, ai_result_callback,
    CHOOSE_CHANNEL, GET_CONTENT, GET_BTN_TITLE, GET_BTN_URL,
    GET_REACTIONS, GET_AUTO_DELETE, GET_TIME, DAILY_TIME, RECUR_DAY, RECUR_TIME,
    GET_DURATION, CONFIRM_POST, EDIT_CONFIRM_FIELD, QUICK_BTN_CONTENT
)

# 3. CHANNELS MODULI
from handlers.channels import (
    channels_menu, start_add_channel, channel_received,
    remove_channel_callback, on_bot_chat_member_update, add_channel_inline_entry,
    tone_menu_callback, tone_chosen,
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
    start_set_channel_ad, channel_ad_received, start_set_bot_reply_ad, bot_reply_ad_received,
    ai_settings_menu, ai_settings_received, cache_db_menu, cache_clear_callback,
    start_set_post_tag, post_tag_received,
    admin_stats_command, admin_dashboard_callback, admin_inline_text_handler,
    ad_pool_callback,
    BROADCAST_MESSAGE, ADD_SPONSOR_CHANNEL, SET_CHANNEL_AD, SET_BOT_REPLY_AD,
    AI_SETTINGS, SET_POST_TAG, ADMIN_GRANT_PRO, ADMIN_PROMO_CREATE,
    ADMIN_SPONSOR_ADD, ADMIN_AD_EDIT, ADMIN_AD_INTERVAL,
)

# 7. AI ASSISTANT + AI STUDIO MODULI (ENG OXIRIDA)
from handlers.ai_assistant import (
    start_ai_assistant, ai_input_received, ai_confirm_callback, ai_time_received,
    ai_studio_menu_entry, ai_studio_nav_callback, ai_prompt_received,
    ai_tone_callback, ai_studio_schedule_callback, ai_audit_received,
    ai_back_to_menu, ai_close,
    AI_INPUT, AI_CONFIRM, AI_GET_TIME,
    AI_MENU_STATE, AI_PROMPT_INPUT, AI_TONE_SELECT, AI_AUDIT_INPUT,
)

# 8. CONTENT PLAN MODULI
from handlers.content_plan import (
    start_content_plan, plan_channel_chosen, plan_topic_received, plan_view_callback,
    PLAN_CHOOSE_CHANNEL, PLAN_GET_TOPIC, PLAN_VIEW
)

# 9. ANALYTICS MODULI
from handlers.analytics import (
    start_analytics, analytics_channel_chosen, analytics_view_callback,
    ANALYTICS_CHOOSE, ANALYTICS_VIEW
)

# 10. SUBSCRIPTION MODULI
from handlers.subscription import (
    start_subscription, subscription_callback, promo_code_received,
    grant_pro_command, create_promo_command,
    precheckout_callback, successful_payment_callback,
    SUBSCRIPTION_VIEW, PROMO_INPUT
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
    QUEUE_MENU, SLOT_ADD,
)

import database as db
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
            "⚠️ <b>Tizim vaqtincha band.</b>\nIltimos, birozdan so'ng /start bosing.",
            parse_mode="HTML",
        )
        return True
    if not is_sub:
        await update.message.reply_text(
            "⚠️ <b>Botdan to'liq foydalanish uchun quyidagi rasmiy kanallarga a'zo bo'ling:</b>",
            reply_markup=get_subscription_check_keyboard(unsubs),
            parse_mode="HTML",
        )
        return True
    return False


async def guard_entry(update, context, fn):
    user = update.effective_user
    if user:
        is_blocked, _ = check_rate_limit(user.id, max_requests=ENTRY_RATE_LIMIT_MAX, window_seconds=2.0)
        if is_blocked:
            if update.message:
                await update.message.reply_text("⏳ Iltimos, biroz kuting...", parse_mode="HTML")
            elif update.callback_query:
                try:
                    await update.callback_query.answer("⏳ Iltimos, biroz kuting...", show_alert=False)
                except Exception:
                    pass
            return ConversationHandler.END

    if await _deny_if_unsubscribed(update, context):
        return ConversationHandler.END

    context.user_data.clear()
    return await fn(update, context)


async def guard_menu(update, context, fn):
    user = update.effective_user
    if user:
        is_blocked, _ = check_rate_limit(user.id, max_requests=NAV_RATE_LIMIT_MAX, window_seconds=2.0)
        if is_blocked:
            if update.message:
                await update.message.reply_text("⏳ Iltimos, biroz kuting...", parse_mode="HTML")
            elif update.callback_query:
                try:
                    await update.callback_query.answer("⏳ Iltimos, biroz kuting...", show_alert=False)
                except Exception:
                    pass
            return ConversationHandler.END

    if await _deny_if_unsubscribed(update, context):
        return ConversationHandler.END

    context.user_data.clear()
    await fn(update, context)
    return ConversationHandler.END


async def reaction_callback(update, context):
    query = update.callback_query
    user_id = query.from_user.id

    is_blocked, _ = check_rate_limit(user_id, max_requests=REACTION_RATE_LIMIT_MAX, window_seconds=2.0)
    if is_blocked:
        await query.answer("⏳ Iltimos, biroz kuting...", show_alert=False)
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
            await query.edit_message_text("✅ Yopildi.", reply_markup=None)
        except Exception:
            pass


async def noop_callback(update, context):
    await update.callback_query.answer(
        "Bu ma'lumot tugmasi. Kanalni o'chirish uchun yonidagi ❌ tugmasini bosing.",
        show_alert=True,
    )


async def expired_session_callback(update, context):
    query = update.callback_query
    # Silent answer — no chat message to avoid phantom "Bu amal allaqachon tugatilgan"
    # when user switches menus and presses stale inline buttons.
    await query.answer()


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
            "⚠️ <b>Bu menyu eskirgan.</b>\n"
            "Davom etish uchun ✨ AI Studio tugmasini qaytadan bosing.",
            reply_markup=None,
            parse_mode="HTML",
        )
    except Exception:
        pass


async def conversation_timeout_handler(update, context):
    is_admin = update.effective_user.id in ADMIN_IDS_SET if update.effective_user else False
    context.user_data.clear()
    if update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⏰ <b>Suhbat muddat tugash sababli yakunlandi.</b>\n"
                "Asosiy menyuga qaytdingiz. Kerakli bo'limni qaytadan tanlang 👇",
                reply_markup=__import__("keyboards.default", fromlist=["get_main_keyboard"]).get_main_keyboard(is_admin),
                parse_mode="HTML",
            )
        except Exception:
            pass


def register_all_handlers(app):
    # ============================================================
    # QAT'IY NAVIGATSIYA HANDLERLARI RO'YXATI
    # ============================================================

    # 1. Start & Navigatsiya
    start_handlers = [
        MessageHandler(exact(BTN_BACK, BTN_MAIN_MENU), lambda u, c: guard_menu(u, c, start)),
        MessageHandler(exact(BTN_SETTINGS, BTN_CABINET), lambda u, c: guard_menu(u, c, user_cabinet_menu)),
        MessageHandler(exact(BTN_HELP), lambda u, c: guard_menu(u, c, help_command)),
        MessageHandler(exact(BTN_EXTRAS), lambda u, c: guard_menu(u, c, extras_menu)),
        MessageHandler(exact(BTN_DAILY_BONUS), lambda u, c: guard_menu(u, c, daily_bonus_handler)),
        MessageHandler(exact(BTN_BUY_AD_FREE), lambda u, c: guard_menu(u, c, buy_ad_free_handler)),
        MessageHandler(exact(BTN_INVITE), lambda u, c: guard_menu(u, c, user_invite_menu)),
        MessageHandler(exact(BTN_TRANSFER), lambda u, c: guard_entry(u, c, start_transfer_credits)),
    ]

    # 2. Yangi post
    new_post_handlers = [
        MessageHandler(exact(BTN_NEW_POST), lambda u, c: guard_entry(u, c, start_new_post)),
    ]

    # 3. Kanallar
    channels_handlers = [
        MessageHandler(exact(BTN_CHANNELS), lambda u, c: guard_menu(u, c, channels_menu)),
        MessageHandler(exact(BTN_ADD_CHANNEL), lambda u, c: guard_entry(u, c, start_add_channel)),
    ]

    # 4. Kutilayotgan postlar
    pending_handlers = [
        MessageHandler(exact(BTN_PENDING), lambda u, c: guard_menu(u, c, list_pending_posts)),
    ]

    # 5. Konverter
    converter_handlers = [
        MessageHandler(exact(BTN_CONVERTER), lambda u, c: guard_entry(u, c, start_converter)),
    ]

    # 6. Admin
    admin_handlers = [
        MessageHandler(exact(BTN_ADMIN_PANEL), lambda u, c: guard_menu(u, c, admin_panel_menu)),
        MessageHandler(exact(BTN_STATS), lambda u, c: guard_menu(u, c, show_statistics)),
        MessageHandler(exact(BTN_ALL_POSTS), lambda u, c: guard_menu(u, c, admin_all_posts)),
        MessageHandler(exact(BTN_ALL_CHANNELS), lambda u, c: guard_menu(u, c, admin_all_channels)),
        MessageHandler(exact(BTN_BROADCAST), lambda u, c: guard_entry(u, c, broadcast_start)),
        MessageHandler(exact(BTN_SPONSORS), lambda u, c: guard_menu(u, c, sponsors_menu)),
        MessageHandler(exact(BTN_ADD_SPONSOR), lambda u, c: guard_entry(u, c, start_add_sponsor)),
        MessageHandler(exact(BTN_CHANNEL_AD), lambda u, c: guard_entry(u, c, start_set_channel_ad)),
        MessageHandler(exact(BTN_BOT_REPLY_AD), lambda u, c: guard_entry(u, c, start_set_bot_reply_ad)),
        MessageHandler(exact(BTN_POST_TAG), lambda u, c: guard_entry(u, c, start_set_post_tag)),
        MessageHandler(exact(BTN_AI_SETTINGS), lambda u, c: guard_entry(u, c, ai_settings_menu)),
        MessageHandler(exact(BTN_CACHE_DB), lambda u, c: guard_entry(u, c, cache_db_menu)),
    ]

    # 7. AI Studio (inline sub-menu — conversation ICHIDA doimiy navigatsiya)
    ai_handlers = [
        MessageHandler(exact(BTN_AI_STUDIO), lambda u, c: guard_entry(u, c, ai_studio_menu_entry)),
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
    subscription_handlers = [
        MessageHandler(exact(BTN_PREMIUM), lambda u, c: guard_entry(u, c, start_subscription)),
    ]

    # 11. Channel Extract
    extract_handlers = [
        MessageHandler(exact(BTN_CHANNEL_EXTRACT), lambda u, c: guard_entry(u, c, start_extract)),
    ]

    # 12. Queue
    queue_handlers = [
        MessageHandler(exact(BTN_QUEUE), lambda u, c: guard_menu(u, c, queue_menu)),
    ]

    # Barcha menyu sakrashlari
    all_menu_jumps = (
        start_handlers +
        new_post_handlers +
        channels_handlers +
        pending_handlers +
        converter_handlers +
        admin_handlers +
        ai_handlers +
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
            CallbackQueryHandler(edit_post_time_start, pattern=r"^edit_time:"),
            CallbackQueryHandler(edit_post_content_start, pattern=r"^edit_content:"),
            CallbackQueryHandler(edit_post_btn_start, pattern=r"^edit_btn:"),
            CallbackQueryHandler(edit_post_react_start, pattern=r"^edit_react:"),
            CallbackQueryHandler(add_channel_inline_entry, pattern=r"^add_channel_start$"),
            CallbackQueryHandler(converter_inline_entry, pattern=r"^extra_converter$"),
            CallbackQueryHandler(quick_button_post_start, pattern=r"^extra_quick_btn$"),
            # ✨ AI Studio inline entry'lar — sessiya tugagach eski tugma bossa ham
            # conversation qayta ochiladi (menu xabari o'chirilmaydi, edit qilinadi)
            CallbackQueryHandler(
                lambda u, c: guard_entry(u, c, ai_studio_nav_callback),
                pattern=r"^studio_(ai_post|ai_audit|extract|content_plan)$",
            ),
            CallbackQueryHandler(
                lambda u, c: guard_entry(u, c, ai_back_to_menu),
                pattern=r"^ai_back_to_menu$",
            ),
            CommandHandler("newpost", lambda u, c: guard_entry(u, c, start_new_post)),
            CommandHandler("broadcast", lambda u, c: guard_entry(u, c, broadcast_start)),
            CommandHandler("queue", lambda u, c: guard_menu(u, c, queue_menu)),
        ],
        states={
            # 2. Yangi post holatlari
            CHOOSE_CHANNEL: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, channel_chosen)],
            GET_CONTENT: all_menu_jumps + [MessageHandler(filters.ALL & ~filters.COMMAND, content_received)],
            GET_BTN_TITLE: all_menu_jumps + [
                MessageHandler(filters.TEXT & ~filters.COMMAND, btn_title_received),
                CallbackQueryHandler(ai_action_menu_callback, pattern=r"^ai_menu$"),
                CallbackQueryHandler(ai_action_callback, pattern=r"^ai_act:"),
                CallbackQueryHandler(ai_result_callback, pattern=r"^ai_res:"),
            ],
            GET_BTN_URL: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, btn_url_received)],
            GET_REACTIONS: all_menu_jumps + [
                # Multi-select reaksiya (toggle): emoji tanlash + Davom etish / O'tkazib yuborish
                CallbackQueryHandler(reaction_toggle_callback, pattern=r"^npreact:tgl:"),
                CallbackQueryHandler(reactions_done_callback, pattern=r"^npreact:done$"),
                CallbackQueryHandler(reactions_skip_callback, pattern=r"^npreact:skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, reactions_received),
            ],
            QUICK_BTN_CONTENT: all_menu_jumps + [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quick_btn_content_received),
                MessageHandler(filters.ALL & ~filters.COMMAND, content_received),
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
            ADD_CHANNEL: all_menu_jumps + [MessageHandler(filters.ALL & ~filters.COMMAND, channel_received)],
            SET_TONE: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, tone_chosen)],

            # 8. Content Plan holatlari
            PLAN_CHOOSE_CHANNEL: all_menu_jumps + [
                CallbackQueryHandler(plan_channel_chosen, pattern=r"^plan_ch:"),
                CallbackQueryHandler(plan_view_callback, pattern=r"^plan_cancel$"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
            ],
            PLAN_GET_TOPIC: all_menu_jumps + [
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, plan_topic_received),
            ],
            PLAN_VIEW: all_menu_jumps + [
                CallbackQueryHandler(plan_view_callback, pattern=r"^plan_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
            ],

            # 9. Analytics holatlari
            ANALYTICS_CHOOSE: all_menu_jumps + [
                CallbackQueryHandler(analytics_channel_chosen, pattern=r"^an_ch:"),
                CallbackQueryHandler(analytics_view_callback, pattern=r"^an_close$"),
            ],
            ANALYTICS_VIEW: all_menu_jumps + [
                CallbackQueryHandler(analytics_view_callback, pattern=r"^an_"),
            ],

            # 10. Subscription holatlari
            SUBSCRIPTION_VIEW: all_menu_jumps + [
                CallbackQueryHandler(subscription_callback, pattern=r"^sub_"),
            ],
            PROMO_INPUT: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_code_received)],

            # 11. Channel Extract holatlari
            EXTRACT_USERNAME: all_menu_jumps + [
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, extract_username_received),
            ],
            EXTRACT_CHOOSE_POST: all_menu_jumps + [
                CallbackQueryHandler(extract_post_chosen, pattern=r"^ext_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
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
            BROADCAST_MESSAGE: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)],
            ADD_SPONSOR_CHANNEL: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, sponsor_channel_received)],
            SET_CHANNEL_AD: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, channel_ad_received)],
            SET_BOT_REPLY_AD: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, bot_reply_ad_received)],
            SET_POST_TAG: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, post_tag_received)],
            AI_SETTINGS: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_settings_received)],

            # Admin inline flow holatlari
            ADMIN_GRANT_PRO: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_inline_text_handler)],
            ADMIN_PROMO_CREATE: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_inline_text_handler)],
            ADMIN_SPONSOR_ADD: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_inline_text_handler)],
            ADMIN_AD_EDIT: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_inline_text_handler)],
            ADMIN_AD_INTERVAL: all_menu_jumps + [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_inline_text_handler)],

            # 7. AI Assistant holatlari (Faqat foydalanuvchi AI ga kirganda ishlaydi!)
            AI_INPUT: all_menu_jumps + [MessageHandler(filters.ALL & ~filters.COMMAND, ai_input_received)],
            AI_CONFIRM: all_menu_jumps + [
                CallbackQueryHandler(ai_confirm_callback, pattern=r"^ai_post_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
                MessageHandler(filters.ALL & ~filters.COMMAND, ai_input_received),
            ],
            AI_GET_TIME: all_menu_jumps + [
                MessageHandler(filters.ALL & ~filters.COMMAND, ai_time_received),
                CallbackQueryHandler(ai_confirm_callback, pattern=r"^ai_post_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
            ],

            # 7b. ✨ AI STUDIO inline oqimi (hardering: xabar edit, doimiy nav-tugmalar)
            AI_MENU_STATE: all_menu_jumps + [
                CallbackQueryHandler(ai_studio_nav_callback, pattern=r"^studio_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
            ],
            AI_PROMPT_INPUT: all_menu_jumps + [
                CallbackQueryHandler(ai_studio_nav_callback, pattern=r"^studio_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
                MessageHandler(filters.ALL & ~filters.COMMAND, ai_prompt_received),
            ],
            AI_TONE_SELECT: all_menu_jumps + [
                CallbackQueryHandler(ai_tone_callback, pattern=r"^ai_tone:"),
                CallbackQueryHandler(ai_studio_schedule_callback, pattern=r"^ai_studio_sched$"),
                CallbackQueryHandler(ai_studio_nav_callback, pattern=r"^studio_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
                # Yangi mavzu yozilsa — qayta generatsiya
                MessageHandler(filters.ALL & ~filters.COMMAND, ai_prompt_received),
            ],
            AI_AUDIT_INPUT: all_menu_jumps + [
                CallbackQueryHandler(ai_studio_nav_callback, pattern=r"^studio_"),
                CallbackQueryHandler(ai_back_to_menu, pattern=r"^ai_back_to_menu$"),
                CallbackQueryHandler(ai_close, pattern=r"^ai_close$"),
                MessageHandler(filters.ALL & ~filters.COMMAND, ai_audit_received),
            ],

            # 8. Queue holatlari
            QUEUE_MENU: all_menu_jumps + [
                CallbackQueryHandler(queue_page_callback, pattern=r"^qpage:"),
                CallbackQueryHandler(queue_view_callback, pattern=r"^qview:"),
                CallbackQueryHandler(queue_delete_callback, pattern=r"^qdel:"),
                CallbackQueryHandler(queue_push_callback, pattern=r"^qpush:"),
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
            MessageHandler(exact(BTN_BACK, BTN_MAIN_MENU), lambda u, c: guard_menu(u, c, start)),
        ],
        allow_reentry=True,
        conversation_timeout=CONVERSATION_TIMEOUT_SEC,
    )

    # 1. Global Buyruqlar
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", user_cabinet_menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_panel_menu))
    app.add_handler(CommandHandler("stats", show_statistics))
    app.add_handler(CommandHandler("cancel", cancel_handler))
    app.add_handler(CommandHandler("grant_pro", grant_pro_command))
    app.add_handler(CommandHandler("create_promo", create_promo_command))
    app.add_handler(CommandHandler("admin_stats", admin_stats_command))

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
    app.add_handler(CallbackQueryHandler(ad_free_callback, pattern=r"^adfree_"))
    app.add_handler(CallbackQueryHandler(converter_callback, pattern=r"^conv_show:"))
    app.add_handler(CallbackQueryHandler(converter_close_callback, pattern=r"^conv_close$"))
    app.add_handler(CallbackQueryHandler(subscription_check_callback, pattern=r"^(check_sub_status|check_subscription)$"))
    app.add_handler(CallbackQueryHandler(del_sponsor_callback, pattern=r"^del_sponsor:"))
    app.add_handler(CallbackQueryHandler(reaction_callback, pattern=r"^react:"))
    app.add_handler(CallbackQueryHandler(cancel_post_callback, pattern=r"^cancel_post:"))
    app.add_handler(CallbackQueryHandler(refresh_pending_callback, pattern=r"^pending_refresh$"))
    app.add_handler(CallbackQueryHandler(edit_post_content_start, pattern=r"^edit_content:"))
    app.add_handler(CallbackQueryHandler(edit_post_btn_start, pattern=r"^edit_btn:"))
    app.add_handler(CallbackQueryHandler(edit_post_react_start, pattern=r"^edit_react:"))
    app.add_handler(CallbackQueryHandler(remove_channel_callback, pattern=r"^remove_channel:"))
    app.add_handler(CallbackQueryHandler(tone_menu_callback, pattern=r"^tone_menu:"))
    app.add_handler(CallbackQueryHandler(close_msg_callback, pattern=r"^close_msg$"))
    app.add_handler(CallbackQueryHandler(noop_callback, pattern=r"^noop$"))
    app.add_handler(CallbackQueryHandler(cache_clear_callback, pattern=r"^cache_clear$"))
    app.add_handler(CallbackQueryHandler(admin_dashboard_callback, pattern=r"^adm_"))
    app.add_handler(CallbackQueryHandler(ad_pool_callback, pattern=r"^adp:"))
    app.add_handler(CallbackQueryHandler(ai_studio_callback, pattern=r"^studio_"))
    # AI Studio stale ❌ tugmasi: conversation tashqarisida ham xabar edit qilinadi
    app.add_handler(CallbackQueryHandler(ai_close, pattern=r"^ai_close$"))
    app.add_handler(CallbackQueryHandler(cabinet_callback, pattern=r"^cab_|^close_cabinet"))
    app.add_handler(CallbackQueryHandler(extras_close_callback, pattern=r"^extra_close$"))
    app.add_handler(ChatMemberHandler(on_bot_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(expired_session_callback))
