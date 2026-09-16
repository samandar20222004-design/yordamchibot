"""Advanced SMM xizmatlari uchun YAGONA poydevor (PHASE 11 & 12).

``variants.py`` (48-band), ``repurpose.py`` (49-band), ``audit.py`` (33/50-band)
va ``planner.py`` (51-band) shu modulga taylanadi — to'rt xizmat ham bir xil
kontrakt bo'yachi ishlaydi:

1. **AIOrchestrator (Phase 3)** — barcha AI chaqiruvlari ``orchestrate()``
   orqali: Intent Router → Provider Chain (Gemini → Groq → OpenRouter →
   **MockProvider**) → AIOutputValidator → 1 martalik controlled retry →
   HTML sanitizatsiya → fail-closed refund. Provider zanjiri o'zgarmaydi,
   shuning uchun API kalitsiz muhitda (mock) ham 100% ishlaydi.

2. **Kvota/kredit (Phase 2, atomik)** — har bir *batch operatsiya* (5 variant,
   5 platforma, audit, 30 kunlik reja) uchun AYNAN BITTA
   ``services.ai_quota.reserve_ai_quota()`` bron qilinadi. Ichimaki AI
   chaqiruvlari ``skip_quota`` bilan o'tadi — chunki to'lov allaqachon
   bronlangan. Xatoda bron ``release_ai_quota()`` bilan qaytariladi
   (idempotent). Eski xato endi-endi «har bir variantga 1 kredit» emas.

3. **Sanitizatsiya (Phase 2)** — foydalanuvchiga chiqadigan HAR QANDAY matn
   ``utils.telegram_sanitizer.sanitize_html()`` dan o'tadi va Telegram
   4096-belgi chegarasiga bo'laklanadi (chunk). Model javobi — shu jumladan
   JSON ichidagi matnlar ham — hech qachon xom holicha chiqmaydi.

4. **Deterministik karkas** — model javobi istalgan darajada buzuq bo'lsin,
   natija HECH QACHON yiqilmaydi: har bir xizmat o'z tuzilmasini (5 variant,
   5 platforma, 6 mezon, N kun) lokal hisoblagich bilan kafolatlaydi, AI
   faqat shu karkasni BOYITADI (merge). Buni ``handlers/content_calendar``
   dagi ``normalize_items`` falsafasining SMM versiyasi deb o'qing.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable

logger = logging.getLogger(__name__)

#: Telegram text message qat'iy chegarasi (decoded UTF-16 birliklari).
TELEGRAM_TEXT_LIMIT = 4096

#: Xavfsiz chunk hajmi: <blockquote>/<b> teglari va bo'laklar orasidagi
#: \n hisobiga zaxira.
CHUNK_SAFE_LIMIT = 3900

#: Qo'llab-quvvatlanadigan tillar (repo standarti: UZ/RU/EN pariteti).
SUPPORTED_LANGS = ("uz", "ru", "en")
DEFAULT_LANG = "uz"

# ---------------------------------------------------------------------------
# REGEXLAR (sof stdlib — tashqi kutubxona YO'Q)
# ---------------------------------------------------------------------------
_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>\n]{1,200}>")
_WS_RE = re.compile(r"[ \t\u00a0\u200b]+")
_HASHTAG_RE = re.compile(r"(?<![\w&])#[A-Za-zА-Яа-яЁёЎўҚҲҒӮӰ_0-9]{2,60}")
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+|\n+")
_BULLET_RE = re.compile(r"^\s*(?:[-•*✔✅🔹▪️]|\d+[.)])\s+")
_DANGER_RE = re.compile(r"<\s*(?:script|iframe|object|embed|link|style)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# TIL / MATN YORDAMCHILARI
# ---------------------------------------------------------------------------
def normalize_lang(lang: Any) -> str:
    """'UZ'/'uz-UZ'/'ru'/'English' → 'uz'|'ru'|'en' (noma'lum → 'uz')."""
    code = str(lang or "").strip().lower().replace("_", "-")
    if not code:
        return DEFAULT_LANG
    base = code.split("-", 1)[0]
    if base in SUPPORTED_LANGS:
        return base
    if base.startswith("eng"):
        return "en"
    if base.startswith("rus"):
        return "ru"
    if base.startswith("uzb"):
        return "uz"
    return DEFAULT_LANG


def lang_text(table: dict | None, lang: Any, default: str = "") -> str:
    """Til bo'yicha lug'atdan matn olish (yo'q bo'lsa — 'uz', keyin default)."""
    if not isinstance(table, dict):
        return default
    code = normalize_lang(lang)
    for key in (code, DEFAULT_LANG):
        value = table.get(key)
        if isinstance(value, str) and value:
            return value
    return default


def clip(text: Any, limit: int) -> str:
    """Matnni uzunligi bo'yicha qisqartirish (hech qachon istisno bermaydi)."""
    value = str(text if text is not None else "").strip()
    if limit <= 0:
        return ""
    return value if len(value) <= limit else value[: max(0, limit - 1)].rstrip() + "…"


def strip_html(text: Any) -> str:
    """HTML teglarini olib tashlab, o'qiladigan tekis matn qaytarish."""
    value = str(text if text is not None else "")
    value = value.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    value = _HTML_TAG_RE.sub(" ", value)
    value = (value.replace("&nbsp;", " ").replace("&amp;", "&")
             .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
             .replace("&#39;", "'"))
    return _WS_RE.sub(" ", value).strip()


def plain_sentences(text: Any, min_len: int = 18, max_items: int = 12) -> list[str]:
    """Matndan mazmuniy jumlalarni ajratib oladi (bullet/bo'sh qatorlarsiz)."""
    out: list[str] = []
    for raw in _SENTENCE_RE.split(strip_html(text)):
        item = _WS_RE.sub(" ", raw or "").strip()
        item = _BULLET_RE.sub("", item).strip()
        item = item.strip(" \t-•*·|—:")
        if len(item) < min_len:
            continue
        if item.lower().startswith(("http://", "https://", "t.me/")):
            continue
        out.append(clip(item, 320))
        if len(out) >= max_items:
            break
    return out


def word_count(text: Any) -> int:
    return len(re.findall(r"[\w']+|[А-Яа-яЁёЎўҚҲҒ]+", strip_html(text)))


def has_dangerous_markup(text: Any) -> bool:
    """Model javobida xavfli teg/qoldig'i bormi (sanitizerdan tashqari cheklov)."""
    return bool(_DANGER_RE.search(str(text or "")))


def strip_hashtags(text: Any) -> str:
    """Hashtaglarni olib tashlash (platforma formatlari ularni alohida blokda chizadi)."""
    return _WS_RE.sub(" ", _HASHTAG_RE.sub(" ", str(text or ""))).strip()


def fingerprint(text: Any) -> str:
    """Variantlar/qatorlar O'XSHASHLIGINI aniqlash uchun normalallashtirilgan iz.

    HTML, emoji, punktatsiya va registga beparvo; faqat so'zlarning tartiblangan
    emas, LEKIN takrorlanishni saqlab qoluvchi oqimi solishtiriladi. Shu sababli
    «ayni so'zma-so'z sinonimi bo'lgan» 2 variant aniqlanadi, turli burchakli
    (angle) 2 variant emas.
    """
    words = re.findall(r"[\w']+", strip_html(text).lower())
    return " ".join(words)


def same_content(left: Any, right: Any, threshold: float = 0.86) -> bool:
    """Ikki matn mazmunan bir xilmi (so'z to'plami Jaccard o'xshashligi)."""
    a = set(re.findall(r"[\w']+", strip_html(left).lower()))
    b = set(re.findall(r"[\w']+", strip_html(right).lower()))
    if not a or not b:
        return bool(a) == bool(b)
    union = len(a | b)
    return union and (len(a & b) / union) >= threshold


def extract_hashtags(text: Any) -> list[str]:
    tags: list[str] = []
    for tag in _HASHTAG_RE.findall(str(text or "")):
        clean = tag if tag.startswith("#") else f"#{tag}"
        if clean.lower() not in [t.lower() for t in tags]:
            tags.append(clean)
    return tags


def ensure_hashtags(text: Any, bank: Iterable[str], minimum: int = 3,
                    maximum: int = 5) -> str:
    """Postda kamida ``minimum`` ta hashtag bo'lishini kafolatlaydi."""
    body = str(text or "").strip()
    found = extract_hashtags(body)
    if len(found) >= minimum:
        return body
    for tag in bank:
        clean = tag if tag.startswith("#") else f"#{tag}"
        if clean.lower() not in [t.lower() for t in found]:
            found.append(clean)
        if len(found) >= max(minimum, 3):
            break
    line = " ".join(found[:maximum])
    without = _HASHTAG_RE.sub("", body).strip()
    return f"{without}\n\n{line}" if line else without


def bold(text: Any) -> str:
    """Xavfsiz <b> — ichidagi matn qo'lda escape qilinmaydi (chaqiruvchi
    tomonidan allaqachon sanitize/escape qilingan fragment deb qaraladi)."""
    return f"<b>{str(text or '').strip()}</b>"


def escape_literal(text: Any) -> str:
    """MODEL yoki FOYDALANUVCHI matnini HTML ichiga qo'yishdan oldin escape qilish.

    Faqat ``& < >`` escape qilinadi (``quote=False``) — Telegram matn
    kontektida apostrof va tirnoqlarni ``&#x27;`` ko'rinishiga
    aylantirish shart emas, aksincha o'qishni yomonlashtiradi va
    4096 hisoblagichni shishiradi. Attribute'larga hech narsa
    qo'ymaymiz (havolalar faqat sanitizer o'tkazgan holda chiqadi).
    """
    from html import escape
    return escape(str(text if text is not None else ""), quote=False)


# ---------------------------------------------------------------------------
# SANITIZATSIYA VA CHUNK
# ---------------------------------------------------------------------------
def sanitize_html(text: Any, max_length: int = TELEGRAM_TEXT_LIMIT) -> str:
    """Phase 2 sanitizeriga yagona kirish nuqtasi (fallback bilan).

    Hech qachon istisno ko'tarmaydi: sanitizer sharoiti bo'lmasa minimal
    xavfsizlantirish (escape + truncate) qo'llanadi.
    """
    try:
        from utils.telegram_sanitizer import sanitize_html as _sanitize
        return _sanitize(str(text if text is not None else ""), max_length)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("sanitize_html fallback ishlatildi: %s", exc)
        from html import escape
        safe = escape(strip_html(text), quote=False)
        return safe[: max(0, int(max_length))] if max_length and max_length > 0 else safe


def html_length(text: Any) -> int:
    """Telegram hisoblagichi: o'qiladigan matn UTF-16 birliklarida."""
    try:
        from utils.telegram_sanitizer import html_length as _length
        return _length(str(text or ""))
    except Exception:  # pragma: no cover - fallback
        plain = strip_html(text)
        return sum(2 if ord(c) > 0xFFFF else 1 for c in plain)


def chunk_blocks(blocks: Iterable[str], limit: int = CHUNK_SAFE_LIMIT) -> list[str]:
    """Tayyor HTML bloklarni Telegram xabarlariga bo'laklaydi.

    Blok — atomic (bo'linmaydi). Agar bitta blok limitdan oshib ketsa, u
    paragraf (\\n\\n) chegaralarida, keyin esa qat'iy kesish bilan bo'linadi,
    shunda HAR BIR xabar 4096 belgidan oshmaydi.
    """
    limit = max(64, int(limit))
    chunks: list[str] = []
    current = ""
    for raw in blocks:
        piece = str(raw or "").strip()
        if not piece:
            continue
        while html_length(piece) > limit:
            head = _cut_at_paragraph(piece, limit) or piece[:limit].strip()
            if not head:
                # Muhofaza: agar hech narsa «yeyilmasa» — bitta belgi ham
                # bo'lsa ajratamiz (cheeksiz sikl bo'lmasligi uchun).
                head = piece[:1]
            _push(chunks, head, limit)
            remainder = piece[len(head):].strip()
            if len(remainder) >= len(piece):
                break
            piece = remainder
        if not piece:
            continue
        candidate = f"{current}\n\n{piece}" if current else piece
        if current and html_length(candidate) > limit:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _push(chunks: list[str], piece: str, limit: int) -> None:
    if chunks and html_length(f"{chunks[-1]}\n\n{piece}") <= limit:
        chunks[-1] = f"{chunks[-1]}\n\n{piece}"
    else:
        chunks.append(piece)


def _cut_at_paragraph(piece: str, limit: int) -> str:
    """Blokni paragraf chegarasida, bo'lmasa simvol chegarasida kesadi."""
    head = piece[:limit]
    idx = head.rfind("\n\n")
    if idx >= limit // 2:
        return piece[:idx].strip()
    idx = head.rfind("\n")
    if idx >= limit // 2:
        return piece[:idx].strip()
    return head.strip()


# ---------------------------------------------------------------------------
# JSON KONTRAKTI (model javobi — ishonchsiz)
# ---------------------------------------------------------------------------
def extract_json(text: Any) -> dict | None:
    """Model javobidagi BIRINCHI JSON ob'ektini xavfsiz o'qish.

    Markdown ```json to'siqlari, oldidagi/ortidagi izohlar va tugallanmagan
    (sanitizatsiya/truncation tufayli) JSON bilan ham yiqilmaydi — ``None``
    qaytaradi va chaqiruvchi deterministik yo'lga tushadi.
    """
    raw = _JSON_FENCE_RE.sub("", str(text or "").strip())
    if not raw:
        return None
    for candidate in (raw, raw[: raw.rfind("}") + 1] if "}" in raw else ""):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except Exception:
            match = _JSON_OBJECT_RE.search(candidate)
            if not match:
                continue
            try:
                data = json.loads(match.group(0))
            except Exception:
                continue
        if isinstance(data, dict):
            return data
    return None


def json_list(data: dict | None, *keys: str) -> list:
    """JSON ob'ektidan ro'yxat maydonini olish (noto'g'ri shaklda bo'sh ro'yxat)."""
    if not isinstance(data, dict):
        return []
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if item is not None]
    return []


