"""📡 RSS / ATOM OQIMI — yangi elementlardan post qoralamalari (PHASE D, 12-band).

Funksional zanjir::

    content_sources (manba)  →  SSRF-xavfsiz yuklash  →  RSS/ATOM parse
        →  DUBLIKAT FILTRI (source_items UNIQUE(source_id, external_id))
        →  Channel DNA asosida post loyihasi (draft)
        →  [Admin/egasi tasdig'i] yoki [reja navbatiga] (autopublish)

Kafolatlar:
  * **Dublikat qayta ishlanmaydi**: har bir element ``(source_id,
    external_id)`` juftligi bo'yicha bazada UNIQUE; ikkinchi marta o'qilgan
    element uchun qoralama YARATILMAYDI (DB darajasida ham,
    ``filter_new_items`` bilan xotirada ham);
  * **SSRF himoyasi**: oqim manzili ham ``url_extractor`` orqali tekshiriladi
    (localhost/ichki IP/redirect — bloklanadi, 5 MB / 10 s);
  * **Autopublish**: yoqilgan manbalarda qoralama reja navbatiga
    (``scheduled_posts``) yuboriladi; o'chirilgan bo'lsa — tasdiqlash uchun
    egasiga/adminga ko'rsatiladi (``source_drafts`` status='pending');
  * **Fail-soft**: bitta manba xatosi qolganlarini to'xtatmaydi, hech qanday
    istisno tashqariga chiqmaydi.
"""

from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable
from urllib import parse as urlparse

import pytz

from ..ai.smm_common import SMMFeatureService, clip, sanitize_html
from . import url_extractor as ux

logger = logging.getLogger(__name__)

tashkent_tz = pytz.timezone("Asia/Tashkent")

#: Rejalashtirish uchun yagona standart vaqt zonasi (scheduler bilan bir xil).

# ---------------------------------------------------------------------------
# CHEGARALAR
# ---------------------------------------------------------------------------
DEFAULT_INTERVAL_MINUTES = 60
MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 1440
MAX_ITEMS_PER_CHECK = 20             # bitta tekshiruvda eng ko'p yangi element
MAX_SUMMARY_CHARS = 1200
MAX_TITLE_CHARS = 300
MAX_FEED_BYTES = ux.MAX_RESPONSE_BYTES
FEED_TIMEOUT_SECONDS = ux.FETCH_TIMEOUT_SECONDS
MAX_SOURCES_PER_TICK = 25            # scheduler tick'dagi manbalar soni
AUTOPUBLISH_HOUR_FALLBACK = 19       # best-time yo'q bo'lsa standart soat

ERR_INVALID_URL = "invalid_url"
ERR_FETCH_FAILED = "fetch_failed"
ERR_PARSE_FAILED = "parse_failed"
ERR_NO_ITEMS = "no_new_items"
ERR_DUPLICATE = "duplicate"
ERR_DRAFT_FAILED = "draft_failed"

#: Element matn maydonlari (RSS + ATOM).
_TAG_STRIP_RE = re.compile(r"<[^>]{1,200}>")
_WS_RE = re.compile(r"\s+")
#: Ichki subset'li DOCTYPE (``<!DOCTYPE x [<!ENTITY e "v">]>``) ALOHIDA
#: regex bilan olib tashlanadi — aks holda qolgan ``]>`` XML'ni buzadi.
_DOCTYPE_SUBSET_RE = re.compile(r"<!\s*DOCTYPE\b[^\[]*\[[^\]]*\]\s*>",
                                re.IGNORECASE | re.DOTALL)
_DOCTYPE_RE = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b[^>]*>",
                         re.IGNORECASE | re.DOTALL)

MESSAGE_KEYS = {
    ERR_INVALID_URL: "rss_msg_invalid_url",
    ERR_FETCH_FAILED: "rss_msg_fetch_failed",
    ERR_PARSE_FAILED: "rss_msg_parse_failed",
    ERR_NO_ITEMS: "rss_msg_no_items",
}


# ---------------------------------------------------------------------------
# 1) PURE: FEED PARSE (RSS 2.0 / Atom 1.0)
# ---------------------------------------------------------------------------
@dataclass
class FeedItem:
    """Bitta oqim elementi (dublikat kaliti — ``external_id``)."""

    external_id: str
    canonical_url: str
    title: str
    summary: str = ""
    published_at: str = ""
    raw_id: str = ""

    def as_dict(self) -> dict:
        return {
            "external_id": self.external_id,
            "canonical_url": self.canonical_url,
            "title": self.title,
            "summary": self.summary,
            "published_at": self.published_at,
            "raw_id": self.raw_id,
        }


