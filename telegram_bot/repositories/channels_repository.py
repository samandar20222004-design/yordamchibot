# -*- coding: utf-8 -*-
"""
=====================================================================
 📢 CHANNELS — kanal CRUD, monitoring, Channel DNA, manba/RSS, reklama
=====================================================================

Kanal ro'yxati va monitoringi, Channel Intelligence (post event ingestion) va Channel DNA profillari, kanal sozlamalari/toni, reklama dvigateli, sponsor kanallar, kontent manbalari (RSS/ATOM), qoralamalar va recycle.

Qatlam: REPOSITORY — domain ma'lumotlariga kirish.

Bu modul yadroga (``database``: pool / tranzaksiya / kesh / sxema)
``repositories.runtime`` orqali **kech bog'lanadi**: ``db_cursor``,
``transaction``, ``_cache_*`` va boshqa yadro yordamchilari chaqiruv
paytida ``database`` modulining joriy atributiga qarab yuradi. Shu
sabab ``unittest.mock.patch("database.db_cursor")`` kabi mavjud mock
nuqtalari bu modulga ko'chirilgandan keyin ham kuchini yo'qotmaydi.
"""

import pytz
from datetime import datetime, timedelta  # noqa: F401
import logging


from database import (  # noqa: F401
    AD_SCOPE_CHANNEL, AD_SCOPE_REPLY, DB_SETTINGS_CACHE_TTL,
    DB_SPONSORS_CACHE_TTL, DB_USER_CACHE_TTL, _MISS
)
from repositories.runtime import (  # noqa: F401
    _cache_clear, _cache_get, _cache_set, _invalidate_rbac_resource_cache,
    _invalidate_user, _profile_clear_all, db_cursor
)

from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)


# ====================================================================
# 📢 CHANNELS — kanal CRUD, monitoring, Channel DNA, manba/RSS, reklama
# ====================================================================

AD_SCOPES = (AD_SCOPE_CHANNEL, AD_SCOPE_REPLY)


# Reklama matni/tugmasi uchun chegaralar (Telegram limitlariga mos).
AD_TEXT_MAX_LEN = 1024


AD_BUTTON_TEXT_MAX_LEN = 64


AD_BUTTON_URL_MAX_LEN = 2048


def _normalize_ad_button(button_text: str = "", button_url: str = "") -> tuple:
    """Tugma matni/havolasini normallashtiradi.

    Ikkalasi ham to'liq bo'lmasa tugma saqlanmaydi (``(None, None)``) —
    Telegram matnsiz yoki havolasiz inline tugmani qabul qilmaydi.
    """
    btn_text = (button_text or "").strip()[:AD_BUTTON_TEXT_MAX_LEN]
    btn_url = (button_url or "").strip()[:AD_BUTTON_URL_MAX_LEN]
    if not btn_text or not btn_url:
        return None, None
    return btn_text, btn_url


def _ad_row_to_dict(row) -> dict:
    """``ad_pool`` qatorini qulay dict ko'rinishiga o'giradi."""
    ad_id, scope, text, btn_text, btn_url, is_active = row[:6]
    return {
        "id": int(ad_id),
        "scope": scope,
        "text": text or "",
        "button_text": btn_text or "",
        "button_url": btn_url or "",
        "is_active": bool(is_active),
    }


def add_ad(scope: str, text: str, button_text: str = "", button_url: str = "") -> int:
    """Rotatsiya puliga yangi reklama qo'shadi. Id qaytaradi (xato: -1)."""
    if scope not in AD_SCOPES:
        return -1
    text = (text or "").strip()
    if not text:
        return -1
    btn_text, btn_url = _normalize_ad_button(button_text, button_url)
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO ad_pool (scope, text, button_text, button_url) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (scope, text, btn_text, btn_url),
            )
            row = cur.fetchone()
        _cache_clear("ad_pool:")
        return int(row[0]) if row else -1
    except Exception as e:
        logger.error(f"Reklama qo'shish xatosi: {e}")
        return -1


def get_ads(scope: str) -> list:
    """Faol reklamalar ro'yxati: [(id, text), ...]. Bo'sh bo'lsa [].

    Orqaga moslik uchun soddalashtirilgan ko'rinish saqlanadi; tugma bilan
    to'liq ma'lumot kerak bo'lsa ``get_ads_full`` ishlatiladi.
    """
    return [(ad["id"], ad["text"]) for ad in get_ads_full(scope)]


def get_ads_full(scope: str, include_inactive: bool = False) -> list:
    """Reklamalarning to'liq ro'yxati (matn + inline tugma + holat).

    Har bir element: ``{"id", "scope", "text", "button_text",
    "button_url", "is_active"}``.
    """
    if scope not in AD_SCOPES:
        return []
    cache_key = f"ad_pool:{scope}:{'all' if include_inactive else 'active'}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    try:
        with db_cursor() as cur:
            query = (
                "SELECT id, scope, text, button_text, button_url, is_active "
                "FROM ad_pool WHERE scope = %s"
            )
            if not include_inactive:
                query += " AND is_active = TRUE"
            query += " ORDER BY id ASC"
            cur.execute(query, (scope,))
            rows = [_ad_row_to_dict(r) for r in cur.fetchall()]
            _cache_set(cache_key, rows, DB_SETTINGS_CACHE_TTL)
            return rows
    except Exception as e:
        logger.error(f"Reklamalar olish xatosi: {e}")
        return []


def get_ad(ad_id: int) -> dict | None:
    """Bitta reklamani id bo'yicha qaytaradi (topilmasa None)."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT id, scope, text, button_text, button_url, is_active "
                "FROM ad_pool WHERE id = %s",
                (int(ad_id),),
            )
            row = cur.fetchone()
        return _ad_row_to_dict(row) if row else None
    except Exception as e:
        logger.error(f"Reklama olish xatosi: {e}")
        return None


def count_ads(scope: str) -> int:
    """Berilgan scope uchun faol reklamalar soni."""
    return len(get_ads_full(scope) or [])


def update_ad(ad_id: int, text: str = None, button_text: str = None,
              button_url: str = None) -> bool:
    """Reklamani tahrirlaydi. Faqat berilgan (None bo'lmagan) maydonlar yangilanadi.

    ``button_text``/``button_url`` ga bo'sh satr berilsa tugma o'chiriladi.
    """
    fields = []
    params = []

    if text is not None:
        text = str(text).strip()
        if not text:
            return False
        fields.append("text = %s")
        params.append(text[:AD_TEXT_MAX_LEN])

    if button_text is not None or button_url is not None:
        # Tugma butunlay yangilanadi: ikkalasi ham berilishi kerak,
        # aks holda mavjud qiymat asos qilib olinadi.
        current = get_ad(ad_id) if (button_text is None or button_url is None) else None
        new_text = button_text if button_text is not None else (current or {}).get("button_text", "")
        new_url = button_url if button_url is not None else (current or {}).get("button_url", "")
        btn_text, btn_url = _normalize_ad_button(new_text, new_url)
        fields.append("button_text = %s")
        params.append(btn_text)
        fields.append("button_url = %s")
        params.append(btn_url)

    if not fields:
        return False

    fields.append("updated_at = CURRENT_TIMESTAMP")
    params.append(int(ad_id))
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                f"UPDATE ad_pool SET {', '.join(fields)} WHERE id = %s",  # nosec B608 — jadval/ustun nomlari kod-konstanta; qiymatlar parametrlangan
                tuple(params),
            )
            updated = cur.rowcount > 0
        _cache_clear("ad_pool:")
        return updated
    except Exception as e:
        logger.error(f"Reklama tahrirlash xatosi: {e}")
        return False


def set_ad_active(ad_id: int, is_active: bool) -> bool:
    """Reklamani faollashtiradi yoki o'chiradi (Toggle Active/Inactive)."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE ad_pool SET is_active = %s, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = %s",
                (bool(is_active), int(ad_id)),
            )
            updated = cur.rowcount > 0
        _cache_clear("ad_pool:")
        return updated
    except Exception as e:
        logger.error(f"Reklama holatini o'zgartirish xatosi: {e}")
        return False


def toggle_ad_active(ad_id: int):
    """Reklama holatini teskarisiga o'giradi. Yangi holat (bool) yoki None."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE ad_pool SET is_active = NOT COALESCE(is_active, FALSE), "
                "updated_at = CURRENT_TIMESTAMP WHERE id = %s RETURNING is_active",
                (int(ad_id),),
            )
            row = cur.fetchone()
        _cache_clear("ad_pool:")
        return bool(row[0]) if row else None
    except Exception as e:
        logger.error(f"Reklama toggle xatosi: {e}")
        return None


def delete_ad(ad_id: int) -> bool:
    """Reklamani puldan butunlay o'chiradi.

    Vaqtincha o'chirish uchun ``set_ad_active(ad_id, False)`` ishlatiladi.
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM ad_pool WHERE id = %s", (int(ad_id),))
            removed = cur.rowcount > 0
        _cache_clear("ad_pool:")
        return removed
    except Exception as e:
        logger.error(f"Reklama o'chirish xatosi: {e}")
        return False


