import logging
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ChatMemberHandler,
    filters,
)
from config import ADMIN_ID, ADMIN_IDS_SET
from keyboards.default import (
    exact,
    BTN_NEW_POST, BTN_AI_ASSISTANT, BTN_CABINET, BTN_INVITE, BTN_DAILY_BONUS, BTN_BUY_AD_FREE,
    BTN_TRANSFER, BTN_HELP, BTN_ADD_CHANNEL, BTN_CHANNELS, BTN_PENDING, BTN_CONVERTER,
    BTN_ADMIN_PANEL, BTN_STATS, BTN_ALL_POSTS, BTN_ALL_CHANNELS,
    BTN_BROADCAST, BTN_MAIN_MENU, BTN_SPONSORS, BTN_ADD_SPONSOR,
    BTN_CHANNEL_AD, BTN_BOT_REPLY_AD, BTN_POST_TAG, BTN_AI_SETTINGS, BTN_CACHE_DB,
)
from keyboards.inline import get_subscription_check_keyboard
from handlers.start import (
    start, user_cabinet_menu, user_invite_menu, daily_bonus_handler, buy_ad_free_handler,
    ad_free_callback, start_transfer_credits, transfer_target_received, transfer_amount_received,
    help_command, cancel_handler, subscription_check_callback, check_user_subscribed,
    TRANSFER_TARGET, TRANSFER_AMOUNT
)
from handlers.new_post import (
    start_new_post, channel_chosen, content_received, btn_title_received,
    btn_url_received, reactions_received, auto_delete_received, time_received,
    daily_time_received, recur_day_chosen, recur_time_received, duration_chosen,
    CHOOSE_CHANNEL, GET_CONTENT, GET_BTN_TITLE, GET_BTN_URL,
    GET_REACTIONS, GET_AUTO_DELETE, GET_TIME, DAILY_TIME, RECUR_DAY, RECUR_TIME, GET_DURATION
)
from handlers.channels import (
    channels_menu, start_add_channel, channel_received,
    remove_channel_callback, on_bot_chat_member_update, add_channel_inline_entry, ADD_CHANNEL
)
from handlers.converter import (
    start_converter, converter_received, converter_callback, converter_close_callback, CONVERT_INPUT
)
from handlers.ai_assistant import (
    start_ai_assistant, ai_input_received, ai_confirm_callback, ai_time_received,
    AI_INPUT, AI_CONFIRM, AI_GET_TIME
)
from handlers.pending import (
    list_pending_posts, cancel_post_callback, refresh_pending_callback,
    edit_post_time_start, edit_post_time_received,
    edit_post_content_start, edit_post_content_received,
    edit_post_btn_start, edit_post_btn_received,
    edit_post_react_start, edit_post_react_received,
    EDIT_POST_TIME, EDIT_POST_CONTENT, EDIT_POST_BTN, EDIT_POST_REACT
)
from handlers.admin import (
    admin_panel_menu, show_statistics, admin_all_posts, admin_all_channels,
    broadcast_start, broadcast_send, sponsors_menu, start_add_sponsor,
    sponsor_channel_received, del_sponsor_callback,
    start_set_channel_ad, channel_ad_received, start_set_bot_reply_ad, bot_reply_ad_received,
    ai_settings_menu, ai_settings_received, cache_db_menu, cache_clear_callback,
    start_set_post_tag, post_tag_received,
    BROADCAST_MESSAGE, ADD_SPONSOR_CHANNEL, SET_CHANNEL_AD, SET_BOT_REPLY_AD,
    AI_SETTINGS, SET_POST_TAG
)
import database as db
from utils.helpers import check_rate_limit

logger = logging.getLogger(__name__)

CONVERSATION_TIMEOUT_SEC = 600

