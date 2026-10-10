"""⚡ CALLBACK «DARHOL JAVOB» — inline tugma spinner'ini lahzalik to'xtatish.

Muammo: Telegram inline tugma bosilgandan keyin ``answerCallbackQuery``
kelguncha tugmada «yuklanmoqda» aylanishini ko'rsatadi. Ko'p handler'lar
``query.answer()`` ni og'ir DB/AI ishidan KEYIN chaqirardi — natijada
tugma 3-5 soniya qotib turardi.

Yechim (ikki qatlam):

1. **Idempotent ``CallbackQuery.answer``** — :func:`install_answer_guard`
   bir marta o'rnatiladi. Bitta callback uchun birinchi ``answer`` haqiqiy
   Telegram chaqiruvini qiladi; keyingi chaqiruvlar (dublikat, handler va
   markaziy ack poygasi) Telegram'ga bormaydi va xato bermaydi. Shu sababli
   handler ``await query.answer()`` ni ENG BOSHIDA chaqirsa ham, keyin
   chaqirilgan toast/xato javoblari tufayli istisno ko'tarilmaydi.

2. **Muddatli markaziy ack** — :func:`schedule_early_ack` har bir callback
   uchun fon vazifa ochadi. Agar handler ``CALLBACK_EARLY_ACK_SECONDS``
   ichida javob bermasa (masalan, DB/AI ishi hali tugamagan yoki foydalanuvchi
   navbatda turibdi), tugma darhol oddiy ack bilan bo'shatiladi. Handler
   shu muddatdan oldin tugasa, vazifa bekor qilinadi — tez handler'larning
   toast xabarlari (``answer(text, show_alert=True)``) to'liq saqlanadi.

Kompromiss (hujjatlangan): muddatdan keyin handler chiqargan toast Telegram
tomonidan ko'rsatilmaydi (callback allaqachon javoblangan). Holat xatoga
olinadi (``debug`` log) va asosiy oqim davom etadi.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import OrderedDict

from telegram import CallbackQuery

from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

#: Handler javob bermasa, markaziy oddiy ack shu muddatdan keyin yuboriladi
#: (ms). Spinner tugashi = shu muddat + Telegram answer RTT (~100-200 ms),
#: shuning uchun standart 150 ms: sekin handler'da ham foydalanuvchi ~300 ms
#: ichida javob oladi, tez handler'larning toast'lari esa saqlanadi.
EARLY_ACK_MS = max(0, int(os.getenv("CALLBACK_EARLY_ACK_MS", "150") or 150))
EARLY_ACK_SECONDS = EARLY_ACK_MS / 1000.0

#: Javoblangan callback ID'lar (bounded LRU — xotira o'smasligi uchun).
_ANSWERED_MAX = 4096
_ANSWERED: "OrderedDict[str, None]" = OrderedDict()

_ORIGINAL_ANSWER = CallbackQuery.answer
_GUARD_INSTALLED = False


def _mark_answered(query_id: str) -> bool:
    """``query_id`` ni javoblangan deb belgilaydi.

    Qaytadi: ``True`` — shu chaqiruv birinchi (Telegram'ga borsin);
    ``False`` — allaqachon javoblangan (dublikat, o'tkazib yuborilsin).
    """
    if query_id in _ANSWERED:
        _ANSWERED.move_to_end(query_id)
        return False
    _ANSWERED[query_id] = None
    while len(_ANSWERED) > _ANSWERED_MAX:
        _ANSWERED.popitem(last=False)
    return True


def is_answered(query) -> bool:
    """Callback allaqachon javoblanganmi (markaziy ack kerakmi?)."""
    query_id = str(getattr(query, "id", "") or "")
    return bool(query_id) and query_id in _ANSWERED


def install_answer_guard() -> None:
    """``CallbackQuery.answer`` ni idempotent qilib o'rnatadi (bir marta)."""
    global _GUARD_INSTALLED
    if _GUARD_INSTALLED:
        return

    async def guarded_answer(self, *args, **kwargs):
        query_id = str(getattr(self, "id", "") or "")
        if query_id and not _mark_answered(query_id):
            logger.debug("callback allaqachon javoblangan — dublikat answer o'tkazildi")
            return True
        return await _ORIGINAL_ANSWER(self, *args, **kwargs)

    guarded_answer.__wrapped__ = _ORIGINAL_ANSWER  # type: ignore[attr-defined]
    CallbackQuery.answer = guarded_answer  # type: ignore[method-assign]
    _GUARD_INSTALLED = True


install_answer_guard()


async def _early_ack(query, delay: float) -> None:
    try:
        await asyncio.sleep(delay)  # bekor qilish shu yerda xavfsiz
        if is_answered(query):
            return
        # Guard orqali: belgilanadi va haqiqiy answer yuboriladi. shield —
        # vazifa bekor qilinsa ham yarim yuborilgan so'rov uzilmaydi.
        await asyncio.shield(query.answer())
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — ack xatosi asosiy oqimni buzmasin
        log_silent_failure("utils.callback_ack:_early_ack", exc)


def schedule_early_ack(query, delay: float | None = None):
    """Callback uchun muddatli markaziy ack vazifasini rejalashtiradi.

    Qaytadi: ``asyncio.Task`` (bekor qilish uchun) yoki ``None`` (callback
    emas yoki event loop yo'q). Chaqiruvchi handler tugagach
    :func:`cancel_early_ack` ni chaqirishi shart.
    """
    if query is None or not getattr(query, "id", None):
        return None
    if is_answered(query):
        return None
    wait = EARLY_ACK_SECONDS if delay is None else max(0.0, float(delay))
    try:
        return asyncio.ensure_future(_early_ack(query, wait))
    except RuntimeError:  # pragma: no cover — event loop yo'q
        return None


def cancel_early_ack(task) -> None:
    """Muddatli ack vazifasini bekor qiladi (handler muddatdan oldin tugasa).

    Bekor qilish xavfsiz: ack allaqachon yuborilayotgan bo'lsa, so'rov
    ``asyncio.shield`` ostida tugallanadi (Telegram so'rovi yarim qolmaydi).
    """
    if task is None or task.done():
        return
    task.cancel()
