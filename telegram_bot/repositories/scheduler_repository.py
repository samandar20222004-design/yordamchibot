# -*- coding: utf-8 -*-
"""
=====================================================================
 ⏰ SCHEDULER — rejalashtirish, delivery jobs, tiklash, tozalash
=====================================================================

Haftalik rejalashtirish, Telegram delivery joblari (idempotency, backoff, dead-letter), 'processing' holatidan tiklash, eskirgan ma'lumotlarni tozalash va bo'sh navbat slotini topish.

Qatlam: REPOSITORY — domain ma'lumotlariga kirish.

Bu modul yadroga (``database``: pool / tranzaksiya / kesh / sxema)
``repositories.runtime`` orqali **kech bog'lanadi**: ``db_cursor``,
``transaction``, ``_cache_*`` va boshqa yadro yordamchilari chaqiruv
paytida ``database`` modulining joriy atributiga qarab yuradi. Shu
sabab ``unittest.mock.patch("database.db_cursor")`` kabi mavjud mock
nuqtalari bu modulga ko'chirilgandan keyin ham kuchini yo'qotmaydi.
"""

import hashlib
from datetime import datetime, timedelta
import logging


from database import tashkent_tz
from repositories.runtime import (  # noqa: F401
    _cache_clear, _invalidate_user, db_cursor
)

logger = logging.getLogger(__name__)


# ====================================================================
# ⏰ SCHEDULER — rejalashtirish, delivery jobs, tiklash, tozalash
# ====================================================================

def schedule_week_posts(user_id: int, channel_id: str, posts: list,
                        post_type: str = "text") -> dict:
    """🚀 Bir necha postni (odatda 7 kunlik kontent-reja) BITTA tranzaksiyada navbatga qo'yadi.

    ``posts`` — ``(scheduled_time, content)`` juftliklari ro'yxati (tartib
    dushanba → yakshanba). Barcha INSERT'lar bitta ``db_cursor(commit=True)``
    blokida bajariladi: psycopg2 birinchi so'rovda tranzaksiyani boshlaydi va
    ``commit`` faqat blok muvaffaqiyatli tugaganda chaqiriladi. Biror INSERT
    yiqilsa — ``db_cursor`` ``ROLLBACK`` qiladi, ya'ni **yarim-yorti navbat
    hech qachon qolmaydi** (hammasi yoki hech narsa).

    ``add_post`` bilan bir xil himoya: ``pg_advisory_xact_lock(user_id)`` va
    ``MAX(user_post_number) + 1`` — parallel chaqiruvlar bir xil post raqamini
    olmaydi. Qulf commit/rollback bilan avtomatik bo'shaydi.

    Qaytadi::

        {"success": bool, "count": int, "ids": [int], "times": [datetime],
         "error": str}
    """
    result = {"success": False, "count": 0, "ids": [], "times": [], "error": ""}
    rows = [p for p in (posts or []) if p]
    if not rows:
        result["error"] = "empty"
        return result
    if not channel_id:
        result["error"] = "no_channel"
        return result
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        result["error"] = "bad_user"
        return result

    try:
        ids = []
        times = []
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (user_id,))
            cur.execute(
                "SELECT COALESCE(MAX(user_post_number), 0) FROM scheduled_posts WHERE user_id = %s",
                (user_id,),
            )
            next_num = int((cur.fetchone() or (0,))[0] or 0)
            for scheduled_time, content in rows:
                next_num += 1
                cur.execute("""
                    INSERT INTO scheduled_posts
                        (user_id, channel_id, post_type, content, file_id,
                         scheduled_time, status, user_post_number, recurrence_type)
                    VALUES (%s, %s, %s, %s, NULL, %s, 'pending', %s, 'none')
                    RETURNING id
                """, (
                    user_id, str(channel_id), post_type, content,
                    scheduled_time, next_num,
                ))
                ids.append(cur.fetchone()[0])
                times.append(scheduled_time)
        _invalidate_user(user_id)
        _cache_clear("system_stats")
        result.update({"success": True, "count": len(ids), "ids": ids, "times": times})
        return result
    except Exception as e:
        logger.error(f"Haftalik postlarni navbatga qo'yish xatosi: {e}")
        result["error"] = str(e)
        return result


