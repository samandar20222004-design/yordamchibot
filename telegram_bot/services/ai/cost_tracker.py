# -*- coding: utf-8 -*-
"""💰 SPRINT 4 — UNIT ECONOMICS: AI XARAJATINI MODEL BO'YICHA HISOBLASH.

Nima uchun bu modul (SPRINT 4, 1-band):
    * ilgari xarajat faqat umumiy ``estimated_cost`` ko'rinishida yozilardi
      (``ai_usage_events``) — model bo'yicha narx (``$ / 1K token``) yagona
      jadvalda emas, "kim qancha sarflayapti" va "PRO tarif o'zini oqlaydimi"
      degan savolga aniq javob yo'q edi;
    * yopiq beta (30–50 kanal egasi) va PRO tarif narxi (19 000 so'm) uchun
      **unit economics** — bitta faol foydalanuvchining AI xarajati, marja va
      rentabellik chegarasi — hisoblanmaydi.

Bu modul YAGONA xarajat manbai (Gemini / OpenAI / Groq + bepul tier'lar):

    * :data:`MODEL_PRICES` — model bo'yicha ``$ / 1K token`` (kirish/chiqish);
    * :func:`cost_usd` — bitta so'rov uchun xarajat (USD, 6 xona);
    * :func:`usd_to_uzs` / :func:`uzs_to_usd` — kurs (env: ``USD_UZS_RATE``);
    * :class:`CostLedger` — foydalanuvchi kesimida kunlik/oylik sarf (USD+UZS),
      jarayon xotirasida, cheklangan (memory guard);
    * :func:`user_ai_costs` — bitta foydalanuvchining kunlik va oylik sarfi
      (baza mavjud bo'lsa ``ai_usage_events`` agregatidan, aks holda
      jarayon xotirasidan);
    * :func:`economics_summary` — ``/economics`` uchun xulosa: o'rtacha
      bitta faol foydalanuvchi sarfi, PRO tarif marjasi va rentabellik.

Prinsip: **soxta raqam yo'q**. Jadvalda yo'q model uchun xarajat ``0.0`` va
``priced=False`` — hisobotda ``unpriced_requests`` sifatida ochiq ko'rsatiladi
(qiymat to'qib chiqarilmaydi). Barcha hisob-kitob funksiyalari deterministik:
``now`` / ``rate`` / ``ledger`` / ``db_module`` tashqaridan beriladi.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field  # noqa: F401
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Narx jadvali — USD / 1000 token (BAHO: ommaviy list narxlar)
# ---------------------------------------------------------------------------
PRIZE_NOTE = "list price (BAHO — USD / 1K token)"


@dataclass(frozen=True)
class ModelPrice:
    """Bitta model uchun 1K token narxi (USD)."""

    input_per_1k: float
    output_per_1k: float
    note: str = ""

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        """Shu narx bo'yicha xarajat (USD)."""
        in_tok = max(0, int(input_tokens or 0))
        out_tok = max(0, int(output_tokens or 0))
        return round(
            in_tok / 1000.0 * max(0.0, float(self.input_per_1k))
            + out_tok / 1000.0 * max(0.0, float(self.output_per_1k)),
            6,
        )


