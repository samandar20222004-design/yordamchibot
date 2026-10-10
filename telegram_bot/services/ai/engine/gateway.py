"""YAGONA KANONIK AI SHLYUZ — AI ENGINE V2 (Faza 1, 2, 3) + PHASE 6.

DEEP AUDIT muammosi: AI chaqiruvlari IKKIGA bo'lingan edi — eski modullar
``utils/ai_agent.py`` ga, yangilari ``services/ai/*`` ga murojaat qilar,
yagona marshrutlash va tezkor kesh yo'q edi.

Endi barcha AI so'rovlari uchun Bitta kirish nuqtasi — shu modul:

    from services.ai_engine import ai_gateway

    res = await ai_gateway.generate(
        prompt="kofe do'koni uchun post",
        task="social_post",            # kanonik vazifa
        user_id=42, channel_id=-1001,  # xarajat/telemetriya konteksti
        lane="fast",                   # "fast" | "smart" | "premium"
    )
    res.text, res.provider, res.model, res.estimated_cost, res.status

Arxitektura (qatlamlar) — PHASE 6:

    handler / xizmat
        └─ APPLICATION SERVICE (``services.ai_engine.app_service``):
             kvota bron/refund + telemetriyani DB'ga yozish + hisobot
             └─ AI GATEWAY (``ai_gateway``)                  ← YAGONA KIRISH
                  ├─ prompt guard (kirish/chiqish himoyasi)
                  ├─ cache.get (FAST lane — deterministik kalit)
                  ├─ router.resolve_lane → FAST/SMART/PREMIUM/VISION
                  ├─ health.healthy_order (circuit breaker — 429/timeout/5xx)
                  ├─ retry siyosati (jitter'li backoff, byudjetga mos)
                  ├─ providers.execute_provider (services/ai_service adapterlari)
                  ├─ validator (sxema + sifat; bypass YO'Q)
                  ├─ telemetry (model/token/latency/xarajat/status)
                  └─ cache.set (muvaffaqiyatda)

    Eski chaqiruvlar (backward compatibility):
        utils/ai_agent._run_ai_chain → gateway.legacy_chain →
        services.ai_service.run_ai_chain (8-provayderli legacy zanjir,
        O'ZGARMAGAN — barcha mavjud testlar va chaqiruvchilar ishlaydi).

Qat'iy qoidalar:

* **Fast Path** — oddiy so'rovlar (FAST lane) og'ir modellar navbatida
  qotib qolmaydi: qat'iy umumiy timeout (default 12s) + kesh tekshiruvi
  va keshga yozish; navbat menejeri (``services.ai.concurrency``) FAQAT
  og'ir orchestratsiya uchun qoladi.
* **Hech qachon istisno otilmaydi** — barcha xatolar
  :class:`GatewayResult(ok=False, error=...)` bilan qaytadi (fail-soft,
  foydalanuvchiga tayyor muloyim xabar).
* **P0-A siyosati buzilmaydi** — shlyuz HAQIQIY provayderlargagina
  murojaat qiladi; Mock faqat dev/test (yoki ``AI_ALLOW_MOCK=1``)
  siyosatida zanjirga qo'shiladi, production'da esa **default O'CHIQ**
  (``mock_provider_allowed()`` — fail-closed).
* **Telemetriya majburiy** — har bir so'rov (muvaffaqiyat ham, xato ham)
  :mod:`services.ai_engine.telemetry` orqali qayd etiladi: model, provider,
  input/output tokenlar, latency, taxminiy xarajat, status.
* **Yagona sog'liq holati** — health monitori legacy ``_BREAKERS`` ni
  mirror qiladi (legacy va gateway bitta breaker siyosatida).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field

from .cache import cache_key, default_cache
from .health import FAILURE_OTHER, classify_exception, default_health_monitor
from .retry import KIND_QUALITY, RetryPolicy, policy_for
from .router import TASK_LANES, Lane, LaneSpec, LANE_SPECS, provider_order, resolve_lane
from .telemetry import (
    STATUS_FAILED,
    STATUS_SUCCESS,
    build_usage_event,
    default_recorder,
)

from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sozlash (ENV — .env.example'da hujjatlangan; chaqiruv paytida o'qiladi,
# shuning uchun testlar/runtime'da o'zgartirish mumkin).
# ---------------------------------------------------------------------------
#: Fast Path qat'iy umumiy timeout'i (soniya) — standart 12s (10-15s oyna).
#: ``AI_FAST_PATH_TIMEOUT`` bilan sozlanadi — qat'iy muddat kafolati uchun
#: qabul oynasi 1.0–15.0s (explicit ``timeout=`` argumenti bilan bir xil floк).


def fast_path_timeout() -> float:
    """FAST so'rovi uchun umumiy limit (env sozlanadigan, 1–15s).

    Standart 12s (Fast Path spetsifikatsiyasi: 10-15s). ``env`` qiymati
    HURMAT qilinadi — past qiymat (masalan 0.5s) testlar va, kerak bo'lsa,
    tajriba rejimlari uchun haqiqiy qat'iy muddat beradi (max(1.0)).
    """
    try:
        return min(15.0, max(1.0, float(os.getenv("AI_FAST_PATH_TIMEOUT", "12"))))
    except (TypeError, ValueError):
        return 12.0


def provider_timeout_cap() -> float:
    """Bitta provayderga beriladigan muddat (2-BOSQICH: 6–8s, env default 7s)."""
    try:
        # 2-BOSQICH: per-provider 6-8s — 429/500 da darhol fallback.
        return min(8.0, max(6.0, float(os.getenv("AI_ENGINE_PROVIDER_TIMEOUT", "7"))))
    except (TypeError, ValueError):
        return 7.0


def lane_default_timeout(lane: Lane) -> float:
    """Lane standart timeout'i (``AI_<LANE>_TIMEOUT`` env bilan bekor qilinadi)."""
    env_name = f"AI_{lane.value}_TIMEOUT"
    try:
        # 2-BOSQICH: har lane 6-15s oynasida, umumiy zanjir 15s dan oshmaydi.
        return min(15.0, max(6.0, float(
            os.getenv(env_name, str(LANE_SPECS[lane].default_timeout)))))
    except (TypeError, ValueError):
        return LANE_SPECS[lane].default_timeout


