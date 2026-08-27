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
    BTN_NEW_POST, BTN_ADD_CHANNEL, BTN_CHANNELS, BTN_PENDING,
    BTN_PROFILE, BTN_ADMIN_PANEL, BTN_STATS, BTN_ALL_POSTS,
    BTN_ALL_CHANNELS, BTN_BROADCAST, BTN_MAIN_MENU
)
from handlers.start import start, user_profile, help_command, cancel_handler
from handlers.new_post import (
    start_new_post, channel_chosen, content_received, button_received,
    time_received, recur_day_chosen, recur_time_received,
    CHOOSE_CHANNEL, GET_CONTENT, GET_BUTTON, GET_TIME, RECUR_DAY, RECUR_TIME
)
from handlers.channels import (
    channels_menu, start_add_channel, channel_received,
    remove_channel_callback, on_bot_chat_member_update, ADD_CHANNEL
)
from handlers.pending import list_pending_posts, cancel_post_callback
from handlers.admin import (
    admin_panel_menu, show_statistics, admin_all_posts, admin_all_channels,
    broadcast_start, broadcast_send, BROADCAST_MESSAGE
)

async def _jump_to(update, context, fn):
    context.user_data.clear()
    await fn(update, context)
    return ConversationHandler.END

def register_all_handlers(app):
    global_jump_handlers = [
        MessageHandler(exact(BTN_MAIN_MENU), lambda u, c: _jump_to(u, c, start)),
        MessageHandler(exact(BTN_NEW_POST), start_new_post),
        MessageHandler(exact(BTN_ADD_CHANNEL), start_add_channel),
        MessageHandler(exact(BTN_CHANNELS), lambda u, c: _jump_to(u, c, channels_menu)),
        MessageHandler(exact(BTN_PENDING), lambda u, c: _jump_to(u, c, list_pending_posts)),
        MessageHandler(exact(BTN_PROFILE), lambda u, c: _jump_to(u, c, user_profile)),
        MessageHandler(exact(BTN_ADMIN_PANEL), lambda u, c: _jump_to(u, c, admin_panel_menu)),
        MessageHandler(exact(BTN_STATS), lambda u, c: _jump_to(u, c, show_statistics)),
        MessageHandler(exact(BTN_ALL_POSTS), lambda u, c: _jump_to(u, c, admin_all_posts)),
        MessageHandler(exact(BTN_ALL_CHANNELS), lambda u, c: _jump_to(u, c, admin_all_channels)),
        MessageHandler(exact(BTN_BROADCAST), broadcast_start),
    ]

    main_conv = ConversationHandler(
        entry_points=[
            MessageHandler(exact(BTN_NEW_POST), start_new_post),
            MessageHandler(exact(BTN_ADD_CHANNEL), start_add_channel),
            MessageHandler(exact(BTN_BROADCAST), broadcast_start),
            CommandHandler("newpost", start_new_post),
            CommandHandler("broadcast", broadcast_start),
        ],
        states={
            CHOOSE_CHANNEL: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, channel_chosen)],
            GET_CONTENT: global_jump_handlers + [MessageHandler(filters.ALL & ~filters.COMMAND, content_received)],
            GET_BUTTON: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, button_received)],
            GET_TIME: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, time_received)],
            RECUR_DAY: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, recur_day_chosen)],
            RECUR_TIME: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, recur_time_received)],
            ADD_CHANNEL: global_jump_handlers + [MessageHandler(filters.ALL & ~filters.COMMAND, channel_received)],
            BROADCAST_MESSAGE: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("cancel", cancel_handler),
        ],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", user_profile))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_panel_menu))
    app.add_handler(CommandHandler("stats", show_statistics))

    app.add_handler(main_conv)

    app.add_handler(MessageHandler(exact(BTN_CHANNELS), channels_menu))
    app.add_handler(MessageHandler(exact(BTN_PENDING), list_pending_posts))
    app.add_handler(MessageHandler(exact(BTN_PROFILE), user_profile))
    app.add_handler(MessageHandler(exact(BTN_MAIN_MENU), start))
    app.add_handler(MessageHandler(exact(BTN_ADMIN_PANEL), admin_panel_menu))
    app.add_handler(MessageHandler(exact(BTN_STATS), show_statistics))
    app.add_handler(MessageHandler(exact(BTN_ALL_POSTS), admin_all_posts))
    app.add_handler(MessageHandler(exact(BTN_ALL_CHANNELS), admin_all_channels))

    app.add_handler(CallbackQueryHandler(cancel_post_callback, pattern=r"^cancel_post:"))
    app.add_handler(CallbackQueryHandler(remove_channel_callback, pattern=r"^remove_channel:"))
    app.add_handler(ChatMemberHandler(on_bot_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
