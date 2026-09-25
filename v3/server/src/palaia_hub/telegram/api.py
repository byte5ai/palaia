"""The Telegram Bot API seam (issue #411): a five-method protocol, one HTTP
implementation, and the rule that keeps the token out of everything.

**Why a protocol.** The Bot API is a network service with no sandbox and no
test instance. Every test in ``tests/telegram/`` therefore runs against
:class:`~palaia_hub.telegram.api.BotApi` implemented by a fake
(``FakeBotApi`` in ``tests/telegram/conftest.py``) — routing, authorisation,
offset handling, webhook verification and the tool surface are all hub-side
logic, and hub-side logic is exactly what a fake can exercise honestly.
:class:`HttpBotApi` is the thin part that is left: build a URL, post JSON,
unwrap ``{"ok": ...}``.

**The token is an argument, never a field.** ``HttpBotApi`` holds no
credential — every method takes the token from the caller, which reads it
out of the encrypted secret store for that one call
(:class:`palaia_hub.telegram.service.TelegramService`). A long-lived object
with a token attribute is a long-lived object that shows up in a ``repr()``,
a ``vars()`` dump or a pickled traceback; this one has nothing to show.

**An error never quotes the URL.** Telegram puts the token *in the path*
(``/bot<token>/sendMessage``), which is the one place none of the usual
"redact the Authorization header" instincts look. So
:class:`TelegramApiError` is built from the *method name* and the API's own
description, never from ``response.url`` or the request object, and
:func:`redact_token` scrubs the token shape out of whatever the remote end
sent back before it is ever raised. :mod:`palaia_hub.logging` redacts the
same shape again on the way to a handler — belt, braces, and a test for
each (``tests/telegram/test_api.py``).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

import httpx

from .models import ALLOWED_UPDATES, TelegramError

logger = logging.getLogger("palaia_hub.telegram.api")

#: The public Bot API. Overridable per instance so a test (or a self-hosted
#: Bot API server, which Telegram supports) can point somewhere else.
DEFAULT_API_BASE = "https://api.telegram.org"

#: How long one non-polling call may take. ``getUpdates`` overrides it with
#: its own long-poll timeout plus a margin — see :meth:`HttpBotApi.get_updates`.
DEFAULT_TIMEOUT_SECONDS = 15.0

#: A Telegram bot token's shape: ``<bot id>:<35-character secret>``. Used to
#: scrub a token out of any string that might carry one, here and in
#: :mod:`palaia_hub.logging`. Deliberately a little looser than the exact
#: format (``\d{6,}`` and a 20+ tail) so a future format tweak on Telegram's
#: side does not silently un-redact anything.
#:
#: **No word boundaries**, and that is the point: the place a token actually
#: appears is ``…/bot123456789:AAH…/sendMessage``, where ``\b`` matches
#: neither end — ``bot`` runs straight into the digits, and the trailing
#: ``/`` follows a character class that includes ``-``. A boundary-anchored
#: pattern passes its unit test on a bare token and lets every real URL
#: through, which is the worst of both.
TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{20,}")

REDACTED = "***REDACTED***"


def redact_token(text: str) -> str:
    """Return ``text`` with anything token-shaped replaced by :data:`REDACTED`."""
    return TOKEN_RE.sub(REDACTED, text)


#: How long one error or outcome line the dashboard shows may get
#: (issue #439). Enough for "telegram getUpdates failed (HTTP 401):
#: Unauthorized" plus a fix; short enough that a sink's exception quoting
#: something long cannot turn a status row into a paragraph.
LINE_CHARS = 200


def summary_line(text: str, *, limit: int = LINE_CHARS) -> str:
    """``text`` as one short, token-free line for a status surface.

    Scrubbed with :func:`redact_token` *before* it is cut, so a truncation
    can never leave half a token behind for the pattern to miss; collapsed
    to one line because a status row has room for one.
    """
    line = " ".join(redact_token(text).split())
    if len(line) > limit:
        line = line[: limit - 1].rstrip() + "…"
    return line


class TelegramApiError(TelegramError):
    """The Bot API refused a call, or could not be reached.

    Carries the method name, the HTTP status when there was one, and
    Telegram's own ``description`` — scrubbed. Never the URL: see the module
    docstring.
    """

    def __init__(self, method: str, message: str, *, status: int | None = None) -> None:
        self.method = method
        self.status = status
        prefix = f"telegram {method} failed"
        if status is not None:
            prefix += f" (HTTP {status})"
        super().__init__(f"{prefix}: {redact_token(message)}")


class BotApi(Protocol):
    """What the connector needs of Telegram — and nothing more.

    Five methods, each taking the bot token as its first argument. A sixth
    would need a reason: every method here backs something the issue names
    (receive, send, reply, edit, delete), and ``get_me`` backs the
    connection-state check the dashboard shows per bot.
    """

    async def get_updates(
        self, token: str, *, offset: int | None, timeout: float, allowed_updates: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        """Long-poll for updates newer than ``offset``."""
        ...

    async def send_message(
        self,
        token: str,
        *,
        chat_id: str,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        """Send ``text``, optionally threaded under an existing message."""
        ...

    async def edit_message_text(
        self, token: str, *, chat_id: str, message_id: int, text: str
    ) -> dict[str, Any]:
        """Replace the text of a message this bot sent."""
        ...

    async def delete_message(self, token: str, *, chat_id: str, message_id: int) -> bool:
        """Delete a message this bot sent."""
        ...

    async def get_me(self, token: str) -> dict[str, Any]:
        """The bot's own account — the cheapest "is this token live" probe."""
        ...


