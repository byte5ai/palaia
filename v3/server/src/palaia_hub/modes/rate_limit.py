"""Rate limiting for public auth endpoints (SPEC-205 deliverable #4).

Mounted by :func:`palaia_hub.app.create_app` only when ``config.mode`` is
``cloud`` or ``open`` — the modes where these endpoints are reachable off
the operator's own network at all; ``locked`` mode has no public attack
surface to throttle and stays exactly as before this module existed.

**Throttles failures, not volume.** A fixed-window counter per
``(client IP, path)`` that only counts a request *against* the limit when
the response itself was a failure (status >= 400) — a login rejected, an
invalid/expired token, a malformed registration. A legitimate burst of
*successful* traffic against these same paths is never throttled, which
matters concretely here: MASTERPLAN §5.5's own hard-won lesson is that a
single connector fans refresh calls out over web, phone and desktop at
once (the mcp-hub "daily re-login" incident this SPEC's sibling, SPEC-203,
exists to prevent) — a volume-based limiter would reproduce exactly that
incident for every legitimate multi-device user, which defeats the whole
point. Repeated *failures* from one caller, on the other hand, is exactly
credential stuffing / registration spam / brute-force login, and gets
throttled regardless of how "successful" surrounding traffic looks.

In memory only — no store, no persistence across a restart. That is a
deliberate, stated trade-off: this is a first line of defense against
casual abuse against a *single* hub process, not a distributed rate
limiter, and every endpoint it covers already has its own cryptographic
defense underneath (argon2id-hashed secrets, PKCE, one-time codes) — this
middleware exists to blunt volume of *failures*, not to be the only
defense.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

#: The endpoints this SPEC's acceptance criterion means by "auth
#: endpoints": every one is reachable with no prior credential (a token
#: request, a login attempt, a client self-registration) and so is the
#: only line one otherwise-anonymous caller can hammer.
DEFAULT_RATE_LIMITED_PATHS: frozenset[str] = frozenset(
    {
        "/oauth/token",
        "/oauth/login",
        "/oauth/register",
        "/oauth/revoke",
        "/api/auth/tokens",
    }
)

#: Failed attempts allowed per ``(client IP, path)`` per window before a
#: 429 is returned *without* even reaching the real endpoint.
DEFAULT_LIMIT = 10
DEFAULT_WINDOW_SECONDS = 60.0


class AuthRateLimitMiddleware:
    """ASGI middleware: fixed-window limit on *failed* requests per path."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        paths: Iterable[str] = DEFAULT_RATE_LIMITED_PATHS,
        limit: int = DEFAULT_LIMIT,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._app = app
        self._paths = frozenset(paths)
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._failures: dict[tuple[str, str], list[float]] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or scope.get("path") not in self._paths:
            await self._app(scope, receive, send)
            return

        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        path = scope["path"]
        now = self._clock()
        bucket = self._failures.setdefault((client_ip, path), [])
        cutoff = now - self._window
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)

        if len(bucket) >= self._limit:
            retry_after = max(1, int(bucket[0] + self._window - now) + 1)
            await self._reject(send, retry_after)
            return

        status_holder: dict[str, int] = {}

        async def observing_send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        await self._app(scope, receive, observing_send)
        if status_holder.get("status", 200) >= 400:
            bucket.append(now)

    @staticmethod
    async def _reject(send: Send, retry_after: int) -> None:
        body = json.dumps(
            {
                "error": "rate_limited",
                "detail": "Too many failed attempts on this endpoint. Please wait and try again.",
            }
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(retry_after).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_RATE_LIMITED_PATHS",
    "DEFAULT_WINDOW_SECONDS",
    "AuthRateLimitMiddleware",
]
