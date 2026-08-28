import logging
from datetime import datetime, timedelta
from typing import Optional
import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
import database as db

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")
_bot_username_cache = None
DEFAULT_REACTIONS = ["👍", "❤️", "🔥", "👏"]


def build_post_keyboard(
    bot,
    post_id: int,
    custom_btn_text: Optional[str],
    custom_btn_url: Optional[str],
    enable_reactions: bool,
) -> Optional[InlineKeyboardMarkup]:
  """Post ostidagi tugmalar, reklama va reaksiyalarni yig'uvchi funksiya."""
  global _bot_username_cache
  keyboard = []

  # 1. Shaxsiy havola tugmasi
  if custom_btn_text and custom_btn_url:
    keyboard.append([InlineKeyboardButton(custom_btn_text, url=custom_btn_url)])

  # 2. Reklama yoki Bot havolasi
  if (custom_btn_text and custom_btn_url) or enable_reactions:
    ad_title = db.get_setting("ad_title", "")
    ad_link = db.get_setting("ad_link", "")
    if ad_title and ad_link:
      keyboard.append([InlineKeyboardButton(f"📢 {ad_title}", url=ad_link)])
    else:
      try:
        username = _bot_username_cache or getattr(bot, "username", None)
        if username:
          _bot_username_cache = username
          bot_url = f"https://t.me/{username}"
          btn_label = (
              "⚡ PostAR" if enable_reactions else "🤖 Post Assist Bot"
          )
          keyboard.append([InlineKeyboardButton(btn_label, url=bot_url)])
      except Exception:
        pass

  # 3. Reaksiya tugmalari
  if enable_reactions:
    counts = db.get_reaction_counts(post_id)
    react_row = []
    for emoji in DEFAULT_REACTIONS:
      c = counts.get(emoji, 0)
      label = f"{emoji} {c}" if c > 0 else emoji
      react_row.append(
          InlineKeyboardButton(
              label, callback_data=f"react:{post_id}:{emoji}"
          )
      )
    keyboard.append(react_row)

  return InlineKeyboardMarkup(keyboard) if keyboard else None


def _calculate_next_run(rec_type, current_time, now):
  """Takroriy postlar uchun keyingi chiqish vaqtini hisoblash."""
  if rec_type == "daily":
    next_time = current_time + timedelta(days=1)
    while next_time <= now:
      next_time += timedelta(days=1)
    return next_time
  elif rec_type == "weekly":
    next_time = current_time + timedelta(weeks=1)
    while next_time <= now:
      next_time += timedelta(weeks=1)
    return next_time
  return None


async def check_and_send_posts(bot):
  """Rejalashtirilgan vaqti kelgan postlarni asl formatini buzmasdan yuborish."""
  now = datetime.now(tashkent_tz)
  posts = db.get_due_posts(now)
  if not posts:
    return

  for post in posts:
    (
        post_id,
        user_id,
        channel_id,
        post_type,
        content,
        file_id,
        btn_text,
        btn_url,
        enable_reactions,
        scheduled_time,
        recurrence_type,
        recurrence_day,
        recurrence_time,
        end_date,
        delete_after_hours,
    ) = post

    markup = build_post_keyboard(
        bot, post_id, btn_text, btn_url, enable_reactions
    )
    try:
      target_chat = (
          int(channel_id)
          if str(channel_id).lstrip("-").isdigit()
          else channel_id
      )

      # copy_message asl xabarning barcha premium stiker, maxsus shrift va formatlarini 100% saqlaydi
      if file_id and str(file_id).isdigit():
        sent_msg = await bot.copy_message(
            chat_id=target_chat,
            from_chat_id=user_id,
            message_id=int(file_id),
            reply_markup=markup,
        )
      else:
        # Zaxira varianti (agar faqat matn bo'lsa)
        sent_msg = await bot.send_message(
            chat_id=target_chat,
            text=content or "",
            reply_markup=markup,
            parse_mode="HTML",
        )

      if recurrence_type in ("daily", "weekly"):
        if end_date and now >= end_date:
          db.mark_post_status(post_id, "completed")
        else:
          next_time = _calculate_next_run(recurrence_type, scheduled_time, now)
          if next_time and (end_date is None or next_time <= end_date):
            db.reschedule_recurring_post(post_id, next_time)
          else:
            db.mark_post_status(post_id, "completed")
      else:
        db.mark_post_as_sent(post_id, sent_msg.message_id)

    except TelegramError as e:
      logger.error(f"Post #{post_id} yuborishda xato: {e}")
      if recurrence_type == "none":
        db.mark_post_status(post_id, "failed")
      try:
        await bot.send_message(
            chat_id=user_id,
            text=f"⚠️ Post #{post_id} kanalingizga yuborilmadi: {e}",
            parse_mode="HTML",
        )
      except Exception:
        pass
    except Exception as e:
      logger.error(f"Kutilmagan xato: {e}")
      if recurrence_type == "none":
        db.mark_post_status(post_id, "failed")


async def check_and_delete_expired_posts(bot):
  """Muddati tugagan postlarni kanaldan avtomatik o'chirish."""
  now = datetime.now(tashkent_tz)
  posts_to_delete = db.get_posts_to_delete(now)

  for post in posts_to_delete:
    p_id, ch_id, msg_id = post
    try:
      target_chat = int(ch_id) if str(ch_id).lstrip("-").isdigit() else ch_id
      await bot.delete_message(chat_id=target_chat, message_id=msg_id)
      db.mark_post_as_deleted(p_id)
      logger.info(
          f"Post #{p_id} (msg_id: {msg_id}) kanaldan avtomatik o'chirildi."
      )
    except TelegramError as e:
      logger.warning(
          f"Post #{p_id} ni o'chirishda xatolik: {e}"
      )
      db.mark_post_as_deleted(p_id)
