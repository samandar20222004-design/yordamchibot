# -*- coding: utf-8 -*-
"""
=====================================================================
 📝 POSTS — post CRUD, statuslar, media, navbat (queue), shablonlar
=====================================================================

Postlar yaratish/o'qish/tahrirlash, status o'tishlari, media/reaksiyalar, auto-delete jadvali, navbat (queue) slotlari va shablonlar (post_templates).

Qatlam: REPOSITORY — domain ma'lumotlariga kirish.

Bu modul yadroga (``database``: pool / tranzaksiya / kesh / sxema)
``repositories.runtime`` orqali **kech bog'lanadi**: ``db_cursor``,
``transaction``, ``_cache_*`` va boshqa yadro yordamchilari chaqiruv
paytida ``database`` modulining joriy atributiga qarab yuradi. Shu
sabab ``unittest.mock.patch("database.db_cursor")`` kabi mavjud mock
nuqtalari bu modulga ko'chirilgandan keyin ham kuchini yo'qotmaydi.
"""

import json
import logging


from database import POST_BATCH_SIZE
from repositories.runtime import (  # noqa: F401
    _cache_clear, _invalidate_user, db_cursor, get_setting, set_setting
)

from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)


# ====================================================================
# 📝 POSTS — post CRUD, statuslar, media, navbat (queue), shablonlar
# ====================================================================

def get_post_health_counts() -> dict:
    """Scheduler monitoringi uchun postlar holati bo'yicha hisob-kitob.

    Ikki yengil COUNT so'rovi (indekslangan ustunlar):

    * ``scheduled_posts``  → ``pending`` / ``processing`` / ``failed`` /
      ``stale_processing`` (10+ daqiqa 'processing'da qotib qolganlar —
      stale-recovery bilan bir xil chegara);
    * ``post_deliveries``  → ``delivery_failed`` / ``dead_letter``.

    Xato bo'lsa hech qachon istisno ko'tarmaydi — hisoblanagan qismi va
    ``error`` kaliti qaytariladi (health hisoboti yarim bo'lsa ham ishlaydi).
    """
    counts = {
        "pending": 0,
        "processing": 0,
        "failed": 0,
        "stale_processing": 0,
        "unknown_posts": 0,
        "delivery_failed": 0,
        "dead_letter": 0,
        "unknown_delivery": 0,
    }
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'pending'),
                    COUNT(*) FILTER (WHERE status = 'processing'),
                    COUNT(*) FILTER (WHERE status = 'failed'),
                    COUNT(*) FILTER (WHERE status = 'processing'
                                     AND processing_started_at
                                         < NOW() - INTERVAL '10 minutes'),
                    COUNT(*) FILTER (WHERE status = 'unknown')
                FROM scheduled_posts
            """)
            row = cur.fetchone() or (0, 0, 0, 0, 0)
            counts["pending"] = int(row[0] or 0)
            counts["processing"] = int(row[1] or 0)
            counts["failed"] = int(row[2] or 0)
            counts["stale_processing"] = int(row[3] or 0)
            counts["unknown_posts"] = int(row[4] or 0) if len(row) > 4 else 0

            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'failed'),
                    COUNT(*) FILTER (WHERE status = 'dead_letter'),
                    COUNT(*) FILTER (WHERE status = 'unknown')
                FROM post_deliveries
            """)
            drow = cur.fetchone() or (0, 0, 0)
            counts["delivery_failed"] = int(drow[0] or 0)
            counts["dead_letter"] = int(drow[1] or 0)
            counts["unknown_delivery"] = int(drow[2] or 0) if len(drow) > 2 else 0
    except Exception as e:
        logger.warning("Post health hisob-kitobida xato: %s", e)
        counts["error"] = f"{type(e).__name__}: {e}"[:200]
    return counts


# --- REACTIONS ---
def toggle_reaction(post_id: int, user_id: int, reaction: str) -> dict:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT reaction_type FROM post_reactions WHERE post_id = %s AND user_id = %s", (post_id, user_id))
            row = cur.fetchone()
            if row:
                if row[0] == reaction:
                    cur.execute("DELETE FROM post_reactions WHERE post_id = %s AND user_id = %s", (post_id, user_id))
                else:
                    cur.execute("UPDATE post_reactions SET reaction_type = %s WHERE post_id = %s AND user_id = %s", (reaction, post_id, user_id))
            else:
                cur.execute("INSERT INTO post_reactions (post_id, user_id, reaction_type) VALUES (%s, %s, %s)", (post_id, user_id, reaction))

            cur.execute("SELECT reaction_type, COUNT(*) FROM post_reactions WHERE post_id = %s GROUP BY reaction_type", (post_id,))
            return {r[0]: r[1] for r in cur.fetchall()}
    except Exception as e:
        logger.error(f"Reaksiya xatosi: {e}")
        return {}


