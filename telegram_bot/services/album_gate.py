"""🖼 ALBOM (media_group) DARVOZASI — bitta albom = BITTA post.

MUAMMO (tuzatilishi shart bo'lgan nosozlik)
-------------------------------------------
Telegram albomning har bir faylini ALOHIDA update sifatida yuboradi
(3 rasmli albom = 3 update). Handlerlar har bir update'ni mustaqil xabar deb
qabul qilsa, foydalanuvchi bitta albom uchun **bir nechta preview kartasi,
bir nechta tugmalar to'plami va bir nechta post** ko'radi.

YECHIM
------
Barcha yangi media update'lar (``group=-3`` da, asosiy FSM'dan OLDIN)
shu darvozadan o'tadi:

1. Xabarda ``media_group_id`` bo'lsa — media DARHOL yagona media handlerlariga
   uzatilmaydi: darvoza uni yig'uvchi buferiga qo'shadi va update zanjiri
   ``ApplicationHandlerStop`` bilan TO'XTATILADI (bitta albom = bitta
   "post" hodisasi).
2. Oxirgi fayldan keyin ``ALBUM_DEBOUNCE_SECONDS`` (qat'iy 2.0s) jimlik
   o'tsa, yig'ilgan BARCHA fayllar bitta :class:`AlbumPayload` ga aylanadi.
3. Payload yagona konsolidatsiyalangan update sifatida PTB zanjiriga
   qaytariladi (``Application.process_update``): preview render qiluvchi
   handler **AYNAN BIR MARTA** ishlaydi, izoh (caption) butun albomga
   birlashtiriladi va kanalga yuborishda barcha fayllar bitta
   ``sendMediaGroup`` chaqiruviga ketadi.

Kafolatlar
----------
* Bir xil ``media_group_id`` uchun bufer/worker FAQAT bitta (collector
  per-key lock + ``add_many`` atomikligi).
* Payload FAQAT bir marta "iste'mol qilinadi" (``mark_consumed``) — takroriy
  preview/crash bo'lmaydi.
* Qayta uzatish (release) ``GuardedApplication``ning per-user lock'i ostida,
  ``UPDATE_HANDLER_TIMEOUT_SECONDS`` chegarasi bilan bajariladi: albom
  handleri boshqa update'lar bilan poyga qilmaydi va botni "osib"
  qo'ymaydi.
* Rate limiter yangi update deb qayta sanamaydi (``pre_admitted``).
* Xato bo'lsa albom logga yoziladi, keyingi update'lar ishlashda davom
  etadi (fail-soft).
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import AsyncExitStack
from typing import Any, Awaitable, Callable

from telegram import Update
from telegram.ext import ApplicationHandlerStop, TypeHandler

from services.media_group_collector import (
    ALBUM_DEBOUNCE_SECONDS,
    DEFAULT_MAX_WAIT_SECONDS,
    AlbumPayload,
    MediaGroupCollector,
    album_caption,
    album_caption_html,
    apply_album_caption,
    extract_media_item,
    is_media_group_message,
    media_group_id_of,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AlbumGate",
    "AlbumGateHandler",
    "ALBUM_PENDING_KEY",
    "ALBUM_GATE_GROUP",
    "register_album_gate",
    "get_album_gate",
    "take_album_payload",
    "album_items_of",
    "album_caption_of",
]

#: ``context.user_data`` kaliti: hali iste'mol qilinmagan albom payload'lari
#: (``{media_group_id: AlbumPayload}``). Har bir payload FAQAT bir marta
#: olinadi (``take_album_payload``) — takroriy preview yo'q.
ALBUM_PENDING_KEY = "_album_pending_payloads"

#: Darvoza guruhi. PTB guruhlarni O'SISH tartibida ishlatadi (-3, -2, -1, 0),
#: shuning uchun bu guruh rate limiter (-1) va RBAC (-2) dan ham, asosiy
#: handlerlar (0) dan ham OLDIN ishlaydi — shu tartibda yagona media
#: handlerlariga albomning bitta elementi ham yetib bormaydi.  (Guarded
#: admission/rate-limit tekshiruvi barcha guruhlardan oldin, update
#: qabul qilinishida bajariladi; qayta uzatilgan konsolidatsiyalangan
#: update esa ``pre_admitted`` bilan qayta sanalmaydi.)
ALBUM_GATE_GROUP = -3

#: Payload'lar shu soniyadan keyin eskirgan hisoblanadi va tozalanadi
#: (handler hech qachon iste'mol qilmagan holat uchun xotira himoyasi).
PAYLOAD_TTL_SECONDS = 300.0

#: Sintetik update ID bazasi (muqova update'i yo'q bo'lganda ishlatiladi).
_SYNTHETIC_UPDATE_BASE = 2_000_000_000

_ACTIVE_GATE: "AlbumGate | None" = None


def get_album_gate() -> "AlbumGate | None":
    """Oxirgi ro'yxatdan o'tgan darvoza (global yordamchilar uchun)."""
    return _ACTIVE_GATE


# =========================================================================
# PAYLOAD YORDAMCHILARI (handlerlar shu funksiyalarni chaqiradi)
# =========================================================================
def take_album_payload(context, message) -> AlbumPayload | None:
    """Shu xabar uchun yig'ilgan TO'LIQ albom payload'ini oladi (bir marta).

    ``None`` qaytaradi, agar xabar albom qismi bo'lmasa, payload topilmasa
    yoki u allaqachon iste'mol qilingan bo'lsa. Handlerlar shu natijaga
    qarab albomni bitta post sifatida qayta ishlaydi.
    """
    group_id = media_group_id_of(message)
    if not group_id:
        return None
    payload = None
    user_data = getattr(context, "user_data", None)
    if isinstance(user_data, dict):
        store = user_data.get(ALBUM_PENDING_KEY)
        if isinstance(store, dict):
            payload = store.pop(group_id, None)
            if not store:
                user_data.pop(ALBUM_PENDING_KEY, None)
    gate = _ACTIVE_GATE
    if gate is not None:
        found = gate.pop_payload(group_id, user_id=_user_id_of(context))
        payload = payload or found
    if payload is None:
        return None
    if not payload.mark_consumed():
        return None  # allaqachon ishlangan — takroriy preview TAQIQLANADI
    return payload


def album_items_of(context, message) -> list:
    """Payload bo'lsa — albomning BARCHA elementlari, aks holda bo'sh ro'yxat."""
    payload = take_album_payload(context, message)
    return payload.to_items() if payload is not None else []


