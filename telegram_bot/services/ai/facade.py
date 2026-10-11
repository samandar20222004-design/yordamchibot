"""AI STEKI UCHUN YAGONA FASAD (Facade) — barcha AI chaqiruvlari shu yerdan.

AI STEK DE-BLOAT (yagona fasad) natijasida botning AI qatlami BITTA paketga
yig'ildi: :mod:`services.ai`. Ilgari parallel yashagan to'rtta avlod
(``utils/ai_agent.py``, ``services/ai_service.py``, ``services/ai_engine/``,
``services/ai_gateway.py``) endi quyidagicha tartibga solindi:

==============================  =============================================
KANONIK joy                     vazifa
==============================  =============================================
``services/ai/transport-ish``   —
``services/ai/fallback.py``     8 provayderli fallback zanjiri
                                (``AIFallbackService``, ``run_ai_chain``,
                                Core provayder adapterlari, rasm tahlili,
                                post-score). Ilgari: ``services/ai_service.py``.
``services/ai/engine/``         KANONIK shlyuz: lane/router, kesh, circuit
                                breaker, retry, telemetriya/xarajat, kvota
                                bron-refund (``run_ai_task``), prompt
                                muhiti, sxema validatori.
                                Ilgari: ``services/ai_engine/``.
``services/ai/*``               SMM orkestratsiyasi (intent router, output
                                validator, concurrency/navbat) va "Advanced
                                SMM" xizmatlari (ko'p variantli post,
                                repurpose, chuqur audit, PRO content-calendar).
``utils/ai_agent.py``           Botga xos yuqori darajadagi kontent
                                funksiyalari (post yozish, Magic Post, DNA,
                                content plan, vision, audit) + provayder
                                transporti. Bu modulning FAZOViy nomi
                                (``GEMINI_API_KEY``, ``_session``,
                                ``_breaker_open``, ``_run_ai_chain`` ...)
                                testlar monkeypatch qiladigan kontrakt —
                                shu sababli u joyida qoldirilgan.
==============================  =============================================

Eski import yo'llari O'CHIRILMAGAN, lekin endi **nol biznes-logikali**
shimlardir (dublikat kod yo'q):

* ``services/ai_engine/``  → ``services.ai.engine`` ni qayta eksport qiladi
  (submodullar ``sys.modules`` orqali AYNI BIR obyektga bog'langan);
* ``services/ai_service.py`` → ``services.ai.fallback`` bilan IDENTITY
  taxallusi (``services.ai_service is services.ai.fallback``) — shu sababli
  modul o'zgaruvchilariga qilingan monkeypatch ikki tomondan ham ko'rinadi;
* ``services/ai_gateway.py`` → ``services.ai.engine`` ni qayta eksport qiladi.

FOYDALANISH (yangi kod uchun YAGONA tavsiya etilgan kirish)::

    from services.ai import facade as ai

    result = await ai.generate_post_two_stage(prompt, user_id=42, lang="uz")
    gw = await ai.generate(prompt="...", task="social_post", user_id=42, lane="fast")
    variants = await ai.generate_post_variants(user_id=42, topic="...", lang="uz")

Bu modul faqat QAYTA EKSPORT qiladi — hech qanday yangi biznes-logika yo'q.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1-QATLAM — utils/ai_agent.py: botga xos yuqori darajadagi AI funksiyalar
# (legacy, lekin hamon asosiy ishlatiluvchi sirt — ko'pchilik handler shu
# yerdan foydalanadi; bu yerda faqat QAYTA EKSPORT qilinadi).
# ---------------------------------------------------------------------------
from utils.ai_agent import (
    ProviderError,
    VisionError,
    ai_timeout_message,
    analyze_channel_voice,
    analyze_user_prompt,
    audit_post,
    audit_post_sync,
    extract_schedule_time,
    format_post_text,
    format_post_text_with_tone,
    generate_ai_response,
    generate_content_plan as generate_content_plan_legacy,
    generate_dna_sample_post,
    generate_magic_post,
    generate_post_from_plan,
    generate_post_two_stage,
    generate_vision_post,
    get_tone_instruction,
    normalize_ai_lang,
    refine_post_pro,
    rewrite_channel_post,
    with_language,
)

# ---------------------------------------------------------------------------
# KANONIK SHLYUZ — services/ai/engine: lane/kvota/kesh/telemetriya.
# (``services/ai_gateway.py`` endi shu paketning deprecated shimi.)
# ---------------------------------------------------------------------------
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
    AIGateway,
    GatewayResult,
    ai_gateway,
    analyze as gateway_analyze,
    gateway_status,
    generate as gateway_generate,
    vision_analyze as gateway_vision_analyze,
)

# ---------------------------------------------------------------------------
# 4-QATLAM — services/ai (ushbu paket): SMM orkestratsiyasi + "Advanced SMM"
# xizmatlari (ko'p variantli post / repurpose / chuqur audit / PRO content
# calendar). Ichki import — paket allaqachon o'z ``__init__.py`` sida
# bularni eksport qiladi; bu yerda faqat bitta joyga yig'ib ko'rsatiladi.
# ---------------------------------------------------------------------------
from services.ai.orchestrator import AIOrchestrationResult, AIOrchestrator
from services.ai.planner import generate_content_plan as generate_content_plan_pro
from services.ai.repurpose import repurpose_content
from services.ai.variants import generate_post_variants

# ---------------------------------------------------------------------------
# 5-QATLAM — 🧠 PROGRESS + 🌊 TOKEN STREAMING + 💎 BOY XABAR QORALAMALARI
# (Bot API 10.1+ tayyorgarlik). Muhim: streaming moduli progress.py'dagi
# ``MIN_EDIT_INTERVAL_FLOOR`` (≥ 1.05 s) va ``CHAT_EDIT_CLOCK`` ni QAYTA
# ISHLATADI, shuning uchun mavjud edit rate-limit o'ramlari buzilmaydi —
# progress-reporter va stream bir chatda bitta soatni bo'lishadi.
# ---------------------------------------------------------------------------
from services.ai.progress import (
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
from services.ai.streaming import (
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

# ---------------------------------------------------------------------------
# 6-QATLAM — 🌍 DINAMIK KALENDAR KONTEKSTI. AI promptlari foydalanuvchining
# MAQSAD DAVLATI bo'yicha sanalarni yutadi (standart: UZ). Ma'lumot manbasi:
# ``telegram_bot/locales/calendars/*.json`` + ``services.calendar_service``.
# ---------------------------------------------------------------------------
from services.ai.calendar_context import (
    AI_CALENDAR_MARKER,
    calendar_context_lines,
    calendar_directive,
    calendar_prompt_context,
    resolve_prompt_country,
    strip_calendar_directive,
    supported_countries,
    with_calendar_context,
)
from services.calendar_service import CalendarService, get_calendar_service

#: Eski ``services.ai_gateway`` sirtidagi nom — backward compatibility.
#: (Barcha importlardan keyin e'lon qilinadi: importlar orasidagi assignment
#: ruff E402 ni keltirib chiqarardi.)
gateway_usage_report = ai_usage_report


class AIFacade:
    """Qulaylik uchun: barcha qatlamlarni BITTA nomespace ostida ko'rsatadi.

    Bu klass hech qanday holatni (state) saqlamaydi — faqat yuqoridagi
    qayta eksport qilingan funksiyalarga ishora qiluvchi statik metodlar.
    Modul darajasidagi funksiyalar (``from services.ai.facade import ...``)
    bilan bir xil — ``AIFacade`` faqat IDE/avtomat-to'ldirish qulayligi
    uchun qo'shimcha interfeys.
    """

    # --- 1-qatlam: legacy kontent generatsiyasi (utils/ai_agent.py) -------
    generate_ai_response = staticmethod(generate_ai_response)
    analyze_user_prompt = staticmethod(analyze_user_prompt)
    generate_post_two_stage = staticmethod(generate_post_two_stage)
    extract_schedule_time = staticmethod(extract_schedule_time)
    format_post_text = staticmethod(format_post_text)
    format_post_text_with_tone = staticmethod(format_post_text_with_tone)
    analyze_channel_voice = staticmethod(analyze_channel_voice)
    generate_dna_sample_post = staticmethod(generate_dna_sample_post)
    generate_content_plan_legacy = staticmethod(generate_content_plan_legacy)
    generate_post_from_plan = staticmethod(generate_post_from_plan)
    rewrite_channel_post = staticmethod(rewrite_channel_post)
    generate_vision_post = staticmethod(generate_vision_post)
    generate_magic_post = staticmethod(generate_magic_post)
    refine_post_pro = staticmethod(refine_post_pro)
    audit_post = staticmethod(audit_post)

    # --- 3-qatlam: kanonik AI Gateway (lane/kvota/telemetriya) -------------
    gateway_generate = staticmethod(gateway_generate)
    gateway_analyze = staticmethod(gateway_analyze)
    gateway_vision_analyze = staticmethod(gateway_vision_analyze)
    run_ai_task = staticmethod(run_ai_task)

    # --- 4-qatlam: Advanced SMM (PRO) ---------------------------------------
    generate_post_variants = staticmethod(generate_post_variants)
    repurpose_content = staticmethod(repurpose_content)
    generate_content_plan_pro = staticmethod(generate_content_plan_pro)

    # --- 5-qatlam: progress + token streaming + rich message drafts ---------
    progress_reporter = staticmethod(AIProgressReporter)
    stream_tokens = staticmethod(stream_tokens)
    render_rich_draft = staticmethod(render_rich_draft)
    rich_message_draft = staticmethod(RichMessageDraft)

    # --- 6-qatlam: davlatga mos kalendar konteksti --------------------------
    with_calendar_context = staticmethod(with_calendar_context)
    calendar_directive = staticmethod(calendar_directive)
    supported_countries = staticmethod(supported_countries)
    calendar_service = staticmethod(get_calendar_service)


#: Modul darajasidagi qulay nom — ``from services.ai.facade import ai``.
ai = AIFacade()

# Qisqa taxallus — yangi chaqiruvchilar uchun: ``gateway_generate`` o'rniga
# ko'proq tabiiy o'qiladigan ism (eski ``generate`` nomi bilan to'qnashmasin
# deb atayin boshqacha nomlangan, chalkashlik bo'lmasligi uchun).
generate = gateway_generate
analyze = gateway_analyze
vision_analyze = gateway_vision_analyze

__all__ = [
    "AIFacade",
    "ai",
    # 1-qatlam (legacy, utils/ai_agent.py)
    "ProviderError",
    "VisionError",
    "ai_timeout_message",
    "analyze_channel_voice",
    "analyze_user_prompt",
    "audit_post",
    "audit_post_sync",
    "extract_schedule_time",
    "format_post_text",
    "format_post_text_with_tone",
    "generate_ai_response",
    "generate_content_plan_legacy",
    "generate_dna_sample_post",
    "generate_magic_post",
    "generate_post_from_plan",
    "generate_post_two_stage",
    "generate_vision_post",
    "get_tone_instruction",
    "normalize_ai_lang",
    "refine_post_pro",
    "rewrite_channel_post",
    "with_language",
    # 3-qatlam (kanonik gateway, services/ai_gateway.py)
    "AIGateway",
    "GatewayResult",
    "ai_gateway",
    "gateway_usage_report",
    "gateway_analyze",
    "gateway_status",
    "gateway_generate",
    "run_ai_task",
    "gateway_vision_analyze",
    "generate",
    "analyze",
    "vision_analyze",
    # 4-qatlam (Advanced SMM, services/ai/*)
    "AIOrchestrator",
    "AIOrchestrationResult",
    "generate_content_plan_pro",
    "repurpose_content",
    "generate_post_variants",
    # 5-qatlam (progress + 🌊 streaming + 💎 rich message drafts)
    "AI_ANALYSIS_STAGES",
    "AI_PROGRESS_STAGES",
    "AIProgressReporter",
    "AIStreamRenderer",
    "CHAT_EDIT_CLOCK",
    "ChatEditClock",
    "MIN_EDIT_INTERVAL_FLOOR",
    "PROGRESS_STAGE_SETS",
    "RichButton",
    "RichMessageDraft",
    "RichMessageDraftRender",
    "StreamResult",
    "TokenStreamBuffer",
    "close_open_tags",
    "normalize_progress_language",
    "progress_stages",
    "render_rich_draft",
    "stream_tokens",
    "truncate_message",
    # 6-qatlam (🌍 davlatga mos kalendar konteksti)
    "AI_CALENDAR_MARKER",
    "CalendarService",
    "calendar_context_lines",
    "calendar_directive",
    "calendar_prompt_context",
    "get_calendar_service",
    "resolve_prompt_country",
    "strip_calendar_directive",
    "supported_countries",
    "with_calendar_context",
]
