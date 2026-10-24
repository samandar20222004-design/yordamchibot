"""🔗 Manba havolalari (PostgreSQL): ``https://t.me/<bot>?start=s_<kod>`` — kim qaysi havola bilan kelgani.

Qoidalar:
  * kod faqat ``[a-z0-9_]``, 2–24 belgi (``normalize_code``); havola matni ``s_<kod>`` (Telegram start parametri chegarasida);
  * bitta foydalanuvchi + bitta havola = bitta qator (``tracked_link_visits``); ``is_new`` — shu havola orqali
    ro'yxatdan o'tgan (birinchi tegish: keyin boshqa havola bossa ham birinchisi o'zgarmaydi);
  * ``clicks`` — havola orqali har bir /start (takrorlar bilan); «tashrif» — noyob foydalanuvchilar;
  * faollik: kanal ulagan (``channels`` qatori bor yoki post qilgan), post qilgan (``first_post_at`` — post saqlanganda
    bir marta yoziladi, chunki eski postlar 30 kundan keyin tozalanadi), to'lagan (muvaffaqiyatli to'lov yoki PRO/ULTRA).
"""
from __future__ import annotations

import re

from database import db_cursor

CODE_RE = re.compile(r"^[a-z0-9_]{2,24}$")
PAYLOAD_PREFIX = "s_"
TITLE_MAX = 80
MAX_LINKS = 500

_LINK_COLS = "l.id, l.code, l.title, l.owner_id, l.created_by, l.is_active, l.clicks, l.created_at"
_LINK_KEYS = ("id", "code", "title", "owner_id", "created_by", "is_active", "clicks", "created_at")
_STATS = (
    "COUNT(v.user_id) AS visitors, "
    "COUNT(v.user_id) FILTER (WHERE v.is_new) AS new_users, "
    "COUNT(v.user_id) FILTER (WHERE v.is_new AND (v.first_post_at IS NOT NULL "
    "  OR EXISTS (SELECT 1 FROM channels c WHERE c.user_id = v.user_id))) AS with_channel, "
    "COUNT(v.user_id) FILTER (WHERE v.is_new AND v.first_post_at IS NOT NULL) AS posted, "
    "COUNT(v.user_id) FILTER (WHERE v.is_new AND (EXISTS (SELECT 1 FROM payments p WHERE p.user_id = v.user_id "
    "  AND p.status = 'succeeded') OR EXISTS (SELECT 1 FROM users u WHERE u.user_id = v.user_id "
    "  AND u.plan_type IN ('pro', 'ultra')))) AS paid"
)
_STAT_KEYS = ("visitors", "new_users", "with_channel", "posted", "paid")


def normalize_code(raw) -> str | None:
    """``" Kanal-1 "`` -> ``"kanal_1"``; yaroqsiz bo'lsa ``None``."""
    code = re.sub(r"[\s\-]+", "_", str(raw or "").strip().lower())
    return code if CODE_RE.match(code) else None


def code_from_payload(arg) -> str | None:
    """/start parametri ``s_<kod>`` bo'lsa kodni qaytaradi (boshqa parametrlar e'tiborsiz)."""
    if not isinstance(arg, str) or not arg.startswith(PAYLOAD_PREFIX):
        return None
    code = arg[len(PAYLOAD_PREFIX):]
    return code if CODE_RE.match(code) else None


def payload_for(code: str) -> str:
    return PAYLOAD_PREFIX + code


def _row(row, keys) -> dict | None:
    if not row:
        return None
    return dict(zip(keys, row))


def create_link(code: str, title: str, owner_id: int | None, created_by: int | None) -> dict:
    """Yangi havola. ``{"ok": True, "link": {...}}`` yoki ``{"ok": False, "error": bad_code|bad_title|exists|limit|owner_unknown}``."""
    norm = normalize_code(code)
    if not norm:
        return {"ok": False, "error": "bad_code"}
    title = " ".join(str(title or "").split())[:TITLE_MAX]
    if not title:
        return {"ok": False, "error": "bad_title"}
    with db_cursor(commit=True) as cur:
        if owner_id is not None:
            cur.execute("SELECT 1 FROM users WHERE user_id = %s", (int(owner_id),))
            if not cur.fetchone():
                return {"ok": False, "error": "owner_unknown"}
        cur.execute("SELECT COUNT(*) FROM tracked_links")
        if int(cur.fetchone()[0]) >= MAX_LINKS:
            return {"ok": False, "error": "limit"}
        cur.execute(
            "INSERT INTO tracked_links (code, title, owner_id, created_by) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (code) DO NOTHING RETURNING id, code, title, owner_id, created_by, is_active, clicks, created_at",
            (norm, title, owner_id, created_by),
        )
        row = cur.fetchone()
    if not row:
        return {"ok": False, "error": "exists"}
    return {"ok": True, "link": _row(row, _LINK_KEYS)}


def get_link(code: str) -> dict | None:
    norm = normalize_code(code)
    if not norm:
        return None
    with db_cursor() as cur:
        cur.execute(f"SELECT {_LINK_COLS} FROM tracked_links l WHERE l.code = %s", (norm,))  # nosec B608 — ustunlar doimiy
        return _row(cur.fetchone(), _LINK_KEYS)


