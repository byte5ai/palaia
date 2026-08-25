"""The admin session gate (SPEC-401): who may call ``/api/*``, and how.

The load-bearing test here is the **route walk**: it asks the assembled app
for its own route table and requires every non-allowlisted ``/api/*`` route
to refuse an unauthenticated caller. That is deliberately not a list of
paths — a list would go stale the day someone adds a route, which is exactly
the accident this SPEC exists to make impossible.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Route

from palaia_hub.admin_session import (
    CSRF_HEADER,
    SIGN_IN_FREE_PATHS,
    sign_in_required,
)
from palaia_hub.app import create_app
from palaia_hub.auth.store import TokenStore
from palaia_hub.config import DashboardSettings, HubConfig, OAuthSettings
from palaia_hub.hooks import HookOutbox, HookStore
from palaia_hub.notifications import NotificationStore
from palaia_hub.oauth import AuthorizationServer, set_owner_password
from palaia_hub.oauth.login import CSRF_COOKIE, SESSION_COOKIE
from palaia_hub.vault import VaultRegistry

ISSUER = "https://hub.example.test"
OWNER = "owner"
PASSWORD = "a-long-enough-passphrase"  # noqa: S105 - test fixture
NOW = 1_800_000_000

#: The one gated route that must not be *called* with a live session in a
#: test: it is an endless server-sent-event stream, so a request with a
#: session never returns. Its unauthenticated half (a 401) is exercised by
#: the walk like every other route, and by its own test below.
STREAMING_PATHS = frozenset({"/api/events"})


@dataclass
class Hub:
    app: FastAPI
    server: AuthorizationServer
    home: Path

    def session_cookie(self) -> str:
        session, _expires = self.server.store.create_login_session(
            OWNER, now=NOW, ttl=self.server.settings.session_ttl
        )
        return session


def _build_hub(
    home: Path,
    *,
    mode: str = "cloud",
    require_sign_in: bool | None = None,
    with_owner: bool = True,
    with_oauth_server: bool = True,
) -> Hub:
    """A hub with a wide REST surface, so the route walk has something to walk."""
    config = HubConfig(
        mode=mode,  # type: ignore[arg-type]
        host="127.0.0.1",
        oauth=OAuthSettings(enabled=True, issuer=ISSUER),
        dashboard=DashboardSettings(require_sign_in=require_sign_in),
    )
    server = AuthorizationServer.build(config, {"default": ["vault:work:read"]}, home=home)
    if with_owner:
        set_owner_password(server.store, OWNER, PASSWORD, now=NOW)
    hook_store = HookStore(home)
    app = create_app(
        config,
        home=home,
        oauth_server=server if with_oauth_server else None,
        vault_registry=VaultRegistry(home / "vaults"),
        token_store=TokenStore(home=home),
        hook_store=hook_store,
        hook_outbox=HookOutbox(home / "hook-outbox.sqlite3"),
        notification_store=NotificationStore(home / "notifications.sqlite3"),
    )
    return Hub(app=app, server=server, home=home)


@pytest.fixture
def hub(tmp_path: Path) -> Iterator[Hub]:
    built = _build_hub(tmp_path)
    try:
        yield built
    finally:
        built.server.store.close()


def _api_routes(app: FastAPI) -> list[tuple[str, str]]:
    """Every ``(method, concrete path)`` under ``/api/`` this app really serves.

    Path parameters are filled with a harmless placeholder — the point is to
    reach the *route*, and a 404 from a missing vault is as good an answer as
    a 200, as long as it is not a 401.
    """
    pairs: list[tuple[str, str]] = []
    for route in _walk(app.routes):
        if not route.path.startswith("/api/"):
            continue
        path = route.path
        for name in route.param_convertors:
            path = path.replace(f"{{{name}}}", "placeholder")
        for method in sorted(route.methods or set()):
            if method in ("HEAD", "OPTIONS"):
                continue
            pairs.append((method, path))
    return pairs


def _walk(routes: Iterable[Any]) -> Iterator[Route]:
    """Flatten the app's route list, following included routers.

    This FastAPI version keeps an included router as one opaque entry
    (``_IncludedRouter``) holding the real router rather than splicing its
    routes into ``app.routes``, so a walk that only looked at the top level
    would silently cover a handful of routes and pass — see
    ``test_the_walk_actually_covers_the_surface``, which exists to catch
    exactly that.
    """
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            yield from _walk(original.routes)
        elif isinstance(route, Route):
            yield route


def _call(client: TestClient, method: str, path: str, **kwargs: Any) -> Any:
    return client.request(method, path, **kwargs)


# ------------------------------------------------------- the route walk (#1)


def test_the_walk_actually_covers_the_surface(hub: Hub) -> None:
    """Guard the guard: a walk over an empty route table proves nothing."""
    routes = _api_routes(hub.app)
    assert len(routes) > 20, routes
    paths = {path for _method, path in routes}
    for expected in ("/api/vaults", "/api/auth/tokens", "/api/mode", "/api/session"):
        assert expected in paths


def test_every_gated_route_refuses_a_caller_with_no_session(hub: Hub) -> None:
    with TestClient(hub.app) as client:
        for method, path in _api_routes(hub.app):
            if path in SIGN_IN_FREE_PATHS:
                continue
            response = _call(client, method, path)
            assert response.status_code == 401, f"{method} {path} answered {response.status_code}"
            assert response.json()["sign_in_url"] == "/oauth/login"


def test_every_gated_route_answers_a_signed_in_caller(hub: Hub) -> None:
    """"Works with one": the gate is what changed, not the route's own answer,
    so this asserts only that nothing is refused for lack of a session."""
    with TestClient(hub.app) as client:
        client.cookies.set(SESSION_COOKIE, hub.session_cookie())
        client.cookies.set(CSRF_COOKIE, "csrf-token-value")
        for method, path in _api_routes(hub.app):
            if path in STREAMING_PATHS:
                continue
            response = _call(client, method, path, headers={CSRF_HEADER: "csrf-token-value"})
            assert response.status_code not in (401, 403), (
                f"{method} {path} answered {response.status_code}: {response.text[:200]}"
            )


def test_the_allowlist_works_with_no_session(hub: Hub) -> None:
    with TestClient(hub.app) as client:
        assert client.get("/api/health").status_code == 200
        info = client.get("/api/info")
        assert info.status_code == 200
        assert info.json()["sign_in"]["required"] is True


def test_the_event_stream_needs_a_session(hub: Hub) -> None:
    """It carries vault activity, so it is gated like any other route."""
    with TestClient(hub.app) as client:
        assert client.get("/api/events").status_code == 401


# --------------------------------------------------------------- CSRF (#3)


def test_a_state_changing_call_without_the_header_is_refused(hub: Hub) -> None:
    with TestClient(hub.app) as client:
        client.cookies.set(SESSION_COOKIE, hub.session_cookie())
        client.cookies.set(CSRF_COOKIE, "csrf-token-value")
        response = client.post("/api/vaults", json={"key": "work"})
    assert response.status_code == 403
    assert "reload the page" in response.json()["detail"]


def test_a_state_changing_call_with_a_wrong_header_is_refused(hub: Hub) -> None:
    with TestClient(hub.app) as client:
        client.cookies.set(SESSION_COOKIE, hub.session_cookie())
        client.cookies.set(CSRF_COOKIE, "csrf-token-value")
        response = client.post(
            "/api/vaults", json={"key": "work"}, headers={CSRF_HEADER: "not-the-token"}
        )
    assert response.status_code == 403


def test_a_state_changing_call_with_no_csrf_cookie_at_all_is_refused(hub: Hub) -> None:
    """A session minted before this token existed cannot be waved through."""
    with TestClient(hub.app) as client:
        client.cookies.set(SESSION_COOKIE, hub.session_cookie())
        response = client.post(
            "/api/vaults", json={"key": "work"}, headers={CSRF_HEADER: "csrf-token-value"}
        )
    assert response.status_code == 403


def test_a_matching_pair_is_accepted(hub: Hub) -> None:
    with TestClient(hub.app) as client:
        client.cookies.set(SESSION_COOKIE, hub.session_cookie())
        client.cookies.set(CSRF_COOKIE, "csrf-token-value")
        response = client.post(
            "/api/vaults",
            json={"key": "work"},
            headers={CSRF_HEADER: "csrf-token-value"},
        )
    assert response.status_code == 200, response.text


def test_reads_need_no_csrf_token(hub: Hub) -> None:
    with TestClient(hub.app) as client:
        client.cookies.set(SESSION_COOKIE, hub.session_cookie())
        assert client.get("/api/vaults").status_code == 200


# ------------------------------------------------------- mode policy (#4)


@pytest.mark.parametrize(
    ("mode", "override", "expected"),
    [
        ("open", None, True),
        ("open", True, True),
        ("cloud", None, True),
        ("cloud", False, False),
        ("cloud", True, True),
        ("locked", None, False),
        ("locked", True, True),
        ("locked", False, False),
    ],
)
def test_per_mode_policy(mode: str, override: bool | None, expected: bool) -> None:
    config = HubConfig(
        mode=mode,  # type: ignore[arg-type]
        host="127.0.0.1",
        auth_enabled=True,
        dashboard=DashboardSettings(require_sign_in=override),
    )
    assert sign_in_required(config) is expected


def test_locked_mode_leaves_the_surface_open_by_default(tmp_path: Path) -> None:
    """SPEC-110's zero-config first run: the wizard is reachable with no session."""
    built = _build_hub(tmp_path, mode="locked")
    try:
        with TestClient(built.app) as client:
            assert client.get("/api/vaults").status_code == 200
            created = client.post("/api/vaults", json={"key": "work"})
            assert created.status_code == 200, created.text
    finally:
        built.server.store.close()