def strip_markup(value: Any) -> str:
    """HTML teglar/matn ortiqchalaridan tozalash (PURE)."""
    text = str(value or "")
    text = _TAG_STRIP_RE.sub(" ", text)
    text = (
        text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        .replace("&quot;", '"').replace("&#39;", "'").replace("&apos;", "'")
    )
    return _WS_RE.sub(" ", text).strip()


def sanitize_xml(xml_text: str, *, max_bytes: int = MAX_FEED_BYTES) -> str:
    """XML'ni xavfsiz holga keltiradi (XXE / billion-laughs himoyasi).

    * hajm cheklanadi;
    * ``DOCTYPE``/``ENTITY`` (tashqi entity va entity-bombalar) olib tashlanadi
      — ichki subset bilan birga, shunda ortiqcha ``]>`` qolmaydi;
    * XML deklaratsiyasi (``<?xml ...?>``) tegilmaydi (u zararsiz).
    """
    text = str(xml_text or "")
    if len(text.encode("utf-8", errors="ignore")) > max_bytes:
        text = text[:max_bytes]
    text = _DOCTYPE_SUBSET_RE.sub(" ", text)
    text = _DOCTYPE_RE.sub(" ", text)
    return text


def _local_name(tag: str) -> str:
    """``{namespace}title`` → ``title`` (RSS namespace'lari uchun)."""
    value = str(tag or "")
    return value.rsplit("}", 1)[-1].lower()


def _find_text(element, *names: str) -> str:
    """Birinchi mos kelgan bolaning matnini qaytaradi (namespace'siz)."""
    wanted = {name.lower() for name in names}
    for child in list(element):
        if _local_name(child.tag) in wanted:
            text = "".join(child.itertext())
            if text and text.strip():
                return text.strip()
    return ""


def _find_link(element, base_url: str = "") -> str:
    """RSS ``<link>`` yoki ATOM ``<link href rel=alternate>`` ni oladi."""
    for child in list(element):
        if _local_name(child.tag) != "link":
            continue
        href = child.get("href")
        rel = (child.get("rel") or "alternate").lower()
        if href and rel in ("alternate", ""):
            return _absolute_url(href, base_url)
        text = (child.text or "").strip()
        if text:
            return _absolute_url(text, base_url)
    return ""


def _absolute_url(url: str, base_url: str = "") -> str:
    """Nisbiy havolani manba domeni bo'yicha to'liq havolaga aylantiradi."""
    value = str(url or "").strip()
    if not value:
        return ""
    if base_url:
        try:
            return urlparse.urljoin(base_url, value)
        except Exception:  # pragma: no cover
            return value
    return value


#: Havoladan kuzatuv parametrlari olib tashlanadi (dublikat kaliti uchun).
_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "yclid", "igshid", "_openstat")