def text_list(values: Iterable[Any], limit_each: int = 240, max_items: int = 6) -> list[str]:
    """Ishonchsiz ro'yxatdan toza, chegaralangan, takrorlanmas satrlar."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values if isinstance(values, (list, tuple, set)) else []:
        if isinstance(value, dict):
            value = (value.get("text") or value.get("value") or value.get("note")
                     or value.get("fix") or value.get("topic") or "")
        item = clip(strip_html(value), limit_each)
        if len(item) < 8:
            continue
        key = unicodedata.normalize("NFKC", item).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= max_items:
            break
    return out


def coerce_int(value: Any, default: int, lo: int, hi: int) -> int:
    """1-10 / 0-100 kabi chegarali butun son (matn, "8/10", 8.6 → int)."""
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:[.,]\d+)?", value)
        value = match.group(0).replace(",", ".") if match else None
    try:
        number = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number))


# ---------------------------------------------------------------------------
# KVOTA BILETI (Phase 2 atomik bron — yagona standart)
# ---------------------------------------------------------------------------
@dataclass
class QuotaTicket:
    """Bitta batch operatsiya uchun atomik bron natijasi."""

    allowed: bool = False
    skipped: bool = False
    reservation_id: int | None = None
    source: str | None = None
    cost: int = 0
    legacy: bool = False
    reason: str | None = None
    used: int = 0
    max_ai: int = 0
    credits_left: int | None = None
    user_id: int | None = None
    db_module: Any = None
    raw: dict = field(default_factory=dict)

    @property
    def active(self) -> bool:
        """Qaytarilishi KERAK bo'lgan real bron bormi."""
        return bool(self.allowed and not self.skipped)

    def as_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "skipped": self.skipped,
            "reservation_id": self.reservation_id,
            "source": self.source,
            "cost": self.cost,
            "legacy": self.legacy,
            "reason": self.reason,
            "used": self.used,
            "max_ai": self.max_ai,
            "credits_left": self.credits_left,
        }


