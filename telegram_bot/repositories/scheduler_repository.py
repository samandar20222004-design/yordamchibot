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
import os
from datetime import datetime, timedelta
import logging
import re


from database import tashkent_tz  # noqa: F401
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
        # ⏱ TTFP/TTFV: haftalik reja ham "birinchi post rejalashtirish"
        # amali hisoblanadi (jarayon xotirasi, best-effort).
        try:
            from services.onboarding_telemetry import record_first_post

            record_first_post(user_id)
        except Exception:  # noqa: BLE001 — analitika best-effort
            logger.debug("TTFP belgilashda xato (week plan user=%s)", user_id,
                         exc_info=True)
        # ACTION-BASED REFERAL MUKOFOTI: birinchi yaroqli amal
        # (haftalik rejalashtirish) konversiyani ham hisobga oladi.
        # Idempotent va fail-soft: navbat natijasi hook'dan BOG'LIQ EMAS.
        try:
            from services.referral_service import ReferralService

            ReferralService.register_first_action(user_id)
        except Exception:  # noqa: BLE001 — referal hook'i best-effort
            logger.debug("Referral konversiya belgilashda xato (user=%s)",
                         user_id, exc_info=True)
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


#``post_deliveries.last_error`` ichidagi "kanal tekshiruvi
#: kutilmoqda" belgisi. Format: ``AMBIGUOUS_VERIFY attempt=<n> | <xato>``.
#: Shu markerli yozuv avtomatik (ko'r-ko'rrona) qayta yuborilmaydi.
DELIVERY_VERIFY_MARKER = "AMBIGUOUS_VERIFY"
_DELIVERY_VERIFY_RE = re.compile(re.escape(DELIVERY_VERIFY_MARKER) + r"\s+attempt=(\d+)")


def delivery_verify_pending(last_error) -> bool:
    """Yozuvda "verify kutilmoqda" markeri bormi (sof funksiya)."""
    return bool(_DELIVERY_VERIFY_RE.search(str(last_error or "")))


def delivery_verify_attempt(last_error) -> int:
    """Markerdagi tekshiruv urinish raqami (marker yo'q bo'lsa ``0``)."""
    match = _DELIVERY_VERIFY_RE.search(str(last_error or ""))
    if not match:
        return 0
    try:
        return max(0, int(match.group(1)))
    except (TypeError, ValueError):
        return 0


def mark_post_delivery_verify_pending(idempotency_key: str, error, attempt: int = 1,
                                      delay_seconds: float = 30.0) -> dict:
    """Noaniq (ambiguous) delivery'ni "kanal tekshiruvi kutilmoqda" holatiga o'tkazadi.

    Yozuv ``failed`` bo'lib qoladi (claim uni ``next_retry_at`` dan keyin
    qayta oladi), lekin ``last_error`` da :data:`DELIVERY_VERIFY_MARKER`
    turadi — scheduler shu belgi bo'yicha Telegramga YUBORMASDAN avval
    kanalni tekshiradi (dublikat oldini olish).

    ``sent``/``dead_letter``/``unknown`` yozuvlar ustidan hech qachon yozmaydi.
    """
    try:
        key = str(idempotency_key or "")
        if not key:
            return {"ok": False, "reason": "missing_key"}
        try:
            attempt = max(1, int(attempt))
        except (TypeError, ValueError):
            attempt = 1
        try:
            delay = max(1.0, float(delay_seconds))
        except (TypeError, ValueError):
            delay = 30.0
        with db_cursor(commit=True) as cur:
            cur.execute(
                "SELECT status FROM post_deliveries WHERE idempotency_key = %s FOR UPDATE",
                (key,),
            )
            row = cur.fetchone()
            if not row:
                return {"ok": False, "reason": "missing", "idempotency_key": key}
            status = row[0]
            if status in ("sent", "dead_letter", "unknown"):
                return {"ok": False, "reason": f"status_{status}",
                        "idempotency_key": key}
            marker = f"{DELIVERY_VERIFY_MARKER} attempt={attempt}"
            detail = str(error or "")[:300]
            if detail:
                marker = f"{marker} | {detail}"
            cur.execute(
                "UPDATE post_deliveries SET status = 'failed', "
                "attempt_count = GREATEST(COALESCE(attempt_count, 0), %s), "
                "last_error = %s, next_retry_at = NOW() + (%s || ' seconds')::INTERVAL, "
                "updated_at = NOW() WHERE idempotency_key = %s",
                (attempt, marker, str(int(delay)), key),
            )
        _cache_clear("system_stats")
        return {"ok": True, "status": "failed", "verify_pending": True,
                "attempt": attempt, "retry_in": int(delay), "idempotency_key": key}
    except Exception as e:
        logger.error("Delivery verify_pending marker xatosi (%s): %s", idempotency_key, e)
        return {"ok": False, "reason": "database_error", "idempotency_key": str(idempotency_key or "")}


