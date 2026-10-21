"""👥 Jamoa: yordamchi taklifi, o'rindiqlar (seat), rollar va ish joyi (workspace).

Qoidalar (egasining talabi):
  * PRO/FREE — bitta odam hamma kanalni boshqaradi: yordamchi qo'shib bo'lmaydi (``team_seats`` = 0).
  * ULTRA — egasi + ``TIER_LIMITS['ultra']['team_seats']`` (standart 2) ta yordamchi akkaunt: jami 3.
  * Yordamchi KANAL bo'yicha rol oladi (``channel_members``): ``editor`` (post yozadi/tahrirlaydi),
    ``scheduler`` (vaqt qo'yadi/o'zgartiradi), ``analyst`` (faqat ko'radi).
  * Taklif — bir martalik havola; token bazada FAQAT sha256 hash ko'rinishida, 7 kun amal qiladi.
  * O'rindiq = egasining kanallaridagi NOYOB yordamchi. Egasi ULTRA'dan tushsa, a'zolar o'chmaydi,
    lekin faqat ENG ESKI ``team_seats`` tasi ishlay oladi (qolganlariga ruxsat vaqtincha yopiladi).
Hammasi sinxron (``db_cursor``); chaqiruvchi ``run_db`` / ``asyncio.to_thread`` orqali ishlatadi.
"""
from __future__ import annotations

import hashlib
import logging
import secrets

from config import TIER_LIMITS
from database import _invalidate_user, db_cursor

logger = logging.getLogger(__name__)

ROLES = ("editor", "scheduler", "analyst")
MODES = ("owner", "helper")
INVITE_TTL_DAYS = 7
MAX_PENDING_INVITES = 10
MAX_INVITE_CHANNELS = 10
MAX_JOINS_PER_DAY = 10  # kuniga egasi qo'sha oladigan yordamchilar (havola + to'g'ridan-to'g'ri): spamga qarshi
MIN_SEARCH_CHARS = 3

#: Yordamchi ruxsatlari (egasi har biriga alohida beradi). «Ko'rish» har doim bor.
#: create — yangi post yaratish/rejalash; edit — matn, tugma, media tahriri; reschedule — vaqtni o'zgartirish;
#: delete — postni bekor qilish; send_now — darhol yuborish; analytics — kanal statistikasi; ai — AI (EGASI kvotasidan).
PERMS = ("create", "edit", "reschedule", "delete", "send_now", "analytics", "ai")

#: Tayyor shablonlar (egasi baribir har birini alohida belgilay oladi). `full` — hamma ruxsat (standart).
PRESETS = {
    "full": PERMS,
    "editor": ("create", "edit", "reschedule", "delete", "ai"),
    "scheduler": ("create", "reschedule"),
    "analyst": ("analytics",),
}

#: Eski (``perms`` ustuni NULL) a'zolar uchun: rol -> shablon.
_LEGACY_ROLE_PERMS = {"editor": PRESETS["editor"], "scheduler": PRESETS["scheduler"], "analyst": PRESETS["analyst"]}


def normalize_perms(value) -> list | None:
    """Ruxsatlar ro'yxati (yoki shablon nomi / vergulli matn) -> tartiblangan noyob ro'yxat. Noma'lum kalit bo'lsa ``None``."""
    if value is None:
        return list(PRESETS["full"])
    if isinstance(value, str):
        value = PRESETS.get(value) or [x for x in value.split(",") if x.strip()]
    try:
        items = [str(x).strip() for x in value]
    except TypeError:
        return None
    if any(x not in PERMS for x in items):
        return None
    return [p for p in PERMS if p in set(items)]


def role_for_perms(perms) -> str:
    """Ruxsatlardan eski ``channel_members.role`` belgisi (RBAC bilan moslik uchun)."""
    perms = set(perms or ())
    if "edit" in perms:
        return "editor"
    if perms & {"create", "reschedule", "delete", "send_now"}:
        return "scheduler"
    return "analyst"


