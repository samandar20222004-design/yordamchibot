"""Final HTML safety boundary for all PTB sends/edits, including albums.

The application and scheduler share this ExtBot. Sanitization happens AFTER
PTB resolves Defaults and api_kwargs, BEFORE rate limiting/network I/O. No
retry is introduced here (a network timeout may mean delivery succeeded).
"""
from copy import copy
import time

from telegram import TelegramObject
from telegram.ext import ExtBot
from telegram.request import HTTPXRequest

import config

from utils.telegram_sanitizer import (
    sanitize_html, TELEGRAM_TEXT_LIMIT, TELEGRAM_CAPTION_LIMIT,
)

from utils.silent_errors import log_silent_failure

_NESTED = ("media", "results", "input_message_content")
_FIELDS = ("text", "message_text", "caption", "parse_mode", "entities",
           "caption_entities", *_NESTED)


def sanitize_api_payload(value):
    """Copy only changed payload containers; never mutate reusable media/files.

    Explicit entities/Markdown/plain text are left untouched. When HTML is
    selected, any conflicting precomputed offsets are discarded: Telegram
    computes entities from the sanitized HTML instead.
    """
    if isinstance(value, (list, tuple)):
        return [sanitize_api_payload(item) for item in value]
    if isinstance(value, TelegramObject):
        original = {key: getattr(value, key) for key in _FIELDS if hasattr(value, key)}
        updated = sanitize_api_payload(original)
        changes = {key: item for key, item in updated.items()
                   if key in original and (item is not original[key] if key in _NESTED
                                           else item != original[key])}
        if not changes:
            return value
        result = copy(value)
        with result._unfrozen():
            for key, item in changes.items():
                setattr(result, key, item)
        return result
    if not isinstance(value, dict):
        return value
    result = dict(value)
    if str(result.get("parse_mode", "")).upper() == "HTML":
        for key, limit in (("text", TELEGRAM_TEXT_LIMIT),
                           ("message_text", TELEGRAM_TEXT_LIMIT),
                           ("caption", TELEGRAM_CAPTION_LIMIT)):
            if result.get(key) is not None:
                result[key] = sanitize_html(result[key], limit)
                entity_key = "caption_entities" if key == "caption" else "entities"
                if entity_key in result:
                    result[entity_key] = None
    for key in _NESTED:
        if key in result:
            result[key] = sanitize_api_payload(result[key])
    return result


class SafeHTMLBot(ExtBot):
    """Production bot: one mandatory SSOT pass for every HTML request."""

    async def _do_post(self, endpoint, data, **kwargs):
        # Count outgoing Bot API attempts without recording endpoint payloads,
        # chat contents, token-bearing URLs, or method arguments.
        safe_data = sanitize_api_payload(data)
        started = time.perf_counter()
        error = None
        try:
            return await super()._do_post(endpoint, safe_data, **kwargs)
        except Exception as exc:
            error = exc
            raise
        finally:
            try:
                from services.observability import record_telegram_request
                record_telegram_request(
                    status_code=getattr(error, "error_code", None),
                    error=error,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            except Exception as _silent_exc:
                # Metrics must never alter Telegram request semantics.
                log_silent_failure("utils.telegram_delivery:SafeHTMLBot._do_post", _silent_exc)


def create_safe_bot(token):
    """Preserve the application's existing network timeout/pool settings.

    STAGING (ixtiyoriy): ``TELEGRAM_API_BASE_URL`` to'ldirilgan bo'lsa, bot
    HAQIQIY Telegram API o'rniga shu manzilga (mock Telegram server) gapiradi
    — yuklama testlari production API'ga spam yubormaydi. Bo'sh bo'lsa
    xatti-harakat o'zgarmaydi (default ``https://api.telegram.org/bot``).
    """
    base_url = getattr(config, "TELEGRAM_API_BASE_URL", "") or ""
    extra = {"base_url": base_url} if base_url else {}
    return SafeHTMLBot(
        token=token,
        **extra,
        request=HTTPXRequest(
            connect_timeout=15, read_timeout=15, write_timeout=30,
            media_write_timeout=60, pool_timeout=5, connection_pool_size=8,
        ),
        get_updates_request=HTTPXRequest(connection_pool_size=1),
    )
