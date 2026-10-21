"""💰 Reklama birjasi (PostgreSQL): kanal e'loni, so'rovlar, bot orqali yozishma, shikoyat va blok.

Qoidalar (hammasi shu qatlamda, handler faqat natijani ko'rsatadi):
  * e'lon egasi FAQAT ``channels.user_id`` bo'lgan foydalanuvchi (IDOR: har yozuvchi funksiya ``owner_id`` ni tekshiradi);
  * katalogda faqat faol e'lon + faol kanal + e'lon egasi hali kanal egasi ko'rinadi;
  * so'rov yaratish atomik (advisory-lock): kunlik limit, bitta ochiq so'rov, blok, o'z kanaliga yozmaslik;
  * yozishma faqat ikki ishtirokchi o'rtasida, xabar soni cheklangan;
  * ``REPORT_BLOCK_THRESHOLD`` ta turli foydalanuvchi shikoyat qilsa e'lon avtomatik ``blocked`` bo'ladi.
"""
from __future__ import annotations

from database import db_cursor

# Boshqa advisory-lock'lar (7_1xx...) bilan to'qnashmaslik uchun alohida siljish (bigint ichida).
_LOCK_BASE = 7_200_000_000_000_000_000

INQUIRIES_PER_DAY = 5
MAX_MESSAGES_PER_INQUIRY = 40
REPORT_BLOCK_THRESHOLD = 3
MAX_LISTINGS_PER_USER = 5
PAGE_SIZE = 5
INBOUND_PER_DAY = 30       # egasiga kuniga ko'pi bilan shuncha YANGI so'rov (spamdan himoya)
DUPLICATE_LIMIT = 2        # 24 soatda bir xil matn ko'pi bilan shuncha marta
USER_BAN_THRESHOLD = 3     # turli foydalanuvchilarning shuncha shikoyati -> global ban

STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
STATUS_BLOCKED = "blocked"

_LISTING_COLS = (
    "l.id, l.channel_id, l.owner_id, l.username, l.title, l.category, l.price_post, l.description, l.status, "
    "l.members, l.avg_views, l.er_percent, l.growth_30d, l.posts_30d, l.stats_updated_at, "
    "l.view_count, l.inquiry_count, l.created_at, l.country, l.price_currency"
)
_LISTING_KEYS = (
    "id", "channel_id", "owner_id", "username", "title", "category", "price_post", "description", "status",
    "members", "avg_views", "er_percent", "growth_30d", "posts_30d", "stats_updated_at",
    "view_count", "inquiry_count", "created_at", "country", "price_currency",
)

#: ``update_listing_fields`` faqat shu ustunlarni o'zgartiradi.
_EDITABLE = {"category", "price_post", "description"}

_LIVE_JOIN = (
    "JOIN channels c ON c.channel_id = l.channel_id AND c.user_id = l.owner_id "
    "AND c.is_active = TRUE AND c.deleted_at IS NULL"
)


def _listing(row) -> dict | None:
    if not row:
        return None
    data = dict(zip(_LISTING_KEYS, row))
    if data.get("er_percent") is not None:
        data["er_percent"] = float(data["er_percent"])
    return data


# ---------------------------------------------------------------- egasi: kanal va e'lon

def get_owned_channel(user_id: int, channel_id) -> dict | None:
    """Foydalanuvchining faol kanali (egalik tekshiruvi). Boshqa odam kanali -> ``None``."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT channel_id, channel_title FROM channels "
            "WHERE user_id = %s AND channel_id = %s AND is_active = TRUE AND deleted_at IS NULL",
            (int(user_id), str(channel_id)),
        )
        row = cur.fetchone()
    return {"channel_id": row[0], "title": row[1]} if row else None


def list_owner_channels(user_id: int) -> list[dict]:
    """Foydalanuvchining faol kanallari + e'lon holati (bo'lsa)."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT c.channel_id, c.channel_title, l.id, l.status FROM channels c "
            "LEFT JOIN ad_market_listings l ON l.channel_id = c.channel_id AND l.owner_id = c.user_id "
            "WHERE c.user_id = %s AND c.is_active = TRUE AND c.deleted_at IS NULL ORDER BY c.id",
            (int(user_id),),
        )
        return [{"channel_id": r[0], "title": r[1], "listing_id": r[2], "status": r[3]} for r in cur.fetchall()]


def count_owner_listings(user_id: int) -> int:
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM ad_market_listings WHERE owner_id = %s", (int(user_id),))
        return int(cur.fetchone()[0])