# Barcha asosiy menyu va navigatsiya tugmalari — AI suhbatiga tushib ketmasligi
# va har doim birinchi navbatda o'z vazifasini bajarishi uchun to'liq ro'yxat.
_MENU_BUTTON_TEXTS = (
    BTN_NEW_POST, BTN_AI_ASSISTANT, BTN_PENDING, BTN_CABINET, BTN_HELP,
    BTN_ADMIN_PANEL, BTN_MAIN_MENU, BTN_CHANNELS, BTN_CONVERTER, BTN_DAILY_BONUS,
    BTN_BUY_AD_FREE, BTN_INVITE, BTN_TRANSFER, BTN_ADD_CHANNEL, BTN_STATS,
    BTN_BROADCAST, BTN_ALL_POSTS, BTN_ALL_CHANNELS, BTN_SPONSORS, BTN_ADD_SPONSOR,
    BTN_CHANNEL_AD, BTN_BOT_REPLY_AD, BTN_POST_TAG, BTN_AI_SETTINGS, BTN_CACHE_DB,
)


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
            "📢 <b>Botdan to'liq foydalanish uchun quyidagi homiy kanallarga obuna bo'ling:</b>",
            reply_markup=get_subscription_check_keyboard(unsubs),
            parse_mode="HTML",
        )
        return True
    return False


async def guard_entry(update, context, fn):
    """ConversationHandler state'iga kiruvchi funksiyalar uchun tekshiruv."""
    user = update.effective_user
    if user:
        is_blocked, should_warn = check_rate_limit(user.id, max_requests=4, window_seconds=2.0)
        if is_blocked:
            if should_warn and update.message:
                await update.message.reply_text("⚠️ <i>Juda ko'p so'rov yubordingiz! Iltimos, 2 soniya kuting...</i>", parse_mode="HTML")
            return ConversationHandler.END

    if await _deny_if_unsubscribed(update, context):
        return ConversationHandler.END

    context.user_data.clear()
    return await fn(update, context)


async def guard_menu(update, context, fn):
    """Oddiy menyu sahifalarini ko'rsatuvchi funksiyalar uchun tekshiruv."""
    user = update.effective_user
    if user:
        is_blocked, should_warn = check_rate_limit(user.id, max_requests=4, window_seconds=2.0)
        if is_blocked:
            if should_warn and update.message:
                await update.message.reply_text("⚠️ <i>Juda ko'p so'rov yubordingiz! Iltimos, 2 soniya kuting...</i>", parse_mode="HTML")
            return ConversationHandler.END

    if await _deny_if_unsubscribed(update, context):
        return ConversationHandler.END

    context.user_data.clear()
    await fn(update, context)
    return ConversationHandler.END


async def reaction_callback(update, context):
    query = update.callback_query
    user_id = query.from_user.id

    is_blocked, _ = check_rate_limit(user_id, max_requests=3, window_seconds=2.0)
    if is_blocked:
        await query.answer("Iltimos, shoshilmang...", show_alert=False)
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
    """Universal '❌ Yopish' inline tugmasi."""
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
    """Ro'yxatdagi ma'lumot tugmasi bosilganda (hech narsa qilmaydi)."""
    await update.callback_query.answer(
        "Bu ma'lumot tugmasi. Kanalni o'chirish uchun yonidagi ❌ tugmasini bosing.",
        show_alert=True,
    )