def clear_ads(scope: str) -> int:
    """Scope bo'yicha barcha reklamalarni o'chiradi. O'chirilgan soni."""
    if scope not in AD_SCOPES:
        return 0
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM ad_pool WHERE scope = %s", (scope,))
            removed = cur.rowcount
        _cache_clear("ad_pool:")
        return int(removed or 0)
    except Exception as e:
        logger.error(f"Reklamalarni tozalash xatosi: {e}")
        return 0


# --- KANAL POST SANAGICHLARI (reklama oralig'i uchun) ---
# Reklama har nechanchi postda chiqishi admin panelda sozlanadi (3-5 ta post).
CHANNEL_AD_INTERVAL_KEY = "channel_ad_interval"


CHANNEL_AD_INTERVAL_DEFAULT = 3


AD_INTERVAL_MIN = 1


AD_INTERVAL_MAX = 100


def clamp_ad_interval(value, default: int = CHANNEL_AD_INTERVAL_DEFAULT) -> int:
    """Interval qiymatini xavfsiz butun songa keltiradi (1..100)."""
    try:
        interval = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(AD_INTERVAL_MIN, min(AD_INTERVAL_MAX, interval))


def bump_channel_post_count(channel_id) -> int:
    """Kanal post sanagichini 1 ga oshiradi va YANGI qiymatni qaytaradi.

    Sanagich har bir kanal uchun ALOHIDA yuritiladi. Atomik UPSERT bo'lgani
    uchun bir nechta scheduler tick'i parallel ishlasa ham qiymat buzilmaydi.
    Xatoda 0 qaytadi (0 hech qachon reklama chiqarmaydi).
    """
    ch = str(channel_id or "").strip()
    if not ch:
        return 0
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO channel_post_counters (channel_id, post_count, updated_at)
                VALUES (%s, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (channel_id) DO UPDATE
                SET post_count = channel_post_counters.post_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING post_count
                """,
                (ch,),
            )
            row = cur.fetchone()
        _cache_clear("channel_counter:")
        return int(row[0]) if row else 0
    except Exception as e:
        logger.error(f"Kanal post sanagichi xatosi: {e}")
        return 0


def mark_channel_ad_shown(channel_id, post_number: int) -> bool:
    """Kanalga reklama chiqarilganini belgilaydi (statistika/audit uchun)."""
    ch = str(channel_id or "").strip()
    if not ch:
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO channel_post_counters
                    (channel_id, post_count, ad_count, last_ad_post_number, updated_at)
                VALUES (%s, %s, 1, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (channel_id) DO UPDATE
                SET ad_count = channel_post_counters.ad_count + 1,
                    last_ad_post_number = EXCLUDED.last_ad_post_number,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (ch, int(post_number or 0), int(post_number or 0)),
            )
        _cache_clear("channel_counter:")
        return True
    except Exception as e:
        logger.error(f"Kanal reklama belgisi xatosi: {e}")
        return False


def get_channel_post_count(channel_id) -> int:
    """Kanalning joriy post sanagichi (yo'q bo'lsa 0)."""
    ch = str(channel_id or "").strip()
    if not ch:
        return 0
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT post_count FROM channel_post_counters WHERE channel_id = %s",
                (ch,),
            )
            row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.error(f"Kanal sanagichini olish xatosi: {e}")
        return 0


def reset_channel_post_count(channel_id=None) -> bool:
    """Bitta kanal (yoki hammasi) uchun post sanagichini nolga qaytaradi."""
    try:
        with db_cursor(commit=True) as cur:
            if channel_id is None:
                cur.execute(
                    "UPDATE channel_post_counters SET post_count = 0, "
                    "last_ad_post_number = 0, updated_at = CURRENT_TIMESTAMP"
                )
            else:
                cur.execute(
                    "UPDATE channel_post_counters SET post_count = 0, "
                    "last_ad_post_number = 0, updated_at = CURRENT_TIMESTAMP "
                    "WHERE channel_id = %s",
                    (str(channel_id),),
                )
        _cache_clear("channel_counter:")
        return True
    except Exception as e:
        logger.error(f"Kanal sanagichini tozalash xatosi: {e}")
        return False


def get_channel_post_counters(limit: int = 10) -> list:
    """Eng faol kanallar sanagichi: [(channel_id, title, post_count, ad_count), ...]."""
    try:
        limit = max(1, int(limit))
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT cpc.channel_id,
                       COALESCE(c.channel_title, '') AS title,
                       cpc.post_count, cpc.ad_count
                FROM channel_post_counters cpc
                LEFT JOIN channels c ON c.channel_id = cpc.channel_id
                ORDER BY cpc.updated_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Kanal sanagichlari ro'yxati xatosi: {e}")
        return []


def get_channel_ad_interval() -> int:
    """Kanal postlarida reklama har nechanchi postda chiqishi (standart 3)."""
    cached = _cache_get("channel_ad_interval")
    if cached is not _MISS:
        return cached
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT value FROM bot_settings WHERE key = %s",
                (CHANNEL_AD_INTERVAL_KEY,),
            )
            row = cur.fetchone()
        interval = clamp_ad_interval(row[0] if row else None)
        _cache_set("channel_ad_interval", interval, DB_SETTINGS_CACHE_TTL)
        return interval
    except Exception as e:
        logger.error(f"Kanal reklama oralig'ini olish xatosi: {e}")
        return CHANNEL_AD_INTERVAL_DEFAULT


def set_channel_ad_interval(interval) -> bool:
    """Kanal postlari reklama oralig'ini saqlaydi (masalan 3, 4 yoki 5)."""
    value = clamp_ad_interval(interval)
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO bot_settings (key, value)
                VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (CHANNEL_AD_INTERVAL_KEY, str(value)),
            )
        _cache_clear("channel_ad_interval")
        _cache_clear("ad_settings")
        return True
    except Exception as e:
        logger.error(f"Kanal reklama oralig'ini saqlash xatosi: {e}")
        return False


# --- SPONSORS ---
def add_sponsor_channel(
    channel_id: int | str,
    title: str = "",
    username: str = "",
    invite_link: str = "",
    **kwargs
) -> bool:
    """Yangi sponsor kanal qo'shadi yoki mavjudini yangilaydi.

    Qo'llab-quvvatlaydi:
      - add_sponsor_channel(channel_id, title, username, invite_link)
      - add_sponsor_channel(channel_id, channel_title, channel_url)
    """
    # Orqaga moslik: agar 3 ta argument berilgan bo'lsa (channel_id, title, url)
    if not invite_link and username and (username.startswith("http://") or username.startswith("https://") or username.startswith("t.me")):
        invite_link = username
        username = ""

    title = (title or kwargs.get("channel_title") or "").strip()
    invite_link = (invite_link or kwargs.get("channel_url") or "").strip()
    username = (username or "").strip()
    if username.startswith("@"):
        username = username[1:]
    if not invite_link and username:
        invite_link = f"https://t.me/{username}"

    ch_id_str = str(channel_id).strip()
    try:
        ch_id_bigint = int(ch_id_str)
    except ValueError:
        ch_id_bigint = None

    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO sponsor_channels (channel_id, title, username, invite_link, channel_title, channel_url, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (channel_id) DO UPDATE
                SET title = COALESCE(NULLIF(EXCLUDED.title, ''), sponsor_channels.title, EXCLUDED.channel_title),
                    username = COALESCE(NULLIF(EXCLUDED.username, ''), sponsor_channels.username),
                    invite_link = COALESCE(NULLIF(EXCLUDED.invite_link, ''), sponsor_channels.invite_link, EXCLUDED.channel_url),
                    channel_title = COALESCE(NULLIF(EXCLUDED.channel_title, ''), sponsor_channels.channel_title, EXCLUDED.title),
                    channel_url = COALESCE(NULLIF(EXCLUDED.channel_url, ''), sponsor_channels.channel_url, EXCLUDED.invite_link),
                    is_active = TRUE
            """, (
                ch_id_bigint if ch_id_bigint is not None else ch_id_str,
                title,
                username,
                invite_link,
                title,
                invite_link
            ))
        _cache_clear("sponsors")
        _cache_clear("system_stats")
        return True
    except Exception as e:
        logger.error(f"Sponsor xatosi: {e}")
        return False


def get_sponsor_channels() -> list:
    """Faol sponsor kanallar ro'yxatini qaytaradi (fail-closed: xatoda None).

    Har bir qator: (id, channel_id, title, username, invite_link)
    """
    cached = _cache_get("sponsors")
    if cached is not _MISS:
        return cached
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, channel_id,
                       COALESCE(title, channel_title, '') AS title,
                       COALESCE(username, '') AS username,
                       COALESCE(invite_link, channel_url, '') AS invite_link
                FROM sponsor_channels
                WHERE is_active = TRUE
                ORDER BY id ASC
            """)
            rows = cur.fetchall()
            _cache_set("sponsors", rows, DB_SPONSORS_CACHE_TTL)
            return rows
    except Exception as e:
        logger.error(f"Sponsorlar olish xatosi: {e}")
        return None


