"""Security headers for every browser-facing response (SPEC-502 deliverable #2).

**What this covers, and what it deliberately does not.** The hub answers
three kinds of request: the dashboard's own pages and assets, the
authorization server's HTML pages (sign-in, the "cannot continue" page), and
machine surfaces (``/api/*`` JSON, ``/mcp/*`` MCP traffic). A browser only
ever *renders* the first two, so those are the ones that get a content
security policy. The machine surfaces still get the cheap, always-correct
headers — ``X-Content-Type-Options`` in particular, because a JSON error
body sniffed as HTML is a genuine reflected-content problem — plus a policy
that forbids everything, since nothing under those prefixes is meant to be
rendered at all.

**Two policies, because they are two different pages.**

* :data:`OAUTH_PAGE_CSP` covers the sign-in form and the authorization
  error page. Those are server-rendered HTML with one inline ``<style>``
  block and *no script at all*, so the policy can be maximal: no scripts, no
  frames, no connections, no images beyond ``data:``. Anything injected into
  one of those pages therefore cannot execute, cannot phone home, and cannot
  be framed by an attacker's page.
* :data:`DASHBOARD_CSP` covers the built single-page app. Vite emits the
  app as external ``<script type="module">`` and ``<link rel=stylesheet>``
  files from the same origin, so ``script-src 'self'`` needs no ``unsafe-
  inline``. Two carve-outs are real and are stated rather than hidden:
  ``style-src`` allows ``'unsafe-inline'`` (React inline ``style=`` props
  and the theme switcher set element styles directly), and ``img-src``
  allows ``data:`` and ``blob:`` (icons and the skill-download blob URLs in
  ``SkillPanel``). ``connect-src 'self'`` keeps every fetch and the
  ``EventSource`` stream on this origin.

**HSTS.** Sent only when the request actually arrived over TLS, which the
hub learns from ``X-Forwarded-Proto`` behind its reverse proxy or from the
ASGI scheme when it terminates TLS itself. Sending it on a plain-HTTP LAN
hub would be worse than useless — a browser that pinned
``http://palaia.local`` to HTTPS could not reach it at all — which is
exactly why the tunnel/exposure documentation (``v3/docs/exposure.md``)
covers it as an exposure-time concern rather than a default.

**Frames.** ``frame-ancestors 'none'`` (plus the legacy
``X-Frame-Options: DENY``) on the browser surfaces. The MCP Apps
(:mod:`palaia_hub.gateway.apps`) *are* framed — by the AI client that hosts
them — but they are served over the MCP transport as resource content, not
as an HTTP page from this app, so they are unaffected by this middleware and
carry their own ``<meta>`` policy instead.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

#: Policy for the built dashboard (see the module docstring for each
#: directive's justification).
DASHBOARD_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "frame-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'"
)

#: Policy for the authorization server's own HTML pages: no script, no
#: network, no framing.
OAUTH_PAGE_CSP = (
    "default-src 'none'; "
    "style-src 'unsafe-inline'; "
    "img-src data:; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'"
)

#: Policy for surfaces nothing should ever render: the REST API and the MCP
#: mounts. Everything is denied; the header exists so a response that is
#: somehow opened in a browser tab is inert.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"

#: One year, and the hub asks to be preloaded only via the operator's own
#: decision — see the exposure docs. Subdomains are included because a
#: palaia deployment owns its whole hostname.
HSTS_VALUE = "max-age=31536000; includeSubDomains"

#: Prefixes whose responses are never rendered by a browser.
_MACHINE_PREFIXES = ("/api/", "/mcp/", "/.well-known/")
_MACHINE_EXACT = ("/api", "/mcp")

#: The authorization server's HTML surface.
_OAUTH_PREFIX = "/oauth"


def policy_for_path(path: str) -> str:
    """Which content security policy a response for ``path`` carries."""
    if path.startswith(_OAUTH_PREFIX):
        return OAUTH_PAGE_CSP
    if path in _MACHINE_EXACT or path.startswith(_MACHINE_PREFIXES):
        return API_CSP
    return DASHBOARD_CSP


def _request_is_secure(scope: Scope) -> bool:
    """Did this request reach the hub over TLS?

    ``X-Forwarded-Proto`` wins when present, because in every packaged
    deployment the hub itself speaks plain HTTP on loopback and a proxy
    (nginx in the container image, a tunnel daemon in ``cloud``/``open``
    mode) terminates TLS in front of it. The header is only ever read to
    decide whether to *add* a hardening header, so a forged value can make a
    response stricter, never laxer.
    """
    headers: list[tuple[bytes, bytes]] = list(scope.get("headers", []))
    for name, value in headers:
        if name == b"x-forwarded-proto":
            return value.decode("latin-1").split(",")[0].strip().lower() == "https"
    return str(scope.get("scheme", "http")).lower() == "https"


class SecurityHeadersMiddleware:
    """Add the browser-hardening headers to every HTTP response.

    A plain ASGI middleware rather than a ``BaseHTTPMiddleware`` subclass:
    it must also cover the streaming event endpoint and the mounted MCP
    apps, and ``BaseHTTPMiddleware`` buffers those.

    Headers already set by a handler are left alone — the MCP transport sets
    its own cache and content-type headers, and the authorization server
    sets ``Cache-Control: no-store`` on everything it serves.
    """

    def __init__(self, app: ASGIApp, *, hsts: bool = True) -> None:
        """Args:
        app: the wrapped ASGI application.
        hsts: whether to send ``Strict-Transport-Security`` on requests
            that arrived over TLS. Left on; a hub that is *not* served
            over TLS never triggers it anyway.
        """
        self._app = app
        self._hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        csp = policy_for_path(path)
        secure = self._hsts and _request_is_secure(scope)

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                present = {name.lower() for name, _value in headers}
                additions: list[tuple[bytes, bytes]] = [
                    (b"content-security-policy", csp.encode("latin-1")),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                ]
                if secure:
                    additions.append(
                        (b"strict-transport-security", HSTS_VALUE.encode("latin-1"))
                    )
                headers.extend(
                    (name, value) for name, value in additions if name not in present
                )
                message = {**message, "headers": headers}
            await send(message)

        await self._app(scope, receive, send_with_headers)


__all__ = [
    "API_CSP",
    "DASHBOARD_CSP",
    "HSTS_VALUE",
    "OAUTH_PAGE_CSP",
    "SecurityHeadersMiddleware",
    "policy_for_path",
]
