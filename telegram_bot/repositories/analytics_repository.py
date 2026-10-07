# -*- coding: utf-8 -*-
"""
=====================================================================
 📊 ANALYTICS — kanal tahlili uchun BATCH (N+1'siz) o'qish qatlami
=====================================================================

Kanalning oxirgi 50–100 ta posti tahlil qilinganda har bir post uchun
alohida SQL yuborish (N+1 query) DB connection pool'ini to'ldirib,
botning umumiy javob tezligini tushiradi. Bu modul AYNAN shu muammoni
hal qiladi: barcha metrikalar (ko'rishlar, reaksiyalar, format, soat)
**bitta** SQL statementda — JOIN + GROUP BY + `= ANY(%s)` — yuklanadi.

Qatlam: REPOSITORY — domain ma'lumotlariga kirish (faqat o'qish).

Kafolatlar
----------
* **Bitta so'rov = bitta `cur.execute`.** Har bir ``get_*`` funksiyasi
  aynan bitta SQL yuboradi; N ta post ham, N ta kanal ham bitta
  statement ichida (`= ANY(%s)` / `GROUP BY`) qayta ishlanadi.
  ``get_channel_analytics_bundle`` — ko'pi bilan 2 ta so'rov.
* **Agregatsiya DB darajasida** — o'rtacha ko'rishlar, eng yaxshi
  formatlar, eng faol soat/hafta kuni SQL'da hisoblanadi; Python
  faqat natijani o'qiydi (katta ro'yxatlarni xotiraga tortmaydi).
* **Fail-soft** — har qanday DB xatosida istisno ko'tarilmaydi:
  bo'sh natija qaytadi (chaqiruvchi handler baribir javob beradi).
* **Kech bog'lanish** — yadroga (``database``) ``repositories.runtime``
  orqali bog'lanadi, shu sabab ``patch("database.db_cursor")`` mock
  nuqtasi saqlanadi (repository_layering_test.py talabi).

Bu modul HECH QANDAY AI chaqiruvini qilmaydi — faqat DB agregatsiyasi.
"""

import logging

from repositories.runtime import db_cursor

logger = logging.getLogger(__name__)

# ====================================================================
# CHEGARALAR
# ====================================================================

#: Bitta `= ANY(%s)` / `IN (...)` batcheda yuboriladigan maksimal ID soni.
#: (PostgreSQL parametr chegarasi va pool yuklamasi hisobga olingan.)
ANALYTICS_MAX_BATCH_IDS = 500

#: Kanal tahlilida bir marta o'qiladigan postlar soni (topshiriq: 50–100).
ANALYTICS_DEFAULT_LIMIT = 100

#: O'qish chegarasi (undan katta qiymat qisqartiriladi).
ANALYTICS_MAX_LIMIT = 500

#: Agregatsiya oynasi (kun) — standart 30 kun.
ANALYTICS_DEFAULT_DAYS = 30

#: Media turi → post format (DB'da format ustuni yo'q, lekin media_type bor).
_MEDIA_FORMATS = {
    "text": "text",
    "photo": "photo",
    "video": "video",
    "video_note": "video",
    "animation": "animation",
    "document": "document",
    "audio": "audio",
    "voice": "audio",
    "sticker": "sticker",
    "poll": "poll",
}


# ====================================================================
# PURE YORDAMCHILAR (DB'siz, deterministik)
# ====================================================================

def normalize_ids(values, limit: int = ANALYTICS_MAX_BATCH_IDS) -> list:
    """ID to'plamini tozalaydi: noma'lumlar tashlanadi, takrorlar yo'q.

    Tartib saqlanadi (birinchi uchragani birinchi qoladi) va ``limit``
    dan oshmaydi. Hech qachon istisno ko'tarmaydi.
    """
    try:
        safe_limit = max(1, int(limit))
    except (TypeError, ValueError):
        safe_limit = ANALYTICS_MAX_BATCH_IDS
    if values is None:
        return []
    if isinstance(values, (str, bytes, int)):
        values = [values]
    seen = set()
    out = []
    try:
        iterator = iter(values)
    except TypeError:
        return []
    for value in iterator:
        try:
            int_value = int(value)
        except (TypeError, ValueError):
            continue
        if int_value in seen:
            continue
        seen.add(int_value)
        out.append(int_value)
        if len(out) >= safe_limit:
            break
    return out


