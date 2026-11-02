"""The OAuth pages let their form's redirect reach the AI app (issue #613).

Browsers check ``form-action`` against every redirect that follows a form
submission, not only against the form's own target. The consent page posts
to this origin and the answer is a 303 to the client's ``redirect_uri``; with
``form-action 'self'`` alone, a browser blocks that hop and no AI app can
finish connecting. These tests pin both halves of the fix: the validated
redirect origin is in the policy of each page whose form can end at the
client, and nothing that was not validated ever gets in.

The real-browser behaviour itself (Chromium blocking the hop before the fix,
letting it through after) was checked once by hand and is recorded on the
PR; the suite has no browser harness, so what it can hold is the header.
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx
import pytest

from palaia_hub.oauth.login import CSRF_COOKIE, SESSION_COOKIE
from palaia_hub.oauth.pkce import challenge_for
from palaia_hub.security.headers import (
    OAUTH_PAGE_CSP,
    form_action_source,
    oauth_page_csp,
)

from .harness import (
    CIMD_CLIENT_ID,
    CIMD_REDIRECT_URI,
    OWNER_PASSWORD,
    OWNER_USERNAME,
    Harness,
)

BASE_URL = "https://testserver"
DCR_REDIRECT_URI = "http://127.0.0.1:7777/callback"


def _form_action(csp: str) -> list[str]:
    """The source list of the policy's ``form-action`` directive."""
    for directive in csp.split(";"):
        name, *sources = directive.split()
        if name == "form-action":
            return sources
    raise AssertionError(f"no form-action in {csp!r}")


def _other_directives(csp: str) -> list[str]:
    return [d.strip() for d in csp.split(";") if not d.strip().startswith("form-action")]


# ---------------------------------------------------------------- the helper


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("https://claude.ai/api/mcp/auth_callback", "https://claude.ai"),
        ("https://client.example:8443/cb?x=1", "https://client.example:8443"),
        ("http://127.0.0.1:7777/callback", "http://127.0.0.1:7777"),
        ("http://localhost/callback", "http://localhost"),
    ],
)
def test_a_validated_redirect_uri_becomes_its_origin(uri: str, expected: str) -> None:
    assert form_action_source(uri) == expected


@pytest.mark.parametrize(
    "uri",
    [
        # CSP has no source form for an IPv6 literal; Chromium ignores one.
        "http://[::1]:7777/callback",
        # A character that would end the directive or start a new source.
        "https://a;b.example/cb",
        "https://a b.example/cb",
        "https://a'b.example/cb",
        # Not an http(s) origin at all.
        "javascript:alert(1)",
        "cursor://anysphere.cursor-retrieval/oauth/callback",
        "https:///no-host",
        "https://client.example:99999/cb",
    ],
)
def test_anything_that_is_not_a_plain_origin_is_left_out(uri: str) -> None:
    assert form_action_source(uri) is None
    assert oauth_page_csp(uri) == OAUTH_PAGE_CSP


def test_the_policy_changes_only_form_action() -> None:
    csp = oauth_page_csp("https://claude.ai/api/mcp/auth_callback")

    assert _form_action(csp) == ["'self'", "https://claude.ai"]
    assert _other_directives(csp) == _other_directives(OAUTH_PAGE_CSP)
    assert oauth_page_csp() == OAUTH_PAGE_CSP
    # One source per origin, however often it is named.
    assert _form_action(oauth_page_csp("https://claude.ai/a", "https://claude.ai/b")) == [
        "'self'",
        "https://claude.ai",
    ]


# ------------------------------------------------------------ the live pages


def _http(harness: Harness, *, session: str | None = None) -> httpx.AsyncClient:
    cookies = {SESSION_COOKIE: session} if session else None
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app),
        base_url=BASE_URL,
        follow_redirects=False,
        cookies=cookies,
    )


def _session(harness: Harness) -> str:
    session, _expires = harness.store.create_login_session(
        OWNER_USERNAME, now=harness.clock(), ttl=3600
    )
    return session


async def _register(http: httpx.AsyncClient, redirect_uri: str) -> str:
    response = await http.post(
        "/oauth/register",
        json={
            "client_name": "Test app",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["client_id"])


def _authorize_params(harness: Harness, client_id: str, redirect_uri: str) -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge_for("v" * 43),
        "code_challenge_method": "S256",
        "resource": harness.audience("alpha"),
        "state": "s1",
    }


def _login_path(params: dict[str, str]) -> str:
    return "/oauth/login?" + urlencode({"next": "/oauth/authorize?" + urlencode(params)})


@pytest.mark.anyio
async def test_the_consent_page_lets_its_answer_reach_a_registered_client(
    harness: Harness,
) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness, session=_session(harness)) as http:
            client_id = await _register(http, DCR_REDIRECT_URI)
            page = await http.get(
                "/oauth/authorize", params=_authorize_params(harness, client_id, DCR_REDIRECT_URI)
            )

    assert page.status_code == 200
    assert 'name="decision"' in page.text
    csp = page.headers["content-security-policy"]
    assert _form_action(csp) == ["'self'", "http://127.0.0.1:7777"]
    assert _other_directives(csp) == _other_directives(OAUTH_PAGE_CSP)