def test_locked_mode_can_opt_in(tmp_path: Path) -> None:
    built = _build_hub(tmp_path, mode="locked", require_sign_in=True)
    try:
        with TestClient(built.app) as client:
            assert client.get("/api/vaults").status_code == 401
    finally:
        built.server.store.close()


def test_the_gate_stays_open_until_an_account_exists(tmp_path: Path) -> None:
    """The first-run wizard has to be reachable before there is any way in —
    and the gate closes on the next call once the account is created."""
    built = _build_hub(tmp_path, mode="cloud", with_owner=False)
    try:
        with TestClient(built.app) as client:
            assert client.get("/api/vaults").status_code == 200

            set_owner_password(built.server.store, OWNER, PASSWORD, now=NOW)

            assert client.get("/api/vaults").status_code == 401
    finally:
        built.server.store.close()


def test_no_gate_without_a_sign_in_server_at_all(tmp_path: Path) -> None:
    """A hub with no authorization server has no session to require — and
    enforcing would lock the operator out with nothing to unlock it."""
    built = _build_hub(tmp_path, mode="cloud", with_oauth_server=False)
    try:
        with TestClient(built.app) as client:
            assert client.get("/api/vaults").status_code == 200
            assert client.get("/api/info").json()["sign_in"]["required"] is False
    finally:
        built.server.store.close()


