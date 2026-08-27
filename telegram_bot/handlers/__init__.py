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
    BTN_ALL_CHANNELS, BTN_BROADCAST, BTN_MAIN_MENU,
    BTN_SPONSORS, BTN_ADD_SPONSOR, BTN_GLOBAL_AD
)
from handlers.start import start, user_profile, help_command, cancel_handler, subscription_check_callback
from handlers.new_post import (
    start_new_post, channel_chosen, content_received, button_received,
    reactions_received, time_received, recur_day_chosen, recur_time_received,
    CHOOSE_CHANNEL, GET_CONTENT, GET_BUTTON, GET_REACTIONS, GET_TIME, RECUR_DAY, RECUR_TIME
)
from handlers.channels import (
    channels_menu, start_add_channel, channel_received,
    remove_channel_callback, on_bot_chat_member_update, ADD_CHANNEL
)
from handlers.pending import list_pending_posts, cancel_post_callback
from handlers.admin import (
    admin_panel_menu, show_statistics, admin_all_posts, admin_all_channels,
    broadcast_start, broadcast_send, sponsors_menu, start_add_sponsor,
    sponsor_channel_received, del_sponsor_callback, start_set_ad,
    ad_text_received, BROADCAST_MESSAGE, ADD_SPONSOR_CHANNEL, SET_AD_TEXT
)
import database as db

async def _jump_to(update, context, fn):
    context.user_data.clear()
    await fn(update, context)
    return ConversationHandler.END

async def reaction_callback(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    try:
        _, pid_str, emoji = query.data.split(":")
        post_id = int(pid_str)
        counts = db.toggle_reaction(post_id, user_id, emoji)
        
        # Tugmalarni yangilash
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
        await query.answer(f"Siz {emoji} reaksiyasini qoldirdingiz!")
    except Exception:
        await query.answer()

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
        MessageHandler(exact(BTN_SPONSORS), lambda u, c: _jump_to(u, c, sponsors_menu)),
        MessageHandler(exact(BTN_ADD_SPONSOR), start_add_sponsor),
        MessageHandler(exact(BTN_GLOBAL_AD), start_set_ad),
    ]

    main_conv = ConversationHandler(
        entry_points=[
            MessageHandler(exact(BTN_NEW_POST), start_new_post),
            MessageHandler(exact(BTN_ADD_CHANNEL), start_add_channel),
            MessageHandler(exact(BTN_BROADCAST), broadcast_start),
            MessageHandler(exact(BTN_ADD_SPONSOR), start_add_sponsor),
            MessageHandler(exact(BTN_GLOBAL_AD), start_set_ad),
            CommandHandler("newpost", start_new_post),
            CommandHandler("broadcast", broadcast_start),
        ],
        states={
            CHOOSE_CHANNEL: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, channel_chosen)],
            GET_CONTENT: global_jump_handlers + [MessageHandler(filters.ALL & ~filters.COMMAND, content_received)],
            GET_BUTTON: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, button_received)],
            GET_REACTIONS: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, reactions_received)],
            GET_TIME: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, time_received)],
            RECUR_DAY: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, recur_day_chosen)],
            RECUR_TIME: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, recur_time_received)],
            ADD_CHANNEL: global_jump_handlers + [MessageHandler(filters.ALL & ~filters.COMMAND, channel_received)],
            BROADCAST_MESSAGE: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)],
            ADD_SPONSOR_CHANNEL: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, sponsor_channel_received)],
            SET_AD_TEXT: global_jump_handlers + [MessageHandler(filters.TEXT & ~filters.COMMAND, ad_text_received)],
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
    app.add_handler(MessageHandler(exact(BTN_SPONSORS), sponsors_menu))

    app.add_handler(CallbackQueryHandler(subscription_check_callback, pattern=r"^check_subscription$"))
    app.add_handler(CallbackQueryHandler(del_sponsor_callback, pattern=r"^del_sponsor:"))
    app.add_handler(CallbackQueryHandler(reaction_callback, pattern=r"^react:"))
    app.add_handler(CallbackQueryHandler(cancel_post_callback, pattern=r"^cancel_post:"))
    app.add_handler(CallbackQueryHandler(remove_channel_callback, pattern=r"^remove_channel:"))
    app.add_handler(ChatMemberHandler(on_bot_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
