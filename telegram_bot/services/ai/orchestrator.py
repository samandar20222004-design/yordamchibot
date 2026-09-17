"""AI Orchestrator.

PHASE 3, 4 & 5: AI Engine, SMM Orkestratsiyasi, Bounded Queue va Concurrency.

Barcha qismlarni birlashtiruvchi markaz:
1. Intent Routing (SMMIntentRouter)
2. Quota Reserve (Phase 2 transactional reserve_ai_request)
3. Concurrency & Bounded Queue (Phase 4/5 AIConcurrencyManager)
4. Provider Fallback Chain (Gemini -> Groq -> OpenRouter; Mock faqat dev/test — P0-A)
5. Output Validation (AIOutputValidator)
6. Strict Quality Gate (P0-B): har bir provayder uchun
   urinish -> validator -> AYNAN 1 retry -> validator -> keyingi HAQIQIY provayder;
   barcha provayderlar yaroqsiz bo'lsa — xavfsiz xato + TO'LIQ refund.
   Uzunlik (``len(...) >= 20``) hech qachon validatorni chetlab o'tmaydi.
7. Prompt-leak himoyasi (P0-C): provayder javobidagi tizim/retry ko'rsatmalari
   (``services.ai.prompt_guard``) foydalanuvchiga yetib bormaydi.
8. HTML Sanitization (Phase 2 telegram_sanitizer.sanitize_html)
9. Fail-Closed Refund (xatolikda yoki bekor qilishda kvotani to'liq qaytarish)
"""

