"""AI Engine va SMM Orkestratsiyasi moduli.

Intent Router, Provider Fallback Chain, Output Validator & Orchestrator.
Concurrency, Bounded Queue va Request Cancellation.
Advanced SMM xizmatlari — multi-variant (48), repurpose (49),
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
# prompt/retry ko'rsatmalarining sizib chiqishidan himoya.
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
# Advanced SMM xizmatlari (48/49/33+50/51-bandlar).
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
# prompt markazi: format aniqlash, fluff-guard,
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
# 🧠 PROGRESS — tahrir chastotasi cheklangan bosqich xabarlari (flood-control).
# Bu o'ram endi token oqimini ham qabul qiladi (:meth:`AIProgressReporter.stream`).
from .progress import (
    AI_ANALYSIS_STAGES,
    AI_PROGRESS_STAGES,
    CHAT_EDIT_CLOCK,
    MIN_EDIT_INTERVAL_FLOOR,
    PROGRESS_STAGE_SETS,
    AIProgressReporter,
    ChatEditClock,
    normalize_progress_language,
    progress_stages,
)
# 🌊 AI STREAMING + 💎 BOY XABAR QORALAMALARI (Bot API 10.1+ tayyorgarlik).
# Mavjud edit rate-limit o'rami buzilmaydi: streaming moduli progress.py'dagi
# MIN_EDIT_INTERVAL_FLOOR va CHAT_EDIT_CLOCK ni QAYTA ISHLATADI.
from .streaming import (
    AIStreamRenderer,
    RichButton,
    RichMessageDraft,
    RichMessageDraftRender,
    StreamResult,
    TokenStreamBuffer,
    close_open_tags,
    render_rich_draft,
    stream_tokens,
    truncate_message,
)
# 🌍 KALENDAR KONTEKSTI — AI promptiga foydalanuvchi davlatiga mos sanalar.
from .calendar_context import (
    AI_CALENDAR_MARKER,
    calendar_context_lines,
    calendar_directive,
    calendar_prompt_context,
    resolve_prompt_country,
    strip_calendar_directive,
    supported_countries,
    with_calendar_context,
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
    # production safety ----------------------------
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
    # advanced SMM -----------------------------------------
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
    # prompt markazi -------------------------------
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
    # --- progress / edit rate-limit ------------------------------------------
    "AI_ANALYSIS_STAGES",
    "AI_PROGRESS_STAGES",
    "CHAT_EDIT_CLOCK",
    "MIN_EDIT_INTERVAL_FLOOR",
    "PROGRESS_STAGE_SETS",
    "AIProgressReporter",
    "ChatEditClock",
    "normalize_progress_language",
    "progress_stages",
    # --- 🌊 token streaming + 💎 rich message drafts --------------------------
    "AIStreamRenderer",
    "RichButton",
    "RichMessageDraft",
    "RichMessageDraftRender",
    "StreamResult",
    "TokenStreamBuffer",
    "close_open_tags",
    "render_rich_draft",
    "stream_tokens",
    "truncate_message",
    # --- 🌍 davlatga mos kalendar konteksti -----------------------------------
    "AI_CALENDAR_MARKER",
    "calendar_context_lines",
    "calendar_directive",
    "calendar_prompt_context",
    "resolve_prompt_country",
    "strip_calendar_directive",
    "supported_countries",
    "with_calendar_context",
]