def get_active_sponsors():
    """Faol homiy kanallar (get_sponsor_channels aliasi)."""
    return get_sponsor_channels()


def remove_sponsor_channel(sponsor_id: int | str) -> bool:
    """Sponsor kanalni o'chiradi (id yoki channel_id bo'yicha)."""
    try:
        s_id_str = str(sponsor_id).strip()
        try:
            s_id_int = int(s_id_str)
        except ValueError:
            s_id_int = -999999999
        with db_cursor(commit=True) as cur:
            cur.execute(
                "DELETE FROM sponsor_channels WHERE id = %s OR channel_id = %s OR CAST(channel_id AS TEXT) = %s",
                (s_id_int, s_id_int, s_id_str),
            )
            removed = cur.rowcount > 0
        _cache_clear("sponsors")
        _cache_clear("system_stats")
        return removed
    except Exception as e:
        logger.error(f"Sponsor o'chirish xatosi: {e}")
        return False


# --- AUTO-AD INJECTOR SETTINGS ---
def get_ad_settings() -> dict:
    """Reklama sozlamalari.

    Qaytadi: ``auto_ad_text``, ``auto_ad_interval`` (bot javoblari uchun),
    ``auto_ad_status``, ``channel_ad_interval`` (kanal postlari uchun —
    reklama har nechanchi postda chiqishi) va ``channel_ad_status``
    (kanal postlari reklamasi yoqilgan/o'chirilgan).
    """
    cached = _cache_get("ad_settings")
    if cached is not _MISS:
        return cached
    settings = {
        "auto_ad_text": "",
        "auto_ad_interval": 4,
        "auto_ad_status": False,
        "channel_ad_interval": CHANNEL_AD_INTERVAL_DEFAULT,
        # Kanal postlari reklamasi standart HOLATDA YOQILGAN — mavjud bot
        # xatti-harakati o'zgarmasligi uchun (orqaga moslik).
        "channel_ad_status": True,
    }
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT key, value FROM bot_settings
                WHERE key IN ('auto_ad_text', 'auto_ad_interval', 'auto_ad_status',
                              'channel_ad_interval', 'channel_ad_status')
            """)
            rows = cur.fetchall()
            for k, v in rows:
                if k == "auto_ad_text":
                    settings["auto_ad_text"] = v or ""
                elif k == "auto_ad_interval":
                    settings["auto_ad_interval"] = clamp_ad_interval(v, 4)
                elif k == "channel_ad_interval":
                    settings["channel_ad_interval"] = clamp_ad_interval(
                        v, CHANNEL_AD_INTERVAL_DEFAULT)
                elif k == "auto_ad_status":
                    settings["auto_ad_status"] = str(v).lower() in ("true", "1", "yes", "on")
                elif k == "channel_ad_status":
                    settings["channel_ad_status"] = str(v).lower() in ("true", "1", "yes", "on")
        _cache_set("ad_settings", settings, DB_SETTINGS_CACHE_TTL)
        return settings
    except Exception as e:
        logger.error(f"get_ad_settings xatosi: {e}")
        return settings


def update_ad_text(text: str) -> bool:
    """Auto-ad matnini yangilaydi."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO bot_settings (key, value)
                VALUES ('auto_ad_text', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (str(text or ""),))
        _cache_clear("ad_settings")
        _cache_clear("setting:")
        return True
    except Exception as e:
        logger.error(f"update_ad_text xatosi: {e}")
        return False


def set_ad_status(status: bool) -> bool:
    """Auto-ad faollik holatini o'zgartiradi (True/False)."""
    val = "true" if status else "false"
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO bot_settings (key, value)
                VALUES ('auto_ad_status', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (val,))
        _cache_clear("ad_settings")
        _cache_clear("setting:")
        return True
    except Exception as e:
        logger.error(f"set_ad_status xatosi: {e}")
        return False


def set_channel_ad_status(status: bool) -> bool:
    """Kanal postlari reklamasini yoqish/o'chirish (True/False)."""
    val = "true" if status else "false"
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO bot_settings (key, value)
                VALUES ('channel_ad_status', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (val,))
        _cache_clear("ad_settings")
        _cache_clear("channel_ad_interval")
        return True
    except Exception as e:
        logger.error(f"set_channel_ad_status xatosi: {e}")
        return False


def set_ad_interval(interval: int) -> bool:
    """Bot javoblari reklama intervalini o'zgartiradi (standart: 4)."""
    try:
        val = str(clamp_ad_interval(interval, 4))
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO bot_settings (key, value)
                VALUES ('auto_ad_interval', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (val,))
        _cache_clear("ad_settings")
        _cache_clear("setting:")
        return True
    except Exception as e:
        logger.error(f"set_ad_interval xatosi: {e}")
        return False


# --- CHANNELS ---
def get_user_channels(user_id: int) -> list:
    cache_key = f"user_channels:{user_id}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    try:
        with db_cursor() as cur:
            cur.execute("SELECT channel_id, channel_title FROM channels WHERE user_id = %s AND is_active = TRUE ORDER BY id ASC", (user_id,))
            channels = cur.fetchall()
            _cache_set(cache_key, channels, DB_USER_CACHE_TTL)
            return channels
    except Exception as e:
        logger.error(f"Kanallar olish xatosi: {e}")
        return []


def get_all_channels(limit: int = None) -> list:
    """Faol kanallarni qaytaradi.

    ``limit`` berilsa, eng so'nggi qo'shilgan kanallar birinchi qaytadi.
    Admin ro'yxati shu yo'l bilan katta bazada ham bitta Telegram xabari
    chegarasidan oshib ketmaydi.
    """
    try:
        with db_cursor() as cur:
            query = """
                SELECT c.channel_id, c.channel_title, c.user_id, u.username
                FROM channels c
                LEFT JOIN users u ON u.user_id = c.user_id
                WHERE c.is_active = TRUE
                ORDER BY c.id DESC
            """
            params = ()
            if limit is not None:
                # LIMIT parametr sifatida beriladi; manfiy yoki nol qiymat
                # kutilmagan katta ro'yxat qaytarmasligi uchun 1 ga tenglanadi.
                limit = max(1, int(limit))
                query += " LIMIT %s"
                params = (limit,)
            cur.execute(query, params)
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Barcha kanallar xatosi: {e}")
        return []


def get_channels_for_content_nudges(setting_key: str, since=None) -> list:
    """Return opted-in channel owners for daily digest/calendar reminders.

    ``setting_key`` is restricted to the two user-controlled reminder flags.
    When ``since`` is provided, channels with a bot-published post or an
    observed Telegram channel post at/after that timestamp are excluded.
    The query is one indexed anti-join rather than one database round-trip per
    user/channel; missing settings default to enabled for backward-compatible
    rollout.

    Rows are ``(channel_id, channel_title, user_id, language_code, topics, tone)``.
    """
    allowed_settings = {"notify_morning_digest", "notify_uzbek_calendar"}
    key = str(setting_key or "")
    if key not in allowed_settings:
        logger.warning("Content nudge query refused unknown setting key: %r", key[:64])
        return []

    query = """
        SELECT c.channel_id, c.channel_title, c.user_id,
               COALESCE(u.language_code, 'uz') AS language_code,
               COALESCE(d.topics, '[]'::jsonb) AS topics,
               COALESCE(d.tone, '') AS tone
        FROM channels c
        LEFT JOIN users u ON u.user_id = c.user_id
        LEFT JOIN channel_dna d ON d.channel_id = c.channel_id
        LEFT JOIN user_settings us
               ON us.user_id = c.user_id AND us.key = %s
        WHERE c.is_active = TRUE
          AND COALESCE(us.value, TRUE) = TRUE
    """
    params = [key]
    if since is not None:
        query += """
          AND NOT EXISTS (
              SELECT 1 FROM scheduled_posts sp
              WHERE sp.channel_id = c.channel_id
                AND sp.status = 'posted'
                AND sp.scheduled_time >= %s
          )
          AND NOT EXISTS (
              SELECT 1 FROM channel_posts_history ph
              WHERE ph.channel_id = c.channel_id
                AND ph.post_date >= %s
          )
        """
        params.extend((since, since))
    query += " ORDER BY c.user_id ASC, c.id ASC"

    try:
        with db_cursor() as cur:
            cur.execute(query, tuple(params))
            return cur.fetchall()
    except Exception as e:
        logger.error("Content nudge kanallari olishda xato: %s", e)
        return []