def effective_perms(perms_value, role) -> list:
    """Saqlangan ``perms`` (bo'lsa) yoki eski rolning shabloni."""
    if perms_value is not None:
        got = normalize_perms(perms_value)
        if got is not None:
            return got
    return list(_LEGACY_ROLE_PERMS.get(role, ()))


def can(perms, action: str) -> bool:
    """Ish joyida amalga ruxsat: ``view`` har doim; qolganlari ruxsatlar ro'yxatida bo'lishi shart."""
    return action == "view" or action in set(perms or ())


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _owner_plan(cur, owner_id: int) -> str:
    from repositories.users_repository import _effective_plan

    cur.execute("SELECT plan_type FROM users WHERE user_id = %s", (owner_id,))
    row = cur.fetchone()
    if not row:
        return "free"
    return _effective_plan(cur, row[0] or "free", owner_id)


def _seat_limit(cur, owner_id: int) -> int:
    plan = _owner_plan(cur, owner_id)
    return int((TIER_LIMITS.get(plan) or {}).get("team_seats", 0) or 0)


def _helpers(cur, owner_id: int) -> list[int]:
    """Egasining kanallaridagi noyob yordamchilar, qo'shilgan tartibda (eng eskisi birinchi)."""
    cur.execute(
        "SELECT cm.user_id FROM channel_members cm JOIN channels c ON c.channel_id = cm.channel_id "
        "WHERE c.user_id = %s AND c.is_active = TRUE AND c.deleted_at IS NULL AND cm.user_id <> %s "
        "GROUP BY cm.user_id ORDER BY MIN(cm.created_at), cm.user_id",
        (owner_id, owner_id),
    )
    return [int(r[0]) for r in cur.fetchall()]


def _pending(cur, owner_id: int) -> int:
    cur.execute("SELECT COUNT(*) FROM team_invites WHERE owner_id = %s AND used_at IS NULL "
                "AND revoked_at IS NULL AND expires_at > NOW()", (owner_id,))
    return int(cur.fetchone()[0])


def seat_status(owner_id: int) -> dict:
    """``{plan, limit, used, pending, free}`` — egasi uchun o'rindiqlar holati."""
    with db_cursor() as cur:
        limit = _seat_limit(cur, owner_id)
        used = len(_helpers(cur, owner_id))
        pending = _pending(cur, owner_id)
        plan = _owner_plan(cur, owner_id)
    return {"plan": plan, "limit": limit, "used": used, "pending": pending, "free": max(0, limit - used - pending)}


def _as_channel_list(channel_ids) -> list:
    if isinstance(channel_ids, (str, int)):
        channel_ids = [channel_ids]
    out = []
    for c in channel_ids or ():
        c = str(c).strip()
        if c and c not in out:
            out.append(c)
    return out


