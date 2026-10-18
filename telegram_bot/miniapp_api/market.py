"""💰 Reklama birjasi — Mini App API (``/api/v1/market/*``).

Biznes-qoidalar BOT bilan AYNAN bir xil (``repositories/ad_market_repository.py``: egalik, kunlik so'rov limiti, blok,
shikoyat, xabar limiti); bu qatlam faqat HTTP <-> repository <-> Telegram (egalikni jonli tekshirish, egasiga xabar) ko'prigi.

  * ``user_id`` faqat tasdiqlangan ``initData`` dan; e'lon/suhbat egaligi HAR DOIM repository SQL ichida tekshiriladi;
  * mijozga faqat ommaviy maydonlar: obunachi/ko'rish/ER, narx, tavsif (egasining ichki hisoblagichlari faqat egasiga);
  * xato matni mijozga o'tmaydi (katalogdagi kodlar).
"""
from __future__ import annotations

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from . import writes
from .errors import ApiError
from .service import iso_utc
from .settings import MiniAppSettings

logger = logging.getLogger(__name__)

TEXT_MAX = 1000
SORTS = ("m", "p", "e")


def _repo():
    from repositories import ad_market_repository as repo

    return repo


def _svc():
    from services import ad_market as svc

    return svc


def public_listing(row: dict, *, owner: bool = False) -> dict:
    """Ommaviy e'lon ko'rinishi (ichki maydonlarsiz)."""
    svc = _svc()
    out = {
        "id": row["id"], "title": row.get("title") or row["username"], "username": row["username"],
        "category": row["category"], "price": row.get("price_post"), "description": row.get("description"),
        "members": row.get("members"), "avg_views": row.get("avg_views"), "er_percent": row.get("er_percent"),
        "growth_30d": row.get("growth_30d"), "posts_30d": row.get("posts_30d"),
        "stats_updated_at": iso_utc(row["stats_updated_at"]) if row.get("stats_updated_at") else None,
        "badges": svc.listing_badges(row),
    }
    if owner:
        out.update({"status": row["status"], "channel_id": row["channel_id"],
                    "view_count": row.get("view_count", 0), "inquiry_count": row.get("inquiry_count", 0)})
    return out


def parse_price(value) -> int | None:
    """JSON narx: ``null`` — kelishiladi; aks holda butun son (PRICE_MIN..PRICE_MAX)."""
    svc = _svc()
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < svc.PRICE_MIN or value > svc.PRICE_MAX:
        raise ApiError("invalid_input", field="price")
    return value


def parse_description(value) -> str | None:
    svc = _svc()
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError("invalid_input", field="description")
    text = svc.clean_text(value, svc.DESCRIPTION_MAX + 1)
    if len(text) > svc.DESCRIPTION_MAX:
        raise ApiError("invalid_input", field="description")
    return text or None


def parse_category(value) -> str:
    if value not in _svc().CATEGORIES:
        raise ApiError("invalid_input", field="category")
    return value


def parse_message(value) -> str:
    text = writes.parse_text(value, "text", max_chars=TEXT_MAX)
    return text