# ---------------------------------------------------------------------------
# PHASE 6 — MOCK SIYOSATI (production'da DEFAULT O'CHIQ, test/dev alohida)
# ---------------------------------------------------------------------------
#: Mock provayder nomlari (kanonik + keng tarqalgan variantlar).
MOCK_PROVIDER_NAMES = frozenset({"mock", "mockprovider", "fake", "stub"})

#: Mock rejimlari (test va dev ALOHIDA — loglar/diagnostika uchun).
MOCK_MODE_OFF = "off"                # production, AI_ALLOW_MOCK=0
MOCK_MODE_TEST = "test"              # ENVIRONMENT=test/testing
MOCK_MODE_DEVELOPMENT = "development"  # ENVIRONMENT=dev/development/local
MOCK_MODE_FORCED = "forced"          # AI_ALLOW_MOCK=1 (ochiq override)


def environment() -> str:
    """Joriy muhit nomi (``services.ai.providers`` bilan bir xil manba)."""
    try:
        from services.ai.providers import get_environment

        return str(get_environment() or "production").lower()
    except Exception:  # pragma: no cover — himoya
        return str(os.getenv("ENVIRONMENT") or "production").strip().lower() or "production"


def mock_mode() -> str:
    """Mock siyosati rejimi: off | test | development | forced.

    * ``production`` + ``AI_ALLOW_MOCK=0`` → ``off`` (production'da Mock
      zanjirga UMUMAN qo'shilmaydi — fail-closed);
    * ``ENVIRONMENT=test``/``testing`` → ``test``;
    * ``ENVIRONMENT=dev``/``development``/``local`` → ``development``;
    * ``AI_ALLOW_MOCK=1`` → ``forced`` (ochiq, ataylab qilingan istisno;
      logda ogohlantirish chiqadi).
    """
    allow_mock_var = "AI_ALLOW_MOCK"
    truthy = frozenset({"1", "true", "yes", "on", "y", "ha"})
    try:  # yagona manba — ``services.ai.providers`` (nusxa ko'chirilmaydi)
        from services.ai.providers import _TRUTHY_VALUES, AI_ALLOW_MOCK_VAR

        allow_mock_var, truthy = AI_ALLOW_MOCK_VAR, _TRUTHY_VALUES
    except Exception as _silent_exc:  # pragma: no cover — izolyatsiyalangan muhit
        log_silent_failure("services.ai_engine.gateway:mock_mode", _silent_exc)
    flag = (os.getenv(allow_mock_var, "0") or "").strip().lower()
    if flag in truthy:
        return MOCK_MODE_FORCED
    env = environment()
    if env in {"test", "testing"}:
        return MOCK_MODE_TEST
    if env in {"development", "dev", "local"}:
        return MOCK_MODE_DEVELOPMENT
    return MOCK_MODE_OFF


def mock_provider_allowed() -> bool:
    """Mock provayder zanjirga tushishi mumkinmi (production'da — YO'Q)."""
    return mock_mode() != MOCK_MODE_OFF


def is_mock_provider(name: str | None) -> bool:
    """Provayder nomi Mock/soxta provaydermi?"""
    clean = "".join(ch for ch in str(name or "").lower() if ch.isalnum())
    return clean in MOCK_PROVIDER_NAMES


def provider_allowed(name: str | None) -> bool:
    """Provayder nomi siyosat bo'yicha ruxsat etilganmi (Mock — faqat dev/test)."""
    if is_mock_provider(name):
        return mock_provider_allowed()
    return True


# ---------------------------------------------------------------------------
# PHASE 6 — MODEL ANIQLASH (telemetriya uchun: qaysi model ishladi)
# ---------------------------------------------------------------------------
_MODEL_FIELDS = ("model", "model_name", "model_used", "used_model")


def resolve_model(provider: str | None, result: dict | None = None) -> str:
    """Provayder javobi/modul konfiguratsiyasidan model nomini aniqlaydi.

    Provayder adapteri javobda modelni qaytarsa — o'sha ishlatiladi; aks
    holda ``utils.ai_agent`` dagi provayder model ro'yxatining birinchisi
    (real default) olinadi. Noma'lum bo'lsa ``""`` (soxta nom yozilmaydi).
    """
    if isinstance(result, dict):
        for key in _MODEL_FIELDS:
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    try:
        from utils import ai_agent as aa

        attr = "".join(ch for ch in str(provider or "") if ch.isalnum()).upper() + "_MODELS"
        models = getattr(aa, attr, None)
        if isinstance(models, (list, tuple)) and models and isinstance(models[0], str):
            return models[0]
    except Exception as _silent_exc:  # pragma: no cover — model nomi ixtiyoriy
        log_silent_failure("services.ai_engine.gateway:resolve_model", _silent_exc, provider=provider)
    return ""


# ---------------------------------------------------------------------------
# Lane standart tizim promptlari (2-BOSQICH: tabiiy toza o'zbek lotin + SMM)
# ---------------------------------------------------------------------------
# 2-BOSQICH TALABI: barcha promptlar faqat tabiiy, toza o'zbek tili
# (lotin) va SMM talablariga mos post tuzilishini (hook → qiymat →
# o'qiladigan paragraflar → tabiiy CTA → hashtag) mustahkamlaydi.
_LANE_SYSTEMS: dict[Lane, str] = {
    Lane.FAST: (
        "Siz professional SMM copywriter'siz. Faqat tabiiy, toza o'zbek "
        "tilida (lotin alifbosida) yozing — ruscha/inglizcha aralashtirmang. "
        "Post tuzilishi: kuchli hook (qalin sarlavha + 1 emoji), 2-4 qisqa "
        "abzasda aniq qiymat, o'qiladigan Telegram paragraflari, tabiiy CTA "
        "va 3-5 hashtag. Faqat tayyor post matnini qaytaring."
    ),
    Lane.QUALITY: (
        "Siz professional SMM copywriter va tahlilchisiz. Faqat tabiiy, "
        "toza o'zbek tilida (lotin) yozing. Sifatli, aniq va ravon post: "
        "kuchli hook, foydali asosiy qism, o'qiladigan paragraflar, tabiiy "
        "CTA va hashtaglar. Soxta fakt, shablon va keraksiz reklamasiz."
    ),
    Lane.REASONING: (
        "Siz tajribali SMM kontent-strateg va analitiksiz. Faqat tabiiy, "
        "toza o'zbek tilida (lotin) yozing. Chuqur, asoslangan tahlil va "
        "reja qaytaring; umumiy 'suv' gaplardan qoching. Har bir xulosa "
        "aniq, o'qiladigan va SMMga mos bo'lsin."
    ),
    Lane.VISION: (
        "Siz vizual kontent tahlilchisisiz. Faqat tabiiy, toza o'zbek tilida "
        "(lotin) va ixcham, o'qiladigan paragraflarda rasm mazmunini tahlil "
        "qiling. SMM talablariga mos, keraksiz bezaksiz."
    ),
}