def get_listing(listing_id: int) -> dict | None:
    with db_cursor() as cur:
        cur.execute(f"SELECT {_LISTING_COLS} FROM ad_market_listings l WHERE l.id = %s", (int(listing_id),))  # nosec B608 — faqat modul konstantalari/oq ro'yxat; qiymatlar %s bilan
        return _listing(cur.fetchone())


def get_listing_for_owner(listing_id: int, owner_id: int) -> dict | None:
    with db_cursor() as cur:
        cur.execute(
            f"SELECT {_LISTING_COLS} FROM ad_market_listings l WHERE l.id = %s AND l.owner_id = %s",  # nosec B608 — faqat modul konstantalari/oq ro'yxat; qiymatlar %s bilan
            (int(listing_id), int(owner_id)),
        )
        return _listing(cur.fetchone())


def get_viewer_country(user_id: int) -> str:
    """Foydalanuvchining telefon bilan tasdiqlangan mamlakati (ISO-2) yoki ``''``."""
    with db_cursor() as cur:
        cur.execute("SELECT COALESCE(phone_country, '') FROM users WHERE user_id = %s", (int(user_id),))
        row = cur.fetchone()
    return (row[0] if row else "") or ""


def create_listing(owner_id: int, channel_id, username: str, title: str, category: str,
                   price_post: int | None, description: str | None, country: str | None = None,
                   price_currency: str = "UZS") -> dict:
    """E'lon yaratadi (kanal egaligi tekshiriladi). ``{"ok", "reason", "listing_id"}``.

    ``reason``: ``not_owner`` | ``exists`` | ``limit``.
    """
    uid = int(owner_id)
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_BASE + uid,))
        cur.execute("SELECT 1 FROM ad_market_bans WHERE user_id = %s", (uid,))
        if cur.fetchone() is not None:
            return {"ok": False, "reason": "banned", "listing_id": None}
        cur.execute(
            "SELECT 1 FROM channels WHERE user_id = %s AND channel_id = %s AND is_active = TRUE AND deleted_at IS NULL",
            (uid, str(channel_id)),
        )
        if cur.fetchone() is None:
            return {"ok": False, "reason": "not_owner", "listing_id": None}
        cur.execute("SELECT id, owner_id FROM ad_market_listings WHERE channel_id = %s", (str(channel_id),))
        old = cur.fetchone()
        if old is not None:
            if int(old[1]) != uid:
                # Kanal egasi o'zgargan: eski egasining e'loni o'chiriladi (yangi egasi qayta yaratadi).
                cur.execute("DELETE FROM ad_market_listings WHERE id = %s", (old[0],))
            else:
                return {"ok": False, "reason": "exists", "listing_id": int(old[0])}
        cur.execute("SELECT COUNT(*) FROM ad_market_listings WHERE owner_id = %s", (uid,))
        if int(cur.fetchone()[0]) >= MAX_LISTINGS_PER_USER:
            return {"ok": False, "reason": "limit", "listing_id": None}
        cur.execute(
            "INSERT INTO ad_market_listings (channel_id, owner_id, username, title, category, price_post, description, "
            "country, price_currency) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (str(channel_id), uid, username, (title or "")[:255], category, price_post, description,
             (country or None), "USD" if price_currency == "USD" else "UZS"),
        )
        return {"ok": True, "reason": None, "listing_id": int(cur.fetchone()[0])}


def update_listing_fields(listing_id: int, owner_id: int, **fields) -> bool:
    """Faqat egasi, faqat ruxsat etilgan ustunlar (``category``, ``price_post``, ``description``)."""
    items = [(k, v) for k, v in fields.items() if k in _EDITABLE]
    if not items:
        return False
    sets = ", ".join(f"{k} = %s" for k, _ in items)
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE ad_market_listings SET {sets}, updated_at = NOW() WHERE id = %s AND owner_id = %s",  # nosec B608 — faqat modul konstantalari/oq ro'yxat; qiymatlar %s bilan
            [v for _, v in items] + [int(listing_id), int(owner_id)],
        )
        return bool(cur.rowcount)


def set_listing_status(listing_id: int, owner_id: int, status: str) -> bool:
    """Egasi e'lonni to'xtatadi/faollashtiradi. Bloklangan (shikoyat) e'lonni egasi o'zi faollashtira olmaydi."""
    if status not in (STATUS_ACTIVE, STATUS_PAUSED):
        return False
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE ad_market_listings SET status = %s, updated_at = NOW() "
            "WHERE id = %s AND owner_id = %s AND status <> %s",
            (status, int(listing_id), int(owner_id), STATUS_BLOCKED),
        )
        return bool(cur.rowcount)


