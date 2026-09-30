# -*- coding: utf-8 -*-
"""PHASE 5 — Telegram Delivery Engine (yagona yetkazib berish nuqtasi).

Barcha kanal postlari, rejalashtirilgan yuborishlar, manual/autopilot
publish va bulk broadcast shu paketdagi ``delivery_service`` orqali o'tadi:

    from services.delivery import delivery_service

    await delivery_service.send_message(bot, chat_id=..., text=...)

``utils.telegram_delivery`` (SafeHTMLBot) — HTML SSOT chegarasi sifatida
o'z joyida qoladi; bu paket esa rate-limit, RetryAfter, idempotency va
failure classification'ni boshqaradi.
"""

from services.delivery.engine import (  # noqa: F401
    TelegramDeliveryService,
    delivery_service,
    get_delivery_service,
    FAILURE_PERMANENT,
    FAILURE_RATE_LIMIT,
    FAILURE_AMBIGUOUS,
    FAILURE_TRANSIENT,
    GLOBAL_PER_SECOND,
    CHANNEL_PER_SECOND,
    DEFAULT_INLINE_MAX_WAIT,
    BROADCAST_INLINE_MAX_WAIT,
)

__all__ = [
    "TelegramDeliveryService",
    "delivery_service",
    "get_delivery_service",
    "FAILURE_PERMANENT",
    "FAILURE_RATE_LIMIT",
    "FAILURE_AMBIGUOUS",
    "FAILURE_TRANSIENT",
    "GLOBAL_PER_SECOND",
    "CHANNEL_PER_SECOND",
    "RETRY_JITTER_MAX",
    "DEFAULT_INLINE_MAX_WAIT",
    "BROADCAST_INLINE_MAX_WAIT",
]