from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from .router import SMMIntent, detect_intent
from .validator import AIOutputValidator
from .prompt_guard import sanitize_output
from .providers import (
    AllProvidersFailedError,
    NoConfiguredProviderError,
    ProviderChain,
    ai_unavailable_message,
)
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
    #: AI umuman ishlamaganda foydalanuvchiga ko'rsatiladigan xavfsiz xabar (P0-A).
    user_message: str | None = None


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

        # PHASE B — Channel DNA: kanal kontekstida (``context["channel_id"]``)
        # post generatsiya qilinayotganda, kanalning saqlangan uslubiy profili
        # ixcham system-prompt bloki sifatida ``ctx["system_prompt"]`` ga
        # ulanadi. FAIL-SOFT: DNA o'qilishi xatosi generatsiyani HECH QACHON
        # to'xtatmaydi; IDOR himoyasi — kanal faqat AYNAN shu foydalanuvchiga
        # tegishli bo'lgandagina ulanadi.
        try:
            from services.channels.dna import attach_dna_to_context
            ctx = await attach_dna_to_context(ctx, user_id, db)
        except Exception as _dna_err:  # noqa: BLE001 — DNA bonus, bloklovchi emas
            logger.debug("Channel DNA ulashda xato (o'tkazib yuborildi): %s", _dna_err)

        retried = False
        raw_output = ""
        provider_used = "none"

        # 3. Provider Chain Execution ichki korutinasi — QAT'IY SIFAT SIKLI (P0-B)
        async def _execute_ai():
            """Bitta provayder → validator → AYNAN 1 retry → validator.

            P0-B: ilgari bu yerda ``if val_second.is_valid or len(retry_output) >= 20:``
            bypass'i bor edi — 20+ belgili HAR QANDAY yaroqsiz javob (masalan
            ``<script>...`` yoki til mos kelmaydigan matn) qabul qilinardi.
            Endi uzunlik validator qoidasini CHETLAB O'TMAYDI.

            P0-A: Mock faqat ``ProviderChain.usable_providers()`` ruxsat bergan
            muhitda (dev/test yoki AI_ALLOW_MOCK=1) sinaladi; production'da esa
            haqiqiy provayderlar tugashi bilan halol xato ko'tariladi.

            P0-C: har bir javob ``sanitize_output()`` orqali tozalanadi —
            tizim/retry ko'rsatmalari validator va foydalanuvchiga yetib bormaydi.
            """
            nonlocal retried
            providers = self.provider_chain.usable_providers()
            if not providers:
                raise NoConfiguredProviderError(
                    "AI provayderlari sozlanmagan yoki Mock taqiqlangan muhit."
                )

            quality_failures: list[str] = []

            for provider in providers:
                retry_addon: str | None = None

                # Har bir provayder uchun maksimum 2 chaqiruv: 1 urinish + 1 retry
                for attempt in (1, 2):
                    attempt_prompt = prompt
                    attempt_ctx = dict(ctx)
                    if attempt == 2:
                        attempt_prompt = f"{prompt}\n{retry_addon}"
                        attempt_ctx["is_retry"] = True

                    try:
                        logger.info("AI chaqiruvi: provider=%s, attempt=%s", provider.name, attempt)
                        candidate = await provider.generate(attempt_prompt, attempt_ctx)
                    except Exception as prov_err:  # noqa: BLE001 — keyingi provayderga o'tamiz
                        logger.warning("Provayder %s xatosi: %s. Keyingisiga o'tilmoqda...",
                                       provider.name, prov_err)
                        quality_failures.append(f"{provider.name}: {prov_err}")
                        break

                    # P0-C: ko'rsatma sizib chiqishini tozalash (validator ham,
                    # foydalanuvchi ham faqat toza matnni ko'radi)
                    clean_candidate, leak_found = sanitize_output(candidate)
                    if leak_found:
                        logger.warning(
                            "P0-C: %s javobidan tizim/retry ko'rsatmasi tozalandi "
                            "(user=%s, gen=%s)", provider.name, user_id, gen_id)

                    val_res = self.validator.validate(clean_candidate, expected_lang=lang)
                    if val_res.is_valid:
                        return clean_candidate, provider.name

                    # LENGTH_EXCEEDED — sifat emas, HAJM muammosi: xavfsiz
                    # kesib, QAYTA validatsiya qilamiz (qoida chetlab o'tilmaydi).
                    if val_res.error_code == "LENGTH_EXCEEDED":
                        truncated = clean_candidate[: self.validator.MAX_TELEGRAM_LENGTH]
                        val_truncated = self.validator.validate(truncated, expected_lang=lang)
                        if val_truncated.is_valid:
                            logger.info("Javob %s belgiga kesildi (LENGTH_EXCEEDED)",
                                        self.validator.MAX_TELEGRAM_LENGTH)
                            return truncated, provider.name

                    quality_failures.append(f"{provider.name}[{val_res.error_code}]")
                    logger.warning(
                        "Validatsiya rad etdi: provider=%s, attempt=%s, code=%s (%s)",
                        provider.name, attempt, val_res.error_code, val_res.reason)

                    if attempt == 1 and val_res.needs_retry:
                        retried = True
                        retry_addon = self.validator.get_retry_prompt_addon(
                            val_res.error_code, expected_lang=lang)
                        continue
                    break

            raise AllProvidersFailedError(
                "Barcha AI provayderlari yaroqsiz javob qaytardi: "
                + ("; ".join(quality_failures) or "sabab noma'lum")
            )

        # Concurrency & Bounded Queue orqali bajarish
        cm = ctx.get("concurrency_manager") or self.concurrency_manager

        async def _refund_kvota(reason: str) -> None:
            """Bron qilingan kvotani TO'LIQ qaytarish (fail-closed, idempotent)."""
            if db is None or not user_id or not reservation_id:
                return
            try:
                from services.ai_quota import release_ai_quota
                await release_ai_quota(db, user_id, reservation_id)
                logger.info("Kvota bron %s foydalanuvchiga qaytarildi (%s)",
                            reservation_id, reason)
            except Exception as ref_err:  # noqa: BLE001
                logger.error("Kvota qaytarishda xatolik (%s): %s", reason, ref_err)

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
            await _refund_kvota("queue_full")
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
            await _refund_kvota("cancelled")
            return AIOrchestrationResult(
                success=False,
                intent=intent,
                error="Vazifa bekor qilindi.",
                error_code="CANCELLED",
                reservation_id=reservation_id,
                generation_id=gen_id,
            )

        except NoConfiguredProviderError as no_prov_err:
            # P0-A: production'da haqiqiy provayder yo'q — soxta generatsiya YO'Q,
            # foydalanuvchiga xavfsiz xabar + TO'LIQ refund.
            logger.error("P0-A: AI provayderlari sozlanmagan (user=%s): %s",
                         user_id, no_prov_err)
            await _refund_kvota("ai_unavailable")
            return AIOrchestrationResult(
                success=False,
                intent=intent,
                error=str(no_prov_err),
                error_code="AI_UNAVAILABLE",
                user_message=ai_unavailable_message(lang),
                reservation_id=reservation_id,
                generation_id=gen_id,
            )

        except Exception as exc:
            unavailable = isinstance(exc, AllProvidersFailedError)
            if unavailable:
                # P0-A/P0-B: barcha HAQIQIY provayderlar yiqildi yoki yaroqsiz
                # javob qaytardi — Mock ishlatilmaydi, kvota TO'LIQ qaytariladi.
                logger.error("AI provayderlari ishlamadi (user=%s): %s", user_id, exc)
            else:
                logger.error("AI orkestratsiya jarayonida halokatli xato: %s", exc)
            # Fail-closed: kvota qaytariladi
            await _refund_kvota("orchestration_failed")
            return AIOrchestrationResult(
                success=False,
                intent=intent,
                error=str(exc),
                error_code="ORCHESTRATION_FAILED",
                user_message=ai_unavailable_message(lang) if unavailable else None,
                provider_used=provider_used,
                retried=retried,
                reservation_id=reservation_id,
                generation_id=gen_id,
            )