def _delivery_channel_number(channel_id) -> int:
    """post_deliveries.channel_id BIGINT uchun kanalni deterministik kodlaydi.

    Telegram kanal ID'lari odatda BIGINT. Legacy konfiguratsiyada ``@username``
    ham uchrashi mumkin; bunday qiymat uchun stable signed 63-bit surrogate
    ishlatiladi. Haqiqiy idempotency_key esa original qiymatni saqlaydi.
    """
    try:
        return int(channel_id)
    except (TypeError, ValueError):
        digest = hashlib.sha256(str(channel_id).encode("utf-8")).digest()[:8]
        value = int.from_bytes(digest, "big") & ((1 << 63) - 1)
        return value or 1


def build_delivery_idempotency_key(post_id: int, channel_id, scheduled_timestamp) -> str:
    """Bir scheduled post/channel/vaqt uchun o'zgarmas delivery key."""
    if hasattr(scheduled_timestamp, "isoformat"):
        timestamp = scheduled_timestamp.isoformat()
    else:
        timestamp = str(scheduled_timestamp)
    return f"post_{int(post_id)}_{channel_id}_{timestamp}"


DELIVERY_MAX_ATTEMPTS = 5


# 'processing' da qolib ketgan delivery crash deb hisoblanadigan muddat.
# scheduled_posts dagi 10 daqiqalik stale-recovery bilan bir xil.
DELIVERY_STALE_PROCESSING_SECONDS = 600


def claim_post_delivery(post_id: int, channel_id, scheduled_timestamp) -> dict:
    """Telegramga yuborish huquqini atomik claim qiladi.

    ``sent`` bo'lsa caller darhol skip qiladi (0 duplikat); ``processing``
    bo'lsa boshqa scheduler instance ishlayotgan bo'ladi; ``dead_letter``
    bo'lsa HECH QACHON qayta urinilmaydi. ``failed`` yozuv faqat backoff
    muddati (``next_retry_at``) o'tgan bo'lsa claim qilinadi.

    Urinish sanagichi (``attempt_count``) claim'da oshirilmaydi — u faqat
    ``SchedulerService.mark_as_failed`` da (real xatoda) yoki stale
    'processing' qayta olinganda (crash hisobi) oshadi.
    """
    key = build_delivery_idempotency_key(post_id, channel_id, scheduled_timestamp)
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO post_deliveries "
                "(post_id, channel_id, status, idempotency_key, scheduled_time) "
                "VALUES (%s, %s, 'pending', %s, %s) ON CONFLICT DO NOTHING",
                (int(post_id), _delivery_channel_number(channel_id), key,
                 scheduled_timestamp),
            )
            cur.execute(
                "SELECT status, attempt_count, telegram_message_id, next_retry_at, updated_at "
                "FROM post_deliveries WHERE idempotency_key = %s FOR UPDATE",
                (key,),
            )
            row = cur.fetchone()
            if not row:
                return {"claimed": False, "status": "missing", "idempotency_key": key}
            status, attempt_count, message_id, next_retry_at, updated_at = row
            if status == "sent":
                return {"claimed": False, "sent": True, "status": status,
                        "message_id": message_id, "idempotency_key": key}
            if status == "dead_letter":
                # Doimiy xato yoki urinishlar tugagan — qayta yuborilmaydi.
                return {"claimed": False, "sent": False, "dead": True,
                        "status": status, "idempotency_key": key}
            if status == "unknown":
                # UNKNOWN_DELIVERY: Telegram javobi olinmagan — xabar chiqqan
                # bo'lishi mumkin. Blind retry TAQIQLANADI (dublikat xavfi).
                return {"claimed": False, "sent": False, "unknown": True,
                        "status": status, "idempotency_key": key}
            if status == "processing":
                if not _delivery_processing_is_stale(updated_at):
                    return {"claimed": False, "sent": False, "status": status,
                            "idempotency_key": key}
                # Crash: avvalgi worker 'processing' da qolib ketgan. Urinishni
                # hisobga olamiz — cheksiz crash-loop bo'lmasligi uchun limit
                # oshsa to'g'ridan-to'g'ri 'dead_letter' qilinadi.
                new_attempt = (attempt_count or 0) + 1
                if new_attempt >= DELIVERY_MAX_ATTEMPTS:
                    cur.execute(
                        "UPDATE post_deliveries SET status = 'dead_letter', "
                        "attempt_count = %s, "
                        "last_error = 'stale processing: attempts exhausted', "
                        "next_retry_at = NULL, updated_at = NOW() "
                        "WHERE idempotency_key = %s",
                        (new_attempt, key),
                    )
                    return {"claimed": False, "sent": False, "dead": True,
                            "status": "dead_letter", "attempt_count": new_attempt,
                            "idempotency_key": key}
                cur.execute(
                    "UPDATE post_deliveries SET status = 'processing', "
                    "attempt_count = %s, updated_at = NOW() "
                    "WHERE idempotency_key = %s",
                    (new_attempt, key),
                )
                return {"claimed": True, "sent": False, "status": "processing",
                        "attempt_count": new_attempt, "stale_reclaim": True,
                        "idempotency_key": key}
            if status == "failed" and next_retry_at is not None:
                from datetime import timezone as _tz
                now_utc = datetime.now(_tz.utc)
                retry_at = next_retry_at
                if getattr(retry_at, "tzinfo", None) is None:
                    retry_at = retry_at.replace(tzinfo=_tz.utc)
                if retry_at > now_utc:
                    # Backoff hali o'tmagan — hozir claim qilib bo'lmaydi.
                    return {"claimed": False, "sent": False, "status": status,
                            "retry_pending": True, "next_retry_at": next_retry_at,
                            "attempt_count": attempt_count or 0,
                            "idempotency_key": key}
            cur.execute(
                "UPDATE post_deliveries SET status = 'processing', "
                "last_error = NULL, updated_at = NOW() "
                "WHERE idempotency_key = %s",
                (key,),
            )
            return {"claimed": True, "sent": False, "status": "processing",
                    "attempt_count": attempt_count or 0,
                    "idempotency_key": key}
    except Exception as e:
        logger.error("Delivery claim xatosi (post=%s, channel=%s): %s", post_id, channel_id, e)
        return {"claimed": False, "error": str(e), "idempotency_key": key}