def album_caption_of(context, message, default: str = "") -> str:
    """Yig'ilgan albom izohi (payload bo'lmasa — ``default``)."""
    payload = take_album_payload(context, message)
    if payload is None:
        return default
    return payload.caption or default


def _context_user_data(context) -> dict | None:
    """``context.user_data`` ni XAVFSIZ oladi (PTB ``KeyError`` bermasin).

    ``CallbackContext.user_data`` ``application.user_data[user_id]`` ga
    murojaat qiladi va foydalanuvchi yozuvi hali ochilmagan bo'lsa xato
    berishi mumkin (masalan, minimal/test Application). Darvoza hech qachon
    shu sababli yiqilmasligi kerak — payload zaxira omborida saqlanadi.
    """
    try:
        data = getattr(context, "user_data", None)
    except Exception:  # noqa: BLE001 — adapter/PTB ichki xatosi
        return None
    return data if isinstance(data, dict) else None


def _user_id_of(context) -> int | None:
    value = getattr(context, "user_id", None)
    if not value:
        value = getattr(context, "_user_id", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _chat_id_of(update) -> int | None:
    chat = getattr(update, "effective_chat", None)
    if chat is None:
        chat = getattr(getattr(update, "message", None), "chat", None)
    value = getattr(chat, "id", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _set_message_caption(message, caption: str) -> None:
    """Muqova xabariga birlashtirilgan izohni yozadi (imkon bo'lsa).

    PTB ``Message`` obyekti "muzlatilgan" (frozen) va o'z ``__slots__``iga
    ega; shu sababli slot darajasida yoziladi. Minimal/test adapterlarida
    oddiy ``setattr`` ishlaydi. Xato bo'lsa — jim o'tiladi (payload'dagi
    izoh baribir ishlatiladi).
    """
    if not caption:
        return
    try:
        if (getattr(message, "caption", None) or "").strip() == caption.strip():
            return
    except Exception:  # noqa: BLE001 — ekzotik adapterlar
        return
    for write in (setattr, object.__setattr__):
        try:
            write(message, "caption", caption)
            return
        except Exception:  # noqa: BLE001, PERF203
            continue


class AlbumGate:
    """Media group update'larini ushlab, BITTA konsolidatsiyalangan post yasaydi."""

    def __init__(self, *, collector: MediaGroupCollector | None = None,
                 dispatcher: Callable[[Any], Awaitable[Any]] | None = None,
                 delay: float = ALBUM_DEBOUNCE_SECONDS,
                 max_wait: float = DEFAULT_MAX_WAIT_SECONDS):
        self.collector = collector or MediaGroupCollector(delay=delay, max_wait=max_wait)
        self._app = None
        self._dispatcher = dispatcher
        # Qayta uzatilayotgan update ID'lari — ayni update darvozaga qayta
        # tushmasligi uchun (Application.process_update qayta chaqiriladi).
        self._released_ids: set = set()
        # Iste'mol qilinmagan payload'lar (user_data yo'qolsa ham topiladi).
        self._payloads: dict = {}
        self._counter = 0
        self._stats = {
            "broadcasts_blocked": 0,   # nechta xom media update buferga ketdi
            "items_collected": 0,      # nechta fayl yig'ildi
            "groups_released": 0,      # nechta TO'LIQ albom qayta uzatildi
            "releases_dispatched": 0,  # shundan nechtasi handlerlarga yetdi
            "release_errors": 0,
            "payloads_dropped": 0,
        }

    # -- holat -------------------------------------------------------------
    def stats(self) -> dict:
        """Darvoza hisoboti (kuzatuv/test uchun)."""
        data = dict(self._stats)
        data.update({
            "pending_groups": len(self.collector.keys()),
            "pending_items": self.collector.pending(),
            "payloads_waiting": len(self._payloads),
            "debounce": self.collector.delay,
        })
        return data

    def attach(self, app) -> None:
        """Application havolasini o'rnatadi (qayta uzatish shu orqali bo'ladi)."""
        self._app = app

    def is_released(self, update) -> bool:
        """Bu update albom sifatida qayta uzatilyaptimi?"""
        return getattr(update, "update_id", None) in self._released_ids

    def intercepts(self, update) -> bool:
        """Update darvoza orqali ushlanishi kerakmi (xom albom elementi)?"""
        if update is None or self.is_released(update):
            return False
        message = getattr(update, "message", None)
        if message is None or not is_media_group_message(message):
            return False
        chat = getattr(update, "effective_chat", None)
        chat_type = getattr(chat, "type", None)
        if chat_type is not None and str(chat_type) != "private":
            return False
        return getattr(update, "effective_user", None) is not None \
            or getattr(message, "from_user", None) is not None

    # -- qabul qilish ------------------------------------------------------
    def consume(self, update, context) -> bool:
        """Xom albom elementini buferga qo'shadi.

        ``True`` — update darvoza tomonidan "yutilgan" (yagona media handlerlarga
        uzatilmaydi); ``False`` — xabar albomga tegishli emas (zanjir davom etadi).
        """
        message = getattr(update, "message", None)
        if message is None or not is_media_group_message(message):
            return False
        group_id = media_group_id_of(message)
        item = extract_media_item(message)
        if item is None:
            return False
        chat_id = _chat_id_of(update)
        user_id = getattr(getattr(update, "effective_user", None), "id", None)
        user_data = _context_user_data(context)
        key = (chat_id, group_id)

        async def on_ready(items):
            await self._release(key, group_id, items, message, update,
                                chat_id, user_id, user_data)

        self.collector.add(key, item, on_ready)
        self._stats["broadcasts_blocked"] += 1
        self._stats["items_collected"] += 1
        logger.debug(
            "AlbumGate: albom elementi buferga olindi (group=%s, fayl=%s, yig'ildi=%d)",
            group_id, item.get("file_id"), self.collector.pending(key),
        )
        return True

    def handle_update(self, update, context) -> None:
        """PTB handler callback'i — xom albom elementini ushlab zanjirni to'xtatadi."""
        if self.consume(update, context):
            # Asosiy FSM / yagona media handlerlarga bu update YETIB BORMAYDI.
            raise ApplicationHandlerStop

    # -- yakunlash ---------------------------------------------------------
    async def _release(self, key, group_id: str, items: list, message, update,
                       chat_id, user_id, user_data) -> None:
        """Yig'ilgan albomni BITTA payload qilib handlerlarga qayta uzatadi."""
        apply_album_caption(items)
        caption = album_caption(items)
        payload = AlbumPayload(
            media_group_id=group_id,
            items=list(items),
            chat_id=chat_id,
            user_id=user_id,
            caption=caption,
            caption_html=album_caption_html(items),
            message=message,
            update=update,
            key=key,
            released_at=time.monotonic(),
        )
        # Muqova xabarida izoh boshqa faylda bo'lgan bo'lsa ham ko'rinadi.
        _set_message_caption(message, caption)
        self._stats["groups_released"] += 1
        logger.info(
            "AlbumGate: albom yakunlandi (group=%s, fayllar=%d) — bitta preview",
            group_id, payload.count,
        )
        self._prune_payloads()
        if user_data is not None:
            store = user_data.setdefault(ALBUM_PENDING_KEY, {})
            if isinstance(store, dict):
                store[group_id] = payload
        self._payloads[(user_id, group_id)] = payload
        await self.release(payload)

    async def release(self, payload: AlbumPayload) -> bool:
        """Payload'ni yagona konsolidatsiyalangan update sifatida qayta uzatadi."""
        update = payload.update
        if update is None:
            self._counter += 1
            update = Update(update_id=_SYNTHETIC_UPDATE_BASE + self._counter,
                            message=payload.message)
            payload.update = update
        update_id = getattr(update, "update_id", None)
        if update_id is not None:
            self._released_ids.add(update_id)
        try:
            delivered = await self.dispatch(update)
        except Exception:  # noqa: BLE001 — bitta albom xatosi qolganlarini buzmaydi
            self._stats["release_errors"] += 1
            logger.exception("AlbumGate: albomni qayta uzatishda xato (group=%s)",
                             payload.media_group_id)
            return False
        finally:
            if update_id is not None:
                self._released_ids.discard(update_id)
        if delivered:
            self._stats["releases_dispatched"] += 1
        return bool(delivered)

    async def dispatch(self, update) -> bool:
        """Konsolidatsiyalangan update'ni handler zanjiriga uzatadi."""
        if self._dispatcher is not None:
            await self._dispatcher(update)
            return True
        app = self._app
        if app is None:
            logger.warning("AlbumGate: Application ulanmagan — albom uzatilmadi")
            return False
        return await self._dispatch_via_application(app, update)

    async def _dispatch_via_application(self, app, update) -> bool:
        """PTB zanjiriga uzatish: per-user lock + timeout + middleware hurmati.

        ``GuardedApplication`` per-user lock'i ishlatiladi — albom handleri
        foydalanuvchining boshqa update'lari bilan poyga qilmaydi. Rate limiter
        esa update'ni "allaqachon qabul qilingan" deb hisoblaydi (albom
        yig'ish jarayoni yangi flood hisoblanmaydi).
        """
        from config import UPDATE_HANDLER_TIMEOUT_SECONDS
        from telegram.ext import Application

        lock = self._user_lock(app, update)
        async with lock:
            async with AsyncExitStack() as stack:
                for middleware in self._middlewares(app):
                    try:
                        await stack.enter_async_context(middleware.pre_admitted(update))
                    except Exception:  # noqa: BLE001 — himoya qatlami fail-soft
                        logger.debug("AlbumGate: middleware scope o'rnatilmadi",
                                     exc_info=True)
                coro = Application.process_update(app, update)
                try:
                    await asyncio.wait_for(
                        coro, timeout=max(1.0, float(UPDATE_HANDLER_TIMEOUT_SECONDS)),
                    )
                except asyncio.TimeoutError:
                    logger.error("AlbumGate: albom handleri vaqt chegarasidan oshdi")
                    return False
        return True

    @staticmethod
    def _user_lock(app, update):
        """Application'ning per-user lock'i (bo'lmasa — no-op kontekst)."""
        manager = getattr(app, "_lock_manager", None)
        if manager is None:
            return _NullLock()
        try:
            from main import get_update_lock_key  # type: ignore
        except Exception:  # noqa: BLE001 — test/minimal muhit
            get_update_lock_key = None
        key = get_update_lock_key(update) if get_update_lock_key else None
        if key is None:
            user = getattr(update, "effective_user", None)
            key = f"user:{user.id}" if user is not None else None
        if key is None:
            return _NullLock()
        return manager.lock(key)

    @staticmethod
    def _middlewares(app):
        """RateLimitMiddleware instansiyalari (qayta sanashni oldini olish uchun)."""
        found = []
        try:
            groups = list(getattr(app, "handlers", {}).values())
        except Exception:  # noqa: BLE001
            return found
        for handlers in groups:
            for handler in handlers or ():
                if hasattr(handler, "pre_admitted") and hasattr(handler, "process_update"):
                    found.append(handler)
        return found

    # -- payload ombori ----------------------------------------------------
    def pop_payload(self, group_id: str, user_id: int | None = None) -> AlbumPayload | None:
        """Payload'ni olib tashlaydi (``user_data`` yo'qolgan holat uchun zaxira)."""
        if user_id is not None:
            return self._payloads.pop((user_id, group_id), None)
        for key in list(self._payloads):
            if key[1] == group_id:
                return self._payloads.pop(key, None)
        return None

    def pending_payload(self, group_id: str, user_id: int | None = None) -> AlbumPayload | None:
        """Payload'ni o'chirmasdan o'qiydi (test/observability uchun)."""
        if user_id is not None:
            return self._payloads.get((user_id, group_id))
        for key, payload in self._payloads.items():
            if key[1] == group_id:
                return payload
        return None

    def _prune_payloads(self) -> None:
        now = time.monotonic()
        stale = [key for key, payload in self._payloads.items()
                 if now - (payload.released_at or payload.created_at) > PAYLOAD_TTL_SECONDS]
        for key in stale:
            self._payloads.pop(key, None)
            self._stats["payloads_dropped"] += 1


class _NullLock:
    """``async with`` uchun bo'sh lock (Application lock manager'i yo'q bo'lsa)."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class AlbumGateHandler(TypeHandler):
    """``group=-3`` da turuvchi tutqich: FAQAT xom albom elementlarini oladi.

    ``check_update`` xabar albomga tegishli bo'lmasa ``None`` qaytaradi
    (update odatdagi zanjirda davom etadi). Albom elementi bo'lsa — buferga
    olinadi va ``ApplicationHandlerStop`` bilan zanjir to'xtatiladi, ya'ni
    bitta fayl ham yakka media handleriga tushmaydi.
    """

    def __init__(self, gate: AlbumGate):
        super().__init__(Update, gate.handle_update, block=True)
        self.gate = gate

    def check_update(self, update):
        if not isinstance(update, Update):
            return None
        return update if self.gate.intercepts(update) else None


def register_album_gate(app, *, gate: AlbumGate | None = None,
                        group: int = ALBUM_GATE_GROUP) -> AlbumGate:
    """Media group darvozasini Application'ga o'rnatadi va qaytaradi.

    Handler ``group=-3`` da ro'yxatdan o'tadi: rate limiter (-1), RBAC (-2)
    va asosiy FSM (0) dan oldin ishlaydi, lekin hech bir handler guruhining
    ishlashini buzmaydi (albom elementlari uchun ``ApplicationHandlerStop``).
    """
    global _ACTIVE_GATE
    gate = gate or AlbumGate()
    gate.attach(app)
    app.add_handler(AlbumGateHandler(gate), group=group)
    _ACTIVE_GATE = gate
    return gate
