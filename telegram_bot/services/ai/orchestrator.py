"""AI Orchestrator.

PHASE 3: AI Engine va SMM Orkestratsiyasini kuchaytirish.

Barcha qismlarni birlashtiruvchi markaz:
1. Intent Routing (SMMIntentRouter)
2. Quota Reserve (Phase 2 transactional reserve_ai_request)
3. Provider Fallback Chain (Gemini -> Groq -> OpenRouter -> Mock)
4. Output Validation (AIOutputValidator)
5. Controlled 1-time Retry (kuchaytirilgan prompt bilan)
6. HTML Sanitization (Phase 2 telegram_sanitizer.sanitize_html)
7. Fail-Closed Refund (xatolikda kvota/kreditni to'liq qaytarish)
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any

from .router import SMMIntent, detect_intent
from .validator import AIOutputValidator, ValidationResult
from .providers import ProviderChain, AIProvider, AIProviderError, MockProvider

logger = logging.getLogger(__name__)


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


class AIOrchestrator:
    """Professional SMM AI Orchestrator."""

    def __init__(
        self,
        provider_chain: ProviderChain | None = None,
        validator: type[AIOutputValidator] = AIOutputValidator,
    ):
        self.provider_chain = provider_chain or ProviderChain()
        self.validator = validator

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

        # 2. Quota Reserve (Phase 2 atomik)
        reservation_id = None
        should_check_quota = db_module is not False and not (context and context.get("skip_quota"))
        if should_check_quota and user_id and user_id > 0:
            db = db_module
            if db is None:
                try:
                    import database as db
                except Exception:
                    db = None

            if db is not None:
                try:
                    from services.ai_quota import reserve_ai_quota
                    res = await reserve_ai_quota(db, user_id, f"ai_{intent.value.lower()}", 1)
                    if not res.get("allowed"):
                        logger.warning("AI kvotasi yetarli emas (user=%s, reason=%s)", user_id, res.get("reason"))
                        return AIOrchestrationResult(
                            success=False,
                            intent=intent,
                            error=res.get("reason", "insufficient_quota"),
                            error_code="QUOTA_EXCEEDED",
                        )
                    reservation_id = res.get("reservation_id")
                except Exception as e:
                    logger.error("Kvota bron qilishda xatolik (fail-closed): %s", e)
                    return AIOrchestrationResult(
                        success=False,
                        intent=intent,
                        error=str(e),
                        error_code="DB_ERROR",
                    )

        retried = False
        raw_output = ""
        provider_used = "none"

        try:
            # 3. Provider Chain Execution (1-urinish)
            raw_output, provider_used = await self.provider_chain.execute(prompt, ctx)

            # 4. Output Validation
            val_res = self.validator.validate(raw_output, expected_lang=lang)

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
                        raw_output = retry_output
                        provider_used = retry_provider
                    else:
                        # Agar ikkinchi urinish ham nosoz bo'lsa, Mock fallback orqali to'g'rilanadi
                        mock = MockProvider()
                        raw_output = await mock.generate(prompt, ctx)
                        provider_used = f"{retry_provider}+mock_safe"
                except Exception as retry_err:
                    logger.warning("Retry muvaffaqiyatsiz bo'ldi, Mock fallback ishlatiladi: %s", retry_err)
                    mock = MockProvider()
                    raw_output = await mock.generate(prompt, ctx)
                    provider_used = "MockFallback"

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
            )
