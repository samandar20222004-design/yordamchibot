"""AI Engine va SMM Orkestratsiyasi moduli.

PHASE 3: Intent Router, Provider Fallback Chain, Output Validator & Orchestrator.
PHASE 4 & 5: Concurrency, Bounded Queue va Request Cancellation.
PHASE 11 & 12: Advanced SMM xizmatlari — multi-variant (48), repurpose (49),
deep audit & score (33/50) va kontent reja generatori (51).

Advanced SMM xizmatlari shu paketdagi AIOrchestrator/Provider zanjiri,
Phase 2 atomik kvotasi (``services.ai_quota``) va Phase 2 HTML sanitizeri
ustiga qurilgan — yangi parallel AI quyi tizimi YO'Q.
"""

from .router import SMMIntent, detect_intent, SMMIntentRouter
from .providers import (
    AIProvider,
    AIProviderError,
    AllProvidersFailedError,
    GeminiProvider,
    GroqProvider,
    NoConfiguredProviderError,
    OpenRouterProvider,
    MockProvider,
    ProviderChain,
    ai_unavailable_message,
    get_environment,
    mock_is_allowed,
)
# 🛡 PHASE A (P0-C) — prompt/retry ko'rsatmalarining sizib chiqishidan himoya.
from .prompt_guard import (
    has_instruction_leak,
    sanitize_output,
    strip_instruction_leaks,
)
from .validator import AIOutputValidator, ValidationResult
from .orchestrator import AIOrchestrator, AIOrchestrationResult
from .concurrency import (
    AIConcurrencyManager,
    AIQueueFullError,
    AITaskCancelledError,
    AIQueueTimeoutError,
    ai_concurrency_manager,
    get_queue_full_message,
)
# 🚀 PHASE 11 & 12 — Advanced SMM xizmatlari (48/49/33+50/51-bandlar).
from .smm_common import (
    QuotaTicket,
    SMMFeatureService,
    chunk_blocks,
    get_default_orchestrator,
    sanitize_html,
    set_default_orchestrator,
)
from .variants import (
    VARIANT_STYLES,
    VARIANT_STYLE_KEYS,
    MultiVariantGenerator,
    PostVariant,
    VariantsResult,
    generate_post_variants,
)
from .repurpose import (
    REPURPOSE_PLATFORMS,
    REPURPOSE_PLATFORM_KEYS,
    ContentRepurposeService,
    RepurposeOutput,
    RepurposeResult,
    repurpose_content,
)
from .audit import (
    AUDIT_CRITERIA,
    AUDIT_CRITERION_KEYS,
    CriterionScore,
    ImprovementTip,
    PostAuditResult,
    PostAuditService,
    audit_post,
    overall_from_criteria,
    score_post_heuristics,
)
from .planner import (
    PLAN_DURATIONS,
    PLAN_FORMATS,
    ContentPlanResult,
    ContentPlanService,
    PlanDay,
    generate_content_plan,
    plan_entitlement,
)
# 🧭 3-QADAM (UI/UX POLISH) — prompt markazi: format aniqlash, fluff-guard,
# sifat standarti. Faqat stdlib — import zanjiriga ta'sir qilmaydi.
from .prompts import (
    FORMAT_GENERAL,
    FORMAT_NEWS,
    FORMAT_SALES,
    FORMAT_SHORT,
    FORMAT_TIPS,
    FORBIDDEN_FLUFF_PHRASES,
    FORMAT_SYSTEMS,
    FORMAT_TO_MAGIC_STYLE,
    POST_FORMATS,
    QUALITY_RULES,
    build_format_system,
    detect_post_format,
    format_hint_line,
    has_concrete_details,
    is_sales_topic,
    map_format_to_magic_style,
    needs_clarification,
    prompts_contain_fluff,
    scan_text_for_fluff,
    should_ask_sales_params,
)

__all__ = [
    "SMMIntent",
    "detect_intent",
    "SMMIntentRouter",
    "AIProvider",
    "AIProviderError",
    "AllProvidersFailedError",
    "NoConfiguredProviderError",
    "GeminiProvider",
    "GroqProvider",
    "OpenRouterProvider",
    "MockProvider",
    "ProviderChain",
    # --- PHASE A: production safety (P0-A / P0-C) ----------------------------
    "get_environment",
    "mock_is_allowed",
    "ai_unavailable_message",
    "has_instruction_leak",
    "sanitize_output",
    "strip_instruction_leaks",
    "AIOutputValidator",
    "ValidationResult",
    "AIOrchestrator",
    "AIOrchestrationResult",
    "AIConcurrencyManager",
    "AIQueueFullError",
    "AITaskCancelledError",
    "AIQueueTimeoutError",
    "ai_concurrency_manager",
    "get_queue_full_message",
    # --- PHASE 11 & 12: advanced SMM -----------------------------------------
    "SMMFeatureService",
    "QuotaTicket",
    "sanitize_html",
    "chunk_blocks",
    "get_default_orchestrator",
    "set_default_orchestrator",
    "VARIANT_STYLES",
    "VARIANT_STYLE_KEYS",
    "MultiVariantGenerator",
    "PostVariant",
    "VariantsResult",
    "generate_post_variants",
    "REPURPOSE_PLATFORMS",
    "REPURPOSE_PLATFORM_KEYS",
    "ContentRepurposeService",
    "RepurposeOutput",
    "RepurposeResult",
    "repurpose_content",
    "AUDIT_CRITERIA",
    "AUDIT_CRITERION_KEYS",
    "CriterionScore",
    "ImprovementTip",
    "PostAuditResult",
    "PostAuditService",
    "audit_post",
    "score_post_heuristics",
    "overall_from_criteria",
    "PLAN_DURATIONS",
    "PLAN_FORMATS",
    "PlanDay",
    "ContentPlanResult",
    "ContentPlanService",
    "plan_entitlement",
    "generate_content_plan",
    # --- 3-QADAM (UI/UX POLISH): prompt markazi -------------------------------
    "FORMAT_GENERAL",
    "FORMAT_NEWS",
    "FORMAT_SALES",
    "FORMAT_SHORT",
    "FORMAT_TIPS",
    "FORBIDDEN_FLUFF_PHRASES",
    "FORMAT_SYSTEMS",
    "FORMAT_TO_MAGIC_STYLE",
    "POST_FORMATS",
    "QUALITY_RULES",
    "build_format_system",
    "detect_post_format",
    "format_hint_line",
    "has_concrete_details",
    "is_sales_topic",
    "map_format_to_magic_style",
    "needs_clarification",
    "prompts_contain_fluff",
    "scan_text_for_fluff",
    "should_ask_sales_params",
]