def save_channel(user_id: int, channel_id: str, channel_title: str, is_admin: bool = False) -> tuple[bool, str]:
    """Kanalni foydalanuvchiga ulash.

    Qaytadi: (True, 'ok') yoki (False, 'taken'|'error').
    Faol kanalni boshqa foydalanuvchi o'g'irlay olmaydi — faqat o'chirilgan
    (nofaol) kanalni qayta ulash yoki admin qayta biriktirishi mumkin.
    """
    try:
        with db_cursor(commit=True) as cur:
            # Kanal avval kimga tegishli bo'lganini bilib olamiz — admin uni
            # boshqa foydalanuvchiga biriktirsa, ESKI EGASINING keshi ham
            # bekor qilinishi kerak (aks holda unda kanal ko'rinib turadi).
            cur.execute(
                "SELECT user_id FROM channels WHERE channel_id = %s",
                (str(channel_id),),
            )
            prev_row = cur.fetchone()
            prev_owner = prev_row[0] if prev_row else None
            cur.execute(
                """
                INSERT INTO channels (user_id, channel_id, channel_title, is_active)
                VALUES (%s, %s, %s, TRUE)
                ON CONFLICT (channel_id) DO UPDATE
                SET is_active = TRUE,
                    channel_title = EXCLUDED.channel_title,
                    user_id = CASE
                        WHEN channels.is_active = FALSE THEN EXCLUDED.user_id
                        WHEN channels.user_id = EXCLUDED.user_id THEN EXCLUDED.user_id
                        WHEN EXCLUDED.user_id = %s THEN EXCLUDED.user_id
                        ELSE channels.user_id
                    END
                RETURNING user_id
                """,
                (user_id, str(channel_id), channel_title, user_id if is_admin else -1),
            )
            row = cur.fetchone()
            if not row:
                return False, "error"
            if row[0] != user_id:
                return False, "taken"
        _invalidate_user(user_id)
        if prev_owner is not None and prev_owner != user_id:
            _invalidate_user(prev_owner)
        _cache_clear("system_stats")
        return True, "ok"
    except Exception as e:
        logger.error(f"Kanal saqlash xatosi: {e}")
        return False, "error"


def deactivate_channel_by_id(channel_id: str) -> bool:
    """Bot kanal/guruhdan chiqarilganda yozuvni nofaol qilish."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE channels SET is_active = FALSE WHERE channel_id = %s AND is_active = TRUE",
                (str(channel_id),),
            )
            changed = cur.rowcount > 0
        _cache_clear("user_channels:")
        _profile_clear_all()  # kanal egasi noma'lum — kanallar soni barcha profillarda qayta o'qiladi
        _cache_clear("system_stats")
        return changed
    except Exception as e:
        logger.error(f"Kanalni nofaol qilish xatosi: {e}")
        return False


def remove_channel(user_id: int, channel_id: str, is_admin: bool = False) -> bool:
    try:
        owner_id = None
        with db_cursor(commit=True) as cur:
            if is_admin:
                # Admin boshqa foydalanuvchining kanalini olib tashlashi mumkin —
                # o'sha egasining keshi ham bekor qilinishi shart.
                cur.execute(
                    "SELECT user_id FROM channels WHERE channel_id = %s",
                    (str(channel_id),),
                )
                row = cur.fetchone()
                owner_id = row[0] if row else None
                cur.execute("UPDATE channels SET is_active = FALSE WHERE channel_id = %s", (str(channel_id),))
            else:
                cur.execute("UPDATE channels SET is_active = FALSE WHERE channel_id = %s AND user_id = %s", (str(channel_id), user_id))
            changed = cur.rowcount > 0
        _invalidate_user(user_id)
        if owner_id is not None and owner_id != user_id:
            _invalidate_user(owner_id)
        # 🔐 PHASE 3: kanal uzildi — RBAC resurs keshini ham bekor qilamiz
        # (aks holda egasi TTL tugagunicha "owner" bo'lib qolaverardi).
        _invalidate_rbac_resource_cache(user_id, channel_id)
        if owner_id is not None and owner_id != user_id:
            _invalidate_rbac_resource_cache(owner_id, channel_id)
        _cache_clear("system_stats")
        return changed
    except Exception as e:
        logger.error(f"Kanal o'chirish xatosi: {e}")
        return False


# --- CHANNEL TONE OF VOICE ---
VALID_TONES = ("formal", "friendly", "concise", "engaging")


def get_channel_tone(channel_id: str) -> str:
    """Kanalning tone_of_voice qiymatini qaytaradi (default: 'friendly')."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT tone_of_voice FROM channels WHERE channel_id = %s AND is_active = TRUE",
                (str(channel_id),),
            )
            row = cur.fetchone()
            if row and row[0]:
                return row[0]
    except Exception as e:
        logger.error(f"Kanal tone olish xatosi: {e}")
    return "friendly"


def set_channel_tone(channel_id: str, tone: str) -> bool:
    """Kanalning tone_of_voice qiymatini yangilaydi."""
    if tone not in VALID_TONES:
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE channels SET tone_of_voice = %s WHERE channel_id = %s AND is_active = TRUE",
                (tone, str(channel_id)),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Kanal tone yangilash xatosi: {e}")
        return False


def get_user_channels_with_tone(user_id: int) -> list:
    """Foydalanuvchi kanallarini tone_of_voice bilan qaytaradi."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT channel_id, channel_title, tone_of_voice FROM channels "
                "WHERE user_id = %s AND is_active = TRUE ORDER BY id ASC",
                (user_id,),
            )
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Kanallar (tone) olish xatosi: {e}")
        return []


# ============================================================
# CHANNEL POSTS HISTORY (Real-time Post History & AI Analytics)
# ============================================================

def save_channel_post_history(
    channel_id: str | int,
    message_id: int = None,
    content: str = "",
    views: int = 0,
    post_date=None
) -> int:
    """Yangi kelgan kanal postini channel_posts_history jadvaliga saqlaydi yoki yangilaydi."""
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return -1
    text = str(content or "").strip()
    v_count = max(0, int(views or 0))
    if post_date is None:
        post_date = datetime.now(pytz.UTC)
    try:
        with db_cursor(commit=True) as cur:
            if message_id is not None:
                cur.execute(
                    "SELECT id FROM channel_posts_history WHERE channel_id = %s AND message_id = %s",
                    (ch_id, int(message_id))
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        """
                        UPDATE channel_posts_history
                        SET content = COALESCE(NULLIF(%s, ''), content),
                            views = GREATEST(views, %s),
                            post_date = COALESCE(%s, post_date)
                        WHERE id = %s
                        RETURNING id
                        """,
                        (text, v_count, post_date, row[0])
                    )
                    res = cur.fetchone()
                    return int(res[0]) if res else row[0]
            cur.execute(
                """
                INSERT INTO channel_posts_history (channel_id, message_id, content, views, post_date)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (ch_id, message_id, text, v_count, post_date)
            )
            row = cur.fetchone()
            return int(row[0]) if row else -1
    except Exception as e:
        logger.error(f"Kanal post tarixini saqlashda xato: {e}")
        return -1


def get_channel_posts_history(channel_id: str | int, limit: int = 5) -> list[dict]:
    """Kanalning bazadagi oxirgi postlari tarixini qaytaradi."""
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return []
    try:
        limit = max(1, min(int(limit), 50))
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT id, channel_id, message_id, content, views, post_date, created_at
                FROM channel_posts_history
                WHERE channel_id = %s
                ORDER BY post_date DESC, id DESC
                LIMIT %s
                """,
                (ch_id, limit)
            )
            rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "channel_id": r[1],
                    "message_id": r[2],
                    "text": r[3] or "",
                    "content": r[3] or "",
                    "views": r[4] or 0,
                    "post_date": r[5].isoformat() if r[5] else "",
                    "date": r[5].isoformat() if r[5] else "",
                    "created_at": r[6].isoformat() if r[6] else "",
                }
                for r in rows
            ]
    except Exception as e:
        logger.error(f"Kanal postlari tarixini olishda xato: {e}")
        return []


def is_channel_connected(channel_id: str | int) -> bool:
    """Kanal botga ulangan va faol ekanini tekshiradi."""
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return False
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM channels WHERE channel_id = %s AND is_active = TRUE",
                (ch_id,)
            )
            return cur.fetchone() is not None
    except Exception as e:
        logger.error(f"Kanal ulanganligini tekshirish xatosi: {e}")
        return False


def get_channel_posts_history_stats(channel_id: str | int = None) -> dict:
    """Kanal postlari tarixi bo'yicha umumiy statistika (soni, ko'rishlar)."""
    stats = {"history_count": 0, "total_views": 0, "avg_views": 0}
    try:
        with db_cursor() as cur:
            if channel_id:
                cur.execute(
                    """
                    SELECT COUNT(*), COALESCE(SUM(views), 0), COALESCE(AVG(views), 0)
                    FROM channel_posts_history
                    WHERE channel_id = %s
                    """,
                    (str(channel_id),)
                )
            else:
                cur.execute(
                    """
                    SELECT COUNT(*), COALESCE(SUM(views), 0), COALESCE(AVG(views), 0)
                    FROM channel_posts_history
                    """
                )
            row = cur.fetchone()
            if row:
                count = int(row[0] or 0)
                total_v = int(row[1] or 0)
                avg_v = round(float(row[2] or 0), 1)
                stats["history_count"] = count
                stats["total_views"] = total_v
                stats["avg_views"] = avg_v
    except Exception as e:
        logger.error(f"Kanal tarixi statistikasini olishda xato: {e}")
    return stats


# ============================================================
# 🧠 PHASE B — CHANNEL INTELLIGENCE (DNA, BEST TIME, EVENT INGESTION)
# ------------------------------------------------------------
# 1) channel_post_events — kanal postlarining metama'lumotlari
#    (idempotent: (channel_id, message_id) UNIQUE, ON CONFLICT DO NOTHING).
#    Media fayllar SAQLANMAYDI — faqat file_id va turi.
# 2) channel_intelligence_profiles — hisoblangan Channel DNA profili.
# 3) Boshqaruv so'rovlari (ownership/best-time/DNA uchun).
# Barcha funksiyalar sinxron (run_db orqali chaqiriladi) va xatoda
# istisno ko'tarmaydi — fail-soft (qo'ng'iroqchiga bo'sh natija).
# ============================================================

def get_channel_settings(channel_id: str | int) -> dict:
    """Return privacy settings without exposing channel member data."""
    try:
        with db_cursor() as cur:
            cur.execute("SELECT enable_comment_analysis FROM channels WHERE channel_id = %s", (str(channel_id),))
            row = cur.fetchone()
            return {"enable_comment_analysis": bool(row[0])} if row else {}
    except Exception as e:
        logger.error("get_channel_settings xatosi: %s", e)
        return {}


def set_comment_analysis(channel_id: str | int, enabled: bool) -> bool:
    """Owner-controlled privacy switch; no comment data is touched."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE channels SET enable_comment_analysis = %s WHERE channel_id = %s", (bool(enabled), str(channel_id)))
            return cur.rowcount > 0
    except Exception as e:
        logger.error("set_comment_analysis xatosi: %s", e)
        return False


