"""Bot -> Mini App qoralamasi (``miniapp_drafts``).

Foydalanuvchi postni botda yuboradi (matn yoki rasm/video/...), bot shu yerga
BITTA joriy qoralamani yozadi, Mini App esa uni ochib tahrirlaydi va rejalashtiradi.
Media Telegram ``file_id`` ko'rinishida qoladi — Mini App fayl yuklamaydi, mijozga
``file_id`` ham berilmaydi (faqat tur va oldindan ko'rish imkoniyati).

Yozuv — sinxron (bot ``db.run_db`` orqali, Mini App ``asyncio.to_thread`` orqali);
o'qish — ``ReadOnlyRunner`` kursori bilan (:func:`read_draft`).
"""
from __future__ import annotations

import json
import re

DRAFT_TTL_HOURS = 48
MAX_TEXT = 4096
MAX_FILE_ID = 20000          # album (JSON ro'yxat) uchun ham yetarli
MAX_BTN_TEXT = 64
MAX_BTN_URL = 2000
POST_TYPES = ("text", "photo", "video", "animation", "document", "audio",
              "voice", "sticker", "album")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_str(value, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    if _CTRL_RE.search(text):
        text = _CTRL_RE.sub("", text)
    text = text.strip()
    return text[:limit] if text else None


def build_payload(user_data) -> dict | None:
    """Bot ``context.user_data`` -> qoralama (yaroqsiz bo'lsa ``None``)."""
    post_type = str(user_data.get("post_type") or "").lower()
    if post_type not in POST_TYPES:
        return None
    content = user_data.get("content")
    file_id = user_data.get("file_id")
    if not isinstance(file_id, str):
        file_id = None if file_id is None else json.dumps(file_id, ensure_ascii=False)
    if post_type != "text" and not file_id:
        return None
    if post_type == "text" and not (content and str(content).strip()):
        return None
    emojis = user_data.get("reaction_emojis")
    if isinstance(emojis, (list, tuple, set)):
        emojis = " ".join(str(e) for e in emojis if e)
    try:
        hours = int(user_data.get("delete_after_hours") or 0)
    except (TypeError, ValueError):
        hours = 0
    channel_id = user_data.get("selected_channel_id")
    return {
        "post_type": post_type,
        "content": _clean_str(content, MAX_TEXT) or "",
        "file_id": file_id[:MAX_FILE_ID] if file_id else None,
        "btn_text": _clean_str(user_data.get("btn_text"), MAX_BTN_TEXT),
        "btn_url": _clean_str(user_data.get("btn_url"), MAX_BTN_URL),
        "enable_reactions": bool(user_data.get("enable_reactions")),
        "reaction_emojis": _clean_str(emojis, 200),
        "delete_after_hours": max(0, min(hours, 24 * 365)),
        "channel_id": str(channel_id) if channel_id not in (None, "") else None,
    }


def save_draft(user_id: int, payload: dict) -> None:
    from repositories.runtime import db_cursor

    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO miniapp_drafts (user_id, payload, updated_at) "
            "VALUES (%s, %s::jsonb, NOW()) "
            "ON CONFLICT (user_id) DO UPDATE "
            "SET payload = EXCLUDED.payload, updated_at = NOW()",
            (int(user_id), json.dumps(payload, ensure_ascii=False)),
        )


def delete_draft(user_id: int, cur=None) -> bool:
    if cur is not None:
        cur.execute("DELETE FROM miniapp_drafts WHERE user_id = %s", (int(user_id),))
        return cur.rowcount > 0
    from repositories.runtime import db_cursor

    with db_cursor(commit=True) as own:
        own.execute("DELETE FROM miniapp_drafts WHERE user_id = %s", (int(user_id),))
        return own.rowcount > 0


def read_draft(cur, user_id: int) -> dict | None:
    """Muddati o'tmagan qoralama: ``{"payload": dict, "updated_at": datetime}``."""
    cur.execute(
        "SELECT payload, updated_at FROM miniapp_drafts "
        "WHERE user_id = %s AND updated_at > NOW() - (%s || ' hours')::interval",
        (int(user_id), str(DRAFT_TTL_HOURS)),
    )
    row = cur.fetchone()
    if not row:
        return None
    payload = row[0]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return None
    if not isinstance(payload, dict):
        return None
    return {"payload": payload, "updated_at": row[1]}


def public_view(draft: dict, iso) -> dict:
    """Mijozga beriladigan ko'rinish (``file_id`` YO'Q)."""
    p = draft["payload"]
    post_type = str(p.get("post_type") or "text")
    count = None
    if post_type == "album":
        try:
            items = json.loads(p.get("file_id") or "[]")
            count = len(items) if isinstance(items, list) else None
        except ValueError:
            count = None
    return {
        "post_type": post_type,
        "text": p.get("content") or "",
        "button_text": p.get("btn_text"),
        "button_url": p.get("btn_url"),
        "channel_id": p.get("channel_id"),
        "reactions": bool(p.get("enable_reactions")),
        "delete_after_hours": int(p.get("delete_after_hours") or 0),
        "media": None if post_type == "text" else {
            "type": post_type, "previewable": post_type == "photo", "count": count},
        "updated_at": iso(draft["updated_at"]),
    }