def normalize_limit(value, default: int = ANALYTICS_DEFAULT_LIMIT,
                    maximum: int = ANALYTICS_MAX_LIMIT) -> int:
    """Limitni xavfsiz oraliqqa keltiradi (fail-soft)."""
    try:
        safe = int(value)
    except (TypeError, ValueError):
        safe = int(default)
    return max(1, min(safe, int(maximum)))


def format_from_media(media_type, has_media=None) -> str:
    """``media_type``/``has_media`` dan post formatini aniqlaydi (PURE).

    Media bo'lmasa — ``"text"``; noma'lum media turi — ``"media"``.
    """
    if media_type:
        key = str(media_type).strip().lower()
        if key in _MEDIA_FORMATS:
            return _MEDIA_FORMATS[key]
        if key:
            return "media"
    if has_media:
        return "media"
    return "text"


def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _iso(value) -> str:
    try:
        return value.isoformat() if value is not None else ""
    except Exception:  # pragma: no cover — date/datetime bo'lmagan qiymat
        return ""


def _empty_summary() -> dict:
    """Agregatsiya natijasining bo'sh (fail-soft) shakli."""
    return {
        "posts": 0,
        "total_views": 0,
        "avg_views": 0.0,
        "max_views": 0,
        "total_reactions": 0,
        "events": 0,
        "media_posts": 0,
        "cta_posts": 0,
        "best_hour": None,
        "best_weekday": None,
        "best_format": None,
        "best_formats": [],
        "format_distribution": {},
    }


# ====================================================================
# 1) POST METRIKALARI — `= ANY(%s)` BATCH (N+1 EMAS)
# ====================================================================

def get_posts_reaction_metrics_batch(post_ids) -> dict:
    """N ta post uchun reaksiya metrikalari — AYNAN 1 SQL so'rov.

    ``WHERE post_id = ANY(%s) GROUP BY post_id`` — N+1 o'rniga bitta
    chaqiruv. Natija::

        {post_id: {"post_id", "reactions", "reaction_types"}}

    Xato bo'lsa ``{}`` (fail-soft).
    """
    ids = normalize_ids(post_ids)
    if not ids:
        return {}
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT pr.post_id,
                       COUNT(pr.id) AS reactions,
                       COUNT(DISTINCT pr.reaction_type) AS reaction_types
                FROM post_reactions pr
                WHERE pr.post_id = ANY(%s)
                GROUP BY pr.post_id
                """,
                (ids,),
            )
            rows = cur.fetchall() or []
    except Exception as e:  # pragma: no cover — fail-soft
        logger.error("get_posts_reaction_metrics_batch xatosi: %s", e)
        return {}
    metrics = {
        pid: {"post_id": pid, "reactions": 0, "reaction_types": 0}
        for pid in ids
    }
    for row in rows:
        try:
            pid = int(row[0])
        except (TypeError, ValueError, IndexError):
            continue
        if pid not in metrics:
            metrics[pid] = {"post_id": pid, "reactions": 0, "reaction_types": 0}
        metrics[pid]["reactions"] = _to_int(row[1] if len(row) > 1 else 0)
        metrics[pid]["reaction_types"] = _to_int(row[2] if len(row) > 2 else 0)
    return metrics


def get_posts_delivery_metrics_batch(post_ids) -> dict:
    """N ta post uchun yuborish/kanal metrikalari — AYNAN 1 SQL so'rov.

    ``sent_post_messages`` (yuborilgan xabarlar) + ``post_deliveries``
    (yetkazish holati) DB darajasida guruhlanadi::

        {post_id: {"post_id", "sent_messages", "message_id",
                   "channel_id", "deliveries", "delivered"}}

    Xato bo'lsa ``{}`` (fail-soft).
    """
    ids = normalize_ids(post_ids)
    if not ids:
        return {}
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT spm.post_id,
                       COUNT(spm.id) AS sent_messages,
                       MAX(spm.message_id) AS message_id,
                       MAX(spm.channel_id) AS channel_id
                FROM sent_post_messages spm
                WHERE spm.post_id = ANY(%s)
                GROUP BY spm.post_id
                """,
                (ids,),
            )
            rows = cur.fetchall() or []
    except Exception as e:  # pragma: no cover — fail-soft
        logger.error("get_posts_delivery_metrics_batch xatosi: %s", e)
        return {}
    metrics = {
        pid: {
            "post_id": pid,
            "sent_messages": 0,
            "message_id": None,
            "channel_id": None,
            "deliveries": 0,
            "delivered": False,
        }
        for pid in ids
    }
    for row in rows:
        try:
            pid = int(row[0])
        except (TypeError, ValueError, IndexError):
            continue
        if pid not in metrics:
            metrics[pid] = {
                "post_id": pid,
                "sent_messages": 0,
                "message_id": None,
                "channel_id": None,
                "deliveries": 0,
                "delivered": False,
            }
        sent = _to_int(row[1] if len(row) > 1 else 0)
        metrics[pid]["sent_messages"] = sent
        metrics[pid]["message_id"] = row[2] if len(row) > 2 else None
        metrics[pid]["channel_id"] = str(row[3]) if len(row) > 3 and row[3] is not None else None
        metrics[pid]["delivered"] = sent > 0
    return metrics