def get_channel_owner_id(channel_id: str | int) -> int | None:
    """Kanalning egasini (user_id) qaytaradi. Yo'q bo'lsa None (fail-soft).

    RBAC/IDOR himoyasi uchun: kanal DNA/best-time so'rovlari AYNAN shu
    egalik tekshiruvidan o'tishi shart (boshqa foydalanuvchining kanali
    hech qachon ochilmaydi).
    """
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return None
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT user_id FROM channels WHERE channel_id = %s",
                (ch_id,),
            )
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else None
    except Exception as e:
        logger.error("get_channel_owner_id xatosi (%s): %s", ch_id, e)
        return None


def insert_channel_post_event(
    channel_id: str | int,
    message_id: int,
    post_hour: int | None = None,
    post_weekday: int | None = None,
    has_media: bool = False,
    media_type: str | None = None,
    media_file_id: str | None = None,
    length: int = 0,
    cta_detected: bool = False,
    emoji_density: float = 0.0,
) -> bool:
    """Kanal postining metama'lumotini ``channel_post_events`` ga yozadi.

    IDEMPOTENT: ``(channel_id, message_id)`` UNIQUE constrainti va
    ``ON CONFLICT ... DO NOTHING`` tufayli takroriy event (masalan
    tahrirlangan post yoki qayta yetib kelgan update) qayta yozilmaydi.

    Qaytadi: ``True`` — yangi qator qo'shildi; ``False`` — duplicate
    (allaqachon bor) yoki xato. Media faylining o'zi EMAS — faqat
    ``media_file_id`` va ``media_type`` (turi) saqlanadi.
    """
    ch_id = str(channel_id or "").strip()
    if not ch_id or message_id is None:
        return False
    try:
        mid = int(message_id)
        hour = int(post_hour) if post_hour is not None else None
        weekday = int(post_weekday) if post_weekday is not None else None
        med_type = str(media_type or "")[:32] or None
        file_id = str(media_file_id or "")[:255] or None
        length_v = max(0, int(length or 0))
        density_v = float(emoji_density or 0.0)
        if density_v < 0:
            density_v = 0.0
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO channel_post_events (
                    channel_id, message_id, post_hour, post_weekday,
                    has_media, media_type, media_file_id, length,
                    cta_detected, emoji_density
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (channel_id, message_id) DO NOTHING
                """,
                (
                    ch_id, mid, hour, weekday,
                    bool(has_media), med_type, file_id, length_v,
                    bool(cta_detected), density_v,
                ),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("insert_channel_post_event xatosi (%s/%s): %s",
                     ch_id, message_id, e)
        return False


def get_channel_post_events(channel_id: str | int, limit: int = 500) -> list[dict]:
    """Kanalning kuzatilgan post eventlarini (eng yangi oldin) qaytaradi.

    Qaytadi: ``[{channel_id, message_id, post_hour, post_weekday, has_media,
    media_type, length, cta_detected, emoji_density, created_at}, ...]``.
    Xatoda bo'sh ro'yxat (fail-soft).
    """
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return []
    try:
        limit = max(1, min(int(limit), 5000))
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT channel_id, message_id, post_hour, post_weekday,
                       has_media, media_type, length, cta_detected,
                       emoji_density, created_at
                FROM channel_post_events
                WHERE channel_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (ch_id, limit),
            )
            rows = cur.fetchall()
            return [
                {
                    "channel_id": r[0],
                    "message_id": r[1],
                    "post_hour": r[2],
                    "post_weekday": r[3],
                    "has_media": bool(r[4]),
                    "media_type": r[5],
                    "length": int(r[6] or 0),
                    "cta_detected": bool(r[7]),
                    "emoji_density": float(r[8] or 0.0),
                    "created_at": r[9].isoformat() if r[9] else "",
                }
                for r in rows
            ]
    except Exception as e:
        logger.error("get_channel_post_events xatosi (%s): %s", ch_id, e)
        return []


def save_channel_intelligence_profile(
    channel_id: str | int,
    avg_post_length: int | None = None,
    emoji_level: str | None = None,
    cta_style: str | None = None,
    formatting_style: str | None = None,
    top_topics: list | None = None,
    confidence: int | None = None,
    sample_size: int | None = None,
) -> bool:
    """Hisoblangan Channel DNA profilini ``channel_intelligence_profiles`` ga
    saqlaydi (UPSERT — kanal uchun bitta qator). Xatoda False (fail-soft).
    """
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return False
    try:
        import json as _json
        topics_json = _json.dumps(top_topics or [], ensure_ascii=False)
        conf = int(confidence) if confidence is not None else None
        if conf is not None:
            conf = max(0, min(100, conf))
        sample = int(sample_size) if sample_size is not None else None
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO channel_intelligence_profiles (
                    channel_id, avg_post_length, emoji_level, cta_style,
                    formatting_style, top_topics, confidence, sample_size,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, NOW())
                ON CONFLICT (channel_id) DO UPDATE SET
                    avg_post_length = EXCLUDED.avg_post_length,
                    emoji_level = EXCLUDED.emoji_level,
                    cta_style = EXCLUDED.cta_style,
                    formatting_style = EXCLUDED.formatting_style,
                    top_topics = EXCLUDED.top_topics,
                    confidence = EXCLUDED.confidence,
                    sample_size = EXCLUDED.sample_size,
                    updated_at = NOW()
                """,
                (
                    ch_id,
                    int(avg_post_length) if avg_post_length is not None else None,
                    str(emoji_level or "")[:32] or None,
                    str(cta_style or "")[:64] or None,
                    str(formatting_style or "")[:64] or None,
                    topics_json,
                    conf,
                    sample,
                ),
            )
            return True
    except Exception as e:
        logger.error("save_channel_intelligence_profile xatosi (%s): %s", ch_id, e)
        return False


