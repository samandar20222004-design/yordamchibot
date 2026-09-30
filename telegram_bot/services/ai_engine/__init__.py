"""AI ENGINE V2 — YAGONA KANONIK AI SHLYUZ (Faza 1, 2, 3).

Repo AI qatlamlarining YAGONA kirish nuqtasi:

    from services.ai_engine import gateway, Lane

    res = await gateway.generate("kofe do'koni uchun post", task="simple_post")
    res.text, res.provider, res.lane

Modullar:

* ``gateway``  — yagona ``ai_gateway.generate`` / ``analyze`` /
  ``vision_analyze`` interfeysi (task/user_id/channel_id/lane) + legacy
  adapter (``utils.ai_agent`` shu yerdan yuradi);
* ``app_service`` — APPLICATION SERVICE qatlami: kvota bron/refund,
  telemetriyani DB'ga yozish va kunlik/oylik xarajat hisoboti;
* ``telemetry``— model/provider/token/latency/xarajat/status hisobi;
* ``retry``    — qayta urinish siyosati (jitter'li backoff, byudjetga mos);
* ``router``   — vazifaga qarab model tanlash: FAST / QUALITY / REASONING /
  VISION (Fast Path: qat'iy timeout + kesh);
* ``providers``— provayder registrı (Gemini, Groq, OpenRouter + chuqur
  zanjir — real HTTP ``services/ai_service.py`` adapterlarida, hech narsa
  noldan yozilmagan);
* ``health``   — Circuit Breaker: 429/timeout/5xx kuzatuvi, ketma-ket
  xatolar soni, sog'lom provayderga avto-fallback (legacy ``_BREAKERS``
  bilan bitta holat — mirror);
* ``cache``    — deterministik kalitli javob keshi (TTL + LRU).

Eslatma: ``services.ai`` (SMM orkestrator paketi) o'z ishini davom
ettiradi — u kvota/validator/navbat bilan ishlaydigan YUQORI qatlam.
Yangi kod AI chaqiruvi uchun FAQAT shu paketdan foydalanadi.
"""

from .cache import (
    AIResponseCache,
    cache_key,
    cache_ttl,
    canonical_prompt,
    default_cache,
    reset_cache,
)
from .gateway import (
    GatewayResult,
    analyze,
    extract_text,
    fast_path_timeout,
    gateway_status,
    generate,
    legacy_chain,
    vision_analyze,
)
from .health import (
    BreakerState,
    FAILURE_NETWORK,
    FAILURE_OTHER,
    FAILURE_RATE_LIMIT,
    FAILURE_SERVER,
    FAILURE_TIMEOUT,
    ProviderHealthMonitor,
    classify_exception,
    default_health_monitor,
    reset_health_monitor,
)
from .providers import (
    ProviderHandle,
    build_provider_handles,
    execute_provider,
    resolve_handles,
)
from .router import (
    Lane,
    LaneSpec,
    LANE_ALIASES,
    LANE_SPECS,
    TASK_LANES,
    lane_alias,
    lane_for_task,
    lane_task_names,
    provider_order,
    resolve_lane,
)
from .gateway import (
    AIGateway,
    MOCK_MODE_DEVELOPMENT,
    MOCK_MODE_FORCED,
    MOCK_MODE_OFF,
    MOCK_MODE_TEST,
    ai_gateway,
    environment,
    is_mock_provider,
    mock_mode,
    mock_provider_allowed,
    provider_allowed,
    resolve_model,
)
from .app_service import (
    DEFAULT_OPERATION_TYPE,
    TASK_OPERATION_TYPES,
    AITaskOutcome,
    AITaskService,
    ai_tasks,
    operation_type_for,
    run_ai_task,
)
from .app_service import usage_report as ai_usage_report
from .retry import (
    DEFAULT_RETRY_POLICY,
    KIND_QUALITY,
    NO_RETRY_POLICY,
    RETRYABLE_KINDS,
    RetryPolicy,
    policy_for,
)
from .telemetry import (
    AIUsageEvent,
    PERIOD_ALL,
    PERIOD_DAILY,
    PERIOD_MONTHLY,
    UsageRecorder,
    build_usage_event,
    default_recorder,
    estimate_cost,
    estimate_tokens,
    is_priced,
    price_spec,
    reset_default_recorder,
    usage_report,
)

__all__ = [
    # --- gateway: yagona kirish ------------------------------------------
    "gateway",
    "GatewayResult",
    "generate",
    "analyze",
    "vision_analyze",
    "legacy_chain",
    "gateway_status",
    "extract_text",
    "fast_path_timeout",
    # --- router: model tanlash -------------------------------------------
    "Lane",
    "LaneSpec",
    "LANE_SPECS",
    "TASK_LANES",
    "lane_for_task",
    "lane_task_names",
    "provider_order",
    "resolve_lane",
    # --- providers: registr (Gemini/Groq/OpenRouter + zanjir) -------------
    "ProviderHandle",
    "build_provider_handles",
    "resolve_handles",
    "execute_provider",
    # --- health: circuit breaker -----------------------------------------
    "ProviderHealthMonitor",
    "BreakerState",
    "classify_exception",
    "default_health_monitor",
    "reset_health_monitor",
    "FAILURE_RATE_LIMIT",
    "FAILURE_TIMEOUT",
    "FAILURE_SERVER",
    "FAILURE_NETWORK",
    "FAILURE_OTHER",
    # --- cache: deterministik kesh ----------------------------------------
    "AIResponseCache",
    "cache_key",
    "cache_ttl",
    "canonical_prompt",
    "default_cache",
    "reset_cache",
    # --- PHASE 6: yagona interfeys + xarajat/telemetriya ------------------
    "ai_gateway",
    "AIGateway",
    "resolve_model",
    "ai_tasks",
    "AITaskService",
    "AITaskOutcome",
    "run_ai_task",
    "ai_usage_report",
    "operation_type_for",
    "TASK_OPERATION_TYPES",
    "DEFAULT_OPERATION_TYPE",
    "LANE_ALIASES",
    "lane_alias",
    "RetryPolicy",
    "DEFAULT_RETRY_POLICY",
    "NO_RETRY_POLICY",
    "RETRYABLE_KINDS",
    "KIND_QUALITY",
    "policy_for",
    "AIUsageEvent",
    "UsageRecorder",
    "default_recorder",
    "reset_default_recorder",
    "build_usage_event",
    "estimate_tokens",
    "estimate_cost",
    "price_spec",
    "is_priced",
    "usage_report",
    "PERIOD_DAILY",
    "PERIOD_MONTHLY",
    "PERIOD_ALL",
    "mock_mode",
    "mock_provider_allowed",
    "is_mock_provider",
    "provider_allowed",
    "environment",
    "MOCK_MODE_OFF",
    "MOCK_MODE_TEST",
    "MOCK_MODE_DEVELOPMENT",
    "MOCK_MODE_FORCED",
]

from .schemas import PostResult, AuditResult, PlanResult
from .prompts import PromptEngine
from .gateway import generate_post, audit, plan

__all__ += ["PostResult", "AuditResult", "PlanResult", "PromptEngine", "generate_post", "audit", "plan"]
