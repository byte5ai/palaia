"""Issue #342: the wizard's owner-account step has a server side.

The docs promised an administrator sign-in as the first thing the wizard
asks for; the only way to create the account was `palaia oauth
set-password` in a terminal — the one thing the Synology guide's reader does
not have. `POST /api/auth/owner` creates the single owner account while none
exists, signs the creating browser in (the account's existence is what
closes the admin gate, so the wizard would otherwise bounce to the login
page mid-setup), and refuses everything after: a second attempt, and any
request a browser marks as coming from another site.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.auth.store import TokenStore
from palaia_hub.config import HubConfig, OAuthSettings
from palaia_hub.oauth import AuthorizationServer, OAuthStore
from palaia_hub.oauth import login as login_module
from palaia_hub.oauth.errors import OAuthError
from palaia_hub.oauth.login import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    LoginThrottle,
    set_owner_password,
    verify_owner_password,
)
from palaia_hub.oauth.owner_api import build_owner_router
from palaia_hub.vault import VaultRegistry

ISSUER = "https://hub.test"
PASSWORD = "a-long-enough-passphrase"  # noqa: S105 - test fixture


def _hub(home: Path, *, mode: str = "cloud") -> tuple[TestClient, AuthorizationServer]:
    config = HubConfig(
        mode=mode,  # type: ignore[arg-type]
        host="127.0.0.1",
        oauth=OAuthSettings(enabled=True, issuer=ISSUER),
    )
    server = AuthorizationServer.build(config, {"default": ["vault:work:read"]}, home=home)
    app = create_app(
        config,
        home=home,
        oauth_server=server,
        vault_registry=VaultRegistry(home / "vaults"),
        token_store=TokenStore(home=home),
    )
    return TestClient(app, base_url=ISSUER), server


def test_a_fresh_hub_reports_no_owner_and_the_wizard_creates_one(tmp_path: Path) -> None:
    client, server = _hub(tmp_path)
    try:
        with client:
            assert client.get("/api/auth/owner").json() == {"configured": False}

            created = client.post(
                "/api/auth/owner",
                json={"username": "ada", "password": PASSWORD},
                headers={"Sec-Fetch-Site": "same-origin"},
            )

            assert created.status_code == 201, created.text
            assert created.json() == {"configured": True}
            assert server.sign_in("ada", PASSWORD)[0], "the password the wizard set signs in"
            # The creating browser is signed in on the spot — both cookies of
            # the pair /oauth/login would have set.
            assert SESSION_COOKIE in client.cookies
            assert CSRF_COOKIE in client.cookies
            assert client.get("/api/auth/owner").json() == {"configured": True}
    finally:
        server.store.close()


def test_creating_the_owner_latches_the_gate_without_locking_the_wizard_out(
    tmp_path: Path,
) -> None:
    """In cloud mode the gate closes the moment an account exists. The
    browser that created it keeps working; a browser without the session
    is now refused — exactly the sequence the wizard runs through."""
    client, server = _hub(tmp_path, mode="cloud")
    try:
        with client:
            assert client.get("/api/vaults").status_code == 200  # open: no account yet
            created = client.post("/api/auth/owner", json={"username": "ada", "password": PASSWORD})
            assert created.status_code == 201, created.text

            # Same browser, next wizard step: still in.
            assert client.get("/api/vaults").status_code == 200

            # Somebody else's browser: the gate is closed now.
            other = TestClient(client.app, base_url=ISSUER)
            assert other.get("/api/vaults").status_code == 401
            assert other.get("/api/auth/owner").status_code == 401
    finally:
        server.store.close()


def test_the_owner_can_be_created_only_once(tmp_path: Path) -> None:
    client, server = _hub(tmp_path, mode="locked")
    try:
        with client:
            first = client.post("/api/auth/owner", json={"username": "ada", "password": PASSWORD})
            assert first.status_code == 201, first.text

            second = client.post(
                "/api/auth/owner", json={"username": "mallory", "password": "another-long-one!"}
            )

            assert second.status_code == 409
            assert "set-password" in second.json()["detail"]
            # The original account is untouched.
            assert server.sign_in("ada", PASSWORD)[0]
    finally:
        server.store.close()


def test_a_cross_site_request_cannot_plant_an_owner(tmp_path: Path) -> None:
    """A page on another site posting through the operator's browser: the
    browser labels it, and the hub refuses it. No account is created."""
    client, server = _hub(tmp_path, mode="locked")
    try:
        with client:
            planted = client.post(
                "/api/auth/owner",
                json={"username": "mallory", "password": PASSWORD},
                headers={"Sec-Fetch-Site": "cross-site"},
            )

            assert planted.status_code == 403
            assert server.store.get_owner() is None
            assert client.get("/api/auth/owner").json() == {"configured": False}
    finally:
        server.store.close()


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"username": "ada", "password": "short"}, "12 characters"),
        ({"username": "   ", "password": PASSWORD}, "username"),
    ],
)
def test_the_password_rules_are_the_same_as_the_terminal_command(
    tmp_path: Path, body: dict[str, str], fragment: str
) -> None:
    client, server = _hub(tmp_path, mode="locked")
    try:
        with client:
            response = client.post("/api/auth/owner", json=body)
            assert response.status_code == 400, response.text
            assert fragment in response.json()["detail"]
            assert server.store.get_owner() is None
    finally:
        server.store.close()


def test_without_a_sign_in_server_the_account_goes_straight_into_the_store(
    tmp_path: Path,
) -> None:
    """Issue #561: the wizard creates the account before cloud access turns
    the sign-in server on. Without a server there is no session to open —
    but the account is in the store the server reads once it starts, and the
    same 'only while none exists' rule holds."""
    config = HubConfig(mode="locked", host="127.0.0.1")
    app = create_app(config, home=tmp_path, vault_registry=VaultRegistry(tmp_path / "vaults"))
    with TestClient(app) as client:
        assert client.get("/api/auth/owner").json() == {"configured": False}
        created = client.post("/api/auth/owner", json={"username": "owner", "password": PASSWORD})
        assert created.status_code == 201, created.text
        assert "palaia_oauth_session" not in created.cookies
        assert client.get("/api/auth/owner").json() == {"configured": True}
        again = client.post("/api/auth/owner", json={"username": "x", "password": PASSWORD})
        assert again.status_code == 409
    store = OAuthStore(tmp_path)
    store.open()
    try:
        owner = store.get_owner()
        assert owner is not None and owner[0] == "owner"
    finally:
        store.close()


# --------------------------------------------------------------- issue #607
#
# The route used to check "no owner yet", then spend a password hash in a
# worker thread, then *replace* whatever owner the store held. Two first-run
# requests could both pass the check; both answered 201 and the later one
# silently replaced the other's account (and, with a sign-in server, its
# session). The barrier below holds both requests inside the hash — after
# the check, before the write — which is exactly that schedule.


def _race_two_owner_posts(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    barrier = threading.Barrier(2, timeout=10)
    real_hash = login_module.hash_password

    def hash_after_both_checked(password: str) -> str:
        barrier.wait()
        return real_hash(password)

    monkeypatch.setattr(login_module, "hash_password", hash_after_both_checked)

    async def race() -> list[tuple[str, int]]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=ISSUER) as client:

            async def post(username: str) -> tuple[str, int]:
                response = await client.post(
                    "/api/auth/owner",
                    json={"username": username, "password": PASSWORD + username},
                )
                return username, response.status_code

            return list(await asyncio.gather(post("first-owner"), post("second-owner")))

    return asyncio.run(race())


def _assert_exactly_one_owner_won(results: list[tuple[str, int]], store: OAuthStore) -> None:
    assert sorted(status for _, status in results) == [201, 409], results
    winner = next(name for name, status in results if status == 201)
    loser = next(name for name, status in results if status == 409)
    owner = store.get_owner()
    assert owner is not None and owner[0] == winner, "the losing request replaced the winner"
    signed_in = verify_owner_password(store, winner, PASSWORD + winner, throttle=LoginThrottle())
    assert signed_in == winner
    with pytest.raises(OAuthError):
        verify_owner_password(store, loser, PASSWORD + loser, throttle=LoginThrottle())


def test_two_concurrent_first_owner_requests_create_exactly_one_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = FastAPI()
    app.include_router(build_owner_router(None, home=tmp_path))

    results = _race_two_owner_posts(app, monkeypatch)

    store = OAuthStore(tmp_path)
    store.open()
    try:
        _assert_exactly_one_owner_won(results, store)
    finally:
        store.close()


def test_with_a_sign_in_server_the_race_also_leaves_the_winner_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = HubConfig(
        mode="cloud", host="127.0.0.1", oauth=OAuthSettings(enabled=True, issuer=ISSUER)
    )
    server = AuthorizationServer.build(config, {"default": ["vault:work:read"]}, home=tmp_path)
    app = FastAPI()
    app.include_router(build_owner_router(server))
    try:
        results = _race_two_owner_posts(app, monkeypatch)
        _assert_exactly_one_owner_won(results, server.store)
    finally:
        server.store.close()


def test_the_terminal_command_still_replaces_an_existing_owner(tmp_path: Path) -> None:
    """Deliberate replacement stays possible where the hub runs — only the
    open first-run route is create-if-absent."""
    store = OAuthStore(tmp_path)
    store.open()
    try:
        set_owner_password(store, "ada", PASSWORD, now=1)
        set_owner_password(store, "grace", PASSWORD + "-new", now=2)
        owner = store.get_owner()
        assert owner is not None and owner[0] == "grace"
    finally:
        store.close()


def test_the_store_refuses_a_second_first_owner(tmp_path: Path) -> None:
    store = OAuthStore(tmp_path)
    store.open()
    try:
        assert store.create_owner("ada", "hash-a", 1) is True
        assert store.create_owner("mallory", "hash-m", 2) is False
        assert store.get_owner() == ("ada", "hash-a")
    finally:
        store.close()
