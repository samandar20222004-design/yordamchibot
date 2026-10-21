"""⏳ «JIM QOLMA» — bot ~2 soniya javob bermasa, foydalanuvchiga darhol «tahlil qilinmoqda» yozuvi.

Muammo: DB/AI/tarmoq sekin bo'lganda bot jim turardi va foydalanuvchi bot
qotib qoldi deb o'ylardi. Yechim: har bir xabar/tugma update'i uchun fon
kuzatuvchi. Agar ``SLOW_NOTICE_SECONDS`` ichida handler foydalanuvchiga hech
narsa yubormagan/tahrirlamagan bo'lsa — chatga «⏳ ...» yozuvi chiqadi (+ «yozmoqda»
holati), handler tugagach yozuv o'chiriladi. Tez handler'larda hech narsa
ko'rinmaydi. Javob berilganini ``Bot._post`` ga o'rnatilgan kuzatuvchi billadi.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import os

from telegram import Bot

from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

SLOW_NOTICE_SECONDS = float(os.getenv("SLOW_NOTICE_SECONDS", "2.0") or 2.0)

#: Foydalanuvchiga ko'rinadigan javob hisoblanadigan Bot API metodlari.
_VISIBLE_PREFIXES = ("send", "edit", "copyMessage", "forwardMessage")

_STATE: contextvars.ContextVar = contextvars.ContextVar("slow_notice_state", default=None)
_ORIGINAL_POST = Bot._post
_INSTALLED = False


class _State:
    __slots__ = ("responded", "chat_id")

    def __init__(self, chat_id):
        self.responded = False
        self.chat_id = chat_id


def _install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    async def tracked_post(self, endpoint, data=None, *args, **kwargs):
        state = _STATE.get()
        if state is not None and not state.responded and endpoint.startswith(_VISIBLE_PREFIXES):
            if not endpoint.startswith("sendChatAction") and (
                data is None or data.get("chat_id", state.chat_id) == state.chat_id
            ):
                state.responded = True
        return await _ORIGINAL_POST(self, endpoint, data, *args, **kwargs)

    tracked_post.__wrapped__ = _ORIGINAL_POST  # type: ignore[attr-defined]
    Bot._post = tracked_post  # type: ignore[method-assign]
    _INSTALLED = True


_install()


def _chat_of(update):
    chat = getattr(update, "effective_chat", None)
    if chat is None or getattr(chat, "type", None) != "private":
        return None
    return getattr(chat, "id", None)


async def _watch(update, bot, state: _State, lang_getter, delay: float) -> None:
    sent = None
    try:
        await asyncio.sleep(delay)
        if state.responded:
            return
        try:
            await bot.send_chat_action(chat_id=state.chat_id, action="typing")
        except Exception as exc:  # noqa: BLE001
            log_silent_failure("utils.slow_notice:chat_action", exc)
        lang = await lang_getter(update)
        if state.responded:
            return
        from locales.translations import get_text
        sent = await bot.send_message(chat_id=state.chat_id, text=get_text("sys_working_notice", lang))
        # Handler tugamaguncha kutamiz; bekor qilinganda yozuv o'chiriladi.
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    except Exception as exc:  # noqa: BLE001 — bildirishnoma asosiy oqimni buzmasin
        log_silent_failure("utils.slow_notice:_watch", exc)
    finally:
        if sent is not None:
            try:
                await asyncio.shield(bot.delete_message(chat_id=state.chat_id, message_id=sent.message_id))
            except Exception as exc:  # noqa: BLE001
                log_silent_failure("utils.slow_notice:delete", exc)


def start(update, bot, lang_getter, delay: float | None = None):
    """Kuzatuvchini ishga tushiradi. Qaytadi: ``(task, token)`` yoki ``(None, None)``."""
    wait = SLOW_NOTICE_SECONDS if delay is None else delay
    if wait <= 0 or bot is None:
        return None, None
    if getattr(update, "message", None) is None and getattr(update, "callback_query", None) is None:
        return None, None
    chat_id = _chat_of(update)
    if chat_id is None:
        return None, None
    state = _State(chat_id)
    token = _STATE.set(state)
    try:
        task = asyncio.ensure_future(_watch(update, bot, state, lang_getter, wait))
    except RuntimeError:  # pragma: no cover
        _STATE.reset(token)
        return None, None
    return task, token


async def stop(task, token) -> None:
    """Handler tugadi: kuzatuvchi bekor qilinadi, bor bo'lsa yozuv o'chiriladi."""
    if token is not None:
        try:
            _STATE.reset(token)
        except ValueError:  # boshqa kontekstda
            pass
    if task is None:
        return
    if not task.done():
        task.cancel()
    try:
        await task
    except BaseException:  # noqa: BLE001
        pass
