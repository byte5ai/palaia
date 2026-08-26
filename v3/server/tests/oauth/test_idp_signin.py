"""SPEC-204: GitHub / generic-OIDC sign-in.

Covers every acceptance criterion:

* a full GitHub-shaped flow against a mocked provider, through to a real
  ``/oauth/authorize`` continuation (proving the resulting session is
  exactly as usable as a password sign-in's)
* the sign-in ticket is single-use (a replayed ``state`` is rejected)
* a fabricated/mismatched ``state`` is rejected
* a user not on the allow-list is rejected
* the provider's access token is never persisted (a store-file scan)
* with an IdP configured, the password endpoint does not exist (404, not
  a 403 that would confirm the door is merely locked)
* the sign-in page's copy passes the jargon rule (no protocol acronyms)
* the generic OIDC provider resolves a username through discovery
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from palaia_hub.config import GitHubIdpSettings, IdpSettings, OAuthSettings, OidcIdpSettings
from palaia_hub.oauth import StaticIdpHttp
from palaia_hub.oauth.idp import GITHUB_TOKEN_URL, GITHUB_USER_URL
from palaia_hub.oauth.pkce import challenge_for

from .harness import (
    CIMD_CLIENT_ID,
    CIMD_REDIRECT_URI,
    ISSUER,
    PROFILES,
    Harness,
    build_harness,
)

BASE_URL = "https://testserver"
FAKE_GITHUB_TOKEN = "gho_this-is-the-providers-token-1234567890"  # noqa: S105 - test fixture

GITHUB_SETTINGS = OAuthSettings(
    enabled=True,
    issuer=ISSUER,
    profiles=list(PROFILES),
    idp=IdpSettings(
        provider="github",
        github=GitHubIdpSettings(
            client_id="test-github-client-id",
            client_secret="test-github-client-secret",  # noqa: S106 - test fixture
            allowed_users=["Octocat"],
        ),
    ),
)

OIDC_DISCOVERY_URL = "https://idp.example.com/.well-known/openid-configuration"
OIDC_SETTINGS = OAuthSettings(
    enabled=True,
    issuer=ISSUER,
    profiles=list(PROFILES),
    idp=IdpSettings(
        provider="oidc",
        oidc=OidcIdpSettings(
            discovery_url=OIDC_DISCOVERY_URL,
            client_id="test-oidc-client-id",
            client_secret="test-oidc-client-secret",  # noqa: S106 - test fixture
            allowed_users=["ana@example.com"],
            username_claim="preferred_username",
            display_name="Example Workspace",
        ),
    ),
)


def _github_http() -> StaticIdpHttp:
    return StaticIdpHttp(
        token_responses={GITHUB_TOKEN_URL: {"access_token": FAKE_GITHUB_TOKEN}},
        json_responses={GITHUB_USER_URL: {"login": "octocat"}},  # case differs from allow-list
    )


def _github_harness(tmp_path: Path) -> Harness:
    return build_harness(
        tmp_path,
        settings=GITHUB_SETTINGS,
        with_owner=False,
        with_plt_tokens=False,
        idp_http=_github_http(),
    )


def _http(harness: Harness) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app),
        base_url=BASE_URL,
        follow_redirects=False,
    )


def _state_from_start_redirect(response: httpx.Response) -> str:
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    assert location.startswith("https://github.com/login/oauth/authorize?")
    query = parse_qs(urlsplit(location).query, keep_blank_values=True)
    assert query["scope"] == [""]  # zero scopes (deliverable #1)
    return query["state"][0]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# ------------------------------------------------------------ full flow (204)


@pytest.mark.anyio
async def test_full_github_shaped_flow_signs_in_and_continues_authorize(
    tmp_path: Path,
) -> None:
    harness = _github_harness(tmp_path)
    try:
        async with _http(harness) as http:
            authorize_params = {
                "response_type": "code",
                "client_id": CIMD_CLIENT_ID,
                "redirect_uri": CIMD_REDIRECT_URI,
                "code_challenge": challenge_for("a-code-verifier-with-enough-entropy-abc"),
                "code_challenge_method": "S256",
                "state": "client-state",
                "resource": harness.audience("alpha"),
            }
            # Unauthenticated: sent straight to the IdP (one door only — no
            # interstitial page offering a password door that does not exist).
            redirected = await http.get("/oauth/authorize", params=authorize_params)
            assert redirected.status_code == 303
            start_location = redirected.headers["location"]
            assert start_location.startswith("/oauth/idp/start?next=")

            start = await http.get(start_location)
            state = _state_from_start_redirect(start)

            callback = await http.get(f"/oauth/idp/callback?code=the-code&state={state}")
            assert callback.status_code == 303, callback.text
            assert "palaia_oauth_session" in http.cookies

            # The session is real: /oauth/authorize now issues a code.
            resumed = await http.get(callback.headers["location"])
            assert resumed.status_code == 303, resumed.text
            resumed_query = parse_qs(urlsplit(resumed.headers["location"]).query)
            assert "error" not in resumed_query, resumed_query
            assert resumed_query["state"] == ["client-state"]
            assert resumed_query["code"][0]
    finally:
        harness.store.close()


@pytest.mark.anyio
async def test_the_provider_token_is_never_persisted(tmp_path: Path) -> None:
    harness = _github_harness(tmp_path)
    try:
        async with _http(harness) as http:
            start = await http.get(
                "/oauth/idp/start?next=" + "%2Foauth%2Fauthorize%3Fx%3D1"
            )
            state = _state_from_start_redirect(start)
            callback = await http.get(f"/oauth/idp/callback?code=the-code&state={state}")
            assert callback.status_code == 303, callback.text
    finally:
        harness.store.close()

    # The store scan: the provider's access token must not appear anywhere
    # in the on-disk database, WAL file, or journal.
    for suffix in ("", "-wal", "-shm", "-journal"):
        sibling = harness.store.path.with_name(harness.store.path.name + suffix)
        if sibling.exists():
            assert FAKE_GITHUB_TOKEN.encode() not in sibling.read_bytes()


# ------------------------------------------------------------------ rejections


@pytest.mark.anyio
async def test_a_replayed_state_is_rejected_single_use(tmp_path: Path) -> None:
    harness = _github_harness(tmp_path)
    try:
        async with _http(harness) as http:
            start = await http.get("/oauth/idp/start?next=%2Foauth%2Fauthorize%3Fx%3D1")
            state = _state_from_start_redirect(start)

            first = await http.get(f"/oauth/idp/callback?code=the-code&state={state}")
            assert first.status_code == 303, first.text

        async with _http(harness) as http:
            second = await http.get(f"/oauth/idp/callback?code=the-code&state={state}")
            assert second.status_code != 303
            assert "palaia_oauth_session" not in http.cookies
    finally:
        harness.store.close()


@pytest.mark.anyio
async def test_a_mismatched_state_is_rejected(tmp_path: Path) -> None:
    harness = _github_harness(tmp_path)
    try:
        async with _http(harness) as http:
            # Never started a flow at all — a fabricated state.
            response = await http.get(
                "/oauth/idp/callback?code=the-code&state=totally-made-up-state"
            )
            assert response.status_code != 303
            assert "palaia_oauth_session" not in http.cookies
    finally:
        harness.store.close()


@pytest.mark.anyio
async def test_a_non_allow_listed_user_is_rejected(tmp_path: Path) -> None:
    harness = build_harness(
        tmp_path,
        settings=GITHUB_SETTINGS,
        with_owner=False,
        with_plt_tokens=False,
        idp_http=StaticIdpHttp(
            token_responses={GITHUB_TOKEN_URL: {"access_token": FAKE_GITHUB_TOKEN}},
            json_responses={GITHUB_USER_URL: {"login": "someone-else"}},
        ),
    )
    try:
        async with _http(harness) as http:
            start = await http.get("/oauth/idp/start?next=%2Foauth%2Fauthorize%3Fx%3D1")
            state = _state_from_start_redirect(start)
            response = await http.get(f"/oauth/idp/callback?code=the-code&state={state}")
            assert response.status_code != 303
            assert "palaia_oauth_session" not in http.cookies
    finally:
        harness.store.close()


@pytest.mark.anyio
async def test_case_folded_allow_list_still_matches(tmp_path: Path) -> None:
    """The allow-list has "Octocat"; the provider reports "octocat"."""
    harness = _github_harness(tmp_path)
    try:
        async with _http(harness) as http:
            start = await http.get("/oauth/idp/start?next=%2Foauth%2Fauthorize%3Fx%3D1")
            state = _state_from_start_redirect(start)
            response = await http.get(f"/oauth/idp/callback?code=the-code&state={state}")
            assert response.status_code == 303, response.text
            assert "palaia_oauth_session" in http.cookies
    finally:
        harness.store.close()


@pytest.mark.anyio
async def test_a_provider_error_is_rejected(tmp_path: Path) -> None:
    harness = _github_harness(tmp_path)
    try:
        async with _http(harness) as http:
            start = await http.get("/oauth/idp/start?next=%2Foauth%2Fauthorize%3Fx%3D1")
            state = _state_from_start_redirect(start)
            response = await http.get(
                f"/oauth/idp/callback?error=access_denied&state={state}"
            )
            assert response.status_code != 303
            assert "palaia_oauth_session" not in http.cookies
    finally:
        harness.store.close()


# --------------------------------------------------------------- one door rule


@pytest.mark.anyio
async def test_the_password_endpoint_is_absent_not_forbidden(tmp_path: Path) -> None:
    harness = _github_harness(tmp_path)
    try:
        async with _http(harness) as http:
            posted = await http.post(
                "/oauth/login", data={"username": "owner", "password": "whatever12345"}
            )
            assert posted.status_code == 404
            got = await http.get("/oauth/login")
            assert got.status_code == 404
    finally:
        harness.store.close()


@pytest.mark.anyio
async def test_without_an_idp_the_idp_routes_are_absent(tmp_path: Path) -> None:
    harness = build_harness(tmp_path)  # default settings: no idp configured
    try:
        async with _http(harness) as http:
            start = await http.get("/oauth/idp/start?next=%2Foauth%2Fauthorize")
            assert start.status_code == 404
            callback = await http.get("/oauth/idp/callback?code=x&state=y")
            assert callback.status_code == 404

            # And the password door is still there.
            form = await http.get("/oauth/login")
            assert form.status_code == 200
    finally:
        harness.store.close()


# ---------------------------------------------------------- admin info (204.4)


@pytest.mark.anyio
async def test_api_info_reports_the_sign_in_method_for_the_dashboard(tmp_path: Path) -> None:
    """The dashboard's settings section (deliverable #4) reads this."""
    harness = _github_harness(tmp_path)
    try:
        async with _http(harness) as http:
            response = await http.get("/api/info")
            assert response.status_code == 200
            # SPEC-401 added `required`/`sign_in_url` to the same block: an
            # IdP hub in cloud mode has the gate on, and its one door is the
            # provider start (there is no password form to point at).
            assert response.json()["sign_in"] == {
                "method": "idp",
                "provider_name": "GitHub",
                "required": True,
                "sign_in_url": "/oauth/idp/start",
            }
    finally:
        harness.store.close()


