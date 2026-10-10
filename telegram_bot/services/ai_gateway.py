"""ESKIRGAN (deprecated) YO'L — ``services.ai_gateway`` → ``services.ai``.

AI STEK DE-BLOAT (yagona fasad): kanonik AI shlyuz kodi endi
:mod:`services.ai.engine` da yashaydi va tashqi chaqiruvchilar uchun yagona
kirish nuqtasi :mod:`services.ai.facade` hisoblanadi.

Bu modul **nol biznes-logikali** muvofiqliq shimi — faqat qayta eksport.
Eski ``from services import ai_gateway`` / ``from services.ai_gateway import
run_ai_task`` importlari buzilmasligi uchun saqlangan; eksport ro'yxati
(``__all__``) avvalgi bilan AYNAN bir xil.

Yangi kod uchun::

    from services.ai import facade as ai

    res = await ai.generate(prompt="...", task="social_post", user_id=42, lane="fast")
    outcome = await ai.run_ai_task(db=db, task="social_post", prompt="...", user_id=42)

Oqim (o'zgarmagan): Handler → Application Service (``run_ai_task``) →
AI Gateway → Router → Provider adapter.
"""

from __future__ import annotations

# --- gateway + application service + mock siyosati (kanonik joy) -----------
from services.ai.engine.app_service import (
    DEFAULT_OPERATION_TYPE,
    TASK_OPERATION_TYPES,
    AITaskOutcome,
    AITaskService,
    ai_tasks,
    operation_type_for,
    run_ai_task,
)
from services.ai.engine.app_service import usage_report as ai_usage_report
from services.ai.engine.gateway import (
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
from services.ai.engine.router import (
    LANE_ALIASES,
    Lane,
    lane_alias,
    lane_for_task,
    resolve_lane,
)
from services.ai.engine.telemetry import (
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
