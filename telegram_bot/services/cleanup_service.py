"""CleanupService — PostAssist V2 (9-BOSQICH): davriy ma'lumotlar tozalash.

Baza (Neon) vaqt o'tishi bilan shishib ketmasligi uchun scheduler har 24 soatda
bir marta (kechasi soat 03:00, Toshkent vaqti) ``cleanup_old_records()``
funksiyasini chaqiradi. U quyidagilarni tozalaydi:

1. **post_deliveries** — 30 kundan eski, holati ``'sent'`` bo'lgan delivery
   jurnallari. ``sent`` delivery — allaqachon Telegramga chiqqan postning
   idempotency markeri; 30 kundan keyin post qayta navbatga tusha olmaydi
   (``scheduled_posts`` ning o'zi ham 30 kunda tozalanadi), shuning uchun
   marker xavfsiz o'chiriladi. ``pending``/``processing``/``failed``/
   ``dead_letter`` yozuvlarga **TEGILMAYDI** (ular faol yoki audit).

2. **Vaqtinchalik sessiya / kredit qoldiqlari** — bekor qilingan yoki 60
   kundan eski bo'lgan "vaqtinchalik" yozuvlar:
   * ``scheduled_posts`` — ``cancelled`` (bekor qilingan) va ``failed``
     holatidagi, 60 kundan eski postlar (foydalanuvchi sessiyasining
     bekor qilingan qoldiqlari; bog'liq delivery/reaksiya qatorlari FK
     ``ON DELETE CASCADE`` bilan birga ketadi);
   * ``payment_receipts`` — ``rejected`` (bekor qilingan) va 60 kundan eski
     kredit/to'lov cheklari (fayl ID + caption vaqtinchalik ma'lumot;
     ``approved`` cheklar audit sifatida saqlanadi);
   * ``payments`` — ``failed`` holatidagi (muvaffaqiyatsiz/bekor) 60 kundan
     eski to'lov urinishlari (``succeeded``/``refunded`` — doimiy audit);
   * ``sent_post_messages`` — 60 kundan oldin o'chirilgan (``deleted_at``)
     kanal xabarlari yozuvlari.

**Xavfsizlik qoidalari** (barcha tozalashlar uchun bir xil):

* Har bir paket **alohida tranzaksiya**, hajmi ``LIMIT 1000``
  (``CLEANUP_BATCH_SIZE``): katta jadval uzoq qulflanmaydi, WAL/lock bosimi
  kichik bo'ladi, scheduler'ning post yuborishiga xalaqit bermaydi.
* Paket ichida ``SELECT ... FOR UPDATE SKIP LOCKED`` — hozir boshqa
  tranzaksiya (masalan, yuborayotgan worker) ushlab turgan qatorlar
  o'tkazib yuboriladi, kutilmaydi.
* Faqat yosh (``created_at``/``updated_at``) chegarasi O'TGAN va holati
  aniq "tugagan" yozuvlar o'chadi — **yangi va faol** yozuvlarga (pending,
  processing, yaqinda yuborilgan) tegilmaydi.
* Har bir jadval uchun paketlar soni ``CLEANUP_MAX_BATCHES`` bilan
  cheklangan — bir kechada juda ulkan orqada qolgan hajm bo'lsa ham
  tozalash chegaralangan vaqtda tugaydi (qolgani ertaga davom etadi).
* Har bir amal o'z ``try/except`` ida — bittasi xato bersa, boshqalari
  davom etadi; funksiya HECH QACHON istisno ko'tarmaydi.
* Graceful shutdown boshlangan bo'lsa (``lifecycle.is_shutting_down()``)
  yangi paket boshlanmaydi — joriy paket tugab, funksiya qaytadi.

Foydalanish::

    from services.cleanup_service import cleanup_old_records
    summary = await cleanup_old_records()
    # {"post_deliveries_sent": 1200, "scheduled_posts_stale": 40, ...,
    #  "total": 1240, "batches": 3, "errors": [], "duration_ms": 87}
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import database as db
from services import lifecycle_service as lifecycle

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


#: post_deliveries 'sent' jurnallari uchun saqlash muddati (kun).
DELIVERY_RETENTION_DAYS = _env_int("CLEANUP_DELIVERY_RETENTION_DAYS", 30, 1, 3650)
#: Vaqtinchalik sessiya/kredit qoldiqlari uchun saqlash muddati (kun).
TEMP_RETENTION_DAYS = _env_int("CLEANUP_TEMP_RETENTION_DAYS", 60, 1, 3650)
#: Bitta tranzaksiyada o'chiriladigan qatorlar soni (LIMIT).
CLEANUP_BATCH_SIZE = _env_int("CLEANUP_BATCH_SIZE", 1000, 1, 10000)
#: Bitta ishga tushishda har bir jadval uchun maks. paketlar soni.
CLEANUP_MAX_BATCHES = _env_int("CLEANUP_MAX_BATCHES", 50, 1, 10000)

#: Scheduler jobi: har 24 soatda bir marta, kechasi soat 03:00 (Toshkent).
CLEANUP_CRON_HOUR = _env_int("CLEANUP_CRON_HOUR", 3, 0, 23)
CLEANUP_CRON_MINUTE = _env_int("CLEANUP_CRON_MINUTE", 0, 0, 59)
CLEANUP_JOB_ID = "cleanup_old_records"

#: Bekor qilingan/yakunlanmagan sessiya qoldiqlari deb hisoblanadigan
#: scheduled_posts holatlari (pending/processing/posted/completed — TEGILMAYDI).
STALE_POST_STATUSES = ("cancelled", "failed")


# ──────────────────────────────────────────────────────────────
# PAKETLI O'CHIRISH YADROSI
# ──────────────────────────────────────────────────────────────
def _delete_batch(table: str, where_sql: str, params: tuple,
                  limit: int, order_by: str = "id") -> int:
    """Bitta paketni ALOHIDA tranzaksiyada o'chiradi va o'chirilgan qatorlar
    sonini qaytaradi.

    ``SELECT ... FOR UPDATE SKIP LOCKED`` — boshqa tranzaksiya ushlab
    turgan qatorlar o'tkazib yuboriladi (qulf kutilmaydi). Faqat oq
    ro'yxatdagi jadval nomlari ishlatiladi (SQL konkatensiyasi xavfsiz).
    """
    assert table in _TABLES_WHITELIST, table
    sql = (
        f"WITH victims AS ("
        f"    SELECT id FROM {table} WHERE {where_sql} "
        f"    ORDER BY {order_by} LIMIT %s FOR UPDATE SKIP LOCKED"
        f") "
        f"DELETE FROM {table} t USING victims v WHERE t.id = v.id"
    )
    with db.db_transaction() as cur:
        cur.execute(sql, tuple(params) + (int(limit),))
        return int(cur.rowcount or 0)


_TABLES_WHITELIST = frozenset({
    "post_deliveries",
    "scheduled_posts",
    "payment_receipts",
    "payments",
    "sent_post_messages",
})


async def _run_batched(name: str, table: str, where_sql: str, params: tuple,
                       summary: dict, batch_size: int, max_batches: int) -> int:
    """``where_sql`` ga mos qatorlarni paketlab o'chiradi (event loop'ni
    bloklamasdan — har paket ``db.run_db`` orqali alohida thread'da)."""
    deleted_total = 0
    batches = 0
    while batches < max_batches:
        if lifecycle.is_shutting_down():
            summary.setdefault("stopped_early", []).append(name)
            break
        try:
            deleted = await db.run_db(
                _delete_batch, table, where_sql, params, batch_size,
            )
        except Exception as e:  # noqa: BLE001 — bitta amal boshqalarini to'xtatmasin
            logger.error("Cleanup [%s] paketida xato: %s", name, e)
            summary["errors"].append(f"{name}: {type(e).__name__}: {e}"[:300])
            break
        batches += 1
        deleted_total += deleted
        if deleted < batch_size:
            break
        # Paketlar orasida event loop'ga nafas — scheduler/handlerlar ishlasin.
        await asyncio.sleep(0)
    summary[name] = deleted_total
    summary["batches"] += batches
    return deleted_total