def _delivery_processing_is_stale(updated_at) -> bool:
    """'processing' yozuv crash deb hisoblanadimi (10 daqiqadan eski)?"""
    if updated_at is None:
        return False
    try:
        from datetime import timezone as _tz
        now_utc = datetime.now(_tz.utc)
        stamp = updated_at
        if getattr(stamp, "tzinfo", None) is None:
            stamp = stamp.replace(tzinfo=_tz.utc)
        return (now_utc - stamp).total_seconds() > DELIVERY_STALE_PROCESSING_SECONDS
    except Exception:
        return False


def mark_post_delivery_sent(idempotency_key: str, telegram_message_id: int) -> bool:
    """Yuborilgan delivery'ni sent/message_id bilan idempotent belgilaydi.

    ``next_retry_at`` tozalanadi — 'sent' yozuv hech qachon retry navbatiga
    qaytmaydi.
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE post_deliveries SET status = 'sent', telegram_message_id = %s, "
                "last_error = NULL, next_retry_at = NULL, updated_at = NOW() "
                "WHERE idempotency_key = %s AND status <> 'sent'",
                (telegram_message_id, idempotency_key),
            )
            if cur.rowcount == 0:
                cur.execute(
                    "SELECT 1 FROM post_deliveries WHERE idempotency_key = %s AND status = 'sent'",
                    (idempotency_key,),
                )
                return cur.fetchone() is not None
        return True
    except Exception as e:
        logger.error("Delivery sent marker xatosi (%s): %s", idempotency_key, e)
        return False


def mark_post_delivery_unknown(idempotency_key: str, error: str) -> bool:
    """Delivery'ni ``unknown`` (UNKNOWN_DELIVERY) deb belgilaydi.

    Telegram API so'rovi ketdi, lekin javob olinmadi (TimedOut/NetworkError
    albom yuborishda) — xabar kanalga chiqqan-chiqmagani NOMA'LUM. Bunday
    yozuv scheduler tomonidan HECH QACHON avtomatik qayta yuborilmaydi
    (blind retry taqiqlanadi); admin health panelida ko'rinadi.
    'sent' va 'dead_letter' ustidan yozilmaydi.
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE post_deliveries SET status = 'unknown', last_error = %s, "
                "next_retry_at = NULL, updated_at = NOW() "
                "WHERE idempotency_key = %s AND status NOT IN ('sent', 'dead_letter')",
                (str(error)[:4000], idempotency_key),
            )
        _cache_clear("system_stats")
        return True
    except Exception as e:
        logger.error(f"Delivery unknown marker xatosi ({idempotency_key}): {e}")
        return False


