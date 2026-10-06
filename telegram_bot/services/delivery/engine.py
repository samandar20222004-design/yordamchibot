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
import hashlib
import logging
import random
import re
import time
import unicodedata
import uuid
import weakref
from datetime import datetime, timezone

from services import lifecycle_service as lifecycle
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

# ── P0: NOANIQ (AMBIGUOUS) YETKAZIB BERISHNI KANAL BO'YICHA HAL QILISH ─────
# TimedOut/NetworkError'da so'rov Telegramga KETGAN bo'lishi mumkin. Avtomatik
# (ko'r-ko'rrona) retry bitta postni kanalga IKKI MARTA chiqaradi. Shuning
# uchun qayta urinishdan OLDIN kanalning oxirgi xabarlari tekshiriladi:
#   * topilsa        → holat DELIVERED (takroriy yuborish YO'Q);
#   * yo'qligi aniq  → xavfsiz qayta yuborish;
#   * tasdiqlanmasa  → verify_pending (keyinroq yana tekshiriladi, yuborilmaydi),
#                      urinishlar tugagach — UNKNOWN (admin ko'radi).
AMBIGUOUS_VERIFY_LIMIT = 5           # kanaldan o'qiladigan oxirgi xabarlar soni
AMBIGUOUS_VERIFY_TAIL_CHARS = 120    # matn oxiri (kesilish/format farqi uchun)
AMBIGUOUS_VERIFY_MAX_ATTEMPTS = 3    # tasdiqlanmasa shu qadar tekshiruv
AMBIGUOUS_VERIFY_DELAY = 30.0        # keyingi tekshiruvgacha kutish (soniya)
AMBIGUOUS_VERIFY_WINDOW = 900.0      # kanal xabari vaqt oynasi (soniya)

#: Kanal tekshiruvi xulosalari.
VERIFY_PRESENT = "present"
VERIFY_ABSENT = "absent"
VERIFY_UNAVAILABLE = "unavailable"

# ── P0: IDEMPOTENT DELIVERY LOCK (bir post — bir marta yuboriladi) ─────────
# Uch qatlam: (1) DB claim — atomik, barcha worker'lar uchun asosiy kafolat;
# (2) in-process asyncio lock — bitta jarayondagi tasklar uchun;
# (3) Redis `SET NX` (cache backend) — bir nechta instansiya uchun (bo'lsa).
DELIVERY_LOCK_TTL = 120.0            # lock TTL (crash bo'lsa o'zi bo'shaydi)
DELIVERY_LOCK_RETRY_DELAY = 10.0     # lock band bo'lsa qayta urinish (soniya)
DELIVERY_LOCAL_LOCKS_MAX = 2048      # in-process lock jadvali chegarasi

#: ``post_deliveries.last_error`` ichidagi "verify kutilmoqda" belgisi —
#: DB (repository), scheduler va engine uchun YAGONA format.
VERIFY_PENDING_MARKER = "AMBIGUOUS_VERIFY"
_VERIFY_ATTEMPT_RE = re.compile(re.escape(VERIFY_PENDING_MARKER) + r"\s+attempt=(\d+)")

_MEDIA_TYPES = ("photo", "video", "animation", "document", "audio", "voice", "sticker")
_CANDIDATE_TEXT_KEYS = ("text", "caption", "content", "message", "body")
_CANDIDATE_DATE_KEYS = ("date", "post_date", "created_at", "timestamp")
_CANDIDATE_MEDIA_KEYS = ("media_url", "media", "file_id", "file_unique_id", "photo",
                         "video", "document", "animation", "audio", "voice", "sticker")

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


# ──────────────────────────────────────────────────────────────────────
# FINGERPRINT (SHA256) — postni kanaldagi xabar bilan solishtirish
# ──────────────────────────────────────────────────────────────────────
def sha256_fingerprint(value: str) -> str:
    """Matnning SHA256 heshi (hex)."""
    return hashlib.sha256(str(value).encode("utf-8", "ignore")).hexdigest()


