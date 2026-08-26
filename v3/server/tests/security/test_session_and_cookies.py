"""Cookie flags, session fixation, and logout completeness (SPEC-502 #2).

The SPEC asks for three things in this area to be re-audited rather than
assumed. They are small properties with large consequences, so each gets its
own named test here even where a SPEC-203 test already touches it — this
module is the one place a reviewer can read the whole cookie and session
story at once.
"""

from __future__ import annotations

from http.cookies import SimpleCookie
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from palaia_hub.admin_session import CSRF_HEADER
from palaia_hub.app import create_app
from palaia_hub.config import DashboardSettings, HubConfig, OAuthSettings
from palaia_hub.oauth import AuthorizationServer, set_owner_password
from palaia_hub.oauth.login import CSRF_COOKIE, SESSION_COOKIE
from palaia_hub.vault import VaultRegistry

from .conftest import NOW, OWNER, PASSWORD, Hub, build_hub


def _set_cookies(response: object) -> dict[str, SimpleCookie[str]]:
    """Every ``Set-Cookie`` on a response, parsed, keyed by cookie name."""
    raw = [
        value
        for name, value in response.headers.multi_items()  # type: ignore[attr-defined]
        if name.lower() == "set-cookie"
    ]
    parsed: dict[str, SimpleCookie[str]] = {}
    for header in raw:
        jar: SimpleCookie[str] = SimpleCookie()
        jar.load(header)
        for key in jar:
            parsed[key] = jar
    return parsed


def _client(app: object, *, tls: bool = True) -> TestClient:
    """A test client whose scheme matches the hub's issuer.

    Not cosmetic: the hub marks its cookies ``Secure`` whenever its issuer is
    https, and an http client would then silently refuse to send them
    back — the sign-in would fail for the wrong reason and every assertion
    below would be about nothing.
    """
    return TestClient(app, base_url="https://testserver" if tls else "http://testserver")  # type: ignore[arg-type]


def _sign_in(client: TestClient) -> object:
    client.get("/oauth/login")
    return client.post(
        "/oauth/login",
        data={
            "username": OWNER,
            "password": PASSWORD,
            "csrf_token": client.cookies[CSRF_COOKIE],
            "next": "",
        },
        follow_redirects=False,
    )


# ------------------------------------------------------------ cookie flags


def test_the_session_cookie_is_httponly_lax_and_root_scoped(hub: Hub) -> None:
    with _client(hub.app) as client:
        response = _sign_in(client)

    jar = _set_cookies(response)[SESSION_COOKIE]
    morsel = jar[SESSION_COOKIE]
    assert morsel["httponly"], "the session cookie must be unreadable from script"
    assert morsel["samesite"].lower() == "lax"
    assert morsel["path"] == "/"


def test_the_csrf_cookie_is_readable_but_otherwise_identical(hub: Hub) -> None:
    """Deliberately *not* HttpOnly: the dashboard must echo it in a header.

    That is what makes it a double-submit token — proving the caller can both
    read a value from this origin and set a header, neither of which another
    site can do.
    """
    with _client(hub.app) as client:
        response = _sign_in(client)

    morsel = _set_cookies(response)[CSRF_COOKIE][CSRF_COOKIE]
    assert not morsel["httponly"]
    assert morsel["samesite"].lower() == "lax"
    assert morsel["path"] == "/"


def test_cookies_are_secure_when_the_hub_is_reached_over_tls(tmp_path: Path) -> None:
    built = build_hub(tmp_path)  # its issuer is https://…
    try:
        with _client(built.app) as client:
            response = _sign_in(client)
        for name in (SESSION_COOKIE, CSRF_COOKIE):
            assert _set_cookies(response)[name][name]["secure"], name
    finally:
        built.server.store.close()


def test_cookies_are_not_secure_on_a_plain_http_hub(tmp_path: Path) -> None:
    """A LAN hub must still be able to sign its operator in."""
    config = HubConfig(
        mode="locked",
        host="127.0.0.1",
        oauth=OAuthSettings(enabled=True, issuer="http://palaia.local:8420"),
        dashboard=DashboardSettings(require_sign_in=True),
    )
    server = AuthorizationServer.build(config, {"default": ["vault:work:read"]}, home=tmp_path)
    set_owner_password(server.store, OWNER, PASSWORD, now=NOW)
    app = create_app(
        config, home=tmp_path, oauth_server=server, vault_registry=VaultRegistry(tmp_path / "v")
    )
    try:
        with _client(app, tls=False) as client:
            response = _sign_in(client)
        assert not _set_cookies(response)[SESSION_COOKIE][SESSION_COOKIE]["secure"]
    finally:
        server.store.close()