# --- POSTS ---
def add_post(
    user_id: int,
    channel_id: str,
    post_type: str,
    content: str,
    file_id: str,
    scheduled_time,
    recurrence_type: str = 'none',
    recurrence_day=None,
    recurrence_time=None,
    end_date=None,
    btn_text: str = None,
    btn_url: str = None,
    enable_reactions: bool = False,
    delete_after_hours: int = 0,
    reaction_emojis=None,
    delivery_options=None
) -> int:
    # reaction_emojis: ro'yxat yoki bo'sh joy bilan ajratilgan satr — DB'da
    # bo'sh joy bilan ajratilgan satr ko'rinishida saqlanadi ("👍 ❤️ 🔥").
    if reaction_emojis:
        if isinstance(reaction_emojis, (list, tuple, set)):
            reaction_emojis = " ".join(str(e) for e in reaction_emojis if e)
        else:
            reaction_emojis = " ".join(str(reaction_emojis).split())
        if not reaction_emojis:
            reaction_emojis = None
    else:
        reaction_emojis = None
    try:
        with db_cursor(commit=True) as cur:
            # Bir foydalanuvchining post raqami MAX(...)+1 bilan tuziladi.
            # Parallel kelgan ikkita saqlash so'rovi bir xil raqam olmasligi
            # uchun transaction darajasidagi advisory qulf ishlatiladi.
            # Qulf commit/rollback bilan avtomatik bo'shaydi.
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (int(user_id),))
            cur.execute("SELECT COALESCE(MAX(user_post_number), 0) + 1 FROM scheduled_posts WHERE user_id = %s", (user_id,))
            next_num = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO scheduled_posts
                    (user_id, channel_id, post_type, content, file_id, inline_button_text, inline_button_url,
                     enable_reactions, reaction_emojis, delete_after_hours, scheduled_time, status, user_post_number,
                     recurrence_type, recurrence_day, recurrence_time, end_date, delivery_options)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING id
            """, (
                user_id, str(channel_id), post_type, content, file_id, btn_text, btn_url,
                enable_reactions, reaction_emojis, delete_after_hours, scheduled_time, next_num,
                recurrence_type, recurrence_day, recurrence_time, end_date,
                json.dumps({key: (delivery_options or {}).get(key) is True for key in
                            ("disable_notification", "protect_content", "auto_pin")})
            ))
            post_id = cur.fetchone()[0]
        _invalidate_user(user_id)
        _cache_clear("system_stats")
        return post_id
    except Exception as e:
        logger.error(f"Post saqlash xatosi: {e}")
        return 0


def get_post_delivery_options(post_id: int) -> dict:
    # Keep the scheduler's existing 16-column tuple contract unchanged.
    # DB failures must propagate: never silently drop content protection.
    with db_cursor() as cur:
        cur.execute("SELECT delivery_options FROM scheduled_posts WHERE id = %s", (post_id,))
        row = cur.fetchone()
    return row[0] if row and isinstance(row[0], dict) else {}


def get_recent_posts(limit: int = 15) -> list:
    """Admin panel uchun eng so'nggi postlarni qaytaradi."""
    try:
        with db_cursor() as cur:
            limit = max(1, int(limit))
            cur.execute("""
                SELECT sp.id, sp.user_id, c.channel_title, sp.post_type, sp.scheduled_time, sp.status
                FROM scheduled_posts sp
                LEFT JOIN channels c ON sp.channel_id = c.channel_id
                ORDER BY sp.id DESC
                LIMIT %s
            """, (limit,))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Oxirgi postlarni olish xatosi: {e}")
        return []