def clear_post_delivery_verify_pending(idempotency_key: str) -> bool:
    """"Verify kutilmoqda" belgisini olib tashlaydi (post yo'qligi tasdiqlanganda).

    Yozuv ``failed`` + ``next_retry_at = NOW()`` bo'ladi — keyingi claim uni
    darhol oladi va xavfsiz qayta yuboradi. ``sent``/``dead_letter`` ustidan
    yozilmaydi (0 duplikat kafolati saqlanadi).
    """
    try:
        key = str(idempotency_key or "")
        if not key:
            return False
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE post_deliveries SET status = 'failed', last_error = NULL, "
                "next_retry_at = NOW(), updated_at = NOW() "
                "WHERE idempotency_key = %s AND status NOT IN ('sent', 'dead_letter')",
                (key,),
            )
            return True
    except Exception as e:
        logger.error("Delivery verify_pending tozalash xatosi (%s): %s", idempotency_key, e)
        return False


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
            # post darajasidagi advisory lock
            # (transaction ichida) — bir xil post uchun TURLI idempotency
            # kalitlari bilan kelgan parallel worker'lar ham serialize bo'ladi.
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"post_delivery:{int(post_id)}",),
            )
            cur.execute(
                "INSERT INTO post_deliveries "
                "(post_id, channel_id, status, idempotency_key, scheduled_time) "
                "VALUES (%s, %s, 'pending', %s, %s) ON CONFLICT DO NOTHING",
                (int(post_id), _delivery_channel_number(channel_id), key,
                 scheduled_timestamp),
            )
            if cur.rowcount == 1:
                # YANGI qator (masalan ``retry_post`` scheduled_time'ni o'zgartirgani uchun kalit o'zgardi):
                # oldingi qatordagi "kanal tekshiruvi kutilmoqda" markeri yo'qolsa, keyingi urinish kanalni
                # TEKSHIRMAY ko'r-ko'rona qayta yuborar edi (AUDIT-002). Faqat shu marker ko'chiriladi;
                # 'sent' qatordan (recurring keyingi davr) va markersiz qatordan HECH NARSA ko'chmaydi,
                # attempt_count/backoff semantikasi o'zgarmaydi.
                # ``DELIVERY_CARRY_ATTEMPTS`` (SUKUT YOQILGAN; ``0/false/no/off`` o'chiradi): oldingi 'failed' qatorning
                # attempt_count'i ham ko'chadi — hujjatlangan backoff (30s/2m/5m/15m) va "5-urinishda dead_letter" qoidasi
                # retry'larda ishlaydi. O'chirilsa sanagich har retry'da 0 dan boshlanadi (eski xulq, cheksiz retry).
                # Diqqat: uzoq (~22 daqiqa+) Telegram uzilishida post 'failed' (dead_letter) bo'ladi.
                cur.execute(
                    "UPDATE post_deliveries d SET last_error = p.last_error "
                    "FROM (SELECT status, last_error FROM post_deliveries "
                    "      WHERE post_id = %s AND idempotency_key <> %s ORDER BY id DESC LIMIT 1) p "
                    "WHERE d.idempotency_key = %s AND p.status = 'failed' AND p.last_error LIKE %s",
                    (int(post_id), key, key, DELIVERY_VERIFY_MARKER + "%"),
                )
                if os.getenv("DELIVERY_CARRY_ATTEMPTS", "1").strip().lower() not in ("0", "false", "no", "off"):
                    cur.execute(
                        "UPDATE post_deliveries d SET attempt_count = COALESCE(p.attempt_count, 0) "
                        "FROM (SELECT status, attempt_count FROM post_deliveries "
                        "      WHERE post_id = %s AND idempotency_key <> %s ORDER BY id DESC LIMIT 1) p "
                        "WHERE d.idempotency_key = %s AND p.status = 'failed'",
                        (int(post_id), key, key),
                    )
            cur.execute(
                "SELECT status, attempt_count, telegram_message_id, next_retry_at, updated_at, "
                "last_error "
                "FROM post_deliveries WHERE idempotency_key = %s FOR UPDATE",
                (key,),
            )
            row = cur.fetchone()
            if not row:
                return {"claimed": False, "status": "missing", "idempotency_key": key}
            status, attempt_count, message_id, next_retry_at, updated_at = row[:5]
            last_error = row[5] if len(row) > 5 else None
            verify_pending = delivery_verify_pending(last_error)
            verify_attempt = delivery_verify_attempt(last_error)

            def _verify_fields():
                """Claim natijasiga verify_pending holatini qo'shadi."""
                return {"last_error": last_error, "verify_pending": verify_pending,
                        "verify_attempt": verify_attempt}

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
                        "idempotency_key": key, **_verify_fields()}
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
                # AUDIT-008: avvalgi worker Telegram'ga yuborib ulgurgan-ulgurmagani NOMA'LUM (crash). Marker qo'yiladi:
                # scheduler yuborishdan OLDIN kanalni tekshiradi (bor -> yubormaydi; yo'q -> yuboradi; o'qib bo'lmasa ->
                # keyinroq, so'ng 'unknown'). Mavjud marker (urinish raqami) saqlanadi.
                cur.execute(
                    "UPDATE post_deliveries SET status = 'processing', "
                    "attempt_count = %s, "
                    "last_error = CASE WHEN last_error LIKE %s THEN last_error ELSE %s END, "
                    "updated_at = NOW() "
                    "WHERE idempotency_key = %s",
                    (new_attempt, DELIVERY_VERIFY_MARKER + "%",
                     DELIVERY_VERIFY_MARKER + " attempt=0 | stale processing", key),
                )
                stale_error = last_error if verify_pending else DELIVERY_VERIFY_MARKER + " attempt=0 | stale processing"
                return {"claimed": True, "sent": False, "status": "processing",
                        "attempt_count": new_attempt, "stale_reclaim": True,
                        "idempotency_key": key, "last_error": stale_error,
                        "verify_pending": True, "verify_attempt": verify_attempt}
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
                            "idempotency_key": key, **_verify_fields()}
            cur.execute(
                # verify_pending markeri (AMBIGUOUS_VERIFY...) SAQLANADI —
                # ishchi crash bo'lsa ham keyingi claim uni ko'radi va telegramga
                # yuborishdan oldin kanal tekshiruvini o'tkazadi.
                "UPDATE post_deliveries SET status = 'processing', "
                "last_error = CASE WHEN last_error LIKE %s THEN last_error "
                "ELSE NULL END, updated_at = NOW() "
                "WHERE idempotency_key = %s",
                (DELIVERY_VERIFY_MARKER + "%", key),
            )
            return {"claimed": True, "sent": False, "status": "processing",
                    "attempt_count": attempt_count or 0,
                    "idempotency_key": key, **_verify_fields()}
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
    """Restart recovery: jarayon qayta ishga tushganda 'processing'
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
    # Recurring post: oldingi davrlardan qolgan ``sent_message_id`` / ``sent_post_messages`` / eski 'sent' delivery
    # "shu davr yuborildi" isboti EMAS (AUDIT-003). Recurring uchun dalil — FAQAT shu davrning delivery yozuvi:
    # ``post_deliveries.status='sent'`` va ``scheduled_time`` = postning joriy ``scheduled_time``.
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
                  AND ((COALESCE(recurrence_type, 'none') IN ('none', '')
                        AND (sent_message_id IS NOT NULL
                             OR id IN (SELECT post_id FROM sent_post_messages)
                             OR id IN (SELECT post_id FROM post_deliveries WHERE status = 'sent')))
                       OR (COALESCE(recurrence_type, 'none') NOT IN ('none', '')
                           AND EXISTS (SELECT 1 FROM post_deliveries d
                                        WHERE d.post_id = scheduled_posts.id AND d.status = 'sent'
                                          AND d.scheduled_time = scheduled_posts.scheduled_time)))
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
                  AND (COALESCE(recurrence_type, 'none') NOT IN ('none', '')
                       OR (sent_message_id IS NULL
                           AND id NOT IN (SELECT post_id FROM sent_post_messages)))
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
                    "last_error = CASE WHEN last_error LIKE %s THEN last_error "
                    "ELSE %s || COALESCE(last_error, 'restart recovery') END, updated_at = NOW() "
                    "WHERE status = 'processing' AND post_id = ANY(%s)",
                    (DELIVERY_VERIFY_MARKER + "%", DELIVERY_VERIFY_MARKER + " attempt=0 | ", ids),
                )
        _cache_clear("system_stats")
    except Exception as e:
        logger.error(f"Restart recovery xatosi: {e}")
        result["error"] = f"{type(e).__name__}: {e}"[:200]
    return result


def get_recent_problem_deliveries(lookback_seconds: int = 900) -> list:
    """Yaqinda ``dead_letter`` / ``unknown`` bo'lgan yetkazishlar (post egasiga xabar berish uchun).

    Faqat post HOZIR ham ``failed`` / ``unknown`` bo'lsa (qayta rejalangan postlar kirmaydi).
    Qaytadi: ``(delivery_id, post_id, user_id, channel_id, delivery_status, last_error, content_preview, channel_title)``.
    DB xatosida bo'sh ro'yxat (istisno yo'q).
    """
    try:
        age = max(1, int(lookback_seconds or 900))
    except (TypeError, ValueError):
        age = 900
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT d.id, d.post_id, p.user_id, p.channel_id, d.status, d.last_error, "
                "LEFT(COALESCE(p.content, ''), 80), c.channel_title "
                "FROM post_deliveries d "
                "JOIN scheduled_posts p ON p.id = d.post_id "
                "LEFT JOIN channels c ON c.channel_id = p.channel_id "
                "WHERE d.status IN ('dead_letter', 'unknown') "
                "AND p.status IN ('failed', 'unknown') "
                "AND d.updated_at > NOW() - (%s || ' seconds')::INTERVAL "
                "ORDER BY d.id LIMIT 200",
                (str(age),),
            )
            return list(cur.fetchall() or [])
    except Exception as e:
        logger.error(f"Muammoli yetkazishlarni o'qish xatosi: {e}")
        return []


def recover_stale_processing_posts():
    """Server crash/restart paytida 'processing' holatida qolib ketgan postlarni tiklash (idempotent).

    1. Agar post allaqachon Telegramga yuborilgan bo'lsa (sent_message_id to'ldirilgan yoki
       sent_post_messages jadvalida qayd etilgan bo'lsa), statusi 'posted' deb belgilanadi —
       bunday postlar hech qachon qayta yuborilmaydi (idempotentlik kafolati).
    2. Yuborilmagan va 10 daqiqadan ko'p vaqt 'processing' holatida qolgan postlar
       qayta navbatga ('pending') qaytariladi.
    """
    # Recurring post: oldingi davrlardan qolgan ``sent_message_id`` / ``sent_post_messages`` / eski 'sent' delivery
    # "shu davr yuborildi" isboti EMAS (AUDIT-003). Recurring uchun dalil — FAQAT shu davrning delivery yozuvi:
    # ``post_deliveries.status='sent'`` va ``scheduled_time`` = postning joriy ``scheduled_time``.
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE scheduled_posts
                SET status = 'posted'
                WHERE status = 'processing'
                  AND ((COALESCE(recurrence_type, 'none') IN ('none', '')
                        AND (sent_message_id IS NOT NULL
                             OR id IN (SELECT post_id FROM sent_post_messages)))
                       OR (COALESCE(recurrence_type, 'none') NOT IN ('none', '')
                           AND EXISTS (SELECT 1 FROM post_deliveries d
                                        WHERE d.post_id = scheduled_posts.id AND d.status = 'sent'
                                          AND d.scheduled_time = scheduled_posts.scheduled_time)))
            """)
            cur.execute("""
                UPDATE scheduled_posts
                SET status = 'pending', processing_started_at = NULL
                WHERE status = 'processing'
                  AND (COALESCE(recurrence_type, 'none') NOT IN ('none', '')
                       OR (sent_message_id IS NULL
                           AND id NOT IN (SELECT post_id FROM sent_post_messages)))
                  AND processing_started_at < NOW() - INTERVAL '10 minutes';
            """)
        _cache_clear("system_stats")
    except Exception as e:
        logger.error(f"Stale processing postlarni tiklashda xato: {e}")