class HttpBotApi:
    """:class:`BotApi` over HTTPS, using the hub's existing httpx dependency.

    One :class:`httpx.AsyncClient` is shared across bots and calls (connection
    reuse is most of what makes long polling cheap); :meth:`aclose` releases
    it. The client carries no auth of its own — see the module docstring.
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_API_BASE,
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _call(
        self, token: str, method: str, payload: dict[str, Any], *, timeout: float | None = None
    ) -> Any:
        """POST one Bot API method and unwrap its ``{"ok", "result"}`` envelope.

        Every failure path funnels through :class:`TelegramApiError` with the
        *method* as its subject. ``httpx`` exceptions are caught and
        re-raised the same way rather than allowed through: an
        ``httpx.ConnectError``'s own message embeds the request URL, token
        and all.
        """
        url = f"{self._base}/bot{token}/{method}"
        body = {k: v for k, v in payload.items() if v is not None}
        try:
            response = await self._client.post(
                url, json=body, timeout=timeout if timeout is not None else self._timeout
            )
        except httpx.HTTPError as exc:
            # str(exc) can contain the URL, and the URL contains the token.
            detail = f"{type(exc).__name__}: {redact_token(str(exc))}"
            raise TelegramApiError(method, detail) from None
        try:
            data = response.json()
        except ValueError:
            raise TelegramApiError(
                method, "the API returned a body that is not JSON", status=response.status_code
            ) from None
        if not isinstance(data, dict) or not data.get("ok"):
            description = ""
            if isinstance(data, dict):
                description = str(data.get("description") or "")
            raise TelegramApiError(
                method,
                description or "the API reported failure with no description",
                status=response.status_code,
            )
        return data.get("result")

    async def get_updates(
        self, token: str, *, offset: int | None, timeout: float, allowed_updates: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        result = await self._call(
            token,
            "getUpdates",
            {
                "offset": offset,
                "timeout": int(timeout),
                "allowed_updates": list(allowed_updates or ALLOWED_UPDATES),
            },
            # The HTTP read must outlive the long poll Telegram is holding
            # open, or every poll ends in a client-side timeout instead of an
            # empty result.
            timeout=timeout + DEFAULT_TIMEOUT_SECONDS,
        )
        if not isinstance(result, list):
            raise TelegramApiError("getUpdates", "expected a list of updates")
        return [item for item in result if isinstance(item, dict)]

    async def send_message(
        self,
        token: str,
        *,
        chat_id: str,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_to_message_id is not None:
            # `reply_parameters` is the current spelling; the deprecated
            # top-level `reply_to_message_id` is still accepted and is what
            # older self-hosted Bot API servers understand. Sending the
            # modern shape only — a self-hosted server that old would fail
            # loudly here rather than silently drop the threading, which is
            # the outcome worth having.
            payload["reply_parameters"] = {"message_id": reply_to_message_id}
        result = await self._call(token, "sendMessage", payload)
        if not isinstance(result, dict):
            raise TelegramApiError("sendMessage", "expected a message object")
        return result

    async def edit_message_text(
        self, token: str, *, chat_id: str, message_id: int, text: str
    ) -> dict[str, Any]:
        result = await self._call(
            token,
            "editMessageText",
            {"chat_id": chat_id, "message_id": message_id, "text": text},
        )
        if not isinstance(result, dict):
            raise TelegramApiError("editMessageText", "expected a message object")
        return result

    async def delete_message(self, token: str, *, chat_id: str, message_id: int) -> bool:
        result = await self._call(
            token, "deleteMessage", {"chat_id": chat_id, "message_id": message_id}
        )
        return bool(result)

    async def get_me(self, token: str) -> dict[str, Any]:
        result = await self._call(token, "getMe", {})
        if not isinstance(result, dict):
            raise TelegramApiError("getMe", "expected a user object")
        return result


__all__ = [
    "DEFAULT_API_BASE",
    "DEFAULT_TIMEOUT_SECONDS",
    "LINE_CHARS",
    "REDACTED",
    "TOKEN_RE",
    "BotApi",
    "HttpBotApi",
    "TelegramApiError",
    "redact_token",
    "summary_line",
]
