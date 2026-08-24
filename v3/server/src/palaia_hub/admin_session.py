"""The admin session gate for the dashboard's own surface (SPEC-401).

The masterplan's mode table (§5.5) makes sign-in mandatory before the admin
dashboard may be reachable from anywhere but the operator's own network. This
module is that gate: one ASGI middleware in front of ``/api/*``.

**One door, reused.** There is no dashboard account: the session this
middleware looks for is the *same* ``palaia_oauth_session`` cookie SPEC-203's
password login and SPEC-204's identity-provider login already mint — password
or provider, whichever the hub is configured for. A second cookie for the
same identity would be a second door, and MASTERPLAN §5.5 is explicit that
two doors into the same room mean the weaker one decides how strong the room
is.

**What is gated, and what deliberately is not.**

* ``/api/*`` — everything except :data:`SIGN_IN_FREE_PATHS`. That includes
  the live event stream: ``/api/events`` carries vault activity, note titles
  and mode changes, which is exactly the material a session is supposed to
  protect. It excludes ``/api/health`` and ``/api/info`` (a liveness probe
  and the non-secret "how do I sign in here" answer the sign-in page itself
  needs), and nothing else.
* ``/oauth/*`` — the authorization server's own surface, including the
  sign-in page and the provider callback. Gating the door on already being
  through the door is a lock-out, not a defense.
* ``/mcp/*`` — MCP clients authenticate with their own bearer/OAuth access
  tokens (SPEC-108/203), verified inside the gateway. A browser session has
  no business there and this middleware never looks at it.
* The dashboard's static build. The HTML shell is not a secret; every byte
  of *data* it renders comes from ``/api/*``, which is gated. Serving the
  shell to an unauthenticated browser is what lets it show a sign-in prompt
  instead of a blank page.

**CSRF.** The session cookie is ``SameSite=Lax``, which already stops a
cross-site *form* POST from carrying it — but not every browser in every
version, and not a same-site-but-untrusted page. So state-changing methods
under ``/api/*`` additionally require the double-submit token the login flow
sets (:data:`~palaia_hub.oauth.login.CSRF_COOKIE`), echoed in the
``X-Palaia-CSRF`` header. A header cannot be set by a plain cross-origin form
post at all, and the value cannot be read cross-origin, so the pair is
unforgeable from another site. ``GET``/``HEAD``/``OPTIONS`` stay
CSRF-free — they change nothing, and ``EventSource`` cannot send headers.

**When it is on** (:func:`sign_in_required`, MASTERPLAN §5.5's mode table):

* ``open`` — mandatory. The dashboard is on the public internet in this mode;
  there is no configuration that turns the gate off.
* ``cloud`` — on by default. The dashboard is VPN/tailnet-only there
  (enforced by :class:`~palaia_hub.config.HubConfig`'s private-bind rule), so
  this is defense in depth against whatever else reaches that network; an
  operator can turn it off with ``dashboard.require_sign_in: false``.
* ``locked`` — off by default, opt-in via ``dashboard.require_sign_in: true``.
  A LAN hub must keep its zero-config first run: the wizard has to be
  reachable before any account exists, or the hub is a brick out of the box.

And, in every mode, **only once a way in exists** — an owner account or a
configured identity provider (:func:`sign_in_configured`). Enforcing before
that would lock the operator out of the very wizard that creates the account,
which is why the check is made per request against the live store rather than
once at startup: the wizard's first step creates the owner, and the gate
closes behind it on the next call.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path
from secrets import compare_digest
from typing import TYPE_CHECKING, Any

from .oauth.keys import OAUTH_DIR_NAME
from .oauth.login import CSRF_COOKIE, SESSION_COOKIE
from .oauth.store import DATABASE_FILE

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .config import HubConfig
    from .oauth import AuthorizationServer

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

#: The header the dashboard echoes its CSRF cookie in. Named, not guessed:
#: :mod:`palaia_hub.oauth.routes` sets the cookie and ``web/src/lib/api/
#: client.ts`` sends the header, and both read the name from their own side
#: of this contract.
CSRF_HEADER = "x-palaia-csrf"

#: HTTP methods that change nothing and therefore need no CSRF token.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: The prefix this gate covers. ``/mcp`` and ``/oauth`` are deliberately
#: absent — see the module docstring.
GUARDED_PREFIX = "/api/"

#: Paths under :data:`GUARDED_PREFIX` that must work with no session at all:
#: a liveness probe, and the non-secret "how does the owner sign in here"
#: answer the sign-in page itself reads. Nothing else — in particular not
#: ``/api/events``, which streams vault activity.
SIGN_IN_FREE_PATHS: frozenset[str] = frozenset({"/api/health", "/api/info"})

#: Where the "sign in first" answer points a browser when the hub has no
#: identity provider configured (the local password form, SPEC-203).
PASSWORD_SIGN_IN_PATH = "/oauth/login"
#: ...and when it has one (SPEC-204's one-door rule: there is no password
#: form to offer in that case).
IDP_SIGN_IN_PATH = "/oauth/idp/start"


def owner_account_exists(home: Path) -> bool:
    """Does a local owner account exist under ``home``?

    A read-only probe of the authorization server's own SQLite file, opened
    ``mode=ro`` so this can never create the database, the directory, or a
    journal as a side effect. Every failure mode — no file yet, no table yet,
    an unreadable file — answers ``False``: "we cannot prove a way in
    exists", which is the safe answer for both callers (a refusal to start in
    ``open`` mode, and a gate that stays open so the wizard is reachable).
    """
    database = Path(home) / OAUTH_DIR_NAME / DATABASE_FILE
    if not database.is_file():
        return False
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        row = connection.execute("SELECT 1 FROM owner_account LIMIT 1").fetchone()
    except sqlite3.Error:
        return False
    finally:
        connection.close()
    return row is not None


def sign_in_configured(config: HubConfig, home: Path) -> bool:
    """Is there a working way for the owner to sign in to this hub?

    Three things have to be true together, and each of them is a real
    lock-out if it is missing:

    * the authorization server is enabled (``oauth.enabled``) — it is what
      serves the sign-in page, the provider callback and the session cookie.
      An owner password with no server to present it to is not a door;
    * an ``oauth.issuer`` is set, since every URL that flow redirects
      through is derived from it;
    * and either an identity provider is configured (SPEC-204) or an owner
      account exists (SPEC-203).
    """
    if not config.oauth.enabled or not config.oauth.issuer:
        return False
    if config.oauth.idp is not None:
        return True
    return owner_account_exists(home)


def sign_in_available(oauth_server: AuthorizationServer, config: HubConfig) -> bool:
    """The same question as :func:`sign_in_configured`, asked of a live server.

    Preferred wherever an :class:`~palaia_hub.oauth.service.
    AuthorizationServer` is at hand (the middleware): it answers from the
    store the running hub actually signs people in against, rather than from
    a path that a caller could have resolved differently.
    :func:`sign_in_configured` exists for the one caller that has no server —
    :func:`palaia_hub.config.load_config`, which runs before anything is
    built.
    """
    if not config.oauth.enabled or not config.oauth.issuer:
        return False
    if oauth_server.idp_configured:
        return True
    return oauth_server.store.get_owner() is not None


def sign_in_required(config: HubConfig) -> bool:
    """Is the admin session gate active for ``config``'s mode?

    MASTERPLAN §5.5's mode table, plus the ``dashboard.require_sign_in``
    override — see this module's docstring for why each mode defaults the way
    it does. ``open`` ignores the override entirely (and
    :class:`~palaia_hub.config.HubConfig` refuses a config that tries to set
    it to ``false`` there, so this is belt and braces rather than a silent
    ignore).
    """
    if config.mode == "open":
        return True
    override = config.dashboard.require_sign_in
    if override is not None:
        return override
    return config.mode == "cloud"


class AdminSessionMiddleware:
    """Require an owner session (and a CSRF token) on the admin surface."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        current_user: Callable[[str | None], str | None],
        sign_in_configured: Callable[[], bool],
        sign_in_url: str = PASSWORD_SIGN_IN_PATH,
        free_paths: frozenset[str] = SIGN_IN_FREE_PATHS,
    ) -> None:
        """Wire the gate.

        Args:
            current_user: resolves a session cookie value to the owner's
                username, or ``None``. In production this is
                :meth:`palaia_hub.oauth.service.AuthorizationServer.
                current_user`; injectable so this middleware can be tested
                without a store.
            sign_in_configured: whether a way in exists *right now* — called
                per gated request, because the first-run wizard creates the
                owner account mid-process and the gate must close behind it
                without a restart. Latched once it answers ``True``: the one
                call that can remove the owner account
                (:meth:`~palaia_hub.oauth.store.OAuthStore.set_owner`)
                replaces it in the same statement, so "configured" is a
                one-way transition and re-asking would only cost a query per
                request forever.
            sign_in_url: where a browser is sent to sign in — the password
                form, or the provider start when one is configured.
        """
        self._app = app
        self._current_user = current_user
        self._sign_in_configured = sign_in_configured
        self._configured_latch = False
        self._sign_in_url = sign_in_url
        self._free_paths = free_paths

    def _configured(self) -> bool:
        if self._configured_latch:
            return True
        self._configured_latch = bool(self._sign_in_configured())
        return self._configured_latch

    def _resolve(self, session: str | None) -> tuple[bool, str | None]:
        """``(gate_open, username)`` — both store reads, on one worker thread.

        ``gate_open`` means "this hub has no way in yet, let the request
        through"; it is never combined with a username, since the session
        lookup is skipped entirely in that case.
        """
        if not self._configured():
            return True, None
        return False, self._current_user(session)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        if not path.startswith(GUARDED_PREFIX) or path in self._free_paths:
            await self._app(scope, receive, send)
            return
        cookies = _parse_cookies(scope)
        # One worker-thread hop for both store reads (is there a way in, and
        # is this session live). SQLite statements are blocking and the
        # store's lock is shared with the token endpoint, so running them
        # inline would serialize the event loop behind them — the same
        # discipline `palaia_hub.oauth.routes` states for its own handlers.
        gate_open, username = await asyncio.to_thread(
            self._resolve, cookies.get(SESSION_COOKIE)
        )
        if gate_open:
            # No account and no provider yet: the first-run wizard has to be
            # reachable or the hub is a brick out of the box.
            await self._app(scope, receive, send)
            return
        if username is None:
            await self._deny(
                send,
                status=401,
                detail=(
                    "Please sign in to continue. This page needs the owner to be "
                    "signed in on this device."
                ),
            )
            return

        method = str(scope.get("method", "GET")).upper()
        if method not in SAFE_METHODS and not _csrf_ok(scope, cookies):
            await self._deny(
                send,
                status=403,
                detail=(
                    "This request could not be confirmed as coming from the "
                    "dashboard. Please reload the page and try again."
                ),
            )
            return

        await self._app(scope, receive, send)

    async def _deny(self, send: Send, *, status: int, detail: str) -> None:
        body = json.dumps({"detail": detail, "sign_in_url": self._sign_in_url}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _parse_cookies(scope: Scope) -> dict[str, str]:
    """Parse the request's ``Cookie`` header.

    Hand-rolled rather than via :class:`starlette.requests.Request` so the
    middleware stays a plain ASGI callable with no per-request object
    allocation, same shape as :mod:`palaia_hub.modes.rate_limit`.
    """
    raw = b""
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            raw = value
            break
    if not raw:
        return {}
    cookies: dict[str, str] = {}
    for part in raw.decode("latin-1").split(";"):
        name, sep, value = part.partition("=")
        if not sep:
            continue
        cookies[name.strip()] = value.strip()
    return cookies


def _csrf_ok(scope: Scope, cookies: dict[str, str]) -> bool:
    """Double-submit check: the header must equal the cookie, both non-empty."""
    header = ""
    for name, value in scope.get("headers", []):
        if name.decode("latin-1").lower() == CSRF_HEADER:
            header = value.decode("latin-1")
            break
    cookie = cookies.get(CSRF_COOKIE, "")
    if not header or not cookie:
        return False
    return compare_digest(header, cookie)


def sign_in_url_for(oauth_server: AuthorizationServer) -> str:
    """The one door into this hub: the provider start, or the password form.

    SPEC-204's one-door rule (MASTERPLAN §5.5) is why this is a choice and
    not a list: with a provider configured there is no password form to
    offer, and the password form's route is not even registered.
    """
    return IDP_SIGN_IN_PATH if oauth_server.idp_configured else PASSWORD_SIGN_IN_PATH


def build_admin_session_middleware_kwargs(
    oauth_server: AuthorizationServer, config: HubConfig
) -> dict[str, Any]:
    """The keyword arguments :func:`palaia_hub.app.create_app` passes in.

    Kept here rather than inline in ``app.py`` so the whole policy — which
    door to point at, and how "is there a way in" is answered — reads in one
    place next to the middleware that applies it.
    """
    return {
        "current_user": oauth_server.current_user,
        "sign_in_configured": lambda: sign_in_available(oauth_server, config),
        "sign_in_url": sign_in_url_for(oauth_server),
    }


__all__ = [
    "CSRF_HEADER",
    "GUARDED_PREFIX",
    "IDP_SIGN_IN_PATH",
    "PASSWORD_SIGN_IN_PATH",
    "SAFE_METHODS",
    "SIGN_IN_FREE_PATHS",
    "AdminSessionMiddleware",
    "build_admin_session_middleware_kwargs",
    "owner_account_exists",
    "sign_in_available",
    "sign_in_configured",
    "sign_in_url_for",
    "sign_in_required",
]
