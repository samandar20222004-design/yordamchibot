"""PHASE 2 · Granular Rate Limiting — har bir harakat uchun ALOHIDA TTL.

Muammo (eski model): ``utils/helpers.py`` dagi ``_USER_HISTORY`` /
``_CB_THROTTLE`` — bitta ``dict`` butun bot uchun, chegara esa
**global**:

  * ``check_rate_limit`` — barcha harakatlar uchun bitta oyna
    (matn, tugma, AI, URL — hamması bir savatda);
  * ``is_callback_throttled(user_id)`` — ``data`` argumenti
    ishlatilmaganda kalit ``(user_id, "")`` bo'lardi, ya'ni **bitta**
    tugmani bosish foydalanuvchining **barcha** tugmalarini 1.5 s
    bloklaydi;
  * ``_USER_HISTORY`` chegaraga yetganda ``clear()`` — ya'ni bir
    flood-tozalash **boshqa foydalanuvchilarning** ham holatini
    buzardi (global tozalash);
  * butun holat **bir instance** ichida — Render/Docker'da ikki
    instance ishlatilganda chegaralar yarim qolardi.

Yechim — bu modul:
  1. **Granular siyosatlar** (har biri o'z kaliti + o'z TTL'i):

     | bucket        | kalit                    | standart            |
     |---------------|--------------------------|---------------------|
     | ``message``   | ``(user_id)``            | 1 s da ≤ 2 ta xabar |
     | ``callback``  | ``(user_id, action)``    | 1.5 s da 1 ta bosish|
     | ``ai``        | ``(user_id)``            | 4 s da 1 ta AI      |
     | ``fetch``     | ``(user_id)``            | 60 s da 5 ta URL/RSS|
     | ``fetch_global`` | ``(bot)``              | 60 s da 120 ta      |

  2. **Hech qanday mass tozalash yo'q** — har bir kalit ``incr`` bilan
     oshiriladi va o'z oynasi tugaganda **o'zi** yo'qoladi. Bitta
     foydalanuvchining flood'i boshqasining chegarasiga ta'sir qilmaydi;
  3. **Ulangan holat** — hisoblagichlar ``services.cache_backend``
     orqali saqlanadi: ``REDIS_URL`` bo'lsa state **butun
     instance'lar arasida umumiy** (multi-instance), bo'lmasa
     In-Memory (thread-xavfsiz, LRU + TTL, 512 MB RAM uchun
     ``max_entries``/``max_total_bytes`` chegaralari bilan);
  4. **Fail-open** — backend nosoz bo'lsa yoki Redis uzilsa rate
     limiter foydalanuvchini ** bloklamaydi** (chunki cache_backend
     allaqachon In-Memory ga o'tadi) — bot hech qachon to'xtamaydi;
  5. **Callback throttling aniq** — bir xil tugma ketma-ket bosilsa
     bloklanadi, **boshqa** tugma esa bemalol bosiladi (test:
     ``tests/rate_limiter_redis_test.py``).

Foydalanish (main.py):

    application.add_handler(RateLimitMiddleware(), group=-1)

Qo'shimcha qulaylik (handler ichida, ixtiyoriy):

    from middlewares.rate_limiter import rate_limiter
    decision = await rate_limiter.allow_ai(user.id)
    if not decision:
        ...  # foydalanuvchiga "⏳ Iltimos, biroz kuting" (uz/ru/en)
"""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterable

from telegram.ext import ApplicationHandlerStop, BaseHandler

logger = logging.getLogger(__name__)

#: ``services.cache_backend`` moduli yuklanmaganda ham ishlashi uchun
#: import xatosi ushlanadi (test muhiti / minimal o'rnatish).
try:  # pragma: no cover — import xatolari hal qilinadi
    from services import cache_backend as _cache
except Exception:  # noqa: BLE001  pragma: no cover
    _cache = None  # type: ignore[assignment]


#: Kalit prefiksi — boshqa ilovalar bilan to'qnashmasligi uchun.
KEY_PREFIX = "rl"

#: Havolani aniqlovchi qisqa regex (SSRF/DoS himoyasi uchun «fetch»
#: chegarasi faqat havolali xabarlarga qo'llanadi).
_URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>\"']{4,}")

