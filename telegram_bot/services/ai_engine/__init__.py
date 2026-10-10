"""ESKIRGAN (deprecated) YO'L — ``services.ai_engine`` → ``services.ai.engine``.

AI STEK DE-BLOAT (yagona fasad) natijasida KANONIK AI shlyuz kodi endi
faqat :mod:`services.ai.engine` da yashaydi. Ushbu paket — **nol biznes-logikali**
muvofiqlik (backward-compatibility) shimi: eski ``from services.ai_engine import ...``
va ``from services.ai_engine.<submodul> import ...`` importlarini buzmaslik
uchun saqlangan.

Yangi kod uchun::

    from services.ai import facade as ai          # tavsiya etilgan kirish nuqtasi
    from services.ai.engine import gateway        # to'g'ridan-to'g'ri kerak bo'lsa

Bu faylda HECH QANDAY AI logikasi yo'q — faqat qayta eksport va
``sys.modules`` taxalluslari (shu sababli ikki nusxa kod/dublikat holat yo'q:
``services.ai_engine.gateway`` va ``services.ai.engine.gateway`` — AYNI BIR
modul obyektidir, monkeypatch ikki tomondan ham bir xil ishlaydi).
"""

from __future__ import annotations

import importlib as _importlib
import sys as _sys

from services.ai import engine as _engine

# --- 1) Ommaviy API'ni qayta eksport qilish --------------------------------
__all__ = list(getattr(_engine, "__all__", [])) or [
    name for name in vars(_engine) if not name.startswith("_")
]
for _name in list(__all__):
    globals()[_name] = getattr(_engine, _name)

# --- 2) Submodul taxalluslari (eski nuqta-notatsiyasi ishlashi uchun) -------
#: ``services.ai.engine`` ostidagi barcha haqiqiy submodullar.
_SUBMODULES = (
    "app_service",
    "cache",
    "gateway",
    "health",
    "prompts",
    "providers",
    "retry",
    "router",
    "safety",
    "schemas",
    "telemetry",
    "validator",
)

for _sub in _SUBMODULES:
    _mod = _importlib.import_module(f"services.ai.engine.{_sub}")
    # `import services.ai_engine.gateway` / `from services.ai_engine import gateway`
    # va `from services.ai_engine.gateway import X` — barchasi shu bitta
    # modul obyektiga yo'naltiriladi (dublikat modul holati YARATILMAYDI).
    _sys.modules[f"{__name__}.{_sub}"] = _mod
    globals()[_sub] = _mod

__all__ += list(_SUBMODULES)


def __getattr__(name: str):  # pragma: no cover — himoya qatlami
    """Kutilmagan atribut so'rovi kanonik paketga yo'naltiriladi."""
    try:
        return getattr(_engine, name)
    except AttributeError as exc:  # pragma: no cover
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r} "
            "(kanonik joy: services.ai.engine)"
        ) from exc
