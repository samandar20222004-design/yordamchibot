"""Post/qoralama mediasi: bitta fayl yoki albom (10 tagacha) ustida sof (DB'siz) amallar.

Saqlash formati botniki bilan BIR XIL: bitta media -> ``post_type`` = tur, ``file_id`` = Telegram file_id;
bir nechta -> ``post_type='album'``, ``file_id`` = JSON ro'yxat ``[{"type", "file_id", "caption"}]``.
Telegram qoidalari: albom 2..10 ta; rasm va video aralashishi mumkin; hujjat/audio faqat o'z turi bilan;
GIF (animation) albomga kirmaydi (alohida yuboriladi).
"""
from __future__ import annotations

import json

from .errors import ApiError

ALBUM_MAX = 10
PHOTO_VIDEO = ("photo", "video")
PREVIEW_TYPES = ("photo", "video", "animation", "document")


def items_of(post_type, file_id) -> list[dict]:
    """``(post_type, file_id)`` -> elementlar ro'yxati (yaroqsiz bo'lsa bo'sh)."""
    pt = str(post_type or "").lower()
    if pt in ("", "text") or not isinstance(file_id, str) or not file_id:
        return []
    if pt != "album":
        return [{"type": pt, "file_id": file_id, "caption": ""}]
    try:
        raw = json.loads(file_id)
    except ValueError:
        return []
    out = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and isinstance(item.get("file_id"), str) and item["file_id"]:
            out.append({**item, "type": str(item.get("type") or "photo").lower()})
    return out[:ALBUM_MAX]


def pack(items: list[dict]) -> tuple[str, str | None]:
    """Elementlar -> ``(post_type, file_id)``: 0 -> matn, 1 -> yakka media, 2+ -> albom."""
    if not items:
        return "text", None
    if len(items) == 1:
        return items[0]["type"], items[0]["file_id"]
    return "album", json.dumps(items, ensure_ascii=False)


def _group(kind: str) -> str:
    return "pv" if kind in PHOTO_VIDEO else kind


def add_item(post_type, file_id, new_type: str, new_file_id: str) -> tuple[str, str | None]:
    """Mavjud mediaga yangi fayl qo'shadi. 10 dan oshsa ``album_full``; aralash turlar -> ``album_mixed``."""
    items = items_of(post_type, file_id)
    if not items:
        return pack([{"type": new_type, "file_id": new_file_id, "caption": ""}])
    if len(items) >= ALBUM_MAX:
        raise ApiError("album_full")
    kinds = [i["type"] for i in items] + [new_type]
    if "animation" in kinds or len({_group(k) for k in kinds}) > 1:
        raise ApiError("album_mixed")
    return pack(items + [{"type": new_type, "file_id": new_file_id, "caption": ""}])


def remove_item(post_type, file_id, index: int) -> tuple[str, str | None]:
    """``index``-chi elementni olib tashlaydi (qolmasa — matnli post)."""
    items = items_of(post_type, file_id)
    if not 0 <= index < len(items):
        raise ApiError("not_found")
    return pack(items[:index] + items[index + 1:])


def public_items(post_type, file_id) -> list[dict]:
    """Mijozga: ``[{"type", "previewable"}]`` (``file_id`` YO'Q)."""
    return [{"type": i["type"], "previewable": i["type"] in PREVIEW_TYPES} for i in items_of(post_type, file_id)]


def file_id_at(post_type, file_id, index: int | None = None) -> str | None:
    """Ko'rsatish mumkin bo'lgan element file_id'si. ``index=None`` — albomdagi BIRINCHI ko'rsatiladigani;
    aniq ``index`` — shu o'rindagisi (yo'q yoki ko'rsatib bo'lmasa ``None``)."""
    items = items_of(post_type, file_id)
    if index is None:
        for item in items:
            if item["type"] in PREVIEW_TYPES:
                return item["file_id"]
        return None
    if not 0 <= index < len(items):
        return None
    item = items[index]
    return item["file_id"] if item["type"] in PREVIEW_TYPES else None


def parse_index(value, default: int | None = None) -> int | None:
    """``?i=`` so'rov parametri: butun, 0..ALBUM_MAX-1."""
    if value in (None, ""):
        return default
    try:
        n = int(str(value))
    except ValueError:
        raise ApiError("bad_request") from None
    if not 0 <= n < ALBUM_MAX:
        raise ApiError("bad_request")
    return n
