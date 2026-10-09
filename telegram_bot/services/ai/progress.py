"""Rate-limited, localized progress updates for long-running AI requests.

While an LLM call runs (typically 5–10 s) the user sees drafting stages::

    🧠 Mavzu tahlil qilinmoqda...  →  ✍️ Post yozilmoqda...  →  ✨ Emojilar va sayqal berilmoqda...

Telegram flood control is respected strictly:

* **≥ 1.05 s between edits of the same message** (``minimum_edit_interval``
  can be raised but never lowered below the floor);
* **≥ 1.05 s between edits in the same chat** — a process-wide, bounded
  per-chat clock (``CHAT_EDIT_CLOCK``) is shared by every reporter, so two
  concurrent generations in one chat cannot double the edit rate;
* **429 / RetryAfter** — the advertised ``retry_after`` blocks that chat; a
  stage edit is *skipped* (never retried in a loop) and the final result
  edit waits for the window (bounded by ``max_finish_wait``);
* "message is not modified" is treated as a successful no-op.

Stage edits only happen when the AI call outlasts a stage interval, so fast
responses cause zero extra API calls. Progress failures never fail the
generation itself.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from datetime import timedelta
from typing import Any

logger = logging.getLogger(__name__)

AI_PROGRESS_STAGES: dict[str, tuple[str, str, str]] = {
    "uz": (
        "🧠 Mavzu tahlil qilinmoqda...",
        "✍️ Post yozilmoqda...",
        "✨ Emojilar va sayqal berilmoqda...",
    ),
    "ru": (
        "🧠 Анализируем тему...",
        "✍️ Пишем пост...",
        "✨ Добавляем эмодзи и финальные штрихи...",
    ),
    "en": (
        "🧠 Analyzing the topic...",
        "✍️ Writing your post...",
        "✨ Adding emojis and polishing...",
    ),
}

#: Stages for analysis-style requests (audit, scoring, content plans, voice
#: analysis) where "writing a post" would be misleading.
AI_ANALYSIS_STAGES: dict[str, tuple[str, str, str]] = {
    "uz": (
        "🔎 Matn o'qilmoqda...",
        "🧠 Tahlil qilinmoqda...",
        "📊 Natijalar tayyorlanmoqda...",
    ),
    "ru": (
        "🔎 Читаем материал...",
        "🧠 Анализируем...",
        "📊 Готовим результаты...",
    ),
    "en": (
        "🔎 Reading the content...",
        "🧠 Analyzing...",
        "📊 Preparing the results...",
    ),
}

PROGRESS_STAGE_SETS: dict[str, dict[str, tuple[str, str, str]]] = {
    "post": AI_PROGRESS_STAGES,
    "analysis": AI_ANALYSIS_STAGES,
}

#: Telegram tolerates roughly one edit per second per chat; keep a margin.
MIN_EDIT_INTERVAL_FLOOR = 1.05
#: Hard cap on a single RetryAfter we honour (defensive against bad values).
MAX_RETRY_AFTER_SECONDS = 60.0


def normalize_progress_language(lang: str | None) -> str:
    """Return one of the supported progress languages (Uzbek is the fallback)."""
    code = str(lang or "uz").strip().lower().split("-")[0]
    return code if code in AI_PROGRESS_STAGES else "uz"


def progress_stages(lang: str | None, kind: str = "post") -> tuple[str, ...]:
    """Localized stage texts; ``kind`` is ``"post"`` (default) or ``"analysis"``."""
    stage_set = PROGRESS_STAGE_SETS.get(str(kind or "post"), AI_PROGRESS_STAGES)
    return stage_set[normalize_progress_language(lang)]


def _retry_after_seconds(exc: BaseException) -> float | None:
    """Seconds from a Telegram flood error (PTB ``RetryAfter``), else ``None``."""
    value = getattr(exc, "retry_after", None)
    if value is None:
        return None
    if isinstance(value, timedelta):
        value = value.total_seconds()
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(seconds, MAX_RETRY_AFTER_SECONDS))


def _is_not_modified(exc: BaseException) -> bool:
    return "not modified" in str(exc).lower()


class ChatEditClock:
    """Process-wide "next allowed edit" timestamps per chat (bounded LRU).

    Times are ``time.monotonic()`` seconds. Thread-safe; tiny critical
    sections only (no awaiting under the lock).
    """

    def __init__(self, max_chats: int = 10_000) -> None:
        self._next: OrderedDict[Any, float] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max(1, int(max_chats))

    def next_allowed(self, chat_id: Any) -> float:
        if chat_id is None:
            return 0.0
        with self._lock:
            return self._next.get(chat_id, 0.0)

    def push(self, chat_id: Any, not_before: float) -> None:
        """Move the chat's next allowed edit to at least ``not_before``."""
        if chat_id is None:
            return
        with self._lock:
            current = self._next.pop(chat_id, 0.0)
            self._next[chat_id] = max(current, float(not_before))
            while len(self._next) > self._max:
                self._next.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._next.clear()