def create_invite(owner_id: int, channel_ids, perms=None) -> dict:
    """Taklif yaratadi (bir yoki bir nechta kanal, bitta ruxsatlar to'plami; standart — hammasi).

    ``perms``: ruxsatlar ro'yxati yoki shablon nomi (``full|editor|scheduler|analyst``); ``None`` = ``full``.
    Natija: ``{"ok": True, "token", "id", "expires_at"}`` yoki ``{"ok": False, "error": kod}``.
    Xato kodlari: ``bad_role`` (noto'g'ri ruxsat/shablon), ``not_owner`` (kanal egasiniki emas), ``no_team`` (tarif jamoani bermaydi),
    ``seats_full`` (bo'sh o'rindiq yo'q), ``too_many_pending``.
    """
    chans = _as_channel_list(channel_ids)
    got = normalize_perms(perms)
    if got is None:
        return {"ok": False, "error": "bad_role"}
    if not chans or len(chans) > MAX_INVITE_CHANNELS:
        return {"ok": False, "error": "not_owner"}
    token = secrets.token_urlsafe(16)
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT channel_id FROM channels WHERE user_id = %s AND channel_id = ANY(%s) AND is_active = TRUE "
                        "AND deleted_at IS NULL", (owner_id, chans))
            if {str(r[0]) for r in cur.fetchall()} != set(chans):
                return {"ok": False, "error": "not_owner"}
            limit = _seat_limit(cur, owner_id)
            if limit <= 0:
                return {"ok": False, "error": "no_team"}
            pending = _pending(cur, owner_id)
            if pending >= MAX_PENDING_INVITES:
                return {"ok": False, "error": "too_many_pending"}
            if len(_helpers(cur, owner_id)) + pending >= limit:
                return {"ok": False, "error": "seats_full"}
            cur.execute(
                "INSERT INTO team_invites (token_hash, owner_id, channel_id, role, perms, channel_ids, expires_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, NOW() + (%s || ' days')::interval) RETURNING id, expires_at",
                (_hash(token), owner_id, chans[0], role_for_perms(got), ",".join(got), ",".join(chans), str(INVITE_TTL_DAYS)),
            )
            row = cur.fetchone()
        return {"ok": True, "token": token, "id": int(row[0]), "expires_at": row[1]}
    except Exception as exc:  # noqa: BLE001
        logger.error("team create_invite xatosi: %s", type(exc).__name__)
        return {"ok": False, "error": "failed"}


def search_people(owner_id: int, query: str, limit: int = 6) -> list[dict]:
    """Botdan foydalanuvchini @username (prefiks, kamida 3 belgi) yoki Telegram ID (aniq) bo'yicha topadi.

    Faqat botni ishga tushirganlar topiladi (ularga xabar yuborish mumkin). Egasining o'zi chiqmaydi.
    Natija: ``[{user_id, name, username, member}]`` (``member`` — allaqachon shu eganing yordamchisi).
    """
    q = (query or "").strip().lstrip("@").strip()
    if not q or len(q) > 64:
        return []
    with db_cursor() as cur:
        if q.isdigit():
            if len(q) < 5 or len(q) > 15:
                return []
            cur.execute("SELECT user_id, full_name, username FROM users WHERE user_id = %s AND user_id <> %s", (int(q), owner_id))
        else:
            if len(q) < MIN_SEARCH_CHARS:
                return []
            like = q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            cur.execute("SELECT user_id, full_name, username FROM users WHERE LOWER(username) LIKE %s AND user_id <> %s "
                        "ORDER BY LOWER(username) LIMIT %s", (like, owner_id, int(limit)))
        rows = cur.fetchall()
        helpers = set(_helpers(cur, owner_id))
    return [{"user_id": int(r[0]), "name": r[1] or "", "username": r[2] or "", "member": int(r[0]) in helpers} for r in rows]