def get_pending_posts(user_id: int) -> list:
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT sp.id, c.channel_title, sp.post_type, sp.scheduled_time,
                       sp.user_post_number, sp.recurrence_type, sp.recurrence_day, sp.recurrence_time
                FROM scheduled_posts sp
                LEFT JOIN channels c ON sp.channel_id = c.channel_id
                WHERE sp.user_id = %s AND sp.status = 'pending'
                ORDER BY sp.scheduled_time ASC
            """, (user_id,))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Pending posts xatosi: {e}")
        return []


def get_post_by_id(post_id: int):
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, user_id, channel_id, post_type, scheduled_time, recurrence_type, recurrence_time, user_post_number
                FROM scheduled_posts WHERE id = %s
            """, (post_id,))
            return cur.fetchone()
    except Exception as e:
        logger.error(f"Post olish xatosi: {e}")
        return None


def update_post_time(post_id: int, new_time, recurrence_time=None, user_id: int = None, is_admin: bool = False) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            owner_clause = "" if is_admin else " AND user_id = %s"
            params = [new_time]
            if recurrence_time:
                query = "UPDATE scheduled_posts SET scheduled_time = %s, recurrence_time = %s WHERE id = %s"; params = [new_time, recurrence_time, post_id]
            else:
                query = "UPDATE scheduled_posts SET scheduled_time = %s WHERE id = %s"; params = [new_time, post_id]
            query += owner_clause
            if not is_admin: params.append(user_id)
            cur.execute(query, tuple(params))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Post vaqtini yangilash xatosi: {e}")
        return False


def update_post_content(post_id: int, user_id: int,
                        content: str = None,
                        btn_text: str = None, btn_url: str = None,
                        enable_reactions: bool = None,
                        reaction_emojis=None,
                        is_admin: bool = False) -> bool:
    """Kutilayotgan postning matn, tugma va reaksiyalarini yangilash.

    Faqat o'zgartirish kerak bo'lgan maydonlar uzatiladi (None bo'lsa o'zgartirilmaydi).
    is_admin=True bo'lsa foydalanuvchi tekshiruvi (user_id) o'tkazib yuboriladi.
    """
    try:
        sets = []
        params = []
        if content is not None:
            sets.append("content = %s")
            params.append(content)
        if btn_text is not None:
            # Jadvaldagi ustun nomlari: inline_button_text / inline_button_url.
            sets.append("inline_button_text = %s")
            params.append(btn_text if btn_text else None)
        if btn_url is not None:
            sets.append("inline_button_url = %s")
            params.append(btn_url if btn_url else None)
        if enable_reactions is not None:
            sets.append("enable_reactions = %s")
            params.append(enable_reactions)
        if reaction_emojis is not None:
            if isinstance(reaction_emojis, (list, tuple, set)):
                reaction_emojis = " ".join(str(e) for e in reaction_emojis if e)
            else:
                reaction_emojis = " ".join(str(reaction_emojis).split())
            sets.append("reaction_emojis = %s")
            params.append(reaction_emojis or None)
        if not sets:
            return False

        query = f"UPDATE scheduled_posts SET {', '.join(sets)} WHERE id = %s AND status = 'pending'"
        params.append(post_id)
        if not is_admin:
            query += " AND user_id = %s"
            params.append(user_id)

        with db_cursor(commit=True) as cur:
            cur.execute(query, tuple(params))
            updated = cur.rowcount > 0
        if updated:
            _cache_clear(f"pending_posts:{user_id}")
        return updated
    except Exception as e:
        logger.error(f"Post kontentini yangilash xatosi: {e}")
        return False


def cancel_post(post_id: int, user_id: int, is_admin: bool = False) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            if is_admin:
                cur.execute("UPDATE scheduled_posts SET status = 'cancelled' WHERE id = %s AND status = 'pending'", (post_id,))
            else:
                cur.execute("UPDATE scheduled_posts SET status = 'cancelled' WHERE id = %s AND user_id = %s AND status = 'pending'", (post_id, user_id))
            cancelled = cur.rowcount > 0
        _invalidate_user(user_id)
        _cache_clear("system_stats")
        return cancelled
    except Exception as e:
        logger.error(f"Post bekor qilish xatosi: {e}")
        return False