def list_links(limit: int = 50, owner_id: int | None = None) -> list[dict]:
    """Havolalar statistikasi bilan (yangi -> eski). ``owner_id`` berilsa faqat o'shaniki."""
    where, params = ("WHERE l.owner_id = %s", [int(owner_id)]) if owner_id is not None else ("", [])
    with db_cursor() as cur:
        cur.execute(
            f"SELECT {_LINK_COLS}, {_STATS} FROM tracked_links l "  # nosec B608 — doimiy SQL bo'laklari, qiymatlar %s bilan
            f"LEFT JOIN tracked_link_visits v ON v.link_id = l.id {where} "
            "GROUP BY l.id ORDER BY l.created_at DESC, l.id DESC LIMIT %s",
            (*params, int(limit)),
        )
        return [dict(zip(_LINK_KEYS + _STAT_KEYS, r)) for r in cur.fetchall()]


def link_stats(link_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute(f"SELECT {_STATS} FROM tracked_link_visits v WHERE v.link_id = %s", (int(link_id),))  # nosec B608 — doimiy
        row = cur.fetchone() or (0, 0, 0, 0, 0)
    return dict(zip(_STAT_KEYS, (int(x or 0) for x in row)))


def recent_joins(link_id: int, limit: int = 20) -> list[dict]:
    """Shu havola orqali ro'yxatdan o'tganlar (yangi -> eski) va har birining holati."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT v.user_id, u.username, u.full_name, v.first_at, "
            "(v.first_post_at IS NOT NULL OR EXISTS (SELECT 1 FROM channels c WHERE c.user_id = v.user_id)), "
            "(v.first_post_at IS NOT NULL), "
            "(EXISTS (SELECT 1 FROM payments p WHERE p.user_id = v.user_id AND p.status = 'succeeded') "
            " OR COALESCE(u.plan_type, 'free') IN ('pro', 'ultra')) "
            "FROM tracked_link_visits v LEFT JOIN users u ON u.user_id = v.user_id "
            "WHERE v.link_id = %s AND v.is_new ORDER BY v.first_at DESC LIMIT %s",
            (int(link_id), int(limit)),
        )
        keys = ("user_id", "username", "full_name", "joined_at", "has_channel", "posted", "paid")
        return [dict(zip(keys, r)) for r in cur.fetchall()]


def source_of_user(user_id: int) -> dict | None:
    """Foydalanuvchi qaysi havola bilan ro'yxatdan o'tgan (bo'lmasa ``None``) va u yana qaysilarini bosgan."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT l.code, l.title, l.owner_id, v.is_new, v.first_at FROM tracked_link_visits v "
            "JOIN tracked_links l ON l.id = v.link_id WHERE v.user_id = %s ORDER BY v.first_at",
            (int(user_id),),
        )
        rows = cur.fetchall()
    if not rows:
        return None
    visits = [dict(zip(("code", "title", "owner_id", "is_new", "first_at"), r)) for r in rows]
    origin = next((x for x in visits if x["is_new"]), None)
    return {"origin": origin, "visits": visits}


def set_active(code: str, active: bool) -> bool:
    norm = normalize_code(code)
    if not norm:
        return False
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE tracked_links SET is_active = %s WHERE code = %s", (bool(active), norm))
        return cur.rowcount > 0


def record_visit(link_id: int, user_id: int, is_new: bool) -> None:
    """/start havola orqali: bosish +1 va (birinchi marta bo'lsa) tashrif qatori. Takrorlar ``is_new`` ni o'zgartirmaydi."""
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE tracked_links SET clicks = clicks + 1 WHERE id = %s", (int(link_id),))
        cur.execute(
            "INSERT INTO tracked_link_visits (link_id, user_id, is_new) VALUES (%s, %s, %s) "
            "ON CONFLICT (link_id, user_id) DO NOTHING",
            (int(link_id), int(user_id), bool(is_new)),
        )


# Post saqlash har safar chaqiradi: bir marta tekshirilgan foydalanuvchiga qayta so'rov yubormaslik uchun jarayon keshi.
_POST_CHECKED: set[int] = set()
_POST_CHECKED_MAX = 50_000


def mark_first_post(user_id: int) -> bool:
    """Havola bilan kelgan foydalanuvchining birinchi posti vaqtini bir marta yozadi. Yozilgan bo'lsa ``True``."""
    uid = int(user_id)
    if uid in _POST_CHECKED:
        return False
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE tracked_link_visits SET first_post_at = NOW() WHERE user_id = %s AND is_new AND first_post_at IS NULL",
            (uid,),
        )
        changed = cur.rowcount > 0
    if len(_POST_CHECKED) >= _POST_CHECKED_MAX:
        _POST_CHECKED.clear()
    _POST_CHECKED.add(uid)
    return changed


def find_user_id(token: str) -> int | None:
    """``@username`` yoki raqamli ID -> botdagi foydalanuvchi ID (topilmasa ``None``)."""
    raw = str(token or "").strip()
    if raw.lstrip("-").isdigit():
        uid = int(raw)
        with db_cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE user_id = %s", (uid,))
            row = cur.fetchone()
        return int(row[0]) if row else None
    name = raw.lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", name):
        return None
    with db_cursor() as cur:
        cur.execute("SELECT user_id FROM users WHERE LOWER(username) = LOWER(%s) ORDER BY user_id LIMIT 1", (name,))
        row = cur.fetchone()
    return int(row[0]) if row else None
