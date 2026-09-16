"""AI Orchestrator.

PHASE 3, 4 & 5: AI Engine, SMM Orkestratsiyasi, Bounded Queue va Concurrency.

Barcha qismlarni birlashtiruvchi markaz:
1. Intent Routing (SMMIntentRouter)
2. Quota Reserve (Phase 2 transactional reserve_ai_request)
3. Concurrency & Bounded Queue (Phase 4/5 AIConcurrencyManager)
4. Provider Fallback Chain (Gemini -> Groq -> OpenRouter -> Mock)
5. Output Validation (AIOutputValidator)
6. Controlled 1-time Retry (kuchaytirilgan prompt bilan)
7. HTML Sanitization (Phase 2 telegram_sanitizer.sanitize_html)
8. Fail-Closed Refund (xatolikda yoki bekor qilishda kvotani to'liq qaytarish)
"""

from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from .router import SMMIntent, detect_intent
from .validator import AIOutputValidator
from .providers import ProviderChain, MockProvider
from .concurrency import (
    AIConcurrencyManager,
    AIQueueFullError,
    AITaskCancelledError,
    ai_concurrency_manager,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Intent → AI kvota operatsiya turi (Phase 2 ``database.AI_OPERATION_TYPES``)
# ---------------------------------------------------------------------------
# MUHIM (P0, Phase 13 yuklama testida topildi): ilgari bu yerda
# ``f"ai_{intent.value.lower()}"`` (masalan ``ai_create_post``) yuborilar edi,
# ammo ``database.AI_OPERATION_TYPES`` oq ro'yxatida bunday qiymat YO'Q.
# Natijada ``reserve_ai_request`` har doim ``invalid_request`` bilan rad etar
# va ``orchestrate(db_module=<haqiqiy database>)`` HECH QACHON ishlamas edi
# (fail-closed, lekin 100% rad). Mavjud testlar ``reserve_ai_quota`` ni mock
# qilgani yoki ``db_module=False`` uzatgani uchun bu holat ko'rinmas edi.
#
# Endi har bir intent oq ro'yxatdagi aniq operatsiya turiga tushiriladi va
# ``_quota_operation_type()`` javobni ishga tushish vaqtida ham oq ro'yxat
# bo'yicha tekshiradi (kelajakda ro'yxat o'zgarsa ham rad javobi qaytmaydi).
INTENT_QUOTA_OPERATIONS: dict[SMMIntent, str] = {
    SMMIntent.CREATE_POST: "magic_post",
    SMMIntent.IMPROVE_POST: "post_enhancer",
    SMMIntent.SHORTEN: "post_enhancer",
    SMMIntent.EXPAND: "post_enhancer",
    SMMIntent.GENERATE_VARIANTS: "magic_post",
    SMMIntent.POST_AUDIT: "post_score",
    SMMIntent.CONTENT_IDEAS: "content_calendar",
    SMMIntent.UNKNOWN: "ai_chat",
}

#: Xarita topilmasa ishlatiladigan xavfsiz standart (oq ro'yxatda bor).
DEFAULT_QUOTA_OPERATION = "ai_chat"


def _quota_operation_type(intent: SMMIntent) -> str:
    """Intent uchun ``database.AI_OPERATION_TYPES`` ga mos operatsiya turi."""
    op = INTENT_QUOTA_OPERATIONS.get(intent, DEFAULT_QUOTA_OPERATION)
    try:
        import database as _db
        allowed = tuple(getattr(_db, "AI_OPERATION_TYPES", ()) or ())
    except Exception:  # noqa: BLE001 — database import qilinmasa ham ishlashi kerak
        allowed = ()
    if allowed:
        base = str(op or "").split(":", 1)[0].lower()
        if base not in allowed:
            logger.warning(
                "Kvota operatsiya turi oq ro'yxatda yo'q (%s) — standart '%s' "
                "ishlatiladi", op, DEFAULT_QUOTA_OPERATION)
            op = DEFAULT_QUOTA_OPERATION
    return op


@dataclass
class AIOrchestrationResult:
    """Orkestratsiya yakuniy natijasi."""
    success: bool
    intent: SMMIntent
    content: str = ""
    raw_content: str = ""
    provider_used: str = "none"
    retried: bool = False
    cost: int = 1
    reservation_id: int | None = None
    error: str | None = None
    error_code: str | None = None
    generation_id: str | None = None


class AIOrchestrator:
    """Professional SMM AI Orchestrator."""

    def __init__(
        self,
        provider_chain: ProviderChain | None = None,
        validator: type[AIOutputValidator] = AIOutputValidator,
        concurrency_manager: AIConcurrencyManager | None = None,
    ):
        self.provider_chain = provider_chain or ProviderChain()
        self.validator = validator
        self.concurrency_manager = concurrency_manager or ai_concurrency_manager

    async def orchestrate(
        self,
        user_id: int,
        prompt: str,
        lang: str = "uz",
        context: dict | None = None,
        db_module: Any = None,
    ) -> AIOrchestrationResult:
        """To'liq AI orkestratsiya siklini bajaradi."""
        # 1. Intent Routing
        intent = detect_intent(prompt)
        logger.info("Foydalanuvchi %s so'rovi intenti: %s", user_id, intent.value)

        ctx = dict(context or {})
        ctx["lang"] = lang
        ctx["intent"] = intent.value

        gen_id = ctx.get("generation_id") or self.concurrency_manager.generate_id(user_id)
        ctx["generation_id"] = gen_id

        # 2. Quota Reserve (Phase 2 atomik)
        reservation_id = None
        should_check_quota = db_module is not False and not ctx.get("skip_quota")
        db = db_module
        if db is None and should_check_quota:
            try:
                import database as db
            except Exception:
                db = None

        if should_check_quota and user_id and user_id > 0 and db is not None:
            try:
                from services.ai_quota import reserve_ai_quota
                res = await reserve_ai_quota(
                    db, user_id, _quota_operation_type(intent), 1)
                if not res.get("allowed"):
                    logger.warning("AI kvotasi yetarli emas (user=%s, reason=%s)", user_id, res.get("reason"))
                    return AIOrchestrationResult(
                        success=False,
                        intent=intent,
                        error=res.get("reason", "insufficient_quota"),
                        error_code="QUOTA_EXCEEDED",
                        generation_id=gen_id,
                    )
                reservation_id = res.get("reservation_id")
            except Exception as e:
                logger.error("Kvota bron qilishda xatolik (fail-closed): %s", e)
                return AIOrchestrationResult(
                    success=False,
                    intent=intent,
                    error=str(e),
                    error_code="DB_ERROR",
                    generation_id=gen_id,
                )

        retried = False
        raw_output = ""
        provider_used = "none"

        # 3. Provider Chain Execution ichki korutinasi
        async def _execute_ai():
            nonlocal retried
            raw, provider = await self.provider_chain.execute(prompt, ctx)

            # 4. Output Validation
            val_res = self.validator.validate(raw, expected_lang=lang)

            # 5. Controlled Retry (Aniq 1 marta)
            if not val_res.is_valid and val_res.needs_retry:
                logger.info(
                    "Validatsiya xatosi (%s: %s). 1 martalik kuchaytirilgan retry yuborilmoqda...",
                    val_res.error_code, val_res.reason,
                )
                retried = True
                addon = self.validator.get_retry_prompt_addon(val_res.error_code, expected_lang=lang)
                boosted_prompt = f"{prompt}\n{addon}"
                retry_ctx = dict(ctx)
                retry_ctx["is_retry"] = True

                try:
                    retry_output, retry_provider = await self.provider_chain.execute(boosted_prompt, retry_ctx)
                    val_second = self.validator.validate(retry_output, expected_lang=lang)
                    if val_second.is_valid or len(retry_output) >= 20:
                        raw = retry_output
                        provider = retry_provider
                    else:
                        mock = MockProvider()
                        raw = await mock.generate(prompt, ctx)
                        provider = f"{retry_provider}+mock_safe"
                except Exception as retry_err:
                    logger.warning("Retry muvaffaqiyatsiz bo'ldi, Mock fallback ishlatiladi: %s", retry_err)
                    mock = MockProvider()
                    raw = await mock.generate(prompt, ctx)
                    provider = "MockFallback"

            return raw, provider

        # Concurrency & Bounded Queue orqali bajarish
        cm = ctx.get("concurrency_manager") or self.concurrency_manager

        try:
            if ctx.get("skip_queue"):
                raw_output, provider_used = await _execute_ai()
            else:
                raw_output, provider_used = await cm.run_with_queue(
                    user_id=user_id,
                    coro_fn=_execute_ai,
                    generation_id=gen_id,
                    reservation_id=reservation_id,
                    db_module=db,
                    lang=lang,
                )

            # 6. Telegram HTML Sanitization (Phase 2)
            try:
                from utils.telegram_sanitizer import sanitize_html
                sanitized_content = sanitize_html(raw_output, max_length=4096)
            except Exception as san_err:
                logger.warning("HTML sanitize xatosi, oddiy xavfsizlantirish qo'llanadi: %s", san_err)
                sanitized_content = raw_output[:4096]

            return AIOrchestrationResult(
                success=True,
                intent=intent,
                content=sanitized_content,
                raw_content=raw_output,
                provider_used=provider_used,
                retried=retried,
                cost=1,
                reservation_id=reservation_id,
                generation_id=gen_id,
            )

        except AIQueueFullError as q_err:
            logger.warning("AI Queue to'ldi (user=%s): %s", user_id, q_err)
            if db is not None and user_id and reservation_id:
                try:
                    from services.ai_quota import release_ai_quota
                    await release_ai_quota(db, user_id, reservation_id)
                except Exception as ref_err:
                    logger.error("Queue full paytida kvota qaytarishda xato: %s", ref_err)
            return AIOrchestrationResult(
                success=False,
                intent=intent,
                error=str(q_err),
                error_code="QUEUE_FULL",
                reservation_id=reservation_id,
                generation_id=gen_id,
            )

        except (AITaskCancelledError, asyncio.CancelledError):
            logger.info("AI so'rovi bekor qilindi (user=%s, gen_id=%s)", user_id, gen_id)
            if db is not None and user_id and reservation_id:
                try:
                    from services.ai_quota import release_ai_quota
                    await release_ai_quota(db, user_id, reservation_id)
                except Exception as ref_err:
                    logger.error("Cancellation paytida kvota qaytarishda xato: %s", ref_err)
            return AIOrchestrationResult(
                success=False,
                intent=intent,
                error="Vazifa bekor qilindi.",
                error_code="CANCELLED",
                reservation_id=reservation_id,
                generation_id=gen_id,
            )

        except Exception as exc:
            logger.error("AI orkestratsiya jarayonida halokatli xato: %s", exc)
            # Fail-closed: kvota qaytariladi
            if db is not None and user_id and reservation_id:
                try:
                    from services.ai_quota import release_ai_quota
                    await release_ai_quota(db, user_id, reservation_id)
                    logger.info("Kvota bron %s foydalanuvchiga muvaffaqiyatli qaytarildi", reservation_id)
                except Exception as ref_err:
                    logger.error("Kvota qaytarishda xatolik: %s", ref_err)

            return AIOrchestrationResult(
                success=False,
                intent=intent,
                error=str(exc),
                error_code="ORCHESTRATION_FAILED",
                provider_used=provider_used,
                retried=retried,
                reservation_id=reservation_id,
                generation_id=gen_id,
            )
