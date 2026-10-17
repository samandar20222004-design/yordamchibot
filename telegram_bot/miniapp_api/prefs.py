"""Mini App'da o'zgartiriladigan foydalanuvchi sozlamalari (bot ``user_settings`` jadvali bilan BIR XIL kalitlar).

Kalitlar va standart qiymatlar botdagi ``handlers.settings.NOTIF_SETTING_KEYS`` / ``SETTING_DEFAULTS`` bilan mos
(``tests/miniapp_settings_test.py`` mosligini tekshiradi). Imzo/tozalash sozlamalari ATAYLAB yo'q (faqat botda).
"""
from __future__ import annotations

NOTIFICATION_KEYS = ("notify_scheduled", "notify_news", "notify_morning_digest", "notify_uzbek_calendar")
NOTIFICATION_DEFAULTS = {
    "notify_scheduled": True,
    "notify_news": False,
    "notify_morning_digest": True,
    "notify_uzbek_calendar": True,
}


def read_notifications(cur, user_id: int) -> dict:
    """``{kalit: bool}`` — saqlanmagan kalit uchun standart qiymat."""
    result = dict(NOTIFICATION_DEFAULTS)
    cur.execute(
        "SELECT key, value FROM user_settings WHERE user_id = %s AND key = ANY(%s)",
        (int(user_id), list(NOTIFICATION_KEYS)),
    )
    for key, value in cur.fetchall():
        if key in result:
            result[key] = bool(value)
    return result
