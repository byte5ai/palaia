"""The cookies a request carries, read straight from the ASGI scope.

The admin gate (:mod:`palaia_hub.admin_session`) reads the session and CSRF
cookies from it, and the failed-attempt limiter
(:mod:`palaia_hub.modes.rate_limit`) reads which session a refused request
presented (issue #593). Both are plain ASGI middlewares, so neither builds a
:class:`starlette.requests.Request` per request just to parse one header.
"""

from __future__ import annotations

from typing import Any

Scope = dict[str, Any]


def request_cookies(scope: Scope) -> dict[str, str]:
    """Parse the request's ``Cookie`` header into ``{name: value}``."""
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


__all__ = ["request_cookies"]