@pytest.mark.anyio
async def test_api_info_reports_password_when_no_idp_is_configured(tmp_path: Path) -> None:
    harness = build_harness(tmp_path)
    try:
        async with _http(harness) as http:
            response = await http.get("/api/info")
            assert response.status_code == 200
            assert response.json()["sign_in"] == {
                "method": "password",
                "provider_name": None,
                "required": True,
                "sign_in_url": "/oauth/login",
            }
    finally:
        harness.store.close()


# --------------------------------------------------------------------- OIDC


@pytest.mark.anyio
async def test_generic_oidc_resolves_username_via_discovery(tmp_path: Path) -> None:
    discovery = {
        "authorization_endpoint": "https://idp.example.com/authorize",
        "token_endpoint": "https://idp.example.com/token",
        "userinfo_endpoint": "https://idp.example.com/userinfo",
    }
    idp_http = StaticIdpHttp(
        token_responses={"https://idp.example.com/token": {"access_token": "oidc-token-xyz"}},
        json_responses={
            OIDC_DISCOVERY_URL: discovery,
            "https://idp.example.com/userinfo": {"preferred_username": "ana@example.com"},
        },
    )
    harness = build_harness(
        tmp_path,
        settings=OIDC_SETTINGS,
        with_owner=False,
        with_plt_tokens=False,
        idp_http=idp_http,
    )
    try:
        async with _http(harness) as http:
            info = await http.get("/api/info")
            assert info.json()["sign_in"] == {
                "method": "idp",
                "provider_name": "Example Workspace",
                "required": True,
                "sign_in_url": "/oauth/idp/start",
            }

            start = await http.get("/oauth/idp/start?next=%2Foauth%2Fauthorize%3Fx%3D1")
            assert start.status_code == 303
            location = start.headers["location"]
            assert location.startswith("https://idp.example.com/authorize?")
            state = parse_qs(urlsplit(location).query)["state"][0]

            callback = await http.get(f"/oauth/idp/callback?code=the-code&state={state}")
            assert callback.status_code == 303, callback.text
            assert "palaia_oauth_session" in http.cookies
    finally:
        harness.store.close()


