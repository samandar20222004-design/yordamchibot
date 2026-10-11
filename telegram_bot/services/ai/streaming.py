"""🌊 AI TOKEN STREAMING + 💎 BOY XABAR QORALAMALARI (rich message drafts).

Bu modul ikkita yangi imkoniyatni :mod:`services.ai` fasadiga qo'shadi:

1. **TOKEN STREAMING** — LLM tokenlarini kelib tushishi bilan bitta Telegram
   xabariga tahrirlab borish (:class:`AIStreamRenderer`).
2. **RICH MESSAGE DRAFTS** — HTML formatlash (qalin/kursiv/kod/spoyler),
   ro'yxatlar, ajratgichlar, sarlavha va inline tugmalardan iborat xabar
   qoralamasi (:class:`RichMessageDraft`).

Telegram flood-control qat'iy saqlanadi
---------------------------------------
Mavjud :class:`services.ai.progress.AIProgressReporter` o'rami buzilmaydi,
chunki bu modul **aynan o'sha qo'riqchilarni qayta ishlatadi**:

* ``MIN_EDIT_INTERVAL_FLOOR`` (≥ 1.05 s) — pasaytirib bo'lmaydi;
* ``CHAT_EDIT_CLOCK`` — jarayon bo'yicha umumiy per-chat soat. Bir chatda
  parallel ishlayotgan progress-reporter va stream-renderer **bitta** soatni
  bo'lishadi, shuning uchun ikkalasi birgalikda tahrir chastotasini
  ikkilantira olmaydi;
* ``429 / RetryAfter`` — oynaning oxirigacha tahrirlar o'tkazib yuboriladi
  (hech qachon tsiklda qayta urilmaydi);
* ``message is not modified`` — muvaffaqiyatli no-op.

Shuningdek:

* tahrirlar faqat **yetarli yangi matn** yig'lganda yuboriladi
  (``min_delta_chars``) — tokeniga bitta API chaqiruvi YO'Q;
* matn Telegram chegarasigacha (4096 belgi) qisqartiriladi va ochiq HTML
  teglar yopiladi;
* stream xatosi generatsiyani **hech qachon** yiqitmaydi (fail-soft).

Bu modul stdlib + :mod:`services.ai.progress` ga tayanadi; ``telegram``
paketi faqat :meth:`RichMessageDraft.telegram_kwargs` ichida lazy import
qilinadi (shu sababli modulni testlar xavfsiz import qila oladi).
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from services.ai.progress import (
    CHAT_EDIT_CLOCK,
    MIN_EDIT_INTERVAL_FLOOR,
    ChatEditClock,
    _is_not_modified,
    _retry_after_seconds,
    normalize_progress_language,
)

logger = logging.getLogger(__name__)

#: Telegram xabar uzunligi chegarasi.
TELEGRAM_MESSAGE_LIMIT = 4096

#: Tahrirga arziydigan minimal yangi belgilar soni (tokeniga 1 API call yo'q).
DEFAULT_MIN_DELTA_CHARS = 24

#: Oqim davomida ko'rsatiladigan kursor belgisi.
DEFAULT_STREAM_CURSOR = "▌"

#: Yakuniy tahrir uchun kutish chegarasi (flood-control oynasi katta bo'lsa).
DEFAULT_MAX_FINAL_WAIT = 5.0

#: Rich-matn uslublari → Telegram HTML teglari.
RICH_STYLES: dict[str, tuple[str, str] | None] = {
    "plain": None,
    "bold": ("<b>", "</b>"),
    "italic": ("<i>", "</i>"),
    "code": ("<code>", "</code>"),
    "pre": ("<pre>", "</pre>"),
    "underline": ("<u>", "</u>"),
    "strike": ("<s>", "</s>"),
    "spoiler": ("<span class=\"tg-spoiler\">", "</span>"),
}

_HTML_TAG_RX = re.compile(r"<(/?)(b|i|u|s|code|pre|span)\b[^>]*>", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Matn yordamchilari
# ---------------------------------------------------------------------------
def close_open_tags(text: Any) -> str:
    """Kesilgan matndagi ochiq HTML teglarni yopadi (parse xatosining oldini oladi)."""
    body = text if isinstance(text, str) else str(text or "")
    stack: list[str] = []
    for match in _HTML_TAG_RX.finditer(body):
        closing, tag = match.group(1), match.group(2).lower()
        if closing:
            if stack and stack[-1] == tag:
                stack.pop()
            elif tag in stack:
                while stack and stack.pop() != tag:
                    pass
        else:
            stack.append(tag)
    return body + "".join(f"</{tag}>" for tag in reversed(stack))


def truncate_message(text: Any, limit: int = TELEGRAM_MESSAGE_LIMIT) -> str:
    """Matnni Telegram chegarasiga moslaydi (ochiq teglarni yopib)."""
    body = text if isinstance(text, str) else str(text or "")
    limit = max(64, int(limit))
    if len(body) <= limit:
        return body
    ellipsis = "…"
    return close_open_tags(body[: limit - len(ellipsis)]) + ellipsis


# ---------------------------------------------------------------------------
# 💎 BOY XABAR QORALAMASI
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RichButton:
    """Inline tugma qoralamasi (``callback_data`` yoki ``url`` — bittasi)."""

    label: str
    callback_data: str = ""
    url: str = ""


@dataclass(frozen=True)
class RichMessageDraftRender:
    """:meth:`RichMessageDraft.render` natijasi — sof ma'lumot, Telegram'siz."""

    text: str
    parse_mode: str = "HTML"
    buttons: tuple[tuple[RichButton, ...], ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


class RichMessageDraft:
    """Telegram xabari qoralamasi: HTML matn + tugmalar (builder).

    Misol::

        draft = (RichMessageDraft(lang="uz")
                 .add_title("📊 Haftalik hisobot")
                 .add_bullets(["Ko'rishlar: 1 240", "Obunachi: +38"])
                 .add_divider()
                 .add_button("📅 Rejalashtirish", callback_data="cal_days:7"))
        payload = draft.telegram_kwargs()
        await bot.send_message(chat_id, **payload)

    Barcha foydalanuvchi matnlari **HTML-escape** qilinadi — qoralama orqali
    teglarni buzib o'tish (injection) mumkin emas.
    """

    def __init__(self, *, lang: str = "uz", parse_mode: str = "HTML",
                 max_chars: int = TELEGRAM_MESSAGE_LIMIT) -> None:
        self.lang = normalize_progress_language(lang)
        self.parse_mode = str(parse_mode or "HTML")
        self.max_chars = max(64, int(max_chars))
        self._blocks: list[str] = []
        self._buttons: list[list[RichButton]] = []

    # -- matn ------------------------------------------------------------
    @staticmethod
    def escape(value: Any) -> str:
        """HTML-escape (hech qachon istisno bermaydi)."""
        try:
            return html.escape(str(value if value is not None else ""), quote=False)
        except Exception:  # pragma: no cover - himoya
            return ""

    def add_text(self, text: Any, style: str = "plain") -> "RichMessageDraft":
        """Bitta paragraf qo'shadi (matn escape qilinadi, uslub qo'llanadi)."""
        body = self.escape(text).strip()
        if not body:
            return self
        tags = RICH_STYLES.get(str(style or "plain").lower())
        self._blocks.append(f"{tags[0]}{body}{tags[1]}" if tags else body)
        return self

    def add_title(self, title: Any) -> "RichMessageDraft":
        return self.add_text(title, "bold")

    def add_bullets(self, items: Iterable[Any], *, bullet: str = "•") -> "RichMessageDraft":
        """Ro'yxat qo'shadi (bo'sh elementlar o'tkazib yuboriladi)."""
        lines = [f"{bullet} {self.escape(item)}" for item in (items or [])
                 if str(item or "").strip()]
        if lines:
            self._blocks.append("\n".join(lines))
        return self

    def add_divider(self, char: str = "—", width: int = 12) -> "RichMessageDraft":
        self._blocks.append(self.escape(char * max(1, min(width, 40))))
        return self

    def add_footer(self, text: Any) -> "RichMessageDraft":
        """Kichik izoh qatori (kursivda)."""
        return self.add_text(text, "italic")

    # -- tugmalar --------------------------------------------------------
    def add_button(self, label: Any, *, callback_data: str = "",
                   url: str = "", new_row: bool = False) -> "RichMessageDraft":
        """Inline tugma qo'shadi (yangi qatorga o'tish ixtiyoriy)."""
        text = self.escape(label).strip()
        if not text or not (callback_data or url):
            return self
        if new_row or not self._buttons:
            self._buttons.append([])
        self._buttons[-1].append(RichButton(text, str(callback_data or "")[:64], url))
        return self

    def add_button_row(self, buttons: Iterable[RichButton]) -> "RichMessageDraft":
        row = [button for button in (buttons or []) if button.label]
        if row:
            self._buttons.append(list(row))
        return self

    # -- render ----------------------------------------------------------
    @property
    def text(self) -> str:
        """Yakuniy HTML matn (Telegram chegarasigacha xavfsiz qisqartiriladi)."""
        joined = "\n\n".join(block for block in self._blocks if block.strip())
        return truncate_message(joined, self.max_chars)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip() and not self._buttons

    def render(self) -> RichMessageDraftRender:
        """Sof ma'lumot ko'rinishi (Telegram obyektisiz — testlar uchun qulay)."""
        return RichMessageDraftRender(
            text=self.text,
            parse_mode=self.parse_mode,
            buttons=tuple(tuple(row) for row in self._buttons),
        )

    def telegram_kwargs(self, **extra: Any) -> dict[str, Any]:
        """``bot.send_message(...)`` / ``edit_message_text(...)`` uchun kwargs.

        ``telegram`` paketi shu yerda lazy import qilinadi; o'rnatilmagan
        bo'lsa ``reply_markup`` tushirib qoldiriladi (matn baribir ishlaydi).
        """
        payload: dict[str, Any] = {"text": self.text}
        if self.parse_mode and self.parse_mode.upper() != "NONE":
            payload["parse_mode"] = self.parse_mode
        rows = [row for row in self._buttons if row]
        if rows:
            try:  # pragma: no cover - telegram mavjud bo'lganda bajariladi
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                payload["reply_markup"] = InlineKeyboardMarkup([
                    [InlineKeyboardButton(button.label,
                                          callback_data=button.callback_data or None,
                                          url=button.url or None)
                     for button in row]
                    for row in rows
                ])
            except Exception:  # noqa: BLE001 — matn buttonsiz ham yuborilishi kerak
                logger.debug("InlineKeyboardMarkup unavailable; sending text only", exc_info=True)
        payload.update(extra)
        return payload


# ---------------------------------------------------------------------------
# 🌊 TOKEN STREAMING
# ---------------------------------------------------------------------------
class TokenStreamBuffer:
    """Token oqimini to'playdi va **tahrirga arziydigan** lahzani aniqlaydi.

    Bu klass sof mantiq (I/O yo'q) — shu sababli tahrir chastotasi qoidalari
    alohida, deterministik sinovdan o'tkaziladi.
    """

    def __init__(self, *,
                 min_edit_interval: float = 1.1,
                 min_delta_chars: int = DEFAULT_MIN_DELTA_CHARS,
                 max_chars: int = TELEGRAM_MESSAGE_LIMIT,
                 chat_id: Any = None,
                 clock: ChatEditClock | None = None,
                 time_fn: Callable[[], float] = time.monotonic) -> None:
        # Telegram chegarasini buzib bo'lmaydi: qiymat pasaytirilsa ham floor qoladi.
        self.minimum_edit_interval = max(MIN_EDIT_INTERVAL_FLOOR, float(min_edit_interval))
        self.min_delta_chars = max(1, int(min_delta_chars))
        self.max_chars = max(64, int(max_chars))
        self.chat_id = chat_id
        self.time_fn = time_fn
        self._clock = clock if clock is not None else CHAT_EDIT_CLOCK
        self._parts: list[str] = []
        self._chars = 0
        self._emitted_chars = 0
        self._last_edit_at: float | None = None
        self._blocked_until = 0.0
        self.tokens = 0
        self.edits = 0

    # -- kirish ----------------------------------------------------------
    def feed(self, chunk: Any) -> None:
        """Bitta token/bo'lak qo'shadi (bo'sh qiymatlar e'tiborsiz)."""
        if chunk is None:
            return
        text = chunk if isinstance(chunk, str) else str(chunk)
        if not text:
            return
        self._parts.append(text)
        self._chars += len(text)
        self.tokens += 1

    def feed_all(self, chunks: Iterable[Any]) -> None:
        for chunk in chunks:
            self.feed(chunk)

    # -- holat -----------------------------------------------------------
    @property
    def text(self) -> str:
        return "".join(self._parts)

    @property
    def char_count(self) -> int:
        return self._chars

    @property
    def pending_chars(self) -> int:
        """Oxirgi tahrirdan beri yig'ilgan yangi belgilar soni."""
        return max(0, self._chars - self._emitted_chars)

    @property
    def truncated(self) -> bool:
        return self._chars > self.max_chars

    @property
    def last_edit_at(self) -> float | None:
        """Oxirgi muvaffaqiyatli tahrir vaqti (monotonic) yoki ``None``."""
        return self._last_edit_at

    def next_edit_slot(self) -> float:
        """Shu chat/xabar uchun eng erta ruxsat etilgan tahrir vaqti (monotonic)."""
        slot = self._blocked_until
        if self._last_edit_at is not None:
            slot = max(slot, self._last_edit_at + self.minimum_edit_interval)
        return max(slot, self._clock.next_allowed(self.chat_id))

    def is_due(self, *, now: float | None = None, force: bool = False) -> bool:
        """Tahrir yuborish vaqti keldimi? (chastota + yetarli yangi matn)"""
        moment = self.time_fn() if now is None else float(now)
        if not force and self.pending_chars < self.min_delta_chars:
            return False
        return moment >= self.next_edit_slot()

    def mark_edit(self, *, now: float | None = None) -> None:
        """Tahrir yuborilganini qayd etadi (per-chat soatni ham suradi)."""
        moment = self.time_fn() if now is None else float(now)
        self._last_edit_at = moment
        self._emitted_chars = self._chars
        self.edits += 1
        self._clock.push(self.chat_id, moment + self.minimum_edit_interval)

    def block_for(self, seconds: float, *, now: float | None = None) -> None:
        """429/RetryAfter oynasini qayd etadi (per-chat soat ham yangilanadi)."""
        moment = self.time_fn() if now is None else float(now)
        until = moment + max(float(seconds), self.minimum_edit_interval)
        self._blocked_until = max(self._blocked_until, until)
        self._clock.push(self.chat_id, until)


@dataclass
class StreamResult:
    """Token oqimi natijasi (telemetriya va assertlar uchun)."""

    text: str = ""
    completed: bool = False
    tokens: int = 0
    edits: int = 0
    skipped_edits: int = 0
    throttled: int = 0
    truncated: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.completed and not self.error


@dataclass
class AIStreamRenderer:
    """Token oqimini bitta Telegram xabariga tahrirlab boradi.

    ``editor`` — xabarni tahrirlovchi coroutine (``Message.edit_text`` yoki
    ``CallbackQuery.edit_message_text``). ``reporter`` berilsa, uning
    per-chat soati, chat'i va tahrir oralig'i **bo'lishiladi** — shunda
    progress o'rami va stream bir chatda tahrir chastotasini oshira olmaydi.
    """

    editor: Callable[..., Awaitable[Any]] | None = None
    message: Any = None
    lang: str = "uz"
    chat_id: Any = None
    reporter: Any = None
    min_edit_interval: float = 1.1
    min_delta_chars: int = DEFAULT_MIN_DELTA_CHARS
    max_chars: int = TELEGRAM_MESSAGE_LIMIT
    cursor: str = DEFAULT_STREAM_CURSOR
    max_final_wait: float = DEFAULT_MAX_FINAL_WAIT
    clock: ChatEditClock | None = None
    final_text: str = ""
    buffer: TokenStreamBuffer | None = field(default=None, repr=False)
    result: StreamResult = field(default_factory=StreamResult, repr=False)

    def __post_init__(self) -> None:
        # Progress-reporter bo'lsa uning chat'ini va soatini meros olamiz.
        if self.chat_id is None and self.reporter is not None:
            self.chat_id = getattr(self.reporter, "chat_id", None)
        if self.editor is None and self.message is not None:
            self.attach_message(self.message)
        clock = self.clock
        if clock is None and self.reporter is not None:
            clock = getattr(self.reporter, "_clock", None)
        self._clock = clock if clock is not None else CHAT_EDIT_CLOCK
        # Reporter chastotasi qat'iyroq bo'lsa — shu qat'iylik meros qilinadi.
        floor = max(MIN_EDIT_INTERVAL_FLOOR, float(self.min_edit_interval))
        if self.reporter is not None:
            floor = max(floor, float(getattr(self.reporter, "minimum_edit_interval", 0.0) or 0.0))
        self.minimum_edit_interval = floor
        self.buffer = TokenStreamBuffer(
            min_edit_interval=floor,
            min_delta_chars=self.min_delta_chars,
            max_chars=self.max_chars,
            chat_id=self.chat_id,
            clock=self._clock,
        )
        self._last_text: str | None = None

    # -- tahrir ----------------------------------------------------------
    def attach_message(self, message: Any) -> None:
        """Allaqachon yuborilgan xabarni stream nishoniga aylantiradi."""
        self.message = message
        candidate = getattr(message, "edit_text", None)
        if callable(candidate):
            self.editor = candidate
        if self.chat_id is None:
            self.chat_id = getattr(message, "chat_id", None)

    def display_text(self, body: str, *, final: bool) -> str:
        """Ko'rsatiladigan matn (oqim davomida oxirida kursor bo'ladi)."""
        text = truncate_message(body, self.max_chars)
        if final or not self.cursor:
            return text
        return truncate_message(text, self.max_chars - len(self.cursor)) + self.cursor

    async def push(self, *, final: bool, force: bool = False) -> bool:
        """Bitta tahrirni yuboradi; chastota/qo'riqchilarga bo'ysunadi."""
        buffer = self.buffer
        if buffer is None or not callable(self.editor):  # pragma: no cover - himoya
            return False
        if not final and not buffer.is_due(force=force):
            return False
        text = self.display_text(buffer.text, final=final)
        if not text.strip():
            # Bo'sh tahrir xabarni o'chirib yuborardi (masalan oqim hech
            # narsa bermasa) — shuning uchun butunlay o'tkazib yuboriladi.
            return False
        if text == self._last_text:
            return False
        remaining = buffer.next_edit_slot() - time.monotonic()
        if not final:
            # Flood-control oynasi bir tahrir oralig'idan katta bo'lsa tahrir
            # O'TKAZIB yuboriladi (keyingi tahrir yoki yakun uni almashtiradi).
            if remaining > max(self.minimum_edit_interval, 0.0):
                self.result.skipped_edits += 1
                return False
            if remaining > 0:
                await asyncio.sleep(remaining)
        elif remaining > 0:
            await asyncio.sleep(min(remaining, max(0.0, float(self.max_final_wait))))
        try:
            await self.editor(text)
        except Exception as exc:  # noqa: BLE001 — stream generatsiyani buzmaydi
            retry_after = _retry_after_seconds(exc)
            if retry_after is not None:
                buffer.block_for(retry_after)
                self.result.throttled += 1
                self.result.skipped_edits += 1
                logger.info("AI stream edit throttled by Telegram (retry_after=%.1fs)",
                            retry_after)
                return False
            if _is_not_modified(exc):
                buffer.mark_edit()
                self._last_text = text
                self.result.edits += 1
                return True
            logger.debug("AI stream edit failed", exc_info=True)
            self.result.error = self.result.error or type(exc).__name__
            return False
        buffer.mark_edit()
        self._last_text = text
        self.result.edits += 1
        return True

    # -- oqim ------------------------------------------------------------
    async def render(self, tokens: AsyncIterable[Any] | Iterable[Any]) -> StreamResult:
        """Token oqimini iste'mol qilib, xabarni bosqichma-bosqich yangilaydi."""
        buffer, result = self.buffer, self.result
        if buffer is None:  # pragma: no cover - himoya
            return result
        # ``tokens`` async-generator FUNKSIYASI bo'lsa — chaqirib olamiz
        # (``stream(gen_fn)`` va ``stream(gen_fn())`` ikkalasi ham ishlaydi).
        if callable(tokens) and not hasattr(tokens, "__aiter__") \
                and not hasattr(tokens, "__iter__"):
            try:
                tokens = tokens()
            except Exception:  # noqa: BLE001 - fabrika xatosi ham fail-soft
                logger.debug("AI token factory failed", exc_info=True)
                result.error = result.error or "TokenFactoryError"
                await self.finish()
                return result
        try:
            if hasattr(tokens, "__aiter__"):
                async for chunk in tokens:  # type: ignore[union-attr]
                    buffer.feed(chunk)
                    result.tokens = buffer.tokens
                    await self.push(final=False)
            else:
                for chunk in tokens:  # type: ignore[assignment]
                    buffer.feed(chunk)
                    result.tokens = buffer.tokens
                    await self.push(final=False)
            result.completed = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — stream xatosi natijani yo'qotmaydi
            logger.debug("AI token stream failed", exc_info=True)
            result.error = result.error or type(exc).__name__
        await self.finish()
        result.truncated = buffer.truncated
        result.text = self._last_text or buffer.text[: self.max_chars]
        return result

    async def finish(self, final_text: str | None = None) -> str:
        """Yakuniy (kursorsiz) matnni yuboradi va uni qaytaradi."""
        if final_text is not None:
            self.final_text = final_text
        if not await self.push(final=True, force=True):
            body = self.final_text or (self.buffer.text if self.buffer else "")
            self._last_text = self.display_text(body, final=True)
        return self._last_text or ""


async def stream_tokens(editor: Callable[..., Awaitable[Any]] | None,
                        tokens: AsyncIterable[Any] | Iterable[Any],
                        **kwargs: Any) -> StreamResult:
    """Qisqa kirish: token oqimini ``editor`` orqali ko'rsatadi."""
    return await AIStreamRenderer(editor=editor, **kwargs).render(tokens)


async def render_rich_draft(editor: Callable[..., Awaitable[Any]] | None,
                            draft: RichMessageDraft) -> StreamResult:
    """Tayyor boy qoralamani **bitta** tahrir bilan chiqaradi (oqimsiz)."""
    renderer = AIStreamRenderer(editor=editor, cursor="", final_text=draft.text)
    renderer.buffer.feed(draft.text)  # type: ignore[union-attr]
    await renderer.push(final=True, force=True)
    result = renderer.result
    result.completed = True
    result.tokens = renderer.buffer.tokens if renderer.buffer else 0
    result.text = draft.text
    return result


__all__ = [
    "DEFAULT_MAX_FINAL_WAIT",
    "DEFAULT_MIN_DELTA_CHARS",
    "DEFAULT_STREAM_CURSOR",
    "RICH_STYLES",
    "TELEGRAM_MESSAGE_LIMIT",
    "AIStreamRenderer",
    "RichButton",
    "RichMessageDraft",
    "RichMessageDraftRender",
    "StreamResult",
    "TokenStreamBuffer",
    "close_open_tags",
    "render_rich_draft",
    "stream_tokens",
    "truncate_message",
]