def admin_set_listing_status(listing_id: int, status: str) -> bool:
    """Admin: e'lonni qo'lda bloklash/qayta faollashtirish (shikoyatlar tozalanadi)."""
    if status not in (STATUS_ACTIVE, STATUS_PAUSED, STATUS_BLOCKED):
        return False
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE ad_market_listings SET status = %s, updated_at = NOW() WHERE id = %s",
            (status, int(listing_id)),
        )
        changed = bool(cur.rowcount)
        if changed and status == STATUS_ACTIVE:
            cur.execute("DELETE FROM ad_market_reports WHERE listing_id = %s", (int(listing_id),))
        return changed


def delete_listing(listing_id: int, owner_id: int) -> bool:
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM ad_market_listings WHERE id = %s AND owner_id = %s", (int(listing_id), int(owner_id)))
        return bool(cur.rowcount)


def save_listing_stats(listing_id: int, stats: dict) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE ad_market_listings SET members = %s, avg_views = %s, er_percent = %s, growth_30d = %s, "
            "posts_30d = %s, stats_updated_at = NOW() WHERE id = %s",
            (stats.get("members"), stats.get("avg_views"), stats.get("er_percent"), stats.get("growth_30d"),
             stats.get("posts_30d"), int(listing_id)),
        )


def get_recent_views(channel_id, limit: int = 10, days: int = 60) -> list[int]:
    """So'nggi postlarning HAQIQIY (NULL emas) ko'rishlari."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT views FROM channel_posts_history WHERE channel_id = %s AND views IS NOT NULL "
            "AND post_date > NOW() - (%s || ' days')::INTERVAL ORDER BY post_date DESC LIMIT %s",
            (str(channel_id), str(int(days)), int(limit)),
        )
        return [int(r[0]) for r in cur.fetchall()]


def count_recent_posts(channel_id, days: int = 30) -> int:
    with db_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM channel_posts_history WHERE channel_id = %s "
            "AND post_date > NOW() - (%s || ' days')::INTERVAL",
            (str(channel_id), str(int(days))),
        )
        return int(cur.fetchone()[0])


# ---------------------------------------------------------------- katalog

_SORTS = {
    "m": "l.members DESC NULLS LAST, l.id DESC",
    "p": "l.price_post ASC NULLS LAST, l.members DESC NULLS LAST",
    "e": "l.er_percent DESC NULLS LAST, l.members DESC NULLS LAST",
}


#: «Tavsiya» tartibi (0..1): ER 50% (30% da to'yinadi) + obunachi 30% (logarifmik, 1M da to'yinadi) + o'sish 20% (30 kunda +10% da to'yinadi);
#: ko'rsatkichi hali yo'q kanal ×0,5 (noma'lum — pastroq), ma'lumoti 7 kundan eski ×0,85. Soxta ER/kichik kanal tepaga chiqmaydi.
_QUALITY = (
    "((0.5 * LEAST(COALESCE(l.er_percent, 0), 30) / 30.0 "
    "+ 0.3 * LEAST(LN(COALESCE(l.members, 0) + 1) / LN(1000000.0), 1) "
    "+ 0.2 * LEAST(GREATEST(COALESCE(l.growth_30d, 0), 0)::float / GREATEST(COALESCE(l.members, 1), 1) * 10, 1)) "
    "* CASE WHEN l.avg_views IS NULL THEN 0.5 ELSE 1 END "
    "* CASE WHEN l.stats_updated_at IS NULL OR l.stats_updated_at < NOW() - INTERVAL '7 days' THEN 0.85 ELSE 1 END)"
)


def list_catalog(category: str | None = None, sort: str = "m", page: int = 0, page_size: int = PAGE_SIZE,
                 country: str | None = None, viewer: str | None = None) -> dict:
    """Faol e'lonlar sahifasi: ``{"items": [...], "total": n}``. ``country`` (ISO-2) berilsa — shu mamlakat va global («ZZ») e'lonlari.

    ``sort="r"`` (tavsiya): avval hudud yaqinligi, keyin sifat ballı (``_QUALITY``). ``viewer`` — ko'ruvchi mamlakati:
    «o'z mamlakati» ko'rinishida o'z davlat kanallari global'dan OLDIN; «hammasi» ko'rinishida YAQIN davlatlar, keyin global,
    keyin boshqa davlatlar, o'z mamlakati kanallari ENG PASTDA (ularni ko'ruvchi «mahalliy» ro'yxatda ko'radi).
    """
    where = ["l.status = 'active'"]
    params: list = []
    if category and category != "all":
        where.append("l.category = %s")
        params.append(category)
    if country:  # o'z mamlakati + global («ZZ») e'lonlar hamma uchun ko'rinadi
        where.append("(l.country = %s OR l.country = 'ZZ')")
        params.append(str(country).upper()[:2])
    order_params: list = []
    if sort == "r":
        v = str(viewer or country or "").upper()[:2]
        if country:
            prox = "CASE WHEN l.country = %s THEN 0 ELSE 1 END"
            order_params = [str(country).upper()[:2]]
        elif v and v != "ZZ":
            from services.channel_region import near_countries

            prox = "CASE WHEN l.country = %s THEN 3 WHEN l.country = ANY(%s) THEN 0 WHEN l.country = 'ZZ' THEN 1 ELSE 2 END"
            order_params = [v, near_countries(v)]
        else:
            prox = "0::int"
        order = f"{prox}, {_QUALITY} DESC, l.members DESC NULLS LAST, l.id DESC"
    else:
        order = _SORTS.get(sort, _SORTS["m"])
    size = max(1, min(int(page_size), 20))
    offset = max(0, int(page)) * size
    with db_cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM ad_market_listings l {_LIVE_JOIN} WHERE {' AND '.join(where)}", params  # nosec B608 — faqat modul konstantalari/oq ro'yxat; qiymatlar %s bilan
        )
        total = int(cur.fetchone()[0])
        cur.execute(
            f"SELECT {_LISTING_COLS} FROM ad_market_listings l {_LIVE_JOIN} "  # nosec B608 — faqat modul konstantalari/oq ro'yxat; qiymatlar %s bilan
            f"WHERE {' AND '.join(where)} ORDER BY {order} LIMIT %s OFFSET %s",
            params + order_params + [size, offset],
        )
        items = [_listing(r) for r in cur.fetchall()]
    return {"items": items, "total": total}


def get_public_listing(listing_id: int, viewer_id: int | None = None) -> dict | None:
    """Reklama beruvchiga ko'rinadigan e'lon (faol + kanal tirik); ko'rishlar hisoblagichi +1 (egasi o'zini ko'rsa — yo'q)."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"SELECT {_LISTING_COLS} FROM ad_market_listings l {_LIVE_JOIN} WHERE l.id = %s AND l.status = 'active'",  # nosec B608 — faqat modul konstantalari/oq ro'yxat; qiymatlar %s bilan
            (int(listing_id),),
        )
        data = _listing(cur.fetchone())
        if data and (viewer_id is None or int(viewer_id) != data["owner_id"]):
            cur.execute("UPDATE ad_market_listings SET view_count = view_count + 1 WHERE id = %s", (data["id"],))
        return data