def canonical_url(url: str) -> str:
    """Havolani kanonik ko'rinishga keltiradi (fragment + tracking olib tashlanadi)."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlparse.urlsplit(raw)
    except Exception:  # pragma: no cover
        return raw
    query_pairs = []
    for key, value in urlparse.parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in _TRACKING_PREFIXES or key.lower().startswith("utm_"):
            continue
        query_pairs.append((key, value))
    query = urlparse.urlencode(query_pairs)
    host = (parts.hostname or "").lower()
    netloc = host
    if parts.port:
        netloc = f"{host}:{parts.port}"
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlparse.urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def item_external_id(entry, canonical: str, title: str = "") -> str:
    """Element uchun barqaror dublikat kaliti (guid/id yoki kanonik URL)."""
    raw = ""
    for child in list(entry):
        if _local_name(child.tag) in ("id", "guid"):
            raw = "".join(child.itertext()).strip()
            if raw:
                break
    if raw:
        return raw[:512]
    seed = canonical or title or ""
    return hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()


def feed_type_of(root) -> str:
    """Oqim turi: ``rss`` yoki ``atom``."""
    name = _local_name(getattr(root, "tag", ""))
    if name == "feed":
        return "atom"
    return "rss"


def parse_feed(xml_text: str, *, base_url: str = "") -> dict:
    """RSS 2.0 yoki Atom 1.0 oqimini o'qiydi (PURE, tashqi kutubxonasiz).

    Qaytadi::

        {"ok": True, "feed_type": "rss", "feed_title": "...",
         "items": [FeedItem, ...], "error_code": None}
        {"ok": False, "error_code": "parse_failed", "items": []}
    """
    safe_xml = sanitize_xml(xml_text)
    if not safe_xml.strip():
        return {"ok": False, "error_code": ERR_PARSE_FAILED, "items": [],
                "feed_title": "", "feed_type": ""}
    try:
        root = ET.fromstring(safe_xml)
    except ET.ParseError as exc:
        logger.info("RSS parse xatosi: %s", exc)
        return {"ok": False, "error_code": ERR_PARSE_FAILED, "items": [],
                "feed_title": "", "feed_type": ""}
    except Exception as exc:  # noqa: BLE001 — buzuq XML ham xavfsiz
        logger.info("RSS kutilmagan parse xatosi: %s", exc)
        return {"ok": False, "error_code": ERR_PARSE_FAILED, "items": [],
                "feed_title": "", "feed_type": ""}

    feed_type = feed_type_of(root)

    # RSS 2.0 da elementlar ``<channel>`` ICHIDA turadi (``<rss><channel><item>``),
    # Atom'da esa to'g'ridan-to'g'ri root ichida. Shu sababli konteyner
    # aniqlanadi — aks holda RSS oqimlari «bo'sh» ko'rinadi (0 element).
    container = root
    for child in list(root):
        if _local_name(child.tag) == "channel":
            container = child
            break

    feed_title = strip_markup(
        _find_text(container, "title") or _find_text(root, "title")
    )[:MAX_TITLE_CHARS]

    entries = [child for child in list(container)
               if _local_name(child.tag) in ("item", "entry")]
    if not entries and container is not root:
        # RSS 1.0 (RDF) kabi aralash ko'rinishlar: elementlar root ostida.
        entries = [child for child in list(root)
                   if _local_name(child.tag) in ("item", "entry")]
    items: list[FeedItem] = []
    seen: set[str] = set()
    for entry in entries:
        title = strip_markup(_find_text(entry, "title"))[:MAX_TITLE_CHARS]
        link = _find_link(entry, base_url)
        canonical = canonical_url(link)
        summary_raw = _find_text(entry, "description", "summary", "content",
                                 "encoded")
        summary = strip_markup(summary_raw)[:MAX_SUMMARY_CHARS]
        published = _find_text(entry, "pubdate", "published", "updated",
                               "date")
        external_id = item_external_id(entry, canonical, title)
        if not external_id or external_id in seen:
            continue
        if not canonical and not title:
            continue
        seen.add(external_id)
        items.append(FeedItem(
            external_id=external_id,
            canonical_url=canonical,
            title=title or clip(canonical, MAX_TITLE_CHARS),
            summary=summary,
            published_at=str(published or "")[:64],
            raw_id=external_id,
        ))
    return {"ok": True, "error_code": None, "feed_type": feed_type,
            "feed_title": feed_title, "items": items}


# ---------------------------------------------------------------------------
# 2) PURE: DUBLIKAT FILTRI + JADVAL (interval) HISOBLARI
# ---------------------------------------------------------------------------
def filter_new_items(items: Iterable[FeedItem],
                     known_ids: Iterable[str]) -> list[FeedItem]:
    """Faqat YANGI elementlarni qoldiradi (dublikat qayta ishlanmaydi)."""
    known = {str(item or "").strip() for item in (known_ids or []) if item}
    fresh: list[FeedItem] = []
    seen: set[str] = set()
    for item in items or []:
        key = str(getattr(item, "external_id", "") or "").strip()
        if not key or key in known or key in seen:
            continue
        seen.add(key)
        fresh.append(item)
    return fresh


def clamp_interval(minutes: Any) -> int:
    """Intervalni xavfsiz chegaraga keltiradi (15..1440 daqiqa)."""
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_MINUTES
    return max(MIN_INTERVAL_MINUTES, min(MAX_INTERVAL_MINUTES, value))


def parse_interval_input(text: Any) -> int | None:
    """Foydalanuvchi kiritgan intervalni o'qiydi: ``60``, ``2 soat``, ``30m``."""
    raw = str(text or "").strip().lower().replace(",", ".")
    if not raw:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", raw)
    if not match:
        return None
    value = float(match.group(1))
    if any(token in raw for token in ("soat", "hour", "ч", "h")):
        value *= 60
    elif "kun" in raw or "day" in raw or "дн" in raw:
        value *= 1440
    if value <= 0:
        return None
    return clamp_interval(round(value))


