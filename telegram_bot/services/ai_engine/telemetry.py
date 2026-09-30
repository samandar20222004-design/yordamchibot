"""AI COST & USAGE TELEMETRY — PHASE 6 (xarajat va token hisobi).

Muammo (PHASE 6 auditi): repo bo'ylab AI chaqiruvlari uchun **token, model,
latency va xarajat** hech qayerda qayd etilmas edi — ``grep input_tokens``
butun ``telegram_bot/`` bo'ylab 0 natija berardi. Natijada:

* qaysi provayder/model qancha sarflayotgani noma'lum edi;
* foydalanuvchi/kanal kesimida kunlik-oylik xarajat hisoboti YO'Q edi;
* provayder tanlash (router) qarorlari faqat "sog'liq" (circuit breaker)
  bilan cheklanardi — xarajat bosimi hisobga olinmasdi.

Bu modul YAGONA telemetriya manbai:

* :func:`estimate_tokens` — matn uzunligidan token bahosi (provayderlar
  token hisobini qaytarmaydi; baho ochiq formula bilan hisoblanadi —
  **soxta aniq raqam yozilmaydi**);
* :class:`PriceSpec` + :data:`PRICE_TABLE` — model bo'yicha 1K token narxi
  (USD). Jadvalda yo'q model uchun narx ``0.0`` va ``priced=False``
  (xarajat "noma'lum", to'qib chiqarilmaydi);
* :class:`AIUsageEvent` — bitta AI so'rovining qat'iy yozuvi: model,
  provider, input/output tokenlar, latency, taxminiy xarajat, status;
* :class:`UsageRecorder` — in-memory yozuv (DB bo'lmasa ham ishlaydi) va
  kunlik/oylik hisobot agregatsiyasi (user/kanal kesimida).

DB'ga yozish alohida **Application Service** qatlamida
(``services.ai_engine.app_service``) bajariladi — bu modul tarmoqqa ham,
bazaga ham chiqmaydi (deterministik va test qilinadigan qoladi).
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status qiymatlari (DB CHECK'i bilan bir xil: schema.sql → ai_usage_events)
# ---------------------------------------------------------------------------
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUSES: tuple[str, ...] = (STATUS_SUCCESS, STATUS_FAILED)

#: Hisobot davrlari (kanonik).
PERIOD_DAILY = "daily"
PERIOD_MONTHLY = "monthly"
PERIOD_ALL = "all"
PERIODS: tuple[str, ...] = (PERIOD_DAILY, PERIOD_MONTHLY, PERIOD_ALL)

#: Token bahosi: o'rtacha ~4 belgi = 1 token (GPT/Llama/Gemini oilasi uchun
#: e'lon qilingan o'rtacha ko'rsatkich). Bu BAHO — provayderlar token
#: hisobini javobda qaytarmagani uchun yagona ochiq formula ishlatiladi.
CHARS_PER_TOKEN = 4

#: Standart kesh/litsey chegarasi: in-memory yozuvlar soni (memory guard).
DEFAULT_MAX_EVENTS = 1000


def estimate_tokens(text: str | None) -> int:
    """Matn uchun token bahosi (bo'sh matn → 0, aks holda kamida 1)."""
    value = "" if text is None else str(text)
    if not value:
        return 0
    return max(1, math.ceil(len(value) / CHARS_PER_TOKEN))


# ---------------------------------------------------------------------------
# Narx jadvali (xarajat BAHOSI — USD / 1000 token)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PriceSpec:
    """Bitta model guruhi uchun 1K token narxi (USD) — BAHO."""

    input_per_1k: float
    output_per_1k: float
    note: str = ""


#: Model → narx. Kalitlar kichik harfda va model nomi/``provider model``
#: satrida qidiriladi (prefiks mos kelishi yetarli). Jadvalda yo'q model
#: uchun xarajat ``0.0`` + ``priced=False`` — "noma'lum" deb yoziladi va
#: hisobotda ``unpriced_requests`` sifatida ajratiladi (soxta raqam yo'q).
PRICE_TABLE: "OrderedDict[str, PriceSpec]" = OrderedDict([
    # --- Google Gemini (bepul tarif mavjud; pullik tarif qiymatlari) --------
    ("gemini-2.5-flash", PriceSpec(0.0003, 0.0025, "Gemini 2.5 Flash (list price)")),
    ("gemini-2.5-pro", PriceSpec(0.00125, 0.01, "Gemini 2.5 Pro (list price)")),
    ("gemini-2.0-flash", PriceSpec(0.0001, 0.0004, "Gemini 2.0 Flash (list price)")),
    ("gemini", PriceSpec(0.0, 0.0, "Gemini — bepul tarif (free tier)")),
    # --- Groq (Llama oilasi) ----------------------------------------------
    ("llama-3.3-70b", PriceSpec(0.00059, 0.00079, "Groq Llama 3.3 70B (list price)")),
    ("llama-3.1-8b", PriceSpec(0.00005, 0.00008, "Groq Llama 3.1 8B (list price)")),
    ("llama", PriceSpec(0.0002, 0.0003, "Llama oilasi (o'rtacha baho)")),
    ("groq", PriceSpec(0.0002, 0.0003, "Groq — o'rtacha baho")),
    # --- OpenRouter / Mistral / Cerebras / SambaNova ----------------------
    ("openrouter", PriceSpec(0.0005, 0.0015, "OpenRouter — o'rtacha baho")),
    ("mistral", PriceSpec(0.0002, 0.0006, "Mistral — o'rtacha baho")),
    ("cerebras", PriceSpec(0.0, 0.0, "Cerebras — bepul tarif")),
    ("sambanova", PriceSpec(0.0, 0.0, "SambaNova — bepul tarif")),
    # --- Bepul/belgilanmagan zanjir oxiri --------------------------------
    ("cloudflare", PriceSpec(0.0, 0.0, "Cloudflare Workers AI — bepul tarif")),
    ("pollinations", PriceSpec(0.0, 0.0, "Pollinations — bepul (kalitsiz)")),
    ("mock", PriceSpec(0.0, 0.0, "Mock/soxta provayder — xarajat YO'Q")),
    ("cache", PriceSpec(0.0, 0.0, "Keshdan javob — xarajat YO'Q")),
])

#: Testlar/ops uchun override (model → PriceSpec); global jadvaldan ustun.
_PRICE_OVERRIDES: dict[str, PriceSpec] = {}


def set_price_override(model: str, spec: PriceSpec | None) -> None:
    """Model uchun narxni qayta belgilaydi (``None`` — override olib tashlanadi)."""
    key = str(model or "").strip().lower()
    if not key:
        return
    if spec is None:
        _PRICE_OVERRIDES.pop(key, None)
    else:
        _PRICE_OVERRIDES[key] = spec


def clear_price_overrides() -> None:
    """Barcha override'larni tozalaydi (testlar uchun)."""
    _PRICE_OVERRIDES.clear()


def _price_key(provider: str | None, model: str | None) -> str:
    return f"{provider or ''} {model or ''}".strip().lower()


def price_spec(provider: str | None, model: str | None) -> PriceSpec:
    """Provayder/model uchun narx (topilmasa — nol narx, ``priced=False``)."""
    haystack = _price_key(provider, model)
    for key, spec in _PRICE_OVERRIDES.items():
        if key and key in haystack:
            return spec
    for key, spec in PRICE_TABLE.items():
        if key in haystack:
            return spec
    return PriceSpec(0.0, 0.0, "noma'lum model — narx jadvalda yo'q")


def is_priced(provider: str | None, model: str | None) -> bool:
    """Bu juftlik uchun narx jadvalda BORmi (xarajat ma'nolimi)?"""
    haystack = _price_key(provider, model)
    if any(key and key in haystack for key in _PRICE_OVERRIDES):
        return True
    return any(key in haystack for key in PRICE_TABLE)


def estimate_cost(
    provider: str | None,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Taxminiy xarajat (USD) — narx jadvali bo'yicha, 6 xonagacha yaxlitlanadi."""
    spec = price_spec(provider, model)
    cost = (
        max(0, int(input_tokens or 0)) / 1000.0 * max(0.0, spec.input_per_1k)
        + max(0, int(output_tokens or 0)) / 1000.0 * max(0.0, spec.output_per_1k)
    )
    return round(cost, 6)


def prompt_hash(prompt: str | None) -> str:
    """Prompt barmoq izi (mazmun saqlanmaydi — faqat 16 belgili sha256)."""
    digest = hashlib.sha256(str(prompt or "").encode("utf-8")).hexdigest()
    return digest[:16]


# ---------------------------------------------------------------------------
# Yozuv (event)
# ---------------------------------------------------------------------------
@dataclass
class AIUsageEvent:
    """Bitta AI so'rovining to'liq telemetriya yozuvi.

    Maydonlar DB jadvali (``ai_usage_events``) ustunlari bilan AYNAN bir xil
    tartibda — :meth:`to_row` shu tartibda tuple qaytaradi.
    """

    user_id: int | None = None
    channel_id: int | None = None
    task: str = ""
    lane: str = ""
    operation_type: str = ""
    provider: str = "none"
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    estimated_cost: float = 0.0
    priced: bool = False
    status: str = STATUS_FAILED
    error_code: str | None = None
    cached: bool = False
    attempts: int = 0
    prompt_hash: str = ""
    reservation_id: int | None = None
    created_at: float = field(default_factory=time.time)

    # -------------------------------------------------------------- yordamchi
    @property
    def total_tokens(self) -> int:
        return int(self.input_tokens or 0) + int(self.output_tokens or 0)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["total_tokens"] = self.total_tokens
        data["created_at_iso"] = datetime.fromtimestamp(
            float(self.created_at or 0), tz=timezone.utc
        ).isoformat()
        return data

    def to_row(self) -> tuple:
        """DB ustunlari tartibidagi tuple (``database.save_ai_usage_event``)."""
        return (
            self.user_id,
            self.channel_id,
            str(self.task or "")[:64],
            str(self.lane or "")[:16],
            str(self.operation_type or "")[:32],
            str(self.provider or "none")[:32],
            str(self.model or "")[:64],
            int(self.input_tokens or 0),
            int(self.output_tokens or 0),
            int(self.latency_ms or 0),
            float(self.estimated_cost or 0.0),
            bool(self.priced),
            self.status if self.status in STATUSES else STATUS_FAILED,
            (str(self.error_code)[:64] if self.error_code else None),
            bool(self.cached),
            int(self.attempts or 0),
            str(self.prompt_hash or "")[:32],
            self.reservation_id,
        )


def build_usage_event(
    *,
    result=None,
    prompt: str = "",
    system_instruction: str = "",
    task: str = "",
    operation_type: str = "",
    user_id: int | None = None,
    channel_id: int | None = None,
    reservation_id: int | None = None,
    latency_ms: int | None = None,
    cached: bool | None = None,
) -> AIUsageEvent:
    """Gateway natijasidan kanonik telemetriya yozuvini quradi (yagona joy).

    Tokenlar prompt + tizim ko'rsatmasi (kirish) va javob matni (chiqish)
    bo'yicha baholanadi; narx jadvali orqali xarajat hisoblanadi.
    """
    ok = bool(getattr(result, "ok", False))
    text = str(getattr(result, "text", "") or "")
    provider = str(getattr(result, "provider", "") or "none")
    model = str(getattr(result, "model", "") or "")
    elapsed = getattr(result, "elapsed", 0.0) or 0.0
    event = AIUsageEvent(
        user_id=user_id,
        channel_id=channel_id,
        task=str(getattr(result, "task", "") or task or ""),
        lane=str(getattr(getattr(result, "lane", ""), "value", getattr(result, "lane", "")) or ""),
        operation_type=str(operation_type or ""),
        provider=provider,
        model=model,
        input_tokens=estimate_tokens(prompt) + estimate_tokens(system_instruction),
        output_tokens=estimate_tokens(text),
        latency_ms=int(latency_ms if latency_ms is not None else round(elapsed * 1000)),
        status=STATUS_SUCCESS if ok else STATUS_FAILED,
        error_code=(None if ok else (str(getattr(result, "failure_kind", "") or "error"))),
        cached=bool(getattr(result, "cached", False) if cached is None else cached),
        attempts=int(getattr(result, "attempts", 0) or 0),
        prompt_hash=prompt_hash(prompt),
        reservation_id=reservation_id,
    )
    event.priced = ok and is_priced(provider, model) and not event.cached
    event.estimated_cost = (
        estimate_cost(provider, model, event.input_tokens, event.output_tokens)
        if event.priced else 0.0
    )
    return event


# ---------------------------------------------------------------------------
# Hisobot agregatsiyasi
# ---------------------------------------------------------------------------
def _window(period: str, now: datetime | None = None) -> tuple[float, float]:
    """Davr oynasi (epoch soniyalar): (start, end)."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    if period == PERIOD_ALL:
        # Chekli oyna: ``inf`` timestamp'ga aylantirib bo'lmaydi (hisobot
        # ISO ko'rsatkichlarini ham buzardi) — "hamma vaqt" = 1970 → hozir.
        return 0.0, moment.timestamp()
    if period == PERIOD_MONTHLY:
        start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # daily (standart)
        start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return start.timestamp(), moment.timestamp()


def _empty_bucket() -> dict:
    return {
        "requests": 0, "successes": 0, "failures": 0, "cache_hits": 0,
        "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0,
        "latency_ms_sum": 0,
    }


def _finish_bucket(bucket: dict) -> dict:
    requests = int(bucket["requests"])
    result = dict(bucket)
    result["total_tokens"] = int(bucket["input_tokens"]) + int(bucket["output_tokens"])
    result["estimated_cost_usd"] = round(float(bucket["estimated_cost_usd"]), 6)
    result["avg_latency_ms"] = (
        round(bucket["latency_ms_sum"] / requests, 1) if requests else 0.0
    )
    result.pop("latency_ms_sum", None)
    return result


class UsageRecorder:
    """In-memory telemetriya yozuvchisi (thread-safe, DB'siz ishlaydi).

    * yozuvlar cheklangan deque'da saqlanadi (memory guard);
    * ``sinks`` — har bir yozuvni tashqi tizimga uzatuvchi sinxron
      funksiyalar; ular xato bersa AI oqimi BUZILMAYDI (jim log);
    * :meth:`report` — user/kanal kesimida kunlik/oylik agregat.
    """

    def __init__(self, max_events: int = DEFAULT_MAX_EVENTS):
        self.max_events = max(1, int(max_events))
        self._events: deque[AIUsageEvent] = deque(maxlen=self.max_events)
        self._sinks: list = []
        self._lock = threading.RLock()
        self._counters = {"recorded": 0, "dropped": 0, "sink_errors": 0}

    # ------------------------------------------------------------- yozish
    def add_sink(self, sink) -> None:
        """Yozuvlarni qabul qiluvchi sinxron funksiya (idempotent qo'shiladi)."""
        with self._lock:
            if sink not in self._sinks:
                self._sinks.append(sink)

    def remove_sink(self, sink) -> None:
        with self._lock:
            if sink in self._sinks:
                self._sinks.remove(sink)

    def record(self, event: AIUsageEvent) -> AIUsageEvent:
        """Yozuvni saqlaydi va sink'larga uzatadi (hech qachon istisno otmaydi)."""
        if event is None:
            return event
        with self._lock:
            self._events.append(event)
            self._counters["recorded"] += 1
            sinks = list(self._sinks)
        for sink in sinks:
            try:
                sink(event)
            except Exception as exc:  # noqa: BLE001 — telemetriya AI'ni buza olmaydi
                with self._lock:
                    self._counters["sink_errors"] += 1
                logger.warning("Telemetriya sink xatosi: %s", exc)
        return event

    def reset(self) -> None:
        """Barcha yozuvlarni tozalaydi (testlar/ops)."""
        with self._lock:
            self._events.clear()
            self._counters = {"recorded": 0, "dropped": 0, "sink_errors": 0}

    # ------------------------------------------------------------- o'qish
    def events(self) -> list[AIUsageEvent]:
        with self._lock:
            return list(self._events)

    def last(self) -> AIUsageEvent | None:
        with self._lock:
            return self._events[-1] if self._events else None

    def stats(self) -> dict:
        """Umumiy yozuv statistikasi (diagnostika uchun)."""
        with self._lock:
            events = list(self._events)
            counters = dict(self._counters)
        return {
            **counters,
            "stored": len(events),
            "max_events": self.max_events,
            "sinks": len(self._sinks),
            "estimated_cost_usd": round(sum(e.estimated_cost for e in events), 6),
            "total_tokens": sum(e.total_tokens for e in events),
        }

    def report(
        self,
        *,
        user_id: int | None = None,
        channel_id: int | None = None,
        period: str = PERIOD_DAILY,
        now: datetime | None = None,
    ) -> dict:
        """Kunlik/oylik xarajat va ishlatilish hisoboti (user/kanal kesimida)."""
        period = str(period or PERIOD_DAILY).lower()
        if period not in PERIODS:
            period = PERIOD_DAILY
        start, end = _window(period, now)
        totals = _empty_bucket()
        by_provider: dict[str, dict] = {}
        by_model: dict[str, dict] = {}
        by_task: dict[str, dict] = {}
        by_lane: dict[str, dict] = {}
        by_day: dict[str, dict] = {}
        priced_requests = 0
        unpriced_requests = 0
        matched = 0

        with self._lock:
            events = list(self._events)

        for event in events:
            if user_id is not None and event.user_id != user_id:
                continue
            if channel_id is not None and event.channel_id != channel_id:
                continue
            created = float(event.created_at or 0)
            if created < start or created > end:
                continue
            matched += 1

            def _bump(bucket: dict) -> None:
                bucket["requests"] += 1
                bucket["successes"] += 1 if event.status == STATUS_SUCCESS else 0
                bucket["failures"] += 1 if event.status == STATUS_FAILED else 0
                bucket["cache_hits"] += 1 if event.cached else 0
                bucket["input_tokens"] += int(event.input_tokens or 0)
                bucket["output_tokens"] += int(event.output_tokens or 0)
                bucket["estimated_cost_usd"] += float(event.estimated_cost or 0.0)
                bucket["latency_ms_sum"] += int(event.latency_ms or 0)

            _bump(totals)
            _bump(by_provider.setdefault(str(event.provider or "none"), _empty_bucket()))
            _bump(by_model.setdefault(str(event.model or "noma'lum"), _empty_bucket()))
            _bump(by_task.setdefault(str(event.task or "noma'lum"), _empty_bucket()))
            _bump(by_lane.setdefault(str(event.lane or "noma'lum"), _empty_bucket()))
            if period == PERIOD_MONTHLY:
                day = datetime.fromtimestamp(created, tz=timezone.utc).strftime("%Y-%m-%d")
                _bump(by_day.setdefault(day, _empty_bucket()))
            if event.status == STATUS_SUCCESS:
                if event.priced:
                    priced_requests += 1
                else:
                    unpriced_requests += 1

        finished = _finish_bucket(totals)

        def _iso(moment_ts: float) -> str | None:
            """Epoch → ISO (chegaradan chiqsa — ``None``, hisobot yiqilmaydi)."""
            try:
                return datetime.fromtimestamp(
                    float(moment_ts), tz=timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                return None

        return {
            "period": period,
            "window_start": _iso(start),
            "window_end": _iso(end),
            "scope": {"user_id": user_id, "channel_id": channel_id},
            "events_matched": matched,
            "totals": finished,
            "priced_requests": priced_requests,
            "unpriced_requests": unpriced_requests,
            "by_provider": {k: _finish_bucket(v) for k, v in sorted(by_provider.items())},
            "by_model": {k: _finish_bucket(v) for k, v in sorted(by_model.items())},
            "by_task": {k: _finish_bucket(v) for k, v in sorted(by_task.items())},
            "by_lane": {k: _finish_bucket(v) for k, v in sorted(by_lane.items())},
            "by_day": {k: _finish_bucket(v) for k, v in sorted(by_day.items())},
        }


# ---------------------------------------------------------------------------
# Yagona singleton (gateway va app service ishlatadi)
# ---------------------------------------------------------------------------
_default_recorder: UsageRecorder | None = None


def default_recorder() -> UsageRecorder:
    """Global telemetriya yozuvchisi (birinchi chaqiruvda quriladi)."""
    global _default_recorder
    if _default_recorder is None:
        _default_recorder = UsageRecorder()
    return _default_recorder


def reset_default_recorder() -> UsageRecorder:
    """Yozuvchini qayta quradi va yangisini qaytaradi (testlar uchun)."""
    global _default_recorder
    _default_recorder = UsageRecorder()
    return _default_recorder


def usage_report(
    *,
    user_id: int | None = None,
    channel_id: int | None = None,
    period: str = PERIOD_DAILY,
    now: datetime | None = None,
    recorder: UsageRecorder | None = None,
) -> dict:
    """Qulaylik: yagona yozuvchidan hisobot (``default_recorder``)."""
    return (recorder or default_recorder()).report(
        user_id=user_id, channel_id=channel_id, period=period, now=now
    )


__all__ = [
    # statuslar / davrlar
    "STATUS_SUCCESS", "STATUS_FAILED", "STATUSES",
    "PERIOD_DAILY", "PERIOD_MONTHLY", "PERIOD_ALL", "PERIODS",
    # token/narx
    "CHARS_PER_TOKEN", "estimate_tokens",
    "PriceSpec", "PRICE_TABLE", "price_spec", "is_priced", "estimate_cost",
    "set_price_override", "clear_price_overrides", "prompt_hash",
    # yozuv
    "AIUsageEvent", "build_usage_event",
    # yozuvchi
    "UsageRecorder", "DEFAULT_MAX_EVENTS",
    "default_recorder", "reset_default_recorder", "usage_report",
]


#: Kun/oy davrlari uchun qulay aliaslar (``timedelta`` import qilingan — API
#: kengaytmasi: hisobot oynasini qo'lda hisoblash uchun).
DAY = timedelta(days=1)
MONTH = timedelta(days=30)