def get_channel_intelligence_profile(channel_id: str | int) -> dict | None:
    """Saqlangan Channel DNA profilini qaytaradi (yo'q bo'lsa None)."""
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return None
    try:
        import json as _json
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT channel_id, avg_post_length, emoji_level, cta_style,
                       formatting_style, top_topics, confidence, sample_size,
                       updated_at
                FROM channel_intelligence_profiles
                WHERE channel_id = %s
                """,
                (ch_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        topics_raw = row[5]
        if isinstance(topics_raw, str):
            try:
                topics = _json.loads(topics_raw)
            except Exception:
                topics = []
        else:
            topics = list(topics_raw or [])
        return {
            "channel_id": row[0],
            "average_post_length": int(row[1]) if row[1] is not None else None,
            "avg_post_length": int(row[1]) if row[1] is not None else None,
            "emoji_level": row[2],
            "cta_style": row[3],
            "formatting_style": row[4],
            "top_topics": topics,
            "confidence": int(row[6]) if row[6] is not None else None,
            "confidence_score": int(row[6]) if row[6] is not None else None,
            "sample_size": int(row[7]) if row[7] is not None else None,
            "updated_at": row[8].isoformat() if row[8] else "",
        }
    except Exception as e:
        logger.error("get_channel_intelligence_profile xatosi (%s): %s", ch_id, e)
        return None


# ============================================================
# 🧬 FAZA 8,9,22 — KENGAYTIRILGAN CHANNEL DNA (channel_dna)
# Har bir metrika: language, tone, topics, avg_length, emoji_density,
# best_hours, best_weekdays, high_performing_formats — profile JSONB da
# sample_size, confidence (0.0-1.0), updated_at bilan.
# ============================================================

def save_channel_dna_profile(
    channel_id: str | int,
    profile: dict | None = None,
    sample_size: int | None = None,
    confidence: float | None = None,
    language: str | None = None,
    tone: str | None = None,
    topics: list | None = None,
    avg_length: int | None = None,
    emoji_density: float | None = None,
    best_hours: list | None = None,
    best_weekdays: list | None = None,
    high_performing_formats: list | None = None,
) -> bool:
    """Kengaytirilgan Channel DNA profilini ``channel_dna`` jadvaliga saqlaydi (UPSERT).

    Qat'iy qoidalar:
      * Idempotent: ON CONFLICT (channel_id) DO UPDATE
      * Har bir metrika sample_size, confidence, updated_at bilan (profile JSONB da)
      * Yetim yozuvlar oldini olish uchun FK: channels(channel_id) ON DELETE CASCADE
        (schema.sql va INTEGRITY_CONSTRAINTS da)
      * Indekslar: channel_id, updated_at (ON CONFLICT DO NOTHING bilan xavfsiz)
    """
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return False
    try:
        import json as _json

        # Normalize profile
        prof = dict(profile) if isinstance(profile, dict) else {}
        # Extract values from wrapped metrics if present
        def _extract_value(key, default=None):
            if key in prof:
                v = prof[key]
                if isinstance(v, dict) and "value" in v:
                    return v["value"]
                return v
            return default

        lang_val = language or _extract_value("language_value") or (_extract_value("language") if isinstance(_extract_value("language"), str) else None)
        if isinstance(prof.get("language"), dict):
            lang_val = prof["language"].get("value") or lang_val
        tone_val = tone or _extract_value("tone_value") or _extract_value("tone")
        if isinstance(prof.get("tone"), dict):
            tone_val = prof["tone"].get("value") or tone_val
        topics_val = topics if topics is not None else _extract_value("topics_value") or _extract_value("topics")
        if isinstance(prof.get("topics"), dict):
            topics_val = prof["topics"].get("value") or topics_val
        avg_len_val = avg_length
        if avg_len_val is None:
            avg_len_val = _extract_value("avg_length_value") or _extract_value("average_post_length") or _extract_value("avg_length")
            if isinstance(prof.get("avg_length"), dict):
                avg_len_val = prof["avg_length"].get("value") or avg_len_val
        emoji_dens_val = emoji_density
        if emoji_dens_val is None:
            emoji_dens_val = _extract_value("emoji_density_value") or _extract_value("emoji_density")
            if isinstance(prof.get("emoji_density"), dict):
                emoji_dens_val = prof["emoji_density"].get("value") or emoji_dens_val
        best_hours_val = best_hours if best_hours is not None else _extract_value("best_hours_value") or _extract_value("best_hours")
        if isinstance(prof.get("best_hours"), dict):
            best_hours_val = prof["best_hours"].get("value") or best_hours_val
        best_weekdays_val = best_weekdays if best_weekdays is not None else _extract_value("best_weekdays_value") or _extract_value("best_weekdays")
        if isinstance(prof.get("best_weekdays"), dict):
            best_weekdays_val = prof["best_weekdays"].get("value") or best_weekdays_val
        high_formats_val = high_performing_formats if high_performing_formats is not None else _extract_value("high_performing_formats_value") or _extract_value("high_performing_formats")
        if isinstance(prof.get("high_performing_formats"), dict):
            high_formats_val = prof["high_performing_formats"].get("value") or high_formats_val

        # Normalize types
        lang_str = str(lang_val or "")[:16] or None
        tone_str = str(tone_val or "")[:32] or None
        topics_json = _json.dumps(topics_val or [], ensure_ascii=False)
        # But topics column is JSONB, best to keep as JSON string for ::jsonb cast
        best_hours_json = _json.dumps(best_hours_val or [], ensure_ascii=False)
        best_weekdays_json = _json.dumps(best_weekdays_val or [], ensure_ascii=False)
        high_formats_json = _json.dumps(high_formats_val or [], ensure_ascii=False)
        profile_json = _json.dumps(prof or {}, ensure_ascii=False, default=str)

        sample = int(sample_size) if sample_size is not None else (int(prof.get("sample_size") or 0) if isinstance(prof.get("sample_size"), int) else None)
        if sample is None:
            # Try from metrics
            for k in ("avg_length", "language", "overall"):
                mv = prof.get(k)
                if isinstance(mv, dict) and "sample_size" in mv:
                    try:
                        sample = int(mv["sample_size"])
                        break
                    except Exception as _silent_exc:
                        log_silent_failure("repositories.channels_repository:save_channel_dna_profile:1400", _silent_exc, channel_id=channel_id)

        conf = None
        if confidence is not None:
            try:
                conf = float(confidence)
                conf = max(0.0, min(1.0, conf))
            except Exception:
                conf = None
        if conf is None and isinstance(prof.get("confidence"), (int, float)):
            try:
                c = float(prof["confidence"])
                # If it's 0-100, convert to 0-1
                if c > 1.0:
                    c = c / 100.0
                conf = max(0.0, min(1.0, c))
            except Exception as _silent_exc:
                log_silent_failure("repositories.channels_repository:save_channel_dna_profile:1417", _silent_exc, channel_id=channel_id)

        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO channel_dna (
                    channel_id, language, tone, topics, avg_length, emoji_density,
                    best_hours, best_weekdays, high_performing_formats,
                    sample_size, confidence, profile, updated_at
                )
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb, NOW())
                ON CONFLICT (channel_id) DO UPDATE SET
                    language = EXCLUDED.language,
                    tone = EXCLUDED.tone,
                    topics = EXCLUDED.topics,
                    avg_length = EXCLUDED.avg_length,
                    emoji_density = EXCLUDED.emoji_density,
                    best_hours = EXCLUDED.best_hours,
                    best_weekdays = EXCLUDED.best_weekdays,
                    high_performing_formats = EXCLUDED.high_performing_formats,
                    sample_size = EXCLUDED.sample_size,
                    confidence = EXCLUDED.confidence,
                    profile = EXCLUDED.profile,
                    updated_at = NOW()
                """,
                (
                    ch_id,
                    lang_str,
                    tone_str,
                    topics_json,
                    int(avg_len_val) if avg_len_val is not None else None,
                    float(emoji_dens_val) if emoji_dens_val is not None else None,
                    best_hours_json,
                    best_weekdays_json,
                    high_formats_json,
                    sample,
                    conf,
                    profile_json,
                ),
            )
            return True
    except Exception as e:
        logger.error("save_channel_dna_profile xatosi (%s): %s", ch_id, e)
        return False