#: AI GENERATSIYANI ishga tushiradigan real callback action'lar
#: (``middlewares/rate_limiter.AI_ACTION_PREFIXES``).
#: Ro'yxat ``RATE_LIMIT_AI_ACTIONS`` bilan kengaytirilishi/ almashtirilishi
#: mumkin; bo'sh qoldirilsa AI oyna faqat handler darajasida
#: (``rate_limiter.allow_ai()``) ishlaydi.
DEFAULT_AI_ACTIONS = (
    "studio_ai_post",     # 🤖 AI Studio → post
    "studio_ai_photo",    # 🤖 AI Studio → rasm
    "studio_ai_audit",    # 🛡 AI Studio → audit
    "ai_post_retry",      # 🔁 tayyor postni qayta generatsiya
    "photo_rewrite",      # ✍️ rasm matnini AI bilan qayta yozish
    "adp:",               # 📢 reklama varianti generatsiyasi
)

#: URL / RSS «fetch» ishga tushiradigan callback action'lar.
DEFAULT_FETCH_ACTIONS = (
    "src_chk:",           # 📡 RSS: «🔄 Hoziroq tekshirish»
    "src_url",            # 🔗 URL → post
    "src_add",            # 📡 RSS manba qo'shish
)

DEFAULT_MESSAGE_MAX = 2
DEFAULT_MESSAGE_WINDOW = 1.0
DEFAULT_CALLBACK_MAX = 1
DEFAULT_CALLBACK_WINDOW = 1.5
DEFAULT_AI_MAX = 1
DEFAULT_AI_WINDOW = 4.0
DEFAULT_FETCH_MAX = 5
DEFAULT_FETCH_WINDOW = 60.0
DEFAULT_FETCH_GLOBAL_MAX = 120


def _cfg(name: str, default: Any) -> Any:
    """``config`` dan sozlama o'qiydi (modul yo'q bo'lsa — ``default``).

    Barcha ``RATE_LIMIT_*`` kalitlari ``config.py`` da (yagona manba)
    o'qiladi; bu modul ulanmagan test muhitida ham ishlaydi.
    """
    try:
        import config  # noqa: WPS437 — runtime import (siklik bog'liqlik yo'q)

        value = getattr(config, name, None)
        return default if value is None else value
    except Exception:  # noqa: BLE001 — config import muvaffaqiyatsiz
        return default