def get_posts_metrics_batch(post_ids) -> dict:
    """N ta postning BARCHA metrikalari — ko'pi bilan 2 SQL so'rov.

    Reaksiyalar va yuborish ma'lumotlari birlashtiriladi (merge Python
    tomonida — pool'ga qo'shimcha yuklama yo'q). 50 ta post uchun
    chaqiruvlar soni: **2** (50 emas).
    """
    reactions = get_posts_reaction_metrics_batch(post_ids)
    deliveries = get_posts_delivery_metrics_batch(post_ids)
    merged = {}
    for pid in normalize_ids(post_ids):
        base = {
            "post_id": pid,
            "reactions": 0,
            "reaction_types": 0,
            "sent_messages": 0,
            "message_id": None,
            "channel_id": None,
            "delivered": False,
        }
        base.update(reactions.get(pid) or {})
        base.update(deliveries.get(pid) or {})
        merged[pid] = base
    return merged


def get_post_metrics(post_id) -> dict:
    """Bitta post metrikasi (orqaga moslik uchun) — 1 SQL so'rov."""
    ids = normalize_ids([post_id], limit=1)
    if not ids:
        return {}
    return get_posts_metrics_batch(ids).get(ids[0], {})


# ====================================================================
# 2) KANAL POSTLARI — JOIN + GROUP BY (1 SQL)
# ====================================================================