# ------------------------------------------------------- session UX (#6)


def test_the_session_route_names_who_is_signed_in(hub: Hub) -> None:
    with TestClient(hub.app) as client:
        client.cookies.set(SESSION_COOKIE, hub.session_cookie())
        body = client.get("/api/session").json()
    assert body["signed_in"] is True
    assert body["username"] == OWNER
    assert body["required"] is True
    assert body["sign_in_url"] == "/oauth/login"
    assert body["session_ttl_seconds"] == 12 * 3600


def test_an_expired_session_is_refused_like_no_session(hub: Hub) -> None:
    """Deliverable #6's "handles expiry mid-use": the answer is the ordinary
    401 with the sign-in address, which is what the dashboard's API client
    turns into one redirect."""
    # Minted in 2020 with a one-second life: expired by any real clock.
    session, _expires = hub.server.store.create_login_session(OWNER, now=1_600_000_000, ttl=1)
    with TestClient(hub.app) as client:
        client.cookies.set(SESSION_COOKIE, session)
        response = client.get("/api/vaults")
    assert response.status_code == 401
    assert response.json()["sign_in_url"] == "/oauth/login"


def test_mcp_endpoints_are_not_touched(hub: Hub) -> None:
    """The gate covers `/api/*` only: MCP clients carry their own tokens."""
    with TestClient(hub.app) as client:
        response = client.post("/mcp/default", json={})
    # No gateway is mounted on this hub, so 404 — the assertion that matters
    # is that the answer did not come from the session gate.
    assert response.status_code != 401
    assert "sign_in_url" not in response.text