def market_totals() -> dict:
    """Bosh ekran uchun: katalogdagi faol e'lonlar va barcha so'rovlar soni."""
    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM ad_market_listings l {_LIVE_JOIN} WHERE l.status = 'active'")  # nosec B608 — faqat modul konstantalari/oq ro'yxat; qiymatlar %s bilan
        listings = int(cur.fetchone()[0])
        cur.execute("SELECT COALESCE(SUM(inquiry_count), 0) FROM ad_market_listings")
        inquiries = int(cur.fetchone()[0])
    return {"listings": listings, "inquiries": inquiries}


# ---------------------------------------------------------------- so'rovlar va yozishma

def is_blocked(owner_id: int, user_id: int) -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM ad_market_blocks WHERE owner_id = %s AND blocked_id = %s", (int(owner_id), int(user_id)))
        return cur.fetchone() is not None


def _dup_count(cur, user_id: int, body: str) -> int:
    """Shu foydalanuvchining oxirgi 24 soatda AYNAN shu matnni necha marta yuborgani (spam)."""
    cur.execute(
        "SELECT COUNT(*) FROM ad_market_messages WHERE sender_id = %s AND body = %s AND created_at > NOW() - INTERVAL '24 hours'",
        (int(user_id), body),
    )
    return int(cur.fetchone()[0])


