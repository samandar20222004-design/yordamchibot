"""KANONIK AI SHLYUZ SIRTI — ``from services import ai_gateway`` (PHASE 6).

Handler va servislar provayderlar bilan TO'G'RIDAN-TO'G'RI ishlamasin:
yagona chaqiruv shu modul orqali bo'lsin.

    from services import ai_gateway

    # 1) To'g'ridan-to'g'ri generatsiya (telemetriya bilan):
    res = await ai_gateway.generate(
        prompt="Kofe do'koni uchun post",
        task="social_post",             # social_post | channel_dna | post_score | repurpose | ...
        user_id=42, channel_id=-1001001,
        lane="fast",                    # "fast" | "smart" | "premium"
    )
    res.text, res.provider, res.model, res.total_tokens, res.estimated_cost

    # 2) To'liq tsikl (kvota bron + refund + DB telemetriya + hisobot):
    from services.ai_gateway import run_ai_task

    outcome = await run_ai_task(
        db=db, task="social_post", prompt="...", user_id=42,
        channel_id=-1001001, lane="smart", context=context, ctx_prefix="magic",
    )
    if not outcome.ok:
        ...

Oqim: Handler → Application Service (``run_ai_task``) → AI Gateway
(``ai_gateway``) → Router → Provider Adapter.

Bu modul faqat qayta eksport (facade) — hech qanday yangi logika yo'q;
haqiqiy kod ``services.ai_engine.{gateway,app_service,router,telemetry}``
da va u yerda ham yagona nusxada yashaydi (dublikat yo'q).
"""

from __future__ import annotations

from services.ai_engine.app_service import (
    DEFAULT_OPERATION_TYPE,
    TASK_OPERATION_TYPES,
    AITaskOutcome,
    AITaskService,
    ai_tasks,
    operation_type_for,
    run_ai_task,
)
from services.ai_engine.app_service import usage_report as ai_usage_report
from services.ai_engine.gateway import (
    MOCK_MODE_DEVELOPMENT,
    MOCK_MODE_FORCED,
    MOCK_MODE_OFF,
    MOCK_MODE_TEST,
    AIGateway,
    GatewayResult,
    ai_gateway,
    analyze,
    audit,
    environment,
    gateway_status,
    generate,
    generate_post,
    is_mock_provider,
    mock_mode,
    mock_provider_allowed,
    plan,
    provider_allowed,
    vision_analyze,
)
from services.ai_engine.router import (
    LANE_ALIASES,
    Lane,
    lane_alias,
    lane_for_task,
    resolve_lane,
)
from services.ai_engine.telemetry import (
    AIUsageEvent,
    PERIOD_ALL,
    PERIOD_DAILY,
    PERIOD_MONTHLY,
    UsageRecorder,
    default_recorder,
    estimate_cost,
    estimate_tokens,
    usage_report,
)

__all__ = [
    # --- gateway: yagona kirish -------------------------------------------
    "ai_gateway",
    "AIGateway",
    "GatewayResult",
    "generate",
    "analyze",
    "vision_analyze",
    "gateway_status",
    # --- application service: kvota + telemetriya + hisobot ---------------
    "ai_tasks",
    "AITaskService",
    "AITaskOutcome",
    "run_ai_task",
    "ai_usage_report",
    "operation_type_for",
    "TASK_OPERATION_TYPES",
    "DEFAULT_OPERATION_TYPE",
    # --- router: vazifa/lane ----------------------------------------------
    "Lane",
    "LANE_ALIASES",
    "lane_alias",
    "lane_for_task",
    "resolve_lane",
    # --- telemetriya / xarajat --------------------------------------------
    "AIUsageEvent",
    "UsageRecorder",
    "default_recorder",
    "usage_report",
    "estimate_cost",
    "estimate_tokens",
    "PERIOD_DAILY",
    "PERIOD_MONTHLY",
    "PERIOD_ALL",
    # --- mock siyosati (P0-A) ---------------------------------------------
    "mock_mode",
    "mock_provider_allowed",
    "is_mock_provider",
    "provider_allowed",
    "environment",
    "MOCK_MODE_OFF",
    "MOCK_MODE_TEST",
    "MOCK_MODE_DEVELOPMENT",
    "MOCK_MODE_FORCED",
    # --- sxema asosidagi yordamchilar -------------------------------------
    "generate_post",
    "audit",
    "plan",
]