def get_channel_dna_profile(channel_id: str | int) -> dict | None:
    """Saqlangan kengaytirilgan Channel DNA profilini qaytaradi (yo'q bo'lsa None)."""
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return None
    try:
        import json as _json
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT channel_id, language, tone, topics, avg_length, emoji_density,
                       best_hours, best_weekdays, high_performing_formats,
                       sample_size, confidence, profile, updated_at
                FROM channel_dna
                WHERE channel_id = %s
                """,
                (ch_id,),
            )
            row = cur.fetchone()
        if not row:
            return None

        def _parse_jsonb(val):
            if val is None:
                return None
            if isinstance(val, str):
                try:
                    return _json.loads(val)
                except Exception:
                    return val
            return val

        topics = _parse_jsonb(row[3])
        best_hours = _parse_jsonb(row[5])
        best_weekdays = _parse_jsonb(row[6])
        high_formats = _parse_jsonb(row[7])
        profile_raw = _parse_jsonb(row[11])

        return {
            "channel_id": row[0],
            "language": row[1],
            "tone": row[2],
            "topics": topics if isinstance(topics, list) else [],
            "avg_length": int(row[4]) if row[4] is not None else None,
            "emoji_density": float(row[5]) if row[5] is not None else None,
            "best_hours": best_hours if isinstance(best_hours, list) else [],
            "best_weekdays": best_weekdays if isinstance(best_weekdays, list) else [],
            "high_performing_formats": high_formats if isinstance(high_formats, list) else [],
            "sample_size": int(row[9]) if row[9] is not None else None,
            "confidence": float(row[10]) if row[10] is not None else None,
            "profile": profile_raw if isinstance(profile_raw, dict) else {},
            "updated_at": row[12].isoformat() if row[12] else "",
        }
    except Exception as e:
        logger.error("get_channel_dna_profile xatosi (%s): %s", ch_id, e)
        return None


# Alias for backward compatibility
save_channel_dna = save_channel_dna_profile


get_channel_dna = get_channel_dna_profile


# ============================================================
# 📥 PHASE D — KONTENT MANBALARI (11, 12-bandlar)
# ------------------------------------------------------------
# RSS/ATOM oqimi va URL→post oqimi uchun DB qatlami:
#   * content_sources — manbalar (interval, enabled, autopublish);
#   * source_items    — o'qilgan elementlar. Dublikat QAYTA ISHLANMAYDI:
#     UNIQUE(source_id, external_id) + INSERT ... ON CONFLICT DO NOTHING;
#   * source_drafts   — element asosidagi post loyihasi (Channel DNA
#     asosida tuzilgan tayyor matn), UNIQUE(source_item_id).
#
# IDOR: barcha o'qish/o'zgartirish/o'chirish so'rovlari ``user_id`` bilan
# filtrlanadi — boshqa foydalanuvchining manbasi ko'rinmaydi va
# o'zgartirilmaydi. Barcha funksiyalar sinxron va xatoda istisno
# ko'tarmaydi (fail-soft, log + xavfsiz standart qiymat).
# ============================================================

#: Bitta foydalanuvchi ulashi mumkin bo'lgan manbalar soni.
CONTENT_SOURCES_LIMIT = 10


#: Bitta element uchun qoralama holatlari.
SOURCE_DRAFT_STATUSES = ("pending", "queued", "dismissed")


#: Qoralama ro'yxati uchun standart limit.
SOURCE_DRAFTS_LIMIT = 30


def _content_source_row_to_dict(row) -> dict | None:
    """``content_sources`` qatorini dict ko'rinishiga o'giradi."""
    if not row:
        return None
    return {
        "id": int(row[0]),
        "user_id": int(row[1]) if row[1] is not None else None,
        "channel_id": str(row[2]) if row[2] is not None else "",
        "source_url": row[3] or "",
        "title": row[4] or "",
        "enabled": bool(row[5]),
        "interval_minutes": int(row[6] or 60),
        "autopublish": bool(row[7]),
        "last_checked_at": row[8].isoformat() if row[8] else "",
        "created_at": row[9].isoformat() if row[9] else "",
    }


def _source_draft_row_to_dict(row) -> dict | None:
    """``source_drafts`` qatorini dict ko'rinishiga o'giradi."""
    if not row:
        return None
    return {
        "id": int(row[0]),
        "source_id": int(row[1]) if row[1] is not None else None,
        "source_item_id": int(row[2]) if row[2] is not None else None,
        "user_id": int(row[3]) if row[3] is not None else None,
        "channel_id": str(row[4]) if row[4] is not None else "",
        "title": row[5] or "",
        "content": row[6] or "",
        "status": row[7] or "pending",
        "scheduled_post_id": int(row[8]) if row[8] else None,
        "created_at": row[9].isoformat() if row[9] else "",
    }


def create_content_source(
    user_id: int,
    channel_id: str,
    source_url: str,
    interval_minutes: int = 60,
    autopublish: bool = False,
    title: str = "",
) -> int:
    """Yangi kontent manbasini qo'shadi. Qaytadi: id yoki 0 (xato/limit)."""
    from services.sources.rss_service import clamp_interval

    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return 0
    url = str(source_url or "").strip()
    ch_id = str(channel_id or "").strip()
    if not url or not ch_id:
        return 0
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "SELECT COUNT(*) FROM content_sources WHERE user_id = %s",
                (uid,),
            )
            if int(cur.fetchone()[0] or 0) >= CONTENT_SOURCES_LIMIT:
                return 0
            cur.execute(
                """
                INSERT INTO content_sources
                    (user_id, channel_id, source_url, title, enabled,
                     interval_minutes, autopublish)
                VALUES (%s, %s, %s, %s, TRUE, %s, %s)
                RETURNING id
                """,
                (uid, ch_id, url, str(title or "")[:300],
                 clamp_interval(interval_minutes), bool(autopublish)),
            )
            return int(cur.fetchone()[0])
    except Exception as e:
        logger.error("create_content_source xatosi (user=%s): %s", user_id, e)
        return 0


def list_content_sources(user_id: int, limit: int = 20) -> list[dict]:
    """Foydalanuvchining manbalari (FAQAT o'ziniki — IDOR himoyasi)."""
    try:
        uid = int(user_id)
        safe_limit = max(1, min(int(limit), CONTENT_SOURCES_LIMIT))
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, channel_id, source_url, title, enabled,
                       interval_minutes, autopublish, last_checked_at, created_at
                FROM content_sources
                WHERE user_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (uid, safe_limit),
            )
            rows = cur.fetchall()
        return [item for item in (_content_source_row_to_dict(row) for row in rows)
                if item]
    except Exception as e:
        logger.error("list_content_sources xatosi (user=%s): %s", user_id, e)
        return []


def get_content_source(source_id: int, user_id: int) -> dict | None:
    """Bitta manba — FAQAT egasi uchun (IDOR himoyasi)."""
    try:
        sid, uid = int(source_id), int(user_id)
    except (TypeError, ValueError):
        return None
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, channel_id, source_url, title, enabled,
                       interval_minutes, autopublish, last_checked_at, created_at
                FROM content_sources
                WHERE id = %s AND user_id = %s
                """,
                (sid, uid),
            )
            return _content_source_row_to_dict(cur.fetchone())
    except Exception as e:
        logger.error("get_content_source xatosi (id=%s): %s", source_id, e)
        return None


def set_content_source_enabled(source_id: int, user_id: int,
                               enabled: bool) -> bool:
    """Manbani yoqadi/o'chiradi (FAQAT egasi)."""
    try:
        sid, uid = int(source_id), int(user_id)
    except (TypeError, ValueError):
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE content_sources SET enabled = %s "
                "WHERE id = %s AND user_id = %s",
                (bool(enabled), sid, uid),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("set_content_source_enabled xatosi (id=%s): %s", source_id, e)
        return False


def set_content_source_autopublish(source_id: int, user_id: int,
                                   enabled: bool) -> bool:
    """Avtopublish rejimini o'zgartiradi (FAQAT egasi)."""
    try:
        sid, uid = int(source_id), int(user_id)
    except (TypeError, ValueError):
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE content_sources SET autopublish = %s "
                "WHERE id = %s AND user_id = %s",
                (bool(enabled), sid, uid),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("set_content_source_autopublish xatosi (id=%s): %s",
                     source_id, e)
        return False


def set_content_source_interval(source_id: int, user_id: int,
                                interval_minutes: int) -> bool:
    """Tekshirish intervalini o'zgartiradi (FAQAT egasi)."""
    from services.sources.rss_service import clamp_interval

    try:
        sid, uid = int(source_id), int(user_id)
    except (TypeError, ValueError):
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE content_sources SET interval_minutes = %s "
                "WHERE id = %s AND user_id = %s",
                (clamp_interval(interval_minutes), sid, uid),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("set_content_source_interval xatosi (id=%s): %s",
                     source_id, e)
        return False


def delete_content_source(source_id: int, user_id: int) -> bool:
    """Manbani o'chiradi (elementlar/qoralamalar CASCADE bilan o'chadi)."""
    try:
        sid, uid = int(source_id), int(user_id)
    except (TypeError, ValueError):
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "DELETE FROM content_sources WHERE id = %s AND user_id = %s",
                (sid, uid),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_content_source xatosi (id=%s): %s", source_id, e)
        return False


def touch_content_source(source_id: int, checked_at=None) -> bool:
    """``last_checked_at`` ni yangilaydi (scheduler tick'idan chaqiriladi)."""
    try:
        sid = int(source_id)
    except (TypeError, ValueError):
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE content_sources SET last_checked_at = COALESCE(%s, NOW()) "
                "WHERE id = %s",
                (checked_at, sid),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("touch_content_source xatosi (id=%s): %s", source_id, e)
        return False