# --------------------------------------------- open mode, end to end (#3)


def test_open_mode_public_bind_sign_in_and_one_admin_call(tmp_path: Path) -> None:
    """The whole point of SPEC-401, in one test: a hub bound the way a public
    one is, an owner signing in through the real form, and an admin call that
    works afterwards and did not before.

    Driven through the real ASGI stack (the same middleware, the real login
    form, real cookies) rather than a socket — every layer this SPEC touches
    is in the path; only the transport is in-process.
    """
    config = HubConfig(
        mode="open",
        host="0.0.0.0",  # noqa: S104 - a public bind is what `open` mode means
        auth_enabled=True,
        oauth=OAuthSettings(enabled=True, issuer="http://testserver"),
    )
    server = AuthorizationServer.build(config, {"default": ["vault:work:read"]}, home=tmp_path)
    set_owner_password(server.store, OWNER, PASSWORD, now=NOW)
    app = create_app(
        config,
        home=tmp_path,
        oauth_server=server,
        vault_registry=VaultRegistry(tmp_path / "vaults"),
    )
    try:
        with TestClient(app, base_url="http://testserver") as client:
            # Before signing in: refused, and told where to go.
            refused = client.get("/api/vaults")
            assert refused.status_code == 401
            assert refused.json()["sign_in_url"] == "/oauth/login"

            form = client.get("/oauth/login")
            assert form.status_code == 200
            token = form.text.split('name="csrf_token" value="')[1].split('"')[0]
            signed_in = client.post(
                "/oauth/login",
                data={
                    "username": OWNER,
                    "password": PASSWORD,
                    "csrf_token": token,
                    "next": "/explorer",
                },
                follow_redirects=False,
            )
            assert signed_in.status_code == 303
            # Deliverable #2/#6: the dashboard page the operator came from is
            # where they land, not a generic home screen.
            assert signed_in.headers["location"] == "/explorer"

            # And the sign-in flow left the dashboard the CSRF token it needs
            # — readable by script on purpose (deliverable #3).
            csrf = client.cookies[CSRF_COOKIE]
            assert csrf
            assert client.get("/api/vaults").status_code == 200
            created = client.post(
                "/api/vaults", json={"key": "work"}, headers={CSRF_HEADER: csrf}
            )
            assert created.status_code == 200, created.text

            # Signing out closes the door again.
            assert client.post("/oauth/logout").status_code == 204
            assert client.get("/api/vaults").status_code == 401
    finally:
        server.store.close()


def test_a_guarded_websocket_scope_is_closed_not_passed_through() -> None:
    """The gate fails closed for every scope type: a websocket handshake
    under /api/* is refused (4401) even though no such route exists today —
    so the first one added later cannot ship unguarded by construction."""
    import asyncio

    from palaia_hub.admin_session import AdminSessionMiddleware

    inner_called = False

    async def inner(scope, receive, send):  # type: ignore[no-untyped-def]
        nonlocal inner_called
        inner_called = True

    sent: list[dict] = []

    async def send(message):  # type: ignore[no-untyped-def]
        sent.append(message)

    async def receive():  # type: ignore[no-untyped-def]
        return {"type": "websocket.connect"}

    middleware = AdminSessionMiddleware(
        inner,
        current_user=lambda session: None,
        sign_in_configured=lambda: True,
    )
    scope = {"type": "websocket", "path": "/api/events", "headers": []}
    asyncio.run(middleware(scope, receive, send))

    assert not inner_called
    assert sent == [{"type": "websocket.close", "code": 4401}]
