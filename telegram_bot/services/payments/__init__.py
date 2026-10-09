"""Automated payment providers (merchant callbacks).

Existing payment methods (Telegram Stars invoices and manual card receipts)
live in :mod:`services.payment_service` and are intentionally untouched.
This package hosts *automated* merchant integrations that are driven by
provider callbacks instead of a human/admin approval step:

* :mod:`services.payments.payme_provider` — Payme Merchant API (JSON-RPC)
  state machine, Basic Auth verification and checkout link builder;
* :mod:`services.payments.payme_webhook` — lightweight aiohttp endpoint that
  exposes the provider on ``POST /payments/payme``;
* :mod:`services.payments.memory_store` — in-memory store used by tests and
  local sandboxes (production uses ``repositories.payme_repository``).
"""

from services.payments.payme_provider import (  # noqa: F401
    PaymeConfig,
    PaymeError,
    PaymeProvider,
    build_checkout_url,
)

__all__ = ["PaymeConfig", "PaymeError", "PaymeProvider", "build_checkout_url"]