CHAT_EDIT_CLOCK = ChatEditClock()


class AIProgressReporter:
    """Show staged status while awaiting an AI coroutine.

    ``editor`` must edit one Telegram message (either Message.edit_text or
    CallbackQuery.edit_message_text). It is invoked no more often than once
    per ``minimum_edit_interval`` (per message *and* per chat). A final-result
    edit should be preceded by :meth:`finish` so it also observes the limit.

    The first stage can already have been sent as a new message. Set
    ``initial_displayed=True`` (or use :meth:`attach_message`) in that case;
    the reporter will not redundantly edit it on startup.

    Prefer the helpers :meth:`for_reply` / :meth:`for_callback`; ``message``
    then holds the Telegram message that shows the progress (and should show
    the final result).
    """

    def __init__(
        self,
        editor: Callable[..., Awaitable[Any]] | None = None,
        lang: str = "uz",
        *,
        stages: Sequence[str] | None = None,
        kind: str = "post",
        stage_interval: float = 2.0,
        minimum_edit_interval: float = 1.1,
        initial_displayed: bool = False,
        chat_id: Any = None,
        max_finish_wait: float = 5.0,
        clock: ChatEditClock | None = None,
    ) -> None:
        self.editor = editor
        self.stages = tuple(stages or progress_stages(lang, kind))
        if not self.stages:
            self.stages = AI_PROGRESS_STAGES["uz"]
        # Guard the Telegram limit even if a caller supplies a smaller value.
        self.minimum_edit_interval = max(MIN_EDIT_INTERVAL_FLOOR, float(minimum_edit_interval))
        self.stage_interval = max(self.minimum_edit_interval, float(stage_interval))
        self.max_finish_wait = max(0.0, float(max_finish_wait))
        self.chat_id = chat_id
        self.message: Any = None
        self.stage_index = 0
        self.edit_count = 0
        self.skipped_edits = 0
        self.last_edit_at: float | None = None
        self._blocked_until = 0.0
        self._clock = clock or CHAT_EDIT_CLOCK
        # A sendMessage isn't an edit, so the stage clock starts unset.
        self.last_text: str | None = self.stages[0] if initial_displayed else None

    # -- construction helpers ------------------------------------------
    @classmethod
    async def for_reply(cls, message, lang: str = "uz", **kwargs) -> "AIProgressReporter":
        """Send stage 1 as a reply to ``message`` and keep editing that reply."""
        kwargs.setdefault("chat_id", getattr(message, "chat_id", None))
        reporter = cls(lang=lang, **kwargs)
        sent = await message.reply_text(reporter.current_text)
        reporter.attach_message(sent)
        return reporter

    @classmethod
    async def for_callback(cls, query, lang: str = "uz", **kwargs) -> "AIProgressReporter":
        """Edit the callback's message into stage 1 (fallback: one new reply)."""
        source = getattr(query, "message", None)
        kwargs.setdefault("chat_id", getattr(source, "chat_id", None))
        reporter = cls(editor=getattr(query, "edit_message_text", None), lang=lang, **kwargs)
        await reporter.begin()
        if reporter.last_text is not None:
            reporter.message = source
            return reporter
        # Editing the menu failed: send ONE progress message and edit it later
        # (never one new message per stage).
        reporter.editor = None
        replier = getattr(source, "reply_text", None)
        if callable(replier):
            try:
                reporter.attach_message(await replier(reporter.current_text))
            except Exception:  # noqa: BLE001 — progress is best-effort
                logger.debug("AI progress fallback reply failed", exc_info=True)
        return reporter

    def attach_message(self, message) -> None:
        """Use an already-sent progress message (showing the current stage)."""
        self.message = message
        self.last_text = self.current_text
        editor = getattr(message, "edit_text", None) if message is not None else None
        # Minimal adapters may not expose Message.edit_text; then no stage
        # edits happen (rather than sending one message per stage).
        self.editor = editor if callable(editor) else None

    # -- state ---------------------------------------------------------
    @property
    def current_text(self) -> str:
        return self.stages[min(self.stage_index, len(self.stages) - 1)]

    def mark_initial_edit(self, *, at: float | None = None) -> None:
        """Record a successful first edit performed by the caller."""
        self._record_edit(self.current_text, time.monotonic() if at is None else float(at))

    def _record_edit(self, text: str, at: float | None = None) -> None:
        now = time.monotonic() if at is None else at
        self.last_edit_at = now
        self.last_text = text
        self.edit_count += 1
        self._clock.push(self.chat_id, now + self.minimum_edit_interval)

    def _block_for(self, seconds: float) -> None:
        until = time.monotonic() + max(seconds, self.minimum_edit_interval)
        self._blocked_until = max(self._blocked_until, until)
        self._clock.push(self.chat_id, until)

    def next_edit_slot(self) -> float:
        """Monotonic time of the earliest edit allowed for this message/chat."""
        slot = self._blocked_until
        if self.last_edit_at is not None:
            slot = max(slot, self.last_edit_at + self.minimum_edit_interval)
        return max(slot, self._clock.next_allowed(self.chat_id))

    async def _wait_for_edit_slot(self, max_wait: float | None = None) -> bool:
        """Sleep until an edit is allowed; ``False`` if that exceeds ``max_wait``."""
        remaining = self.next_edit_slot() - time.monotonic()
        if remaining <= 0:
            return True
        if max_wait is not None and remaining > max_wait:
            return False
        await asyncio.sleep(remaining)
        return True

    async def _edit(self, text: str) -> bool:
        if not callable(self.editor) or text == self.last_text:
            return False
        # A stage that cannot be shown within one interval (flood wait) is
        # skipped — the next stage or the final result supersedes it.
        if not await self._wait_for_edit_slot(max_wait=self.stage_interval):
            self.skipped_edits += 1
            return False
        try:
            await self.editor(text)
        except Exception as exc:  # noqa: BLE001 — progress must never fail generation
            retry_after = _retry_after_seconds(exc)
            if retry_after is not None:
                self._block_for(retry_after)
                self.skipped_edits += 1
                logger.info("AI progress edit throttled by Telegram (retry_after=%.1fs)", retry_after)
                return False
            if _is_not_modified(exc):
                self._record_edit(text)
                return True
            logger.debug("AI progress edit failed", exc_info=True)
            return False
        self._record_edit(text)
        return True

    # -- lifecycle -----------------------------------------------------
    async def begin(self) -> None:
        """Render the initial analysis stage unless the caller already sent it."""
        if self.last_text is None:
            await self._edit(self.current_text)

    async def run(self, operation: Awaitable[Any]) -> Any:
        """Run ``operation`` while advancing through progress stages.

        The user-visible text is only edited when the AI call outlasts a stage
        interval. Stage messages therefore reflect real elapsed work without
        fake token streaming or excessive Telegram API calls.
        """
        await self.begin()
        task = asyncio.ensure_future(operation)
        try:
            next_stage = self.stage_index + 1
            while next_stage < len(self.stages) and not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=self.stage_interval)
                except asyncio.TimeoutError:
                    self.stage_index = next_stage
                    next_stage += 1
                    await self._edit(self.current_text)
            return await task
        except asyncio.CancelledError:
            if not task.done():
                task.cancel()
            raise

    async def finish(self) -> None:
        """Wait until a subsequent result edit is safe under Telegram limits."""
        remaining = self.next_edit_slot() - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(min(remaining, self.max_finish_wait))


__all__ = [
    "AI_ANALYSIS_STAGES",
    "AI_PROGRESS_STAGES",
    "PROGRESS_STAGE_SETS",
    "AIProgressReporter",
    "CHAT_EDIT_CLOCK",
    "ChatEditClock",
    "MIN_EDIT_INTERVAL_FLOOR",
    "normalize_progress_language",
    "progress_stages",
]