def add_helper(owner_id: int, member_id: int, channel_ids, perms) -> dict:
    """Foydalanuvchini to'g'ridan-to'g'ri yordamchi qiladi (qidiruv/kontakt orqali tanlangan odam).

    Taklif havolasidan farqi: odam allaqachon botda; unga xabar boradi va u istalgan vaqt chiqib keta oladi.
    Natija ``{"ok": True, channel_ids, perms, name}`` yoki ``{"ok": False, "error"}``: ``bad_role``, ``not_owner``, ``self``,
    ``user_unknown`` (botni ishga tushirmagan), ``no_team``, ``seats_full``, ``too_many_pending`` (kunlik chegara).
    """
    chans = _as_channel_list(channel_ids)
    got = normalize_perms(perms)
    if got is None:
        return {"ok": False, "error": "bad_role"}
    if int(member_id) == int(owner_id):
        return {"ok": False, "error": "self"}
    if not chans or len(chans) > MAX_INVITE_CHANNELS:
        return {"ok": False, "error": "not_owner"}
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT full_name, username FROM users WHERE user_id = %s", (int(member_id),))
            who = cur.fetchone()
            if not who:
                return {"ok": False, "error": "user_unknown"}
            cur.execute("SELECT channel_id FROM channels WHERE user_id = %s AND channel_id = ANY(%s) AND is_active = TRUE "
                        "AND deleted_at IS NULL", (owner_id, chans))
            if {str(r[0]) for r in cur.fetchall()} != set(chans):
                return {"ok": False, "error": "not_owner"}
            limit = _seat_limit(cur, owner_id)
            if limit <= 0:
                return {"ok": False, "error": "no_team"}
            helpers = _helpers(cur, owner_id)
            is_new = int(member_id) not in helpers
            if is_new:
                if len(helpers) + _pending(cur, owner_id) >= limit:
                    return {"ok": False, "error": "seats_full"}
                cur.execute("SELECT COUNT(*) FROM team_invites WHERE owner_id = %s AND used_at > NOW() - INTERVAL '1 day'", (owner_id,))
                if int(cur.fetchone()[0]) >= MAX_JOINS_PER_DAY:
                    return {"ok": False, "error": "too_many_pending"}
            base_role = role_for_perms(got)
            for ch in chans:
                cur.execute("INSERT INTO channel_members (channel_id, user_id, role, perms) VALUES (%s, %s, %s, %s) "
                            "ON CONFLICT (channel_id, user_id) DO UPDATE SET role = EXCLUDED.role, perms = EXCLUDED.perms",
                            (ch, int(member_id), base_role, ",".join(got)))
            if is_new:  # kunlik chegara hisobi uchun iz (token tasodifiy, ishlatib bo'lingan)
                cur.execute("INSERT INTO team_invites (token_hash, owner_id, channel_id, role, perms, channel_ids, expires_at, used_by, used_at) "
                            "VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, NOW())",
                            (_hash(secrets.token_urlsafe(16)), owner_id, chans[0], base_role, ",".join(got), ",".join(chans), int(member_id)))
            cur.execute("UPDATE users SET work_mode = COALESCE(work_mode, 'helper') WHERE user_id = %s", (int(member_id),))
        _invalidate_user(int(member_id))
        for ch in chans:
            _drop_rbac_cache(member_id, ch)
        return {"ok": True, "channel_ids": chans, "perms": got, "name": who[0] or who[1] or "", "new": is_new}
    except Exception as exc:  # noqa: BLE001
        logger.error("team add_helper xatosi: %s", type(exc).__name__)
        return {"ok": False, "error": "failed"}


