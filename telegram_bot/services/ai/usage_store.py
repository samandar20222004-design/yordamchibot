# -*- coding: utf-8 -*-
"""💾 AI USAGE HODISALARINI DB'GA SAQLASH (production yo'li).

Muammo: ``ai_usage_events`` ni faqat ``AITaskService`` yozardi, uni production
kodida hech kim chaqirmaydi. Gateway/fallback/legacy yo'llari hodisani faqat
jarayon xotirasiga (``UsageRecorder`` + ``CostLedger``) yozardi: restart bilan
yo'qolardi, instance'lar bir-birini ko'rmasdi.

Bu modul har bir telemetriya hodisasini ``database.save_ai_usage_event`` orqali
saqlaydi (fire-and-forget: AI javobini kechiktirmaydi, xatosi AI oqimini
buzmaydi). Semantika ustunlardan aniqlanadi (``cost_status`` ustuni yo'q):

* muvaffaqiyat, narxli      → ``status='success' AND priced``
* muvaffaqiyat, narxi noma'lum → ``status='success' AND NOT priced AND NOT cached``
  (``estimated_cost = 0``: taxminiy budjet sarfi bu yerda YOZILMAYDI)
* kesh                      → ``cached`` (xarajat 0)
* xato / timeout / rad      → ``status='failed'`` (``error_code`` = xato turi)

Eslatma: bu yozuv BEST-EFFORT. Jarayon yozuv tugamasdan to'xtasa hodisa
yo'qolishi mumkin (:func:`drain` graceful shutdown'da kutadi). Global
xarajat chegarasi hodisalarga emas, atomik ``ai_budget_*`` jadvallariga
tayanadi (``repositories/ai_budget_repository.py``).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)

_PENDING: set = set()

_FIELDS = (
    "user_id", "channel_id", "task", "lane", "operation_type", "provider",
    "model", "input_tokens", "output_tokens", "latency_ms", "estimated_cost",
    "priced", "status", "error_code", "cached", "attempts", "prompt_hash",
    "reservation_id",
)


def persist_enabled() -> bool:
    """``AI_USAGE_PERSIST=0`` bilan o'chiriladi (sukut: yoqilgan)."""
    return os.getenv("AI_USAGE_PERSIST", "1").strip().lower() not in (
        "0", "false", "no", "off", "")


def _database():
    """Haqiqiy DB moduli (pool tayyor bo'lsa), aks holda ``None`` (testlarda almashtiriladi)."""
    database = sys.modules.get("database")
    if database is None or getattr(database, "_pool", None) is None:
        return None
    return database


def _fields_of(event: dict) -> dict:
    return {key: event.get(key) for key in _FIELDS if key in event}


def persist_usage_event(event: dict) -> bool:
    """Hodisani fonda DB'ga yozishga navbatga qo'yadi. Qaytadi: navbatga qo'yildimi."""
    try:
        if not persist_enabled() or not isinstance(event, dict):
            return False
        database = _database()
        if database is None:
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False          # sinxron kontekst: blokirovka qilmaymiz
        fields = _fields_of(event)
        task = loop.create_task(_write(database, fields))
        _PENDING.add(task)
        task.add_done_callback(_PENDING.discard)
        return True
    except Exception as exc:  # noqa: BLE001 — telemetriya AI'ni buzmaydi
        logger.debug("usage_store: navbatga qo'yib bo'lmadi: %s", exc)
        return False


async def _write(database, fields: dict) -> None:
    try:
        await database.run_db(database.save_ai_usage_event, **fields)
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI usage yozuvini saqlab bo'lmadi: %s", exc)


async def drain(timeout: float = 5.0) -> int:
    """Kutilayotgan yozuvlarni tugashini kutadi (graceful shutdown/testlar). Qaytadi: qolgani."""
    pending = [t for t in list(_PENDING) if not t.done()]
    if pending:
        await asyncio.wait(pending, timeout=max(0.0, float(timeout)))
    return len([t for t in _PENDING if not t.done()])


__all__ = ["drain", "persist_enabled", "persist_usage_event"]