class MarketApi:
    def __init__(self, service, settings: MiniAppSettings, *, bot_factory=None, repo=None) -> None:
        self._service = service
        self._settings = settings
        self._gate = asyncio.Semaphore(settings.max_inflight_db)
        self._repo = repo
        self._bot_holder = writes.MediaFetcher(settings.bot_token, bot_factory)

    # ------------------------------------------------------------ yordamchilar
    def repo(self):
        if self._repo is None:
            self._repo = _repo()
        return self._repo

    async def _blocking(self, fn, *args):
        try:
            await asyncio.wait_for(self._gate.acquire(), self._settings.db_queue_wait_seconds or 0.01)
        except asyncio.TimeoutError:
            raise ApiError("service_unavailable", retry_after=2) from None
        try:
            return await asyncio.to_thread(fn, *args)
        except ApiError:
            raise
        except Exception as exc:  # noqa: BLE001 — xabar SQL/qiymat saqlashi mumkin
            logger.warning("miniapp market: DB xatosi (%s)", type(exc).__name__)
            raise ApiError("service_unavailable", retry_after=3) from None
        finally:
            self._gate.release()

    async def _bot(self):
        return await self._bot_holder.get_bot()

    async def aclose(self) -> None:
        await self._bot_holder.aclose()

    async def _lang_of(self, user_id: int) -> str:
        import database as db

        try:
            return (await self._blocking(db.get_user_language, user_id)) or "uz"
        except ApiError:
            return "uz"

    async def _notify(self, user_id: int, text: str, markup=None) -> bool:
        """Ikkinchi tomonga bot orqali xabar. Yetkazilmasa ``False`` (Mini App amali bekor bo'lmaydi)."""
        try:
            bot = await self._bot()
            await bot.send_message(user_id, text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                   disable_web_page_preview=True)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.info("miniapp market: xabar yetkazilmadi (%s)", type(exc).__name__)
            return False

    @staticmethod
    def _thread_markup(inquiry_id: int, role: str, lang: str) -> InlineKeyboardMarkup:
        from translations import market_t

        rows = [[InlineKeyboardButton(market_t("mk_btn_reply", lang), callback_data=f"mk:r:{inquiry_id}"),
                 InlineKeyboardButton(market_t("mk_btn_share", lang), callback_data=f"mk:c:{inquiry_id}")],
                [InlineKeyboardButton(market_t("mk_btn_end", lang), callback_data=f"mk:x:{inquiry_id}")]]
        if role == "owner":
            rows[1].append(InlineKeyboardButton(market_t("mk_btn_block", lang), callback_data=f"mk:b:{inquiry_id}"))
        return InlineKeyboardMarkup(rows)

    # ---------------------------------------------------------------- katalog
    async def summary(self, user_id: int) -> dict:
        await self._service.authorize(user_id)
        svc, repo = _svc(), self.repo()
        totals = await self._blocking(repo.market_totals)
        return {**totals, "categories": list(svc.CATEGORIES), "max_listings": repo.MAX_LISTINGS_PER_USER,
                "price_min": svc.PRICE_MIN, "price_max": svc.PRICE_MAX,
                "description_max": svc.DESCRIPTION_MAX, "message_min": svc.INQUIRY_MIN, "message_max": TEXT_MAX}

    async def catalog(self, user_id: int, *, category: str | None, sort: str, page: int) -> dict:
        await self._service.authorize(user_id)
        svc, repo = _svc(), self.repo()
        if category not in (None, "", "all") and category not in svc.CATEGORIES:
            raise ApiError("bad_request")
        if sort not in SORTS:
            raise ApiError("bad_request")
        data = await self._blocking(repo.list_catalog, category or "all", sort, page, repo.PAGE_SIZE)
        pages = max(1, -(-data["total"] // repo.PAGE_SIZE))
        return {"items": [public_listing(i) for i in data["items"]], "total": data["total"], "page": page,
                "pages": pages, "page_size": repo.PAGE_SIZE}

    async def listing(self, user_id: int, listing_id: int) -> dict:
        await self._service.authorize(user_id)
        svc, repo = _svc(), self.repo()
        row = await self._blocking(repo.get_public_listing, listing_id, user_id)
        if row is None:
            raise ApiError("not_found")
        if svc.stats_are_stale(row):
            await self._blocking(svc.refresh_listing_stats, row["id"], row["channel_id"], row.get("members"))
            row = await self._blocking(repo.get_listing, listing_id) or row
        return {"listing": public_listing(row), "is_owner": row["owner_id"] == user_id}

    async def inquire(self, user_id: int, listing_id: int, body: dict) -> dict:
        writes._only_keys(body, ("text",))
        text = parse_message(body.get("text"))
        svc, repo = _svc(), self.repo()
        if len(text) < svc.INQUIRY_MIN:
            raise ApiError("invalid_input", field="text")
        await self._service.authorize(user_id)
        res = await self._blocking(repo.create_inquiry, listing_id, user_id, text)
        if not res["ok"]:
            raise ApiError({"limit": "inquiry_limit", "blocked": "inquiry_blocked", "own": "inquiry_own",
                            "open_exists": "inquiry_exists"}.get(res["reason"], "not_found"))
        from translations import market_t
        from utils.helpers import html_escape

        listing = await self._blocking(repo.get_listing, listing_id)
        owner_lang = await self._lang_of(res["owner_id"])
        delivered = await self._notify(
            res["owner_id"],
            market_t("mk_inq_owner_new", owner_lang, title=html_escape((listing or {}).get("title") or ""),
                     text=html_escape(text)),
            self._thread_markup(res["inquiry_id"], "owner", owner_lang))
        return {"inquiry_id": res["inquiry_id"], "delivered": delivered}

    async def report(self, user_id: int, listing_id: int) -> dict:
        await self._service.authorize(user_id)
        repo = self.repo()
        res = await self._blocking(repo.report_listing, listing_id, user_id)
        if not res["ok"]:
            raise ApiError("inquiry_own" if res["reason"] == "own" else "not_found")
        if res["blocked"]:
            from config import ADMIN_IDS_SET
            from translations import market_t

            listing = await self._blocking(repo.get_listing, listing_id)
            for admin_id in ADMIN_IDS_SET:
                await self._notify(admin_id, market_t("mk_admin_blocked", "uz", id=listing_id,
                                                      username=(listing or {}).get("username", "?"), count=res["count"]))
        return {"reported": True, "again": res["reason"] == "again", "blocked": bool(res["blocked"])}

    # ----------------------------------------------------------- kanal egasi
    async def mine(self, user_id: int) -> dict:
        await self._service.authorize(user_id)
        repo = self.repo()
        channels = await self._blocking(repo.list_owner_channels, user_id)
        items = []
        for c in channels:
            listing = None
            if c["listing_id"]:
                row = await self._blocking(repo.get_listing_for_owner, c["listing_id"], user_id)
                listing = public_listing(row, owner=True) if row else None
            items.append({"channel_id": str(c["channel_id"]), "title": c["title"] or str(c["channel_id"]), "listing": listing})
        return {"items": items, "max_listings": repo.MAX_LISTINGS_PER_USER}

    async def publish(self, user_id: int, body: dict) -> dict:
        writes._only_keys(body, ("channel_id", "category", "price", "description"))
        channel_id = writes.parse_channel_id(body.get("channel_id"))
        category = parse_category(body.get("category"))
        price = parse_price(body.get("price"))
        description = parse_description(body.get("description"))
        await self._service.authorize(user_id)
        svc, repo = _svc(), self.repo()
        channel = await self._blocking(repo.get_owned_channel, user_id, channel_id)
        if channel is None:
            raise ApiError("channel_not_found")
        if await self._blocking(repo.count_owner_listings, user_id) >= repo.MAX_LISTINGS_PER_USER:
            raise ApiError("market_limit")
        info = await svc.verify_channel_ownership(await self._bot(), user_id, channel["channel_id"])
        if not info["ok"]:
            raise ApiError({"private": "market_private", "tg_error": "service_unavailable"}.get(info["reason"], "market_not_admin"))
        res = await self._blocking(repo.create_listing, user_id, channel["channel_id"], info["username"],
                                   info["title"] or channel.get("title") or info["username"], category, price, description)
        if not res["ok"]:
            raise ApiError({"limit": "market_limit", "exists": "inquiry_exists"}.get(res["reason"], "channel_not_found"))
        await self._blocking(svc.refresh_listing_stats, res["listing_id"], channel["channel_id"], info["members"])
        row = await self._blocking(repo.get_listing_for_owner, res["listing_id"], user_id)
        return {"listing": public_listing(row, owner=True)}

    async def update_listing(self, user_id: int, listing_id: int, body: dict) -> dict:
        writes._only_keys(body, ("category", "price", "description", "status"))
        if not body:
            raise ApiError("invalid_input")
        fields: dict = {}
        if "category" in body:
            fields["category"] = parse_category(body["category"])
        if "price" in body:
            fields["price_post"] = parse_price(body["price"])
        if "description" in body:
            fields["description"] = parse_description(body["description"])
        status = body.get("status")
        if "status" in body and status not in ("active", "paused"):
            raise ApiError("invalid_input", field="status")
        await self._service.authorize(user_id)
        repo = self.repo()
        row = await self._blocking(repo.get_listing_for_owner, listing_id, user_id)
        if row is None:
            raise ApiError("not_found")
        if "status" in body:
            if row["status"] == "blocked":
                raise ApiError("market_blocked")
            await self._blocking(repo.set_listing_status, listing_id, user_id, status)
        if fields:
            await self._blocking(lambda: repo.update_listing_fields(listing_id, user_id, **fields))
        row = await self._blocking(repo.get_listing_for_owner, listing_id, user_id)
        return {"listing": public_listing(row, owner=True)}

    async def refresh(self, user_id: int, listing_id: int) -> dict:
        await self._service.authorize(user_id)
        svc, repo = _svc(), self.repo()
        row = await self._blocking(repo.get_listing_for_owner, listing_id, user_id)
        if row is None:
            raise ApiError("not_found")
        live = None
        try:
            raw = row["channel_id"]
            live = await (await self._bot()).get_chat_member_count(int(raw) if str(raw).lstrip("-").isdigit() else raw)
        except Exception as exc:  # noqa: BLE001 — jonli son bo'lmasa bazadagi ma'lumot ishlatiladi
            logger.debug("miniapp market: jonli obunachi soni olinmadi (%s)", type(exc).__name__)
        await self._blocking(svc.refresh_listing_stats, listing_id, row["channel_id"], live)
        row = await self._blocking(repo.get_listing_for_owner, listing_id, user_id)
        return {"listing": public_listing(row, owner=True)}

    async def delete_listing(self, user_id: int, listing_id: int) -> dict:
        await self._service.authorize(user_id)
        if not await self._blocking(self.repo().delete_listing, listing_id, user_id):
            raise ApiError("not_found")
        return {"id": listing_id, "deleted": True}

    # --------------------------------------------------------------- suhbatlar
    async def threads(self, user_id: int) -> dict:
        await self._service.authorize(user_id)
        rows = await self._blocking(self.repo().list_user_inquiries, user_id, 30)
        return {"items": [{"id": r["id"], "title": r["title"] or "", "role": r["role"],
                           "updated_at": iso_utc(r["updated_at"])} for r in rows]}

    async def thread(self, user_id: int, inquiry_id: int) -> dict:
        await self._service.authorize(user_id)
        repo = self.repo()
        info = await self._blocking(repo.get_inquiry, inquiry_id, user_id)
        if info is None:
            raise ApiError("not_found")
        msgs = await self._blocking(repo.recent_messages, inquiry_id, user_id, 40)
        return {"thread": {"id": info["id"], "title": info["title"] or "", "username": info["username"],
                           "role": info["role"], "status": info["status"], "listing_id": info["listing_id"]},
                "messages": [{"mine": m["sender_id"] == user_id, "text": m["body"], "at": iso_utc(m["created_at"])} for m in msgs]}

    async def reply(self, user_id: int, inquiry_id: int, body: dict) -> dict:
        writes._only_keys(body, ("text",))
        text = parse_message(body.get("text"))
        await self._service.authorize(user_id)
        repo = self.repo()
        res = await self._blocking(repo.add_message, inquiry_id, user_id, text)
        if not res["ok"]:
            raise ApiError({"closed": "thread_closed", "full": "thread_full"}.get(res["reason"], "not_found"))
        from translations import market_t
        from utils.helpers import html_escape

        info = await self._blocking(repo.get_inquiry, inquiry_id, user_id)
        peer_lang = await self._lang_of(res["recipient_id"])
        peer_role = "advertiser" if info["role"] == "owner" else "owner"
        delivered = await self._notify(
            res["recipient_id"],
            market_t("mk_msg_in", peer_lang, title=html_escape(info["title"] or ""),
                     role=market_t("mk_role_owner" if info["role"] == "owner" else "mk_role_adv", peer_lang),
                     text=html_escape(text)),
            self._thread_markup(inquiry_id, peer_role, peer_lang))
        return {"sent": True, "delivered": delivered}

    async def close_thread(self, user_id: int, inquiry_id: int) -> dict:
        await self._service.authorize(user_id)
        info = await self._blocking(self.repo().close_inquiry, inquiry_id, user_id)
        if info is None:
            raise ApiError("not_found")
        from translations import market_t
        from utils.helpers import html_escape

        peer_lang = await self._lang_of(info["peer_id"])
        await self._notify(info["peer_id"], market_t("mk_closed_notice", peer_lang, title=html_escape(info["title"] or "")))
        return {"closed": True}

    async def block(self, user_id: int, inquiry_id: int) -> dict:
        await self._service.authorize(user_id)
        if await self._blocking(self.repo().block_advertiser, user_id, inquiry_id) is None:
            raise ApiError("not_found")
        return {"blocked": True}