def accept_invite(token: str, user_id: int) -> dict:
    """Taklifni qabul qiladi (atomik). ``{"ok": True, owner_id, channel_id, channel_ids, role, perms, title}`` yoki ``{"ok": False, "error"}``.

    Xato kodlari: ``invalid``, ``used``, ``expired``, ``revoked``, ``self`` (egasi o'zini taklif qila olmaydi),
    ``no_team`` (egasi tarifi endi jamoani bermaydi), ``seats_full``.
    """
    token = (token or "").strip()
    if not 8 <= len(token) <= 64:
        return {"ok": False, "error": "invalid"}
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT id, owner_id, channel_id, role, expires_at <= NOW(), used_at, revoked_at, perms, channel_ids "
                        "FROM team_invites WHERE token_hash = %s FOR UPDATE", (_hash(token),))
            inv = cur.fetchone()
            if not inv:
                return {"ok": False, "error": "invalid"}
            inv_id, owner_id, channel_id, role, expired, used_at, revoked_at, perms_value, ids_value = inv
            if revoked_at is not None:
                return {"ok": False, "error": "revoked"}
            if used_at is not None:
                return {"ok": False, "error": "used"}
            if expired:
                return {"ok": False, "error": "expired"}
            if int(owner_id) == int(user_id):
                return {"ok": False, "error": "self"}
            chans = _as_channel_list((ids_value or "").split(",")) or [str(channel_id)]
            cur.execute("SELECT channel_id, channel_title FROM channels WHERE user_id = %s AND channel_id = ANY(%s) AND is_active = TRUE "
                        "AND deleted_at IS NULL", (owner_id, chans))
            live = {str(r[0]): r[1] or "" for r in cur.fetchall()}
            chans = [c for c in chans if c in live]
            if not chans:
                return {"ok": False, "error": "invalid"}
            limit = _seat_limit(cur, owner_id)
            if limit <= 0:
                return {"ok": False, "error": "no_team"}
            helpers = _helpers(cur, owner_id)
            if int(user_id) not in helpers and len(helpers) >= limit:
                return {"ok": False, "error": "seats_full"}
            perms = effective_perms(perms_value, role)
            base_role = role_for_perms(perms)
            for ch in chans:
                cur.execute(
                    "INSERT INTO channel_members (channel_id, user_id, role, perms) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (channel_id, user_id) DO UPDATE SET role = EXCLUDED.role, perms = EXCLUDED.perms",
                    (ch, int(user_id), base_role, ",".join(perms)),
                )
            cur.execute("UPDATE team_invites SET used_by = %s, used_at = NOW() WHERE id = %s", (int(user_id), inv_id))
            cur.execute("UPDATE users SET work_mode = COALESCE(work_mode, 'helper') WHERE user_id = %s", (int(user_id),))
        _invalidate_user(int(user_id))
        for ch in chans:
            _drop_rbac_cache(user_id, ch)
        title = live[chans[0]] + (f" +{len(chans) - 1}" if len(chans) > 1 else "")
        return {"ok": True, "owner_id": int(owner_id), "channel_id": chans[0], "channel_ids": chans, "role": base_role,
                "perms": perms, "title": title}
    except Exception as exc:  # noqa: BLE001
        logger.error("team accept_invite xatosi: %s", type(exc).__name__)
        return {"ok": False, "error": "failed"}


def _drop_rbac_cache(user_id, channel_id) -> None:
    try:
        from repositories.teams_repository import _invalidate_rbac_resource_cache

        _invalidate_rbac_resource_cache(user_id, str(channel_id))
    except Exception:  # noqa: BLE001
        logger.debug("rbac kesh bekor qilinmadi", exc_info=True)


def revoke_invite(owner_id: int, invite_id: int) -> bool:
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE team_invites SET revoked_at = NOW() WHERE id = %s AND owner_id = %s "
                    "AND used_at IS NULL AND revoked_at IS NULL", (int(invite_id), owner_id))
        return cur.rowcount > 0


def remove_member(owner_id: int, channel_id: str, member_id: int) -> bool:
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM channel_members cm USING channels c WHERE cm.channel_id = c.channel_id "
                    "AND c.user_id = %s AND cm.channel_id = %s AND cm.user_id = %s", (owner_id, str(channel_id), int(member_id)))
        ok = cur.rowcount > 0
    if ok:
        _drop_rbac_cache(member_id, channel_id)
    return ok


def set_member_role(owner_id: int, channel_id: str, member_id: int, role: str) -> bool:
    """Eski usul: rol shablonini qo'llaydi (``editor|scheduler|analyst``)."""
    if role not in ROLES:
        return False
    return set_member_perms(owner_id, channel_id, member_id, list(PRESETS[role]))


def set_member_perms(owner_id: int, channel_id: str, member_id: int, perms) -> bool:
    """Bitta kanaldagi a'zoning ruxsatlarini o'zgartiradi (bo'sh ro'yxat = faqat ko'rish)."""
    got = normalize_perms(perms if perms is not None else [])
    if got is None:
        return False
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE channel_members cm SET role = %s, perms = %s FROM channels c WHERE cm.channel_id = c.channel_id "
                    "AND c.user_id = %s AND cm.channel_id = %s AND cm.user_id = %s",
                    (role_for_perms(got), ",".join(got), owner_id, str(channel_id), int(member_id)))
        ok = cur.rowcount > 0
    if ok:
        _drop_rbac_cache(member_id, channel_id)
    return ok


