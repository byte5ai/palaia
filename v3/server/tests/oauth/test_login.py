"""The local owner account: password rules, CSRF, throttling, open redirects.

This is the only door into the authorization server in this SPEC (IdPs are
SPEC-204), so each of its defenses gets a test rather than a comment.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from palaia_hub.oauth import LoginThrottle, OAuthError, OAuthStore, set_owner_password
from palaia_hub.oauth.login import (
    MAX_FAILED_ATTEMPTS,
    verify_owner_password,
)
from palaia_hub.oauth.pkce import challenge_for

from .harness import (
    CIMD_CLIENT_ID,
    CIMD_REDIRECT_URI,
    OWNER_PASSWORD,
    OWNER_USERNAME,
    Harness,
    build_harness,
)

BASE_URL = "https://testserver"
NOW = 1_800_000_000


def _http(harness: Harness) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app),
        base_url=BASE_URL,
        follow_redirects=False,
    )


# ---------------------------------------------------------------- unit level


def test_the_password_has_a_length_floor(store: OAuthStore) -> None:
    with pytest.raises(OAuthError, match="12 characters"):
        set_owner_password(store, "owner", "short", now=NOW)


def test_setting_a_password_clears_existing_sessions(store: OAuthStore) -> None:
    set_owner_password(store, "owner", "a-long-enough-passphrase", now=NOW)
    session, _expiry = store.create_login_session("owner", now=NOW, ttl=3600)
    assert store.get_login_session(session, NOW) == "owner"

    set_owner_password(store, "owner", "a-different-long-passphrase", now=NOW + 1)

    assert store.get_login_session(session, NOW + 1) is None


def test_only_one_owner_account_can_exist(store: OAuthStore) -> None:
    set_owner_password(store, "first", "a-long-enough-passphrase", now=NOW)
    set_owner_password(store, "second", "another-long-passphrase", now=NOW + 1)

    owner = store.get_owner()
    assert owner is not None and owner[0] == "second"


def test_an_expired_session_is_not_accepted(store: OAuthStore) -> None:
    set_owner_password(store, "owner", "a-long-enough-passphrase", now=NOW)
    session, expiry = store.create_login_session("owner", now=NOW, ttl=60)

    assert store.get_login_session(session, expiry - 1) == "owner"
    assert store.get_login_session(session, expiry) is None


def test_a_wrong_username_and_a_wrong_password_fail_identically(
    store: OAuthStore,
) -> None:
    set_owner_password(store, "owner", "a-long-enough-passphrase", now=NOW)
    throttle = LoginThrottle()

    messages = []
    for username, password in (("nobody", "whatever"), ("owner", "wrong-password")):
        with pytest.raises(OAuthError) as excinfo:
            verify_owner_password(store, username, password, throttle=throttle)
        messages.append((excinfo.value.error, excinfo.value.description))

    assert messages[0] == messages[1]


def test_a_hub_with_no_owner_account_fails_the_same_way(store: OAuthStore) -> None:
    with pytest.raises(OAuthError) as excinfo:
        verify_owner_password(store, "owner", "anything", throttle=LoginThrottle())

    assert excinfo.value.error == "access_denied"


def test_repeated_failures_lock_the_account_then_release_it(store: OAuthStore) -> None:
    set_owner_password(store, "owner", "a-long-enough-passphrase", now=NOW)
    fake_time = [1000.0]
    throttle = LoginThrottle(max_failures=3, lockout_seconds=60, clock=lambda: fake_time[0])

    for _ in range(3):
        with pytest.raises(OAuthError):
            verify_owner_password(store, "owner", "wrong", throttle=throttle)

    # Locked: even the correct password is refused, with 429 rather than 401.
    with pytest.raises(OAuthError) as excinfo:
        verify_owner_password(store, "owner", OWNER_PASSWORD, throttle=throttle)
    assert excinfo.value.status_code == 429

    fake_time[0] += 61
    assert (
        verify_owner_password(store, "owner", "a-long-enough-passphrase", throttle=throttle)
        == "owner"
    )


def test_the_default_lockout_threshold_is_what_the_module_documents() -> None:
    assert LoginThrottle().max_failures == MAX_FAILED_ATTEMPTS


def test_a_successful_sign_in_clears_the_failure_counter(store: OAuthStore) -> None:
    set_owner_password(store, "owner", "a-long-enough-passphrase", now=NOW)
    throttle = LoginThrottle(max_failures=3, lockout_seconds=60)

    for _ in range(2):
        with pytest.raises(OAuthError):
            verify_owner_password(store, "owner", "wrong", throttle=throttle)
    verify_owner_password(store, "owner", "a-long-enough-passphrase", throttle=throttle)

    # Two more failures must not trip the (reset) counter.
    for _ in range(2):
        with pytest.raises(OAuthError) as excinfo:
            verify_owner_password(store, "owner", "wrong", throttle=throttle)
        assert excinfo.value.status_code == 401


# ---------------------------------------------------------------- HTTP level


@pytest.mark.anyio
async def test_a_post_without_the_csrf_token_is_refused(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            await http.get("/oauth/login")
            response = await http.post(
                "/oauth/login",
                data={"username": OWNER_USERNAME, "password": OWNER_PASSWORD, "next": ""},
            )

    assert response.status_code == 401
    assert "expired" in response.text


@pytest.mark.anyio
async def test_a_post_with_a_forged_csrf_token_is_refused(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            await http.get("/oauth/login")
            response = await http.post(
                "/oauth/login",
                data={
                    "username": OWNER_USERNAME,
                    "password": OWNER_PASSWORD,
                    "csrf_token": "attacker-chosen-value",
                    "next": "",
                },
            )

    assert response.status_code == 401
    assert "palaia_oauth_session" not in response.cookies


@pytest.mark.anyio
async def test_the_session_cookie_is_httponly_samesite_lax_and_secure(
    harness: Harness,
) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            await http.get("/oauth/login")
            response = await http.post(
                "/oauth/login",
                data={
                    "username": OWNER_USERNAME,
                    "password": OWNER_PASSWORD,
                    "csrf_token": http.cookies["palaia_oauth_csrf"],
                    "next": "",
                },
            )

    header = response.headers["set-cookie"]
    assert "palaia_oauth_session=" in header
    assert "HttpOnly" in header
    assert "SameSite=lax" in header.replace("samesite", "SameSite")
    assert "Secure" in header
    assert "Path=/" in header


@pytest.mark.anyio
async def test_the_cookie_is_not_marked_secure_on_a_plain_http_issuer(
    tmp_path: Path,
) -> None:
    """A localhost-only deployment would otherwise never receive its cookie."""
    from palaia_hub.config import OAuthSettings

    plain = build_harness(
        tmp_path,
        mode="locked",
        settings=OAuthSettings(
            enabled=True, issuer="http://127.0.0.1:8420", profiles=["alpha", "beta"]
        ),
    )
    try:
        async with plain.app.router.lifespan_context(plain.app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=plain.app),
                base_url="http://127.0.0.1:8420",
                follow_redirects=False,
            ) as http:
                await http.get("/oauth/login")
                response = await http.post(
                    "/oauth/login",
                    data={
                        "username": OWNER_USERNAME,
                        "password": OWNER_PASSWORD,
                        "csrf_token": http.cookies["palaia_oauth_csrf"],
                        "next": "",
                    },
                )
    finally:
        plain.store.close()

    assert response.status_code == 303
    assert "Secure" not in response.headers["set-cookie"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "next_url",
    [
        "https://evil.test/steal",
        "//evil.test/steal",
        "/api/health",
        "/oauth/logout",
    ],
)
async def test_an_unsafe_next_url_is_ignored(harness: Harness, next_url: str) -> None:
    """``next`` is attacker-controllable, so only /oauth/authorize is honored."""
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            await http.get("/oauth/login")
            response = await http.post(
                "/oauth/login",
                data={
                    "username": OWNER_USERNAME,
                    "password": OWNER_PASSWORD,
                    "csrf_token": http.cookies["palaia_oauth_csrf"],
                    "next": next_url,
                },
            )

    assert response.status_code == 303
    assert response.headers["location"] == "/"


@pytest.mark.anyio
async def test_a_safe_next_url_carries_the_operator_back_to_authorize(
    harness: Harness,
) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            first = await http.get(
                "/oauth/authorize",
                params={
                    "response_type": "code",
                    "client_id": CIMD_CLIENT_ID,
                    "redirect_uri": CIMD_REDIRECT_URI,
                    "code_challenge": challenge_for("a" * 43),
                    "code_challenge_method": "S256",
                    "resource": harness.audience("alpha"),
                },
            )
            login_url = first.headers["location"]
            form = await http.get(login_url)
            assert form.status_code == 200
            next_value = httpx.URL(login_url).params["next"]
            response = await http.post(
                "/oauth/login",
                data={
                    "username": OWNER_USERNAME,
                    "password": OWNER_PASSWORD,
                    "csrf_token": http.cookies["palaia_oauth_csrf"],
                    "next": next_value,
                },
            )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/oauth/authorize?")


@pytest.mark.anyio
async def test_signing_out_drops_the_session(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            await http.get("/oauth/login")
            await http.post(
                "/oauth/login",
                data={
                    "username": OWNER_USERNAME,
                    "password": OWNER_PASSWORD,
                    "csrf_token": http.cookies["palaia_oauth_csrf"],
                    "next": "",
                },
            )
            session = http.cookies["palaia_oauth_session"]
            response = await http.post("/oauth/logout")

    assert response.status_code == 204
    assert harness.store.get_login_session(session, harness.clock()) is None


@pytest.mark.anyio
async def test_the_login_page_escapes_the_error_it_renders(harness: Harness) -> None:
    """The form re-renders operator-visible text; nothing may be injected."""
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            response = await http.get("/oauth/login", params={"next": "<script>x</script>"})

    assert response.status_code == 200
    assert "<script>x</script>" not in response.text