def cleanup_old_data() -> dict:
    """Eski, keraksiz ma'lumotlarni o'chirish (scheduler har 6 soatda chaqiradi).

    Baza o'sib ketmasligi uchun: yuborilgan/ochilgan xabarlar, 30 kundan eski
    yakunlangan postlar va boshqa qoldiqlar tozalanadi.

    ``scheduled_posts.channel_id → channels(channel_id)`` FK'i
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
        # Obunachilar snapshot'lari: 400 kundan eskisi o'chiriladi (yillik taqqoslash uchun yetarli). ALOHIDA tranzaksiya:
        # jadval hali yo'q bo'lsa yuqoridagi tozalash bekor bo'lmaydi.
        try:
            with db_cursor(commit=True) as cur:
                cur.execute("DELETE FROM channel_member_counts WHERE snapshot_date < CURRENT_DATE - INTERVAL '400 days'")
                deleted["channel_member_counts"] = cur.rowcount
                # Kanal qatori o'chirilgan (90 kunlik nofaol tozalash) bo'lsa snapshot'lari ham ketadi: qayta ulansa
                # eski hisoblar "tarix" bo'lib qaytib chiqmasligi va egasiz saqlanmasligi uchun.
                cur.execute(
                    "DELETE FROM channel_member_counts m "
                    "WHERE NOT EXISTS (SELECT 1 FROM channels c WHERE c.channel_id = m.channel_id)"
                )
                deleted["channel_member_counts"] += cur.rowcount
        except Exception as e:
            logger.warning(f"Obunachilar snapshot'larini tozalash xatosi: {e}")
        # Ovozli rejalash kvotasi: PRO uchun faqat oxirgi 24 soat kerak -> 3 kundan eskisi o'chiriladi. Free'ning butun-umr
        # hisobi saqlanadi (faqat hozirgi PRO/enterprise foydalanuvchilarning eski qatorlari tozalanadi). ALOHIDA tranzaksiya.
        try:
            with db_cursor(commit=True) as cur:
                cur.execute(
                    "DELETE FROM voice_schedule_usage v WHERE v.used_at < NOW() - INTERVAL '3 days' "
                    "AND EXISTS (SELECT 1 FROM users u WHERE u.user_id = v.user_id AND u.plan_type IN ('pro', 'ultra', 'enterprise'))"
                )
                deleted["voice_schedule_usage"] = cur.rowcount
        except Exception as e:
            logger.warning(f"Ovozli rejalash kvotasini tozalash xatosi: {e}")
        # Mini App qoralamalari: o'qishda 48 soatdan eskisi hisobga olinmaydi (miniapp_api.drafts.DRAFT_TTL_HOURS);
        # jadval cheksiz to'planmasligi uchun 7 kundan eskisi o'chiriladi. ALOHIDA tranzaksiya: jadval bo'lmasa
        # yuqoridagi tozalash bekor bo'lmaydi.
        try:
            with db_cursor(commit=True) as cur:
                cur.execute("DELETE FROM miniapp_drafts WHERE updated_at < NOW() - INTERVAL '7 days'")
                deleted["miniapp_drafts"] = cur.rowcount
        except Exception as e:
            logger.warning(f"Mini App qoralamalarini tozalash xatosi: {e}")
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
                from services.user_timezone import utz  # kech import: `services` paketi database bilan aylanma import qilmasin

                slot_dt = utz().localize(
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