def set_helper(owner_id: int, member_id: int, channel_ids, perms) -> bool:
    """Yordamchini MARKAZ qilib sozlash: u ishlaydigan kanallar to'plami va ruxsatlari (hammasiga bir xil).

    Yangi kanal qo'shiladi, ro'yxatda yo'qlari olib tashlanadi. O'rindiq o'zgarmaydi (yordamchi allaqachon a'zo).
    Yordamchi bo'lmagan odamni bu usul bilan qo'shib bo'lmaydi (faqat taklif orqali).
    """
    chans = _as_channel_list(channel_ids)
    got = normalize_perms(perms if perms is not None else [])
    if got is None:
        return False
    with db_cursor(commit=True) as cur:
        if int(member_id) not in _helpers(cur, owner_id):
            return False
        cur.execute("SELECT channel_id FROM channels WHERE user_id = %s AND is_active = TRUE AND deleted_at IS NULL", (owner_id,))
        owned = {str(r[0]) for r in cur.fetchall()}
        if not set(chans) <= owned:
            return False
        cur.execute("SELECT cm.channel_id FROM channel_members cm JOIN channels c ON c.channel_id = cm.channel_id "
                    "WHERE c.user_id = %s AND cm.user_id = %s", (owner_id, int(member_id)))
        had = {str(r[0]) for r in cur.fetchall()}
        for ch in chans:
            cur.execute("INSERT INTO channel_members (channel_id, user_id, role, perms) VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (channel_id, user_id) DO UPDATE SET role = EXCLUDED.role, perms = EXCLUDED.perms",
                        (ch, int(member_id), role_for_perms(got), ",".join(got)))
        for ch in had - set(chans):
            cur.execute("DELETE FROM channel_members WHERE channel_id = %s AND user_id = %s", (ch, int(member_id)))
    for ch in had | set(chans):
        _drop_rbac_cache(member_id, ch)
    return True


def leave(user_id: int, owner_id: int) -> int:
    """Yordamchi egasining ish joyidan chiqadi (hamma kanaldagi rolini qaytaradi). O'chirilgan qatorlar soni."""
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT cm.channel_id FROM channel_members cm JOIN channels c ON c.channel_id = cm.channel_id "
                    "WHERE c.user_id = %s AND cm.user_id = %s", (owner_id, int(user_id)))
        chans = [r[0] for r in cur.fetchall()]
        cur.execute("DELETE FROM channel_members cm USING channels c WHERE cm.channel_id = c.channel_id "
                    "AND c.user_id = %s AND cm.user_id = %s", (owner_id, int(user_id)))
        n = cur.rowcount
    for ch in chans:
        _drop_rbac_cache(user_id, ch)
    return int(n)


def list_team(owner_id: int) -> dict:
    """Egasi uchun: o'rindiqlar + har kanal bo'yicha a'zolar (ruxsatlari bilan) va kutilayotgan takliflar."""
    seats = seat_status(owner_id)
    with db_cursor() as cur:
        cur.execute("SELECT channel_id, channel_title FROM channels WHERE user_id = %s AND is_active = TRUE "
                    "AND deleted_at IS NULL ORDER BY id", (owner_id,))
        chans = cur.fetchall()
        cur.execute("SELECT cm.channel_id, cm.user_id, cm.role, cm.created_at, u.full_name, u.username, cm.perms "
                    "FROM channel_members cm JOIN channels c ON c.channel_id = cm.channel_id "
                    "LEFT JOIN users u ON u.user_id = cm.user_id "
                    "WHERE c.user_id = %s AND cm.user_id <> %s ORDER BY cm.created_at", (owner_id, owner_id))
        members = cur.fetchall()
        active = set(_helpers(cur, owner_id)[: seats["limit"]])
        cur.execute("SELECT id, channel_id, role, expires_at, perms, channel_ids FROM team_invites WHERE owner_id = %s AND used_at IS NULL "
                    "AND revoked_at IS NULL AND expires_at > NOW() ORDER BY id", (owner_id,))
        invites = cur.fetchall()
    out = []
    for ch_id, title in chans:
        out.append({
            "channel_id": str(ch_id), "title": title or "",
            "members": [{"user_id": int(m[1]), "role": m[2], "perms": effective_perms(m[6], m[2]), "name": m[4] or "", "username": m[5] or "",
                         "active": int(m[1]) in active, "since": m[3]} for m in members if str(m[0]) == str(ch_id)],
            "invites": [{"id": int(i[0]), "role": i[2], "perms": effective_perms(i[4], i[2]), "expires_at": i[3]}
                        for i in invites if str(ch_id) in (_as_channel_list((i[5] or "").split(",")) or [str(i[1])])],
        })
    return {"seats": seats, "channels": out}


