"""Another site's page cannot change anything on this hub (issue #587).

The load-bearing test is again a **route walk**: it asks the hub the
installer sets up — Private, no dashboard sign-in, so no admin session gate
— for its own route table, and sends every state-changing ``/api/*`` route
what a page on another site can send through the owner's browser. Every one
must refuse, with the guard's own answer (``palaia_hub.security.cross_site``),
not a route's. The same walk runs with the gate on, and the dashboard's own
requests, clients that are not browsers, and the surfaces outside ``/api/``
(AI apps, sign-in pages, Telegram) must keep working.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from palaia_hub.admin_session import CSRF_HEADER, AdminSessionMiddleware, sign_in_required
from palaia_hub.config import load_config
from palaia_hub.oauth.login import CSRF_COOKIE, SESSION_COOKIE
from palaia_hub.security.cross_site import (
    CROSS_SITE_DETAIL,
    NOT_JSON_DETAIL,
    STATE_CHANGING_METHODS,
)
from palaia_hub.serve import ProductionApp, build_production_app

from .conftest import Hub, build_hub
from .test_threat_model_coverage import _walk

BASE_URL = "http://palaia.local:8420"
ELSEWHERE = "http://elsewhere.example"
CSRF_VALUE = "csrf-token-value"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def private_hub(tmp_path: Path) -> AsyncIterator[ProductionApp]:
    """The hub as installed: the real assembly, Private, no dashboard sign-in."""
    config = load_config(home=tmp_path)
    assert config.mode == "locked"
    assert not sign_in_required(config)
    production = await build_production_app(config, home=tmp_path)
    try:
        yield production
    finally:
        await production.dynamic_gateway.aclose()
        for attribute in ("stash_store", "directory_store", "messenger_store", "secret_store"):
            store = getattr(production, attribute)
            if store is not None:
                store.close()
        for index in production.indexes.values():
            await index.close()


@pytest.fixture
def signed_in_hub(tmp_path: Path) -> Iterator[Hub]:
    """Private with dashboard sign-in: the admin session gate runs."""
    built = build_hub(tmp_path, mode="locked", require_sign_in=True)
    try:
        yield built
    finally:
        built.server.store.close()


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL)


def _signed_in(client: httpx.AsyncClient, hub: Hub) -> dict[str, str]:
    """A live owner session and its CSRF token: what gets a request past the gate."""
    client.cookies.set(SESSION_COOKIE, hub.session_cookie())
    client.cookies.set(CSRF_COOKIE, CSRF_VALUE)
    return {CSRF_HEADER: CSRF_VALUE}


def _state_changing_routes(app: FastAPI) -> list[tuple[str, str]]:
    """Every ``(method, concrete path)`` under ``/api/`` that changes something."""
    pairs: list[tuple[str, str]] = []
    for route in _walk(app.routes):
        if not route.path.startswith("/api/"):
            continue
        path = re.sub(r"\{[^}]+\}", "placeholder", route.path)
        for method in sorted((route.methods or set()) & STATE_CHANGING_METHODS):
            pairs.append((method, path))
    return pairs


#: What a page on another site can send through the owner's browser without
#: asking first, and how the hub must answer. ``methods`` are the ones that
#: shape can arrive with: a browser sends ``PUT``/``PATCH``/``DELETE`` across
#: sites only after a CORS preflight, which this hub never grants, so the
#: content-type shapes are ``POST``-only in reality; ``PUT``/``PATCH`` are
#: held to the same rule, ``DELETE`` (sent with no body by the dashboard) is
#: not. The ``Sec-Fetch-Site`` shapes are refused for every method.
OTHER_SITE_SENDS = [
    pytest.param(
        {"POST", "PUT", "PATCH"},
        {"data": {"mode": "open"}},
        {"origin": ELSEWHERE},
        415,
        NOT_JSON_DETAIL,
        id="a form, on a plain-http hub",
    ),
    pytest.param(
        {"POST", "PUT", "PATCH"},
        {"files": {"upload": ("a.txt", b"x")}},
        {"origin": ELSEWHERE},
        415,
        NOT_JSON_DETAIL,
        id="a file-upload form",
    ),
    pytest.param(
        {"POST", "PUT", "PATCH"},
        {"content": b'{"mode": "open"}'},
        {"origin": ELSEWHERE, "content-type": "text/plain;charset=UTF-8"},
        415,
        NOT_JSON_DETAIL,
        id="fetch with a text body",
    ),
    pytest.param(
        {"POST", "PUT", "PATCH"},
        {"content": b'{"mode": "open"}'},
        {"origin": ELSEWHERE},
        415,
        NOT_JSON_DETAIL,
        id="fetch with a body of no type",
    ),
    pytest.param(
        {"POST", "PUT", "PATCH"},
        {},
        {"origin": ELSEWHERE},
        415,
        NOT_JSON_DETAIL,
        id="fetch with no body",
    ),
    pytest.param(
        STATE_CHANGING_METHODS,
        {"data": {"mode": "open"}},
        {"origin": ELSEWHERE, "sec-fetch-site": "cross-site"},
        403,
        CROSS_SITE_DETAIL,
        id="a form, on an https hub",
    ),
    pytest.param(
        STATE_CHANGING_METHODS,
        {"json": {}},
        {"origin": ELSEWHERE, "sec-fetch-site": "cross-site"},
        403,
        CROSS_SITE_DETAIL,
        id="JSON from another site",
    ),
    pytest.param(
        STATE_CHANGING_METHODS,
        {"json": {}},
        {"origin": "http://other.palaia.local", "sec-fetch-site": "same-site"},
        403,
        CROSS_SITE_DETAIL,
        id="JSON from a neighbouring host",
    ),
]


# ------------------------------------------------------------- the route walk


@pytest.mark.anyio
async def test_the_walk_covers_the_whole_surface_with_no_gate(private_hub: ProductionApp) -> None:
    """Guard the guard: the walk sees the routes the issue names, on a hub
    where nothing but this rule stands in the way."""
    app = private_hub.app
    assert not any(m.cls is AdminSessionMiddleware for m in app.user_middleware)
    routes = _state_changing_routes(app)
    assert len(routes) >= 50, routes
    for expected in (
        ("POST", "/api/notifications/read_all"),
        ("POST", "/api/gateway/upstreams/placeholder/probe"),
        ("POST", "/api/telegram/bots/placeholder/check"),
        ("POST", "/api/market/curated/refresh"),
        ("POST", "/api/hub/restart"),
        ("POST", "/api/auth/owner"),
        ("POST", "/api/mode"),
        ("PUT", "/api/secrets/placeholder"),
        ("DELETE", "/api/gateway/profiles/placeholder"),
    ):
        assert expected in routes, expected


@pytest.mark.anyio
@pytest.mark.parametrize(("methods", "kwargs", "headers", "status", "detail"), OTHER_SITE_SENDS)
async def test_every_change_refuses_another_sites_page_with_no_gate(
    private_hub: ProductionApp,
    methods: set[str],
    kwargs: dict[str, Any],
    headers: dict[str, str],
    status: int,
    detail: str,
) -> None:
    async with _client(private_hub.app) as client:
        for method, path in _state_changing_routes(private_hub.app):
            if method not in methods:
                continue
            response = await client.request(method, path, headers=headers, **kwargs)
            assert (response.status_code, response.json().get("detail")) == (status, detail), (
                f"{method} {path} answered {response.status_code}: {response.text[:200]}"
            )


@pytest.mark.anyio
@pytest.mark.parametrize(("methods", "kwargs", "headers", "status", "detail"), OTHER_SITE_SENDS)
async def test_every_change_refuses_another_sites_page_past_the_gate(
    signed_in_hub: Hub,
    methods: set[str],
    kwargs: dict[str, Any],
    headers: dict[str, str],
    status: int,
    detail: str,
) -> None:
    """The rule does not lean on the gate: even a request that carries the
    owner's session and token is refused when it is shaped like this."""
    async with _client(signed_in_hub.app) as client:
        token = _signed_in(client, signed_in_hub)
        routes = _state_changing_routes(signed_in_hub.app)
        assert len(routes) > 15, routes
        for method, path in routes:
            if method not in methods:
                continue
            response = await client.request(method, path, headers={**headers, **token}, **kwargs)
            assert (response.status_code, response.json().get("detail")) == (status, detail), (
                f"{method} {path} answered {response.status_code}: {response.text[:200]}"
            )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mode", "require_sign_in"),
    [("locked", None), ("locked", True), ("cloud", None), ("open", None)],
)
async def test_the_rule_holds_in_every_mode(
    tmp_path: Path, mode: str, require_sign_in: bool | None
) -> None:
    hub = build_hub(tmp_path, mode=mode, require_sign_in=require_sign_in)
    try:
        async with _client(hub.app) as client:
            token = _signed_in(client, hub)
            form = await client.post("/api/notifications/read_all", data={"x": "1"}, headers=token)
            cross_site = await client.post(
                "/api/notifications/read_all",
                json={},
                headers={**token, "sec-fetch-site": "cross-site"},
            )
            own = await client.post(
                "/api/notifications/read_all",
                json={},
                headers={**token, "sec-fetch-site": "same-origin"},
            )
    finally:
        hub.server.store.close()
    assert (form.status_code, form.json()["detail"]) == (415, NOT_JSON_DETAIL)
    assert (cross_site.status_code, cross_site.json()["detail"]) == (403, CROSS_SITE_DETAIL)
    assert own.status_code == 200, own.text


