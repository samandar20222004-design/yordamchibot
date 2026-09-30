# -*- coding: utf-8 -*-
"""
=====================================================================
 ⚙️ SETTINGS — bot sozlamalari (kalit/qiymat) keshi bilan
=====================================================================

Global bot sozlamalari (``settings`` jadvali): kalit-qiymat yozish/o'qish, topshiriq bo'yicha guruhlash va o'chirish. Kichik TTL kesh bilan.

Qatlam: REPOSITORY — domain ma'lumotlariga kirish.

Bu modul yadroga (``database``: pool / tranzaksiya / kesh / sxema)
``repositories.runtime`` orqali **kech bog'lanadi**: ``db_cursor``,
``transaction``, ``_cache_*`` va boshqa yadro yordamchilari chaqiruv
paytida ``database`` modulining joriy atributiga qarab yuradi. Shu
sabab ``unittest.mock.patch("database.db_cursor")`` kabi mavjud mock
nuqtalari bu modulga ko'chirilgandan keyin ham kuchini yo'qotmaydi.
"""

import logging

from database import DB_SETTINGS_CACHE_TTL, _MISS
from repositories.runtime import (  # noqa: F401
    _cache_clear, _cache_get, _cache_set, db_cursor
)

logger = logging.getLogger(__name__)


# ====================================================================
# ⚙️ SETTINGS — bot sozlamalari (kalit/qiymat) keshi bilan
# ====================================================================

def set_setting(key: str, value: str) -> bool:
    """``system_settings`` jadvaliga sozlamani yozadi (upsert).

    Muvaffaqiyatda True qaytadi — chaqiruvchi saqlanganini tekshira oladi.
    """
    key = str(key or "").strip()
    if not key:
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO system_settings (key, value)
                VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (key, "" if value is None else str(value)))
        _cache_clear("setting:")
        _cache_clear("system_stats")
        return True
    except Exception as e:
        logger.error(f"Sozlama xatosi: {e}")
        return False


def get_setting(key: str, default: str = "") -> str:
    """``system_settings`` dan qiymat o'qiydi.

    Kesh faqat BAZADAGI qiymatni saqlaydi — ``default`` keshlanmaydi, shuning
    uchun turli default bilan chaqirilganda ham to'g'ri natija qaytadi.
    """
    key = str(key or "").strip()
    if not key:
        return default
    cache_key = f"setting:{key}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return default if cached is None else cached
    try:
        with db_cursor() as cur:
            cur.execute("SELECT value FROM system_settings WHERE key = %s", (key,))
            row = cur.fetchone()
            value = row[0] if row else None
            _cache_set(cache_key, value, DB_SETTINGS_CACHE_TTL)
            return default if value is None else value
    except Exception as e:
        logger.error(f"Sozlama olish xatosi: {e}")
        return default


def get_settings_map(keys=None) -> dict:
    """Bir nechta sozlamani bitta so'rovda o'qiydi: ``{key: value}``.

    ``keys`` berilmasa — barcha sozlamalar qaytadi. Admin paneldagi
    "tizim sozlamalari" ekrani shu funksiyadan foydalanadi.
    """
    try:
        with db_cursor() as cur:
            if keys is not None:
                keys = [str(k) for k in keys if str(k).strip()]
                if not keys:
                    return {}
                cur.execute(
                    "SELECT key, value FROM system_settings WHERE key = ANY(%s) ORDER BY key",
                    (keys,),
                )
            else:
                cur.execute("SELECT key, value FROM system_settings ORDER BY key")
            return {k: (v or "") for k, v in cur.fetchall()}
    except Exception as e:
        logger.error(f"Sozlamalarni olish xatosi: {e}")
        return {}


def delete_setting(key: str) -> bool:
    """Sozlamani o'chiradi (default qiymatga qaytarish uchun)."""
    key = str(key or "").strip()
    if not key:
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM system_settings WHERE key = %s", (key,))
            removed = cur.rowcount > 0
        _cache_clear("setting:")
        return removed
    except Exception as e:
        logger.error(f"Sozlamani o'chirish xatosi: {e}")
        return False