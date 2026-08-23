from telegram.ext import Application, CommandHandler

from config import BOT_TOKEN, CHANNEL_ID
from database import init_db
from scheduler import start_scheduler, load_all_posts
from handlers.start import start, help_command
from handlers.new_post import new_post_conversation
from handlers.list_posts import list_posts
from handlers.delete_post import delete_post_command


async def post_init(application: Application):
    start_scheduler()
    load_all_posts(application.bot, CHANNEL_ID)
    print("✅ Scheduler ishga tushdi, mavjud postlar qayta yuklandi.")


def main():
    init_db()

    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("yordam", help_command))
    application.add_handler(new_post_conversation)
    application.add_handler(CommandHandler("royxat", list_posts))
    application.add_handler(CommandHandler("ochir", delete_post_command))

    print("🤖 Bot ishga tushdi...")
    application.run_polling()


if __name__ == "__main__":
    main()
