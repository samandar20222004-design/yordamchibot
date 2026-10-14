"""🖼 Media group (albom) yig'uvchi — ``media_group_id`` bo'yicha debounce bufer.

Telegram albomning har bir faylini ALOHIDA update sifatida yuboradi (odatda
0.1–0.5 soniya ichida). Handler har bir updatega alohida javob bersa, bitta
albom bir nechta mustaqil postga bo'linib ketadi. Bu kollektor fayllarni
``(chat, media_group_id)`` kaliti bo'yicha yig'adi va OXIRGI fayldan
``delay`` soniya jimlik o'tgach BITTA ro'yxat sifatida ``on_ready`` ga beradi.

Muhim:
  * ``GuardedApplication`` har bir foydalanuvchi updatelarini ketma-ket
    ishlaydi, shu sababli handler ICHIDA ``sleep`` qilib bo'lmaydi — albomning
    qolgan qismlari navbatda kutib, har biri alohida post bo'lib ketadi.
    Kollektor kutishni ALOHIDA fon vazifasida bajaradi, handler esa darhol
    qaytadi.
  * Har bir yangi element debounce taymerini uyg'otadi va OXIRGI elementdan
    boshlab qayta sanaydi. Bitta bufer uchun faqat bitta worker yaratiladi.
  * Har bir kalitning alohida ``asyncio.Lock``'i bor. Timeout va ``flush`` bir
    paytda ishga tushsa ham faqat bittasi buferni olib, ``on_ready``'ni bir
    marta chaqiradi.
  * Dublikat update (bir xil ``message_id``) bir marta hisoblanadi.
  * ``max_wait`` — sekin tarmoqda ham yig'ish cheksiz cho'zilmaydi.
  * ``on_ready`` xatosi logga yoziladi va boshqa albomlarga ta'sir qilmaydi.

Modul faqat stdlib + asyncio ishlatadi (telegram bog'liqligi yo'q): xabar
obyektlari duck-typing orqali o'qiladi, shu sababli modulni handlermasdan
ham unit-test qilish mumkin.

Standart debounce — **2.0 soniya** (``ALBUM_DEBOUNCE_SECONDS``). Bu qiymat
butun loyiha uchun YAGONA manba: handlerlar o'z konstantalarini emas, shu
moduldagi qiymatni ishlatadi.

🖼 BIRLASHTIRILGAN (UNIFIED) PREVIEW: albom to'liq yig'ilgach preview
**BITTA tuzilgan javob** bo'lib chiqishi kerak — muqova media + butun albomga
tegishli caption + boshqaruv tugmalari bir xabarda. Media fayllarni va
menyuni ikki alohida xabarga bo'lish preview'ni uzib qo'yadi (panel yuqorida,
media pastda "uzilgan" ko'rinadi). Telegram ``sendMediaGroup`` ga
``inline_keyboard`` ulashga ruxsat bermagani uchun yagona to'g'ri yo'l —
muqova fayl bilan karta; albomning qolgan fayllari draftda saqlanadi va
kanalga bitta ``sendMediaGroup`` bilan chiqadi. Shu sababli
:func:`build_album_preview` va :func:`send_album_preview` barcha albom
preview handlerlari uchun YAGONA shartnoma hisoblanadi.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Hashable

logger = logging.getLogger(__name__)

__all__ = [
    "MediaGroupCollector",
    "AlbumPayload",
    "AlbumPreview",
    "ALBUM_DEBOUNCE_SECONDS",
    "DEFAULT_DELAY_SECONDS",
    "DEFAULT_MAX_WAIT_SECONDS",
    "TELEGRAM_ALBUM_MAX_ITEMS",
    "ALBUM_CAPTION_LIMIT",
    "ALBUM_TEXT_LIMIT",
    "ALBUM_PREVIEW_MEDIA_KINDS",
    "ADDED_STARTED",
    "ADDED",
    "DUPLICATE",
    "FULL",
    "get_album_collector",
    "reset_album_collectors",
    "media_type_of",
    "media_file_id_of",
    "media_group_id_of",
    "is_media_group_message",
    "extract_media_item",
    "album_caption",
    "apply_album_caption",
    "build_album_preview",
    "send_album_preview",
]

#: Oxirgi fayldan keyingi jimlik oynasi (debounce) — QAT'IY 2.0 soniya.
#: Butun ilova (handlerlar, post tozalagich, oddiy post, enhancer) shu
#: qiymatdan foydalanadi; boshqa joyda 1.5/2.0 adabiyot qiymat yozilmaydi.
ALBUM_DEBOUNCE_SECONDS = 2.0
#: Orqaga moslik uchun taxallus.
DEFAULT_DELAY_SECONDS = ALBUM_DEBOUNCE_SECONDS
#: Birinchi fayldan boshlab umumiy kutish chegarasi (sekin tarmoq himoyasi).
DEFAULT_MAX_WAIT_SECONDS = 15.0
#: Telegram albom chegarasi.
TELEGRAM_ALBUM_MAX_ITEMS = 10

#: Albom elementi bo'la oladigan media turlari (Telegram media group).
ALBUM_MEDIA_KINDS = ("photo", "video", "document", "animation", "audio")

#: ``add`` natijalari.
ADDED_STARTED = "started"   # yangi bufer ochildi (shu albomning birinchi fayli)
ADDED = "added"             # mavjud buferga qo'shildi
DUPLICATE = "duplicate"     # shu ``message_id`` allaqachon bor
FULL = "full"               # bufer to'lgan (fayl qo'shilmadi)

ReadyCallback = Callable[[list], Awaitable[Any]]


# =========================================================================
# Media oxirigacha bog'liq yordamchilar (telegram-bog'liq EMAS, duck-typing)
# =========================================================================
def media_of(message) -> tuple:
    """``(kind, media)`` — xabardagi media va uning turi (bo'lmasa ``(None, None)``).

    ``photo`` — ro'yxat bo'lgani uchun eng katta (oxirgi) o'lcham olinadi.
    """
    for kind in ALBUM_MEDIA_KINDS:
        media = getattr(message, kind, None)
        if media:
            if kind == "photo":
                media = media[-1]
            return kind, media
    return None, None


def media_type_of(message) -> str | None:
    """Xabardagi media turi (``photo``/``video``/``document``...) yoki ``None``."""
    return media_of(message)[0]


def media_file_id_of(message) -> str | None:
    """Xabardagi media ``file_id`` (bo'lmasa ``None``)."""
    kind, media = media_of(message)
    if kind is None or media is None:
        return None
    return getattr(media, "file_id", None)


def media_group_id_of(message) -> str | None:
    """Xabarning ``media_group_id``'si (bo'sh/xato bo'lsa ``None``)."""
    value = getattr(message, "media_group_id", None)
    if value is None:
        return None
    text = str(value)
    return text or None


def is_media_group_message(message) -> bool:
    """Xabar Telegram albomining bir qismimi (media + ``media_group_id``)."""
    if message is None:
        return False
    return bool(media_group_id_of(message)) and media_type_of(message) is not None


def extract_media_item(message) -> dict | None:
    """Xabarni albom elementi (dict) ga aylantiradi; media bo'lmasa ``None``.

    Qaytarilgan dict::

        {"message_id": int|None, "type": "photo", "file_id": str,
         "caption": str, "caption_html": str|None, "entities": tuple}
    """
    kind, media = media_of(message)
    file_id = getattr(media, "file_id", None) if media is not None else None
    if not kind or not file_id:
        return None
    caption = getattr(message, "caption", None) or ""
    caption_html = getattr(message, "caption_html", None)
    return {
        "message_id": getattr(message, "message_id", None),
        "type": kind,
        "file_id": file_id,
        "caption": caption,
        "caption_html": caption_html,
        "entities": tuple(getattr(message, "caption_entities", None) or ()),
    }


def album_caption(items: list) -> str:
    """Albom uchun YAGONA izoh: birinchi bo'sh bo'lmagan caption (strip qilinadi)."""
    for item in items or ():
        if isinstance(item, dict):
            caption = (item.get("caption") or "").strip()
            if caption:
                return caption
    return ""


def album_caption_html(items: list) -> str | None:
    """Albom uchun YAGONA HTML izoh (bo'lmasa ``None``)."""
    for item in items or ():
        if not isinstance(item, dict):
            continue
        value = item.get("caption_html")
        if value and str(value).strip():
            return str(value)
    return None


def apply_album_caption(items: list) -> str:
    """Izohni faqat BIRINCHI elementda qoldiradi va u izohni qaytaradi.

    Telegram albomda matn faqat bitta ``InputMedia`` elementida ko'rinadi,
    shu sababli yig'ilgan ro'yxatni kanalga yuborishdan oldin izoh
    birlashtiriladi (qolgan elementlardan olib tashlanadi).
    """
    caption = album_caption(items)
    for index, item in enumerate(items or ()):
        if isinstance(item, dict):
            item["caption"] = caption if index == 0 else ""
    return caption


# =========================================================================
# 🖼 BIRLASHTIRILGAN (UNIFIED) ALBOM PREVIEW'I — YAGONA MANBA
# =========================================================================
# MUAMMO: albom yig'ilgach ba'zi oqimlar avval matn + boshqaruv tugmalarini,
# keyin esa media fayllarni ALOHIDA xabar qilib yuborardi. Natijada bitta
# preview holati IKKITA uzilgan xabarga bo'linib ketardi (panel yuqorida,
# media pastda) va foydalanuvchi "bu postga tegishlimi?" deb qolardi.
#
# TELEGRAM CHEKLOVI: ``sendMediaGroup`` ga ``inline_keyboard`` (reply_markup)
# ULAB BO'LMAYDI — Bot API'da bunday parametr yo'q. Shu sababli media,
# caption va tugmalarni bitta xabarga yig'ishning yagona yo'li: albomning
# MUQOVA (birinchi) fayli + butun albomga tegishli caption + boshqaruv
# tugmalari bo'lgan BITTA karta. Albomning qolgan fayllari yo'qolmaydi:
# ular draftda saqlanadi va kanalga bitta ``sendMediaGroup`` bilan chiqadi.
#
# Bu bo'lim shu bitta tuzilgan javobni (``AlbumPreview``) yasaydi va
# yuboradi — barcha albom preview handlerlari YAGONA shartnomadan foydalanadi
# (ikkita nusxa/naqsh yo'q). Modul telegram'siz qoladi: transport obyektlari
# duck-typing orqali chaqiriladi.

#: Media caption chegarasi (Telegram: 1024 UTF-16 birligi).
ALBUM_CAPTION_LIMIT = 1024
#: Matnli karta chegarasi (Telegram: 4096 UTF-16 birligi).
ALBUM_TEXT_LIMIT = 4096
#: Preview kartasi sifatida ko'rsatila oladigan muqova media turlari.
#: Har biri uchun transportda ``send_<tur>`` / ``reply_<tur>`` metodi va
#: ``<tur>=file_id`` parametri mavjud (photo/video/animation/document/audio).
ALBUM_PREVIEW_MEDIA_KINDS = ("photo", "video", "animation", "document", "audio")


def _utf16_length(text: str) -> int:
    """Telegram hisoblaydigan uzunlik (UTF-16 birligi; emoji = 2)."""
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text)


def _truncate_utf16(text: str, limit: int) -> str:
    """Matnni UTF-16 chegarasigacha qirqadi (butun belgilar saqlanadi)."""
    if limit <= 0 or _utf16_length(text) <= limit:
        return text
    keep = max(0, limit - 1)  # oxiridagi "…" uchun joy
    out: list = []
    total = 0
    for char in text:
        width = 2 if ord(char) > 0xFFFF else 1
        if total + width > keep:
            break
        out.append(char)
        total += width
    return "".join(out).rstrip() + "…"


def _limit_preview_text(text: str, limit: int, sanitizer=None) -> str:
    """Preview matnini chegaraga tushiradi (HTML-xavfsiz, agar sanitizer berilsa).

    ``sanitizer(text, limit)`` — loyihadagi HTML sanitizer (teg'larni
    balanslaydi va chegaraga qirqadi). U bo'lmasa/xato bersa oddiy UTF-16
    qirqish ishlatiladi: preview hech qachon Telegram chegarasidan oshmaydi.
    """
    raw = "" if text is None else str(text)
    if sanitizer is not None:
        try:
            cleaned = sanitizer(raw, limit)
        except Exception:  # noqa: BLE001 — sanitizer xatosi preview'ni buzmaydi
            logger.debug("albom preview sanitizer xatosi — oddiy qirqish", exc_info=True)
        else:
            if isinstance(cleaned, str) and cleaned:
                return _truncate_utf16(cleaned, limit) if limit > 0 else cleaned
    return _truncate_utf16(raw, limit)


def _preview_items(items) -> list:
    """Preview uchun yaroqli albom elementlari (tartib saqlanadi, ≤ 10)."""
    normalized = []
    for item in items or ():
        if not isinstance(item, dict):
            continue
        file_id = item.get("file_id")
        if not file_id:
            continue
        normalized.append(item)
        if len(normalized) >= TELEGRAM_ALBUM_MAX_ITEMS:
            break
    return normalized


def _preview_cover(items: list) -> tuple | None:
    """Muqova elementi: ``(kind, file_id)`` — kartaga qo'yib bo'ladigan birinchi fayl."""
    for item in items:
        kind = str(item.get("type") or "photo").lower()
        if kind in ALBUM_PREVIEW_MEDIA_KINDS:
            return kind, item.get("file_id")
    return None


@dataclass(frozen=True)
class AlbumPreview:
    """BIRLASHTIRILGAN albom preview javobi: media + caption + tugmalar.

    Bu BITTA tuzilgan javob (bitta xabar): muqova media, butun albomga
    tegishli caption va boshqaruv tugmalari birgalikda. Media va tugmalarni
    ikki alohida xabarga bo'lish preview'ni uzib qo'yadi, shu sababli
    albom preview'i har doim shu obyektdan render qilinadi.

    Maydonlar:
      * ``kind`` / ``file_id`` — muqova media (``None`` bo'lsa karta matnli);
      * ``caption`` — media kartasi uchun matn (≤ 1024 UTF-16);
      * ``text`` — matnli karta/zaxira uchun matn (≤ 4096 UTF-16);
      * ``reply_markup`` — boshqaruv tugmalari (shaffof obyekt);
      * ``items`` / ``count`` — BUTUN albom (kanalga ``sendMediaGroup`` bilan).
    """

    kind: str | None = None
    file_id: str | None = None
    caption: str = ""
    text: str = ""
    reply_markup: Any = None
    parse_mode: str | None = "HTML"
    items: tuple = ()
    count: int = 0

    @property
    def is_media(self) -> bool:
        """Muqova media bilan chiqadigan kartami (aks holda matnli karta)."""
        return bool(self.kind and self.file_id)

    @property
    def is_album(self) -> bool:
        """Bir nechta faylli albommi."""
        return self.count > 1

    def body(self) -> str:
        """Kartaga yoziladigan matn (media → caption, aks holda to'liq matn)."""
        return self.caption if self.is_media else self.text

    def sender(self, *, reply: bool = False) -> tuple | None:
        """``(metod, media kwargs)`` — transportda metod bo'lmasa ham qaytaradi.

        ``reply=True`` bo'lsa ``reply_<tur>`` (xabar adapteri), aks holda
        ``send_<tur>`` (bot + ``chat_id``) ishlatiladi.
        """
        if not self.is_media:
            return None
        prefix = "reply_" if reply else "send_"
        return f"{prefix}{self.kind}", {self.kind: self.file_id}

    def to_dict(self) -> dict:
        """Kuzatuv/test uchun sof dict ko'rinishi."""
        return {
            "kind": self.kind,
            "file_id": self.file_id,
            "caption": self.caption,
            "text": self.text,
            "reply_markup": self.reply_markup,
            "parse_mode": self.parse_mode,
            "count": self.count,
            "is_media": self.is_media,
            "is_album": self.is_album,
        }


def build_album_preview(items, *, text: str = "", reply_markup=None,
                        parse_mode: str | None = "HTML", sanitizer=None,
                        caption_limit: int = ALBUM_CAPTION_LIMIT,
                        text_limit: int = ALBUM_TEXT_LIMIT) -> AlbumPreview:
    """Yig'ilgan albomni BITTA tuzilgan preview javobiga aylantiradi.

    ``items`` — kollektor yig'gan fayllar; ``text`` — preview matni (tasdiq,
    xulosa, post kontenti); ``reply_markup`` — boshqaruv tugmalari. Natija:
    muqova media + caption + tugmalar BITTA xabarda (media fayllar va menyu
    ikki alohida xabarga AJRATILMAYDI).

    Muqova media topilmasa (bo'sh albom/qo'llab-quvvatlanmaydigan tur) karta
    matnli bo'ladi — tugmalar baribir biriktiriladi (boshqaruv yo'qolmaydi).
    """
    normalized = _preview_items(items)
    cover = _preview_cover(normalized)
    caption = _limit_preview_text(text, caption_limit, sanitizer) if cover else ""
    body = _limit_preview_text(text, text_limit, sanitizer)
    return AlbumPreview(
        kind=cover[0] if cover else None,
        file_id=cover[1] if cover else None,
        caption=caption,
        text=body,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        items=tuple(normalized),
        count=len(normalized),
    )


async def send_album_preview(transport, preview: AlbumPreview | None, *,
                             chat_id=None, reply: bool = False,
                             parse_mode: str | None = None):
    """Unified preview'ni BITTA xabar qilib yuboradi (media + caption + tugmalar).

    * ``reply=True`` — xabar adapteri (``reply_<tur>`` / ``reply_text``);
    * ``reply=False`` — bot + ``chat_id`` (``send_<tur>`` / ``send_message``).

    Muqova media yuborilmasa (adapter metodi yo'q yoki Telegram xatosi) O'SHA
    matn va tugmalar bilan matnli kartaga o'tiladi: preview hech qachon
    boshqaruvsiz qolmaydi va media ALOHIDA xabarga ajralib ketmaydi.
    Qaytaradi: yuborilgan xabar (yoki ``None``).
    """
    if preview is None or transport is None:
        return None
    mode = preview.parse_mode if parse_mode is None else parse_mode
    sender = preview.sender(reply=reply)
    if sender is not None:
        method, media_kwargs = sender
        media_send = getattr(transport, method, None)
        if callable(media_send):
            kwargs = dict(media_kwargs)
            kwargs["caption"] = preview.caption
            kwargs["reply_markup"] = preview.reply_markup
            kwargs["parse_mode"] = mode
            if not reply and chat_id is not None:
                kwargs["chat_id"] = chat_id
            try:
                return await media_send(**kwargs)
            except Exception:  # noqa: BLE001 — media kartasi xatosi preview'ni to'xtatmaydi
                logger.warning(
                    "Unified albom preview: muqova media yuborilmadi — matnli karta",
                    exc_info=True,
                )
    text_method = "reply_text" if reply else "send_message"
    text_send = getattr(transport, text_method, None)
    if not callable(text_send):
        logger.warning("Unified albom preview: transportda %s yo'q", text_method)
        return None
    kwargs = {
        "text": preview.text or preview.caption or " ",
        "reply_markup": preview.reply_markup,
        "parse_mode": mode,
    }
    if not reply and chat_id is not None:
        kwargs["chat_id"] = chat_id
    try:
        return await text_send(**kwargs)
    except Exception:  # noqa: BLE001 — HTML xatosida oddiy matn bilan qayta urinish
        try:
            kwargs["parse_mode"] = None
            return await text_send(**kwargs)
        except Exception:  # noqa: BLE001 — preview yuborilmasa ham oqim buzilmaydi
            logger.exception("Unified albom preview: matnli karta ham yuborilmadi")
            return None


@dataclass
class AlbumPayload:
    """Yig'ilgan, TO'LIQ albom — bitta konsolidatsiyalangan post manbasi.

    Voqea oqimi: birinchi fayl kelganda bufer ochiladi → qolgan fayllar
    shu buferga qo'shiladi → jimlik oynasi (2.0s) tugagach **bitta**
    ``AlbumPayload`` yasaladi va u orqali FAQAT BITTA preview render qilinadi.
    """

    media_group_id: str
    items: list = field(default_factory=list)
    chat_id: int | None = None
    user_id: int | None = None
    caption: str = ""
    caption_html: str | None = None
    message: Any = None          # muqova (cover) xabar — preview uchun
    update: Any = None           # muqova update — dispatch uchun
    key: Hashable | None = None
    created_at: float = field(default_factory=time.monotonic)
    released_at: float | None = None
    consumed: bool = False

    @property
    def count(self) -> int:
        """Albomdagi fayllar soni."""
        return len(self.items or [])

    @property
    def is_album(self) -> bool:
        """Bir nechta fayl (Telegram albomi) — bitta post sifatida chiqadi."""
        return self.count > 1

    def cover(self) -> dict | None:
        """Muqova elementi (birinchi fayl)."""
        return self.items[0] if self.items else None

    def media_items(self) -> list:
        """``sendMediaGroup`` uchun tayyor media elementlari (nusxa)."""
        return [dict(item) for item in (self.items or [])]

    def preview(self, *, text: str | None = None, reply_markup=None,
                parse_mode: str | None = "HTML", sanitizer=None) -> AlbumPreview:
        """Payload'dan BIRLASHTIRILGAN preview javobi (media + caption + tugmalar).

        ``text`` berilmasa albomning o'z izohi (``caption``) ishlatiladi.
        Handler natijani :func:`send_album_preview` ga beradi — preview BITTA
        xabar bo'lib chiqadi (media va tugmalar alohida xabarlarga bo'linmaydi).
        """
        return build_album_preview(
            self.items,
            text=self.caption if text is None else text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            sanitizer=sanitizer,
        )

    def mark_consumed(self) -> bool:
        """Payload'ni "iste'mol qilindi" deb belgilaydi (idempotent).

        Qaytaradi: ``True`` — birinchi marta (handler ishlashi mumkin);
        ``False`` — allaqachon iste'mol qilingan (takroriy preview TAQIQLANADI).
        """
        if self.consumed:
            return False
        self.consumed = True
        return True

    def to_items(self) -> list:
        """Handlerlar kutadigan sof ro'yxat ko'rinishi."""
        return self.media_items()


class _Buffer:
    __slots__ = (
        "items", "ids", "first_at", "last_at", "on_ready", "task",
        "changed", "lock",
    )

    def __init__(self, now: float, on_ready: ReadyCallback, lock: asyncio.Lock):
        self.items: list = []
        self.ids: set = set()
        self.first_at = now
        self.last_at = now
        self.on_ready = on_ready
        self.task: asyncio.Task | None = None
        # ``add`` bu event orqali mavjud bitta worker'ning debounce kutishini
        # qayta boshlaydi; har update uchun yangi finalizer task yaratilmaydi.
        self.changed = asyncio.Event()
        # Timeout/flush/cancel chegarasidagi finalizatsiyani idempotent qiladi.
        self.lock = lock


class MediaGroupCollector:
    """Albom fayllarini yig'adi va jimlikdan keyin bir marta qaytaradi."""

    def __init__(self, *, delay: float = DEFAULT_DELAY_SECONDS,
                 max_wait: float = DEFAULT_MAX_WAIT_SECONDS,
                 max_items: int = TELEGRAM_ALBUM_MAX_ITEMS):
        self.delay = max(0.0, float(delay))
        self.max_wait = max(self.delay, float(max_wait))
        self.max_items = max(1, int(max_items))
        self._buffers: dict[Hashable, _Buffer] = {}
        # Talab bo'yicha har bir media_group kalitiga alohida lock. Lock callback
        # tugaguncha ushlab turiladi, shuning uchun rendering ikki marta ketmaydi.
        self._locks: dict[Hashable, asyncio.Lock] = {}
        # Fon vazifalarga kuchli havola — GC ularni yig'ib yubormasligi uchun.
        self._tasks: set[asyncio.Task] = set()
        # Kuzatuv (health/test): nechta albom yig'ilib yakunlandi.
        self._delivered = 0

    # -- holat --------------------------------------------------------------
    def pending(self, key: Hashable | None = None) -> int:
        """Yig'ilayotgan fayllar soni (``key`` bo'lmasa — barcha albomlar)."""
        if key is not None:
            buf = self._buffers.get(key)
            return len(buf.items) if buf else 0
        return sum(len(b.items) for b in self._buffers.values())

    def is_collecting(self, key: Hashable) -> bool:
        return key in self._buffers

    def task_for(self, key: Hashable) -> asyncio.Task | None:
        """Kalitning yagona worker vazifasi (integratsiya/test cleanup'i uchun)."""
        buf = self._buffers.get(key)
        return buf.task if buf is not None else None

    def keys(self) -> list:
        """Hozir yig'ilayotgan barcha kalitlar."""
        return list(self._buffers.keys())

    def stats(self) -> dict:
        """Kollektor hisoboti (kuzatuv/health uchun)."""
        return {
            "collecting_keys": len(self._buffers),
            "pending_items": self.pending(),
            "delivered_groups": self._delivered,
            "delay": self.delay,
            "max_wait": self.max_wait,
            "max_items": self.max_items,
        }

    # -- qo'shish -----------------------------------------------------------
    def add(self, key: Hashable, item: dict, on_ready: ReadyCallback) -> str:
        """Faylni buferga qo'shadi (event loop ichidan chaqiriladi).

        ``item`` — dict; ``message_id`` bo'lsa dublikat aniqlanadi va yakuniy
        ro'yxat shu bo'yicha tartiblangan holda beriladi (Telegram tartibi).

        Metodda ``await`` yo'q: bitta asyncio event loop ichida append +
        ``last_at`` yangilanishi atomik bajariladi. Finalizer esa shu kalitning
        lock'i ichida vaqtni qayta tekshiradi.
        """
        return self.add_many(key, [item], on_ready)

    def add_many(self, key: Hashable, items: list, on_ready: ReadyCallback) -> str:
        """Bir nechta faylni BIR marta (atomik) buferga qo'shadi.

        Konsolidatsiyalangan albom (masalan, darvoza tomonidan yig'ilgan
        media group) shu metod orqali butunlay qo'shiladi — handler bir
        marta chaqirilib, bitta preview render qiladi.

        Qaytaradi: ``ADDED_STARTED`` (bufer ochildi), ``ADDED`` (mavjud
        buferga qo'shildi), ``DUPLICATE`` yoki ``FULL``.
        """
        loop = asyncio.get_running_loop()
        now = loop.time()
        buf = self._buffers.get(key)
        started = buf is None
        if started:
            lock = self._locks.setdefault(key, asyncio.Lock())
            buf = _Buffer(now, on_ready, lock)
            self._buffers[key] = buf
        added = 0
        duplicates = 0
        full = False
        for item in items:
            outcome = self._append(buf, item)
            if outcome == DUPLICATE:
                duplicates += 1
            elif outcome == FULL:
                full = True
            else:
                added += 1
        if not added:
            if started:
                # Bo'sh/yaroqsiz ro'yxat — bo'sh bufer ochib qo'ymaymiz.
                self._buffers.pop(key, None)
                lock = self._locks.get(key)
                if lock is not None and not lock.locked():
                    self._locks.pop(key, None)
            if full:
                return FULL
            return DUPLICATE if duplicates else FULL
        buf.last_at = now
        if buf.first_at > now:  # pragma: no cover - himoya
            buf.first_at = now
        if started:
            # Bitta media_group uchun FAQAT bitta worker.
            buf.task = loop.create_task(self._run(key, buf))
            self._tasks.add(buf.task)
            buf.task.add_done_callback(self._tasks.discard)
            return ADDED_STARTED
        # Mavjud worker'ni uyg'otamiz; yangi preview/finalizer task ochilmaydi.
        buf.changed.set()
        return ADDED

    def _append(self, buf: _Buffer, item: dict) -> str:
        """Bitta elementni buferga qo'shadi (dublikat/limit tekshiruvi bilan)."""
        message_id = item.get("message_id") if isinstance(item, dict) else None
        if message_id is not None and message_id in buf.ids:
            return DUPLICATE
        if len(buf.items) >= self.max_items:
            return FULL
        buf.items.append(item)
        if message_id is not None:
            buf.ids.add(message_id)
        return ADDED

    # -- bekor qilish -------------------------------------------------------
    def cancel(self, key: Hashable) -> bool:
        """Yig'ishni bekor qiladi (``on_ready`` chaqirilmaydi)."""
        buf = self._buffers.pop(key, None)
        if buf is None:
            return False
        if buf.task is not None and not buf.task.done():
            buf.task.cancel()
        self._cleanup_lock(key, buf)
        return True

    async def flush(self, key: Hashable) -> bool:
        """Kutmasdan darhol yakunlaydi (test/o'chirish uchun).

        Worker timeouti bilan bir vaqtda chaqirilsa, per-key lock va bufer
        identity tekshiruvi callback'ni aynan bir marta bajaradi.
        """
        buf = self._buffers.get(key)
        if buf is None:
            return False
        current = asyncio.current_task()
        if buf.task is not None and buf.task is not current and not buf.task.done():
            buf.task.cancel()
        delivered = False
        try:
            async with buf.lock:
                if self._buffers.get(key) is not buf:
                    return False
                self._buffers.pop(key, None)
                await self._deliver(buf)
                delivered = True
        finally:
            self._cleanup_lock(key, buf)
        return delivered

    async def flush_all(self) -> int:
        """Barcha yig'ilayotgan albomlarni darhol yakunlaydi (test/o'chirish)."""
        delivered = 0
        for key in list(self._buffers):
            if await self.flush(key):
                delivered += 1
        return delivered

    async def wait_idle(self) -> None:
        """Barcha fon vazifalar tugashini kutadi (testlar uchun)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # -- ichki --------------------------------------------------------------
    async def _run(self, key: Hashable, buf: _Buffer) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                now = loop.time()
                wait = min(
                    buf.last_at + self.delay - now,
                    buf.first_at + self.max_wait - now,
                )
                if wait > 0:
                    try:
                        # Yangi item kelsa darhol uyg'onib, OXIRGI itemdan
                        # yangi to'liq debounce oynasini hisoblaydi.
                        await asyncio.wait_for(buf.changed.wait(), timeout=wait)
                    except asyncio.TimeoutError:
                        pass
                    else:
                        buf.changed.clear()
                        continue

                # Timeout chegarasida update kelishi mumkin. Lock ichida
                # last_at'ni qayta tekshirmasdan pop qilish partial albumga
                # olib kelardi.
                async with buf.lock:
                    if self._buffers.get(key) is not buf:
                        return  # cancel()/flush() allaqachon olib tashlagan
                    now = loop.time()
                    quiet_until = buf.last_at + self.delay
                    hard_deadline = buf.first_at + self.max_wait
                    if now < quiet_until and now < hard_deadline:
                        continue
                    self._buffers.pop(key, None)
                    # Rendering/callback ham shu lock ichida: ayni guruhning
                    # ikkinchi finalizer'i parallel ishlay olmaydi.
                    await self._deliver(buf)
                    return
        except asyncio.CancelledError:
            return
        finally:
            self._cleanup_lock(key, buf)

    def _cleanup_lock(self, key: Hashable, buf: _Buffer) -> None:
        """Kalit qayta ishlatilmayotgan bo'lsa uning lock'ini chiqaradi."""
        # Callback davomida ayni Telegram group ID uchun juda kech update
        # kelsa, yangi buffer aynan shu lock'dan foydalanadi. Bunday holatda
        # eski worker lock mapping'ini o'chirmasligi kerak.
        if self._buffers.get(key) is None \
                and self._locks.get(key) is buf.lock \
                and not buf.lock.locked():
            self._locks.pop(key, None)

    async def _deliver(self, buf: _Buffer) -> None:
        items = sorted(
            list(buf.items),
            key=lambda it: (it.get("message_id") is None, it.get("message_id") or 0)
            if isinstance(it, dict) else (True, 0),
        )
        self._delivered += 1
        try:
            await buf.on_ready(items)
        except Exception:  # noqa: BLE001 — bitta albom xatosi boshqalarni buzmasin
            logger.exception("MediaGroupCollector: on_ready xatosi (%d ta fayl)", len(items))


# =========================================================================
# NOMLANGAN SINGLETON'LAR
# =========================================================================
#: Jarayon bo'yicha yagona kollektorlar: turli modullar (darvoza, post
#: tozalagich, enhancer) bir xil navigatsiya/cleanup semantikasini saqlashi
#: va testlarda bitta nuqtadan reset qilinishi uchun.
_COLLECTORS: dict[str, MediaGroupCollector] = {}


def get_album_collector(name: str = "global") -> MediaGroupCollector:
    """Nomlangan umumiy kollektor (yaratilmasa — standart 2.0s bilan yasaladi)."""
    collector = _COLLECTORS.get(name)
    if collector is None:
        collector = MediaGroupCollector()
        _COLLECTORS[name] = collector
    return collector


def reset_album_collectors() -> None:
    """Barcha nomlangan kollektorlarni tozalaydi (test/restart uchun)."""
    _COLLECTORS.clear()
