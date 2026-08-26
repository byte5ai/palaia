"""Drive a mounted MCP profile over real HTTP semantics, no real socket.

Builds an ``httpx.AsyncClient`` on ``httpx.ASGITransport`` so a
``fastmcp.Client`` speaks the actual streamable-HTTP wire protocol —
including FastMCP's ``RequireAuthMiddleware``/``BearerAuthBackend`` auth
layer — against an in-process ASGI app. This is what lets the SPEC-108
tests exercise real 401s and real bearer-token handling without spawning a
subprocess/socket (contrast ``tests/gateway/test_e2e_claude_code.py``,
which does spawn one, for a different acceptance criterion).
"""

from __future__ import annotations

from typing import Any

import httpx
from fastmcp.client.transports import StreamableHttpTransport
from starlette.types import ASGIApp


def mcp_client_transport(
    app: ASGIApp, url: str, *, token: str | None = None
) -> StreamableHttpTransport:
    """A ``StreamableHttpTransport`` for ``fastmcp.Client`` bound to ``app``.

    ``url`` should be the full path the app expects (e.g.
    ``"http://testserver/mcp/default/"``); no real DNS/socket is used —
    ``ASGITransport`` dispatches directly into ``app``.
    """

    def factory(
        *,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
        **_: Any,
    ) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "transport": httpx.ASGITransport(app=app),
            "follow_redirects": True,
        }
        if headers is not None:
            kwargs["headers"] = headers
        if timeout is not None:
            kwargs["timeout"] = timeout
        if auth is not None:
            kwargs["auth"] = auth
        return httpx.AsyncClient(**kwargs)

    return StreamableHttpTransport(url=url, auth=token, httpx_client_factory=factory)