# ------------------------------------------------------- session fixation


def test_the_server_mints_the_session_and_never_accepts_one(hub: Hub) -> None:
    """A value planted in the browser before sign-in must not survive it."""
    planted = "a-session-value-the-attacker-chose"
    with _client(hub.app) as client:
        client.cookies.set(SESSION_COOKIE, planted)
        response = _sign_in(client)

    issued = _set_cookies(response)[SESSION_COOKIE][SESSION_COOKIE].value
    assert issued != planted
    assert hub.server.store.get_login_session(planted, NOW) is None


def test_two_sign_ins_do_not_share_a_session(hub: Hub) -> None:
    with _client(hub.app) as client:
        first = _set_cookies(_sign_in(client))[SESSION_COOKIE][SESSION_COOKIE].value
    with _client(hub.app) as client:
        second = _set_cookies(_sign_in(client))[SESSION_COOKIE][SESSION_COOKIE].value

    assert first != second


def test_setting_the_owner_password_clears_every_live_session(hub: Hub) -> None:
    """Changing the password is the operator's "log everyone out" lever."""
    session = hub.session_cookie()
    assert hub.server.store.get_login_session(session, NOW) is not None

    set_owner_password(hub.server.store, OWNER, "another-long-passphrase", now=NOW)

    assert hub.server.store.get_login_session(session, NOW) is None


# ----------------------------------------------------- logout completeness


def test_signing_out_invalidates_the_session_server_side(hub: Hub) -> None:
    """Clearing the cookie is not enough — the row has to go."""
    with _client(hub.app) as client:
        session = _set_cookies(_sign_in(client))[SESSION_COOKIE][SESSION_COOKIE].value
        # The server's own clock, not the fixture's fixed NOW: this session
        # was minted by the real sign-in flow, so it lives on real time.
        assert hub.server.store.get_login_session(session, hub.server.now()) is not None

        response = client.post(
            "/oauth/logout", headers={CSRF_HEADER: client.cookies[CSRF_COOKIE]}
        )

    assert response.status_code == 204
    assert hub.server.store.get_login_session(session, hub.server.now()) is None


def test_signing_out_clears_both_cookies(hub: Hub) -> None:
    """A CSRF token left behind outlives the session it belonged to."""
    with _client(hub.app) as client:
        _sign_in(client)
        response = client.post(
            "/oauth/logout", headers={CSRF_HEADER: client.cookies[CSRF_COOKIE]}
        )

    cleared = _set_cookies(response)
    assert SESSION_COOKIE in cleared
    assert CSRF_COOKIE in cleared


def test_signing_out_from_another_site_is_refused(hub: Hub) -> None:
    """SPEC-502: `/oauth/logout` sits outside `/api/*`, so the session gate
    does not cover it — it carries its own double-submit token."""
    with _client(hub.app) as client:
        session = _set_cookies(_sign_in(client))[SESSION_COOKIE][SESSION_COOKIE].value

        response = client.post("/oauth/logout")  # no header: a cross-site form post

        assert response.status_code == 403
        assert "reload the page" in response.json()["detail"]
        assert hub.server.store.get_login_session(session, hub.server.now()) is not None


def test_a_wrong_token_cannot_sign_the_operator_out(hub: Hub) -> None:
    with _client(hub.app) as client:
        _sign_in(client)
        response = client.post("/oauth/logout", headers={CSRF_HEADER: "not-the-token"})

    assert response.status_code == 403


@pytest.mark.parametrize("path", ["/oauth/login", "/oauth/logout"])
def test_every_credential_response_forbids_caching(hub: Hub, path: str) -> None:
    with _client(hub.app) as client:
        _sign_in(client)
        response = (
            client.get(path)
            if path == "/oauth/login"
            else client.post(path, headers={CSRF_HEADER: client.cookies[CSRF_COOKIE]})
        )

    assert response.headers["cache-control"] == "no-store"