def get_due_content_sources(now=None, limit: int = 25) -> list[dict]:
    """Vaqti kelgan FAOLLAR (``enabled``) manbalar ro'yxati (scheduler uchun).

    Qaytaradi: manba maydonlari + ``lang`` (foydalanuvchi tili) +
    ``channel_title`` — bildirishnoma va prompt uchun qulay ko'rinishda.
    """
    try:
        safe_limit = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        safe_limit = 25
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT cs.id, cs.user_id, cs.channel_id, cs.source_url,
                       cs.title, cs.enabled, cs.interval_minutes,
                       cs.autopublish, cs.last_checked_at, cs.created_at,
                       COALESCE(u.language_code, 'uz') AS lang,
                       COALESCE(ch.channel_title, '') AS channel_title
                FROM content_sources cs
                LEFT JOIN users u ON u.user_id = cs.user_id
                LEFT JOIN channels ch ON ch.channel_id = cs.channel_id
                WHERE cs.enabled = TRUE
                  AND (
                        cs.last_checked_at IS NULL
                        OR cs.last_checked_at <= COALESCE(%s, NOW())
                           - make_interval(
                               mins => COALESCE(cs.interval_minutes, 60))
                      )
                ORDER BY COALESCE(cs.last_checked_at, cs.created_at) ASC
                LIMIT %s
                """,
                (now, safe_limit),
            )
            rows = cur.fetchall()
        result = []
        for row in rows:
            item = _content_source_row_to_dict(row[:10])
            if not item:
                continue
            item["lang"] = str(row[10] or "uz")
            item["channel_title"] = row[11] or ""
            result.append(item)
        return result
    except Exception as e:
        logger.error("get_due_content_sources xatosi: %s", e)
        return []


def get_source_item_external_ids(source_id: int, limit: int = 1000) -> list[str]:
    """Manba bo'yicha allaqachon o'qilgan element kalitlari (dublikat filtri)."""
    try:
        sid = int(source_id)
        safe_limit = max(1, min(int(limit), 5000))
    except (TypeError, ValueError):
        return []
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT external_id FROM source_items
                WHERE source_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (sid, safe_limit),
            )
            return [str(row[0]) for row in cur.fetchall() if row and row[0]]
    except Exception as e:
        logger.error("get_source_item_external_ids xatosi (id=%s): %s",
                     source_id, e)
        return []


def save_source_item(source_id: int, external_id: str,
                     canonical_url: str = "", title: str = "",
                     summary: str = "") -> int:
    """Elementni saqlaydi (DUBLIKAT: 0 qaytadi — qayta ishlanmaydi).

    ``INSERT ... ON CONFLICT (source_id, external_id) DO NOTHING`` — bir xil
    element ikkinchi marta kelganda YANGI qator yaratilmaydi, shuning uchun
    uning uchun qoralama ham yaratilmaydi.
    """
    try:
        sid = int(source_id)
    except (TypeError, ValueError):
        return 0
    ext_id = str(external_id or "").strip()
    if not ext_id:
        return 0
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO source_items
                    (source_id, external_id, canonical_url, title, summary)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (source_id, external_id) DO NOTHING
                RETURNING id
                """,
                (sid, ext_id[:512], str(canonical_url or "")[:2048],
                 str(title or "")[:500], str(summary or "")[:4000]),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0
    except Exception as e:
        logger.error("save_source_item xatosi (source=%s): %s", source_id, e)
        return 0


def mark_source_item_processed(item_id: int, processed_at=None) -> bool:
    """Element qayta ishlanganini belgilaydi (``processed_at``)."""
    try:
        iid = int(item_id)
    except (TypeError, ValueError):
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE source_items SET processed_at = COALESCE(%s, NOW()) "
                "WHERE id = %s",
                (processed_at, iid),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("mark_source_item_processed xatosi (id=%s): %s", item_id, e)
        return False


def create_source_draft(source_id: int, source_item_id: int, user_id: int,
                        channel_id: str, title: str, content: str,
                        autopublish: bool = False) -> int:
    """Element uchun post loyihasini (draft) saqlaydi.

    Bitta element uchun FAQAT BITTA qoralama (UNIQUE(source_item_id)) —
    takroriy chaqiruvda mavjud qoralama id'si qaytadi (idempotent).
    Qoralama har doim ``pending`` holatida yaratiladi: ``queued`` ga faqat
    navbatga MUVAFFAQIYATLI yozilgandan keyin o'tadi
    (``services.sources.rss_service.autopublish_draft``) — shu sababli
    rejalashtirish yiqilsa qoralama tasdiqlash ro'yxatida qolaveradi.
    """
    try:
        sid = int(source_id)
        iid = int(source_item_id)
        uid = int(user_id)
    except (TypeError, ValueError):
        return 0
    text = str(content or "").strip()
    if not text:
        return 0
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO source_drafts
                    (source_id, source_item_id, user_id, channel_id, title,
                     content, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending')
                ON CONFLICT (source_item_id) DO NOTHING
                RETURNING id
                """,
                (sid, iid, uid, str(channel_id or "")[:255],
                 str(title or "")[:500], text),
            )
            row = cur.fetchone()
            if row:
                return int(row[0])
            cur.execute(
                "SELECT id FROM source_drafts WHERE source_item_id = %s", (iid,))
            existing = cur.fetchone()
            return int(existing[0]) if existing else 0
    except Exception as e:
        logger.error("create_source_draft xatosi (item=%s): %s", source_item_id, e)
        return 0


def list_source_drafts(user_id: int, status: str = "pending",
                       limit: int = SOURCE_DRAFTS_LIMIT) -> list[dict]:
    """Foydalanuvchining post loyihalari (FAQAT o'ziniki — IDOR himoyasi)."""
    try:
        uid = int(user_id)
        safe_limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        return []
    state = str(status or "").strip().lower()
    try:
        with db_cursor() as cur:
            if state in SOURCE_DRAFT_STATUSES:
                cur.execute(
                    """
                    SELECT id, source_id, source_item_id, user_id, channel_id,
                           title, content, status, scheduled_post_id, created_at
                    FROM source_drafts
                    WHERE user_id = %s AND status = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (uid, state, safe_limit),
                )
            else:
                cur.execute(
                    """
                    SELECT id, source_id, source_item_id, user_id, channel_id,
                           title, content, status, scheduled_post_id, created_at
                    FROM source_drafts
                    WHERE user_id = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (uid, safe_limit),
                )
            rows = cur.fetchall()
        return [item for item in (_source_draft_row_to_dict(row) for row in rows)
                if item]
    except Exception as e:
        logger.error("list_source_drafts xatosi (user=%s): %s", user_id, e)
        return []


def get_source_draft(draft_id: int, user_id: int) -> dict | None:
    """Bitta qoralama — FAQAT egasi uchun (IDOR himoyasi)."""
    try:
        did, uid = int(draft_id), int(user_id)
    except (TypeError, ValueError):
        return None
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT id, source_id, source_item_id, user_id, channel_id,
                       title, content, status, scheduled_post_id, created_at
                FROM source_drafts
                WHERE id = %s AND user_id = %s
                """,
                (did, uid),
            )
            return _source_draft_row_to_dict(cur.fetchone())
    except Exception as e:
        logger.error("get_source_draft xatosi (id=%s): %s", draft_id, e)
        return None


def set_source_draft_status(draft_id: int, user_id: int, status: str,
                            scheduled_post_id: int = None) -> bool:
    """Qoralama holatini o'zgartiradi (FAQAT egasi; statuslar oq ro'yxatda)."""
    state = str(status or "").strip().lower()
    if state not in SOURCE_DRAFT_STATUSES:
        return False
    try:
        did, uid = int(draft_id), int(user_id)
    except (TypeError, ValueError):
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE source_drafts SET status = %s, "
                "scheduled_post_id = COALESCE(%s, scheduled_post_id) "
                "WHERE id = %s AND user_id = %s",
                (state, scheduled_post_id, did, uid),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("set_source_draft_status xatosi (id=%s): %s", draft_id, e)
        return False


def count_source_drafts(user_id: int, status: str = "pending") -> int:
    """Foydalanuvchining qoralamalari soni (badge/limit uchun)."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return 0
    state = str(status or "pending").strip().lower()
    try:
        with db_cursor() as cur:
            if state in SOURCE_DRAFT_STATUSES:
                cur.execute(
                    "SELECT COUNT(*) FROM source_drafts "
                    "WHERE user_id = %s AND status = %s", (uid, state))
            else:
                cur.execute(
                    "SELECT COUNT(*) FROM source_drafts WHERE user_id = %s",
                    (uid,))
            return int(cur.fetchone()[0] or 0)
    except Exception as e:
        logger.error("count_source_drafts xatosi (user=%s): %s", user_id, e)
        return 0


def get_recycle_candidates(channel_id: str | int, min_age_days: int = 14,
                           limit: int = 30) -> list[dict]:
    """♻️ Recycle uchun eski postlar (PHASE D, 13-band).

    ``channel_posts_history`` dan ``min_age_days`` kundan eski postlar
    olinadi (views + reaksiyalar soni bilan). Bu funksiya FAQAT xom
    ma'lumot beradi — «yaxshi ko'rsatkich» tanlovi sof funksiya
    ``services.channels.recycle.select_recycle_candidates`` da bajariladi
    (soxta raqamlar uydirilmasligi uchun).
    """
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return []
    try:
        days = max(1, int(min_age_days))
        safe_limit = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        return []
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT h.id, h.message_id, h.content, h.views, h.post_date,
                       COALESCE(r.reactions, 0) AS reactions
                FROM channel_posts_history h
                LEFT JOIN (
                    SELECT spm.message_id, COUNT(pr.id) AS reactions
                    FROM sent_post_messages spm
                    JOIN post_reactions pr ON pr.post_id = spm.post_id
                    GROUP BY spm.message_id
                ) r ON r.message_id = h.message_id
                WHERE h.channel_id = %s
                  AND h.post_date <= NOW() - make_interval(days => %s)
                ORDER BY h.post_date DESC, h.id DESC
                LIMIT %s
                """,
                (ch_id, days, safe_limit),
            )
            rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "message_id": row[1],
                "content": row[2] or "",
                "text": row[2] or "",
                "views": int(row[3] or 0),
                "post_date": row[4].isoformat() if row[4] else "",
                "reactions": int(row[5] or 0),
            }
            for row in rows
        ]
    except Exception as e:
        logger.error("get_recycle_candidates xatosi (channel=%s): %s",
                     channel_id, e)
        return []