#: Kalitlar kichik harfda — ``provider + model`` satrida QISMAN mos kelishi
#: yetarli (eng uzun moslik ustun). Jadvalda yo'q model = narx NOMA'LUM.
MODEL_PRICES: "OrderedDict[str, ModelPrice]" = OrderedDict([
    # --- Google Gemini ----------------------------------------------------
    ("gemini-2.5-flash", ModelPrice(0.0003, 0.0025, "Gemini 2.5 Flash — " + PRIZE_NOTE)),
    ("gemini-2.5-pro", ModelPrice(0.00125, 0.01, "Gemini 2.5 Pro — " + PRIZE_NOTE)),
    ("gemini-2.0-flash", ModelPrice(0.0001, 0.0004, "Gemini 2.0 Flash — " + PRIZE_NOTE)),
    ("gemini", ModelPrice(0.0003, 0.0025, "Gemini oilasi (o'rtacha)")),
    # --- OpenAI (OpenRouter orqali ham) ----------------------------------
    ("gpt-4o-mini", ModelPrice(0.00015, 0.0006, "OpenAI GPT-4o mini — " + PRIZE_NOTE)),
    ("gpt-4o", ModelPrice(0.0025, 0.01, "OpenAI GPT-4o — " + PRIZE_NOTE)),
    ("gpt-4.1-mini", ModelPrice(0.0004, 0.0016, "OpenAI GPT-4.1 mini — " + PRIZE_NOTE)),
    ("o4-mini", ModelPrice(0.0011, 0.0044, "OpenAI o4-mini — " + PRIZE_NOTE)),
    ("openai", ModelPrice(0.0025, 0.01, "OpenAI oilasi (o'rtacha)")),
    # --- Groq (Llama / Mixtral / Qwen oilasi) ----------------------------
    ("llama-3.3-70b", ModelPrice(0.00059, 0.00079, "Groq Llama 3.3 70B — " + PRIZE_NOTE)),
    ("llama-3.1-8b", ModelPrice(0.00005, 0.00008, "Groq Llama 3.1 8B — " + PRIZE_NOTE)),
    ("mixtral", ModelPrice(0.00024, 0.00024, "Groq Mixtral 8x7B — " + PRIZE_NOTE)),
    ("qwen", ModelPrice(0.0002, 0.0006, "Qwen oilasi — " + PRIZE_NOTE)),
    ("llama", ModelPrice(0.0002, 0.0003, "Llama oilasi (o'rtacha)")),
    ("groq", ModelPrice(0.0002, 0.0003, "Groq — o'rtacha baho")),
    # --- Boshqa provayderlar (openrouter/mistral/...) --------------------
    ("openrouter", ModelPrice(0.0005, 0.0015, "OpenRouter — o'rtacha baho")),
    ("mistral", ModelPrice(0.0002, 0.0006, "Mistral — o'rtacha baho")),
    # --- Xarajat YO'Q (bepul tier / kesh / mock) --------------------------
    ("cerebras", ModelPrice(0.0, 0.0, "Cerebras — bepul tier")),
    ("sambanova", ModelPrice(0.0, 0.0, "SambaNova — bepul tier")),
    ("cloudflare", ModelPrice(0.0, 0.0, "Cloudflare Workers AI — bepul tier")),
    ("pollinations", ModelPrice(0.0, 0.0, "Pollinations — bepul (kalitsiz)")),
    ("mock", ModelPrice(0.0, 0.0, "Mock/soxta provayder — xarajat YO'Q")),
    ("cache", ModelPrice(0.0, 0.0, "Keshdan javob — xarajat YO'Q")),
])

#: Standart USD → UZS kursi (env ``USD_UZS_RATE`` bilan almashadi).
DEFAULT_USD_UZS_RATE = 12600


def _price_key(provider, model) -> str:
    return f"{provider or ''} {model or ''}".strip().lower()


def price_for(provider, model) -> "ModelPrice | None":
    """Provayder/model uchun narx (jadvalda yo'q bo'lsa — ``None``).

    Moslik: eng UZUN kalit ustun (masalan ``gemini-2.5-flash`` ``gemini``
    dan oldin tekshiriladi).
    """
    haystack = _price_key(provider, model)
    if not haystack:
        return None
    best: "ModelPrice | None" = None
    best_len = 0
    for key, price in MODEL_PRICES.items():
        if key in haystack and len(key) > best_len:
            best, best_len = price, len(key)
    return best


def is_priced(provider, model) -> bool:
    """Bu model uchun narx jadvalda BORmi (xarajat ma'nolimi)?"""
    return price_for(provider, model) is not None


def cost_usd(provider, model, input_tokens: int, output_tokens: int) -> float:
    """Bitta AI so'rovi uchun xarajat (USD, 6 xona).

    Noma'lum model → ``0.0`` (soxta raqam to'qilmaydi; chaqiruvchi
    :func:`is_priced` bilan "noma'lum" ekanini ajratadi).
    """
    price = price_for(provider, model)
    if price is None:
        return 0.0
    return price.cost(input_tokens, output_tokens)