def get_due_posts(now) -> list:
    """Atomically claim due posts so concurrent scheduler runs cannot duplicate them.

    Bir tick'da ko'pi bilan POST_BATCH_SIZE ta post olinadi — qolganlari
    keyingi tick'da yuboriladi (ulkan navbat bitta ishlashni to'sib qo'ymaydi).
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                WITH due AS (
                    SELECT id FROM scheduled_posts
                    -- ``pending`` is the legacy single-owner queue; ``scheduled``
                    -- is the Phase E queue and can only be reached after approval.
                    WHERE (status = 'pending' OR status = 'scheduled') AND scheduled_time <= %s
                    ORDER BY scheduled_time
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE scheduled_posts sp
                SET status = 'processing', processing_started_at = NOW()
                FROM due
                WHERE sp.id = due.id
                RETURNING sp.id, sp.user_id, sp.channel_id, sp.post_type, sp.content, sp.file_id,
                          sp.inline_button_text, sp.inline_button_url, sp.enable_reactions,
                          sp.scheduled_time, sp.recurrence_type, sp.recurrence_day,
                          sp.recurrence_time, sp.end_date, sp.delete_after_hours, sp.reaction_emojis
            """, (now, POST_BATCH_SIZE))
            rows = cur.fetchall()
        _cache_clear("system_stats")
        return rows
    except Exception as e:
        logger.error(f"Due posts xatosi: {e}")
        return []


def mark_post_processing(post_id: int) -> bool:
    """Postni Telegramga yuborishdan oldin statusini qat'iy 'processing' va processing_started_at ni NOW() deb belgilash.

    Qaytaradi: ``True`` — yozildi, ``False`` — DB xatosi (istisno tashlanmaydi).
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE scheduled_posts SET status = 'processing', processing_started_at = NOW() WHERE id = %s",
                (post_id,)
            )
        _cache_clear("system_stats")
        return True
    except Exception as e:
        logger.error(f"Post processing status xatosi (Post ID {post_id}): {e}")
        return False


def mark_post_status(post_id: int, status: str) -> bool:
    """Post statusini yangilaydi. ``True`` — yozildi, ``False`` — DB xatosi (istisno yo'q).

    Scheduler qaytgan qiymatga qarab transient DB xatosida qayta urinadi —
    aks holda 'yuborildi' fakti yo'qolib, restartdan keyin post ikki marta chiqishi mumkin.
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE scheduled_posts SET status = %s WHERE id = %s", (status, post_id))
        _cache_clear("system_stats")
        return True
    except Exception as e:
        logger.error(f"Post status xatosi: {e}")
        return False


def mark_post_as_sent(post_id: int, sent_message_id: int, channel_id: str = None, delete_after_hours: int = 0, extra_message_ids: list = None, delivery_key: str = None) -> bool:
    """Telegramga yuborilgan postni 'posted' deb belgilaydi va xabar ID'larini saqlaydi.

    Bitta tranzaksiyada bajariladi (yarim yozilgan holat bo'lmaydi). Qaytaradi:
    ``True`` — commit bo'ldi; ``False`` — DB xatosi (istisno tashlanmaydi, chaqiruvchi
    qayta urinishi kerak: 'yuborildi' markeri idempotentlik kafolatining asosi).

    11-bosqich (P0): ``delivery_key`` berilsa ``post_deliveries`` yozuvi ham
    AYNI SHU tranzaksiyada ``'sent'`` bo'ladi — scheduled_posts 'posted' va
    delivery 'sent' markerlari hech qachon bir-biridan ajralib qolmaydi
    (crash oralig'ida "biri yozildi, biri yo'q" holati bo'lmaydi).
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE scheduled_posts
                   SET status = CASE WHEN status = 'scheduled' THEN 'published' ELSE 'posted' END,
                       sent_message_id = %s
                 WHERE id = %s
            """, (sent_message_id, post_id))
            if delivery_key:
                cur.execute(
                    "UPDATE post_deliveries SET status = 'sent', telegram_message_id = %s, "
                    "last_error = NULL, next_retry_at = NULL, updated_at = NOW() "
                    "WHERE idempotency_key = %s AND status <> 'sent'",
                    (sent_message_id, str(delivery_key)),
                )
            if channel_id is not None:
                ids = [sent_message_id]
                if extra_message_ids:
                    for mid in extra_message_ids:
                        if mid and mid not in ids:
                            ids.append(mid)
                for mid in ids:
                    cur.execute("""
                        INSERT INTO sent_post_messages (post_id, channel_id, message_id, delete_at)
                        VALUES (%s, %s, %s, CASE WHEN %s > 0 THEN NOW() + (%s || ' hours')::INTERVAL ELSE NULL END)
                    """, (post_id, str(channel_id), mid, delete_after_hours, delete_after_hours))
        _cache_clear("system_stats")
        return True
    except Exception as e:
        logger.error(f"Post yuborilganini belgilash xatosi: {e}")
        return False


