"""The cloud entry's second lock (issues #566, #567).

The packaged image has two doors (``deploy/nginx.conf.template``): the
private one every device on the owner's network uses, and the *cloud entry*
a public tunnel points at. nginx lets only the AI-connection routes through
the cloud entry and marks those requests with ``X-Palaia-Entry: cloud``; the
private door always clears that header, so a client cannot set it.

This middleware is the hub's own half of the rule, so it holds even when a
tunnel or proxy is pointed somewhere unexpected:

* a cloud-entry request for anything but :data:`CLOUD_ENTRY_PREFIXES` (the
  dashboard, every ``/api`` route) gets 404;
* while the hub is in ``locked`` mode — cloud access not turned on — every
  cloud-entry request gets 403 with a plain explanation. The installer can
  therefore prepare the tunnel before the owner has decided anything: until
  they switch to Cloud mode in the dashboard, the tunnel leads nowhere.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

ENTRY_HEADER = b"x-palaia-entry"
CLOUD_ENTRY = b"cloud"

#: What a cloud AI app needs: the MCP endpoints, their sign-in pages, the
#: discovery documents, and the Telegram webhook. Kept identical to the
#: cloud server block in ``deploy/nginx.conf.template`` (a test checks both).
CLOUD_ENTRY_PREFIXES: tuple[str, ...] = ("/mcp", "/oauth", "/.well-known", "/telegram/webhook")


def is_cloud_entry(scope: Scope) -> bool:
    for name, value in scope.get("headers") or ():
        if name == ENTRY_HEADER:
            return bool(value.strip().lower() == CLOUD_ENTRY)
    return False


def _allowed(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in CLOUD_ENTRY_PREFIXES)


class CloudEntryMiddleware:
    """Refuse cloud-entry requests the running mode does not allow."""

    def __init__(self, app: ASGIApp, *, mode: str) -> None:
        self.app = app
        self.mode = mode

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_cloud_entry(scope):
            await self.app(scope, receive, send)
            return
        if not _allowed(str(scope.get("path", ""))):
            await _answer(
                send, 404, "not_found", "This address serves palaia's AI connection only."
            )
            return
        if self.mode == "locked":
            await _answer(
                send,
                403,
                "cloud_access_off",
                "This palaia hub does not accept connections from the internet. Its owner "
                "can turn on cloud access in the dashboard.",
            )
            return
        await self.app(scope, receive, send)


async def _answer(send: Send, status: int, error: str, description: str) -> None:
    body = json.dumps({"error": error, "error_description": description}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


__all__ = ["CLOUD_ENTRY_PREFIXES", "CloudEntryMiddleware", "is_cloud_entry"]