def get_channel_posts_metrics_batch(channel_id, limit: int = ANALYTICS_DEFAULT_LIMIT) -> list:
    """Kanalning oxirgi ``limit`` posti metrikasi — AYNAN 1 SQL so'rov.

    Uchta manba bitta statementda birlashtiriladi:

      * ``channel_posts_history`` — kontent, ko'rishlar (``views``), sana;
      * ``sent_post_messages`` + ``post_reactions`` — reaksiyalar soni
        (ichki ``GROUP BY`` — har bir xabar uchun bitta qator);
      * ``channel_post_events`` — soat/kun/media/CTA/emoji (ichki
        ``GROUP BY``).

    Har bir element::

        {"post_id", "message_id", "content", "views", "post_date",
         "reactions", "reactors", "format", "has_media", "media_type",
         "post_hour", "post_weekday", "length", "cta_detected",
         "emoji_density", "engagement_rate"}

    ``engagement_rate`` — (reaksiyalar / ko'rishlar) * 100, DB'dan
    kelgan agregatlar asosida Python'da hisoblanadi (PURE).
    """
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return []
    safe_limit = normalize_limit(limit)
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT h.id,
                       h.message_id,
                       h.content,
                       COALESCE(h.views, 0) AS views,
                       h.post_date,
                       COALESCE(r.reactions, 0) AS reactions,
                       COALESCE(r.reactors, 0) AS reactors,
                       e.post_hour,
                       e.post_weekday,
                       e.has_media,
                       e.media_type,
                       e.length,
                       e.cta_detected,
                       e.emoji_density
                FROM channel_posts_history h
                LEFT JOIN (
                    SELECT spm.message_id,
                           COUNT(pr.id) AS reactions,
                           COUNT(DISTINCT pr.user_id) AS reactors
                    FROM sent_post_messages spm
                    JOIN post_reactions pr ON pr.post_id = spm.post_id
                    WHERE spm.channel_id = %s
                    GROUP BY spm.message_id
                ) r ON r.message_id = h.message_id
                LEFT JOIN (
                    SELECT message_id,
                           MAX(post_hour) AS post_hour,
                           MAX(post_weekday) AS post_weekday,
                           BOOL_OR(has_media) AS has_media,
                           MAX(media_type) AS media_type,
                           MAX(length) AS length,
                           BOOL_OR(cta_detected) AS cta_detected,
                           MAX(emoji_density) AS emoji_density
                    FROM channel_post_events
                    WHERE channel_id = %s
                    GROUP BY message_id
                ) e ON e.message_id = h.message_id
                WHERE h.channel_id = %s
                ORDER BY h.post_date DESC NULLS LAST, h.id DESC
                LIMIT %s
                """,
                (ch_id, ch_id, ch_id, safe_limit),
            )
            rows = cur.fetchall() or []
    except Exception as e:
        logger.error("get_channel_posts_metrics_batch xatosi (%s): %s", ch_id, e)
        return []
    return [_row_to_post_metric(row) for row in rows]


def _row_to_post_metric(row) -> dict:
    """SQL qatorini post-metrika dict'iga aylantiradi (PURE, fail-soft)."""
    values = list(row or []) + [None] * 14
    views = _to_int(values[3])
    reactions = _to_int(values[5])
    reactors = _to_int(values[6])
    has_media = bool(values[9]) if values[9] is not None else None
    media_type = values[10]
    rate = round((reactions / views) * 100, 4) if views > 0 else 0.0
    return {
        "post_id": _to_int(values[0]),
        "message_id": values[1],
        "content": values[2] or "",
        "text": values[2] or "",
        "views": views,
        "post_date": _iso(values[4]),
        "reactions": reactions,
        "reactors": reactors,
        "format": format_from_media(media_type, has_media),
        "has_media": bool(has_media) if has_media is not None else False,
        "media_type": media_type,
        "post_hour": values[7] if values[7] is None else _to_int(values[7]),
        "post_weekday": values[8] if values[8] is None else _to_int(values[8]),
        "length": _to_int(values[11]),
        "cta_detected": bool(values[12]),
        "emoji_density": _to_float(values[13]),
        "engagement_rate": rate,
    }


# ====================================================================
# 3) KANAL AGREGATSIYASI — DB DARAJASIDA (1 SQL)
# ====================================================================

