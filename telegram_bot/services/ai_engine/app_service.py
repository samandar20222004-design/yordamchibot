"""APPLICATION SERVICE — AI vazifalari uchun yagona yuqori qatlam (PHASE 6).

Arxitektura oqimi (PHASE 6 talabi):

    Handler → APPLICATION SERVICE (shu modul) → AI GATEWAY → ROUTER →
    PROVIDER ADAPTER

Handler hech qachon:

* provayder adapteriga (``services.ai_service`` / ``services.ai.providers``)
  murojaat qilmaydi;
* kvota (kunlik AI so'rov / kredit) bronini o'zi ochmaydi;
* telemetriya (token/xarajat) yozuvini o'zi shakllantirmaydi.

Bularning barchasi bitta joyda — :class:`AITaskService` da:

* **kvota** — ``services.ai_quota.reserve_ai_quota`` (atomik, fail-closed);
  AI xatosi/timeout'da bron ``release_ai_quota`` bilan QAYTARILADI;
* **shlyuz** — ``services.ai_engine.gateway.ai_gateway`` (kesh/breaker/
  retry/validator/telemetriya);
* **telemetriya** — har bir so'rov ``ai_usage_events`` jadvaliga yoziladi
  (foydalanuvchi + kanal kesimida kunlik/oylik xarajat hisoboti uchun);
* **hisobot** — :meth:`AITaskService.usage_report` DB agregatini va
  in-memory telemetriyani birlashtiradi (DB bo'lmasa ham ishlaydi).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import telemetry
from .gateway import AIGateway, GatewayResult, ai_gateway

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vazifa → kvota operatsiya turi (``database.AI_OPERATION_TYPES`` oq ro'yxati)
# ---------------------------------------------------------------------------
#: ``AI_OPERATION_TYPES`` = ("ai_chat", "ai_studio", "magic_post",
#: "voice_post", "image_post", "post_score", "post_enhancer",
#: "content_calendar", "other"). Xarita SHU oq ro'yxatga tushadi — aks
#: holda ``reserve_ai_request`` so'rovni ``invalid_request`` bilan rad etadi.
TASK_OPERATION_TYPES: dict[str, str] = {
    # post yaratish oqimlari
    "social_post": "magic_post",
    "simple_post": "magic_post",
    "short_post": "magic_post",
    "quick_post": "magic_post",
    "magic_post": "magic_post",
    "rewrite": "post_enhancer",
    "restyle": "post_enhancer",
    "improve": "post_enhancer",
    "shorten": "post_enhancer",
    "expand": "post_enhancer",
    # media oqimlari
    "voice_post": "voice_post",
    "image_post": "image_post",
    "vision": "image_post",
    # tahlil / reja oqimlari
    "post_score": "post_score",
    "audit": "post_score",
    "audit_post": "post_score",
    "analyze": "post_score",
    "repurpose": "ai_studio",
    "content_repurpose": "ai_studio",
    "variants": "ai_studio",
    "channel_dna": "content_calendar",
    "channel_analysis": "content_calendar",
    "channel_voice": "content_calendar",
    "weekly_plan": "content_calendar",
    "content_plan": "content_calendar",
    "content_ideas": "content_calendar",
    "ai_chat": "ai_chat",
    "clarify": "ai_chat",
}

#: Xarita topilmasa ishlatiladigan xavfsiz standart (oq ro'yxatda bor).
DEFAULT_OPERATION_TYPE = "other"


def operation_type_for(task: str | None, explicit: str | None = None) -> str:
    """Vazifa uchun kvota operatsiya turi (oq ro'yxatga moslashtirilgan)."""
    if explicit:
        return str(explicit)
    key = str(task or "").strip().lower().replace("-", "_").replace(" ", "_")
    op = TASK_OPERATION_TYPES.get(key, DEFAULT_OPERATION_TYPE)
    try:
        import database as _db

        allowed = tuple(getattr(_db, "AI_OPERATION_TYPES", ()) or ())
    except Exception:  # noqa: BLE001 — database import qilinmasa ham ishlaydi
        allowed = ()
    if allowed:
        base = str(op or "").split(":", 1)[0].lower()
        if base not in allowed:
            logger.warning(
                "AI operatsiya turi oq ro'yxatda yo'q (%s) — '%s' ishlatiladi",
                op, DEFAULT_OPERATION_TYPE)
            return DEFAULT_OPERATION_TYPE
    return op


# ---------------------------------------------------------------------------
# Natija
# ---------------------------------------------------------------------------
@dataclass
class AITaskOutcome:
    """Application Service natijasi (handler uchun qulay yagona shakl)."""

    ok: bool
    text: str = ""
    result: GatewayResult | None = None
    reservation: dict = field(default_factory=dict)
    refunded: bool = False
    usage: dict = field(default_factory=dict)
    usage_id: int | None = None
    denied_reason: str | None = None
    error: str | None = None

    # ----------------------------------------------------------- qulayliklar
    @property
    def provider(self) -> str:
        return str(getattr(self.result, "provider", "") or "")

    @property
    def model(self) -> str:
        return str(getattr(self.result, "model", "") or "")

    @property
    def lane(self) -> str:
        lane = getattr(self.result, "lane", "")
        return str(getattr(lane, "value", lane) or "")

    @property
    def task(self) -> str:
        return str(getattr(self.result, "task", "") or "")

    @property
    def cached(self) -> bool:
        return bool(getattr(self.result, "cached", False))

    @property
    def estimated_cost(self) -> float:
        return float(getattr(self.result, "estimated_cost", 0.0) or 0.0)

    @property
    def total_tokens(self) -> int:
        return int(getattr(self.result, "total_tokens", 0) or 0)

    @property
    def latency_ms(self) -> int:
        return int(getattr(self.result, "latency_ms", 0) or 0)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "lane": self.lane,
            "task": self.task,
            "cached": self.cached,
            "estimated_cost": self.estimated_cost,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "refunded": self.refunded,
            "denied_reason": self.denied_reason,
            "usage_id": self.usage_id,
        }