# --------------------------------------------------- what must keep working


@pytest.mark.anyio
@pytest.mark.parametrize("fetch_site", ["same-origin", "none"])
async def test_the_dashboards_own_requests_pass(
    private_hub: ProductionApp, monkeypatch: pytest.MonkeyPatch, fetch_site: str
) -> None:
    """As `web/src/lib/api/client.ts` sends them: JSON for every write
    (`{}` where the route takes no input), a bare `DELETE`."""
    monkeypatch.delenv("PALAIA_SELF_RESTART", raising=False)
    own = {"sec-fetch-site": fetch_site, "origin": BASE_URL, "accept": "application/json"}
    async with _client(private_hub.app) as client:
        read_all = await client.post("/api/notifications/read_all", json={}, headers=own)
        setup = await client.put("/api/setup", json={"goal": "private"}, headers=own)
        delete = await client.delete("/api/hooks/placeholder", headers=own)
        restart = await client.post("/api/hub/restart", json={}, headers=own)
    assert read_all.status_code == 200, read_all.text
    assert setup.status_code == 200, setup.text
    # The routes' own answers: the hook does not exist, and nothing would
    # start this hub again after a restart here.
    assert delete.status_code == 404, delete.text
    assert restart.status_code == 409, restart.text


@pytest.mark.anyio
async def test_a_client_that_is_not_a_browser_passes(private_hub: ProductionApp) -> None:
    """No `Sec-Fetch-Site`, JSON (with or without a charset), or a bare `DELETE`."""
    async with _client(private_hub.app) as client:
        plain = await client.post("/api/notifications/read_all", json={})
        charset = await client.post(
            "/api/notifications/read_all",
            content=b"{}",
            headers={"content-type": "Application/JSON; charset=utf-8"},
        )
        delete = await client.delete("/api/hooks/placeholder")
    assert plain.status_code == 200, plain.text
    assert charset.status_code == 200, charset.text
    assert delete.status_code == 404, delete.text