def _cfg_list(name: str, default: Iterable[str]) -> tuple[str, ...]:
    """Vergul bilan ajratilgan ro'yxatni o'qiydi (bo'sh bo'lsa — standart).

    Manba — ``config.<NAME>`` (``RATE_LIMIT_AI_ACTIONS`` va h.k.); config
    moduli ulanmagan test muhitida to'g'ridan-to'g'ri ``os.environ`` ga
    qaraydi.
    """
    raw = str(_cfg(name, "") or "").strip()
    if not raw:
        return tuple(default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class RatePolicy:
    """Bitta granula: chegara + oyna (TTL)."""

    name: str
    limit: int
    window: float
    description: str = ""

    def cache_key(self, subject: str) -> str:
        """``rl:{bucket}:{subject}`` — butun botga tegishli kalitlar.

        Kalit **har bir harakat uchun alohida**: bir foydalanuvchining
        xabari boshqasining yoki boshqa callback action'ning sanagichiga
        tegilmaydi. Uzunlik 96 belgi bilan cheklangan (Telegram callback
        ma'lumoti 64 bayt — kalitlar tasodifan ustma-ust tushmaydi).
        """
        safe = str(subject or "-").replace(" ", "_")[:96]
        return f"{KEY_PREFIX}:{self.name}:{safe}"


@dataclass(frozen=True)
class RateDecision:
    """Chegara natijasi (``bool`` kontekstida ishlatiladi)."""

    allowed: bool
    bucket: str
    limit: int
    window: float
    retry_after: float = 0.0
    subject: str = ""

    def __bool__(self) -> bool:  # ``if not decision:`` — o'qilishi oson
        return self.allowed


def default_policies() -> dict[str, RatePolicy]:
    """Standart siyosatlar (config'dan, ``RATE_LIMIT_*``)."""
    def _int(name: str, default: int) -> int:
        try:
            return max(0, int(_cfg(name, default)))
        except (TypeError, ValueError):
            return default

    def _float(name: str, default: float) -> float:
        try:
            value = float(_cfg(name, default))
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    fetch_window = _float("RATE_LIMIT_FETCH_WINDOW", DEFAULT_FETCH_WINDOW)
    return {
        "message": RatePolicy(
            "message",
            _int("RATE_LIMIT_MESSAGE_MAX", DEFAULT_MESSAGE_MAX),
            _float("RATE_LIMIT_MESSAGE_WINDOW", DEFAULT_MESSAGE_WINDOW),
            "oddiy matnli xabarlar (bir foydalanuvchi uchun)",
        ),
        "callback": RatePolicy(
            "callback",
            _int("RATE_LIMIT_CALLBACK_MAX", DEFAULT_CALLBACK_MAX),
            _float("RATE_LIMIT_CALLBACK_WINDOW", DEFAULT_CALLBACK_WINDOW),
            "inline tugma: (user_id, callback_action) — boshqa tugma erkin",
        ),
        "ai": RatePolicy(
            "ai",
            _int("RATE_LIMIT_AI_MAX", DEFAULT_AI_MAX),
            _float("RATE_LIMIT_AI_WINDOW", DEFAULT_AI_WINDOW),
            "qimmatli AI generatsiyasi (bitta so'rov)",
        ),
        "fetch": RatePolicy(
            "fetch",
            _int("RATE_LIMIT_FETCH_MAX", DEFAULT_FETCH_MAX),
            fetch_window,
            "URL / RSS fetch (SSRF + DoS himoyasi), foydalanuvchi bo'yicha",
        ),
        "fetch_global": RatePolicy(
            "fetch_global",
            _int("RATE_LIMIT_FETCH_GLOBAL_MAX", DEFAULT_FETCH_GLOBAL_MAX),
            fetch_window,
            "URL / RSS fetch — butun bot (multi-instance bo'lsa Redis'da umumiy)",
        ),
    }


class RateLimiter:
    """Granular, ko'p bucket'li rate limiter.

    Barcha sanagichlar umumiy cache backend'da saqlanadi — Redis
    yoqilsa, In-Memory'da ishlaydi (modul hech qachon to'xtamaydi).
    """

    def __init__(
        self,
        backend: Any = None,
        policies: dict[str, RatePolicy] | None = None,
    ) -> None:
        self._backend = backend
        self.policies = dict(policies or default_policies())
        self.ai_actions = _cfg_list("RATE_LIMIT_AI_ACTIONS", DEFAULT_AI_ACTIONS)
        self.fetch_actions = _cfg_list("RATE_LIMIT_FETCH_ACTIONS", DEFAULT_FETCH_ACTIONS)
        self.enabled = bool(_cfg("RATE_LIMIT_ENABLED", True))

    # --- backend ---------------------------------------------------------
    @property
    def backend(self) -> Any:
        """Faol backend (yo'q bo'lsa — global In-Memory singleton).

        Global backend **keshlanmaydi**: ``init_cache_backend()`` main.py
        da startdan keyin chaqirilishi mumkin — limiter eskirgan
        nusxani ushlamaydi, har doim joriy backendni oladi.
        """
        if self._backend is not None:
            return self._backend
        if _cache is not None:
            return _cache.get_cache_backend()
        return None

    def set_backend(self, backend: Any) -> None:
        """Backendni almashtiradi (testlar / init)."""
        self._backend = backend

    def policy(self, bucket: str) -> RatePolicy:
        """Bucket siyosatini qaytaradi (noma'lum bo'lsa — keng oyna)."""
        found = self.policies.get(bucket)
        if found is not None:
            return found
        return RatePolicy(bucket, limit=10_000, window=1.0,
                          description="noma'lum bucket — deyarli cheklanmagan")

    def describe(self) -> dict:
        """Diagnostika: joriy siyosatlar (matn ko'rinishida)."""
        return {
            name: {
                "limit": p.limit,
                "window": p.window,
                "description": p.description,
            }
            for name, p in self.policies.items()
        }

    # --- yadroq: bitta sanagichni urinish --------------------------------
    async def hit(self, bucket: str, subject: str = "") -> RateDecision:
        """``bucket`` sanagichini oshiradi va ruxsat qarorini qaytaradi.

        **Fail-open**: backend istisno kelsa — foydalanuvchi
        bloklanmaydi (rate limit botni to'xtatmasligi kerak).
        """
        policy = self.policy(bucket)
        if not self.enabled or policy.limit <= 0:
            return RateDecision(True, bucket, policy.limit, policy.window,
                                subject=str(subject))
        backend = self.backend
        if backend is None:
            return RateDecision(True, bucket, policy.limit, policy.window,
                                subject=str(subject))
        try:
            count = int(await backend.incr(policy.cache_key(subject), ttl=policy.window))
        except Exception as exc:  # noqa: BLE001 — limiter hech qachon botni yiqitmasin
            logger.warning("rate_limiter: %s sanagichi ishlamadi (%s) — fail-open.",
                           bucket, exc)
            return RateDecision(True, bucket, policy.limit, policy.window,
                                subject=str(subject))
        allowed = count <= policy.limit
        return RateDecision(
            allowed=allowed,
            bucket=bucket,
            limit=policy.limit,
            window=policy.window,
            # Aniq QOLDIQ vaqtni bilmaymiz ( interfeys faqat 5 metod) —
            # birdan beriladigan eng xavfsiz taxmin: to'liq oyna.
            retry_after=0.0 if allowed else policy.window,
            subject=str(subject),
        )

    # --- qulaylik metodlari ---------------------------------------------
    async def allow_message(self, user_id: Any) -> RateDecision:
        return await self.hit("message", subject=user_id)

    async def allow_callback(self, user_id: Any, action: str = "") -> RateDecision:
        """``(user_id, callback_action)`` bo'yicha — bir xil tugma bloklanadi,
        **boshqa tugma esa bemalol bosiladi**."""
        subject = f"{user_id}|{str(action or '')[:64]}"
        return await self.hit("callback", subject=subject)

    async def allow_ai(self, user_id: Any) -> RateDecision:
        return await self.hit("ai", subject=user_id)

    async def allow_fetch(self, user_id: Any) -> RateDecision:
        """Foydalanuvchi bo'yicha URL/RSS fetch + butun bot global chek."""
        per_user = await self.hit("fetch", subject=user_id)
        if not per_user.allowed:
            return per_user
        return await self.hit("fetch_global", subject="bot")

    # --- update klassifikatsiyasi ----------------------------------------
    def classify(self, update: Any) -> list[tuple[str, str]]:
        """Update → ``[(bucket, subject), ...]`` ro'yxati.

        * ``callback_query`` → ``callback`` (aniq action bo'yicha) va,
          agar action AI/fetch ishga tushirsa — ``ai`` / ``fetch``;
        * matnli xabar → ``message``; agar matnda havola bo'lsa —
          yana ``fetch`` + ``fetch_global`` (SSRF/DoS himoyasi);
        * media/sticker/audio → bu qatlamda tegilmaydi (ularning
          chegarasi AI concurrency + kvota tomonda).
        """
        user = getattr(update, "effective_user", None)
        user_id = getattr(user, "id", None)
        if user_id is None:
            return []

        query = getattr(update, "callback_query", None)
        if query is not None:
            data = str(getattr(query, "data", "") or "")
            actions: list[tuple[str, str]] = [("callback", f"{user_id}|{data[:64]}")]
            if any(data.startswith(prefix) for prefix in self.ai_actions):
                actions.append(("ai", str(user_id)))
            if any(data.startswith(prefix) for prefix in self.fetch_actions):
                actions.append(("fetch", str(user_id)))
                actions.append(("fetch_global", "bot"))
            return actions

        message = getattr(update, "effective_message", None) or getattr(
            update, "message", None
        )
        if message is None:
            return []
        text = getattr(message, "text", None) or getattr(message, "caption", None)
        if not text or not str(text).strip():
            return []
        text = str(text)
        if text.lstrip().startswith("/"):
            # Buyruqlar (matn limitidan qat'i nazar) — o'z chegarasida.
            return []
        actions = [("message", str(user_id))]
        if _URL_RE.search(text):
            actions.append(("fetch", str(user_id)))
            actions.append(("fetch_global", "bot"))
        return actions

    async def evaluate(self, update: Any) -> RateDecision | None:
        """Update uchun barcha granullarni tekshiradi.

        Qaytaradi: ruxsat berilgan bo'lsa ``None`` (yoki o'chirilgan
        bo'lsa), rad bo'lgan granula qarori esa :class:`RateDecision`.
        """
        if not self.enabled:
            return None
        for bucket, subject in self.classify(update):
            decision = await self.hit(bucket, subject=subject)
            if not decision.allowed:
                return decision
        return None


#: Butun ilovada bitta limiter nusxasi (singleton).
rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Global limiter (import qiluvchilar uchun qulaylik)."""
    return rate_limiter


def set_rate_limiter(limiter: RateLimiter | None) -> None:
    """Global limiter'ni almashtiradi (testlar)."""
    global rate_limiter
    rate_limiter = limiter or RateLimiter()


@dataclass
class _AdmissionScope:
    update: Any


class RateLimitMiddleware(BaseHandler):
    """PTB middleware — update boshqaruv zanjirida granullarni tekshiradi.

    python-telegram-bot v21 da middleware oddiy ``BaseHandler`` sifatida
    ro'yxatga olinadi (``application.add_handler(..., group=-1)``):
      * ``check_update`` → har bir update qabul qilinadi (``True``);
      * ``block=True`` → qaror keyingi handler'lardan OLDIN qabul
        qilinadi (bloklangan update umuman yetib borMAYdi);
      * rad bo'lsa — ``ApplicationHandlerStop`` ko'tariladi: butun
        zanjir to'xtaydi, callback'ga esa tilga mos
        «⏳ Iltimos, kuting» toast yuboriladi (tugma «yuklanmoqda»
        holatida qotib qolmaydi).

    Middleware **hech qanday global tozalash** qilmaydi va backend
    nosoz bo'lsa foydalanuvchini bloklamaydi (fail-open).
    """

    def __init__(self, limiter: RateLimiter | None = None, enabled: bool | None = None):
        super().__init__(callback=self._dispatch, block=True)
        self._admitted_update: ContextVar[_AdmissionScope | None] = ContextVar(
            "rate_admitted_update", default=None
        )
        self.limiter = limiter if limiter is not None else rate_limiter
        if enabled is not None:
            self.limiter.enabled = bool(enabled)

    @asynccontextmanager
    async def admission(self, update: Any, context: Any = None):
        """Pre-lock check, scoped to this middleware and update object.

        Standalone BaseHandler usage still checks normally. Admitted updates
        count once even if cancelled while waiting for the user lock.
        """
        if await self.process_update(update, context):
            yield False
            return
        scope = _AdmissionScope(update)
        token = self._admitted_update.set(scope)
        try:
            yield True
        finally:
            # Child/background tasks inherit ContextVars. Invalidate their
            # marker too, and do not retain this update after dispatch exits.
            scope.update = None
            self._admitted_update.reset(token)

    # --- PTB handler interfeysi ----------------------------------------
    def check_update(self, update: Any) -> bool:
        """Har bir update tekshiriladi (lekin «qo'lda ushlanmaydi»)."""
        return True

    async def _dispatch(self, update: Any, context: Any = None) -> None:
        """``BaseHandler.handle_update`` ichidan chaqiriladi."""
        if await self.process_update(update, context):
            raise ApplicationHandlerStop

    # --- foydalanuvchiga xabar -----------------------------------------
    @staticmethod
    async def _reject(update: Any, context: Any = None) -> None:
        """Rad etilgan update uchun xushmuomala javob (uz/ru/en).

        * ``callback_query`` → ``query.answer(...)`` — tugma darhol
          bo'shaydi (spinning tugma qolmaydi);
        * matnli xabar → **jim** tashlab yuboriladi (javob yuborish
          o'ziga yangi flood bo'lardi).
        """
        query = getattr(update, "callback_query", None)
        if query is None:
            return
        text = "⏳ Iltimos, biroz kuting..."
        try:
            from locales.translations import get_lang, get_text

            lang = "uz"
            if context is not None:
                lang = get_lang(context) or "uz"
            text = get_text("sys_wait_short", lang) or text
        except Exception:  # noqa: BLE001 — i18n nosoz bo'lsa — standart matn
            pass
        try:
            await asyncio.wait_for(query.answer(text, show_alert=False), timeout=1.0)
        except Exception:  # noqa: BLE001 — javob yuborib bo'lmasa — jim
            logger.debug("rate_limiter: callback javobi yuborilmadi.", exc_info=True)

    async def process_update(self, update: Any, context: Any = None) -> bool:
        """Granullarni tekshiradi.

        Qaytaradi: ``True`` — update bloklandi (handler ishlamaydi),
        ``False`` — davom etish mumkin.
        """
        scope = self._admitted_update.get()
        if update is not None and scope is not None and scope.update is update:
            return False
        limiter = self.limiter
        if not limiter.enabled:
            return False
        try:
            # Admission now precedes the handler watchdog; bound the entire
            # multi-bucket check, not only individual Redis socket operations.
            decision = await asyncio.wait_for(
                limiter.evaluate(update),
                timeout=max(0.1, float(_cfg("REDIS_SOCKET_TIMEOUT", 2.0))),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — limiter botni to'xtatmasin
            logger.warning("rate_limiter: tekshiruvda xato (%s) — fail-open.", exc)
            return False
        if decision is None or decision.allowed:
            return False
        logger.info(
            "rate_limiter: bloklandi bucket=%s limit=%s/window=%.1fs",
            decision.bucket, decision.limit, decision.window,
        )
        await self._reject(update, context)
        return True