def as_utc(value: Any) -> datetime | None:
    """Turli ko'rinishdagi vaqtni UTC aware datetime'ga keltiradi (fail-soft)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        # DB TIMESTAMPTZ UTC'da qaytaradi; naive qiymat — UTC deb olamiz.
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def next_check_at(source: dict, *, now: datetime | None = None) -> datetime:
    """Keyingi tekshiruv vaqti (last_checked_at + interval)."""
    moment = now or datetime.now(timezone.utc)
    last = as_utc((source or {}).get("last_checked_at")
                  or (source or {}).get("created_at"))
    interval = clamp_interval((source or {}).get("interval_minutes"))
    if last is None:
        return moment
    return last + timedelta(minutes=interval)


def is_source_due(source: dict, *, now: datetime | None = None) -> bool:
    """Manba vaqti kelganini bildiradi (enabled + interval)."""
    data = dict(source or {})
    if not data.get("enabled", True):
        return False
    moment = now or datetime.now(timezone.utc)
    return next_check_at(data, now=moment) <= moment


def digest_draft(item: FeedItem, *, lang: str = "uz",
                 channel_title: str = "") -> str:
    """AI'siz, FAQAT oqim mazmunidan tuzilgan qoralama (fakt qo'shilmaydi).

    AI mavjud bo'lmaganda ham oqim ishlayveradi va foydalanuvchi nima
    o'qiyotganini aniq ko'radi (``ai_used=False``).
    """
    labels = {
        "uz": {"new": "📡 Yangi maqola", "source": "🔗 Manba", "more": "👉 Batafsil"},
        "ru": {"new": "📡 Новая статья", "source": "🔗 Источник",
               "more": "👉 Подробнее"},
        "en": {"new": "📡 New article", "source": "🔗 Source",
               "more": "👉 Read more"},
    }.get(lang if lang in ("uz", "ru", "en") else "uz")
    title = clip(strip_markup(item.title), MAX_TITLE_CHARS)
    summary = clip(strip_markup(item.summary), 600)
    url = clip(item.canonical_url or "", 300)
    head = f"{labels['new']}"
    if channel_title:
        head += f" · {clip(strip_markup(channel_title), 60)}"
    body = f"{head}\n\n<b>{title}</b>"
    if summary:
        body += f"\n\n{summary}"
    if url:
        body += f"\n\n{labels['source']}: {url}"
    return sanitize_html(body, 3600)


# ---------------------------------------------------------------------------
# 3) XIZMAT — MANBANI TEKSHIRISH + QORALAMA YARATISH
# ---------------------------------------------------------------------------
def _import_database():
    try:
        import database as db
        return db
    except Exception:  # pragma: no cover — test muhitida modul yo'q bo'lishi mumkin
        return None


async def _db_call(db: Any, fn, *args, **kwargs):
    """DB funksiyasini chaqiradi (``run_db`` bo'lsa thread'da)."""
    runner = getattr(db, "run_db", None)
    if callable(runner):
        return await runner(fn, *args, **kwargs)
    import asyncio
    return await asyncio.to_thread(fn, *args, **kwargs)


class RssService(SMMFeatureService):
    """RSS/ATOM manbalarini tekshiruvchi va qoralama yaratuvchi xizmat."""

    feature = "rss"
    quota_operation = "magic_post"
    quota_cost = 1

    # -- 1 qadam: oqimni yuklash -------------------------------------------
    @staticmethod
    def load_feed(url: str, *, client: Any = None, resolver=None,
                  timeout: float = FEED_TIMEOUT_SECONDS) -> dict:
        """Oqimni SSRF-xavfsiz yuklaydi (5 MB / 10 s chegarasi bilan)."""
        fetched = ux.fetch_url(url, client=client, resolver=resolver,
                               timeout=timeout, max_bytes=MAX_FEED_BYTES)
        if not fetched.get("ok"):
            return {"ok": False, "error_code": ERR_FETCH_FAILED,
                    "message": fetched.get("message"), "items": [],
                    "guard_code": fetched.get("error_code")}
        parsed = parse_feed(fetched.get("text", ""),
                            base_url=fetched.get("final_url") or url)
        if not parsed.get("ok"):
            return {"ok": False, "error_code": ERR_PARSE_FAILED,
                    "message": None, "items": [], "guard_code": None}
        return {"ok": True, "error_code": None, "message": None,
                "items": parsed["items"], "feed_type": parsed["feed_type"],
                "feed_title": parsed["feed_title"],
                "guard_code": None, "source_url": fetched.get("final_url") or url}

    # -- 2 qadam: qoralama ---------------------------------------------------
    async def build_draft(self, item: FeedItem, *, user_id: int | None = None,
                          lang: str = "uz", db_module: Any = None,
                          channel_title: str = "", dna_block: str = "",
                          use_ai: bool = True) -> dict:
        """Element uchun post qoralamasi (AI + Channel DNA yoki digest).

        ``use_ai=False`` yoki AI muvaffaqiyatsiz bo'lsa — deterministik digest
        qaytadi (``ai_used=False``), ya'ni oqim hech qachon "jim qolmaydi".
        """
        base_text = digest_draft(item, lang=lang, channel_title=channel_title)
        if not use_ai:
            return {"text": sanitize_html(base_text, 3600), "ai_used": False,
                    "title": item.title}

        prompt = (
            "Quyidagi yangilik elementidan kanal uslubida qisqa Telegram post "
            "tayyorlang. Faqat berilgan faktlardan foydalaning, hech narsa "
            "o'ylab topmang. Javobda faqat tayyor post matni bo'lsin.\n\n"
            "Element sarlavhasi: " + clip(item.title, MAX_TITLE_CHARS) + "\n"
            "Element qisqacha mazmuni: " + clip(item.summary, 800) + "\n"
            "Havola: " + clip(item.canonical_url, 300)
        )
        ticket = await self.acquire_quota(db_module=db_module, user_id=user_id)
        if not ticket.allowed:
            return {"text": sanitize_html(base_text, 3600), "ai_used": False,
                    "title": item.title, "reason": ticket.reason,
                    "quota": ticket.as_dict()}
        outcome = await self.ask(
            prompt, user_id=user_id, lang=lang,
            context={"feature": self.feature, "system_prompt": dna_block,
                     "untrusted_source": True, "smm_mode": "RSS_DIGEST",
                     "smm_topic": clip(strip_markup(item.title), 120)},
        )
        if not outcome.ok:
            await self.release_quota(ticket)
            return {"text": sanitize_html(base_text, 3600), "ai_used": False,
                    "title": item.title, "quota": ticket.as_dict()}
        text = sanitize_html(outcome.text, 3600)
        return {"text": text or sanitize_html(base_text, 3600),
                "ai_used": bool(text), "title": item.title,
                "quota": ticket.as_dict(), "provider": outcome.provider}

    # -- 3 qadam: manbani to'liq tekshirish ---------------------------------
    async def check_source(self, source: dict, *, db_module: Any = None,
                           lang: str = "uz", client: Any = None, resolver=None,
                           dna_block: str = "", channel_title: str = "",
                           limit: int = MAX_ITEMS_PER_CHECK,
                           now: datetime | None = None,
                           use_ai: bool = True) -> dict:
        """Manbani tekshiradi: yangi elementlar → qoralamalar (+autopublish).

        Qaytadi::

            {"ok": True, "new": [...], "drafts": [...], "duplicates": 3,
             "source": {...}, "error_code": None, "checked_at": "..."}
        """
        db = db_module if db_module is not None else _import_database()
        data = dict(source or {})
        checked_at = now or datetime.now(timezone.utc)
        source_id = data.get("id")
        source_url = str(data.get("source_url") or "").strip()

        guard = ux.validate_public_url(source_url, resolver=resolver)
        if not guard.get("ok"):
            return {"ok": False, "error_code": guard.get("error_code"),
                    "new": [], "drafts": [], "duplicates": 0,
                    "message": guard.get("message")}

        loaded = self.load_feed(source_url, client=client, resolver=resolver)
        if not loaded.get("ok"):
            return {"ok": False, "error_code": loaded.get("error_code"),
                    "new": [], "drafts": [], "duplicates": 0,
                    "message": loaded.get("message")}

        known_ids: list[str] = []
        if db is not None and source_id is not None:
            try:
                known_ids = await _db_call(db, db.get_source_item_external_ids,
                                           source_id) or []
            except Exception:  # noqa: BLE001 — fail-soft: filtrsiz davom etamiz
                logger.warning("RSS: mavjud elementlar ro'yxatini o'qishda xato",
                               exc_info=True)
                known_ids = []

        all_items = list(loaded.get("items") or [])
        fresh = filter_new_items(all_items, known_ids)[:max(1, int(limit))]
        duplicates = max(0, len(all_items) - len(fresh))

        drafts: list[dict] = []
        saved_items: list[dict] = []
        for item in fresh:
            item_id = None
            if db is not None and source_id is not None:
                try:
                    item_id = await _db_call(
                        db, db.save_source_item, source_id, item.external_id,
                        item.canonical_url, item.title, item.summary)
                except Exception:  # noqa: BLE001
                    logger.warning("RSS: element saqlanmadi (%s)",
                                   item.external_id, exc_info=True)
                    item_id = None
                if not item_id:
                    # DB darajasidagi dublikat (UNIQUE) — qayta ishlanmaydi.
                    continue

            draft = await self.build_draft(
                item, user_id=data.get("user_id"), lang=lang, db_module=db,
                channel_title=channel_title, dna_block=dna_block,
                use_ai=use_ai)
            draft_payload = {
                "external_id": item.external_id,
                "source_item_id": item_id,
                "title": item.title,
                "url": item.canonical_url,
                "text": draft.get("text", ""),
                "ai_used": bool(draft.get("ai_used")),
            }
            draft_id = None
            if db is not None and item_id:
                try:
                    draft_id = await _db_call(
                        db, db.create_source_draft, source_id, item_id,
                        data.get("user_id"), data.get("channel_id"),
                        item.title, draft.get("text", ""),
                        bool(data.get("autopublish")))
                except Exception:  # noqa: BLE001
                    logger.warning("RSS: qoralama saqlanmadi (%s)",
                                   item.external_id, exc_info=True)
                    draft_id = None
                if item_id:
                    try:
                        await _db_call(db, db.mark_source_item_processed, item_id)
                    except Exception:  # noqa: BLE001
                        logger.debug("RSS: processed_at yangilanmadi", exc_info=True)
            draft_payload["draft_id"] = draft_id
            drafts.append(draft_payload)
            saved_items.append(item.as_dict())

        if db is not None and source_id is not None:
            try:
                await _db_call(db, db.touch_content_source, source_id, checked_at)
            except Exception:  # noqa: BLE001
                logger.debug("RSS: last_checked_at yangilanmadi", exc_info=True)

        return {
            "ok": True,
            "error_code": None if fresh else ERR_NO_ITEMS,
            "new": saved_items,
            "drafts": drafts,
            "duplicates": duplicates,
            "checked_at": checked_at.isoformat(),
            "source": data,
        }


# ---------------------------------------------------------------------------
# 4) SCHEDULER — vaqti kelgan manbalarni tekshirish
# ---------------------------------------------------------------------------
def _scheduled_time_for(source: dict, *, now: datetime | None = None) -> datetime:
    """Autopublish uchun rejalashtirish vaqti (best-time yoki standart)."""
    moment = now or datetime.now(tashkent_tz)
    if moment.tzinfo is None:
        moment = tashkent_tz.localize(moment)
    local = moment.astimezone(tashkent_tz)
    hour = AUTOPUBLISH_HOUR_FALLBACK
    try:
        hour = int((source or {}).get("post_hour") or AUTOPUBLISH_HOUR_FALLBACK)
    except (TypeError, ValueError):
        hour = AUTOPUBLISH_HOUR_FALLBACK
    hour = max(0, min(23, hour))
    candidate = tashkent_tz.localize(
        datetime(local.year, local.month, local.day, hour, 0, 0))
    if candidate <= local:
        candidate = candidate + timedelta(days=1)
    return candidate


async def poll_due_sources(db_module: Any = None, *, now: datetime | None = None,
                           client: Any = None, resolver=None,
                           limit: int = MAX_SOURCES_PER_TICK,
                           notifier: Callable | None = None,
                           schedule_post: Callable | None = None,
                           service: RssService | None = None) -> dict:
    """Vaqti kelgan BARCHA manbalarni tekshiradi (scheduler tick'i).

    ``notifier`` — ixtiyoriy async callback: ``(user_id, source, drafts)``.
    ``schedule_post`` — ixtiyoriy async callback: ``(source, draft)`` (navbatga
    yozish). Ikkalasi ham fail-soft: xatolar tick'ni to'xtatmaydi.
    """
    db = db_module if db_module is not None else _import_database()
    summary = {"checked": 0, "drafts": 0, "errors": 0, "scheduled": 0}
    if db is None or not hasattr(db, "get_due_content_sources"):
        return summary
    try:
        sources = await _db_call(db, db.get_due_content_sources, now, int(limit))
    except Exception:  # noqa: BLE001
        logger.exception("RSS poll: manbalar ro'yxatini olishda xato")
        return summary

    svc = service or RssService()
    for source in sources or []:
        data = dict(source or {})
        summary["checked"] += 1
        try:
            lang = str(data.get("lang") or "uz")
            dna_block = str(data.get("dna_block") or "")
            result = await svc.check_source(
                data, db_module=db, lang=lang, client=client, resolver=resolver,
                dna_block=dna_block, channel_title=str(data.get("channel_title") or ""))
        except Exception:  # noqa: BLE001
            logger.exception("RSS poll: manba xatosi (id=%s)", data.get("id"))
            summary["errors"] += 1
            continue

        if not result.get("ok"):
            summary["errors"] += 1
            continue

        drafts = list(result.get("drafts") or [])
        summary["drafts"] += len(drafts)
        if data.get("autopublish") and drafts and callable(schedule_post):
            for draft in drafts:
                try:
                    ok = await schedule_post(data, draft)
                    if ok:
                        summary["scheduled"] += 1
                except Exception:  # noqa: BLE001
                    logger.exception("RSS poll: navbatga yozishda xato (id=%s)",
                                     data.get("id"))
        if drafts and callable(notifier):
            try:
                await notifier(data.get("user_id"), data, drafts)
            except Exception:  # noqa: BLE001
                logger.debug("RSS poll: bildirishnoma yuborilmadi", exc_info=True)
    return summary


async def autopublish_draft(db_module: Any, source: dict, draft: dict,
                            *, hour: int | None = None,
                            now: datetime | None = None) -> int:
    """Qoralamani reja navbatiga (``scheduled_posts``) yozadi.

    Qaytadi: post id (0 — xato). ``add_post`` (testdan o'tgan yagona
    yozish nuqtasi, atomik ``user_post_number`` bilan) ishlatiladi.
    """
    db = db_module if db_module is not None else _import_database()
    if db is None or not hasattr(db, "add_post"):
        return 0
    text = str((draft or {}).get("text") or "").strip()
    channel_id = str((source or {}).get("channel_id") or "").strip()
    user_id = (source or {}).get("user_id")
    if not text or not channel_id or not user_id:
        return 0
    payload = dict(source or {})
    payload["post_hour"] = hour if hour is not None else payload.get("post_hour")
    moment = _scheduled_time_for(payload, now=now)
    try:
        post_id = await _db_call(
            db, db.add_post,
            user_id=int(user_id), channel_id=channel_id, post_type="text",
            content=text, file_id=None, scheduled_time=moment)
    except Exception:  # noqa: BLE001
        logger.exception("RSS: autopublish xatosi (source=%s)", source.get("id"))
        return 0
    draft_id = (draft or {}).get("draft_id")
    if post_id and draft_id and hasattr(db, "set_source_draft_status"):
        try:
            await _db_call(db, db.set_source_draft_status, draft_id,
                           int(user_id), "queued", int(post_id))
        except Exception:  # noqa: BLE001
            logger.debug("RSS: qoralama statusi yangilanmadi", exc_info=True)
    return int(post_id or 0)


__all__ = [
    "FeedItem", "DEFAULT_INTERVAL_MINUTES", "MIN_INTERVAL_MINUTES",
    "MAX_INTERVAL_MINUTES", "MAX_ITEMS_PER_CHECK", "MAX_SOURCES_PER_TICK",
    "ERR_INVALID_URL", "ERR_FETCH_FAILED", "ERR_PARSE_FAILED",
    "ERR_NO_ITEMS", "ERR_DUPLICATE", "ERR_DRAFT_FAILED",
    "strip_markup", "sanitize_xml", "canonical_url", "item_external_id",
    "parse_feed", "filter_new_items", "clamp_interval", "parse_interval_input",
    "as_utc", "next_check_at", "is_source_due", "digest_draft",
    "RssService", "poll_due_sources", "autopublish_draft",
]