def get_posts_to_delete(now) -> list:
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, channel_id, message_id
                FROM sent_post_messages
                WHERE deleted_at IS NULL AND delete_at IS NOT NULL AND delete_at <= %s
            """, (now,))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"O'chiriladigan postlar xatosi: {e}")
        return []


def mark_post_as_deleted(message_row_id: int) -> bool:
    """Kanal xabarini 'o'chirildi' deb belgilaydi (``deleted_at = NOW()``).

    FAQAT haqiqatan o'chirilganda yoki xabar Telegramda topilmaganda
    chaqirilishi kerak (scheduler ``classify_delete_error`` bilan ajratadi).
    Qaytaradi: ``True`` — yozildi, ``False`` — DB xatosi.
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE sent_post_messages SET deleted_at = NOW() WHERE id = %s", (message_row_id,))
        _cache_clear("system_stats")
        return True
    except Exception as e:
        logger.error(f"Post o'chirish xatosi: {e}")
        return False


def defer_post_deletion(message_row_id: int, delay_seconds: int = 300) -> bool:
    """Avto-o'chirishni vaqtinchalik xatoda (tarmoq/FloodWait) KEYINGA suradi.

    ``deleted_at`` TEGILMAYDI — xabar hali kanalda turibdi deb hisoblanadi;
    faqat ``delete_at`` oldinga suriladi, scheduler keyingi tick'da yana urinadi.
    """
    try:
        delay = max(30, int(delay_seconds or 300))
    except (TypeError, ValueError):
        delay = 300
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE sent_post_messages "
                "SET delete_at = NOW() + (%s || ' seconds')::INTERVAL "
                "WHERE id = %s AND deleted_at IS NULL",
                (str(delay), message_row_id),
            )
        return True
    except Exception as e:
        logger.error(f"Avto-o'chirishni kechiktirish xatosi: {e}")
        return False


def reschedule_recurring_post(post_id: int, next_time):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE scheduled_posts SET scheduled_time = %s WHERE id = %s", (next_time, post_id))
        _cache_clear("system_stats")
    except Exception as e:
        logger.error(f"Qayta rejalashtirish xatosi: {e}")


def retry_post(post_id: int, retry_at):
    """Telegram vaqtinchalik xatosi (rate-limit/tarmoq) tufayli postni qayta navbatga qo'yish."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE scheduled_posts SET scheduled_time = %s, status = 'pending', processing_started_at = NULL WHERE id = %s",
                (retry_at, post_id),
            )
        _cache_clear("system_stats")
    except Exception as e:
        logger.error(f"Post qayta navbatlash xatosi: {e}")


# --- QUEUE SYSTEM ---
DEFAULT_QUEUE_SLOTS = ["09:00", "14:00", "19:00"]


def get_queue_slots(user_id: int) -> list:
    """Foydalanuvchining queue slotlarini qaytaradi."""
    import json as _json
    raw = get_setting(f"queue_slots:{user_id}", "")
    if not raw:
        return list(DEFAULT_QUEUE_SLOTS)
    try:
        slots = _json.loads(raw)
        if isinstance(slots, list) and all(isinstance(s, str) for s in slots):
            return slots
    except Exception as _silent_exc:
        log_silent_failure("repositories.posts_repository:get_queue_slots", _silent_exc, user_id=user_id)
    return list(DEFAULT_QUEUE_SLOTS)


def set_queue_slots(user_id: int, slots: list) -> bool:
    """Foydalanuvchining queue slotlarini saqlaydi."""
    import json as _json
    try:
        set_setting(f"queue_slots:{user_id}", _json.dumps(slots))
        return True
    except Exception:
        return False


def get_queue_occupied_times(user_id: int, channel_id: str, target_date) -> list:
    """Berilgan sana uchun band qilingan vaqtlarni qaytaradi."""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT EXTRACT(HOUR FROM scheduled_time AT TIME ZONE 'Asia/Tashkent')::int,
                       EXTRACT(MINUTE FROM scheduled_time AT TIME ZONE 'Asia/Tashkent')::int
                FROM scheduled_posts
                WHERE user_id = %s
                  AND status = 'pending'
                  AND (channel_id = %s OR channel_id = 'ALL')
                  AND (scheduled_time AT TIME ZONE 'Asia/Tashkent')::date = %s
            """, (user_id, str(channel_id), target_date))
            return [(row[0], row[1]) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Queue occupied times xatosi: {e}")
        return []


def get_queue_posts(user_id: int, offset: int = 0, limit: int = 5) -> list:
    """Foydalanuvchining navbatdagi postlarini sahifalab qaytaradi."""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT sp.id, c.channel_title, sp.post_type, sp.content,
                       sp.scheduled_time, sp.user_post_number, sp.channel_id
                FROM scheduled_posts sp
                LEFT JOIN channels c ON sp.channel_id = c.channel_id
                WHERE sp.user_id = %s AND sp.status = 'pending'
                ORDER BY sp.scheduled_time ASC
                OFFSET %s LIMIT %s
            """, (user_id, offset, limit))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Queue posts xatosi: {e}")
        return []


def get_queue_post_count(user_id: int) -> int:
    """Foydalanuvchining navbatdagi postlar soni."""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM scheduled_posts
                WHERE user_id = %s AND status = 'pending'
            """, (user_id,))
            return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"Queue count xatosi: {e}")
        return 0


