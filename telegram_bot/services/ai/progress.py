"""Rate-limited, localized progress updates for long-running AI requests.

Telegram limits edits to a message; this small reporter deliberately spaces
``editMessageText`` calls by at least 1.1 seconds (default). Generation keeps
running concurrently while the user sees meaningful drafting stages.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
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


def normalize_progress_language(lang: str | None) -> str:
    """Return one of the supported progress languages (Uzbek is the fallback)."""
    code = str(lang or "uz").strip().lower().split("-")[0]
    return code if code in AI_PROGRESS_STAGES else "uz"


class AIProgressReporter:
    """Show staged status while awaiting an AI coroutine.

    ``editor`` must edit one Telegram message (either Message.edit_text or
    CallbackQuery.edit_message_text). It is invoked no more often than once
    per ``minimum_edit_interval``. A final-result edit should be preceded by
    :meth:`finish` so it also observes the spacing limit.

    The first stage can already have been sent as a new message. Set
    ``initial_displayed=True`` in that case; the reporter will not redundantly
    edit it on startup.
    """

    def __init__(
        self,
        editor: Callable[..., Awaitable[Any]] | None = None,
        lang: str = "uz",
        *,
        stages: Sequence[str] | None = None,
        stage_interval: float = 2.0,
        minimum_edit_interval: float = 1.1,
        initial_displayed: bool = False,
    ) -> None:
        self.editor = editor
        self.stages = tuple(stages or AI_PROGRESS_STAGES[normalize_progress_language(lang)])
        if not self.stages:
            self.stages = AI_PROGRESS_STAGES["uz"]
        # Guard the Telegram limit even if a caller supplies a smaller value.
        self.minimum_edit_interval = max(1.05, float(minimum_edit_interval))
        self.stage_interval = max(self.minimum_edit_interval, float(stage_interval))
        self.stage_index = 0
        self.last_edit_at: float | None = None
        self.last_text: str | None = self.stages[0] if initial_displayed else None
        if initial_displayed:
            # A sendMessage isn't an edit, but it is safe to start the stage
            # clock here so the first edit doesn't arrive immediately.
            self.last_edit_at = None

    @property
    def current_text(self) -> str:
        return self.stages[min(self.stage_index, len(self.stages) - 1)]

    def mark_initial_edit(self, *, at: float | None = None) -> None:
        """Record a successful first edit performed by the caller."""
        self.last_text = self.current_text
        self.last_edit_at = time.monotonic() if at is None else float(at)

    async def _wait_for_edit_slot(self) -> None:
        if self.last_edit_at is None:
            return
        elapsed = time.monotonic() - self.last_edit_at
        remaining = self.minimum_edit_interval - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def _edit(self, text: str) -> bool:
        if not callable(self.editor) or text == self.last_text:
            return False
        await self._wait_for_edit_slot()
        try:
            await self.editor(text)
        except Exception:  # noqa: BLE001 — progress must never fail generation
            logger.debug("AI progress edit failed", exc_info=True)
            return False
        self.last_edit_at = time.monotonic()
        self.last_text = text
        return True

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
        task = asyncio.create_task(operation)
        try:
            next_stage = self.stage_index + 1
            while next_stage < len(self.stages) and not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=self.stage_interval)
                except asyncio.TimeoutError:
                    self.stage_index = next_stage
                    next_stage += 1
                    await self._edit(self.current_text)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Propagate the operation's original exception.
                    raise
            return await task
        except asyncio.CancelledError:
            if not task.done():
                task.cancel()
            raise

    async def finish(self) -> None:
        """Wait until a subsequent result edit is safe under Telegram limits."""
        await self._wait_for_edit_slot()


__all__ = [
    "AI_PROGRESS_STAGES",
    "AIProgressReporter",
    "normalize_progress_language",
]
