# -*- coding: utf-8 -*-
"""=====================================================================
 📮 TELEGRAM DELIVERY ENGINE — markazlashtirilgan yetkazib berish dvigateli
=====================================================================

PHASE 5: Telegram'ga yuboriladigan BARCHA post/media xabarlari yagona
quvurdan o'tadi. Hech bir integratsiya nuqtasi to'g'ridan-to'g'ri
``bot.send_message`` ga murojaat qilmaydi.

Asosiy qatlamlar:

1) **Rate limiting** (Telegram rasmiy limitlari):
   * 1 post/soniya — har bir kanal/chat uchun (``channel_per_second``);
   * 30 xabar/soniya — butun bot uchun umumiy (``global_per_second``);
   * holat bot instansiyasiga bog'lanadi (test fake botlari izolyatsiyalanadi).

2) **RetryAfter (429) boshqaruvi:**
   * Telegram ko'rsatgan **aniq** kutish vaqti + **jitter** (0..0.25s);
   * ``inline_max_wait`` chegarasigacha kutib qayta uriniladi;
   * scheduler kabi "defer" yo'lini tanlagan chaqiruvchi (inline=0) uchun
   *xato o'z holida qaytariladi* — aniq kutish DB'da (``retry_post``)
   boshqariladi (scheduler scheduler'dagi aniq kutish + jitter bilan).

3) **Failure classification** (degenerate xatolar darhol to'xtatish):
   * ``rate_limit``  — RetryAfter (aniq kutish + qayta urinish);
   * ``permanent``    — bot kicked / channel deleted / not enough rights /
     invalid HTML-parse (BadRequest) — **qayta urinilmaydi**, delivery
     ``FAILED``/``dead_letter`` bo'ladi (dead-letter);
   * ``ambiguous``    — TimedOut/NetworkError: so'rov Telegramga ketgan
     bo'lishi mumkin — **blind retry taqiqlanadi** (dublikat xavfi),
     holat ``UNKNOWN`` bo'ladi;
   * ``transient``    — ba'zi vaqtinchalik Telegram xatolari (backoff bilan).

4) **Idempotency & crash recovery** (``deliver_with_state``):
   DB'dagi ``post_deliveries`` qatorini atomik claim qiladi::

       pending ──claim──▶ processing (SENDING) ──▶ sent (DELIVERED)
                          │                        ▲
                          ├─ permanent ─▶ dead_letter (FAILED, qayta YO'Q)
                          ├─ rate_limit/transient ─▶ failed (backoff)
                          └─ ambiguous ─▶ unknown (blind retry YO'Q)

   Jarayon crash bo'lib qayta turganda claim qayta olinadi (stale) yoki
   ``sent`` bo'lsa 0 duplikat bilan skip qilinadi — bitta post kanalga
   HECH QACHON 2 marta chiqmaydi.

Foydalanish::

    from services.delivery import delivery_service

    # Transport (rate-limit + RetryAfter + classification):
    await delivery_service.send_message(bot, chat_id=..., text=...)

    # To'liq state-machine (idempotent, crash-safe):
    result = await delivery_service.deliver_with_state(
        post_id, channel_id, scheduled_time, send_fn, run=db.run_db,
    )
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import weakref

from services.scheduler_service import SchedulerService

logger = logging.getLogger(__name__)

# ── Rate limit (Telegram rasmiy limitlari) ─────────────────────────────────
GLOBAL_PER_SECOND = 30.0        # 30 xabar/soniya — butun bot uchun
CHANNEL_PER_SECOND = 1.0        # 1 post/soniya — har bir kanal/chat uchun

# ── RetryAfter kutish siyosati ─────────────────────────────────────────────
RETRY_JITTER_MAX = 0.25         # sekunda: aniq kutishga qo'shiladigan jitter
RETRY_AFTER_DEFAULT = 2.0       # buzilgan/0 retry_after uchun xavfsiz default
RETRY_AFTER_MIN = 1.0           # Telegram minimal maqul kutishi
RETRY_AFTER_MAX = 60.0          # dvigatel ichidagi yuqori chekka
DEFAULT_INLINE_MAX_WAIT = 8.0   # interaktiv handlerlar: uzun FloodWait kutmaydi
BROADCAST_INLINE_MAX_WAIT = 30.0  # broadcast fonda ishlaydi — uzroq kutish mumkin
NETWORK_BACKOFF_BASE = 1.0      # ambiguous tarmoq xatosidan keyin backoff asosi
NETWORK_BACKOFF_MAX = 5.0

# ── Failure classification qiymatlari ──────────────────────────────────────
FAILURE_PERMANENT = "permanent"
FAILURE_RATE_LIMIT = "rate_limit"
FAILURE_AMBIGUOUS = "ambiguous"
FAILURE_TRANSIENT = "transient"

_CONTROL_KEYS = ("max_attempts", "inline_max_wait", "retry_network")

#: Ism bo'yicha classifiatsiya — test fake klasslari uchun ham ishonchli.
_RATE_LIMIT_NAMES = ("RetryAfter",)
_AMBIGUOUS_NAMES = ("TimedOut", "NetworkError", "ConnectionError",
                    "TimeoutError", "ConnectError", "ReadError")
#: BadRequest PTB'da NetworkError subklassi — AVVAL shu nom tekshiriladi.
_PERMANENT_NAMES = ("BadRequest",)


def _extract_message_id(result):
    """Bot natijasidan telegram_message_id oladi (albom uchun ham)."""
    if result is None:
        return None
    if isinstance(result, bool):
        return None
    if isinstance(result, int):
        return int(result)
    if isinstance(result, (list, tuple)):
        for item in result:
            mid = _extract_message_id(item)
            if mid:
                return mid
        return None
    mid = getattr(result, "message_id", None)
    try:
        return int(mid) if mid is not None else None
    except (TypeError, ValueError):
        return None


class _IntervalLimiter:
    """Minimal interval limiter: kalit bo'yicha kamida ``interval`` sekunda bitta slot."""

    __slots__ = ("interval", "_next", "_clock", "max_keys")

    def __init__(self, interval: float, clock, max_keys: int = 1024):
        self.interval = max(0.0, float(interval))
        self._next = {}
        self._clock = clock
        self.max_keys = int(max_keys)

    def claim(self, key) -> float:
        """Slotni ro'yxatga oladi: 0 — hozir mumkin, >0 — shunchacha kutish kerak."""
        now = float(self._clock())
        nxt = self._next.get(key, 0.0)
        if now < nxt - 1e-9:
            return nxt - now
        self._next[key] = now + self.interval
        self._evict(now)
        return 0.0

    def _evict(self, now: float) -> None:
        # Xotira chegarasi: o'tgan slotlar tashlanadi (fail-safe, cheksiz o'smaslik uchun).
        while len(self._next) > self.max_keys:
            oldest = min(self._next, key=lambda k: self._next[k])
            if self._next[oldest] > now:
                # Hali faol slotlar — eng eskisini ham tashlaymiz (xavfsizlik tomoni).
                pass
            self._next.pop(oldest, None)


