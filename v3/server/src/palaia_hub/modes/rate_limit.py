"""Rate limiting for public auth endpoints (SPEC-205 deliverable #4).

Mounted by :func:`palaia_hub.app.create_app` only when ``config.mode`` is
``cloud`` or ``open`` — the modes where these endpoints are reachable off
the operator's own network at all; ``locked`` mode has no public attack
surface to throttle and stays exactly as before this module existed.

**Throttles failures, not volume.** A fixed-window counter per
``(client IP, bucket)`` that only counts a request *against* the limit when
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

**SPEC-502 closed two gaps in the above.**

1. *The admin surface was not covered.* SPEC-401 added an owner session in
   front of ``/api/*`` and noted that rate limiting was "SPEC-205's
   problem" — but SPEC-205's path list predates that gate and names none of
   it, and the gate itself was mounted *outside* this middleware, so its
   refusals never even passed through here to be counted. Guessing a
   session cookie was therefore unlimited. The admin surface is now one
   shared bucket per caller (:data:`ADMIN_BUCKET`) fed by every ``401``/
   ``403`` under ``/api/``, and ``create_app`` mounts this middleware
   *outside* the gate so it sees them. One bucket for the whole surface, not
   one per path: otherwise an attacker gets a fresh allowance for every
   route they walk.
2. *Every caller behind the container's nginx shared one bucket.* The peer
   address of a proxied request is loopback, so on the packaged image the
   per-IP key collapsed to ``127.0.0.1`` — no per-attacker limit, and one
   attacker locking out every other user. :func:`palaia_hub.security.
   client_ip.client_ip_for_scope` resolves the real caller where a local
   reverse proxy is in front, and only there.

The sign-in-free paths (``/api/health``, ``/api/info``) are never
throttled: the sign-in page itself reads them, and a locked-out operator
must still be able to see that their hub is alive.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from ..security.client_ip import client_ip_for_scope

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
        "/oauth/logout",
        "/api/auth/tokens",
    }
)

#: The prefix whose refusals share one bucket per caller (SPEC-502).
ADMIN_PREFIX = "/api/"

#: The bucket name those refusals are counted under. Not a path: the whole
#: admin surface shares it, so walking routes does not multiply the
#: allowance.
ADMIN_BUCKET = "admin-session"

#: Statuses that count as "this caller was refused by the admin gate".
#: A ``404`` or a ``422`` from a route the caller legitimately reached is
#: not an authentication failure and must not fill the bucket.
ADMIN_FAILURE_STATUSES: frozenset[int] = frozenset({401, 403})

#: Admin paths that are never throttled — see the module docstring. Kept
#: as a literal rather than imported from :mod:`palaia_hub.admin_session`
#: because importing that module here would make the gate and its limiter
#: mutually dependent; ``tests/modes/test_rate_limit.py`` asserts the two
#: sets agree.
ADMIN_FREE_PATHS: frozenset[str] = frozenset({"/api/health", "/api/info"})

#: Failed attempts allowed per ``(client IP, bucket)`` per window before a
#: 429 is returned *without* even reaching the real endpoint.
DEFAULT_LIMIT = 10
DEFAULT_WINDOW_SECONDS = 60.0


class AuthRateLimitMiddleware:
    """ASGI middleware: fixed-window limit on *failed* requests per bucket."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        paths: Iterable[str] = DEFAULT_RATE_LIMITED_PATHS,
        limit: int = DEFAULT_LIMIT,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        admin_prefix: str | None = ADMIN_PREFIX,
    ) -> None:
        """Args:
        app: the wrapped ASGI application.
        paths: exact paths whose ``>= 400`` responses are counted, each in
            its own bucket.
        limit: failures allowed per bucket per window.
        window_seconds: the fixed window's width.
        clock: monotonic time source, injectable for tests.
        admin_prefix: the prefix whose ``401``/``403`` responses share one
            bucket per caller. ``None`` disables that half entirely (what
            a hub with no admin gate wants).
        """
        self._app = app
        self._paths = frozenset(paths)
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._admin_prefix = admin_prefix
        self._failures: dict[tuple[str, str], list[float]] = {}

    def _bucket_for(self, path: str) -> str | None:
        """Which bucket ``path`` counts into, or ``None`` if it is untracked.

        The admin surface is checked *first*, so a path that is both under
        ``/api/`` and in the explicit list (``/api/auth/tokens``) joins the
        shared admin bucket rather than getting a second allowance of its
        own. With the admin half switched off, that same path falls through
        to its own bucket exactly as it did before SPEC-502.
        """
        if (
            self._admin_prefix is not None
            and path.startswith(self._admin_prefix)
            and path not in ADMIN_FREE_PATHS
        ):
            return ADMIN_BUCKET
        if path in self._paths:
            return path
        return None

    def _counts(self, bucket: str, status: int) -> bool:
        """Does a response with ``status`` count against ``bucket``?"""
        if bucket == ADMIN_BUCKET:
            return status in ADMIN_FAILURE_STATUSES
        return status >= 400

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        bucket = self._bucket_for(str(scope.get("path", "")))
        if bucket is None:
            await self._app(scope, receive, send)
            return

        client_ip = client_ip_for_scope(scope)
        now = self._clock()
        attempts = self._failures.setdefault((client_ip, bucket), [])
        cutoff = now - self._window
        while attempts and attempts[0] < cutoff:
            attempts.pop(0)

        if len(attempts) >= self._limit:
            retry_after = max(1, int(attempts[0] + self._window - now) + 1)
            await self._reject(send, retry_after)
            return

        status_holder: dict[str, int] = {}

        async def observing_send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        await self._app(scope, receive, observing_send)
        if self._counts(bucket, status_holder.get("status", 200)):
            attempts.append(now)

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
    "ADMIN_BUCKET",
    "ADMIN_FAILURE_STATUSES",
    "ADMIN_FREE_PATHS",
    "ADMIN_PREFIX",
    "DEFAULT_LIMIT",
    "DEFAULT_RATE_LIMITED_PATHS",
    "DEFAULT_WINDOW_SECONDS",
    "AuthRateLimitMiddleware",
]