def default_system_instruction(lane: Lane) -> str:
    """Lane uchun standart tizim prompti (chaqiruvchi bermasa)."""
    return _LANE_SYSTEMS.get(lane, _LANE_SYSTEMS[Lane.QUALITY])


#: Qayta urinish ko'rsatmasi. ``[SYSTEM]`` belgisi ataylab qo'yilgan:
#: model uni javobiga ko'chirsa, xavfsizlik tekshiruvi
#: (``safety.contains_leak``) bunday javobni PROMPT_LEAK deb RAD etadi.
RETRY_INSTRUCTION = "[SYSTEM] Regenerate: correct schema, language and substantive content."


# ---------------------------------------------------------------------------
# Natija konteyneri
# ---------------------------------------------------------------------------
@dataclass
class GatewayResult:
    """Shlyuz javobi — xato ham ISTISNO EMAS, qat'iy qiymat."""

    ok: bool
    text: str = ""
    #: Muvaffaqiyatli provayder (kanonik nom) yoki "cache" / "none".
    provider: str = "none"
    lane: Lane = Lane.QUALITY
    task: str = ""
    #: Javob keshdan kelganmi?
    cached: bool = False
    #: Umumiy ketgan vaqt (soniya).
    elapsed: float = 0.0
    #: Ok bo'lmasa — foydalanuvchiga tayyor muloyim xabar (uz/ru/en).
    error: str | None = None
    #: Provayder qaytargan to'liq dict (legacy shakl) — bo'lishi mumkin.
    raw: dict = field(default_factory=dict)
    #: Sinovdan o'tgan provayderlar (tartib bilan, diagnostika).
    provider_chain: list[str] = field(default_factory=list)
    # --- PHASE 6: telemetriya (xarajat/token/model/status) ----------------
    #: Ishlatilgan model nomi (aniqlanmasa — bo'sh satr).
    model: str = ""
    #: Kirish tokenlari (baho — ``telemetry.estimate_tokens``).
    input_tokens: int = 0
    #: Chiqish tokenlari (baho).
    output_tokens: int = 0
    #: Kechikish (millisekund).
    latency_ms: int = 0
    #: Taxminiy xarajat (USD; narx jadvalida yo'q model uchun 0.0).
    estimated_cost: float = 0.0
    #: Xarajat ma'nolimi (narx jadvalida model bor va javob keshdan emas)?
    priced: bool = False
    #: "success" | "failed" (telemetriya/DB CHECK bilan bir xil).
    status: str = ""
    #: Xato turi (rate_limit/timeout/server_error/network/other/quality...).
    failure_kind: str = ""
    #: Provayderga qilingan urinishlar soni (retry bilan birga).
    attempts: int = 0
    #: So'rov konteksti (telemetriya uchun).
    user_id: int | None = None
    channel_id: int | None = None
    #: Telemetriya yozuvi (``AIUsageEvent.as_dict()``) — monitoring uchun.
    usage: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ API
    @property
    def total_tokens(self) -> int:
        return int(self.input_tokens or 0) + int(self.output_tokens or 0)

    def structured_result(self, model):
        from .schemas import parse_result
        return parse_result(self.text, model)

    def json_result(self) -> dict | None:
        """Javob matnidan JSON dict ajratadi (bo'lmasa ``None``).

        Tahlil (analyze) natijalari uchun qulaylik; hech qachon yiqilmaydi.
        """
        import json

        text = (self.text or "").strip()
        if not text:
            return None
        # ```json ... ``` fence'ini yechish.
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, TypeError):
            return None


# ---------------------------------------------------------------------------
# Yordamchi: provayder javobidan matn ajratish (legacy shakllar bilan mos)
# ---------------------------------------------------------------------------
_TEXT_FIELDS = ("post_text", "content", "text", "reply", "response")


def extract_text(result: dict) -> str:
    """Provayder dict'idan asosiy matnni ajratadi (legacy maydonlar)."""
    if not isinstance(result, dict):
        return ""
    for field_name in _TEXT_FIELDS:
        value = result.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _graceful_error(lang: str, timeout: bool = False) -> str:
    """Foydalanuvchiga tayyor xavfsiz xabar (legacy xabarlar bilan bir xil)."""
    try:
        if timeout:
            from utils.ai_agent import ai_timeout_message

            return ai_timeout_message(lang or "uz")
        from services.ai.providers import ai_unavailable_message

        return ai_unavailable_message(lang or "uz")
    except Exception:  # pragma: no cover — himoya
        return "⚠️ AI hozirda mavjud emas, iltimos keyinroq urinib ko'ring."


def _language_directive(system_instruction: str, lang: str | None) -> str:
    """Til qoidasini biriktirish (legacy ``with_language`` — yagona manba)."""
    if not lang:
        return system_instruction
    try:
        from utils.ai_agent import normalize_ai_lang, with_language

        return with_language(system_instruction, normalize_ai_lang(lang))
    except Exception:  # pragma: no cover — himoya
        return system_instruction


def _output_leaks_instructions(text: str) -> bool:
    """Javobda tizim/retry ko'rsatmasi sizib chiqqanmi (P0-C, PHASE 6)?

    ``services.ai.prompt_guard`` — shu repo'ning kanonik guard'i; u mavjud
    bo'lmasa (izolyatsiyalangan muhit) faqat ``safety.contains_leak``
    ishlatiladi.
    """
    if not text:
        return False
    try:
        from services.ai.prompt_guard import has_instruction_leak

        return bool(has_instruction_leak(text))
    except Exception:  # pragma: no cover — himoya
        return False


