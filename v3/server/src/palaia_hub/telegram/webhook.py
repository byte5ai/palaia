"""Webhook transport (issue #411): the opt-in for hubs with a public URL.

``POST /telegram/webhook/{bot}``. Telegram pushes each update here instead of
the hub pulling it, which removes the poll latency and the idle connections —
at the price of needing a URL that Telegram's servers can reach, which a
``locked`` hub by definition does not have. Long polling stays the default;
this is what a ``cloud``/``open`` hub can switch to.

**The secret token is the whole authentication story, so it is checked
first and compared in constant time.** Telegram's own mechanism: the operator
passes ``secret_token`` to ``setWebhook``, and Telegram then echoes it in an
``X-Telegram-Bot-Api-Secret-Token`` header on every delivery. The URL itself
is not a secret — it contains a bot *key*, which is the operator's own short
name and appears in ``config.yaml``, logs and the dashboard — so without this
header check the endpoint would be an unauthenticated inbox for anyone who
guessed the key. :class:`~palaia_hub.telegram.models.TelegramBotConfig`
refuses a webhook bot with no ``webhook_secret`` for exactly this reason,
and :meth:`~palaia_hub.telegram.service.TelegramService.webhook_secret`
refuses one whose secret store entry is empty: there is no configuration in
which this route runs without a check.

**Why this router is not behind the admin session.** Telegram is not a
browser and has no session; the hub cannot demand a bearer token of it
either (``setWebhook`` takes no arbitrary headers beyond the secret one).
The secret-token header *is* this surface's credential — the same shape the
outbound-webhook receiver on the other side of :mod:`palaia_hub.hooks` uses,
seen from the opposite direction.

**Always answer 200 once the update is accepted.** Telegram retries a
delivery that did not get a 2xx, so a hub-side delivery failure (a vault that
refused a capture) must not turn into a redelivery loop — it is reported in
the response body and on the event bus, and the update is not re-sent.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from .models import MissingSecretError, TelegramError, UnknownBotError
from .service import TelegramService

logger = logging.getLogger("palaia_hub.telegram.webhook")

#: The header Telegram echoes the configured ``secret_token`` in.
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"

#: Where the webhook endpoint lives. One segment per bot, so several bots can
#: point at the same hub with different secrets.
WEBHOOK_PREFIX = "/telegram/webhook"


def verify_secret(expected: str, presented: str | None) -> bool:
    """Whether ``presented`` is the configured secret token.

    ``hmac.compare_digest`` rather than ``==``: the comparison runs on an
    unauthenticated request, so it is exactly the place a timing oracle would
    be reachable from the internet. A missing header is a plain ``False`` —
    never an exception, which would turn into a 500 and tell the caller that
    the bot key at least exists.
    """
    if not expected or not presented:
        return False
    return hmac.compare_digest(expected, presented)


def build_telegram_webhook_router(service: TelegramService) -> APIRouter:
    """The ``POST /telegram/webhook/{bot}`` route, backed by ``service``."""
    router = APIRouter(prefix=WEBHOOK_PREFIX, tags=["telegram"])

    @router.post("/{bot}")
    async def receive(bot: str, request: Request) -> Response:
        try:
            config = service.require_bot(bot)
        except UnknownBotError:
            # 404 for an unknown bot key, and nothing about which keys exist.
            return JSONResponse({"detail": "no such Telegram webhook"}, status_code=404)
        if config.transport != "webhook":
            return JSONResponse(
                {
                    "detail": (
                        f"bot {bot!r} is configured for long polling; it has no "
                        "webhook endpoint"
                    )
                },
                status_code=404,
            )
        try:
            expected = service.webhook_secret(config)
        except MissingSecretError as exc:
            # Fail closed, loudly on the hub's side and opaquely on the wire:
            # a misconfigured hub must never accept an unverified update.
            logger.error("telegram webhook for bot %r cannot verify: %s", bot, exc)
            return JSONResponse({"detail": "webhook not configured"}, status_code=503)
        if not verify_secret(expected, request.headers.get(SECRET_HEADER)):
            logger.warning(
                "telegram webhook for bot %r rejected: bad or missing %s",
                bot,
                SECRET_HEADER,
            )
            return JSONResponse({"detail": "bad secret token"}, status_code=401)

        try:
            payload: Any = await request.json()
        except Exception:
            return JSONResponse({"detail": "body is not JSON"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"detail": "body is not a Telegram update"}, status_code=400)

        try:
            outcome = await service.handle_update(bot, payload)
        except TelegramError as exc:  # pragma: no cover - handle_update absorbs these
            logger.warning("telegram webhook for bot %r could not dispatch: %s", bot, exc)
            return JSONResponse({"ok": True, "detail": str(exc)}, status_code=200)
        return JSONResponse(
            {
                "ok": True,
                "routed": outcome.routed,
                "delivered": outcome.delivered,
                "destination": outcome.destination,
                "detail": outcome.detail,
            },
            status_code=200,
        )

    return router


__all__ = ["SECRET_HEADER", "WEBHOOK_PREFIX", "build_telegram_webhook_router", "verify_secret"]