def mark_post_delivery_failed(idempotency_key: str, error: str) -> bool:
    """Telegram yuborish xatosini qayd qiladi; keyingi retry claim qila oladi.

    Legacy imzo (PostAssist V2'gacha): backoff qo'ymaydi — keyingi urinish
    vaqti ``scheduled_posts.scheduled_time`` (``retry_post``) orqali boshqariladi.
    Backoff'li yangi oqim ``SchedulerService.mark_as_failed`` da.
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE post_deliveries SET status = 'failed', last_error = %s, "
                "next_retry_at = NULL, updated_at = NOW() "
                "WHERE idempotency_key = %s AND status NOT IN ('sent', 'dead_letter')",
                (str(error)[:4000], idempotency_key),
            )
        return True
    except Exception as e:
        logger.error("Delivery failed marker xatosi (%s): %s", idempotency_key, e)
        return False


def recover_processing_posts_on_startup(max_age_seconds: int = 0) -> dict:
    """Restart recovery (11-bosqich): jarayon qayta ishga tushganda 'processing'
    da qolib ketgan postlarni XAVFSIZ tiklaydi.

    Restartdan keyin 'processing' yozuvlar o'lik jarayonga tegishli, shuning
    uchun 10 daqiqalik stale chegarasini kutish shart emas (``max_age_seconds``
    bilan sozlanadi, 0 — darhol):

    1. Telegramga chiqqani ISBOTLANGAN postlar (``sent_message_id`` yoki
       ``sent_post_messages`` yozuvi) → ``posted`` — HECH QACHON qayta
       yuborilmaydi (0 duplikat).
    2. ``post_deliveries`` da ``sent`` bo'lgan postlar ham → ``posted``
       (scheduled_posts markeri yozilmay qolgan crash holati).
    3. ``post_deliveries`` da ``unknown`` (UNKNOWN_DELIVERY) bo'lganlar →
       ``unknown`` — blind retry TAQIQLANADI, admin ko'rib chiqadi.
    4. Qolgan (yuborilmagani aniq) postlar → ``pending``; ularning
       'processing' delivery yozuvlari ``failed`` (backoff'siz) qilinadi —
       keyingi tick darhol qayta claim qila oladi.

    Qaytadi: ``{"posted": n, "unknown": n, "requeued": n, "error": str|None}``.
    """
    result = {"posted": 0, "unknown": 0, "requeued": 0, "error": None}
    try:
        age = max(0, int(max_age_seconds or 0))
    except (TypeError, ValueError):
        age = 0
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE scheduled_posts
                SET status = 'posted'
                WHERE status = 'processing'
                  AND (sent_message_id IS NOT NULL
                       OR id IN (SELECT post_id FROM sent_post_messages)
                       OR id IN (SELECT post_id FROM post_deliveries WHERE status = 'sent'))
            """)
            result["posted"] = int(cur.rowcount or 0)
            cur.execute("""
                UPDATE scheduled_posts
                SET status = 'unknown'
                WHERE status = 'processing'
                  AND id IN (SELECT post_id FROM post_deliveries WHERE status = 'unknown')
            """)
            result["unknown"] = int(cur.rowcount or 0)
            cur.execute("""
                UPDATE scheduled_posts
                SET status = 'pending', processing_started_at = NULL
                WHERE status = 'processing'
                  AND sent_message_id IS NULL
                  AND id NOT IN (SELECT post_id FROM sent_post_messages)
                  AND (processing_started_at IS NULL
                       OR processing_started_at < NOW() - (%s || ' seconds')::INTERVAL)
                RETURNING id
            """, (str(age),))
            rows = cur.fetchall() or []
            result["requeued"] = len(rows)
            if rows:
                ids = [int(r[0]) for r in rows]
                cur.execute(
                    "UPDATE post_deliveries SET status = 'failed', next_retry_at = NULL, "
                    "last_error = COALESCE(last_error, 'restart recovery'), updated_at = NOW() "
                    "WHERE status = 'processing' AND post_id = ANY(%s)",
                    (ids,),
                )
        _cache_clear("system_stats")
    except Exception as e:
        logger.error(f"Restart recovery xatosi: {e}")
        result["error"] = f"{type(e).__name__}: {e}"[:200]
    return result


def recover_stale_processing_posts():
    """Server crash/restart paytida 'processing' holatida qolib ketgan postlarni tiklash (idempotent).

    1. Agar post allaqachon Telegramga yuborilgan bo'lsa (sent_message_id to'ldirilgan yoki
       sent_post_messages jadvalida qayd etilgan bo'lsa), statusi 'posted' deb belgilanadi —
       bunday postlar hech qachon qayta yuborilmaydi (idempotentlik kafolati).
    2. Yuborilmagan va 10 daqiqadan ko'p vaqt 'processing' holatida qolgan postlar
       qayta navbatga ('pending') qaytariladi.
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE scheduled_posts
                SET status = 'posted'
                WHERE status = 'processing'
                  AND (sent_message_id IS NOT NULL 
                       OR id IN (SELECT post_id FROM sent_post_messages));
            """)
            cur.execute("""
                UPDATE scheduled_posts
                SET status = 'pending', processing_started_at = NULL
                WHERE status = 'processing'
                  AND sent_message_id IS NULL
                  AND id NOT IN (SELECT post_id FROM sent_post_messages)
                  AND processing_started_at < NOW() - INTERVAL '10 minutes';
            """)
        _cache_clear("system_stats")
    except Exception as e:
        logger.error(f"Stale processing postlarni tiklashda xato: {e}")


