"""📢 Kanal yorlig'i: «Nomi» (@username) — yuborish natijasida aniq ko'rsatiladi.

``channels`` jadvalida alohida username ustuni yo'q: ochiq kanal ``channel_id``
sifatida ``@username`` bilan ulanadi, yopiq kanal esa raqamli ID bilan. Shu
sababli username faqat ``channel_id`` ochiq nom bo'lsa ko'rsatiladi
(raqamli ID foydalanuvchiga ko'rsatilmaydi).

Modul HECH QANDAY og'ir bog'liqliksiz (faqat stdlib) — handlerlar va testlar
xavfsiz import qiladi.
"""

from __future__ import annotations

import html
import re

__all__ = ["channel_username", "channel_label", "channel_label_html", "channel_row",
           "sent_notice"]

_USERNAME_RE = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{3,31})$")


def channel_username(channel_id) -> str:
    """``@mirza_ch`` (yoki ``mirza_ch``) → ``@mirza_ch``; raqamli ID → ``""``."""
    match = _USERNAME_RE.match(str(channel_id or "").strip())
    return f"@{match.group(1)}" if match else ""


def channel_label(channel_id, title="") -> str:
    """Oddiy matn: ``"Jizzax Yangiliklari" (@jizzax_ch)``.

    Nom bo'lmasa username (yoki ``"Kanal"``), username bo'lmasa faqat nom.
    """
    username = channel_username(channel_id)
    name = str(title or "").strip()
    if name and name == str(channel_id or "").strip() and username:
        name = ""  # sarlavha o'rniga ID saqlangan — takrorlamaymiz
    if name and username:
        return f'"{name}" ({username})'
    if name:
        return f'"{name}"'
    return username or '"Kanal"'


def channel_label_html(channel_id, title="") -> str:
    """``channel_label`` — HTML-xavfsiz (``parse_mode="HTML"`` uchun)."""
    return html.escape(channel_label(channel_id, title), quote=False)


def channel_row(channel) -> tuple:
    """Kanal qatori (tuple / list / dict) → ``(channel_id, title)``."""
    if isinstance(channel, dict):
        return (channel.get("channel_id") or channel.get("id"),
                channel.get("channel_title") or channel.get("title") or "")
    if isinstance(channel, (tuple, list)):
        if len(channel) >= 2:
            return channel[0], channel[1]
        if channel:
            return channel[0], ""
    return channel, ""


def sent_notice(lang: str, labels: list) -> str:
    """Yuborish natijasi: aniq nishon kanal(lar) nomi va username'i bilan.

    ``labels`` — ``channel_label_html`` natijalari. Bitta kanal::

        ✅ Post "Jizzax Yangiliklari" (@jizzax_ch) kanaliga yuborildi!
    """
    from translations import content_menu_t

    labels = [str(x) for x in (labels or []) if x]
    if len(labels) == 1:
        return content_menu_t("sent_to_one", lang, channel=labels[0])
    shown = "\n".join(f"• {item}" for item in labels[:10])
    if len(labels) > 10:
        shown += f"\n… +{len(labels) - 10}"
    return content_menu_t("sent_to_many", lang, count=len(labels), channels=shown)