# ---------------------------------------------------------------------------
# AI JAVOB NATIJASI
# ---------------------------------------------------------------------------
@dataclass
class AskOutcome:
    """Bitta AIOrchestrator chaqiruvi natijasi (xavfsiz, soddalashtirilgan)."""

    ok: bool = False
    text: str = ""
    raw: str = ""
    provider: str = "none"
    retried: bool = False
    intent: str = "UNKNOWN"
    error: str | None = None
    error_code: str | None = None
    generation_id: str | None = None

    @property
    def usable(self) -> bool:
        return bool(self.ok and len(strip_html(self.text)) >= 20)


# ---------------------------------------------------------------------------
# XIZMAT BAZASI
# ---------------------------------------------------------------------------
_orchestrator_singleton: Any = None


def get_default_orchestrator():
    """Lazy global AIOrchestrator (Phase 3) — testlar uni almashtira oladi."""
    global _orchestrator_singleton
    if _orchestrator_singleton is None:
        from .orchestrator import AIOrchestrator
        _orchestrator_singleton = AIOrchestrator()
    return _orchestrator_singleton


def set_default_orchestrator(orchestrator) -> None:
    """Test/injector uchun (``None`` → keyingi chaqiruvda qayta quriladi)."""
    global _orchestrator_singleton
    _orchestrator_singleton = orchestrator