# ---------------------------------------------------------------------------
# Valyuta kursi (USD ⇄ UZS)
# ---------------------------------------------------------------------------
def usd_uzs_rate(default: int = DEFAULT_USD_UZS_RATE) -> float:
    """USD → UZS kursi (config ``USD_UZS_RATE``; berilmasa ``default``)."""
    try:
        from config import USD_UZS_RATE  # type: ignore

        rate = float(USD_UZS_RATE)
    except Exception:  # noqa: BLE001 — config yo'q bo'lsa ham modul ishlaydi
        return float(default)
    return rate if rate > 0 else float(default)


def usd_to_uzs(usd: float, rate: float | None = None) -> float:
    """USD → UZS (2 xona — tiyin aniqligida)."""
    kurs = float(rate) if rate else usd_uzs_rate()
    if kurs <= 0:
        kurs = float(DEFAULT_USD_UZS_RATE)
    try:
        value = float(usd or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    return round(max(0.0, value) * kurs, 2)


def uzs_to_usd(uzs: float, rate: float | None = None) -> float:
    """UZS → USD (6 xona)."""
    kurs = float(rate) if rate else usd_uzs_rate()
    if kurs <= 0:
        kurs = float(DEFAULT_USD_UZS_RATE)
    try:
        value = float(uzs or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    return round(max(0.0, value) / kurs, 6)


# ---------------------------------------------------------------------------
# Foydalanuvchi kesimida sarf (in-memory ledger)
# ---------------------------------------------------------------------------
@dataclass
class CostBucket:
    """Bitta davr (kun/oy) uchun sarf yig'indisi."""

    requests: int = 0
    failures: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, *, input_tokens: int, output_tokens: int, cost: float,
            failed: bool = False) -> None:
        self.requests += 1
        if failed:
            self.failures += 1
        self.input_tokens += max(0, int(input_tokens or 0))
        self.output_tokens += max(0, int(output_tokens or 0))
        self.cost_usd = round(self.cost_usd + max(0.0, float(cost or 0.0)), 6)

    def as_dict(self, rate: float | None = None) -> dict:
        return {
            "requests": int(self.requests),
            "failures": int(self.failures),
            "input_tokens": int(self.input_tokens),
            "output_tokens": int(self.output_tokens),
            "total_tokens": int(self.input_tokens) + int(self.output_tokens),
            "cost_usd": round(float(self.cost_usd), 6),
            "cost_uzs": usd_to_uzs(self.cost_usd, rate),
        }


def _day_key(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d")


def _month_key(moment: datetime) -> str:
    return moment.strftime("%Y-%m")


class CostLedger:
    """Foydalanuvchi kesimida kunlik/oylik sarf (thread-safe, bounded).

    Xotira chegarasi: ``max_users`` (LRU) foydalanuvchi, har biri uchun
    ``daily_keep`` kun va ``monthly_keep`` oy. To'lib ketganda eng eski
    yozuvlar chiqarib tashlanadi — jarayon xotirasi cheksiz o'smaydi.
    """

    def __init__(self, *, max_users: int = 20_000, daily_keep: int = 45,
                 monthly_keep: int = 13) -> None:
        self._lock = threading.RLock()
        self._daily: "OrderedDict[int, OrderedDict[str, CostBucket]]" = OrderedDict()
        self._monthly: "OrderedDict[int, OrderedDict[str, CostBucket]]" = OrderedDict()
        self._max_users = max(1, int(max_users))
        self._daily_keep = max(1, int(daily_keep))
        self._monthly_keep = max(1, int(monthly_keep))

    # ------------------------------------------------------------------ yozuv
    def record(self, *, user_id, provider: str = "", model: str = "",
               input_tokens: int = 0, output_tokens: int = 0,
               cost: float | None = None, status: str = "success",
               cached: bool = False, ts: float | None = None) -> dict:
        """Bitta AI so'rovini qayd etadi va yozuv lug'atini qaytaradi.

        ``cost`` berilmasa — :func:`cost_usd` orqali narx jadvalidan
        hisoblanadi. ``user_id`` yo'q bo'lsa yozuv "egasiz" bo'ladi va
        saqlanmaydi (individual hisob faqat foydalanuvchi bilan).
        """
        moment = datetime.fromtimestamp(
            float(ts if ts is not None else time.time()), tz=timezone.utc
        )
        failed = str(status or "").lower() not in ("", "success")
        if cost is None:
            cost = cost_usd(provider, model, input_tokens, output_tokens)
        priced = is_priced(provider, model)
        entry = {
            "user_id": int(user_id) if user_id is not None else None,
            "provider": str(provider or ""),
            "model": str(model or ""),
            "input_tokens": max(0, int(input_tokens or 0)),
            "output_tokens": max(0, int(output_tokens or 0)),
            "cost_usd": round(max(0.0, float(cost or 0.0)), 6),
            "priced": bool(priced),
            "status": "failed" if failed else "success",
            "cached": bool(cached),
            "at": moment.isoformat(),
        }
        if user_id is None:
            return entry
        uid = int(user_id)
        with self._lock:
            daily = self._touch(self._daily, uid)
            monthly = self._touch(self._monthly, uid)
            bucket = daily.setdefault(_day_key(moment), CostBucket())
            bucket.add(input_tokens=input_tokens, output_tokens=output_tokens,
                       cost=entry["cost_usd"], failed=failed)
            month_bucket = monthly.setdefault(_month_key(moment), CostBucket())
            month_bucket.add(input_tokens=input_tokens, output_tokens=output_tokens,
                             cost=entry["cost_usd"], failed=failed)
            self._trim(daily, self._daily_keep)
            self._trim(monthly, self._monthly_keep)
        return entry

    def record_event(self, event: dict) -> dict | None:
        """Telemetriya yozuvi (``ai_usage_events`` shakli) → ledger.

        ``build_usage_event(...).as_dict()`` natijasi shu yerga uzatiladi.
        Xato bo'lsa ``None`` qaytadi — AI oqimi HECH QACHON buzilmaydi.
        """
        try:
            return self.record(
                user_id=(event or {}).get("user_id"),
                provider=(event or {}).get("provider") or "",
                model=(event or {}).get("model") or "",
                input_tokens=(event or {}).get("input_tokens") or 0,
                output_tokens=(event or {}).get("output_tokens") or 0,
                cost=(event or {}).get("estimated_cost"),
                status=(event or {}).get("status") or "success",
                cached=bool((event or {}).get("cached")),
            )
        except Exception:  # pragma: no cover — himoya
            logger.debug("cost_tracker: yozuvda xato", exc_info=True)
            return None

    # ------------------------------------------------------------------ o'quv
    def user_bucket(self, user_id, period: str = "daily",
                    now: datetime | None = None) -> CostBucket:
        """Foydalanuvchining joriy davr (kun/oy) savatchasi."""
        moment = now or datetime.now(timezone.utc)
        if period == "monthly":
            key = _month_key(moment)
            store = self._monthly
        else:
            key = _day_key(moment)
            store = self._daily
        with self._lock:
            got = (store.get(int(user_id)) or {}).get(key)
        return got or CostBucket()

    def user_costs(self, user_id, *, period: str = "daily",
                   now: datetime | None = None, rate: float | None = None) -> dict:
        """Foydalanuvchi sarfi: ``{requests, tokens, cost_usd, cost_uzs, ...}``."""
        moment = now or datetime.now(timezone.utc)
        if period == "monthly":
            bucket = self.user_bucket(user_id, "monthly", moment)
        elif period == "all":
            total = CostBucket()
            with self._lock:
                for bucket_day in (self._monthly.get(int(user_id)) or {}).values():
                    total.requests += bucket_day.requests
                    total.failures += bucket_day.failures
                    total.input_tokens += bucket_day.input_tokens
                    total.output_tokens += bucket_day.output_tokens
                    total.cost_usd = round(total.cost_usd + bucket_day.cost_usd, 6)
            bucket = total
        else:
            bucket = self.user_bucket(user_id, "daily", moment)
        data = bucket.as_dict(rate)
        data.update({"user_id": int(user_id) if user_id is not None else None,
                     "period": period, "source": "memory"})
        return data

    def totals(self, *, period: str = "daily", now: datetime | None = None,
               rate: float | None = None) -> dict:
        """Butun jarayon bo'yicha sarf (joriy kun yoki oy)."""
        moment = now or datetime.now(timezone.utc)
        store = self._monthly if period == "monthly" else self._daily
        key = _month_key(moment) if period == "monthly" else _day_key(moment)
        total = CostBucket()
        with self._lock:
            for user_days in store.values():
                bucket = user_days.get(key)
                if bucket is None:
                    continue
                total.requests += bucket.requests
                total.failures += bucket.failures
                total.input_tokens += bucket.input_tokens
                total.output_tokens += bucket.output_tokens
                total.cost_usd = round(total.cost_usd + bucket.cost_usd, 6)
        data = total.as_dict(rate)
        data.update({"period": period, "source": "memory"})
        return data

    def top_users(self, *, period: str = "monthly", limit: int = 5,
                  now: datetime | None = None, rate: float | None = None) -> list:
        """Eng ko'p sarflagan foydalanuvchilar (jarayon xotirasi kesimida)."""
        moment = now or datetime.now(timezone.utc)
        key = _month_key(moment) if period == "monthly" else _day_key(moment)
        store = self._monthly if period == "monthly" else self._daily
        rows = []
        with self._lock:
            for uid, buckets in store.items():
                bucket = buckets.get(key)
                if bucket is None or bucket.requests == 0:
                    continue
                rows.append({"user_id": int(uid),
                             **bucket.as_dict(rate)})
        rows.sort(key=lambda r: r["cost_usd"], reverse=True)
        return rows[: max(1, int(limit))]

    def users_tracked(self) -> int:
        with self._lock:
            return len(self._daily)

    def reset(self) -> None:
        """Faqat testlar uchun."""
        with self._lock:
            self._daily.clear()
            self._monthly.clear()

    # -------------------------------------------------------------- ichki
    def _touch(self, store, uid: int) -> "OrderedDict[str, CostBucket]":
        buckets = store.get(uid)
        if buckets is None:
            buckets = OrderedDict()
            store[uid] = buckets
        store.move_to_end(uid)
        while len(store) > self._max_users:
            store.popitem(last=False)
        return buckets

    @staticmethod
    def _trim(buckets: "OrderedDict[str, CostBucket]", keep: int) -> None:
        while len(buckets) > keep:
            buckets.popitem(last=False)


#: Jarayon bo'yicha yagona ledger (bot ishlab turgan davr xarajati).
_ledger = CostLedger()


def default_ledger() -> CostLedger:
    """Jarayonning yagona ledger'i."""
    return _ledger


def record_usage_event(event: dict, ledger: CostLedger | None = None) -> bool:
    """Telemetriya yozuvini ledger'ga yozadi (best-effort, xatosiz)."""
    try:
        (ledger or _ledger).record_event(event)
        return True
    except Exception:  # pragma: no cover — hisob AI oqimini to'xtatmaydi
        logger.debug("cost_tracker: record_usage_event xatosi", exc_info=True)
        return False


def record_ai_cost(*, user_id, provider: str = "", model: str = "",
                   input_tokens: int = 0, output_tokens: int = 0,
                   cost: float | None = None, status: str = "success",
                   cached: bool = False, ledger: CostLedger | None = None) -> bool:
    """To'g'ridan-to'g'ri xarajat yozuvi (sinxron chaqiruvchilar uchun)."""
    try:
        (ledger or _ledger).record(
            user_id=user_id, provider=provider, model=model,
            input_tokens=input_tokens, output_tokens=output_tokens,
            cost=cost, status=status, cached=cached,
        )
        return True
    except Exception:  # pragma: no cover
        logger.debug("cost_tracker: record_ai_cost xatosi", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Baza (ai_usage_events) bilan birlashtirilgan hisobot
# ---------------------------------------------------------------------------
def _db_cost_totals(db_module, *, user_id=None, period: str = "daily") -> dict | None:
    """``ai_usage_events`` agregati (real baza bo'lmasa — ``None``)."""
    if db_module is None or not hasattr(db_module, "get_ai_usage_report"):
        return None
    try:
        report = db_module.get_ai_usage_report(user_id=user_id, period=period)
    except Exception as exc:  # noqa: BLE001 — hisobot best-effort
        logger.warning("AI xarajat hisobotini olishda xato: %s", exc)
        return None
    if not isinstance(report, dict):
        return None
    totals = report.get("totals") or {}
    return {
        "requests": int(totals.get("requests") or 0),
        "successes": int(totals.get("successes") or 0),
        "failures": int(totals.get("failures") or 0),
        "input_tokens": int(totals.get("input_tokens") or 0),
        "output_tokens": int(totals.get("output_tokens") or 0),
        "total_tokens": int(totals.get("total_tokens")
                            or (int(totals.get("input_tokens") or 0)
                                + int(totals.get("output_tokens") or 0))),
        "cost_usd": round(float(totals.get("estimated_cost_usd") or 0.0), 6),
        "priced_requests": int(totals.get("priced_requests") or 0),
        "unpriced_requests": int(totals.get("unpriced_requests") or 0),
        "period": str(report.get("period") or period),
        "source": "db",
    }


def user_ai_costs(user_id, *, db_module=None, ledger: CostLedger | None = None,
                  rate: float | None = None, now: datetime | None = None) -> dict:
    """Foydalanuvchi AI sarfi: kunlik/oylik/umumiy — USD va UZS da.

    ``user_ai_costs`` — SPRINT 4 talabidagi ko'rsatkich: bitta foydalanuvchi
    uchun kunlik va oylik sarf. Manba: baza mavjud bo'lsa ``ai_usage_events``
    (haqiqiy tarix), aks holda jarayon xotirasidagi ledger
    (``source`` maydonida OCHIQ ko'rsatiladi — soxta raqam yo'q).
    """
    book = ledger if ledger is not None else _ledger
    result = {
        "user_id": int(user_id) if user_id is not None else None,
        "rate_usd_uzs": float(rate) if rate else usd_uzs_rate(),
        "daily": {},
        "monthly": {},
        "all": {},
        "source": "memory",
    }
    db_available = False
    for period in ("daily", "monthly", "all"):
        from_db = _db_cost_totals(db_module, user_id=user_id, period=period)
        if from_db is not None:
            db_available = True
            from_db["cost_uzs"] = usd_to_uzs(from_db["cost_usd"], rate)
            result[period] = from_db
        else:
            result[period] = book.user_costs(user_id, period=period,
                                             now=now, rate=rate)
    result["source"] = "db" if db_available else "memory"
    return result


# ---------------------------------------------------------------------------
# UNIT ECONOMICS — PRO tarif rentabelligi
# ---------------------------------------------------------------------------
#: Marja zonalari (o'rtacha AI xarajat / PRO narxi nisbati).
MARGIN_HEALTHY_MAX = 0.30   # < 30%  → sog'lom
MARGIN_WATCH_MAX = 0.60     # < 60%  → kuzatuv
MARGIN_THIN_MAX = 1.00      # < 100% → yupqa (lekin foydada)

VERDICT_HEALTHY = "healthy"
VERDICT_WATCH = "watch"
VERDICT_THIN = "thin"
VERDICT_LOSS = "loss"


def _verdict(cost_share: float) -> str:
    if cost_share < MARGIN_HEALTHY_MAX:
        return VERDICT_HEALTHY
    if cost_share < MARGIN_WATCH_MAX:
        return VERDICT_WATCH
    if cost_share < MARGIN_THIN_MAX:
        return VERDICT_THIN
    return VERDICT_LOSS


def economics_summary(*, period: str = "monthly", db_module=None,
                      ledger: CostLedger | None = None, active_users: int | None = None,
                      pro_price_uzs: int | None = None, rate: float | None = None,
                      now: datetime | None = None) -> dict:
    """``/economics`` uchun xulosa: o'rtacha sarf va PRO tarif rentabelligi.

    Returns:
        dict::

            {
              "period": "monthly" | "daily",
              "source": "db" | "memory",
              "requests": int, "total_tokens": int,
              "total_cost_usd": float, "total_cost_uzs": float,
              "priced_requests": int, "unpriced_requests": int,
              "active_users": int, "avg_cost_usd": float, "avg_cost_uzs": float,
              "pro_price_uzs": int, "pro_price_usd": float,
              "margin_uzs": float, "margin_rate": float,
              "cost_share": float, "verdict": str,
              "users_per_payment": int | None,
              "rate_usd_uzs": float,
            }
    """
    book = ledger if ledger is not None else _ledger
    totals = _db_cost_totals(db_module, period=period)
    if totals is None:
        totals = book.totals(period=period, now=now, rate=rate)
        totals.setdefault("priced_requests", 0)
        totals.setdefault("unpriced_requests", 0)

    cost_usd = float(totals.get("cost_usd") or 0.0)
    cost_uzs = usd_to_uzs(cost_usd, rate)

    # Faol foydalanuvchilar: baza metrikasi → jarayon xotirasi (fallback).
    if active_users is None:
        active_users = _active_users_from_db(db_module, period)
    if active_users is None or int(active_users) <= 0:
        active_users = book.users_tracked()
    active_users = max(0, int(active_users or 0))

    avg_usd = round(cost_usd / active_users, 6) if active_users else 0.0
    avg_uzs = usd_to_uzs(avg_usd, rate)

    if pro_price_uzs is None:
        pro_price_uzs = _pro_price_uzs()
    pro_price_uzs = max(0, int(pro_price_uzs))

    margin_uzs = round(pro_price_uzs - avg_uzs, 2)
    margin_rate = round(margin_uzs / pro_price_uzs, 4) if pro_price_uzs else 0.0
    cost_share = round(avg_uzs / pro_price_uzs, 4) if pro_price_uzs else 0.0
    users_per_payment = (
        int(pro_price_uzs // avg_uzs) if (avg_uzs > 0 and pro_price_uzs > 0) else None
    )

    return {
        "period": period,
        "source": str(totals.get("source") or "memory"),
        "requests": int(totals.get("requests") or 0),
        "total_tokens": int(totals.get("total_tokens") or 0),
        "total_cost_usd": round(cost_usd, 6),
        "total_cost_uzs": cost_uzs,
        "priced_requests": int(totals.get("priced_requests") or 0),
        "unpriced_requests": int(totals.get("unpriced_requests") or 0),
        "active_users": active_users,
        "avg_cost_usd": avg_usd,
        "avg_cost_uzs": avg_uzs,
        "pro_price_uzs": pro_price_uzs,
        "pro_price_usd": uzs_to_usd(pro_price_uzs, rate),
        "margin_uzs": margin_uzs,
        "margin_rate": margin_rate,
        "cost_share": cost_share,
        "verdict": _verdict(cost_share),
        "users_per_payment": users_per_payment,
        "rate_usd_uzs": float(rate) if rate else usd_uzs_rate(),
    }


def _active_users_from_db(db_module, period: str) -> int | None:
    """Faol foydalanuvchilar soni (baza metrikasi; yo'q bo'lsa ``None``)."""
    if db_module is None:
        return None
    metrics = None
    if hasattr(db_module, "get_observability_metrics"):
        try:
            metrics = db_module.get_observability_metrics()
        except Exception:  # noqa: BLE001
            metrics = None
    if isinstance(metrics, dict) and metrics.get("available"):
        key = "active_users_monthly" if period == "monthly" else "active_users_daily"
        try:
            value = int(metrics.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return None


def _pro_price_uzs() -> int:
    """PRO tarif narxi (so'm) — config'dan (yagona manba), fallback 19 000."""
    try:
        from config import PAYMENT_PRICE_1M_UZS  # type: ignore

        return int(PAYMENT_PRICE_1M_UZS)
    except Exception:  # noqa: BLE001
        return 19000


__all__ = [
    "CostBucket",
    "CostLedger",
    "DEFAULT_USD_UZS_RATE",
    "MARGIN_HEALTHY_MAX",
    "MARGIN_THIN_MAX",
    "MARGIN_WATCH_MAX",
    "MODEL_PRICES",
    "ModelPrice",
    "VERDICT_HEALTHY",
    "VERDICT_LOSS",
    "VERDICT_THIN",
    "VERDICT_WATCH",
    "cost_usd",
    "default_ledger",
    "economics_summary",
    "is_priced",
    "price_for",
    "record_ai_cost",
    "record_usage_event",
    "usd_to_uzs",
    "usd_uzs_rate",
    "user_ai_costs",
    "uzs_to_usd",
]
