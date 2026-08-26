"""The admin gate's refusals feed the failed-attempt limiter (SPEC-502 #2).

SPEC-401 left a note: the session gate was mounted *outside*
:class:`~palaia_hub.modes.rate_limit.AuthRateLimitMiddleware`, so guessing a
session cookie produced 401s that the limiter never saw and never counted.
This module is the closing of that note — and of the second half of it, the
per-caller key that collapsed to ``127.0.0.1`` behind the container's own
reverse proxy.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from palaia_hub.admin_session import SIGN_IN_FREE_PATHS
from palaia_hub.modes.rate_limit import (
    ADMIN_BUCKET,
    ADMIN_FREE_PATHS,
    AuthRateLimitMiddleware,
)
from palaia_hub.security.client_ip import client_ip_for_scope

from .conftest import build_hub

# ------------------------------------------- the gate, through the real app


def _tries(client: TestClient, path: str, count: int) -> list[int]:
    return [client.get(path).status_code for _ in range(count)]


def test_guessing_a_session_is_throttled_in_cloud_mode(tmp_path: Path) -> None:
    built = build_hub(tmp_path, mode="cloud")
    try:
        with TestClient(built.app) as client:
            statuses = _tries(client, "/api/vaults", 14)
    finally:
        built.server.store.close()

    assert statuses[:10] == [401] * 10, statuses
    assert set(statuses[10:]) == {429}, statuses


def test_the_whole_admin_surface_shares_one_bucket(tmp_path: Path) -> None:
    """Walking routes must not buy a fresh allowance per route."""
    built = build_hub(tmp_path, mode="cloud")
    paths = ["/api/vaults", "/api/mode", "/api/session", "/api/auth/tokens", "/api/hooks"]
    try:
        with TestClient(built.app) as client:
            statuses = [client.get(paths[i % len(paths)]).status_code for i in range(13)]
    finally:
        built.server.store.close()

    assert statuses[:10] == [401] * 10, statuses
    assert set(statuses[10:]) == {429}, statuses


def test_the_sign_in_free_paths_are_never_throttled(tmp_path: Path) -> None:
    """A locked-out operator must still be able to see the hub is alive, and
    the sign-in page itself reads both of these."""
    built = build_hub(tmp_path, mode="cloud")
    try:
        with TestClient(built.app) as client:
            for _ in range(12):
                client.get("/api/vaults")  # fill the bucket
            assert client.get("/api/health").status_code == 200
            assert client.get("/api/info").status_code == 200
    finally:
        built.server.store.close()


def test_the_two_free_lists_agree() -> None:
    """The limiter keeps its own copy of the list to avoid an import cycle;
    a copy that drifts is worse than no copy."""
    assert ADMIN_FREE_PATHS == SIGN_IN_FREE_PATHS


def test_locked_mode_has_no_limiter_at_all(tmp_path: Path) -> None:
    """SPEC-205's rule is unchanged: nothing to throttle on a private LAN."""
    built = build_hub(tmp_path, mode="locked", require_sign_in=True)
    try:
        with TestClient(built.app) as client:
            statuses = _tries(client, "/api/vaults", 14)
    finally:
        built.server.store.close()

    assert set(statuses) == {401}, statuses


def test_a_signed_in_operator_is_not_throttled_by_their_own_404s(tmp_path: Path) -> None:
    """Only 401/403 fill the admin bucket — a route answering 404 for a
    missing vault is the operator using the app, not an attack."""
    built = build_hub(tmp_path, mode="cloud")
    try:
        with TestClient(built.app) as client:
            client.cookies.set("palaia_oauth_session", built.session_cookie())
            statuses = [
                client.get("/api/vaults/nope/inbox_status").status_code for _ in range(14)
            ]
    finally:
        built.server.store.close()

    assert 429 not in statuses, statuses


# ---------------------------------------------- the middleware, in isolation


def _limited_app(status: int) -> FastAPI:
    app = FastAPI()

    @app.get("/api/thing")
    async def thing() -> JSONResponse:
        return JSONResponse({"ok": False}, status_code=status)

    return app


@pytest.mark.parametrize(("status", "throttled"), [(401, True), (403, True), (404, False)])
def test_only_auth_failures_fill_the_admin_bucket(status: int, throttled: bool) -> None:
    app = _limited_app(status)
    app.add_middleware(AuthRateLimitMiddleware, paths=set(), limit=2, window_seconds=60)
    client = TestClient(app)

    statuses = [client.get("/api/thing").status_code for _ in range(4)]

    assert (429 in statuses) is throttled, statuses


def test_the_admin_half_can_be_switched_off() -> None:
    """A hub with no session gate has no gate refusals to count."""
    app = _limited_app(401)
    app.add_middleware(
        AuthRateLimitMiddleware, paths=set(), limit=2, window_seconds=60, admin_prefix=None
    )
    client = TestClient(app)

    assert [client.get("/api/thing").status_code for _ in range(4)] == [401] * 4


def test_the_bucket_name_is_not_a_path() -> None:
    """Documented invariant: one bucket for the surface, not one per route."""
    assert not ADMIN_BUCKET.startswith("/")


# ------------------------------------------------------ the per-caller key


def _scope(peer: str, forwarded: str | None = None) -> dict[str, object]:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    return {"type": "http", "path": "/api/x", "client": (peer, 1234), "headers": headers}


def test_a_direct_caller_is_keyed_on_its_own_address() -> None:
    assert client_ip_for_scope(_scope("203.0.113.5")) == "203.0.113.5"


def test_a_direct_caller_cannot_forge_a_different_identity() -> None:
    """Off loopback the header is ignored entirely."""
    assert client_ip_for_scope(_scope("203.0.113.5", "9.9.9.9")) == "203.0.113.5"


def test_behind_a_local_proxy_the_real_caller_is_used() -> None:
    """nginx in the container image appends the peer it saw."""
    assert client_ip_for_scope(_scope("127.0.0.1", "198.51.100.7")) == "198.51.100.7"


def test_a_forged_prefix_cannot_escape_the_bucket() -> None:
    """``$proxy_add_x_forwarded_for`` appends, so the LAST entry is the
    trusted one — reading the first would read the attacker's own value."""
    scope = _scope("127.0.0.1", "1.2.3.4, 198.51.100.7")
    assert client_ip_for_scope(scope) == "198.51.100.7"


def test_a_loopback_peer_with_no_header_stays_loopback() -> None:
    assert client_ip_for_scope(_scope("127.0.0.1")) == "127.0.0.1"


def test_a_scope_with_no_client_is_still_keyed() -> None:
    assert client_ip_for_scope({"type": "http", "path": "/api/x", "headers": []}) == "unknown"
