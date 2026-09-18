"""AI ENGINE V2 — YAGONA KANONIK AI SHLYUZ (Faza 1, 2, 3).

Repo AI qatlamlarining YAGONA kirish nuqtasi:

    from services.ai_engine import gateway, Lane

    res = await gateway.generate("kofe do'koni uchun post", task="simple_post")
    res.text, res.provider, res.lane

Modullar:

* ``gateway``  — yagona ``generate`` / ``analyze`` / ``vision_analyze``
  interfeysi + legacy adapter (``utils.ai_agent`` shu yerdan yuradi);
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
    LANE_SPECS,
    TASK_LANES,
    lane_for_task,
    lane_task_names,
    provider_order,
    resolve_lane,
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
]

from .schemas import PostResult, AuditResult, PlanResult
from .prompts import PromptEngine
from .gateway import generate_post, audit, plan

__all__ += ["PostResult", "AuditResult", "PlanResult", "PromptEngine", "generate_post", "audit", "plan"]