# ---------------------------------------------------------------------------
# YAGONA KIRISH NUQTALARI (class-based shlyuz + modul darajasidagi delegatlar)
# ---------------------------------------------------------------------------
class AIGateway:
    """Kanonik AI shlyuzi (yagona interfeys) — PHASE 6.

    Handler va servislar provayderlar bilan TO'G'RIDAN-TO'G'RI ishlamaydi:
    faqat shu obyekt orqali (yoki modul darajasidagi ``generate`` delegati
    orqali) murojaat qiladi. Har bir chaqiruvda:

    1. prompt guard (kirish himoyasi) — ko'rsatma sizib chiqishini oldini oladi;
    2. router (task/lane → FAST/SMART/PREMIUM/VISION) va kesh (Fast Path);
    3. circuit breaker (sog'lom provayder tartibi) + retry siyosati;
    4. validator (sxema/sifat) — bypass YO'Q;
    5. telemetriya (model, provider, tokenlar, latency, xarajat, status).
    """

    def __init__(self, *, recorder=None, monitor=None):
        self._recorder = recorder
        self._monitor = monitor

    # ------------------------------------------------------------- yordamchi
    @property
    def recorder(self):
        return self._recorder if self._recorder is not None else default_recorder()

    @property
    def monitor(self):
        return self._monitor if self._monitor is not None else default_health_monitor()

    def status(self) -> dict:
        """Shlyuz diagnostikasi (lane'lar, kesh, breaker, xarajat)."""
        status = gateway_status(monitor=self.monitor)
        status["mock"] = {"mode": mock_mode(), "allowed": mock_provider_allowed()}
        try:
            status["usage"] = self.recorder.stats()
        except Exception:  # pragma: no cover
            status["usage"] = {}
        return status

    # ------------------------------------------------------------- generate
    async def generate(
        self,
        prompt: str = "",
        *,
        task: str | None = None,
        lane: Lane | str | None = None,
        lang: str = "uz",
        system_instruction: str | None = None,
        timeout: float | None = None,
        use_cache: bool | None = None,
        force_refresh: bool = False,
        tone: str = "",
        is_pro: bool = False,
        schema=None,
        channel_context: str = "",
        user_id: int | None = None,
        channel_id: int | None = None,
        operation_type: str = "",
        retry_policy: RetryPolicy | None = None,
        require_quality: bool = False,
        record_usage: bool = True,
    ) -> GatewayResult:
        """Kanonik AI generatsiyasi (barcha AI matn so'rovlari uchun yagona kirish).

        Args:
            prompt: foydalanuvchi mavzusi/matni.
            task: kanonik vazifa nomi (``router.TASK_LANES``) — lane tanlanadi
                (``social_post``, ``channel_dna``, ``post_score``, ``repurpose``).
            lane: aniq lane yoki alias (``"fast" | "smart" | "premium"``);
                task'dan ustun turadi.
            lang: foydalanuvchi tili (uz/ru/en) — qat'iy til qoidasi biriktiriladi.
            system_instruction: maxsus tizim prompti (bo'lmasa lane standarti).
            timeout: umumiy qat'iy muddat (bo'lmasa lane standarti; FAST —
                ``AI_FAST_PATH_TIMEOUT``, default 12s).
            use_cache/force_refresh: Fast Path keshi boshqaruvi.
            tone/is_pro: kesh kaliti konteksti.
            schema: qat'iy sxema (``PostResult``/``AuditResult``/``PlanResult``).
            channel_context: kanal konteksti (untrusted_input blokida).
            user_id/channel_id: telemetriya va hisobot konteksti (PHASE 6).
            operation_type: kvota turi (``magic_post``/``ai_studio``/...).
            retry_policy: qayta urinish siyosati (bo'lmasa lane siyosati).
            require_quality: ``True`` bo'lsa qat'iy sifat validatori
                (THIN/FLUFF/LANGUAGE) ham qo'llanadi — Application Service
                kontenti uchun standart.
            record_usage: ``False`` bo'lsa telemetriya yozilmaydi (diagnostika).

        Returns:
            :class:`GatewayResult` — xatoda ham istisno YO'Q (``ok=False``).
        """
        started = time.monotonic()
        resolved_lane = resolve_lane(task=task, lane=lane, prompt=prompt)
        # prompt guard (kirish): ko'rsatma bloklari promptdan olib tashlanadi —
        # model ularni "davom ettirib" javobga ko'chirmasligi uchun.
        safe_prompt = _guard_prompt(prompt)
        cache_enabled = resolved_lane.default_cache if use_cache is None else bool(use_cache)

        from .prompts import PromptEngine
        built_prompt, built_system = PromptEngine.build(
            safe_prompt, system=system_instruction or default_system_instruction(resolved_lane),
            lang=lang, task=task or "Create the requested content.",
            channel_context=channel_context, schema=schema,
        )

        # 1) KESH TEKSHIRUVI (Fast Path birinchi qadam — provayderga chiqmasdan).
        key = ""
        if cache_enabled:
            key = cache_key(
                prompt=built_prompt, lane=resolved_lane.value, task=str(task or ""),
                lang=lang, tone=tone, is_pro=is_pro,
                system_instruction=built_system or "",
            )
            if not force_refresh:
                cached_value = default_cache().get(key)
                if cached_value is not None:
                    logger.info("AI Engine [FAST-HIT]: lane=%s task=%s (%.3fs)",
                                resolved_lane.value, task or "-", time.monotonic() - started)
                    cached_text = extract_text(cached_value) or str(cached_value.get("text", ""))
                    result = GatewayResult(
                        ok=True, text=cached_text, provider="cache",
                        lane=resolved_lane, task=str(task or ""),
                        cached=True, elapsed=time.monotonic() - started,
                        raw=cached_value, status=STATUS_SUCCESS,
                        user_id=user_id, channel_id=channel_id,
                        model=str(cached_value.get("model", "") or ""),
                    )
                    if record_usage:
                        result = self._record(
                            result, prompt=built_prompt, system_instruction=built_system,
                            operation_type=operation_type, user_id=user_id,
                            channel_id=channel_id,
                        )
                    return result

        # 2) TIZIM PROMPTI + QAT'IY TIL QOIDASI.
        sys_instr = built_system or default_system_instruction(resolved_lane)
        sys_instr = _language_directive(sys_instr, lang)

        # 3) QAT'IY UMUMIY MUDDAT.
        overall = min(15.0, max(1.0, float(timeout))) if timeout else (
            fast_path_timeout() if resolved_lane is Lane.FAST
            else lane_default_timeout(resolved_lane)
        )

        # 4) GLOBAL KONKURENTLIK — legacy bilan bir xil semaphore
        #    (MAX_CONCURRENT_AI; bepul RPM limitlarini himoya qiladi).
        try:
            from utils import ai_agent as aa

            semaphore = aa._AI_SEMAPHORE
        except Exception:  # pragma: no cover — izolyatsiyalangan muhit
            semaphore = None

        policy = retry_policy or policy_for(resolved_lane)

        async def _run() -> GatewayResult:
            return await _generate_via_chain(
                built_prompt, sys_instr, resolved_lane, lang,
                overall=overall, started=started, task=str(task or ""), schema=schema,
                retry_policy=policy, require_quality=bool(require_quality or schema),
                user_id=user_id, channel_id=channel_id,
            )

        try:
            if semaphore is not None:
                async with semaphore:
                    result = await asyncio.wait_for(_run(), timeout=overall)
            else:
                result = await asyncio.wait_for(_run(), timeout=overall)
        except asyncio.TimeoutError:
            logger.warning("AI Engine [%s]: %.0fs umumiy muddat oshdi (task=%s)",
                           resolved_lane.value, overall, task or "-")
            result = GatewayResult(
                ok=False, lane=resolved_lane, task=str(task or ""),
                elapsed=time.monotonic() - started,
                error=_graceful_error(lang, timeout=True),
                failure_kind="timeout", status=STATUS_FAILED,
                user_id=user_id, channel_id=channel_id,
            )
        except Exception as exc:  # noqa: BLE001 — fail-soft kafolati
            logger.warning("AI Engine [%s] kutilmagan xato: %s", resolved_lane.value, exc)
            result = GatewayResult(
                ok=False, lane=resolved_lane, task=str(task or ""),
                elapsed=time.monotonic() - started, error=_graceful_error(lang),
                failure_kind=classify_exception(exc), status=STATUS_FAILED,
                user_id=user_id, channel_id=channel_id,
            )

        result.user_id = user_id
        result.channel_id = channel_id

        # 5) MUVAFFAQIYAT → KESHGA YOZISH (deterministik kalit).
        if result.ok and cache_enabled and key:
            payload = dict(result.raw or {"text": result.text})
            if result.model:
                payload.setdefault("model", result.model)
            default_cache().set(key, payload)

        # 6) TELEMETRIYA — har bir so'rov (xato ham) qayd etiladi.
        if record_usage:
            result = self._record(
                result, prompt=built_prompt, system_instruction=sys_instr,
                operation_type=operation_type, user_id=user_id, channel_id=channel_id,
            )
        return result

    # ------------------------------------------------------------- analyze
    async def analyze(
        self,
        prompt: str = "",
        *,
        task: str | None = None,
        lang: str = "uz",
        system_instruction: str | None = None,
        timeout: float | None = None,
        lane: Lane | str | None = None,
        **kwargs,
    ) -> GatewayResult:
        """Tahlil so'rovlari (default: QUALITY/SMART lane)."""
        resolved = resolve_lane(task=task, lane=lane, prompt=prompt)
        if system_instruction is None and resolved is Lane.QUALITY and not task:
            # analyze() default — tahlilga yo'naltirilgan tizim prompti.
            system_instruction = (
                "Siz professional SMM tahlilchisisiz. Javobni ixcham va aniq bering."
            )
        return await self.generate(
            prompt, task=task, lane=resolved, lang=lang,
            system_instruction=system_instruction, timeout=timeout, **kwargs,
        )

    # -------------------------------------------------------- vision_analyze
    async def vision_analyze(
        self,
        data: bytes | bytearray | memoryview,
        *,
        caption: str = "",
        lang: str = "uz",
        timeout: float | None = None,
        user_id: int | None = None,
        channel_id: int | None = None,
        operation_type: str = "",
        record_usage: bool = True,
    ) -> GatewayResult:
        """Rasm tahlili — VISION lane (yagona shlyuz orqali).

        Haqiqiy Vision ishlari sinovdan o'tgan ``utils.vision_analyzer`` da
        qoladi (model zanjiri, 404/429/timeout fallback) — bu yerda ular
        QAYTA YOZILMAYDI, faqat shlyuz kontraktiga o'raladi + telemetriya.
        """
        started = time.monotonic()
        lane = Lane.VISION
        try:
            from utils import vision_analyzer as va

            analysis = await va.analyze_image(data, caption=caption, lang=lang,
                                              timeout=timeout)
            if isinstance(analysis, dict) and analysis.get("error"):
                result = GatewayResult(
                    ok=False, lane=lane, task="vision",
                    elapsed=time.monotonic() - started, raw=dict(analysis),
                    error=str(analysis.get("error")) or None,
                    failure_kind="vision_error", status=STATUS_FAILED,
                    user_id=user_id, channel_id=channel_id,
                )
            else:
                result = GatewayResult(
                    ok=True, lane=lane, task="vision",
                    text=str(analysis.get("description") or analysis.get("summary") or ""),
                    provider=f"Vision:{analysis.get('model', '')}".strip(":"),
                    model=str(analysis.get("model", "") or ""),
                    elapsed=time.monotonic() - started,
                    raw=dict(analysis), status=STATUS_SUCCESS,
                    user_id=user_id, channel_id=channel_id,
                )
        except Exception as exc:  # noqa: BLE001 — Vision xatosi handler fallback'i
            logger.warning("AI Engine [VISION]: tahlil xatosi: %s", exc)
            result = GatewayResult(
                ok=False, lane=lane, task="vision", elapsed=time.monotonic() - started,
                raw={}, error=_graceful_error(lang),
                failure_kind=classify_exception(exc), status=STATUS_FAILED,
                user_id=user_id, channel_id=channel_id,
            )
        if record_usage:
            result = self._record(
                result, prompt=f"[vision] {caption}".strip(),
                system_instruction="", operation_type=operation_type,
                user_id=user_id, channel_id=channel_id,
            )
        return result

    # ------------------------------------------------------------ telemetriya
    def _record(
        self,
        result: GatewayResult,
        *,
        prompt: str,
        system_instruction: str,
        operation_type: str,
        user_id: int | None,
        channel_id: int | None,
    ) -> GatewayResult:
        """Natijani telemetriyaga yozadi (hech qachon AI oqimini buza olmaydi)."""
        result.status = STATUS_SUCCESS if result.ok else STATUS_FAILED
        result.latency_ms = int(round((result.elapsed or 0.0) * 1000))
        try:
            event = build_usage_event(
                result=result, prompt=prompt, system_instruction=system_instruction,
                operation_type=operation_type, user_id=user_id, channel_id=channel_id,
            )
            result.model = event.model or result.model
            result.input_tokens = event.input_tokens
            result.output_tokens = event.output_tokens
            result.estimated_cost = event.estimated_cost
            result.priced = event.priced
            result.usage = event.as_dict()
            self.recorder.record(event)
        except Exception as exc:  # noqa: BLE001 — telemetriya ixtiyoriy qatlam
            logger.warning("AI Engine telemetriya xatosi: %s", exc)
            result.input_tokens = result.input_tokens or 0
            result.output_tokens = result.output_tokens or 0
        return result


