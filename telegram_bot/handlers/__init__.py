import logging
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ChatMemberHandler,
    filters,
)
from keyboards.default import (
    exact,
    BTN_NEW_POST, BTN_AI_ASSISTANT, BTN_CABINET, BTN_INVITE, BTN_DAILY_BONUS, BTN_BUY_AD_FREE,
    BTN_TRANSFER, BTN_HELP, BTN_ADD_CHANNEL, BTN_CHANNELS, BTN_PENDING, BTN_CONVERTER,
    BTN_ADMIN_PANEL, BTN_STATS, BTN_ALL_POSTS, BTN_ALL_CHANNELS,
    BTN_BROADCAST, BTN_MAIN_MENU, BTN_SPONSORS, BTN_ADD_SPONSOR,
    BTN_CHANNEL_AD, BTN_BOT_REPLY_AD
)
from handlers.start import (
    start, user_cabinet_menu, user_invite_menu, daily_bonus_handler, buy_ad_free_handler,
    ad_free_callback, start_transfer_credits, transfer_target_received, transfer_amount_received,
    help_command, cancel_handler, subscription_check_callback,
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
    remove_channel_callback, on_bot_chat_member_update, ADD_CHANNEL
)
from handlers.converter_2 import (
    start_converter, converter_received, converter_callback, CONVERT_INPUT
)
from handlers.ai_assistant import (
    start_ai_assistant, ai_input_received, ai_confirm_callback, AI_INPUT, AI_CONFIRM
)
from handlers.pending import (
    list_pending_posts, cancel_post_callback,
    edit_post_time_start, edit_post_time_received, EDIT_POST_TIME
)
from handlers.admin import (
    admin_panel_menu, show_statistics, admin_all_posts, admin_all_channels,
    broadcast_start, broadcast_send, sponsors_menu, start_add_sponsor,
    sponsor_channel_received, del_sponsor_callback,
    start_set_channel_ad, channel_ad_received, start_set_bot_reply_ad, bot_reply_ad_received,
    BROADCAST_MESSAGE, ADD_SPONSOR_CHANNEL, SET_CHANNEL_AD, SET_BOT_REPLY_AD
)
import database as db
from utils.helpers import check_rate_limit

logger = logging.getLogger(__name__)

async def guard_entry(update, context, fn):
    user = update.effective_user
    if user:
        is_blocked, should_warn = check_rate_limit(user.id, max_requests=3, window_seconds=3.0)
        if is_blocked:
            if should_warn and update.message:
                await update.message.reply_text("⚠️ <i>Juda ko'p so'rov yubordingiz! Iltimos, 3 soniya kuting...</i>", parse_mode="HTML")
            return ConversationHandler.END
            
    context.user_data.clear()
    return await fn(update, context)

async def guard_menu(update, context, fn):
    user = update.effective_user
    if user:
        is_blocked, should_warn = check_rate_limit(user.id, max_requests=3, window_seconds=3.0)
        if is_blocked:
            if should_warn and update.message:
                await update.message.reply_text("⚠️ <i>Juda ko'p so'rov yubordingiz! Iltimos, 3 soniya kuting...</i>", parse_mode="HTML")
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
        counts = db.toggle_reaction(post_id, user_id, emoji)
        
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