class SMMFeatureService:
    """Advanced SMM xizmatlarining umumiy oqimi (base class).

    Sub-klasslar faqat ``feature`` / ``quota_operation`` ni belgilaydi va o'z
    mantiqini yozadi — kvota, sanitizatsiya, chunk va AI chaqiruvi yagona
    standartda shu yerda turadi.
    """

    #: Loggingleydigan qisqa nom (tests/monitoring uchun).
    feature: str = "smm"
    #: ``database.AI_OPERATION_TYPES`` ichidagi asos; ``base:tag`` ko'rinishida
    #: yoziladi (masalan ``magic_post:variants``) — whitelist asosni tekshiradi.
    quota_operation: str = "other"
    #: Butun batch uchun yechiladigan bron narxi (standart: 1).
    quota_cost: int = 1

    def __init__(self, orchestrator: Any = None):
        self._injected_orchestrator = orchestrator

    # -- orchestrator ------------------------------------------------------
    @property
    def orchestrator(self):
        return self._injected_orchestrator or get_default_orchestrator()

    # -- kvota (Phase 2 atomik) -------------------------------------------
    async def acquire_quota(self, db_module: Any = None, user_id: int | None = None,
                            cost: int | None = None) -> QuotaTicket:
        """Batch uchun BITTA atomik bron. ``db_module`` yo'q bo'lsa — skip.

        Fail-closed: bron xatosida yoki rad etilganida natija
        ``allowed=False`` va chaqiruvchi AI'ga umuman chiqmaydi.
        """
        cost_value = int(cost or self.quota_cost)
        skip = db_module is None or db_module is False
        if skip or not user_id or int(user_id) <= 0:
            return QuotaTicket(allowed=True, skipped=True, cost=0,
                               reason="quota_skipped", user_id=user_id,
                               db_module=db_module if not skip else None)
        try:
            from services.ai_quota import reserve_ai_quota
            result = await reserve_ai_quota(db_module, int(user_id),
                                            self.quota_operation, cost_value)
        except Exception as exc:  # noqa: BLE001 — FAIL-CLOSED
            logger.error("%s: kvota bron xatosi (user=%s): %s", self.feature, user_id, exc)
            return QuotaTicket(allowed=False, reason="db_error", cost=cost_value,
                               user_id=user_id, db_module=db_module)
        result = result if isinstance(result, dict) else {}
        ticket = QuotaTicket(
            allowed=bool(result.get("allowed")),
            reservation_id=result.get("reservation_id"),
            source=result.get("source"),
            cost=int(result.get("cost") or cost_value),
            legacy=bool(result.get("legacy")),
            reason=result.get("reason"),
            used=int(result.get("used") or 0),
            max_ai=int(result.get("max_ai") or 0),
            credits_left=result.get("credits_left"),
            user_id=int(user_id),
            db_module=db_module,
            raw=result,
        )
        return ticket

    async def release_quota(self, ticket: QuotaTicket | None) -> bool:
        """Bronni fail-closed qaytarish (idempotent — ikkinchi marta qaytarilmaydi)."""
        if ticket is None or not ticket.active:
            return False
        if ticket.db_module is None or ticket.user_id is None:
            return False
        try:
            from services.ai_quota import release_ai_quota
            ok = bool(await release_ai_quota(ticket.db_module, ticket.user_id,
                                             ticket.reservation_id))
            if ok:
                # Ikkinchi qaytarishning oldini olamiz.
                ticket.allowed = False
            return ok
        except Exception as exc:  # noqa: BLE001
            logger.error("%s: kvota qaytarishda xato: %s", self.feature, exc)
            return False

    # -- AI chaqiruvi (Phase 3 orchestrator) --------------------------------
    async def ask(self, prompt: str, *, user_id: int | None, lang: str = DEFAULT_LANG,
                  context: dict | None = None, db_module: Any = False,
                  force_quota: bool = False) -> AskOutcome:
        """AIOrchestrator orqali bitta xavfsiz generatsiya.

        Standart holatda ``db_module=False`` + ``skip_quota`` — chunki batch
        uchun bron ``acquire_quota()`` da ALLAQACHON olingan (2 qadamli
        «har bir chaqiruvga kredit» xatosiga yo'l qo'yilmaydi).
        ``force_quota=True`` bo'lsa so'rov o'zi ham Phase 2 atomik bronidan
        o'tadi (mustaqil chaqiruv rejimi).
        """
        ctx: dict[str, Any] = dict(context or {})
        ctx.setdefault("lang", normalize_lang(lang))
        if not force_quota:
            ctx.setdefault("skip_quota", True)

        orchestrator = self.orchestrator
        try:
            result = await orchestrator.orchestrate(
                user_id=int(user_id or 0),
                prompt=str(prompt or ""),
                lang=normalize_lang(lang),
                context=ctx,
                db_module=db_module if force_quota else False,
            )
        except Exception as exc:  # noqa: BLE001 — xizmat hech qachon yiqilmaydi
            logger.error("%s: orchestrator xatosi: %s", self.feature, exc)
            return AskOutcome(ok=False, error=str(exc), error_code="ORCHESTRATOR_ERROR")

        if result is None:
            return AskOutcome(ok=False, error="empty_result", error_code="EMPTY_RESULT")

        success = bool(getattr(result, "success", False))
        content = str(getattr(result, "content", "") or "")
        if success and len(strip_html(content)) < 20:
            success = False
        return AskOutcome(
            ok=success,
            text=content if success else "",
            raw=str(getattr(result, "raw_content", "") or content),
            provider=str(getattr(result, "provider_used", "none") or "none"),
            retried=bool(getattr(result, "retried", False)),
            intent=str(getattr(result, "intent", "") or ""),
            error=getattr(result, "error", None),
            error_code=getattr(result, "error_code", None),
            generation_id=getattr(result, "generation_id", None),
        )

    # -- chiqish -----------------------------------------------------------
    def render(self, blocks: Iterable[str], *, limit: int = CHUNK_SAFE_LIMIT) -> list[str]:
        """Bloklarni sanitize + chunk qilib, yuborishga TAYYOR xabarlar.

        Ikki bosqichli sanitizer sababi: katta blok chunk'ga bo'linganda
        ``<b>`` bitta xabarda ochilib, ikkinchisida yopilishi mumkin —
        Telegram «can't parse entities» beradi. Shuning uchun HAR BIR
        chunk qayta sanitate qilinadi: ochiq teglar shu xabar ichida
        yopiladi, beteg qoldiqlari esa escape qilinadi.
        """
        safe = [sanitize_html(block, TELEGRAM_TEXT_LIMIT) for block in blocks if block]
        pieces = chunk_blocks([item for item in safe if item.strip()], limit=limit)
        return [sanitize_html(piece, TELEGRAM_TEXT_LIMIT) for piece in pieces]

    # -- logging -----------------------------------------------------------
    def _log(self, message: str, *args) -> None:
        try:
            logger.info(f"[smm:{self.feature}] {message}", *args)
        except Exception:  # pragma: no cover
            pass


def result_payload(result: Any) -> dict:
    """Dataclass natijasini JSON-lug'atga aylantirish (handler/API uchun)."""
    if hasattr(result, "as_dict"):
        try:
            return result.as_dict()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("as_dict xatosi: %s", exc)
    if isinstance(result, dict):
        return result
    return {"success": bool(getattr(result, "success", False))}
