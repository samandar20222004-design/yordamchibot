"""Provider Registry — AI ENGINE V2 (Faza 1).

MUHIM SIYOSAT: **hech narsa noldan qayta yozilmaydi.** Barcha real HTTP
ishlari sinovdan o'tgan ``services/ai_service.py`` provayder adapterlarida
(Gemini/Groq/OpenRouter/Mistral/Cerebras/SambaNova/Cloudflare/Pollinations)
qoladi — ular:

* har bir provayder uchun qat'iy connect/read/total timeout;
* 429 (rate limit) retry logikasi;
* model auto-discovery — shu yerda allaqachon bor.

Bu modul faqat REGISTR va nozik ijro yordamchisi:

* :func:`build_provider_handles` — kanonik nom → provayder adapter xaritasi
  (har chaqiruvda qayta quriladi: kalitlar/``AI_PROVIDER_CHAIN`` env
  runtime'da o'zgarsa darhol hisobga olinadi);
* :func:`resolve_handles` — lane tartibini faqat MA VJUD provayderlarga
  qisqartiradi;
* :func:`execute_provider` — bitta provayderni qat'iy timeout bilan
  chaqiradi (natija: provayder qaytargan JSON dict).

Shlyuz (:mod:`services.ai_engine.gateway`) shu uchtaga tayanadi.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Iterable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderHandle:
    """Registr yozuvi: kanonik nom + sinovdan o'tgan adapter obyekti."""

    name: str
    provider: object  # services.ai_service.AIProvider (adapter)


def build_provider_handles() -> dict[str, ProviderHandle]:
    """Kanonik provayder nomlari → adapter xaritasi (har chaqiruvda yangi).

    ``services.ai_service.build_default_providers()`` YAGONA manba bo'lib
    qoladi — bu yerda provayder kodi TAKRORLANMAYDI.
    """
    from services import ai_service

    handles: dict[str, ProviderHandle] = {}
    for adapter in ai_service.build_default_providers():
        name = str(getattr(adapter, "name", "") or "").strip()
        if name:
            handles[name] = ProviderHandle(name=name, provider=adapter)
    return handles


def resolve_handles(order: Iterable[str]) -> list[ProviderHandle]:
    """Tartibni mavjud (kaliti sozlangan) provayderlargacha qisqartiradi.

    ``is_available()`` kalit mavjudligini CHAQIRUV paytida tekshiradi —
    testlar/runtime kalitni almashtirsa zanjir darhol moslashadi
    (legacy xatti-harakat bilan bir xil).
    """
    handles = build_provider_handles()
    resolved: list[ProviderHandle] = []
    seen: set[str] = set()
    for name in order:
        if name in seen:
            continue
        handle = handles.get(name)
        if handle is None:
            continue
        if not handle.provider.is_available():
            continue
        seen.add(name)
        resolved.append(handle)
    return resolved


async def execute_provider(
    handle: ProviderHandle,
    prompt: str,
    system_instruction: str,
    *,
    lang: str | None = None,
    timeout: float = 10.0,
) -> dict:
    """Bitta provayderni QAT'IY timeout bilan chaqiradi.

    Muvaffaqiyat: provayder qaytargan JSON dict (legacy zanjir shakli —
    ``post_text``/``content``/``text`` maydonlaridan biri bilan).
    Xato/timeout: istisno ko'tariladi (shlyuz keyingi provayderga o'tadi).
    """
    from services import ai_service
    from utils import ai_agent as aa

    params = aa.get_runtime_params()
    started = time.monotonic()
    result = await asyncio.wait_for(
        handle.provider.complete(
            prompt, system_instruction, params, deadline=time.monotonic() + timeout
        ),
        timeout=max(0.1, float(timeout)),
    )
    if not isinstance(result, dict):
        raise ai_service.AIProviderError(
            0, f"{handle.name}: javob formati noto'g'ri ({type(result).__name__})",
            provider=handle.name)
    logger.info("AI Engine: %s %.2fs ichida javob berdi", handle.name,
                time.monotonic() - started)
    return result


__all__ = [
    "ProviderHandle",
    "build_provider_handles",
    "resolve_handles",
    "execute_provider",
]