def create_inquiry(listing_id: int, advertiser_id: int, body: str, flags: str = "") -> dict:
    """Reklama beruvchining birinchi xabari. ``{"ok", "reason", "inquiry_id", "owner_id"}``.

    ``reason``: ``not_found`` | ``own`` | ``blocked`` | ``banned`` | ``limit`` | ``busy`` | ``spam`` | ``open_exists``
    (``inquiry_id`` bilan). ``flags`` — ``services.market_safety.pack_flags`` natijasi (oluvchiga ogohlantirish).
    """
    adv = int(advertiser_id)
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_BASE + adv,))
        cur.execute("SELECT 1 FROM ad_market_bans WHERE user_id = %s", (adv,))
        if cur.fetchone() is not None:
            return {"ok": False, "reason": "banned", "inquiry_id": None, "owner_id": None}
        cur.execute(
            f"SELECT l.id, l.owner_id FROM ad_market_listings l {_LIVE_JOIN} WHERE l.id = %s AND l.status = 'active'",  # nosec B608 — faqat modul konstantalari/oq ro'yxat; qiymatlar %s bilan
            (int(listing_id),),
        )
        row = cur.fetchone()
        if row is None:
            return {"ok": False, "reason": "not_found", "inquiry_id": None, "owner_id": None}
        owner = int(row[1])
        fail = {"ok": False, "inquiry_id": None, "owner_id": owner}
        if owner == adv:
            return {**fail, "reason": "own"}
        cur.execute("SELECT 1 FROM ad_market_blocks WHERE owner_id = %s AND blocked_id = %s", (owner, adv))
        if cur.fetchone() is not None:
            return {**fail, "reason": "blocked"}
        cur.execute(
            "SELECT id FROM ad_market_inquiries WHERE listing_id = %s AND advertiser_id = %s AND status = 'open'",
            (int(listing_id), adv),
        )
        existing = cur.fetchone()
        if existing is not None:
            return {**fail, "reason": "open_exists", "inquiry_id": int(existing[0])}
        cur.execute(
            "SELECT COUNT(*) FROM ad_market_inquiries WHERE advertiser_id = %s AND created_at > NOW() - INTERVAL '24 hours'",
            (adv,),
        )
        if int(cur.fetchone()[0]) >= INQUIRIES_PER_DAY:
            return {**fail, "reason": "limit"}
        cur.execute(
            "SELECT COUNT(*) FROM ad_market_inquiries WHERE owner_id = %s AND created_at > NOW() - INTERVAL '24 hours'",
            (owner,),
        )
        if int(cur.fetchone()[0]) >= INBOUND_PER_DAY:
            return {**fail, "reason": "busy"}
        if _dup_count(cur, adv, body) >= DUPLICATE_LIMIT:
            return {**fail, "reason": "spam"}
        cur.execute(
            "INSERT INTO ad_market_inquiries (listing_id, advertiser_id, owner_id, msg_count) "
            "VALUES (%s, %s, %s, 1) RETURNING id",
            (int(listing_id), adv, owner),
        )
        inquiry_id = int(cur.fetchone()[0])
        cur.execute("INSERT INTO ad_market_messages (inquiry_id, sender_id, body, flags) VALUES (%s, %s, %s, %s)",
                    (inquiry_id, adv, body, flags))
        cur.execute("UPDATE ad_market_listings SET inquiry_count = inquiry_count + 1 WHERE id = %s", (int(listing_id),))
        return {"ok": True, "reason": None, "inquiry_id": inquiry_id, "owner_id": owner}