def get_queue_post_detail(post_id: int, user_id: int):
    """Bitta queue postni to'liq ma'lumotlari bilan qaytaradi."""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT sp.id, sp.user_id, sp.channel_id, c.channel_title,
                       sp.post_type, sp.content, sp.file_id,
                       sp.inline_button_text, sp.inline_button_url,
                       sp.enable_reactions, sp.delete_after_hours,
                       sp.scheduled_time, sp.user_post_number
                FROM scheduled_posts sp
                LEFT JOIN channels c ON sp.channel_id = c.channel_id
                WHERE sp.id = %s AND sp.user_id = %s AND sp.status = 'pending'
            """, (post_id, user_id))
            return cur.fetchone()
    except Exception as e:
        logger.error(f"Queue post detail xatosi: {e}")
        return None


# ============================================================
# ANALYTICS & POST PERFORMANCE
# ============================================================

def get_channel_post_stats(user_id: int, channel_id: str = None) -> dict:
    """Kanal post statistikasini qaytaradi.

    P1 PERFORMANCE (5-qadam): ilgari bu funksiya **8 ta ketma-ket SQL**
    yuborardi (har bir ko'rsatkich uchun alohida SELECT — N+1 uslubi).
    Endi barcha hisob-kitob **DB darajasida agregatsiya** qilinadi va
    jami **3 ta so'rov** ketadi:

      1) barcha COUNT'lar (7 kun / 30 kun / jami / pending) — bitta
         ``COUNT(*) FILTER (WHERE ...)`` so'rovida;
      2) eng faol soatlar + post turi taqsimoti — bitta ``GROUPING SETS``
         so'rovida (ilgari 2 ta alohida GROUP BY edi);
      3) ``channel_posts_history`` ko'rishlar statistikasi (o'zgarmagan).

    Qaytariladigan lug'at kalitlari va qiymatlari AYNAN o'sha —
    orqaga moslik 100% (handler'lar o'zgartirilmagan).

    Args:
        user_id: foydalanuvchi ID
        channel_id: kanal ID (None bo'lsa — barcha kanallar)

    Returns:
        {
            "sent_7d": int, "sent_30d": int, "sent_all": int,
            "pending": int,
            "peak_hours": [(hour, count), ...],
            "type_distribution": {"text": N, "photo": N, ...},
            "history_count": int, "total_views": int, "avg_views": float,
        }
    """
    result = {
        "sent_7d": 0, "sent_30d": 0, "sent_all": 0,
        "pending": 0,
        "peak_hours": [],
        "type_distribution": {},
    }
    try:
        with db_cursor() as cur:
            ch_filter = "AND sp.channel_id = %s" if channel_id else ""
            params_base = (user_id, str(channel_id)) if channel_id else (user_id,)

            # (1) BARCHA davr COUNT'lari — BITTA so'rov (conditional aggregation).
            q = (
                f"SELECT "
                f"COUNT(*) FILTER (WHERE sp.status = 'posted' "
                f"  AND sp.scheduled_time >= NOW() - INTERVAL '7 days') AS sent_7d, "
                f"COUNT(*) FILTER (WHERE sp.status = 'posted' "
                f"  AND sp.scheduled_time >= NOW() - INTERVAL '30 days') AS sent_30d, "
                f"COUNT(*) FILTER (WHERE sp.status = 'posted') AS sent_all, "
                f"COUNT(*) FILTER (WHERE sp.status = 'pending') AS pending "
                f"FROM scheduled_posts sp "
                f"WHERE sp.user_id = %s {ch_filter}"
            )
            cur.execute(q, params_base)
            row = cur.fetchone()
            if row:
                result["sent_7d"] = int(row[0] or 0)
                result["sent_30d"] = int(row[1] or 0)
                result["sent_all"] = int(row[2] or 0)
                result["pending"] = int(row[3] or 0)

            # (2) Peak hours (top 3) + post type distribution — BITTA so'rov.
            #     `GROUPING(...)` ustuni qaysi guruhlash to'plamidan kelganini
            #     ko'rsatadi (1 = bu so'rovda hisoblanmagan).
            q = (
                f"SELECT EXTRACT(HOUR FROM sp.scheduled_time)::int AS hour_bucket, "
                f"sp.post_type AS post_type, "
                f"GROUPING(EXTRACT(HOUR FROM sp.scheduled_time)::int) AS hour_grouped, "
                f"GROUPING(sp.post_type) AS type_grouped, "
                f"COUNT(*) AS cnt "
                f"FROM scheduled_posts sp "
                f"WHERE sp.user_id = %s AND sp.status = 'posted' {ch_filter} "
                f"GROUP BY GROUPING SETS ("
                f"  (EXTRACT(HOUR FROM sp.scheduled_time)::int), (sp.post_type))"
            )
            cur.execute(q, params_base)
            peak = []
            type_dist = {}
            for stat_row in cur.fetchall() or []:
                values = list(stat_row) + [None] * 5
                cnt = int(values[4] or 0)
                if int(values[2] or 0) == 0 and values[0] is not None:
                    peak.append((int(values[0]), cnt))
                elif int(values[3] or 0) == 0 and values[1] is not None:
                    type_dist[str(values[1])] = cnt
            peak.sort(key=lambda item: (-item[1], item[0]))
            result["peak_hours"] = peak[:3]
            result["type_distribution"] = dict(
                sorted(type_dist.items(), key=lambda item: (-item[1], item[0]))
            )

            # (3) Real vaqtli kanal postlari tarixi statistikasi (views, count)
            #     — DB darajasidagi agregatsiya (o'zgarmagan).
            try:
                if channel_id:
                    cur.execute(
                        "SELECT COUNT(*), COALESCE(SUM(views), 0), COALESCE(AVG(views), 0) "
                        "FROM channel_posts_history WHERE channel_id = %s",
                        (str(channel_id),)
                    )
                else:
                    cur.execute(
                        "SELECT COUNT(*), COALESCE(SUM(cph.views), 0), COALESCE(AVG(cph.views), 0) "
                        "FROM channel_posts_history cph "
                        "INNER JOIN channels c ON c.channel_id = cph.channel_id "
                        "WHERE c.user_id = %s AND c.is_active = TRUE",
                        (user_id,)
                    )
                h_row = cur.fetchone()
                if h_row:
                    result["history_count"] = int(h_row[0] or 0)
                    result["total_views"] = int(h_row[1] or 0)
                    result["avg_views"] = round(float(h_row[2] or 0), 1)
            except Exception as _silent_exc:
                log_silent_failure("repositories.posts_repository:get_channel_post_stats", _silent_exc, user_id=user_id, channel_id=channel_id)

    except Exception as e:
        logger.error(f"Channel post stats xatosi: {e}")
    return result


# ============================================================
# 📋 PHASE C — POST SHABLONLARI (post_templates CRUD)
# ------------------------------------------------------------
# Foydalanuvchining takroriy post shablonlari. IDOR himoyasi:
# barcha o'qish/o'chirish so'rovlari ``user_id`` bilan filtrlanadi —
# boshqa foydalanuvchining shablonini ko'rib/o'chira olish MUMKIN EMAS.
# Barcha funksiyalar sinxron (``run_db`` orqali chaqiriladi) va xatoda
# istisno ko'tarmaydi — fail-soft.
# ============================================================

#: Bitta foydalanuvchi saqlashi mumkin bo'lgan shablonlar soni (FREE/PRO).
POST_TEMPLATES_LIMIT = 20


def _template_row_to_dict(row) -> dict | None:
    """``post_templates`` qatorini dict ko'rinishiga o'tkazadi."""
    if not row:
        return None
    variables_raw = row[5]
    if isinstance(variables_raw, str):
        try:
            variables = json.loads(variables_raw)
        except Exception:
            variables = {}
    else:
        variables = dict(variables_raw or {})
    return {
        "id": int(row[0]),
        "user_id": int(row[1]),
        "channel_id": row[2],
        "name": row[3],
        "content": row[4] or "",
        "variables": variables,
        "created_at": row[6].isoformat() if row[6] else "",
    }


def create_post_template(
    user_id: int,
    name: str,
    content: str,
    channel_id: str | None = None,
    variables: list | dict | None = None,
) -> int:
    """Yangi post shablonini saqlaydi. Qaytadi: template id yoki 0 (xato)."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return 0
    tpl_name = str(name or "").strip()[:128]
    tpl_content = str(content or "").strip()
    if not tpl_name or not tpl_content:
        return 0
    if isinstance(variables, dict):
        var_list = sorted(str(v).upper() for v in variables.keys())
    elif isinstance(variables, (list, tuple, set)):
        var_list = sorted({str(v).upper() for v in variables if v})
    else:
        var_list = []
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "SELECT COUNT(*) FROM post_templates WHERE user_id = %s", (uid,))
            count = int(cur.fetchone()[0] or 0)
            if count >= POST_TEMPLATES_LIMIT:
                return 0
            cur.execute(
                """
                INSERT INTO post_templates (user_id, channel_id, name, content, variables)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (uid, str(channel_id) if channel_id else None, tpl_name,
                 tpl_content, json.dumps(var_list)),
            )
            return int(cur.fetchone()[0])
    except Exception as e:
        logger.error("create_post_template xatosi (user=%s): %s", uid, e)
        return 0


def get_post_templates(user_id: int, limit: int = 20) -> list[dict]:
    """Foydalanuvchining shablonlari (FAQAT o'ziniki — IDOR himoyasi)."""
    try:
        uid = int(user_id)
        safe_limit = max(1, min(int(limit), POST_TEMPLATES_LIMIT))
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, channel_id, name, content, variables, created_at
                FROM post_templates
                WHERE user_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (uid, safe_limit),
            )
            rows = cur.fetchall()
        return [r for r in (_template_row_to_dict(row) for row in rows) if r]
    except Exception as e:
        logger.error("get_post_templates xatosi (user=%s): %s", user_id, e)
        return []


def get_post_template(template_id: int, user_id: int) -> dict | None:
    """Bitta shablon — FAQAT egasi uchun (user_id filtri = IDOR himoyasi).

    ``user_id`` mos kelmasa (yoki shablon yo'q bo'lsa) ``None`` qaytadi:
    boshqa foydalanuvchining shablonini ko'rib bo'lmaydi.
    """
    try:
        tid = int(template_id)
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, channel_id, name, content, variables, created_at
                FROM post_templates
                WHERE id = %s AND user_id = %s
                """,
                (tid, uid),
            )
            return _template_row_to_dict(cur.fetchone())
    except Exception as e:
        logger.error("get_post_template xatosi (id=%s): %s", template_id, e)
        return None


def delete_post_template(template_id: int, user_id: int) -> bool:
    """Shablonni o'chiradi — FAQAT egasi o'chira oladi (IDOR himoyasi).

    Qaytadi: ``True`` — o'chirildi; ``False`` — topilmadi/yetarli emas.
    """
    try:
        tid = int(template_id)
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "DELETE FROM post_templates WHERE id = %s AND user_id = %s",
                (tid, uid),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_post_template xatosi (id=%s): %s", template_id, e)
        return False


def count_post_templates(user_id: int) -> int:
    """Foydalanuvchining shablonlari soni (limit tekshiruvi uchun)."""
    try:
        uid = int(user_id)
        with db_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM post_templates WHERE user_id = %s", (uid,))
            return int(cur.fetchone()[0] or 0)
    except Exception as e:
        logger.error("count_post_templates xatosi (user=%s): %s", user_id, e)
        return 0
