"""Issue #342: the wizard's owner-account step has a server side.

The docs promised an administrator sign-in as the first thing the wizard
asks for; the only way to create the account was `palaia-hub oauth
set-password` in a terminal — the one thing the Synology guide's reader does
not have. `POST /api/auth/owner` creates the single owner account while none
exists, signs the creating browser in (the account's existence is what
closes the admin gate, so the wizard would otherwise bounce to the login
page mid-setup), and refuses everything after: a second attempt, and any
request a browser marks as coming from another site.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.auth.store import TokenStore
from palaia_hub.config import HubConfig, OAuthSettings
from palaia_hub.oauth import AuthorizationServer
from palaia_hub.oauth.login import CSRF_COOKIE, SESSION_COOKIE
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


def test_the_route_is_absent_on_a_hub_with_no_sign_in_server(tmp_path: Path) -> None:
    """No authorization server, nothing to create an account for: the
    wizard's step reads the 404 as 'nothing to set up here'."""
    config = HubConfig(mode="locked", host="127.0.0.1")
    app = create_app(config, home=tmp_path, vault_registry=VaultRegistry(tmp_path / "vaults"))
    with TestClient(app) as client:
        assert client.get("/api/auth/owner").status_code == 404
        assert (
            client.post("/api/auth/owner", json={"username": "a", "password": PASSWORD}).status_code
            == 404
        )
