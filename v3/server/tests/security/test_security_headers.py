"""Security headers on every browser-facing response (SPEC-502 #2).

The acceptance criterion is "security headers present on dashboard + OAuth
responses". These tests read the headers off the *assembled app*, not off the
middleware in isolation, because the thing that can regress is the wiring:
a middleware that exists but is added in the wrong place, or one that a
mounted sub-application shadows.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from palaia_hub.security.headers import (
    API_CSP,
    DASHBOARD_CSP,
    HSTS_VALUE,
    OAUTH_PAGE_CSP,
    SecurityHeadersMiddleware,
    policy_for_path,
)

from .conftest import Hub, build_hub

#: Headers that must be on every response, whatever it is.
ALWAYS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cross-origin-opener-policy": "same-origin",
}


def _assert_baseline(headers: dict[str, str], path: str) -> None:
    for name, value in ALWAYS.items():
        assert headers.get(name) == value, f"{path}: {name} was {headers.get(name)!r}"
    assert headers.get("content-security-policy") == policy_for_path(path), path


# ----------------------------------------------------- the assembled app


def test_the_oauth_sign_in_page_carries_its_own_policy(hub: Hub) -> None:
    with TestClient(hub.app) as client:
        response = client.get("/oauth/login")

    assert response.status_code == 200
    _assert_baseline({k.lower(): v for k, v in response.headers.items()}, "/oauth/login")
    assert response.headers["content-security-policy"] == OAUTH_PAGE_CSP
    # The sign-in page renders no script at all, so the policy can forbid
    # every source outright — that is what makes injected markup inert.
    assert "script-src" not in OAUTH_PAGE_CSP
    assert OAUTH_PAGE_CSP.startswith("default-src 'none'")


def test_an_api_response_carries_the_deny_everything_policy(hub: Hub) -> None:
    with TestClient(hub.app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    _assert_baseline({k.lower(): v for k, v in response.headers.items()}, "/api/health")
    assert response.headers["content-security-policy"] == API_CSP


def test_a_refused_request_still_carries_the_headers(hub: Hub) -> None:
    """The responses an attacker sees most are the ones the gate generates."""
    with TestClient(hub.app) as client:
        response = client.get("/api/vaults")

    assert response.status_code == 401
    _assert_baseline({k.lower(): v for k, v in response.headers.items()}, "/api/vaults")


def test_the_dashboard_shell_gets_the_spa_policy(tmp_path: Path) -> None:
    """A hub with a built dashboard serves it under the SPA policy.

    Stands in for a real ``npm run build`` output: what is asserted is the
    policy chosen for a non-API, non-OAuth path, which is exactly the
    decision :func:`policy_for_path` makes for every dashboard route.
    """
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>palaia</title>", encoding="utf-8")
    built = build_hub(tmp_path / "home", mode="locked")
    try:
        from palaia_hub.static import mount_dashboard

        mount_dashboard(built.app, dist)
        with TestClient(built.app) as client:
            response = client.get("/explorer/some-note")
        assert response.status_code == 200
        _assert_baseline(
            {k.lower(): v for k, v in response.headers.items()}, "/explorer/some-note"
        )
        assert response.headers["content-security-policy"] == DASHBOARD_CSP
    finally:
        built.server.store.close()


# ------------------------------------------------------------------ HSTS


def test_hsts_is_absent_on_a_plain_http_request(hub: Hub) -> None:
    """A LAN hub pinned to HTTPS by its own header would be unreachable."""
    with TestClient(hub.app) as client:
        response = client.get("/api/health")

    assert "strict-transport-security" not in {k.lower() for k in response.headers}


def test_hsts_appears_when_a_proxy_reports_tls(hub: Hub) -> None:
    with TestClient(hub.app) as client:
        response = client.get("/api/health", headers={"X-Forwarded-Proto": "https"})

    assert response.headers["strict-transport-security"] == HSTS_VALUE


# --------------------------------------------------- the middleware itself


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/", DASHBOARD_CSP),
        ("/explorer", DASHBOARD_CSP),
        ("/oauth/login", OAUTH_PAGE_CSP),
        ("/oauth/idp/start", OAUTH_PAGE_CSP),
        ("/api/health", API_CSP),
        ("/api", API_CSP),
        ("/mcp/default/", API_CSP),
        ("/.well-known/oauth-authorization-server", API_CSP),
    ],
)
def test_the_policy_chosen_per_path(path: str, expected: str) -> None:
    assert policy_for_path(path) == expected


def test_a_handler_that_sets_its_own_header_wins() -> None:
    """The middleware adds; it never overwrites a deliberate value."""
    import asyncio
    from typing import Any

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def inner(scope: dict[str, Any], receive: Any, send_: Any) -> None:
        await send_(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"referrer-policy", b"origin")],
            }
        )
        await send_({"type": "http.response.body", "body": b""})

    async def receive() -> dict[str, Any]:  # pragma: no cover - never called
        return {"type": "http.request"}

    middleware = SecurityHeadersMiddleware(inner)
    asyncio.run(
        middleware({"type": "http", "path": "/", "headers": [], "scheme": "http"}, receive, send)
    )

    headers = dict(sent[0]["headers"])
    assert headers[b"referrer-policy"] == b"origin"
    assert headers[b"x-content-type-options"] == b"nosniff"
