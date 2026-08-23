from datetime import datetime, date
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from database import get_active_posts, deactivate_post

scheduler = AsyncIOScheduler()


async def _send_and_maybe_deactivate(bot, channel_id, post_id, text, one_time,
                                      media_type=None, media_file_id=None):
    try:
        if media_type == "photo":
            await bot.send_photo(chat_id=channel_id, photo=media_file_id, caption=text or None)
        elif media_type == "video":
            await bot.send_video(chat_id=channel_id, video=media_file_id, caption=text or None)
        elif media_type == "document":
            await bot.send_document(chat_id=channel_id, document=media_file_id, caption=text or None)
        else:
            await bot.send_message(chat_id=channel_id, text=text)
        print(f"[YUBORILDI] post_id={post_id}")
    except Exception as e:
        print(f"[XATOLIK] Xabar yuborishda muammo (post_id={post_id}): {e}")
        return
    if one_time:
        deactivate_post(post_id)


def schedule_post(bot, channel_id, post):
    """Bitta postni scheduler'ga qo'shadi (yoki qayta yuklaydi)."""
    job_id = f"post_{post['id']}"
    hour, minute = map(int, post["send_time"].split(":"))
    media_type = post.get("media_type")
    media_file_id = post.get("media_file_id")

    if post["post_type"] == "once":
        y, m, d = map(int, post["send_date"].split("-"))
        run_date = datetime(y, m, d, hour, minute)
        if run_date < datetime.now():
            return  # sana allaqachon o'tib ketgan, o'tkazib yuboramiz
        scheduler.add_job(
            _send_and_maybe_deactivate,
            trigger=DateTrigger(run_date=run_date),
            args=[bot, channel_id, post["id"], post["text"], True, media_type, media_file_id],
            id=job_id,
            replace_existing=True,
        )
    else:  # daily
        kwargs = {"hour": hour, "minute": minute}
        if post.get("end_date"):
            y, m, d = map(int, post["end_date"].split("-"))
            kwargs["end_date"] = date(y, m, d)
        scheduler.add_job(
            _send_and_maybe_deactivate,
            trigger=CronTrigger(**kwargs),
            args=[bot, channel_id, post["id"], post["text"], False, media_type, media_file_id],
            id=job_id,
            replace_existing=True,
        )


def remove_job(post_id):
    job_id = f"post_{post_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


def load_all_posts(bot, channel_id):
    """Bot qayta ishga tushganda barcha faol postlarni qayta yuklaydi."""
    for post in get_active_posts():
        schedule_post(bot, channel_id, post)


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