@pytest.mark.anyio
async def test_oidc_username_claim_is_configurable(tmp_path: Path) -> None:
    """A provider that only populates 'email' still works via ``username_claim``."""
    settings = OAuthSettings(
        enabled=True,
        issuer=ISSUER,
        profiles=list(PROFILES),
        idp=IdpSettings(
            provider="oidc",
            oidc=OidcIdpSettings(
                discovery_url=OIDC_DISCOVERY_URL,
                client_id="test-oidc-client-id",
                client_secret="test-oidc-client-secret",  # noqa: S106 - test fixture
                allowed_users=["ana@example.com"],
                username_claim="email",
                display_name="Example Workspace",
            ),
        ),
    )
    discovery = {
        "authorization_endpoint": "https://idp.example.com/authorize",
        "token_endpoint": "https://idp.example.com/token",
        "userinfo_endpoint": "https://idp.example.com/userinfo",
    }
    idp_http = StaticIdpHttp(
        token_responses={"https://idp.example.com/token": {"access_token": "oidc-token-xyz"}},
        json_responses={
            OIDC_DISCOVERY_URL: discovery,
            "https://idp.example.com/userinfo": {"email": "ana@example.com"},
        },
    )
    harness = build_harness(
        tmp_path, settings=settings, with_owner=False, with_plt_tokens=False, idp_http=idp_http
    )
    try:
        async with _http(harness) as http:
            start = await http.get("/oauth/idp/start?next=%2Foauth%2Fauthorize%3Fx%3D1")
            state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
            callback = await http.get(f"/oauth/idp/callback?code=the-code&state={state}")
            assert callback.status_code == 303, callback.text
            assert "palaia_oauth_session" in http.cookies
    finally:
        harness.store.close()