def get_inquiry(inquiry_id: int, user_id: int) -> dict | None:
    """So'rov (FAQAT ishtirokchi uchun): e'lon nomi va ikkinchi tomon ID si bilan."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT i.id, i.listing_id, i.advertiser_id, i.owner_id, i.status, i.msg_count, l.title, l.username "
            "FROM ad_market_inquiries i JOIN ad_market_listings l ON l.id = i.listing_id "
            "WHERE i.id = %s AND (i.advertiser_id = %s OR i.owner_id = %s)",
            (int(inquiry_id), int(user_id), int(user_id)),
        )
        r = cur.fetchone()
    if not r:
        return None
    uid = int(user_id)
    return {"id": r[0], "listing_id": r[1], "advertiser_id": int(r[2]), "owner_id": int(r[3]), "status": r[4],
            "msg_count": r[5], "title": r[6], "username": r[7],
            "role": "owner" if int(r[3]) == uid else "advertiser",
            "peer_id": int(r[2]) if int(r[3]) == uid else int(r[3])}


def add_message(inquiry_id: int, sender_id: int, body: str, flags: str = "") -> dict:
    """Ishtirokchi xabari. ``{"ok", "reason", "recipient_id"}`` (``reason``: ``not_found|closed|full|banned|spam``)."""
    info = get_inquiry(inquiry_id, sender_id)
    if info is None:
        return {"ok": False, "reason": "not_found", "recipient_id": None}
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT 1 FROM ad_market_bans WHERE user_id = %s", (int(sender_id),))
        if cur.fetchone() is not None:
            return {"ok": False, "reason": "banned", "recipient_id": None}
        if _dup_count(cur, sender_id, body) >= DUPLICATE_LIMIT:
            return {"ok": False, "reason": "spam", "recipient_id": None}
        cur.execute(
            "UPDATE ad_market_inquiries SET msg_count = msg_count + 1, updated_at = NOW() "
            "WHERE id = %s AND status = 'open' AND msg_count < %s",
            (int(inquiry_id), MAX_MESSAGES_PER_INQUIRY),
        )
        if not cur.rowcount:
            cur.execute("SELECT status FROM ad_market_inquiries WHERE id = %s", (int(inquiry_id),))
            st = cur.fetchone()
            return {"ok": False, "reason": "closed" if st and st[0] != "open" else "full", "recipient_id": None}
        cur.execute("INSERT INTO ad_market_messages (inquiry_id, sender_id, body, flags) VALUES (%s, %s, %s, %s)",
                    (int(inquiry_id), int(sender_id), body, flags))
    return {"ok": True, "reason": None, "recipient_id": info["peer_id"]}


def recent_messages(inquiry_id: int, user_id: int, limit: int = 6) -> list[dict]:
    """So'nggi xabarlar (eskidan yangiga); faqat ishtirokchi o'qiy oladi."""
    if get_inquiry(inquiry_id, user_id) is None:
        return []
    with db_cursor() as cur:
        cur.execute(
            "SELECT sender_id, body, created_at, flags FROM ad_market_messages WHERE inquiry_id = %s ORDER BY id DESC LIMIT %s",
            (int(inquiry_id), int(limit)),
        )
        rows = cur.fetchall()
    return [{"sender_id": int(r[0]), "body": r[1], "created_at": r[2], "flags": [f for f in (r[3] or "").split(",") if f]}
            for r in reversed(rows)]


def list_user_inquiries(user_id: int, limit: int = 10) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT i.id, i.status, i.owner_id, i.advertiser_id, l.title, i.updated_at, "
            "(SELECT COUNT(*) FROM ad_market_messages m WHERE m.inquiry_id = i.id AND m.sender_id <> %s AND m.created_at > "
            " CASE WHEN i.owner_id = %s THEN COALESCE(i.owner_read_at, 'epoch'::timestamptz) ELSE i.adv_read_at END) "
            "FROM ad_market_inquiries i "
            "JOIN ad_market_listings l ON l.id = i.listing_id "
            "WHERE (i.advertiser_id = %s OR i.owner_id = %s) AND i.status = 'open' "
            "ORDER BY i.updated_at DESC LIMIT %s",
            (int(user_id), int(user_id), int(user_id), int(user_id), int(limit)),
        )
        rows = cur.fetchall()
    return [{"id": r[0], "status": r[1], "role": "owner" if int(r[2]) == int(user_id) else "advertiser",
             "title": r[4], "updated_at": r[5], "unread": int(r[6])} for r in rows]


def close_inquiry(inquiry_id: int, user_id: int) -> dict | None:
    """Ishtirokchi suhbatni yopadi. Qaytadi: yopishdan oldingi ``get_inquiry`` (xabar berish uchun) yoki ``None``."""
    info = get_inquiry(inquiry_id, user_id)
    if info is None or info["status"] != "open":
        return None
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE ad_market_inquiries SET status = 'closed', updated_at = NOW() WHERE id = %s AND status = 'open'",
                    (int(inquiry_id),))
        if not cur.rowcount:
            return None
    return info


# ---------------------------------------------------------------- blok va shikoyat

def block_advertiser(owner_id: int, inquiry_id: int) -> dict | None:
    """Egasi reklama beruvchini bloklaydi va uning ochiq so'rovlarini yopadi."""
    info = get_inquiry(inquiry_id, owner_id)
    if info is None or info["role"] != "owner":
        return None
    adv = info["advertiser_id"]
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO ad_market_blocks (owner_id, blocked_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (int(owner_id), adv),
        )
        cur.execute(
            "UPDATE ad_market_inquiries SET status = 'closed', updated_at = NOW() "
            "WHERE owner_id = %s AND advertiser_id = %s AND status = 'open'",
            (int(owner_id), adv),
        )
    return info