class TelegramDeliveryService:
    """Yagona Telegram yetkazib berish dvigateli (transport + state machine)."""

    def __init__(
        self,
        global_per_second: float = GLOBAL_PER_SECOND,
        channel_per_second: float = CHANNEL_PER_SECOND,
        jitter_max: float = RETRY_JITTER_MAX,
        default_inline_max_wait: float = DEFAULT_INLINE_MAX_WAIT,
    ):
        self.global_per_second = float(global_per_second)
        self.channel_per_second = float(channel_per_second)
        self.jitter_max = max(0.0, float(jitter_max))
        self.default_inline_max_wait = max(0.0, float(default_inline_max_wait))

        # Test uchun injectable: real sleep/soat o'rniga deterministik qo'yiladi.
        self._sleep = asyncio.sleep
        self._mono = time.monotonic

        self._per_bot = weakref.WeakKeyDictionary()
        self._fallback_limiters = {}   # weakref qo'llab-quvvatlanmaydigan botlar uchun

        # ── State machine (post_deliveries): funksiyalar SHU identity bilan
        #    delegate qilinadi — mavjud mock nuqtalari (``__name__`` bo'yicha
        #    dispatch) buzilmaydi. PENDING → SENDING → DELIVERED shu yerda.
        self.claim_post_for_delivery = SchedulerService.claim_post_for_delivery
        self.mark_as_sent = SchedulerService.mark_as_sent
        self.mark_sent_by_key = SchedulerService.mark_sent_by_key
        self.mark_as_failed = SchedulerService.mark_as_failed
        self.mark_failed_by_key = SchedulerService.mark_failed_by_key
        self.mark_unknown_by_key = SchedulerService.mark_unknown_by_key
        self.build_idempotency_key = SchedulerService.build_idempotency_key
        self.STATUS_PENDING = SchedulerService.STATUS_PENDING
        self.STATUS_PROCESSING = SchedulerService.STATUS_PROCESSING
        self.STATUS_SENT = SchedulerService.STATUS_SENT
        self.STATUS_FAILED = SchedulerService.STATUS_FAILED
        self.STATUS_DEAD_LETTER = SchedulerService.STATUS_DEAD_LETTER
        self.STATUS_UNKNOWN = SchedulerService.STATUS_UNKNOWN

    # ──────────────────────────────────────────────────────────────
    # CLASSIFICATION
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def classify(error) -> str:
        """Xatoni failure klassiga ajratadi.

        * ``rate_limit`` — RetryAfter (aniq kutish + qayta urinish);
        * ``permanent``   — bot kicked / kanal o'chirilgan / huquq yo'q /
          invalid HTML (BadRequest) — darhol to'xtash, dead-letter/FAILED;
        * ``ambiguous``   — so'rov Telegramga borgan bo'lishi mumkin
          (TimedOut/NetworkError) — blind retry taqiqlanadi (UNKNOWN);
        * ``transient``   — boshqa vaqtinchalik xatolar (backoff).
        """
        if error is None:
            return FAILURE_TRANSIENT
        name = type(error).__name__
        if name in _RATE_LIMIT_NAMES:
            return FAILURE_RATE_LIMIT
        if name in _PERMANENT_NAMES:
            # BadRequest: noto'g'ri HTML/markup yoki yaroqsiz so'rov —
            # qayta urinish foydasiz (parser xatosi ham shu yerda).
            return FAILURE_PERMANENT
        if SchedulerService.is_permanent_error(error):
            return FAILURE_PERMANENT
        if name in _AMBIGUOUS_NAMES:
            return FAILURE_AMBIGUOUS
        return FAILURE_TRANSIENT

    @staticmethod
    def is_permanent(error) -> bool:
        """Doimiy (qayta tuzatib bo'lmaydigan) xato mi?"""
        return TelegramDeliveryService.classify(error) == FAILURE_PERMANENT

    # ──────────────────────────────────────────────────────────────
    # RETRYAFTER — aniq kutish + jitter
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def retry_after_seconds(error, default: float = RETRY_AFTER_DEFAULT) -> float:
        """``RetryAfter`` uchun aniq kutish (soniya), [1.0, 60.0] oralig'ida.

        Telegram ba'zan ``retry_after`` ni ``None``/``0``/str qaytaradi —
        bunda default qo'llanadi. Hech qachon ``TypeError`` bo'lmaydi.
        """
        raw = getattr(error, "retry_after", None)
        try:
            value = float(raw) if raw is not None else float(default)
        except (TypeError, ValueError):
            value = float(default)
        if value <= 0:
            value = float(default)
        return max(RETRY_AFTER_MIN, min(value, RETRY_AFTER_MAX))

    def retry_jitter(self) -> float:
        """Jitter: 0..jitter_max sekunda tasodifiy qo'shimcha."""
        if self.jitter_max <= 0:
            return 0.0
        return random.uniform(0.0, self.jitter_max)

    def retry_wait_with_jitter(self, error) -> float:
        """429 uchun ANIQ kutish vaqti + jitter (dvigatelning qayta urinish vaqti)."""
        return self.retry_after_seconds(error) + self.retry_jitter()

    # ──────────────────────────────────────────────────────────────
    # RATE LIMITING
    # ──────────────────────────────────────────────────────────────
    def _limiters_for(self, bot):
        """Bot instansiyasiga bog'langan (global + per-channel) limiterlar."""
        channel_interval = 1.0 / self.channel_per_second if self.channel_per_second > 0 else 0.0
        global_interval = 1.0 / self.global_per_second if self.global_per_second > 0 else 0.0
        try:
            lims = self._per_bot.get(bot)
            if lims is None:
                lims = {
                    "channel": _IntervalLimiter(channel_interval, lambda: self._mono()),
                    "global": _IntervalLimiter(global_interval, lambda: self._mono()),
                }
                self._per_bot[bot] = lims
            return lims
        except TypeError:
            # weakref qo'llab-quvvatlanmaydigan nadir botlar — kichik fallback.
            key = id(bot)
            lims = self._fallback_limiters.get(key)
            if lims is None:
                if len(self._fallback_limiters) > 64:
                    self._fallback_limiters.clear()
                lims = {
                    "channel": _IntervalLimiter(channel_interval, lambda: self._mono()),
                    "global": _IntervalLimiter(global_interval, lambda: self._mono()),
                }
                self._fallback_limiters[key] = lims
            return lims

    async def _acquire_slot(self, limiter, key) -> None:
        """Slot ochilmaguncha kutadi (event-loop do'stli — fake sleep bilan testlanadi)."""
        while True:
            wait = limiter.claim(key)
            if wait <= 0:
                return
            await self._sleep(wait)

    async def _acquire(self, bot, chat_id) -> None:
        """1 post/s (kanal) + 30 msg/s (umumiy) limitlarini kafolatlaydi."""
        lims = self._limiters_for(bot)
        if chat_id is not None:
            await self._acquire_slot(lims["channel"], str(chat_id))
        await self._acquire_slot(lims["global"], None)

    # ──────────────────────────────────────────────────────────────
    # TRANSPORT — barcha kanal yuborishlari shu yerdan o'tadi
    # ──────────────────────────────────────────────────────────────
    async def execute(
        self,
        bot,
        method: str,
        *,
        max_attempts: int = 3,
        inline_max_wait=None,
        retry_network: bool = False,
        **kwargs,
    ):
        """``bot.<method>`` ni rate-limit + RetryAfter + classification bilan chaqiradi.

        * RetryAfter: aniq kutish + jitter bilan ``max_attempts`` gacha inline
          qayta uriniladi (``inline_max_wait`` dan oshsa — xato chaqiruvchiga
          qaytariladi; scheduler defer rejimida DB orqali kutadi).
        * ``retry_network=True`` bo'lsa ambiguous (TimedOut/NetworkError)
          backoff bilan qayta uriniladi (broadcast kabi fonda oqimlar uchun).
        * Doimiy xatolar (bot kicked / BadRequest) HECH qayta urinilmaydi —
          asl istisno o'z holida qaytariladi (dead-letter/fallback chaqiruvchida).
        * Qaytarilgan qiymat bot'nikiday — hech qanday o'zgartirilmaydi.

        Eslatma: yagona SSOT HTML sanitizatsiyasi ``SafeHTMLBot`` chegarasida
        (``utils.telegram_delivery``) qoladi — bu dvigatel sanitizatsiyani
        takrorlamaydi, faqat kvotani/retry/status boshqaradi.
        """
        attempts = max(1, int(max_attempts or 1))
        if inline_max_wait is None:
            inline_max = self.default_inline_max_wait
        else:
            inline_max = max(0.0, float(inline_max_wait))
        chat_id = kwargs.get("chat_id")
        attempt = 0
        while True:
            attempt += 1
            await self._acquire(bot, chat_id)
            try:
                func = getattr(bot, method)
                return await func(**kwargs)
            except Exception as exc:
                cls = self.classify(exc)
                if cls == FAILURE_RATE_LIMIT and attempt < attempts:
                    wait = self.retry_wait_with_jitter(exc)
                    if inline_max > 0 and wait <= inline_max:
                        logger.info(
                            "Delivery: Telegram 429 — %.2fs aniq kutish + jitter "
                            "(urinish %d/%d, chat=%s)", wait, attempt, attempts, chat_id,
                        )
                        await self._sleep(wait)
                        continue
                    # Defer rejim (scheduler) yoki juda uzun kutish:
                    # aniq kutish chaqiruvchi tomonida (DB retry_post + jitter).
                    raise
                if cls == FAILURE_AMBIGUOUS and retry_network and attempt < attempts:
                    delay = min(NETWORK_BACKOFF_BASE * attempt, NETWORK_BACKOFF_MAX) + self.retry_jitter()
                    logger.info(
                        "Delivery: tarmoq xatosi — %.2fs backoff bilan qayta urinish "
                        "(%d/%d, chat=%s)", delay, attempt, attempts, chat_id,
                    )
                    await self._sleep(delay)
                    continue
                # Doimiy xato yoki urinishlar tugadi — ASL istisno qaytadi.
                raise

    async def send_message(self, bot, **kwargs):
        return await self._send_via("send_message", bot, **kwargs)

    async def send_photo(self, bot, **kwargs):
        return await self._send_via("send_photo", bot, **kwargs)

    async def send_video(self, bot, **kwargs):
        return await self._send_via("send_video", bot, **kwargs)

    async def send_animation(self, bot, **kwargs):
        return await self._send_via("send_animation", bot, **kwargs)

    async def send_document(self, bot, **kwargs):
        return await self._send_via("send_document", bot, **kwargs)

    async def send_audio(self, bot, **kwargs):
        return await self._send_via("send_audio", bot, **kwargs)

    async def send_voice(self, bot, **kwargs):
        return await self._send_via("send_voice", bot, **kwargs)

    async def send_sticker(self, bot, **kwargs):
        return await self._send_via("send_sticker", bot, **kwargs)

    async def send_media_group(self, bot, **kwargs):
        return await self._send_via("send_media_group", bot, **kwargs)

    async def _send_via(self, method: str, bot, **kwargs):
        """Qisqa yo'l: nazorat parametrlarini ajratib, execute'ga uzatadi."""
        opts = {key: kwargs.pop(key) for key in _CONTROL_KEYS if key in kwargs}
        return await self.execute(bot, method, **opts, **kwargs)

    # ──────────────────────────────────────────────────────────────
    # STATE MACHINE — PENDING → SENDING → DELIVERED (idempotent)
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    async def _default_run(fn, *args, **kwargs):
        """DB offload adapteri (``database.run_db``) — kech import, testda almashtiriladi."""
        import database
        return await database.run_db(fn, *args, **kwargs)

    async def deliver_with_state(
        self,
        post_id,
        channel_id,
        scheduled_time,
        send,
        *,
        run=None,
        idempotency_key=None,
    ) -> dict:
        """Idempotent delivery: DB claim lock'i bilan PENDING→SENDING→DELIVERED.

        ``send`` — async callable: bitta Telegram urinishini bajaradi (o'zi ham
        ``execute`` orqali rate-limit/RetryAfter'dan o'tgan bo'lishi kerak).

        Qaytadi::

            {"status": "sent", "claimed": True, "message_id": int, ...}
            {"status": "sent", "duplicate": True, ...}          # 0 duplikat
            {"status": "processing"/"retry_pending", ...}        # boshqa worker/backoff
            {"status": "dead_letter", "classification": "permanent", ...}
            {"status": "failed", ...}                            # backoff bilan qayta
            {"status": "unknown", ...}                           # blind retry YO'Q
            {"status": "error", ...}                             # DB yozilmadi — YUBORILMAYDI
        """
        run = run or self._default_run
        try:
            claim = await run(
                self.claim_post_for_delivery, post_id, channel_id, scheduled_time
            )
        except Exception as exc:
            # Fail-closed: claim bo'lmasa yuborish YO'Q (crash dublikat oldini olish).
            logger.error("deliver_with_state: claim olinmadi (post=%s): %s", post_id, exc)
            return {"status": "error", "claimed": False, "reason": "claim_failed",
                    "idempotency_key": idempotency_key or ""}
        if not isinstance(claim, dict):
            claim = {"claimed": False, "status": "invalid_claim"}
        key = claim.get("idempotency_key") or idempotency_key

        if claim.get("sent") or claim.get("status") == self.STATUS_SENT:
            return {"status": self.STATUS_SENT, "claimed": False, "duplicate": True,
                    "message_id": claim.get("message_id"),
                    "idempotency_key": claim.get("idempotency_key") or key}
        if claim.get("dead") or claim.get("status") == self.STATUS_DEAD_LETTER:
            return {"status": self.STATUS_DEAD_LETTER, "claimed": False,
                    "idempotency_key": key}
        if claim.get("unknown") or claim.get("status") == self.STATUS_UNKNOWN:
            return {"status": self.STATUS_UNKNOWN, "claimed": False,
                    "idempotency_key": key}
        if not claim.get("claimed"):
            # processing (boshqa worker) / retry_pending (backoff) / invalid.
            return {"status": claim.get("status") or "busy", "claimed": False,
                    "retry_pending": bool(claim.get("retry_pending")),
                    "idempotency_key": key}

        # ── SENDING: claim qo'lida — endi xavfsiz yuborish mumkin ──
        try:
            result = await send()
        except Exception as exc:
            cls = self.classify(exc)
            return await self._record_failure(run, post_id, channel_id, scheduled_time,
                                              key, exc, cls)

        # ── DELIVERED: sent markeri yoziladi (qayta chaqiruv xavfsiz) ──
        message_id = _extract_message_id(result)
        persisted = True
        try:
            persisted = bool(await run(
                self.mark_as_sent, post_id, channel_id, message_id,
                scheduled_time, key,
            ))
        except Exception as exc:
            persisted = False
            logger.error("deliver_with_state: sent marker yozilmadi (post=%s): %s",
                         post_id, exc)
        return {"status": self.STATUS_SENT, "claimed": True,
                "message_id": message_id, "persisted": persisted,
                "idempotency_key": key}

    async def _record_failure(self, run, post_id, channel_id, scheduled_time,
                              key, error, cls) -> dict:
        """Xato klassiga mos holat: dead_letter / failed / unknown (FAILED darhol)."""
        if not key:
            return {"status": "error", "claimed": True, "classification": cls,
                    "reason": "missing_key", "error": str(error)[:400]}
        try:
            if cls == FAILURE_AMBIGUOUS:
                # So'rov ketgan bo'lishi mumkin — blind retry dublikat chiqaradi.
                await run(self.mark_unknown_by_key, key, error)
                return {"status": self.STATUS_UNKNOWN, "claimed": True,
                        "classification": cls, "idempotency_key": key,
                        "error": str(error)[:400]}
            transient = cls in (FAILURE_TRANSIENT, FAILURE_RATE_LIMIT)
            res = await run(self.mark_failed_by_key, key, error, transient)
            if isinstance(res, dict) and res.get("status"):
                status = res["status"]
            else:
                # DB natijasi yo'q — konservativ: permanent darhol FAILED.
                status = (self.STATUS_FAILED if transient
                          else self.STATUS_DEAD_LETTER)
            return {"status": status, "claimed": True, "classification": cls,
                    "idempotency_key": key, "error": str(error)[:400]}
        except Exception as exc:
            logger.error("deliver_with_state: failure marker yozilmadi (post=%s): %s",
                         post_id, exc)
            return {"status": "error", "claimed": True, "classification": cls,
                    "reason": "mark_failed_error", "idempotency_key": key}


def get_delivery_service() -> TelegramDeliveryService:
    """Yagona dvigatel instansiyasi."""
    return delivery_service


#: Butun bot davomida bitta delivery engine.
delivery_service = TelegramDeliveryService()