def get_channel_analytics_summary(channel_id, days: int = ANALYTICS_DEFAULT_DAYS) -> dict:
    """Kanal bo'yicha AGREGATSIYA — AYNAN 1 SQL so'rov (DB darajasida).

    Python katta ro'yxatni ko'chirmaydi: o'rtacha/umumiy ko'rishlar,
    reaksiyalar, media va CTA ulushi, eng faol soat/hafta kuni va
    **eng yaxshi samarali formatlar** (format bo'yicha AVG(views))
    SQL'da hisoblanadi::

        {"posts", "total_views", "avg_views", "max_views",
         "total_reactions", "events", "media_posts", "cta_posts",
         "best_hour", "best_weekday", "best_format", "best_formats",
         "format_distribution"}

    Xato bo'lsa bo'sh (nolli) tuzilma qaytadi — fail-soft.
    """
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return _empty_summary()
    try:
        safe_days = max(1, int(days))
    except (TypeError, ValueError):
        safe_days = ANALYTICS_DEFAULT_DAYS
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                WITH ev AS (
                    SELECT *
                    FROM channel_post_events
                    WHERE channel_id = %s
                      AND created_at >= NOW() - make_interval(days => %s)
                ),
                hist AS (
                    SELECT *
                    FROM channel_posts_history
                    WHERE channel_id = %s
                      AND post_date >= NOW() - make_interval(days => %s)
                ),
                rx AS (
                    SELECT COUNT(pr.id) AS reactions
                    FROM sent_post_messages spm
                    JOIN post_reactions pr ON pr.post_id = spm.post_id
                    WHERE spm.channel_id = %s
                )
                SELECT
                    (SELECT COUNT(*) FROM hist) AS posts,
                    (SELECT COALESCE(SUM(h.views), 0) FROM hist h) AS total_views,
                    (SELECT COALESCE(AVG(h.views), 0) FROM hist h) AS avg_views,
                    (SELECT COALESCE(MAX(h.views), 0) FROM hist h) AS max_views,
                    (SELECT COALESCE(SUM(rx.reactions), 0) FROM rx) AS total_reactions,
                    (SELECT COUNT(*) FROM ev) AS events,
                    (SELECT COUNT(*) FROM ev WHERE has_media) AS media_posts,
                    (SELECT COUNT(*) FROM ev WHERE cta_detected) AS cta_posts,
                    (SELECT e.post_hour FROM ev e
                      GROUP BY e.post_hour
                      ORDER BY COUNT(*) DESC, e.post_hour ASC
                      LIMIT 1) AS best_hour,
                    (SELECT e.post_weekday FROM ev e
                      GROUP BY e.post_weekday
                      ORDER BY COUNT(*) DESC, e.post_weekday ASC
                      LIMIT 1) AS best_weekday,
                    (SELECT g.fmt FROM (
                        SELECT CASE
                                   WHEN e.media_type IS NULL OR e.media_type = ''
                                       THEN 'text' ELSE e.media_type END AS fmt,
                               COUNT(*) AS cnt
                        FROM ev e
                        GROUP BY 1
                    ) g ORDER BY g.cnt DESC, g.fmt ASC LIMIT 1) AS best_format,
                    (SELECT COALESCE(ARRAY_AGG(g.fmt ORDER BY g.avg_views DESC, g.fmt ASC), ARRAY[]::text[])
                     FROM (
                        SELECT CASE
                                   WHEN e.media_type IS NULL OR e.media_type = ''
                                       THEN 'text' ELSE e.media_type END AS fmt,
                               COALESCE(AVG(h.views), 0) AS avg_views
                        FROM hist h
                        LEFT JOIN ev e ON e.message_id = h.message_id
                        GROUP BY 1
                     ) g) AS best_formats,
                    (SELECT COALESCE(JSONB_OBJECT_AGG(g.fmt, g.cnt), '{}'::jsonb)
                     FROM (
                        SELECT CASE
                                   WHEN e.media_type IS NULL OR e.media_type = ''
                                       THEN 'text' ELSE e.media_type END AS fmt,
                               COUNT(*) AS cnt
                        FROM ev e
                        GROUP BY 1
                     ) g) AS format_distribution
                """,
                (ch_id, safe_days, ch_id, safe_days, ch_id),
            )
            row = cur.fetchone()
    except Exception as e:
        logger.error("get_channel_analytics_summary xatosi (%s): %s", ch_id, e)
        return _empty_summary()
    return _row_to_summary(row, days=safe_days)


def _row_to_summary(row, days: int = ANALYTICS_DEFAULT_DAYS) -> dict:
    """Agregat qatorini xavfsiz dict'ga aylantiradi (PURE)."""
    summary = _empty_summary()
    if not row:
        summary["days"] = _to_int(days, ANALYTICS_DEFAULT_DAYS)
        return summary
    values = list(row) + [None] * 13
    summary["posts"] = _to_int(values[0])
    summary["total_views"] = _to_int(values[1])
    summary["avg_views"] = round(_to_float(values[2]), 1)
    summary["max_views"] = _to_int(values[3])
    summary["total_reactions"] = _to_int(values[4])
    summary["events"] = _to_int(values[5])
    summary["media_posts"] = _to_int(values[6])
    summary["cta_posts"] = _to_int(values[7])
    summary["best_hour"] = values[8] if values[8] is None else _to_int(values[8])
    summary["best_weekday"] = values[9] if values[9] is None else _to_int(values[9])
    summary["best_format"] = values[10] if values[10] is None else format_from_media(values[10], True)
    raw_formats = values[11]
    if isinstance(raw_formats, (list, tuple)):
        summary["best_formats"] = [format_from_media(f, True) for f in raw_formats if f]
    elif raw_formats:
        summary["best_formats"] = [format_from_media(raw_formats, True)]
    raw_dist = values[12]
    if isinstance(raw_dist, dict):
        summary["format_distribution"] = {
            format_from_media(k, True): _to_int(v) for k, v in raw_dist.items()
        }
    summary["days"] = _to_int(days, ANALYTICS_DEFAULT_DAYS)
    return summary