@pytest.mark.anyio
async def test_the_consent_page_lets_its_answer_reach_a_cimd_client(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness, session=_session(harness)) as http:
            page = await http.get(
                "/oauth/authorize",
                params=_authorize_params(harness, CIMD_CLIENT_ID, CIMD_REDIRECT_URI),
            )

    assert page.status_code == 200
    assert _form_action(page.headers["content-security-policy"]) == [
        "'self'",
        "https://client.test",
    ]


@pytest.mark.anyio
async def test_an_unregistered_redirect_uri_never_reaches_a_policy(harness: Harness) -> None:
    """The consent page is not rendered for it, and the error page says 'self' only."""
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness, session=_session(harness)) as http:
            client_id = await _register(http, DCR_REDIRECT_URI)
            page = await http.get(
                "/oauth/authorize",
                params=_authorize_params(harness, client_id, "https://evil.example/cb"),
            )

    assert page.status_code != 200 or 'name="decision"' not in page.text
    assert "evil.example" not in page.headers["content-security-policy"]
    assert page.headers["content-security-policy"] == OAUTH_PAGE_CSP


@pytest.mark.anyio
async def test_the_sign_in_page_lets_an_error_redirect_reach_a_registered_client(
    harness: Harness,
) -> None:
    """After sign-in, a request that fails validation goes on to the client."""
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            client_id = await _register(http, DCR_REDIRECT_URI)
            params = _authorize_params(harness, client_id, DCR_REDIRECT_URI)
            form = await http.get(_login_path(params))
            failed = await http.post(
                "/oauth/login",
                data={
                    "username": OWNER_USERNAME,
                    "password": "not-the-password",
                    "csrf_token": http.cookies[CSRF_COOKIE],
                    "next": "/oauth/authorize?" + urlencode(params),
                },
            )

    assert form.status_code == 200
    assert _form_action(form.headers["content-security-policy"]) == [
        "'self'",
        "http://127.0.0.1:7777",
    ]
    # The page shown again after a wrong password posts from the same place.
    assert failed.status_code == 401
    assert failed.headers["content-security-policy"] == form.headers["content-security-policy"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case",
    ["unregistered_redirect", "unknown_client", "first_time_cimd", "absolute_next", "no_next"],
)
async def test_the_sign_in_page_names_no_target_it_has_not_validated(
    harness: Harness, case: str
) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            client_id = await _register(http, DCR_REDIRECT_URI)
            paths = {
                "unregistered_redirect": _login_path(
                    _authorize_params(harness, client_id, "https://evil.example/cb")
                ),
                "unknown_client": _login_path(
                    _authorize_params(harness, "no-such-client", "https://evil.example/cb")
                ),
                # Never resolved before, so not in the store. Its document is
                # served by the harness, so a sign-in page that fetched it for
                # a stranger would name https://client.test and fail here.
                "first_time_cimd": _login_path(
                    _authorize_params(harness, CIMD_CLIENT_ID, CIMD_REDIRECT_URI)
                ),
                "absolute_next": "/oauth/login?"
                + urlencode(
                    {
                        "next": "https://evil.example/oauth/authorize?"
                        + urlencode(_authorize_params(harness, client_id, DCR_REDIRECT_URI))
                    }
                ),
                "no_next": "/oauth/login",
            }
            form = await http.get(paths[case])

    assert form.status_code == 200
    assert form.headers["content-security-policy"] == OAUTH_PAGE_CSP


@pytest.mark.anyio
async def test_a_signed_in_owner_answering_the_page_gets_a_redirect_the_policy_allows(
    harness: Harness,
) -> None:
    """End to end over the ASGI app: the hop Allow produces is the one allowed."""
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            client_id = await _register(http, DCR_REDIRECT_URI)
            params = _authorize_params(harness, client_id, DCR_REDIRECT_URI)
            await http.get(_login_path(params))
            signed_in = await http.post(
                "/oauth/login",
                data={
                    "username": OWNER_USERNAME,
                    "password": OWNER_PASSWORD,
                    "csrf_token": http.cookies[CSRF_COOKIE],
                    "next": "/oauth/authorize?" + urlencode(params),
                },
            )
            page = await http.get(signed_in.headers["location"])
            fields = dict(params)
            fields["csrf_token"] = http.cookies[CSRF_COOKIE]
            fields["decision"] = "allow"
            answer = await http.post("/oauth/authorize", data=fields)

    assert answer.status_code == 303
    target = httpx.URL(answer.headers["location"])
    assert f"{target.scheme}://{target.host}:{target.port}" in _form_action(
        page.headers["content-security-policy"]
    )