def _guard_prompt(prompt: str) -> str:
    """Kirish promptidan tizim/retry ko'rsatma bloklarini olib tashlaydi.

    Bu — prompt-injection himoyasining BIRINCHI qatlami (PHASE 6): foydalanuvchi
    matniga yopishtirilgan ko'rsatmalar modelga "tizim" kabi ko'rinmaydi;
    ikkinchi qatlam — chiqishni tekshirish (``contains_leak``) va
    ``PromptEngine`` ning ``untrusted_input`` bloklari.
    """
    text = "" if prompt is None else str(prompt)
    if not text:
        return text
    try:
        from services.ai.prompt_guard import has_instruction_leak, strip_instruction_leaks

        if has_instruction_leak(text):
            cleaned = strip_instruction_leaks(text)
            logger.warning("AI Engine prompt guard: kirishdan ko'rsatma bloklari olib tashlandi")
            return cleaned
    except Exception as _silent_exc:  # pragma: no cover — himoya
        log_silent_failure("services.ai_engine.gateway:_guard_prompt", _silent_exc)
    return text


#: Yagona shlyuz obyekti (handler va servislar shundan foydalanadi).
ai_gateway = AIGateway()


async def generate(
    prompt: str,
    *,
    task: str | None = None,
    lane: Lane | str | None = None,
    lang: str = "uz",
    system_instruction: str | None = None,
    timeout: float | None = None,
    use_cache: bool | None = None,
    force_refresh: bool = False,
    tone: str = "",
    is_pro: bool = False,
    schema=None,
    channel_context: str = "",
    user_id: int | None = None,
    channel_id: int | None = None,
    operation_type: str = "",
    retry_policy: RetryPolicy | None = None,
    require_quality: bool = False,
    record_usage: bool = True,
) -> GatewayResult:
    """Modul darajasidagi delegat — ``ai_gateway.generate`` (backward compat).

    Eski chaqiruvlar (``gateway.generate("...", task="simple_post")``)
    O'ZGARISHSIZ ishlaydi; yangi kontekst parametrlari (``user_id``,
    ``channel_id``, ``operation_type``, ``lane="fast"/"smart"/"premium"``)
    ixtiyoriy.
    """
    return await ai_gateway.generate(
        prompt, task=task, lane=lane, lang=lang,
        system_instruction=system_instruction, timeout=timeout,
        use_cache=use_cache, force_refresh=force_refresh, tone=tone, is_pro=is_pro,
        schema=schema, channel_context=channel_context,
        user_id=user_id, channel_id=channel_id, operation_type=operation_type,
        retry_policy=retry_policy, require_quality=require_quality,
        record_usage=record_usage,
    )