def workspace_access(user_id: int, owner_id: int) -> dict:
    """Yordamchining egasi ish joyidagi kanallari: ``{channel_id: {"role", "perms": [...]}}``. Ruxsat yo'q bo'lsa ``{}``.

    Ruxsat: yordamchi egasining ENG ESKI ``team_seats`` tasidan biri bo'lishi shart (egasi tarifi tushsa — yopiladi).
    """
    with db_cursor() as cur:
        limit = _seat_limit(cur, owner_id)
        if limit <= 0 or int(user_id) not in _helpers(cur, owner_id)[:limit]:
            return {}
        cur.execute("SELECT cm.channel_id, cm.role, cm.perms FROM channel_members cm JOIN channels c ON c.channel_id = cm.channel_id "
                    "WHERE c.user_id = %s AND cm.user_id = %s AND c.is_active = TRUE AND c.deleted_at IS NULL "
                    "AND cm.role IN ('editor', 'scheduler', 'analyst')", (owner_id, int(user_id)))
        return {str(r[0]): {"role": r[1], "perms": effective_perms(r[2], r[1])} for r in cur.fetchall()}


def workspaces_for(user_id: int) -> list[dict]:
    """Foydalanuvchi yordamchi bo'lgan ish joylari (faol o'rindiq bilan): egasi + kanallar/ruxsatlar."""
    with db_cursor() as cur:
        cur.execute("SELECT DISTINCT c.user_id FROM channel_members cm JOIN channels c ON c.channel_id = cm.channel_id "
                    "WHERE cm.user_id = %s AND c.user_id <> %s AND c.is_active = TRUE AND c.deleted_at IS NULL",
                    (int(user_id), int(user_id)))
        owners = [int(r[0]) for r in cur.fetchall()]
    out = []
    for owner in owners:
        access = workspace_access(user_id, owner)
        with db_cursor() as cur:
            cur.execute("SELECT full_name, username FROM users WHERE user_id = %s", (owner,))
            row = cur.fetchone() or ("", "")
            cur.execute("SELECT channel_id, channel_title FROM channels WHERE user_id = %s", (owner,))
            titles = {str(r[0]): r[1] or "" for r in cur.fetchall()}
        out.append({"owner_id": owner, "owner_name": row[0] or row[1] or "", "suspended": not access,
                    "channels": [{"channel_id": ch, "title": titles.get(ch, ""), "role": a["role"], "perms": a["perms"]}
                                 for ch, a in access.items()]})
    return out


def get_mode(user_id: int) -> str | None:
    with db_cursor() as cur:
        cur.execute("SELECT work_mode FROM users WHERE user_id = %s", (int(user_id),))
        row = cur.fetchone()
    return row[0] if row and row[0] in MODES else None


def set_mode(user_id: int, mode: str) -> bool:
    if mode not in MODES:
        return False
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE users SET work_mode = %s WHERE user_id = %s", (mode, int(user_id)))
        ok = cur.rowcount > 0
    if ok:
        _invalidate_user(int(user_id))
    return ok
