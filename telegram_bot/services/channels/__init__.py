"""🧠 Channel Intelligence (PostAssist V2 — PHASE B + FAZA 8,9,22).

Kanal monitoringi va aqlli tahlil qatlami:

* :mod:`services.channels.monitoring` — kanal postlarining metama'lumotlarini
  ``channel_post_events`` jadvaliga IDEMPOTENT (ON CONFLICT DO NOTHING) yozish
  — asinxron va bloklamaydigan rejimda (channel post handler ichida task sifatida);
* :mod:`services.channels.monitor` — FAZA 8,9,22: yengil xom ma'lumot olish,
  DB event yozish (AI'siz), batch agregatsiya — har bir post uchun AI chaqirilmaydi;
* :mod:`services.channels.dna` — Channel DNA profili (average_post_length,
  emoji_level, cta_style, formatting_style, sample_size, confidence_score)
  hisoblash, ``channel_intelligence_profiles`` va ``channel_dna`` ga saqlash
  va AI orkestrator promptiga ixcham system-prompt bloki sifatida ulash;
  Kengaytirilgan profil: language, tone, topics, avg_length, emoji_density,
  best_hours, best_weekdays, high_performing_formats — har bir metrika
  sample_size, confidence (0.0-1.0), updated_at bilan;
* :mod:`services.channels.best_time` — post chiqarish statistikasi bo'yicha
  eng maqbul vaqt oynalari (soxta raqamlar UYDIRMAYDI — yetarli ma'lumot
  bo'lmasa "insufficient data" holati qaytadi);
* :mod:`services.channels.duplicate_detector` — post kanalga
  rejalashtirilishidan/chiqarilishidan oldin kanalning oxirgi postlari bilan
  YENGIL (AI'siz, Jaccard/token-overlap) o'xshashlik tekshiruvi (PHASE C);
* :mod:`services.channels.recycle` — ♻️ CONTENT RECYCLE (PHASE D, 13-band):
  kanalning **14+ kun** oldingi, yaxshi ko'rsatkichli postlarini aniqlash va
  AI yordamida yangi **hook + sarlavha + CTA** bilan "yangilangan post"
  yaratish. Ko'r-ko'rona repost QAT'IYAN TAQIQLANADI (o'xshashlik chegarasi
  ``MAX_REUSE_SIMILARITY``).

Xavfsizlik: barcha foydalanuvchiga ochiladigan so'rovlar (DNA / best time /
dublikat tekshiruvi) ``user_id`` + ``channel_id`` ownership tekshiruvidan
o'tadi (IDOR himoyasi).
"""

from services.channels.best_time import (  # noqa: F401
    MIN_POSTS_FOR_BEST_TIME,
    compute_best_time,
    format_hour,
    get_best_time,
    hour_window,
)
from services.channels.dna import (  # noqa: F401
    MIN_POSTS_FOR_DNA,
    INSUFFICIENT_DATA_MESSAGE,
    attach_dna_to_context,
    build_dna_system_prompt,
    build_dna_system_prompt_extended,
    classify_cta_style,
    classify_emoji_level,
    classify_formatting_style,
    classify_tone_extended,
    compute_best_hours,
    compute_best_weekdays,
    compute_channel_dna,
    compute_channel_dna_extended,
    compute_channel_dna_v2,
    compute_high_performing_formats,
    confidence_float,
    confidence_from_sample,
    detect_language,
    detect_language_from_events,
    extract_topics,
    get_channel_dna,
    get_channel_dna_extended,
)
from services.channels.duplicate_detector import (  # noqa: F401
    DUPLICATE_THRESHOLD,
    DUPLICATE_WARNING_MESSAGE,
    check_duplicate,
    containment_ratio,
    jaccard_similarity,
    normalize_text,
    screen_post_for_duplicates,
    similarity,
    tokenize,
)
from services.channels.monitoring import (  # noqa: F401
    detect_cta,
    emoji_density,
    extract_event_metadata,
    ingest_channel_post_event,
    schedule_post_event_ingest,
)
from services.channels.monitor import (  # noqa: F401
    ChannelMonitor,
    batch_aggregate_channel,
    extract_lightweight_metadata,
    get_aggregated_metrics,
)
from services.channels.team import (  # noqa: F401
    ApprovalButtons, ApprovalService, ApprovalWorkflow, ChannelMember,
    ChannelMemberService, ChannelRole, TeamService, WORKFLOW_STATUSES,
    authorize, can_role, check_permission, has_channel_permission,
    resolve_member_role,
)
from services.channels.comments import (  # noqa: F401
    AudienceQuestionEngine, CommentAnalysisService, CommentInsightService,
    analyze_comments, analyze_repeated_questions, build_faq_draft,
    comment_to_content, redact_personal_data,
)
from services.channels.advisor import (  # noqa: F401
    ChannelAdvisor, ChannelAdvisorService, build_weekly_report,
    compute_weekly_insights, render_report_card,
)
from services.channels.recycle import (  # noqa: F401
    MAX_REUSE_SIMILARITY,
    MIN_AGE_DAYS,
    RecycleService,
    build_recycle_prompt,
    compose_refreshed,
    engagement_score,
    is_blind_repost,
    load_recycle_candidates,
    parse_recycled_payload,
    reuse_similarity,
    schedule_recycled_post,
    select_recycle_candidates,
)

__all__ = [
    "DUPLICATE_THRESHOLD",
    "DUPLICATE_WARNING_MESSAGE",
    "MAX_REUSE_SIMILARITY",
    "MIN_AGE_DAYS",
    "MIN_POSTS_FOR_BEST_TIME",
    "MIN_POSTS_FOR_DNA",
    "INSUFFICIENT_DATA_MESSAGE",
    "ApprovalButtons",
    "ApprovalService",
    "ApprovalWorkflow",
    "AudienceQuestionEngine",
    "ChannelAdvisor",
    "ChannelAdvisorService",
    "ChannelMember",
    "ChannelMemberService",
    "ChannelRole",
    "ChannelMonitor",
    "CommentAnalysisService",
    "CommentInsightService",
    "TeamService",
    "WORKFLOW_STATUSES",
    "RecycleService",
    "analyze_comments",
    "analyze_repeated_questions",
    "authorize",
    "batch_aggregate_channel",
    "build_dna_system_prompt",
    "build_dna_system_prompt_extended",
    "build_faq_draft",
    "build_weekly_report",
    "can_role",
    "check_permission",
    "classify_cta_style",
    "classify_emoji_level",
    "classify_formatting_style",
    "classify_tone_extended",
    "has_channel_permission",
    "comment_to_content",
    "compute_best_hours",
    "compute_best_weekdays",
    "compute_channel_dna",
    "compute_channel_dna_extended",
    "compute_channel_dna_v2",
    "compute_high_performing_formats",
    "compute_weekly_insights",
    "confidence_float",
    "confidence_from_sample",
    "containment_ratio",
    "detect_cta",
    "detect_language",
    "detect_language_from_events",
    "emoji_density",
    "engagement_score",
    "extract_event_metadata",
    "extract_lightweight_metadata",
    "extract_topics",
    "format_hour",
    "get_aggregated_metrics",
    "get_best_time",
    "get_channel_dna",
    "get_channel_dna_extended",
    "hour_window",
    "ingest_channel_post_event",
    "is_blind_repost",
    "jaccard_similarity",
    "load_recycle_candidates",
    "normalize_text",
    "parse_recycled_payload",
    "reuse_similarity",
    "schedule_post_event_ingest",
    "schedule_recycled_post",
    "screen_post_for_duplicates",
    "select_recycle_candidates",
    "similarity",
    "tokenize",
]
