"""ESKIRGAN (deprecated) YO'L — ``services.ai_service`` → ``services.ai.fallback``.

AI STEK DE-BLOAT (yagona fasad) natijasida 8-provayderli fallback zanjiri
(``AIFallbackService``, ``run_ai_chain``, Core provayder adapterlari, rasm
tahlili va post-score yordamchilari) endi KANONIK joyda —
:mod:`services.ai.fallback` da yashaydi.

Bu fayl **nol biznes-logikali** muvofiqlik shimi. U oddiy ``import *``
emas, balki ``sys.modules`` IDENTITY taxallusini qo'llaydi: import
tugagach ``services.ai_service`` va ``services.ai.fallback`` — AYNI BIR
modul obyektiga aylanadi. Shu sababli:

* dublikat kod/dublikat modul holati YARATILMAYDI (bitta nusxa);
* modul darajasidagi o'zgaruvchilarga qilingan monkeypatch
  (``ai_service.AI_PROVIDER_TOTAL_TIMEOUT = ...``,
  ``ai_service.run_ai_chain = ...``) ikkala nomdan ham ko'rinadi va
  ``provider_total_timeout()`` kabi ichki o'quvchilar ham uni sezadi —
  mavjud test kontraktlari O'ZGARMAYDI.

Yangi kod uchun::

    from services.ai import fallback          # kanonik
    from services.ai import facade as ai      # tavsiya etilgan umumiy kirish
"""

from __future__ import annotations

import sys as _sys

from services.ai import fallback as _fallback

# Import mexanizmi modul bajarilgandan SO'NG ``sys.modules`` ni qayta o'qiydi
# (CPython: ``module = sys.modules.pop(spec.name)``) — shu sababli quyidagi
# almashtirish ``services.ai_service`` nomini KANONIK modulga bog'laydi.
_sys.modules[__name__] = _fallback