# ---------------------------------------------------------------------------
# Application Service
# ---------------------------------------------------------------------------
class AITaskService:
    """Yagona AI vazifa servisi: kvota + shlyuz + telemetriya + hisobot."""

    def __init__(self, *, gateway: AIGateway | None = None, recorder=None):
        self._gateway = gateway
        self._recorder = recorder

    # -------------------------------------------------------------- yordamchi
    @property
    def gateway(self) -> AIGateway:
        return self._gateway or ai_gateway

    @property
    def recorder(self):
        return self._recorder or telemetry.default_recorder()

    @staticmethod
    def _real_db(db) -> bool:
        """DB adaptori haqiqiy ``database`` modulimi (mock testlarda — yo'q)."""
        try:
            from services.ai_quota import _is_real_db_adapter

            return bool(_is_real_db_adapter(db))
        except Exception:  # noqa: BLE001 — himoya
            return False

    async def _save_usage(self, db, event_dict: dict, reservation: dict) -> int | None:
        """Telemetriya yozuvini DB'ga saqlaydi (xato bo'lsa AI oqimi buzilmaydi)."""
        if db is None or not hasattr(db, "save_ai_usage_event"):
            return None
        if not self._real_db(db):
            return None
        fields = {
            "user_id": event_dict.get("user_id"),
            "channel_id": event_dict.get("channel_id"),
            "task": event_dict.get("task") or "",
            "lane": event_dict.get("lane") or "",
            "operation_type": (event_dict.get("operation_type")
                               or reservation.get("operation_type") or ""),
            "provider": event_dict.get("provider") or "none",
            "model": event_dict.get("model") or "",
            "input_tokens": int(event_dict.get("input_tokens") or 0),
            "output_tokens": int(event_dict.get("output_tokens") or 0),
            "latency_ms": int(event_dict.get("latency_ms") or 0),
            "estimated_cost": float(event_dict.get("estimated_cost") or 0.0),
            "priced": bool(event_dict.get("priced")),
            "status": event_dict.get("status") or telemetry.STATUS_FAILED,
            "error_code": event_dict.get("error_code"),
            "cached": bool(event_dict.get("cached")),
            "attempts": int(event_dict.get("attempts") or 0),
            "prompt_hash": event_dict.get("prompt_hash") or "",
            "reservation_id": reservation.get("reservation_id"),
        }
        try:
            return await db.run_db(db.save_ai_usage_event, **fields)
        except Exception as exc:  # noqa: BLE001 — telemetriya AI'ni to'xtatmaydi
            logger.warning("AI usage yozuvini saqlashda xato: %s", exc)
            return None

    # ------------------------------------------------------------------ run
    async def run(
        self,
        *,
        task: str,
        prompt: str,
        db=None,
        user_id: int | None = None,
        channel_id: int | None = None,
        lane=None,
        lang: str = "uz",
        operation_type: str | None = None,
        cost: int = 1,
        context=None,
        ctx_prefix: str | None = None,
        system_instruction: str | None = None,
        schema=None,
        timeout: float | None = None,
        use_cache: bool | None = None,
        tone: str = "",
        is_pro: bool = False,
        channel_context: str = "",
        reserve_quota: bool = True,
        require_quality: bool = True,
        persist_usage: bool = True,
        limit_text: str = "",
        **kwargs,
    ) -> AITaskOutcome:
        """AI vazifasini to'liq tsikl bilan bajaradi.

        1. kvota bron (foydalanuvchi bo'lsa) — fail-closed;
        2. shlyuz orqali generatsiya (yagona interfeys);
        3. xatoda bron QAYTARILADI (refund);
        4. telemetriya DB'ga yoziladi (user + kanal).

        Args:
            task: kanonik vazifa (``social_post``, ``channel_dna``,
                ``post_score``, ``repurpose``, ...).
            prompt: foydalanuvchi matni/mavzusi.
            db: ``database`` moduli (yoki test adapteri).
            user_id/channel_id: kvota va hisobot konteksti.
            lane: ``"fast" | "smart" | "premium"`` yoki aniq ``Lane``.
            operation_type: kvota turi (bo'lmasa task'dan aniqlanadi).
            cost: kvota birligi (standart 1).
            context: FSM context (bron ID'sini saqlash uchun).
            ctx_prefix: bron kaliti prefiksi (masalan ``magic``/``studio``).
            reserve_quota: ``False`` bo'lsa kvota bron qilinmaydi
                (bepul operatsiyalar, masalan ``post_score``).
            require_quality: qat'iy sifat validatori (standart: yoqilgan).
            limit_text: kvota tugaganda ko'rsatiladigan tayyor matn.
            persist_usage: telemetriyani DB'ga yozish.

        Returns:
            :class:`AITaskOutcome` — hech qachon istisno otilmaydi.
        """
        op_type = operation_type_for(task, operation_type)
        reservation: dict = {
            "allowed": False, "reason": "skipped", "reservation_id": None,
            "operation_type": op_type,
        }
        refunded = False

        # 1) KVOTA BRONI (faqat foydalanuvchi + db bo'lsa; fail-closed).
        charged = bool(reserve_quota and user_id is not None and db is not None)
        if charged:
            try:
                if context is not None and ctx_prefix:
                    from services.ai_quota import reserve_for_flow

                    reservation = await reserve_for_flow(
                        db, context, int(user_id), op_type, ctx_prefix, cost)
                else:
                    from services.ai_quota import reserve_ai_quota

                    reservation = await reserve_ai_quota(
                        db, int(user_id), op_type, cost)
            except Exception as exc:  # noqa: BLE001 — fail-closed
                logger.error("AI kvota bron xatosi (user=%s, task=%s): %s",
                             user_id, task, exc)
                reservation = {
                    "allowed": False, "reason": "db_error", "reservation_id": None,
                    "operation_type": op_type,
                }
            reservation.setdefault("operation_type", op_type)
            if not reservation.get("allowed"):
                from services.ai_quota import denial_message

                return AITaskOutcome(
                    ok=False, denied_reason=str(reservation.get("reason") or ""),
                    reservation=reservation,
                    error=denial_message(reservation, limit_text, lang) if limit_text
                    else None,
                )

        # 2) SHLYUZ (yagona interfeys) — telemetriya shlyuz ichida yoziladi.
        try:
            result = await self.gateway.generate(
                prompt, task=task, lane=lane, lang=lang,
                system_instruction=system_instruction, timeout=timeout,
                use_cache=use_cache, tone=tone, is_pro=is_pro, schema=schema,
                channel_context=channel_context, user_id=user_id,
                channel_id=channel_id, operation_type=op_type,
                require_quality=require_quality, **kwargs,
            )
        except Exception as exc:  # noqa: BLE001 — shlyuz istisno otmaydi, lekin himoya
            logger.error("AI shlyuz kutilmagan xatosi (task=%s): %s", task, exc)
            result = GatewayResult(
                ok=False, task=str(task or ""), error=None,
                failure_kind="other", status=telemetry.STATUS_FAILED,
                user_id=user_id, channel_id=channel_id,
            )

        # 3) XATO → BRONNI QAYTARISH (foydalanuvchi to'lovi yonib ketmasin).
        if not result.ok and charged:
            try:
                from services.ai_quota import release_ai_quota

                refunded = bool(await release_ai_quota(
                    db, int(user_id), reservation.get("reservation_id")))
            except Exception as exc:  # noqa: BLE001
                logger.error("AI kvota refund xatosi (user=%s): %s", user_id, exc)
                refunded = False

        # 4) TELEMETRIYA (batafsil yozuv) — DB + in-memory.
        event_dict = dict(result.usage or {})
        if not event_dict:
            event = telemetry.build_usage_event(
                result=result, prompt=prompt, system_instruction=system_instruction or "",
                task=task, operation_type=op_type, user_id=user_id,
                channel_id=channel_id,
                reservation_id=reservation.get("reservation_id"),
            )
            event_dict = event.as_dict()
            try:
                self.recorder.record(event)
            except Exception:  # pragma: no cover — himoya
                pass
        usage_id = None
        if persist_usage:
            usage_id = await self._save_usage(db, event_dict, reservation)

        return AITaskOutcome(
            ok=bool(result.ok), text=str(result.text or ""), result=result,
            reservation=reservation, refunded=refunded, usage=event_dict,
            usage_id=usage_id,
        )

    # -------------------------------------------------------------- hisobot
    async def usage_report(
        self,
        db=None,
        *,
        user_id: int | None = None,
        channel_id: int | None = None,
        period: str = telemetry.PERIOD_DAILY,
    ) -> dict:
        """Kunlik/oylik xarajat va foydalanish hisoboti (user/kanal kesimida).

        DB mavjud bo'lsa — ``get_ai_usage_report`` agregati (butun tarix);
        har holatda in-memory telemetriya (joriy jarayon) ham qo'shiladi.
        """
        memory = self.recorder.report(
            user_id=user_id, channel_id=channel_id, period=period)
        database_report = None
        if db is not None and hasattr(db, "get_ai_usage_report") and self._real_db(db):
            try:
                database_report = await db.run_db(
                    db.get_ai_usage_report,
                    user_id=user_id, channel_id=channel_id, period=period)
            except Exception as exc:  # noqa: BLE001 — hisobot best-effort
                logger.warning("AI usage hisobotini olishda xato: %s", exc)
        return {
            "period": period,
            "scope": {"user_id": user_id, "channel_id": channel_id},
            "source": "database" if database_report else "memory",
            "database": database_report,
            "memory": memory,
        }

    async def quota_status(self, db, user_id: int) -> dict:
        """Foydalanuvchining kunlik AI kvotasi holati (used/max/remaining)."""
        if db is None or user_id is None:
            return {"used": 0, "max_ai": 0, "remaining": 0, "available": False}
        try:
            limit = await db.run_db(db.check_ai_limit, int(user_id))
        except Exception as exc:  # noqa: BLE001 — fail-closed ko'rsatkich
            logger.warning("AI kvota holatini olishda xato: %s", exc)
            return {"used": -1, "max_ai": 0, "remaining": 0, "available": False}
        if isinstance(limit, (tuple, list)) and limit:
            used = int(limit[1] or 0) if len(limit) > 1 else 0
            max_ai = int(limit[2] or 0) if len(limit) > 2 else 0
        elif isinstance(limit, dict):
            used = int(limit.get("used") or 0)
            max_ai = int(limit.get("max_ai") or 0)
        else:
            used, max_ai = 0, 0
        return {
            "used": used, "max_ai": max_ai,
            "remaining": max(0, max_ai - used), "available": True,
        }


#: Yagona Application Service obyekti (handler va servislar shundan oladi).
ai_tasks = AITaskService()


async def run_ai_task(**kwargs) -> AITaskOutcome:
    """Qulaylik delegati: ``ai_tasks.run(...)`` (yagona Application Service)."""
    return await ai_tasks.run(**kwargs)


async def usage_report(db=None, **kwargs) -> dict:
    """Qulaylik delegati: ``ai_tasks.usage_report(...)``."""
    return await ai_tasks.usage_report(db, **kwargs)


__all__ = [
    "AITaskOutcome",
    "AITaskService",
    "ai_tasks",
    "run_ai_task",
    "usage_report",
    "operation_type_for",
    "TASK_OPERATION_TYPES",
    "DEFAULT_OPERATION_TYPE",
]