# ──────────────────────────────────────────────────────────────
# ASOSIY FUNKSIYA
# ──────────────────────────────────────────────────────────────
async def cleanup_old_records(batch_size: int = None, max_batches: int = None,
                              delivery_days: int = None,
                              temp_days: int = None) -> dict:
    """Eski yozuvlarni paketlab tozalaydi va hisobot (dict) qaytaradi.

    Parametrlar berilmasa modul konstantalari (env) ishlatiladi. Funksiya
    HECH QACHON istisno ko'tarmaydi — xatolar ``summary["errors"]`` da.
    """
    batch_size = int(batch_size or CLEANUP_BATCH_SIZE)
    max_batches = int(max_batches or CLEANUP_MAX_BATCHES)
    delivery_days = int(delivery_days or DELIVERY_RETENTION_DAYS)
    temp_days = int(temp_days or TEMP_RETENTION_DAYS)
    batch_size = max(1, min(batch_size, 10000))
    max_batches = max(1, max_batches)

    started = time.monotonic()
    summary: dict = {
        "post_deliveries_sent": 0,
        "scheduled_posts_stale": 0,
        "payment_receipts_rejected": 0,
        "payments_failed": 0,
        "sent_post_messages_deleted": 0,
        "total": 0,
        "batches": 0,
        "errors": [],
        "batch_size": batch_size,
        "delivery_retention_days": delivery_days,
        "temp_retention_days": temp_days,
    }

    if lifecycle.is_shutting_down():
        summary["skipped"] = "shutting_down"
        logger.info("Cleanup: bot yopilmoqda — tozalash o'tkazib yuborildi.")
        return summary

    # 1) post_deliveries — 30 kundan eski 'sent' jurnallari.
    #    updated_at — 'sent' ga o'tgan payt (mark_post_delivery_sent NOW() yozadi);
    #    u NULL bo'lgan eski qatorlar uchun created_at ga qaraladi.
    await _run_batched(
        "post_deliveries_sent", "post_deliveries",
        "status = 'sent' "
        "AND COALESCE(updated_at, created_at) < NOW() - (%s * INTERVAL '1 day')",
        (delivery_days,), summary, batch_size, max_batches,
    )

    # 2) Bekor qilingan sessiya qoldiqlari — scheduled_posts (cancelled/failed,
    #    60+ kun). Bog'liq post_deliveries / post_reactions FK CASCADE bilan ketadi.
    await _run_batched(
        "scheduled_posts_stale", "scheduled_posts",
        "status = ANY(%s) AND created_at < NOW() - (%s * INTERVAL '1 day')",
        (list(STALE_POST_STATUSES), temp_days), summary, batch_size, max_batches,
    )

    # 3) Rad etilgan (bekor qilingan) kredit/to'lov cheklari — 60+ kun.
    await _run_batched(
        "payment_receipts_rejected", "payment_receipts",
        "status = 'rejected' "
        "AND COALESCE(reviewed_at, created_at) < NOW() - (%s * INTERVAL '1 day')",
        (temp_days,), summary, batch_size, max_batches,
    )

    # 4) Muvaffaqiyatsiz to'lov urinishlari — 60+ kun (succeeded/refunded — audit).
    await _run_batched(
        "payments_failed", "payments",
        "status = 'failed' AND created_at < NOW() - (%s * INTERVAL '1 day')",
        (temp_days,), summary, batch_size, max_batches,
    )

    # 5) Kanaldan allaqachon o'chirilgan xabarlar yozuvlari — 60+ kun.
    await _run_batched(
        "sent_post_messages_deleted", "sent_post_messages",
        "deleted_at IS NOT NULL AND deleted_at < NOW() - (%s * INTERVAL '1 day')",
        (temp_days,), summary, batch_size, max_batches,
    )

    summary["total"] = (
        summary["post_deliveries_sent"]
        + summary["scheduled_posts_stale"]
        + summary["payment_receipts_rejected"]
        + summary["payments_failed"]
        + summary["sent_post_messages_deleted"]
    )
    summary["duration_ms"] = int((time.monotonic() - started) * 1000)

    if summary["total"]:
        try:
            db._cache_clear("system_stats")
        except Exception:  # noqa: BLE001
            pass
    level = logging.WARNING if summary["errors"] else logging.INFO
    logger.log(
        level,
        "Cleanup yakunlandi: deliveries(sent)=%d, posts(cancelled/failed)=%d, "
        "receipts(rejected)=%d, payments(failed)=%d, sent_msgs(deleted)=%d "
        "| jami=%d, paketlar=%d, %d ms, xatolar=%d",
        summary["post_deliveries_sent"], summary["scheduled_posts_stale"],
        summary["payment_receipts_rejected"], summary["payments_failed"],
        summary["sent_post_messages_deleted"], summary["total"],
        summary["batches"], summary["duration_ms"], len(summary["errors"]),
    )
    return summary


def cleanup_old_records_sync(**kwargs) -> dict:
    """Sinxron o'ram (admin buyruqlari / skriptlar uchun)."""
    return asyncio.run(cleanup_old_records(**kwargs))


class CleanupService:
    """Servis qatlamidagi nom (boshqa servislar uslubida)."""

    BATCH_SIZE = CLEANUP_BATCH_SIZE
    DELIVERY_RETENTION_DAYS = DELIVERY_RETENTION_DAYS
    TEMP_RETENTION_DAYS = TEMP_RETENTION_DAYS
    CRON_HOUR = CLEANUP_CRON_HOUR
    CRON_MINUTE = CLEANUP_CRON_MINUTE
    JOB_ID = CLEANUP_JOB_ID

    cleanup_old_records = staticmethod(cleanup_old_records)