def cleanup_old_data() -> dict:
    """Eski, keraksiz ma'lumotlarni o'chirish (scheduler har 6 soatda chaqiradi).

    Baza o'sib ketmasligi uchun: yuborilgan/ochilgan xabarlar, 30 kundan eski
    yakunlangan postlar va boshqa qoldiqlar tozalanadi.

    ⚠️ 5-bosqich: ``scheduled_posts.channel_id → channels(channel_id)`` FK'i
    ``ON DELETE CASCADE`` bilan, ya'ni kanal qatori o'chirilsa, uning BARCHA
    post tarixi (analitika shu ustunda qurilgan) ham ketadi. Shuning uchun bu
    tozalash endi kanal qatorini faqat unga bog'liq BIRORTA post qolmaganida
    o'chiradi — tarix hech qachon "reklama sanagichi tozalash" oqibatida
    yo'qolmaydi.
    """
    recover_stale_processing_posts()
    deleted = {"sent_post_messages": 0, "scheduled_posts": 0, "post_reactions": 0, "channels": 0}
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                DELETE FROM sent_post_messages
                WHERE (deleted_at IS NOT NULL AND deleted_at < NOW() - INTERVAL '30 days')
                   OR (delete_at IS NOT NULL AND delete_at < NOW() - INTERVAL '90 days')
            """)
            deleted["sent_post_messages"] = cur.rowcount

            cur.execute("""
                DELETE FROM scheduled_posts
                WHERE status IN ('posted', 'cancelled', 'failed', 'completed')
                  AND created_at < NOW() - INTERVAL '30 days'
            """)
            deleted["scheduled_posts"] = cur.rowcount

            # FK (fk_post_reactions_post) ishlaganda bunday yetim qatorlar
            # umudan paydo bo'lmaydi — bu sorov eski/nofaol (NOT VALID)
            # bazalarda himoya to'r sifatida qoladi.
            cur.execute("DELETE FROM post_reactions WHERE post_id NOT IN (SELECT id FROM scheduled_posts)")
            deleted["post_reactions"] = cur.rowcount

            cur.execute("""
                DELETE FROM channels c
                 WHERE c.is_active = FALSE
                   AND c.created_at < NOW() - INTERVAL '90 days'
                   AND NOT EXISTS (
                       SELECT 1 FROM scheduled_posts sp WHERE sp.channel_id = c.channel_id
                   )
            """)
            deleted["channels"] = cur.rowcount

            cur.execute("DELETE FROM channel_posts_history WHERE created_at < NOW() - INTERVAL '90 days'")
            deleted["channel_posts_history"] = cur.rowcount
        _cache_clear()
        return deleted
    except Exception as e:
        logger.error(f"DB tozalash xatosi: {e}")
        return deleted


def find_next_queue_slot(slots: list, occupied: list, now, max_days: int = 7) -> tuple:
    """Eng yaqin bo'sh slotni topadi.

    Returns: (datetime, date_label) yoki (None, None).
    """
    parsed_slots = []
    for s in slots:
        try:
            hh, mm = s.split(":")
            parsed_slots.append((int(hh), int(mm)))
        except Exception:
            continue
    if not parsed_slots:
        return None, None

    parsed_slots.sort()
    occupied_set = set(occupied)
    today = now.date()

    for day_offset in range(max_days):
        target_date = today + timedelta(days=day_offset)
        is_today = (day_offset == 0)

        for hh, mm in parsed_slots:
            if is_today:
                slot_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if slot_dt <= now:
                    continue
            else:
                slot_dt = tashkent_tz.localize(
                    datetime(target_date.year, target_date.month, target_date.day, hh, mm)
                )

            if (hh, mm) not in occupied_set:
                if day_offset == 0:
                    label = "Bugun"
                elif day_offset == 1:
                    label = "Ertaga"
                else:
                    label = target_date.strftime("%d.%m.%Y")
                return slot_dt, label

        occupied_set = set()

    return None, None