async def _generate_via_chain(
    prompt: str,
    system_instruction: str,
    lane: Lane,
    lang: str,
    *,
    overall: float,
    started: float,
    task: str = "",
    schema=None,
    retry_policy: RetryPolicy | None = None,
    require_quality: bool = False,
    user_id: int | None = None,
    channel_id: int | None = None,
) -> GatewayResult:
    """Lane tartibida provayderlar zanjiri + circuit breaker avto-fallback.

    Provayderlar ``services.ai_engine.health`` monitori bo'yicha sog'lom
    tartibda sinab ko'riladi: 429/timeout/5xx → qayta urinish (jitter'li
    backoff, siyosat bo'yicha) → keyingi SOG'LOM provayder.
    """
    from . import providers as _providers

    policy = retry_policy or policy_for(lane)
    monitor = default_health_monitor()
    wanted = provider_order(lane)
    order = monitor.healthy_order(wanted)
    handles = _providers.build_provider_handles()

    per_provider_cap = min(provider_timeout_cap(), lane_default_timeout(lane))
    chain_tried: list[str] = []
    last_errors: list[str] = []
    total_attempts = 0
    last_kind = FAILURE_OTHER
    skipped_mock: list[str] = []

    for name in order:
        handle = handles.get(name)
        if handle is None:
            continue
        # PHASE 6 (P0-A): Mock FAQAT dev/test rejimida zanjirga tushadi.
        if not provider_allowed(name):
            skipped_mock.append(name)
            continue
        if monitor.is_open(name):
            continue  # breaker ochiq — avto-fallback allaqachon surilgan
        if not handle.provider.is_available():
            continue  # kalit yo'q (chaqiruv paytida tekshiriladi)

        remaining = overall - (time.monotonic() - started)
        if remaining <= 0.2:
            break  # umumiy muddat tugadi — foydalanuvchi kutmasin
        per_provider = min(per_provider_cap, remaining)
        chain_tried.append(name)
        checked = None
        attempts_done = 0
        try:
            from .validator import OutputQualityError, QualityResult, validate_output
            from .safety import contains_leak

            while True:
                remaining = overall - (time.monotonic() - started)
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                attempts_done += 1
                total_attempts += 1
                kind = None
                instruction = system_instruction + (
                    "\n" + RETRY_INSTRUCTION if attempts_done > 1 else "")
                try:
                    result = await _providers.execute_provider(
                        handle, prompt, instruction, lang=lang,
                        timeout=min(per_provider, remaining),
                    )
                    text = extract_text(result)
                    if require_quality or schema:
                        checked = validate_output(text, lang=lang, schema=schema)
                    else:
                        # Transport darajasi: bo'sh/leak/sizib chiqqan javob
                        # hech qachon qabul qilinmaydi (bypass yo'q).
                        ok = bool(text) and not contains_leak(text) and not _output_leaks_instructions(text)
                        checked = QualityResult(ok, text=text,
                                                error_code=None if ok else "INVALID_OUTPUT")
                    if not checked.is_valid:
                        kind = KIND_QUALITY if not require_quality else (
                            checked.error_code or KIND_QUALITY)
                        raise OutputQualityError(kind)
                except OutputQualityError as exc:
                    kind = str(exc) or KIND_QUALITY
                    last_kind = kind
                    if policy.should_retry(attempts_done, KIND_QUALITY):
                        wait = policy.delay_for(
                            attempts_done,
                            remaining=overall - (time.monotonic() - started),
                        )
                        if wait > 0:
                            await asyncio.sleep(wait)
                        continue
                    raise
                except Exception as exc:  # noqa: BLE001 — fallback/retry qarori
                    kind = classify_exception(exc)
                    last_kind = kind
                    if policy.should_retry(attempts_done, kind):
                        wait = policy.delay_for(
                            attempts_done,
                            remaining=overall - (time.monotonic() - started),
                        )
                        if wait > 0:
                            await asyncio.sleep(wait)
                        continue
                    raise
                else:
                    if checked is not None and checked.is_valid:
                        break
                    # Himoya: nazariy jihatdan bu yerga tushmasligi kerak.
                    raise OutputQualityError("INVALID_OUTPUT")

            text = checked.text
            model = resolve_model(name, result if isinstance(result, dict) else None)
            # Never retain unsanitized aliases in raw/cache.
            payload = {"text": text}
            if model:
                payload["model"] = model
            monitor.record_success(name)
            logger.info("AI Engine [%s]: javob %s provayderidan (%.2fs)",
                        lane.value, name, time.monotonic() - started)
            return GatewayResult(
                ok=True, text=text, provider=name, lane=lane, task=task,
                model=model, elapsed=time.monotonic() - started,
                raw=dict(payload), provider_chain=list(chain_tried),
                status=STATUS_SUCCESS, attempts=total_attempts,
                user_id=user_id, channel_id=channel_id,
            )
        except Exception as exc:  # noqa: BLE001 — keyingi provayderga
            kind = classify_exception(exc)
            last_kind = kind
            monitor.record_failure(name, kind, str(exc))
            last_errors.append(f"{name}:{kind}:{attempts_done}x")
            logger.warning("AI Engine [%s]: %s xato (%s, %s urinish) → keyingi provayder",
                           lane.value, name, kind, attempts_done)

    detail = "; ".join(last_errors) or "mavjud provayder yo'q"
    if skipped_mock:
        detail += f" (mock taqiqlangan: {mock_mode()})"
    logger.warning("AI Engine [%s]: barcha provayderlar ishlamadi (%s)",
                   lane.value, detail)
    return GatewayResult(
        ok=False, lane=lane, task=task, elapsed=time.monotonic() - started,
        error=_graceful_error(lang), provider_chain=list(chain_tried),
        failure_kind=last_kind, status=STATUS_FAILED, attempts=total_attempts,
        user_id=user_id, channel_id=channel_id,
    )