async def expired_session_callback(update, context):
    """Suhbat tugagandan keyin eski inline tugma bosilsa — tushunarli javob."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "ℹ️ Bu amal allaqachon tugatilgan. Iltimos, menyudan kerakli bo'limni qayta tanlang yoki /start bosing.",
    )


async def conversation_timeout_handler(update, context):
    """10 daqiqa faolsizlikdan keyin suhbat avtomatik tugaydi."""
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


async def free_chat_entry(update, context):
    """Suhbat tashqarisida kelgan har qanday matn/media — AI intent routing'ga.

    Faqatgina hech qanday menyu tugmasiga to'g'ri kelmagan erkin xabarlar
    uchun ishlaydi.
    """
    user = update.effective_user
    msg = update.message
    if not user or not msg or msg.chat.type != "private":
        return ConversationHandler.END

    is_blocked, should_warn = check_rate_limit(user.id, max_requests=3, window_seconds=3.0)
    if is_blocked:
        if should_warn:
            await msg.reply_text("⚠️ <i>Juda ko'p so'rov yubordingiz! Iltimos, 3 soniya kuting...</i>", parse_mode="HTML")
        return ConversationHandler.END

    if await _deny_if_unsubscribed(update, context):
        return ConversationHandler.END

    is_admin = (user.id in ADMIN_IDS_SET)
    if not is_admin:
        credits = await db.run_db(db.get_user_credits, user.id)
        if credits <= 0:
            bot_obj = await context.bot.get_me()
            from handlers.ai_assistant import _no_credits_text
            await msg.reply_text(
                _no_credits_text(bot_obj.username, user.id),
                parse_mode="HTML",
            )
            return ConversationHandler.END

    return await ai_input_received(update, context)


def register_all_handlers(app):
    # 1. Barcha asosiy menyu navigatsiya handlerlari (bosh menyu va kabinet)
    menu_handlers = [
        MessageHandler(exact(BTN_MAIN_MENU), lambda u, c: guard_menu(u, c, start)),
        MessageHandler(exact(BTN_NEW_POST), lambda u, c: guard_entry(u, c, start_new_post)),
        MessageHandler(exact(BTN_AI_ASSISTANT), lambda u, c: guard_entry(u, c, start_ai_assistant)),
        MessageHandler(exact(BTN_PENDING), lambda u, c: guard_menu(u, c, list_pending_posts)),
        MessageHandler(exact(BTN_CABINET), lambda u, c: guard_menu(u, c, user_cabinet_menu)),
        MessageHandler(exact(BTN_HELP), lambda u, c: guard_menu(u, c, help_command)),
        MessageHandler(exact(BTN_CHANNELS), lambda u, c: guard_menu(u, c, channels_menu)),
        MessageHandler(exact(BTN_ADD_CHANNEL), lambda u, c: guard_entry(u, c, start_add_channel)),
        MessageHandler(exact(BTN_CONVERTER), lambda u, c: guard_entry(u, c, start_converter)),
        MessageHandler(exact(BTN_DAILY_BONUS), lambda u, c: guard_menu(u, c, daily_bonus_handler)),
        MessageHandler(exact(BTN_BUY_AD_FREE), lambda u, c: guard_menu(u, c, buy_ad_free_handler)),
        MessageHandler(exact(BTN_INVITE), lambda u, c: guard_menu(u, c, user_invite_menu)),
        MessageHandler(exact(BTN_TRANSFER), lambda u, c: guard_entry(u, c, start_transfer_credits)),
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

    # 2. Erkin xabarlar — faqat menyu tugmasi bo'lmagan xabarlar uchun ENG OXIRGI filtr
    free_chat_entries = [
        MessageHandler(
            filters.ChatType.PRIVATE
            & ~filters.COMMAND
            & ~exact(*_MENU_BUTTON_TEXTS)
            & (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL
               | filters.AUDIO | filters.VOICE | filters.ANIMATION | filters.FORWARDED),
            free_chat_entry,
        ),
    ]

    # 3. Asosiy ConversationHandler
    main_conv = ConversationHandler(
        entry_points=menu_handlers + [
            CallbackQueryHandler(edit_post_time_start, pattern=r"^edit_time:"),
            CallbackQueryHandler(edit_post_content_start, pattern=r"^edit_content:"),
            CallbackQueryHandler(edit_post_btn_start, pattern=r"^edit_btn:"),
            CallbackQueryHandler(edit_post_react_start, pattern=r"^edit_react:"),
            CallbackQueryHandler(add_channel_inline_entry, pattern=r"^add_channel_start$"),
            CommandHandler("newpost", lambda u, c: guard_entry(u, c, start_new_post)),
            CommandHandler("broadcast", lambda u, c: guard_entry(u, c, broadcast_start)),
        ] + free_chat_entries,
        states={
            CHOOSE_CHANNEL: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, channel_chosen)],
            GET_CONTENT: menu_handlers + [MessageHandler(filters.ALL & ~filters.COMMAND, content_received)],
            GET_BTN_TITLE: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, btn_title_received)],
            GET_BTN_URL: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, btn_url_received)],
            GET_REACTIONS: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, reactions_received)],
            GET_AUTO_DELETE: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, auto_delete_received)],
            GET_TIME: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, time_received)],
            DAILY_TIME: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, daily_time_received)],
            RECUR_DAY: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, recur_day_chosen)],
            RECUR_TIME: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, recur_time_received)],
            GET_DURATION: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, duration_chosen)],
            ADD_CHANNEL: menu_handlers + [MessageHandler(filters.ALL & ~filters.COMMAND, channel_received)],
            CONVERT_INPUT: menu_handlers + [MessageHandler(filters.ALL & ~filters.COMMAND, converter_received)],
            AI_INPUT: menu_handlers + [MessageHandler(filters.ALL & ~filters.COMMAND, ai_input_received)],
            AI_CONFIRM: menu_handlers + [
                CallbackQueryHandler(ai_confirm_callback, pattern=r"^ai_post_"),
                MessageHandler(filters.ALL & ~filters.COMMAND, ai_input_received),
            ],
            AI_GET_TIME: menu_handlers + [
                MessageHandler(filters.ALL & ~filters.COMMAND, ai_time_received),
                CallbackQueryHandler(ai_confirm_callback, pattern=r"^ai_post_"),
            ],
            TRANSFER_TARGET: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_target_received)],
            TRANSFER_AMOUNT: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_amount_received)],
            BROADCAST_MESSAGE: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)],
            ADD_SPONSOR_CHANNEL: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, sponsor_channel_received)],
            SET_CHANNEL_AD: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, channel_ad_received)],
            SET_BOT_REPLY_AD: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, bot_reply_ad_received)],
            SET_POST_TAG: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, post_tag_received)],
            AI_SETTINGS: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_settings_received)],
            EDIT_POST_TIME: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_post_time_received)],
            EDIT_POST_CONTENT: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_post_content_received)],
            EDIT_POST_BTN: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_post_btn_received)],
            EDIT_POST_REACT: menu_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_post_react_received)],
            ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, conversation_timeout_handler)],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("cancel", cancel_handler),
            MessageHandler(exact(BTN_MAIN_MENU), lambda u, c: guard_menu(u, c, start)),
        ],
        allow_reentry=True,
        conversation_timeout=CONVERSATION_TIMEOUT_SEC,
    )

    # 4. Global Command Handlerlar
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", user_cabinet_menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_panel_menu))
    app.add_handler(CommandHandler("stats", show_statistics))
    app.add_handler(CommandHandler("cancel", cancel_handler))

    # 5. ConversationHandler ro'yxatdan o'tadi
    app.add_handler(main_conv)

    # 6. Global menyu handlerlari (ConversationHandler dan tashqari holatlar uchun)
    for mh in menu_handlers:
        app.add_handler(mh)

    # 7. CallbackQuery Handlerlar
    app.add_handler(CallbackQueryHandler(ad_free_callback, pattern=r"^adfree_"))
    app.add_handler(CallbackQueryHandler(converter_callback, pattern=r"^conv_show:"))
    app.add_handler(CallbackQueryHandler(converter_close_callback, pattern=r"^conv_close$"))
    app.add_handler(CallbackQueryHandler(subscription_check_callback, pattern=r"^check_subscription$"))
    app.add_handler(CallbackQueryHandler(del_sponsor_callback, pattern=r"^del_sponsor:"))
    app.add_handler(CallbackQueryHandler(reaction_callback, pattern=r"^react:"))
    app.add_handler(CallbackQueryHandler(cancel_post_callback, pattern=r"^cancel_post:"))
    app.add_handler(CallbackQueryHandler(refresh_pending_callback, pattern=r"^pending_refresh$"))
    app.add_handler(CallbackQueryHandler(edit_post_content_start, pattern=r"^edit_content:"))
    app.add_handler(CallbackQueryHandler(edit_post_btn_start, pattern=r"^edit_btn:"))
    app.add_handler(CallbackQueryHandler(edit_post_react_start, pattern=r"^edit_react:"))
    app.add_handler(CallbackQueryHandler(remove_channel_callback, pattern=r"^remove_channel:"))
    app.add_handler(CallbackQueryHandler(close_msg_callback, pattern=r"^close_msg$"))
    app.add_handler(CallbackQueryHandler(noop_callback, pattern=r"^noop$"))
    app.add_handler(CallbackQueryHandler(cache_clear_callback, pattern=r"^cache_clear$"))
    app.add_handler(ChatMemberHandler(on_bot_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(expired_session_callback))