def report_listing(listing_id: int, reporter_id: int) -> dict:
    """Shikoyat (bir foydalanuvchi bitta e'longa bir marta). ``{"ok", "reason", "count", "blocked"}``."""
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT owner_id, status FROM ad_market_listings WHERE id = %s", (int(listing_id),))
        row = cur.fetchone()
        if row is None:
            return {"ok": False, "reason": "not_found", "count": 0, "blocked": False}
        if int(row[0]) == int(reporter_id):
            return {"ok": False, "reason": "own", "count": 0, "blocked": False}
        cur.execute(
            "INSERT INTO ad_market_reports (listing_id, reporter_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (int(listing_id), int(reporter_id)),
        )
        fresh = bool(cur.rowcount)
        cur.execute("SELECT COUNT(*) FROM ad_market_reports WHERE listing_id = %s", (int(listing_id),))
        count = int(cur.fetchone()[0])
        blocked = False
        if count >= REPORT_BLOCK_THRESHOLD and row[1] != STATUS_BLOCKED:
            cur.execute("UPDATE ad_market_listings SET status = 'blocked', updated_at = NOW() WHERE id = %s", (int(listing_id),))
            blocked = True
        return {"ok": True, "reason": None if fresh else "again", "count": count, "blocked": blocked}


# ---------------------------------------------------------------- o'qilmagan xabarlar

def mark_read(inquiry_id: int, user_id: int) -> bool:
    """Suhbat ochilganda: shu foydalanuvchi uchun o'qilgan vaqt yangilanadi (faqat ishtirokchi)."""
    info = get_inquiry(inquiry_id, user_id)
    if info is None:
        return False
    col = "owner_read_at" if info["role"] == "owner" else "adv_read_at"
    with db_cursor(commit=True) as cur:
        cur.execute(f"UPDATE ad_market_inquiries SET {col} = NOW() WHERE id = %s", (int(inquiry_id),))  # nosec B608 — faqat modul konstantalari/oq ro'yxat; qiymatlar %s bilan
    return True


def unread_total(user_id: int) -> int:
    """Barcha ochiq suhbatlardagi o'qilmagan (ikkinchi tomon yozgan) xabarlar soni."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM ad_market_messages m JOIN ad_market_inquiries i ON i.id = m.inquiry_id "
            "WHERE i.status = 'open' AND m.sender_id <> %s AND ("
            " (i.owner_id = %s AND m.created_at > COALESCE(i.owner_read_at, 'epoch'::timestamptz)) OR "
            " (i.advertiser_id = %s AND m.created_at > i.adv_read_at))",
            (int(user_id), int(user_id), int(user_id)),
        )
        return int(cur.fetchone()[0])


# ---------------------------------------------------------------- foydalanuvchi shikoyati va global ban

def is_banned(user_id: int) -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM ad_market_bans WHERE user_id = %s", (int(user_id),))
        return cur.fetchone() is not None


def _ban(cur, user_id: int, reason: str) -> None:
    """Global ban: e'lonlari bloklanadi, ochiq suhbatlari yopiladi."""
    uid = int(user_id)
    cur.execute("INSERT INTO ad_market_bans (user_id, reason) VALUES (%s, %s) ON CONFLICT DO NOTHING", (uid, reason))
    cur.execute("UPDATE ad_market_listings SET status = 'blocked', updated_at = NOW() WHERE owner_id = %s", (uid,))
    cur.execute("UPDATE ad_market_inquiries SET status = 'closed', updated_at = NOW() "
                "WHERE (advertiser_id = %s OR owner_id = %s) AND status = 'open'", (uid, uid))


def admin_set_ban(user_id: int, banned: bool) -> bool:
    """Admin: foydalanuvchini birjadan butunlay chetlatish / qaytarish."""
    with db_cursor(commit=True) as cur:
        if banned:
            _ban(cur, user_id, "admin")
            return True
        cur.execute("DELETE FROM ad_market_bans WHERE user_id = %s", (int(user_id),))
        cur.execute("DELETE FROM ad_market_user_reports WHERE reported_id = %s", (int(user_id),))
        return True


def report_user(reporter_id: int, inquiry_id: int) -> dict:
    """Suhbatdagi ikkinchi tomon haqida shikoyat (firibgarlik). ``{"ok", "reason", "count", "banned", "reported_id"}``.

    Bir foydalanuvchi bir odamdan bir marta shikoyat qila oladi; ``USER_BAN_THRESHOLD`` ta TURLI foydalanuvchi
    shikoyat qilsa shikoyat qilingan odam avtomatik global banga tushadi.
    """
    info = get_inquiry(inquiry_id, reporter_id)
    if info is None:
        return {"ok": False, "reason": "not_found", "count": 0, "banned": False, "reported_id": None}
    reported = info["peer_id"]
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO ad_market_user_reports (reporter_id, reported_id, inquiry_id) VALUES (%s, %s, %s) "
            "ON CONFLICT DO NOTHING", (int(reporter_id), int(reported), int(inquiry_id)))
        fresh = bool(cur.rowcount)
        cur.execute("SELECT COUNT(*) FROM ad_market_user_reports WHERE reported_id = %s", (int(reported),))
        count = int(cur.fetchone()[0])
        banned = False
        if count >= USER_BAN_THRESHOLD:
            cur.execute("SELECT 1 FROM ad_market_bans WHERE user_id = %s", (int(reported),))
            if cur.fetchone() is None:
                _ban(cur, reported, "reports")
                banned = True
    return {"ok": True, "reason": None if fresh else "again", "count": count, "banned": banned, "reported_id": reported}


