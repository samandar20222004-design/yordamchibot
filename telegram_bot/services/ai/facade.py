"""SPRINT 2 (VAZIFA 1) — AI STEKI UCHUN YAGONA FASAD (Facade).

Botning AI qatlami tarixan to'rtta avlodda rivojlangan:

    1. ``utils/ai_agent.py``        — ENG ESKI qatlam: provayderlarga
       to'g'ridan-to'g'ri (aiohttp) chaqiruvlar (``_call_gemini``,
       ``_call_groq``, ``_call_openrouter``, ...) HAMDA botga xos barcha
       yuqori darajadagi kontent funksiyalari (post yozish, DNA, content
       plan, vision, Magic Post, audit...). Ko'pchilik handler shu yerdan
       to'g'ridan-to'g'ri import qiladi.
    2. ``services/ai_service.py``   — 4-BOSQICH: 8 ta provayderli fallback
       zanjirini (qat'iy timeout + circuit breaker) markazlashtiradi;
       haqiqiy HTTP chaqiruvlarni DUBLIKATSIZ — ``utils.ai_agent``dagi
       xuddi o'sha ``_call_*`` funksiyalarga delegatsiya qiladi (``_ai_agent()``
       orqali kech import — aylanma importdan himoya).
    3. ``services/ai_engine/`` (+ fasadi ``services/ai_gateway.py``) —
       6-BOSQICH: KANONIK shlyuz. Lane (fast/smart/premium), kvota,
       keshlash, circuit breaker, telemetriya/xarajat hisobi shu yerda.
       Eski zanjir ``gateway.legacy_chain`` adapteri orqali ham shu
       shlyuzga ulanadi (``ai_agent._run_ai_chain`` → ``legacy_chain`` →
       ``ai_service.run_ai_chain`` → ``ai_agent._call_*``) — xatti-harakat
       O'ZGARMAYDI, faqat marshrut/kesh/telemetriya YAGONA joyda.
    4. ``services/ai/`` (ushbu paket) — 3/4/5/11/12-BOSQICHLAR: SMM
       orkestratsiyasi (intent routing, validator, concurrency/navbat) va
       "Advanced SMM" xizmatlari (ko'p variantli post, repurpose, chuqur
       audit, PRO content-calendar). Bu paketning ``providers.py``dagi
       ``GeminiProvider``/``GroqProvider``/``OpenRouterProvider`` klasslari
       ham DUBLIKAT EMAS — ular ``services.ai_service``dagi "Core"
       provayderlarga delegatsiya qiladigan yupqa adapterlar.

TEKSHIRUV (shu Sprint davomida): yuqoridagi to'rttala qatlam orasida
provayderga chaqiruv qiluvchi HAQIQIY dublikat kod TOPILMADI — ular
allaqachon DELEGATSIYA zanjiri orqali bog'langan (yuqoridagi 2/3/4-bandlar).
Shuning uchun bu Sprintda ularni jismoniy BIRLASHTIRISH (fayllarni
ko'chirish/o'chirish) — testlar bilan qattiq bog'langan ~6000 qatorlik,
12+ handler tomonidan ishlatiladigan kodni qayta yozish — mutanosib
bo'lmagan regressiya xavfini keltirib chiqargan bo'lardi (talab: "eski
import/API shartnomalarida regressiya BO'LMASIN"). Shu sababli amaliy va
xavfsiz yechim tanlandi: **bitta FASAD** — quyida — barcha tashqi
chaqiruvchilar (handler/tasks) uchun YAGONA, hujjatlashtirilgan kirish
nuqtasi sifatida qo'shildi; TO'RTTALA eski modul o'zgarishsiz qoladi va
eski importlar ildizidan ishlab turadi.

FOYDALANISH (yangi kod uchun tavsiya etiladi)::

    from services.ai import facade as ai

    result = await ai.generate_post_two_stage(prompt, user_id=42, lang="uz")
    gw = await ai.generate(prompt="...", task="social_post", user_id=42, lane="fast")
    variants = await ai.generate_post_variants(user_id=42, topic="...", lang="uz")

Eski kod ESKICHA ishlayveradi — bu modul faqat QAYTA EKSPORT qiladi,
hech qanday yangi biznes-logika yo'q (xuddi ``services/ai_gateway.py``
singari "faqat facade" tamoyili).
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
# 3-QATLAM — services/ai_gateway.py: KANONIK shlyuz (lane/kvota/telemetriya).
# ``services/ai_gateway.py`` o'zi ham faqat facade — shu yerda uning ustiga
# IKKINCHI qavat qurmasdan, to'g'ridan-to'g'ri qayta eksport qilinadi.
# ---------------------------------------------------------------------------
from services.ai_gateway import (
    AIGateway,
    GatewayResult,
    ai_gateway,
    ai_usage_report as gateway_usage_report,
    analyze as gateway_analyze,
    gateway_status,
    generate as gateway_generate,
    run_ai_task,
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
]
