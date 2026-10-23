"""Refuse changes another site's page could make through a browser (issue #587).

Every state-changing call under ``/api/*`` (``POST``, ``PUT``, ``PATCH``,
``DELETE``) passes one rule, in every mode — also where no admin session gate
runs, as in ``locked`` mode without dashboard sign-in, where a page on any
website, opened in a browser on the owner's network, could otherwise reach
those routes with a plain form post.

**What another site's page can send without asking.** A browser sends a
cross-site request without a CORS preflight only for ``GET``/``HEAD``/``POST``
with a ``Content-Type`` that is absent or one of
``application/x-www-form-urlencoded``, ``multipart/form-data`` and
``text/plain`` — a ``<form>``, or ``fetch`` in ``no-cors`` mode. Anything else
(``PUT``/``PATCH``/``DELETE``, or a JSON body) needs a preflight, and this hub
never grants one: it sends no CORS headers at all. So:

* ``POST``, ``PUT`` and ``PATCH`` must say ``Content-Type: application/json``
  (415 otherwise), with or without a body. That is what the dashboard sends
  (``web/src/lib/api/client.ts``: every write is a JSON ``fetch``, and a write
  that takes no input sends ``{}``) and what an API client sends anyway.
  ``DELETE`` is exempt: the dashboard sends it with no body, and no browser
  sends a cross-site ``DELETE`` without the preflight.
* A ``Sec-Fetch-Site`` other than ``same-origin`` or ``none`` (typed or
  bookmarked) is refused (403) for every method. Browsers send this header
  only over https, so on a plain-http hub on the owner's network the
  content-type rule is what holds; over https both do. ``same-site`` is
  refused too: another app on a neighbouring host is still another site.

A client that is not a browser sends no ``Sec-Fetch-Site`` and is unaffected
as long as it sends JSON. ``/mcp`` (AI apps, with their own tokens),
``/oauth`` (the sign-in pages post forms to themselves) and
``/telegram/webhook`` (Telegram's secret header) are outside ``/api/`` and
never looked at.

No ``Origin``/``Host`` comparison: a reverse proxy that rewrites ``Host``
would break the dashboard's own requests (the reasoning of issue #586's
restart check, which this rule replaces).

The admin session gate (:mod:`palaia_hub.admin_session`), where it runs,
adds its double-submit CSRF token on top; this rule does not depend on it.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

#: The prefix this rule covers: the dashboard's admin API.
GUARDED_PREFIX = "/api/"

#: Methods that change something.
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Methods whose request must say it is JSON. ``DELETE`` is not one: see the
#: module docstring.
JSON_METHODS = frozenset({"POST", "PUT", "PATCH"})

#: ``Sec-Fetch-Site`` values a browser sends for this hub's own pages
#: (``same-origin``) or for an address typed or bookmarked (``none``).
OWN_FETCH_SITES = frozenset({"same-origin", "none"})

#: The answer to a request a browser marked as coming from another site.
CROSS_SITE_DETAIL = (
    "This change came from another website. palaia accepts changes only from its own dashboard."
)

#: The answer to a write that is not JSON.
NOT_JSON_DETAIL = (
    "This change must be sent as JSON, as palaia's dashboard sends it. "
    "Fix: send it with the header Content-Type: application/json."
)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or ():
        if key == name:
            return str(value.decode("latin-1"))
    return None


def refusal(scope: Scope) -> tuple[int, str] | None:
    """Why this request must be refused, as ``(status, detail)``, or ``None``."""
    if scope.get("type") != "http":
        return None
    if not str(scope.get("path", "")).startswith(GUARDED_PREFIX):
        return None
    method = str(scope.get("method", "GET")).upper()
    if method not in STATE_CHANGING_METHODS:
        return None
    fetch_site = _header(scope, b"sec-fetch-site")
    if fetch_site is not None and fetch_site.strip().lower() not in OWN_FETCH_SITES:
        return 403, CROSS_SITE_DETAIL
    if method in JSON_METHODS:
        content_type = (_header(scope, b"content-type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            return 415, NOT_JSON_DETAIL
    return None


class CrossSiteRequestGuard:
    """Apply :func:`refusal` to every request; pass everything else through."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        refused = refusal(scope)
        if refused is None:
            await self.app(scope, receive, send)
            return
        status, detail = refused
        body = json.dumps({"detail": detail}).encode("utf-8")
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


__all__ = [
    "CROSS_SITE_DETAIL",
    "GUARDED_PREFIX",
    "JSON_METHODS",
    "NOT_JSON_DETAIL",
    "OWN_FETCH_SITES",
    "STATE_CHANGING_METHODS",
    "CrossSiteRequestGuard",
    "refusal",
]