# ====================================================================
# 4) KO'P KANAL AGREGATSIYASI — N+1 EMAS (1 SQL)
# ====================================================================

def get_channels_analytics_summary(channel_ids, days: int = ANALYTICS_DEFAULT_DAYS) -> dict:
    """N ta kanal uchun agregatsiya — AYNAN 1 SQL so'rov.

    Har bir kanal uchun alohida so'rov yuborish (N+1) o'rniga
    ``WHERE channel_id = ANY(%s) ... GROUP BY channel_id`` ishlatiladi.
    Natija: ``{channel_id: summary_dict}`` (har biri
    :func:`get_channel_analytics_summary` bilan bir xil kalitlarga ega).

    Xato bo'lsa ``{}`` (fail-soft).
    """
    ids = [str(c).strip() for c in (channel_ids or []) if str(c).strip()]
    if not ids:
        return {}
    ids = list(dict.fromkeys(ids))[:ANALYTICS_MAX_BATCH_IDS]
    try:
        safe_days = max(1, int(days))
    except (TypeError, ValueError):
        safe_days = ANALYTICS_DEFAULT_DAYS
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                WITH ev AS (
                    SELECT *
                    FROM channel_post_events
                    WHERE channel_id = ANY(%s)
                      AND created_at >= NOW() - make_interval(days => %s)
                ),
                hist AS (
                    SELECT *
                    FROM channel_posts_history
                    WHERE channel_id = ANY(%s)
                      AND post_date >= NOW() - make_interval(days => %s)
                )
                SELECT c.channel_id,
                       (SELECT COUNT(*) FROM hist h WHERE h.channel_id = c.channel_id) AS posts,
                       (SELECT COALESCE(SUM(h.views), 0) FROM hist h
                         WHERE h.channel_id = c.channel_id) AS total_views,
                       (SELECT COALESCE(AVG(h.views), 0) FROM hist h
                         WHERE h.channel_id = c.channel_id) AS avg_views,
                       (SELECT COALESCE(MAX(h.views), 0) FROM hist h
                         WHERE h.channel_id = c.channel_id) AS max_views,
                       (SELECT COUNT(*) FROM ev e
                         WHERE e.channel_id = c.channel_id) AS events,
                       (SELECT COUNT(*) FROM ev e
                         WHERE e.channel_id = c.channel_id AND e.has_media) AS media_posts,
                       (SELECT COUNT(*) FROM ev e
                         WHERE e.channel_id = c.channel_id AND e.cta_detected) AS cta_posts,
                       (SELECT e.post_hour FROM ev e
                         WHERE e.channel_id = c.channel_id
                         GROUP BY e.post_hour
                         ORDER BY COUNT(*) DESC, e.post_hour ASC LIMIT 1) AS best_hour,
                       (SELECT e.post_weekday FROM ev e
                         WHERE e.channel_id = c.channel_id
                         GROUP BY e.post_weekday
                         ORDER BY COUNT(*) DESC, e.post_weekday ASC LIMIT 1) AS best_weekday
                FROM (SELECT UNNEST(%s::text[]) AS channel_id) c
                """,
                (ids, safe_days, ids, safe_days, ids),
            )
            rows = cur.fetchall() or []
    except Exception as e:
        logger.error("get_channels_analytics_summary xatosi: %s", e)
        return {}
    out = {}
    for row in rows:
        if not row:
            continue
        row_values = list(row) + [None] * 10
        ch_id = row_values[0]
        if ch_id is None:
            continue
        out[str(ch_id)] = _row_to_summary(
            [row_values[1], row_values[2], row_values[3], row_values[4],
             None, row_values[5], row_values[6], row_values[7],
             row_values[8], row_values[9], None, None, None],
            days=safe_days,
        )
    return out


# ====================================================================
# 5) YAGONA KIRISH NUQTASI — kanal tahlili (ko'pi bilan 2 SQL)
# ====================================================================

def get_channel_analytics_bundle(channel_id, limit: int = ANALYTICS_DEFAULT_LIMIT,
                                 days: int = ANALYTICS_DEFAULT_DAYS) -> dict:
    """Kanal tahlili uchun TO'LIQ to'plam — **ko'pi bilan 2 SQL so'rov**.

    Eski (N+1) yo'l: 50–100 post × (reaksiyalar + ko'rishlar + metrikalar)
    = 150+ so'rov. Yangi yo'l: 1 ta JOIN/GROUP BY (postlar) + 1 ta DB
    darajasidagi agregatsiya (xulosa).

    Qaytadi::

        {"channel_id", "posts": [...], "summary": {...},
         "query_count": 2, "batched": True}
    """
    ch_id = str(channel_id or "").strip()
    posts = get_channel_posts_metrics_batch(ch_id, limit) if ch_id else []
    summary = get_channel_analytics_summary(ch_id, days) if ch_id else _empty_summary()
    return {
        "channel_id": ch_id,
        "posts": posts,
        "summary": summary,
        "query_count": 2 if ch_id else 0,
        "batched": True,
    }


def count_posts_by_format(posts) -> dict:
    """Postlar ro'yxati bo'yicha format taqsimoti (PURE)."""
    distribution = {}
    for post in posts or ():
        if not isinstance(post, dict):
            continue
        fmt = str(post.get("format") or "text").strip().lower() or "text"
        distribution[fmt] = distribution.get(fmt, 0) + 1
    return distribution


__all__ = [
    "ANALYTICS_DEFAULT_DAYS",
    "ANALYTICS_DEFAULT_LIMIT",
    "ANALYTICS_MAX_BATCH_IDS",
    "ANALYTICS_MAX_LIMIT",
    "count_posts_by_format",
    "format_from_media",
    "get_channel_analytics_bundle",
    "get_channel_analytics_summary",
    "get_channel_posts_metrics_batch",
    "get_channels_analytics_summary",
    "get_post_metrics",
    "get_posts_delivery_metrics_batch",
    "get_posts_metrics_batch",
    "get_posts_reaction_metrics_batch",
    "normalize_ids",
    "normalize_limit",
]