def _not_the_guard(response: httpx.Response) -> bool:
    return CROSS_SITE_DETAIL not in response.text and NOT_JSON_DETAIL not in response.text


@pytest.mark.anyio
async def test_ai_apps_and_telegram_are_not_held_to_it(private_hub: ProductionApp) -> None:
    """Outside `/api/`: an AI app's MCP request and a Telegram delivery reach
    their own routes, whatever a browser would have said about them."""
    other_site = {"origin": ELSEWHERE, "sec-fetch-site": "cross-site"}
    async with _client(private_hub.app) as client:
        mcp = await client.post(
            "/mcp/default/",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={**other_site, "accept": "application/json, text/event-stream"},
        )
        telegram = await client.post(
            "/telegram/webhook/placeholder", content=b"{}", headers=other_site
        )
    assert _not_the_guard(mcp), mcp.text
    assert (telegram.status_code, telegram.json()) == (404, {"detail": "no such Telegram webhook"})


@pytest.mark.anyio
async def test_the_sign_in_pages_still_take_their_forms(signed_in_hub: Hub) -> None:
    """`/oauth/*` posts forms by design — the sign-in page to itself, and an
    AI app's token request — and checks them itself."""
    async with _client(signed_in_hub.app) as client:
        login = await client.post(
            "/oauth/login",
            data={"username": "owner", "password": "wrong"},
            headers={"origin": BASE_URL, "sec-fetch-site": "same-origin"},
        )
        token = await client.post(
            "/oauth/token",
            data={"grant_type": "authorization_code", "code": "nope"},
            headers={"origin": ELSEWHERE, "sec-fetch-site": "cross-site"},
        )
    assert _not_the_guard(login), login.text
    assert login.status_code != 415
    assert _not_the_guard(token), token.text
    assert token.json()["error"] in {"invalid_request", "invalid_grant", "invalid_client"}