def normalize_fingerprint_text(value) -> str:
    """Fingerprint uchun matnni normallashtiradi (format farqlariga bardosh)."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value).replace("\r\n", "\n").replace("\r", "\n"))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def post_media_count(post_type, file_id) -> int:
    """Postdagi media elementlari soni (albom uchun JSON ro'yxati uzunligi)."""
    pt = str(post_type or "").lower()
    if pt in ("album", "media_group"):
        if not file_id:
            return 0
        try:
            import json
            items = json.loads(file_id) if isinstance(file_id, str) else file_id
            return max(1, len(list(items))) if items else 0
        except Exception:
            return 1
    if pt in ("text", "", "poll", "quiz"):
        return 0
    if pt in _MEDIA_TYPES:
        return 1 if file_id else 0
    return 1 if file_id else 0


def build_delivery_signature(text=None, *, media_count: int = 0, marker=None) -> dict:
    """Yuborilayotgan post uchun solishtirish "imzosi" (SHA256 to'plami).

    ``text`` — kanalga CHIQADIGAN yakuniy matn (watermark/reklama qo'shilgan).
    Kanal tekshiruvi shu imzo bo'yicha oxirgi xabarlarni qidiradi.
    """
    normalized = normalize_fingerprint_text(text)
    marker_text = str(marker) if marker else ""
    tail_hash = ""
    if len(normalized) > AMBIGUOUS_VERIFY_TAIL_CHARS:
        tail_hash = sha256_fingerprint("tail:" + normalized[-AMBIGUOUS_VERIFY_TAIL_CHARS:])
    fingerprints = set()
    if normalized:
        fingerprints.add(sha256_fingerprint("text:" + normalized))
        if tail_hash:
            fingerprints.add(tail_hash)
    if marker_text:
        fingerprints.add(sha256_fingerprint("marker:" + marker_text))
    return {
        "text": normalized,
        "text_hash": sha256_fingerprint("text:" + normalized) if normalized else "",
        "tail_hash": tail_hash,
        "marker": marker_text,
        "media_count": max(0, int(media_count or 0)),
        "fingerprints": fingerprints,
    }


def _candidate_text(item) -> str:
    if isinstance(item, dict):
        for key in _CANDIDATE_TEXT_KEYS:
            value = item.get(key)
            if value:
                return normalize_fingerprint_text(value)
        return ""
    if isinstance(item, str):
        return normalize_fingerprint_text(item)
    for key in _CANDIDATE_TEXT_KEYS:
        value = getattr(item, key, None)
        if value:
            return normalize_fingerprint_text(value)
    return ""


def _candidate_media_count(item) -> int:
    count = 0
    for key in _CANDIDATE_MEDIA_KEYS:
        value = item.get(key) if isinstance(item, dict) else getattr(item, key, None)
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            count += max(1, len(value))
        else:
            count += 1
    return count


def _parse_moment(value):
    """Sana/vaqtni tz-aware ``datetime`` ga keltiradi (imkonsiz bo'lsa ``None``)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def candidate_matches_signature(signature, item, *,
                                now=None, window: float = AMBIGUOUS_VERIFY_WINDOW) -> bool:
    """Kanal xabari kutilgan post bilan bir xilmi?

    1. To'liq matn SHA256 heshi mos → HA (eng ishonchli signal);
    2. matn oxiri (``tail``) heshi mos → HA (Telegram kesishi/format farqi);
    3. noyob marker matnda bor → HA;
    4. matnsiz (faqat media) post: media soni mos VA vaqt oynasida → HA.
    """
    if not signature or item is None:
        return False
    text = _candidate_text(item)
    expected_text_hash = signature.get("text_hash") or ""
    tail_hash = signature.get("tail_hash") or ""
    marker = signature.get("marker") or ""

    if expected_text_hash and text:
        if sha256_fingerprint("text:" + text) == expected_text_hash:
            return True
    if tail_hash and text:
        if sha256_fingerprint("tail:" + text[-AMBIGUOUS_VERIFY_TAIL_CHARS:]) == tail_hash:
            return True
    if marker and marker in text:
        return True

    # Matnsiz media post: faqat media borligi + vaqt oynasi bo'yicha.
    if not expected_text_hash and not marker and int(signature.get("media_count") or 0) > 0:
        if not text and _candidate_media_count(item) > 0:
            stamp = _parse_moment(next(
                (item.get(k) for k in _CANDIDATE_DATE_KEYS if isinstance(item, dict) and item.get(k)),
                None,
            )) if isinstance(item, dict) else None
            moment = now if isinstance(now, datetime) else None
            if stamp is None or moment is None:
                return False
            return abs((moment - stamp).total_seconds()) <= float(window)
    return False


def evaluate_channel_probe(probe_result, signature, *,
                           now=None, window: float = AMBIGUOUS_VERIFY_WINDOW):
    """Kanal tekshiruvi natijasini baholaydi.

    ``probe_result`` — ``{"status": "ok"|"unavailable", "items": [...]}`` yoki
    shunchaki xabarlar ro'yxati. Qaytadi: ``(verdict, matched_item)``.

    * ``present``     — post kanalda BOR (dublikat yuborilmaydi);
    * ``absent``      — kanal O'QILDI va post YO'Q (xavfsiz qayta yuborish);
    * ``unavailable`` — kanal o'qilmadi (ko'r-ko'rrona retry TAQIQLANADI).
    """
    if isinstance(probe_result, dict):
        status = str(probe_result.get("status") or "").lower()
        items = probe_result.get("items")
        if status and status not in ("ok", "success", "ready"):
            return VERIFY_UNAVAILABLE, None
    else:
        items = probe_result
    if items is None:
        return VERIFY_UNAVAILABLE, None
    try:
        candidates = list(items)
    except TypeError:
        return VERIFY_UNAVAILABLE, None
    if not candidates:
        # Bo'sh ro'yxat "yo'qligi tasdiqlandi" degani EMAS (parser/o'qish
        # nosozligi bo'lishi mumkin) — konservativ: tasdiqlanmadi.
        return VERIFY_UNAVAILABLE, None
    moment = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    for item in candidates:
        if candidate_matches_signature(signature, item, now=moment, window=window):
            return VERIFY_PRESENT, item
    return VERIFY_ABSENT, None


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

    # P0: noaniq yetkazib berish / dedup / lock sozlamalari (instance'dan ham
    # o'qiladi — scheduler va testlar shu yagona manbadan foydalanadi).
    AMBIGUOUS_VERIFY_LIMIT = AMBIGUOUS_VERIFY_LIMIT
    AMBIGUOUS_VERIFY_MAX_ATTEMPTS = AMBIGUOUS_VERIFY_MAX_ATTEMPTS
    AMBIGUOUS_VERIFY_DELAY = AMBIGUOUS_VERIFY_DELAY
    AMBIGUOUS_VERIFY_WINDOW = AMBIGUOUS_VERIFY_WINDOW
    DELIVERY_LOCK_TTL = DELIVERY_LOCK_TTL
    DELIVERY_LOCK_RETRY_DELAY = DELIVERY_LOCK_RETRY_DELAY
    VERIFY_PENDING_MARKER = VERIFY_PENDING_MARKER

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
        # P0: noaniq (UNKNOWN) holatni kanal tekshiruvi bilan hal qilish uchun
        # verify_pending markerini yozuvchi/tozalovchi DB funksiyalari.
        self.mark_verify_pending_by_key = SchedulerService.mark_verify_pending_by_key
        self.clear_verify_pending_by_key = SchedulerService.clear_verify_pending_by_key
        self.build_idempotency_key = SchedulerService.build_idempotency_key
        self.STATUS_PENDING = SchedulerService.STATUS_PENDING
        self.STATUS_PROCESSING = SchedulerService.STATUS_PROCESSING
        self.STATUS_SENT = SchedulerService.STATUS_SENT
        self.STATUS_FAILED = SchedulerService.STATUS_FAILED
        self.STATUS_DEAD_LETTER = SchedulerService.STATUS_DEAD_LETTER
        self.STATUS_UNKNOWN = SchedulerService.STATUS_UNKNOWN

        # P0: bir jarayon ichida bir xil delivery kaliti bilan yuborishni
        # to'suvchi in-process lock jadvali (DB claim'ga qo'shimcha qatlam).
        self._local_locks: dict = {}

    # ──────────────────────────────────────────────────────────────
    # P0: FINGERPRINT / KANAL TEKSHIRUVI (ambiguous resolution)
    # ──────────────────────────────────────────────────────────────
    build_delivery_signature = staticmethod(build_delivery_signature)
    post_media_count = staticmethod(post_media_count)
    normalize_fingerprint_text = staticmethod(normalize_fingerprint_text)
    sha256_fingerprint = staticmethod(sha256_fingerprint)

    @staticmethod
    def delivery_verify_pending(last_error) -> bool:
        """``last_error`` da "kanal tekshiruvi kutilmoqda" markeri bormi?"""
        return bool(_VERIFY_ATTEMPT_RE.search(str(last_error or "")))

    @staticmethod
    def delivery_verify_attempt(last_error) -> int:
        """Markerdagi tekshiruv urinish raqami (marker yo'q bo'lsa 0)."""
        match = _VERIFY_ATTEMPT_RE.search(str(last_error or ""))
        if not match:
            return 0
        try:
            return max(0, int(match.group(1)))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def build_verify_marker(attempt, error=None) -> str:
        """verify_pending uchun ``last_error`` matni (yagona format)."""
        try:
            attempt = max(1, int(attempt))
        except (TypeError, ValueError):
            attempt = 1
        detail = str(error or "")[:300]
        return f"{VERIFY_PENDING_MARKER} attempt={attempt}" + (f" | {detail}" if detail else "")

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
        # PHASE 12 · GRACEFUL SHUTDOWN: yuborilayotgan har bir xabar "delivery"
        # navbatida band hisoblanadi. Shutdown boshlanganda main.py aynan shu
        # hisoblagichni kutib turadi (lifecycle.wait_for_queues) — navbat
        # drenajsiz konteyner yopilmaydi (post yarim yo'lda tashlanmaydi).
        with lifecycle.track_queue("delivery"):
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
    # P0: NOANIQ YETKAZIB BERISHNI HAL QILISH (kanal deduplikatsiyasi)
    # ──────────────────────────────────────────────────────────────
    async def resolve_ambiguous(
        self,
        *,
        probe,
        channel_id=None,
        signature=None,
        attempt: int = 1,
        max_attempts: int = AMBIGUOUS_VERIFY_MAX_ATTEMPTS,
        run=None,
        key=None,
        error=None,
        delay: float = AMBIGUOUS_VERIFY_DELAY,
        now=None,
    ) -> dict:
        """TimedOut/NetworkError bilan noaniq qolgan holatni hal qiladi.

        ``probe`` — kanalning oxirgi xabarlarini qaytaruvchi natija
        (``{"status": "ok"|"unavailable", "items": [...]}`` yoki ro'yxat).
        Qaytadi::

            {"status": "sent",   "verdict": "present",     ...}  # DELIVERED
            {"status": "ready",  "verdict": "absent",      ...}  # xavfsiz retry
            {"status": "verify_pending", "verdict": "unavailable", ...}
            {"status": "unknown","verdict": "unavailable", "attempt": n}

        Muhim: ``unavailable`` holatda Telegramga QAYTA YUBORILMAYDI —
        holat keyingi tekshiruvgacha (yoki UNKNOWN bo'lgunga qadar) saqlanadi.
        """
        run = run or self._default_run
        try:
            attempt = max(1, int(attempt))
        except (TypeError, ValueError):
            attempt = 1
        try:
            max_attempts = max(1, int(max_attempts))
        except (TypeError, ValueError):
            max_attempts = AMBIGUOUS_VERIFY_MAX_ATTEMPTS

        verdict, matched = evaluate_channel_probe(probe, signature, now=now)
        result = {
            "verdict": verdict,
            "attempt": attempt,
            "channel_id": channel_id,
            "idempotency_key": key or "",
        }
        if matched is not None:
            result["matched_message_id"] = (
                matched.get("message_id") if isinstance(matched, dict)
                else getattr(matched, "message_id", None)
            )

        if verdict == VERIFY_PRESENT:
            # Post allaqachon kanalda — DELIVERED (dublikat YO'Q).
            message_id = result.get("matched_message_id")
            persisted = False
            if key:
                try:
                    persisted = bool(await run(self.mark_sent_by_key, key, message_id))
                except Exception as exc:  # noqa: BLE001 — marker yozilmasa ham yubormaymiz
                    logger.error(
                        "resolve_ambiguous: 'sent' marker yozilmadi (%s): %s", key, exc,
                    )
            if key:
                try:
                    await run(self.clear_verify_pending_by_key, key)
                except Exception:  # noqa: BLE001
                    pass
            logger.warning(
                "Delivery ANIQLANDI: post kanalda allaqachon bor (kanal=%s, "
                "message_id=%s) — qayta yuborilmaydi (0 duplikat).",
                channel_id, message_id,
            )
            result.update({"status": self.STATUS_SENT, "claimed": True,
                           "verified_duplicate": True, "persisted": persisted})
            return result

        if verdict == VERIFY_ABSENT:
            # Kanal o'qildi va post YO'Q — xavfsiz qayta yuborish mumkin.
            if key:
                try:
                    await run(self.clear_verify_pending_by_key, key)
                except Exception:  # noqa: BLE001
                    pass
            logger.info(
                "Delivery tekshirildi: post kanalda YO'Q (kanal=%s) — xavfsiz qayta urinish.",
                channel_id,
            )
            result.update({"status": "ready", "safe_retry": True})
            return result

        # ── Tasdiqlab bo'lmadi: ko'r-ko'rrona retry TAQIQLANADI ──
        if attempt >= max_attempts:
            if key:
                try:
                    await run(self.mark_unknown_by_key, key, error)
                except Exception as exc:  # noqa: BLE001
                    logger.error("resolve_ambiguous: unknown marker xatosi (%s): %s", key, exc)
            logger.error(
                "Delivery UNKNOWN: kanal tekshiruvi %s urinishda ham post borligini/"
                "yo'qligini tasdiqlamadi (kanal=%s) — avtomatik yuborish TAQIQLANADI.",
                attempt, channel_id,
            )
            result.update({"status": self.STATUS_UNKNOWN, "claimed": True})
            return result

        if key:
            try:
                await run(self.mark_verify_pending_by_key, key, error, attempt, delay)
            except Exception as exc:  # noqa: BLE001
                logger.error("resolve_ambiguous: verify_pending yozilmadi (%s): %s", key, exc)
        logger.warning(
            "Delivery VERIFY_PENDING: kanal tekshiruvi natijasiz (kanal=%s, urinish %s/%s) — "
            "%.0fs dan keyin yana tekshiriladi, Telegramga yuborilmaydi.",
            channel_id, attempt, max_attempts, delay,
        )
        result.update({"status": "verify_pending", "retry_in": float(delay)})
        return result

    async def verify_channel_delivery(
        self,
        *,
        probe,
        channel_id=None,
        post_type=None,
        content=None,
        file_id=None,
        marker=None,
        attempt: int = 1,
        **kwargs,
    ) -> dict:
        """Qulaylik: postdan imzo qurib, :meth:`resolve_ambiguous` ni chaqiradi."""
        signature = self.build_delivery_signature(
            content,
            media_count=self.post_media_count(post_type, file_id),
            marker=marker,
        )
        return await self.resolve_ambiguous(
            probe=probe, channel_id=channel_id, signature=signature,
            attempt=attempt, **kwargs,
        )

    # ──────────────────────────────────────────────────────────────
    # P0: IDEMPOTENT DELIVERY LOCK (in-process + Redis SET NX)
    # ──────────────────────────────────────────────────────────────
    def _local_lock_for(self, key: str) -> asyncio.Lock:
        """Kalit uchun in-process ``asyncio.Lock`` (jadval chegaralangan)."""
        lock = self._local_locks.get(key)
        if lock is None:
            if len(self._local_locks) >= DELIVERY_LOCAL_LOCKS_MAX:
                for stale in [k for k, item in self._local_locks.items() if not item.locked()]:
                    self._local_locks.pop(stale, None)
                    if len(self._local_locks) < DELIVERY_LOCAL_LOCKS_MAX:
                        break
            lock = self._local_locks.setdefault(key, asyncio.Lock())
        return lock

    @staticmethod
    def _cache_backend():
        """Cache backend (bo'lmasa ``None``) — Redis lock qatlami uchun."""
        try:
            from services import cache_backend as cb
            return cb.get_cache_backend()
        except Exception:  # noqa: BLE001 — lock qatlami hech qachon botni yiqitmasin
            return None

    async def acquire_delivery_lock(self, key, *, ttl: float = DELIVERY_LOCK_TTL,
                                    timeout: float = 0.0):
        """Post uchun qo'shimcha atomik lock (in-process + ixtiyoriy Redis).

        DB claim allaqachon atomik kafolat beradi; bu qatlam bir jarayondagi
        tasklar va (Redis mavjud bo'lsa) instansiyalar orasidagi parallel
        yuborishni to'sadi. ``None`` — lock band (yuborish YO'Q); aks holda
        release uchun token qaytadi.
        """
        if not key:
            return ""
        lock_key = str(key)
        local = self._local_lock_for(lock_key)
        try:
            if timeout and float(timeout) > 0:
                await asyncio.wait_for(local.acquire(), timeout=float(timeout))
            else:
                if local.locked():
                    return None
                await local.acquire()
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return None

        token = uuid.uuid4().hex
        try:
            backend = self._cache_backend()
            setter = getattr(backend, "set_if_absent", None)
            if setter is not None:
                acquired = await setter(f"lock:delivery:{lock_key}", token, ttl=float(ttl))
                if acquired is False:
                    local.release()
                    return None
        except Exception as exc:  # noqa: BLE001 — fail-open: DB claim asosiy kafolat
            logger.debug("delivery lock: Redis qatlami ishlamadi (%s) — DB claim davom etadi", exc)
        return token

    async def release_delivery_lock(self, key, token) -> None:
        """Lockni bo'shatadi (token mos kelsagina; hech qachon xato ko'tarmaydi)."""
        if not key:
            return
        lock_key = str(key)
        try:
            backend = self._cache_backend()
            remover = getattr(backend, "compare_and_delete", None)
            if remover is not None and token:
                await remover(f"lock:delivery:{lock_key}", token)
        except Exception as exc:  # noqa: BLE001
            logger.debug("delivery lock release (remote) xatosi: %s", exc)
        lock = self._local_locks.get(lock_key)
        if lock is not None and lock.locked():
            try:
                lock.release()
            except RuntimeError:  # pragma: no cover — boshqa loop/task
                pass

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
        verify=None,
        signature=None,
        verify_attempt: int = 1,
    ) -> dict:
        """Idempotent delivery: DB claim lock'i bilan PENDING→SENDING→DELIVERED.

        ``send`` — async callable: bitta Telegram urinishini bajaradi (o'zi ham
        ``execute`` orqali rate-limit/RetryAfter'dan o'tgan bo'lishi kerak).

        Qaytadi::

            {"status": "sent", "claimed": True, "message_id": int, ...}
            {"status": "sent", "duplicate": True, ...}          # 0 duplikat
            {"status": "sent", "verified_duplicate": True, ...}  # kanalda topildi
            {"status": "processing"/"retry_pending", ...}        # boshqa worker/backoff
            {"status": "dead_letter", "classification": "permanent", ...}
            {"status": "failed", ...}                            # backoff bilan qayta
            {"status": "verify_pending", ...}                    # kanal tekshirilmoqda
            {"status": "unknown", ...}                           # blind retry YO'Q
            {"status": "error", ...}                             # DB yozilmadi — YUBORILMAYDI

        ``verify`` berilsa (async callable ``() -> probe natijasi``), ambiguous
        (TimedOut/NetworkError) xatoda kanal tekshiruvi ishga tushadi:
        post topilsa — DELIVERED (0 duplikat), yo'qligi tasdiqlansa — xavfsiz
        retry, tasdiqlanmasa — ``verify_pending`` (blind retry TAQIQLANADI).
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
        # P0 qo'shimcha lock: bir jarayondagi ikkinchi task bir xil kalit bilan
        # yubormasin (DB claim allaqachon atomik — bu ikkinchi qatlam).
        lock_token = await self.acquire_delivery_lock(key)
        if lock_token is None:
            logger.warning(
                "deliver_with_state: delivery lock band (post=%s) — yuborilmaydi", post_id,
            )
            return {"status": "processing", "claimed": False, "busy": True,
                    "reason": "delivery_lock_busy", "idempotency_key": key or ""}
        try:
            try:
                result = await send()
            except Exception as exc:
                cls = self.classify(exc)
                if cls == FAILURE_AMBIGUOUS and verify is not None:
                    return await self._resolve_ambiguous_failure(
                        run, post_id, channel_id, scheduled_time, key, exc,
                        verify=verify, signature=signature, attempt=verify_attempt,
                    )
                return await self._record_failure(run, post_id, channel_id, scheduled_time,
                                                  key, exc, cls)
        finally:
            await self.release_delivery_lock(key, lock_token)

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

    async def _resolve_ambiguous_failure(self, run, post_id, channel_id, scheduled_time,
                                         key, error, *, verify, signature=None,
                                         attempt: int = 1) -> dict:
        """Ambiguous xatoni kanal tekshiruvi bilan hal qiladi (blind retry yo'q)."""
        try:
            probe = await verify()
        except Exception as exc:  # noqa: BLE001 — tekshiruv xatosi = tasdiqlanmadi
            logger.warning("Kanal tekshiruvi xatosi (post=%s): %s", post_id, exc)
            probe = {"status": "unavailable", "items": []}
        decision = await self.resolve_ambiguous(
            probe=probe, channel_id=channel_id, signature=signature,
            attempt=attempt, run=run, key=key, error=error,
        )
        decision["classification"] = FAILURE_AMBIGUOUS
        decision["post_id"] = post_id
        if decision.get("status") == "ready":
            # Yo'qligi tasdiqlandi — oddiy transient yo'l (backoff bilan retry).
            return await self._record_failure(run, post_id, channel_id, scheduled_time,
                                              key, error, FAILURE_TRANSIENT)
        if decision.get("status") == "verify_pending":
            decision.setdefault("retry_pending", True)
        return decision

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