def get_account_age_days(user_id: int) -> float | None:
    """Botdagi hisob yoshi (kun); noma'lum bo'lsa ``None``."""
    with db_cursor() as cur:
        cur.execute("SELECT EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400.0 FROM users WHERE user_id = %s", (int(user_id),))
        row = cur.fetchone()
    return float(row[0]) if row and row[0] is not None else None


def count_peer_reports(user_id: int) -> int:
    """Shu foydalanuvchi haqida nechta shikoyat bor (egasiga «ishonchsiz» nishoni uchun)."""
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM ad_market_user_reports WHERE reported_id = %s", (int(user_id),))
        return int(cur.fetchone()[0])


def admin_list_listings(limit: int = 30, status: str | None = None) -> list[dict]:
    """Admin nazorati: so'nggi e'lonlar (barcha holatlar) + shikoyatlar soni."""
    where, params = "", []
    if status in (STATUS_ACTIVE, STATUS_PAUSED, STATUS_BLOCKED):
        where, params = "WHERE l.status = %s", [status]
    with db_cursor() as cur:
        cur.execute(
            f"SELECT l.id, l.title, l.username, l.owner_id, l.category, l.status, l.members, l.view_count, l.inquiry_count, "  # nosec B608 — faqat modul konstantalari/oq ro'yxat; qiymatlar %s bilan
            f"(SELECT COUNT(*) FROM ad_market_reports r WHERE r.listing_id = l.id), "
            f"EXISTS (SELECT 1 FROM ad_market_bans b WHERE b.user_id = l.owner_id) "
            f"FROM ad_market_listings l {where} ORDER BY l.created_at DESC LIMIT %s",
            params + [max(1, min(int(limit), 100))],
        )
        rows = cur.fetchall()
    return [{"id": r[0], "title": r[1], "username": r[2], "owner_id": int(r[3]), "category": r[4], "status": r[5],
             "members": r[6], "view_count": r[7], "inquiry_count": r[8], "reports": int(r[9]), "owner_banned": bool(r[10])}
            for r in rows]


def admin_market_totals() -> dict:
    """Admin nazorati uchun umumiy hisob: e'lonlar holati, chetlatilganlar, shikoyatlar."""
    with db_cursor() as cur:
        cur.execute("SELECT status, COUNT(*) FROM ad_market_listings GROUP BY status")
        by_status = {r[0]: int(r[1]) for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*) FROM ad_market_bans")
        banned = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM ad_market_inquiries WHERE status = 'open'")
        open_inq = int(cur.fetchone()[0])
    return {"active": by_status.get("active", 0), "paused": by_status.get("paused", 0), "blocked": by_status.get("blocked", 0),
            "banned_users": banned, "open_inquiries": open_inq}


# ---------------------------------------------------------------- hisobni o'chirish

def delete_user_market_data(cur, user_id: int) -> dict:
    """Foydalanuvchining birja ma'lumotlari (``users_repository`` o'chirish tranzaksiyasi ichida chaqiriladi)."""
    uid = int(user_id)
    out = {}
    cur.execute("DELETE FROM ad_market_listings WHERE owner_id = %s", (uid,))
    out["ad_market_listings"] = int(cur.rowcount or 0)
    cur.execute("DELETE FROM ad_market_inquiries WHERE advertiser_id = %s OR owner_id = %s", (uid, uid))
    out["ad_market_inquiries"] = int(cur.rowcount or 0)
    cur.execute("DELETE FROM ad_market_reports WHERE reporter_id = %s", (uid,))
    cur.execute("DELETE FROM ad_market_blocks WHERE owner_id = %s OR blocked_id = %s", (uid, uid))
    cur.execute("DELETE FROM ad_market_user_reports WHERE reporter_id = %s", (uid,))
    # Ban va unga kelgan shikoyatlar SAQLANADI: hisobni o'chirib ban'dan qochib bo'lmasin (faqat user_id, boshqa ma'lumot yo'q).
    return out