def register_all_handlers(app):
    global_jump_handlers = [
        MessageHandler(exact(BTN_MAIN_MENU), lambda u, c: guard_menu(u, c, start)),
        MessageHandler(exact(BTN_NEW_POST), lambda u, c: guard_entry(u, c, start_new_post)),
        MessageHandler(exact(BTN_AI_ASSISTANT), lambda u, c: guard_entry(u, c, start_ai_assistant)),
        MessageHandler(exact(BTN_CABINET), lambda u, c: guard_menu(u, c, user_cabinet_menu)),
        MessageHandler(exact(BTN_DAILY_BONUS), lambda u, c: guard_menu(u, c, daily_bonus_handler)),
        MessageHandler(exact(BTN_BUY_AD_FREE), lambda u, c: guard_menu(u, c, buy_ad_free_handler)),
        MessageHandler(exact(BTN_INVITE), lambda u, c: guard_menu(u, c, user_invite_menu)),
        MessageHandler(exact(BTN_TRANSFER), lambda u, c: guard_entry(u, c, start_transfer_credits)),
        MessageHandler(exact(BTN_HELP), lambda u, c: guard_menu(u, c, help_command)),
        MessageHandler(exact(BTN_ADD_CHANNEL), lambda u, c: guard_entry(u, c, start_add_channel)),
        MessageHandler(exact(BTN_CHANNELS), lambda u, c: guard_menu(u, c, channels_menu)),
        MessageHandler(exact(BTN_CONVERTER), lambda u, c: guard_entry(u, c, start_converter)),
        MessageHandler(exact(BTN_PENDING), lambda u, c: guard_menu(u, c, list_pending_posts)),
        MessageHandler(exact(BTN_ADMIN_PANEL), lambda u, c: guard_menu(u, c, admin_panel_menu)),
        MessageHandler(exact(BTN_STATS), lambda u, c: guard_menu(u, c, show_statistics)),
        MessageHandler(exact(BTN_ALL_POSTS), lambda u, c: guard_menu(u, c, admin_all_posts)),
        MessageHandler(exact(BTN_ALL_CHANNELS), lambda u, c: guard_menu(u, c, admin_all_channels)),
        MessageHandler(exact(BTN_BROADCAST), lambda u, c: guard_entry(u, c, broadcast_start)),
        MessageHandler(exact(BTN_SPONSORS), lambda u, c: guard_menu(u, c, sponsors_menu)),
        MessageHandler(exact(BTN_ADD_SPONSOR), lambda u, c: guard_entry(u, c, start_add_sponsor)),
        MessageHandler(exact(BTN_CHANNEL_AD), lambda u, c: guard_entry(u, c, start_set_channel_ad)),
        MessageHandler(exact(BTN_BOT_REPLY_AD), lambda u, c: guard_entry(u, c, start_set_bot_reply_ad)),
    ]

    main_conv = ConversationHandler(
        entry_points=[
            MessageHandler(exact(BTN_NEW_POST), lambda u, c: guard_entry(u, c, start_new_post)),
            MessageHandler(exact(BTN_AI_ASSISTANT), lambda u, c: guard_entry(u, c, start_ai_assistant)),
            MessageHandler(exact(BTN_TRANSFER), lambda u, c: guard_entry(u, c, start_transfer_credits)),
            MessageHandler(exact(BTN_ADD_CHANNEL), lambda u, c: guard_entry(u, c, start_add_channel)),
            MessageHandler(exact(BTN_CONVERTER), lambda u, c: guard_entry(u, c, start_converter)),
            MessageHandler(exact(BTN_BROADCAST), lambda u, c: guard_entry(u, c, broadcast_start)),
            MessageHandler(exact(BTN_ADD_SPONSOR), lambda u, c: guard_entry(u, c, start_add_sponsor)),
            MessageHandler(exact(BTN_CHANNEL_AD), lambda u, c: guard_entry(u, c, start_set_channel_ad)),
            MessageHandler(exact(BTN_BOT_REPLY_AD), lambda u, c: guard_entry(u, c, start_set_bot_reply_ad)),
            CallbackQueryHandler(edit_post_time_start, pattern=r"^edit_time:"),
            CommandHandler("newpost", lambda u, c: guard_entry(u, c, start_new_post)),
            CommandHandler("broadcast", lambda u, c: guard_entry(u, c, broadcast_start)),
        ],
        states={
            CHOOSE_CHANNEL: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, channel_chosen)],
            GET_CONTENT: global_jump_handlers + [MessageHandler(filters.ALL & ~filters.COMMAND, content_received)],
            GET_BTN_TITLE: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, btn_title_received)],
            GET_BTN_URL: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, btn_url_received)],
            GET_REACTIONS: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, reactions_received)],
            GET_AUTO_DELETE: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, auto_delete_received)],
            GET_TIME: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, time_received)],
            DAILY_TIME: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, daily_time_received)],
            RECUR_DAY: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, recur_day_chosen)],
            RECUR_TIME: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, recur_time_received)],
            GET_DURATION: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, duration_chosen)],
            ADD_CHANNEL: global_jump_handlers + [MessageHandler(filters.ALL & ~filters.COMMAND, channel_received)],
            CONVERT_INPUT: global_jump_handlers + [MessageHandler(filters.ALL & ~filters.COMMAND, converter_received)],
            AI_INPUT: global_jump_handlers + [MessageHandler(filters.ALL & ~filters.COMMAND, ai_input_received)],
            AI_CONFIRM: global_jump_handlers + [CallbackQueryHandler(ai_confirm_callback, pattern=r"^ai_post_")],
            TRANSFER_TARGET: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_target_received)],
            TRANSFER_AMOUNT: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_amount_received)],
            BROADCAST_MESSAGE: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)],
            ADD_SPONSOR_CHANNEL: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, sponsor_channel_received)],
            SET_CHANNEL_AD: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, channel_ad_received)],
            SET_BOT_REPLY_AD: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, bot_reply_ad_received)],
            EDIT_POST_TIME: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_post_time_received)],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("cancel", cancel_handler),
            MessageHandler(exact(BTN_MAIN_MENU), lambda u, c: guard_menu(u, c, start)),
        ],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", user_cabinet_menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_panel_menu))
    app.add_handler(CommandHandler("stats", show_statistics))
    app.add_handler(main_conv)
    
    # Alohida menyu tugmalari
    app.add_handler(MessageHandler(exact(BTN_CABINET), lambda u, c: guard_menu(u, c, user_cabinet_menu)))
    app.add_handler(MessageHandler(exact(BTN_DAILY_BONUS), lambda u, c: guard_menu(u, c, daily_bonus_handler)))
    app.add_handler(MessageHandler(exact(BTN_BUY_AD_FREE), lambda u, c: guard_menu(u, c, buy_ad_free_handler)))
    app.add_handler(MessageHandler(exact(BTN_INVITE), lambda u, c: guard_menu(u, c, user_invite_menu)))
    app.add_handler(MessageHandler(exact(BTN_HELP), lambda u, c: guard_menu(u, c, help_command)))
    app.add_handler(MessageHandler(exact(BTN_CHANNELS), lambda u, c: guard_menu(u, c, channels_menu)))
    app.add_handler(MessageHandler(exact(BTN_PENDING), lambda u, c: guard_menu(u, c, list_pending_posts)))
    app.add_handler(MessageHandler(exact(BTN_MAIN_MENU), lambda u, c: guard_menu(u, c, start)))
    app.add_handler(MessageHandler(exact(BTN_ADMIN_PANEL), lambda u, c: guard_menu(u, c, admin_panel_menu)))
    app.add_handler(MessageHandler(exact(BTN_STATS), lambda u, c: guard_menu(u, c, show_statistics)))
    app.add_handler(MessageHandler(exact(BTN_ALL_POSTS), lambda u, c: guard_menu(u, c, admin_all_posts)))
    app.add_handler(MessageHandler(exact(BTN_ALL_CHANNELS), lambda u, c: guard_menu(u, c, admin_all_channels)))
    app.add_handler(MessageHandler(exact(BTN_SPONSORS), lambda u, c: guard_menu(u, c, sponsors_menu)))
    
    # Callbacklar
    app.add_handler(CallbackQueryHandler(ad_free_callback, pattern=r"^adfree_"))
    app.add_handler(CallbackQueryHandler(converter_callback, pattern=r"^conv_show:"))
    app.add_handler(CallbackQueryHandler(subscription_check_callback, pattern=r"^check_subscription$"))
    app.add_handler(CallbackQueryHandler(del_sponsor_callback, pattern=r"^del_sponsor:"))
    app.add_handler(CallbackQueryHandler(reaction_callback, pattern=r"^react:"))
    app.add_handler(CallbackQueryHandler(cancel_post_callback, pattern=r"^cancel_post:"))
    app.add_handler(CallbackQueryHandler(remove_channel_callback, pattern=r"^remove_channel:"))
    app.add_handler(ChatMemberHandler(on_bot_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
