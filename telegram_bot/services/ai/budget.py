# -*- coding: utf-8 -*-
"""💳 AI BYUDJET — FREE va PRO tarif uchun kunlik/oylik token + USD limiti.

Nega kerak
----------
Kvota (so'rov soni) bilan birga AI XARAJATINI ham cheklash kerak: bitta uzun
so'rov yoki katta model bepul kvotani "arzon" qilib qo'yadi. Shu sababli har
tarif uchun TO'RT cheklov:

* ``daily_tokens`` / ``monthly_tokens`` — token hajmi (narxdan mustaqil);
* ``daily_usd`` / ``monthly_usd`` — taxminiy xarajat (USD, narx jadvali bo'yicha).

PRO oylik USD limiti standart holatda PRO narxining (``PAYMENT_PRICE_1M_UZS``,
19 000 so'm) ``AI_BUDGET_PRO_MAX_COST_SHARE`` (standart 40%) ulushi —
ya'ni AI xarajati PRO daromadining katta qismini yemasligi uchun.

Qat'iylik (atomiklik)
---------------------
Bitta so'rov chaqirilishidan OLDIN ``acquire`` — joriy sarf (ledger / DB) +
hozir ketayotgan (in-flight) bron + bu so'rovning TAXMINI hajmi limitdan
oshmasligi tekshiriladi va bron darhol yoziladi (tekshiruv va yozuv bitta
qulf ichida). Javob tugagach ``release`` bronni bo'shatadi; haqiqiy sarf
telemetriya orqali ledger'ga yoziladi. Xato bo'lsa ham bron bo'shatiladi
(refund) — foydalanuvchi byudjeti yonib ketmaydi.

Narxi noma'lum (``priced=False``) muvaffaqiyatli so'rovlar
-----------------------------------------------------------
Ular ``cost_usd = 0`` bilan yoziladi (soxta narx yo'q), lekin USD limitidan
chetda qolmasligi uchun budjet alohida ``assumed_usd`` yuritadi: mos yozuv
narxi (``cost_tracker.ASSUMED_PRICE_*``) × tokenlar. U haqiqiy sarf EMAS va
``estimated_cost`` / ``priced`` ga yozilmaydi. Xato, timeout, kesh va rad
etilgan so'rovlarga taxmin qo'shilmaydi. Fallback zanjirida yakuniy natijadan
oldingi muvaffaqiyatsiz provayder urinishlari hozir umuman hisoblanmaydi.

Limit ``0`` yoki manfiy bo'lsa — shu metrika bo'yicha cheklov YO'Q.
Byudjet xatosi (DB uzilishi) AI'ni to'xtatmaydi: DB'siz faqat jarayon
xotirasidagi ledger ishlatiladi (fail-soft, lekin xarajat har doim yoziladi).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

TIER_FREE = "free"
TIER_PRO = "pro"
TIERS: tuple[str, ...] = (TIER_FREE, TIER_PRO)

#: Byudjet tekshiruvi uchun DB so'rovi kutish chegarasi (soniya).
DB_SNAPSHOT_TIMEOUT = 1.5

#: Taxminiy narx uchun ma'lumotnoma model (bron bahosi; haqiqiy narx — telemetriya).
REFERENCE_PRICE_PROVIDER = "Gemini"
REFERENCE_PRICE_MODEL = "gemini-2.5-flash"

PERIOD_DAILY = "daily"
PERIOD_MONTHLY = "monthly"


# ---------------------------------------------------------------------------
# Tarif limitlari
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TierBudget:
    """Bitta tarifning kunlik/oylik limitlari (0 → cheklov yo'q)."""

    tier: str
    daily_tokens: int
    daily_usd: float
    monthly_tokens: int
    monthly_usd: float

    def as_dict(self) -> dict:
        return {
            "tier": self.tier,
            "daily_tokens": self.daily_tokens,
            "daily_usd": self.daily_usd,
            "monthly_tokens": self.monthly_tokens,
            "monthly_usd": self.monthly_usd,
        }


def _int_env(raw: str | None, default: int) -> int:
    try:
        return int(str(raw).strip()) if raw not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _float_env(raw: str | None, default: float) -> float:
    try:
        return float(str(raw).strip()) if raw not in (None, "") else default
    except (TypeError, ValueError):
        return default


def pro_monthly_usd_default() -> float:
    """PRO oylik AI xarajat limiti (USD) — PRO narxi × ulush (env bo'lmasa)."""
    try:
        from services.ai import cost_tracker

        price_usd = cost_tracker.uzs_to_usd(cost_tracker._pro_price_uzs())
    except Exception:  # noqa: BLE001 — konfiguratsiya xatosi AI'ni to'xtatmasin
        price_usd = 19000 / 12600.0
    share = _float_env(os.getenv("AI_BUDGET_PRO_MAX_COST_SHARE"), 0.40)
    return round(price_usd * max(0.0, share), 4)


def tier_budget(tier: str | None) -> TierBudget:
    """Tarif uchun joriy limitlar (env har chaqiruvda o'qiladi — runtime o'zgaradi).

    Noma'lum tarif → FREE (eng qat'iy, xarajat xavfsizligi uchun).
    """
    if str(tier or "").lower() == TIER_PRO:
        monthly_usd_raw = os.getenv("AI_BUDGET_PRO_MONTHLY_USD")
        return TierBudget(
            tier=TIER_PRO,
            daily_tokens=_int_env(os.getenv("AI_BUDGET_PRO_DAILY_TOKENS"), 300_000),
            daily_usd=_float_env(os.getenv("AI_BUDGET_PRO_DAILY_USD"), 0.10),
            monthly_tokens=_int_env(os.getenv("AI_BUDGET_PRO_MONTHLY_TOKENS"), 3_000_000),
            monthly_usd=(_float_env(monthly_usd_raw, 0.0) if monthly_usd_raw not in (None, "")
                         else pro_monthly_usd_default()),
        )
    return TierBudget(
        tier=TIER_FREE,
        daily_tokens=_int_env(os.getenv("AI_BUDGET_FREE_DAILY_TOKENS"), 50_000),
        daily_usd=_float_env(os.getenv("AI_BUDGET_FREE_DAILY_USD"), 0.02),
        monthly_tokens=_int_env(os.getenv("AI_BUDGET_FREE_MONTHLY_TOKENS"), 500_000),
        monthly_usd=_float_env(os.getenv("AI_BUDGET_FREE_MONTHLY_USD"), 0.15),
    )


def reserve_output_tokens() -> int:
    """Bron uchun taxminiy chiqish tokenlari (standart 1024)."""
    return max(0, _int_env(os.getenv("AI_BUDGET_RESERVE_OUTPUT_TOKENS"), 1024))


def estimate_request(prompt: str = "", system_instruction: str = "") -> tuple[int, float]:
    """So'rov uchun taxminiy ``(tokens, usd)`` — bron bahosi (qat'iy emas)."""
    from services.ai.engine.telemetry import estimate_cost, estimate_tokens

    in_tokens = estimate_tokens(prompt) + estimate_tokens(system_instruction)
    out_tokens = reserve_output_tokens()
    usd = estimate_cost(REFERENCE_PRICE_PROVIDER, REFERENCE_PRICE_MODEL,
                        in_tokens, out_tokens)
    return in_tokens + out_tokens, usd


# ---------------------------------------------------------------------------
# Tarif aniqlash (FREE / PRO)
# ---------------------------------------------------------------------------
def _is_premium_sync(user_id: int) -> bool:
    """DB orqali PRO holati (baza yo'q bo'lsa — FREE)."""
    if not _db_ready():
        return False
    return bool(sys.modules["database"].is_premium(int(user_id)))


_tier_resolver = _is_premium_sync


def set_tier_resolver(fn) -> None:
    """Testlar / ops uchun tarif aniqlovchi funksiyani almashtiradi."""
    global _tier_resolver
    _tier_resolver = fn or _is_premium_sync


async def resolve_tier(user_id, is_pro: bool = False) -> str:
    """``is_pro=True`` → PRO; aks holda DB'dan. Xato → FREE (fail-closed)."""
    if is_pro:
        return TIER_PRO
    if user_id is None:
        return TIER_FREE
    try:
        premium = await asyncio.wait_for(
            asyncio.to_thread(_tier_resolver, int(user_id)), DB_SNAPSHOT_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — tarif aniqlanmasa FREE limit
        logger.debug("budget: tarif aniqlanmadi (user=%s): %s", user_id, exc)
        return TIER_FREE
    return TIER_PRO if premium else TIER_FREE


# ---------------------------------------------------------------------------
# Joriy sarf (committed) — jarayon ledger + DB agregati
# ---------------------------------------------------------------------------
@dataclass
class Usage:
    tokens: int = 0
    usd: float = 0.0
    #: Narxi noma'lum muvaffaqiyatli so'rovlar uchun FAQAT budjet taxmini (USD).
    #: ``usd`` (haqiqiy/estimated sarf) bilan aralashtirilmaydi; USD limit
    #: tekshiruvida ``total_usd`` ishlatiladi.
    assumed_usd: float = 0.0

    @property
    def total_usd(self) -> float:
        """USD limit tekshiruvi uchun: haqiqiy sarf + noma'lum narx taxmini."""
        return self.usd + self.assumed_usd

    def max_with(self, other: "Usage") -> "Usage":
        return Usage(max(self.tokens, other.tokens), max(self.usd, other.usd),
                     max(self.assumed_usd, other.assumed_usd))


@dataclass
class Snapshot:
    daily: Usage = field(default_factory=Usage)
    monthly: Usage = field(default_factory=Usage)


def _memory_snapshot(user_id: int) -> Snapshot:
    from services.ai import cost_tracker

    book = cost_tracker.default_ledger()
    out = Snapshot()
    for period, slot in ((PERIOD_DAILY, out.daily), (PERIOD_MONTHLY, out.monthly)):
        data = book.user_costs(user_id, period=period)
        slot.tokens = int(data.get("total_tokens") or 0)
        slot.usd = float(data.get("cost_usd") or 0.0)
        slot.assumed_usd = float(data.get("assumed_cost_usd") or 0.0)
    return out


def _db_ready() -> bool:
    """DB pool tayyormi? (modul yuklanmagan yoki pool yo'q → ``False``)."""
    database = sys.modules.get("database")
    return database is not None and getattr(database, "_pool", None) is not None


def _db_usage(user_id: int, period: str) -> Usage | None:
    if not _db_ready():
        return None
    database = sys.modules["database"]
    report = database.get_ai_usage_report(user_id=int(user_id), period=period)
    if not isinstance(report, dict):
        return None
    totals = report.get("totals") or {}
    from services.ai import cost_tracker

    # Narxi noma'lum so'rovlar taxmini DB'dagi tokenlardan hisoblanadi
    # (eski javobda maydonlar yo'q bo'lsa — 0).
    assumed = cost_tracker.assumed_cost_usd(
        int(totals.get("unpriced_input_tokens") or 0),
        int(totals.get("unpriced_output_tokens") or 0))
    return Usage(int(totals.get("total_tokens") or 0),
                 float(totals.get("estimated_cost_usd") or 0.0), assumed)


async def _db_snapshot(user_id: int) -> Snapshot | None:
    """DB agregati (pool yo'q yoki javob bermasa — ``None``, fail-soft)."""
    if not _db_ready():
        return None
    try:
        daily = await asyncio.wait_for(
            asyncio.to_thread(_db_usage, user_id, PERIOD_DAILY), DB_SNAPSHOT_TIMEOUT)
        monthly = await asyncio.wait_for(
            asyncio.to_thread(_db_usage, user_id, PERIOD_MONTHLY), DB_SNAPSHOT_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        logger.debug("budget: DB agregati olinmadi (user=%s): %s", user_id, exc)
        return None
    if daily is None or monthly is None:
        return None
    return Snapshot(daily=daily, monthly=monthly)


# ---------------------------------------------------------------------------
# Byudjet bron (atomik) va refund
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BudgetTicket:
    ticket_id: str
    user_id: int
    tokens: int
    usd: float


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: str = "ok"          # ok | daily_tokens | daily_usd | monthly_tokens | monthly_usd
    ticket: BudgetTicket | None = None
    tier: str = TIER_FREE

    @property
    def period(self) -> str:
        return PERIOD_MONTHLY if self.reason.startswith("monthly") else PERIOD_DAILY


class BudgetGuard:
    """Foydalanuvchi kesimida in-flight bron + limit tekshiruvi (thread-safe)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inflight: dict[int, Usage] = {}
        self._tickets: dict[str, BudgetTicket] = {}
        self.denied = 0

    def inflight(self, user_id) -> Usage:
        with self._lock:
            got = self._inflight.get(int(user_id))
            return Usage(got.tokens, got.usd) if got else Usage()

    async def acquire(self, user_id, tier: str, tokens: int, usd: float) -> BudgetDecision:
        """Limit ichida bo'lsa bron yozadi; aks holda ``allowed=False``."""
        if user_id is None:
            return BudgetDecision(True, "ok", None, tier)
        uid = int(user_id)
        limits = tier_budget(tier)
        db_snap = await _db_snapshot(uid)          # tarmoq I/O — qulfdan TASHQARIDA
        with self._lock:
            committed = _memory_snapshot(uid)
            if db_snap is not None:
                committed = Snapshot(committed.daily.max_with(db_snap.daily),
                                     committed.monthly.max_with(db_snap.monthly))
            held = self._inflight.get(uid, Usage())
            checks = (
                ("daily_tokens", committed.daily.tokens + held.tokens + tokens,
                 limits.daily_tokens),
                ("daily_usd", committed.daily.total_usd + held.usd + usd, limits.daily_usd),
                ("monthly_tokens", committed.monthly.tokens + held.tokens + tokens,
                 limits.monthly_tokens),
                ("monthly_usd", committed.monthly.total_usd + held.usd + usd, limits.monthly_usd),
            )
            for reason, projected, cap in checks:
                if cap and cap > 0 and projected > cap:
                    self.denied += 1
                    return BudgetDecision(False, reason, None, tier)
            ticket = BudgetTicket(uuid.uuid4().hex, uid, int(tokens), float(usd))
            self._tickets[ticket.ticket_id] = ticket
            self._inflight[uid] = Usage(held.tokens + ticket.tokens, held.usd + ticket.usd)
        return BudgetDecision(True, "ok", ticket, tier)

    def release(self, ticket: BudgetTicket | None) -> bool:
        """Bronni bo'shatadi (idempotent — ikkinchi chaqiruv no-op)."""
        if ticket is None:
            return False
        with self._lock:
            if self._tickets.pop(ticket.ticket_id, None) is None:
                return False
            held = self._inflight.get(ticket.user_id, Usage())
            left = Usage(max(0, held.tokens - ticket.tokens), max(0.0, held.usd - ticket.usd))
            if left.tokens == 0 and left.usd <= 0:
                self._inflight.pop(ticket.user_id, None)
            else:
                self._inflight[ticket.user_id] = left
        return True

    def status(self) -> dict:
        with self._lock:
            return {"inflight_users": len(self._inflight),
                    "open_tickets": len(self._tickets),
                    "denied": self.denied}


_guard = BudgetGuard()


def default_guard() -> BudgetGuard:
    """Jarayon bo'yicha yagona byudjet guard'i."""
    return _guard


# ---------------------------------------------------------------------------
# Foydalanuvchiga matn (uz / ru / en)
# ---------------------------------------------------------------------------
_TEXTS = {
    "uz": {
        "daily": "kunlik", "monthly": "oylik",
        "msg": ("⏳ AI {period} xarajat byudjeti tugadi. Ertaga qayta urinib ko'ring "
                "yoki PRO tarifga o'ting."),
    },
    "ru": {
        "daily": "дневной", "monthly": "месячный",
        "msg": ("⏳ Исчерпан {period} бюджет расходов на ИИ. Попробуйте завтра "
                "или перейдите на тариф PRO."),
    },
    "en": {
        "daily": "daily", "monthly": "monthly",
        "msg": ("⏳ The {period} AI spending budget is used up. Try again tomorrow "
                "or upgrade to PRO."),
    },
}


def budget_message(lang: str = "uz", period: str = PERIOD_DAILY) -> str:
    """Byudjet tugaganda foydalanuvchiga muloyim xabar (uz/ru/en)."""
    code = (lang or "uz").lower()
    table = _TEXTS.get(code, _TEXTS["uz"])
    label = table["monthly" if period == PERIOD_MONTHLY else "daily"]
    return table["msg"].format(period=label)


__all__ = [
    "BudgetDecision",
    "BudgetGuard",
    "BudgetTicket",
    "PERIOD_DAILY",
    "PERIOD_MONTHLY",
    "TIER_FREE",
    "TIER_PRO",
    "TierBudget",
    "budget_message",
    "default_guard",
    "estimate_request",
    "pro_monthly_usd_default",
    "resolve_tier",
    "reserve_output_tokens",
    "set_tier_resolver",
    "tier_budget",
]
