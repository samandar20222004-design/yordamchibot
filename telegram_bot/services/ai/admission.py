# -*- coding: utf-8 -*-
"""🛡 AI QABUL QILISH + TELEMETRIYA (STEP 1) — fallback yo'li uchun yagona qatlam.

Gateway yo'li (``AIGateway.generate``) o'z gate/byudjet/telemetriyasiga ega.
Handler trafigi esa ko'pincha ``services.ai.fallback`` orqali o'tadi — bu
modul o'sha yo'lga BIR XIL qoidalarni beradi:

* :func:`admit_ai_request` — foydalanuvchi uchun parallel-job limiti
  (:mod:`services.ai.concurrency`) va kunlik/oylik AI byudjeti
  (:mod:`services.ai.budget`). Rad etilsa — provayder chaqirilmaydi.
* :func:`record_request` — natijani gateway telemetriyasiga (recorder +
  xarajat ledger'i) yozadi; ``usage_scope(suppress_recording=True)`` ichida
  esa yozmaydi (ikki marta hisoblashning oldini olish, masalan legacy_chain).

Foydalanuvchi konteksti :func:`services.ai.usage_scope.usage_scope` dan
olinadi (``main.py`` update darajasida o'rnatadi). Kontekst yo'q bo'lsa —
gate/byudjet qo'llanmaydi, lekin telemetriya (user_id=None) yoziladi.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from services.ai.budget import (
    budget_message,
    default_guard,
    estimate_request,
    resolve_tier,
)
from services.ai.concurrency import default_user_gate, user_busy_message
from services.ai.usage_scope import current_scope

logger = logging.getLogger(__name__)


@dataclass
class Admission:
    """Qabul natijasi. ``allowed=False`` bo'lsa ``error`` — foydalanuvchi matni."""

    allowed: bool = True
    reason: str = "ok"
    error: str | None = None
    gated_user: int | None = None
    ticket: object | None = None

    def release(self) -> None:
        """Slot va byudjet bronini bo'shatadi (idempotent)."""
        if self.ticket is not None:
            default_guard().release(self.ticket)
            self.ticket = None
        if self.gated_user is not None:
            default_user_gate().release(self.gated_user)
            self.gated_user = None


async def admit_ai_request(prompt: str, system_instruction: str = "",
                           lang: str | None = None) -> Admission:
    """Foydalanuvchi limiti + AI byudjeti. Kontekst yo'q → doim ruxsat."""
    scope = current_scope()
    user_id = scope.user_id if scope is not None else None
    if user_id is None:
        return Admission(True, "ok")
    gate = default_user_gate()
    if not gate.try_acquire(user_id):
        logger.info("AI fallback: foydalanuvchi limiti (user=%s)", user_id)
        return Admission(False, "user_busy", user_busy_message(lang or "uz"), user_id)
    try:
        tier = await resolve_tier(user_id, False)
        tokens, usd = estimate_request(prompt, system_instruction or "")
        decision = await default_guard().acquire(user_id, tier, tokens, usd)
    except BaseException:
        gate.release(user_id)
        raise
    if not decision.allowed:
        gate.release(user_id)
        logger.info("AI fallback: byudjet tugadi (user=%s, %s)", user_id, decision.reason)
        return Admission(False, decision.reason,
                         budget_message(lang or "uz", decision.period), user_id)
    return Admission(True, "ok", None, user_id, decision.ticket)


def record_request(*, ok: bool, provider: str = "", model: str = "", text: str = "",
                   prompt: str = "", system_instruction: str = "",
                   started: float | None = None, failure_kind: str | None = None,
                   error: str | None = None, task: str = "") -> None:
    """Fallback natijasini gateway telemetriyasiga yozadi (best-effort).

    ``suppress_recording`` faol bo'lsa (ichki chaqiruv) — hech narsa yozilmaydi.
    """
    scope = current_scope()
    if scope is not None and scope.suppress_recording:
        return
    try:
        from services.ai.engine.gateway import GatewayResult, Lane, ai_gateway
        from services.ai.engine.telemetry import STATUS_FAILED, STATUS_SUCCESS

        elapsed = max(0.0, time.monotonic() - started) if started else 0.0
        result = GatewayResult(
            ok=bool(ok), text=str(text or ""),
            provider=str(provider or ("none" if not ok else "")) or "none",
            lane=Lane.QUALITY, task=str(task or ""), elapsed=elapsed,
            error=error, failure_kind=(None if ok else (failure_kind or "other")),
            status=STATUS_SUCCESS if ok else STATUS_FAILED,
            user_id=scope.user_id if scope is not None else None,
            channel_id=scope.channel_id if scope is not None else None,
            model=str(model or ""),
        )
        ai_gateway._record(
            result, prompt=prompt, system_instruction=system_instruction,
            operation_type=(scope.action_type or "") if scope is not None else "",
            user_id=result.user_id, channel_id=result.channel_id,
        )
    except Exception as exc:  # noqa: BLE001 — telemetriya AI oqimini buzmaydi
        logger.warning("AI fallback telemetriya xatosi: %s", exc)


__all__ = ["Admission", "admit_ai_request", "record_request"]