async def analyze(
    prompt: str,
    *,
    task: str | None = None,
    lang: str = "uz",
    system_instruction: str | None = None,
    timeout: float | None = None,
    lane: Lane | str | None = None,
    **kwargs,
) -> GatewayResult:
    """Tahlil so'rovlari uchun shlyuz kirishi (default: QUALITY lane).

    ``task`` aniq ko'rsatilsa — shu vazifa lane'i ishlatiladi (masalan
    ``task="channel_analysis"`` → REASONING). Natijani dict ko'rinishida
    olish uchun ``result.json_result()``.
    """
    return await ai_gateway.analyze(
        prompt, task=task, lang=lang, system_instruction=system_instruction,
        timeout=timeout, lane=lane, **kwargs,
    )


async def vision_analyze(
    data: bytes | bytearray | memoryview,
    *,
    caption: str = "",
    lang: str = "uz",
    timeout: float | None = None,
    **kwargs,
) -> GatewayResult:
    """Rasm tahlili — VISION lane (yagona shlyuz orqali, telemetriya bilan)."""
    return await ai_gateway.vision_analyze(
        data, caption=caption, lang=lang, timeout=timeout, **kwargs,
    )


# ---------------------------------------------------------------------------
# LEGACY ADAPTER — utils/ai_agent.py ning kanonik shlyuzga ulanishi
# ---------------------------------------------------------------------------
async def legacy_chain(prompt: str, system_instruction: str, lang: str | None = None) -> dict:
    """Legacy zanjir adapteri (``utils.ai_agent._run_ai_chain`` delegati).

    Eski 8-provayderli zanjir (``services.ai_service.run_ai_chain``) O'ZGARISHSIZ
    qoladi — shu adapter orqali chaqiriladi. Shu tufayli:

    * ``generate_ai_response``/``audit_post``/``generate_magic_post`` va barcha
      boshqa eski funksiyalar endi kanonik shlyuz KANALIGA tushadi;
    * ``provider``/``provider_chain`` maydonlari va test monkeypatch
      nuqtalari (``ai_agent._run_ai_chain``) o'zgarmaydi — backward compat.

    PHASE 6: bu yo'l ham telemetriyaga yoziladi (provayder + token/xarajat
    bahosi) — legacy oqim "ko'rinmas" sarf bo'lib qolmaydi. Foydalanuvchi
    konteksti yo'q, shuning uchun yozuvda ``task="legacy_chain"`` bo'ladi.
    """
    from services.ai import fallback as ai_service

    started = time.monotonic()
    result = await ai_service.run_ai_chain(prompt, system_instruction, lang=lang)
    try:
        provider = ""
        text = ""
        model = ""
        if isinstance(result, dict):
            provider = str(result.get("provider") or result.get("provider_used") or "")
            text = extract_text(result)
            model = resolve_model(provider, result)
        from .telemetry import STATUS_SUCCESS, STATUS_FAILED, estimate_cost, estimate_tokens, is_priced

        provider = provider or "legacy_chain"
        ok = bool(text)
        input_tokens = estimate_tokens(prompt) + estimate_tokens(system_instruction)
        output_tokens = estimate_tokens(text)
        priced = ok and is_priced(provider, model)
        entry = {
            "user_id": None,
            "channel_id": None,
            "task": "legacy_chain",
            "lane": "",
            "operation_type": "",
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": int(round((time.monotonic() - started) * 1000)),
            "estimated_cost": (estimate_cost(provider, model, input_tokens, output_tokens)
                               if priced else 0.0),
            "priced": priced,
            "status": STATUS_SUCCESS if ok else STATUS_FAILED,
            "error_code": (None if ok else str(result.get("error", ""))[:64] or "legacy_error"
                           if isinstance(result, dict) else "legacy_error"),
            "cached": False,
            "attempts": 1,
            "prompt_hash": "",
            "reservation_id": None,
            "created_at": time.time(),
        }
        from .telemetry import AIUsageEvent

        event = AIUsageEvent(**entry)
        default_recorder().record(event)
    except Exception as exc:  # noqa: BLE001 — telemetriya legacy yo'lni buza olmaydi
        logger.warning("Legacy telemetriya xatosi: %s", exc)
    return result


