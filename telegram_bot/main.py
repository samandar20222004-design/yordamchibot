import logging
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)
from config import BOT_TOKEN
from database import init_db
from scheduler import start_scheduler
from handlers import (
    start_command,
    list_channels_handler,
    add_channel_start,
    add_channel_process,
    WAITING_CHANNEL_FORWARD,
    new_post_start,
    choose_channel_step,
    post_content_step,
    post_time_step,
    confirm_post_step,
    cancel_handler,
    CHOOSE_CHANNEL,
    POST_CONTENT,
    POST_TIME,
    CONFIRM_POST,
    list_posts_command,
    delete_post_start,
    delete_post_process,
    WAIT_DELETE_ID,
    admin_panel_handler,
    broadcast_start,
    broadcast_send,
    ADMIN_BROADCAST_STATE
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

def main():
    init_db()
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Broadcast (Admin)
    broadcast_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 Barchaga xabar yuborish$"), broadcast_start)],
        states={
            ADMIN_BROADCAST_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)]
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)]
    )

    # Kanal qo'shish
    channel_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^➕ Kanal ulash$"), add_channel_start),
            CommandHandler("addchannel", add_channel_start)
        ],
        states={
            WAITING_CHANNEL_FORWARD: [MessageHandler(filters.ALL & ~filters.COMMAND, add_channel_process)]
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)]
    )

    # Post yaratish
    post_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^➕ Yangi post yaratish$"), new_post_start),
            CommandHandler("newpost", new_post_start)
        ],
        states={
            CHOOSE_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_channel_step)],
            POST_CONTENT: [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, post_content_step)],
            POST_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, post_time_step)],
            CONFIRM_POST: [MessageHandler(filters.Regex("^(✅ Tasdiqlash|❌ Bekor qilish)$"), confirm_post_step)]
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)]
    )

    # Post o'chirish
    delete_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^❌ Postni o'chirish$"), delete_post_start),
            CommandHandler("deletepost", delete_post_start)
        ],
        states={
            WAIT_DELETE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_post_process)]
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)]
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.Regex("^🔙 Asosiy menyu$"), start_command))
    app.add_handler(MessageHandler(filters.Regex("^📢 Kanallarim$"), list_channels_handler))
    app.add_handler(MessageHandler(filters.Regex("^📋 Rejalashtirilgan postlar$"), list_posts_command))
    app.add_handler(MessageHandler(filters.Regex("^👑 Admin Panel$"), admin_panel_handler))
    
    app.add_handler(broadcast_conv)
    app.add_handler(channel_conv)
    app.add_handler(post_conv)
    app.add_handler(delete_conv)

    start_scheduler(app.bot)

    print("Universal Telegram bot muvaffaqiyatli ishga tushdi...")
    app.run_polling()

if __name__ == "__main__":
    main()