# ---------------------------------------------------------------------------
# KANONIK OPERATSIYALAR — handler'lar AI uchun FAQAT shu sirttan import oladi
# ---------------------------------------------------------------------------
# Audit qoidasi: "Hech bir handler provayderga to'g'ridan-to'g'ri
# bog'lanmasin!" — shu sababli handler'lar ``services.ai_service`` /
# ``services.ai.providers`` import QILMAYDI. Ushbu delegatlar xuddi shu
# sinovdan o'tgan funksiyalarni (hech narsa noldan yozilmagan) kechikkan
# bog'lanish (late binding) bilan chaqiradi: ``services.ai_service.X``
# testlarda monkeypatch qilinsa — delegat ham yangi qiymatni ko'radi.
def _late_bind_service_op(name: str):
    async def _op(*args, **kwargs):
        from services.ai import fallback as ai_service

        return await getattr(ai_service, name)(*args, **kwargs)
    _op.__name__ = name
    _op.__qualname__ = f"gateway.{name}"
    _op.__doc__ = (
        f"Yagona shlyuz delegati: ``services.ai_service.{name}`` "
        "(kechikkan bog'lanish — test monkeypatch'lari ishlashda davom etadi)."
    )
    return _op


#: Post baholash (6 mezon, bepul) — ``handlers.post_score``.
score_post = _late_bind_service_op("score_post")
#: Postni 95+ ballik variantga qayta ishlash — ``handlers.post_score``.
improve_post_to_95 = _late_bind_service_op("improve_post_to_95")
#: Rasm tahlilidan post generatsiya — ``handlers.image_post``.
generate_image_post = _late_bind_service_op("generate_image_post")


# ---------------------------------------------------------------------------
# Diagnostika (admin/health panel uchun)
# ---------------------------------------------------------------------------
def gateway_status(monitor=None) -> dict:
    """Shlyuz holati: lane'lar, kesh, provayderlar sog'lig'i va mock siyosati."""
    monitor = monitor or default_health_monitor()
    try:
        cache_stats = default_cache().stats()
    except Exception:  # pragma: no cover
        cache_stats = {}
    lanes_status: dict[str, dict] = {}
    for lane, spec in LANE_SPECS.items():
        lanes_status[lane.value] = {
            "label": spec.label,
            "description": spec.description,
            "default_timeout": spec.default_timeout,
            "cache_by_default": spec.cache_by_default,
            "provider_order": list(spec.provider_order),
            "tasks": sorted(t for t, l in TASK_LANES.items() if l is lane),
        }
    try:
        # PHASE 6: xarajat/telemetriya ko'rsatkichlari (jarayon davomida).
        usage_stats = default_recorder().stats()
    except Exception:  # pragma: no cover — diagnostika yiqilmaydi
        usage_stats = {}
    return {
        "lanes": lanes_status,
        "fast_path_timeout": fast_path_timeout(),
        "cache": cache_stats,
        "health": monitor.snapshot(),
        "usage": usage_stats,
        "mock": {"mode": mock_mode(), "allowed": mock_provider_allowed()},
    }


__all__ = [
    "AIGateway",
    "ai_gateway",
    "GatewayResult",
    "generate",
    "analyze",
    "vision_analyze",
    "legacy_chain",
    "gateway_status",
    "extract_text",
    "resolve_model",
    "default_system_instruction",
    "fast_path_timeout",
    "lane_default_timeout",
    "score_post",
    "improve_post_to_95",
    "generate_image_post",
    "Lane",
    "LaneSpec",
    # PHASE 6 — mock siyosati
    "MOCK_PROVIDER_NAMES",
    "MOCK_MODE_OFF",
    "MOCK_MODE_TEST",
    "MOCK_MODE_DEVELOPMENT",
    "MOCK_MODE_FORCED",
    "environment",
    "mock_mode",
    "mock_provider_allowed",
    "is_mock_provider",
    "provider_allowed",
    "RETRY_INSTRUCTION",
]


async def generate_post(prompt: str, **kwargs) -> GatewayResult:
    from .schemas import PostResult
    return await generate(prompt, task="simple_post", schema=PostResult, **kwargs)


async def audit(prompt: str, **kwargs) -> GatewayResult:
    from .schemas import AuditResult
    return await generate(prompt, task="audit", schema=AuditResult, **kwargs)


async def plan(prompt: str, **kwargs) -> GatewayResult:
    from .schemas import PlanResult
    return await generate(prompt, task="weekly_plan", schema=PlanResult, **kwargs)
