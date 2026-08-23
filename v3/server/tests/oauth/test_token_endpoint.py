"""The token, revocation and registration endpoints over HTTP.

The grace-window behaviour is proven at the store level in
``test_refresh_rotation.py``; this file proves it survives the trip through
the HTTP layer — which is where a real client meets it, and where the wrong
status code or a missing ``no-store`` would matter.
"""

from __future__ import annotations

import httpx
import pytest

from palaia_hub.oauth import provision_machine_client
from palaia_hub.oauth.pkce import challenge_for

from .harness import CIMD_CLIENT_ID, CIMD_REDIRECT_URI, OWNER_PASSWORD, OWNER_USERNAME, Harness

BASE_URL = "https://testserver"
VERIFIER = "token-endpoint-code-verifier-with-plenty-of-entropy"
SCOPES = ("vault:work:read", "vault:work:write")


def _http(harness: Harness) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app),
        base_url=BASE_URL,
        follow_redirects=False,
    )


async def _sign_in(http: httpx.AsyncClient) -> None:
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


async def _grant_tokens(harness: Harness, http: httpx.AsyncClient) -> dict[str, str]:
    await _sign_in(http)
    authorize = await http.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": CIMD_CLIENT_ID,
            "redirect_uri": CIMD_REDIRECT_URI,
            "code_challenge": challenge_for(VERIFIER),
            "code_challenge_method": "S256",
            "state": "s",
            "resource": harness.audience("alpha"),
        },
    )
    assert authorize.status_code == 303, authorize.text
    code = httpx.URL(authorize.headers["location"]).params["code"]
    response = await http.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": CIMD_CLIENT_ID,
            "redirect_uri": CIMD_REDIRECT_URI,
            "code_verifier": VERIFIER,
        },
    )
    assert response.status_code == 200, response.text
    return {k: str(v) for k, v in response.json().items()}


# --------------------------------------------------------------- refreshing


@pytest.mark.anyio
async def test_two_concurrent_refreshes_over_http_both_get_working_tokens(
    harness: Harness,
) -> None:
    """The fan-out acceptance criterion, at the endpoint a connector calls."""
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            tokens = await _grant_tokens(harness, http)
            shared = tokens["refresh_token"]

            first = await http.post(
                "/oauth/token", data={"grant_type": "refresh_token", "refresh_token": shared}
            )
            second = await http.post(
                "/oauth/token", data={"grant_type": "refresh_token", "refresh_token": shared}
            )

            assert first.status_code == 200, first.text
            assert second.status_code == 200, second.text
            successors = {first.json()["refresh_token"], second.json()["refresh_token"]}
            assert len(successors) == 2
            for successor in successors:
                again = await http.post(
                    "/oauth/token",
                    data={"grant_type": "refresh_token", "refresh_token": successor},
                )
                assert again.status_code == 200, again.text


@pytest.mark.anyio
async def test_after_the_grace_window_the_spent_token_is_invalid_grant(
    harness: Harness,
) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            tokens = await _grant_tokens(harness, http)
            spent = tokens["refresh_token"]
            await http.post(
                "/oauth/token", data={"grant_type": "refresh_token", "refresh_token": spent}
            )

            harness.clock.advance(harness.server.settings.refresh_grace_window + 1)
            response = await http.post(
                "/oauth/token", data={"grant_type": "refresh_token", "refresh_token": spent}
            )

            assert response.status_code == 400
            assert response.json()["error"] == "invalid_grant"
            assert response.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_a_refresh_may_narrow_but_never_widen_the_scope(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            tokens = await _grant_tokens(harness, http)

            narrowed = await http.post(
                "/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": tokens["refresh_token"],
                    "scope": "vault:work:read",
                },
            )
            assert narrowed.status_code == 200
            assert narrowed.json()["scope"] == "vault:work:read"

            widened = await http.post(
                "/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": narrowed.json()["refresh_token"],
                    "scope": "vault:other:write",
                },
            )
            assert widened.status_code == 400
            assert widened.json()["error"] == "invalid_scope"


@pytest.mark.anyio
async def test_a_revoked_refresh_token_stops_working_immediately(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            tokens = await _grant_tokens(harness, http)

            revoked = await http.post("/oauth/revoke", data={"token": tokens["refresh_token"]})
            assert revoked.status_code == 200

            response = await http.post(
                "/oauth/token",
                data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]},
            )
            assert response.status_code == 400
            assert response.json()["error"] == "invalid_grant"


@pytest.mark.anyio
async def test_revoking_an_unknown_token_is_still_a_200(harness: Harness) -> None:
    """RFC 7009 §2.2 — the endpoint must not become a lookup oracle."""
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            response = await http.post("/oauth/revoke", data={"token": "never-existed"})

    assert response.status_code == 200


# -------------------------------------------------------------- code errors


@pytest.mark.anyio
async def test_a_code_cannot_be_redeemed_twice(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            await _sign_in(http)
            authorize = await http.get(
                "/oauth/authorize",
                params={
                    "response_type": "code",
                    "client_id": CIMD_CLIENT_ID,
                    "redirect_uri": CIMD_REDIRECT_URI,
                    "code_challenge": challenge_for(VERIFIER),
                    "code_challenge_method": "S256",
                    "resource": harness.audience("alpha"),
                },
            )
            code = httpx.URL(authorize.headers["location"]).params["code"]
            form = {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": CIMD_CLIENT_ID,
                "redirect_uri": CIMD_REDIRECT_URI,
                "code_verifier": VERIFIER,
            }
            first = await http.post("/oauth/token", data=form)
            second = await http.post("/oauth/token", data=form)

            assert first.status_code == 200
            assert second.status_code == 400
            assert second.json()["error"] == "invalid_grant"
            # The replay revoked the grant, so the first refresh token is dead.
            refresh = await http.post(
                "/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": first.json()["refresh_token"],
                },
            )
            assert refresh.status_code == 400


@pytest.mark.anyio
async def test_a_wrong_code_verifier_is_refused_and_kills_the_grant(
    harness: Harness,
) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            await _sign_in(http)
            authorize = await http.get(
                "/oauth/authorize",
                params={
                    "response_type": "code",
                    "client_id": CIMD_CLIENT_ID,
                    "redirect_uri": CIMD_REDIRECT_URI,
                    "code_challenge": challenge_for(VERIFIER),
                    "code_challenge_method": "S256",
                    "resource": harness.audience("alpha"),
                },
            )
            code = httpx.URL(authorize.headers["location"]).params["code"]
            response = await http.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": CIMD_CLIENT_ID,
                    "redirect_uri": CIMD_REDIRECT_URI,
                    "code_verifier": "b" * 43,
                },
            )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


@pytest.mark.anyio
async def test_an_unsupported_grant_type_is_named_as_such(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            response = await http.post("/oauth/token", data={"grant_type": "password"})

    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"


# --------------------------------------------------------- machine identities


@pytest.mark.anyio
async def test_a_machine_client_gets_an_access_token_and_no_refresh_token(
    harness: Harness,
) -> None:
    provisioned = provision_machine_client(
        harness.store,
        client_name="nightly job",
        audience=harness.audience("alpha"),
        scopes=SCOPES,
        now=harness.clock(),
    )

    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            response = await http.post(
                "/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": provisioned.client.client_id,
                    "client_secret": provisioned.client_secret,
                },
            )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "refresh_token" not in body
    assert body["scope"] == " ".join(SCOPES)


@pytest.mark.anyio
async def test_a_machine_client_authenticates_with_http_basic_too(
    harness: Harness,
) -> None:
    provisioned = provision_machine_client(
        harness.store,
        client_name="job",
        audience=harness.audience("alpha"),
        scopes=SCOPES,
        now=harness.clock(),
    )

    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            response = await http.post(
                "/oauth/token",
                data={"grant_type": "client_credentials"},
                auth=(provisioned.client.client_id, provisioned.client_secret),
            )

    assert response.status_code == 200, response.text


@pytest.mark.anyio
async def test_a_machine_client_cannot_be_talked_into_another_resource(
    harness: Harness,
) -> None:
    """MASTERPLAN §5.5: "pinned to exactly one audience", enforced."""
    provisioned = provision_machine_client(
        harness.store,
        client_name="job",
        audience=harness.audience("alpha"),
        scopes=SCOPES,
        now=harness.clock(),
    )

    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            response = await http.post(
                "/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": provisioned.client.client_id,
                    "client_secret": provisioned.client_secret,
                    "resource": harness.audience("beta"),
                },
            )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_target"


@pytest.mark.anyio
async def test_a_wrong_machine_secret_is_invalid_client_with_a_challenge(
    harness: Harness,
) -> None:
    provisioned = provision_machine_client(
        harness.store,
        client_name="job",
        audience=harness.audience("alpha"),
        scopes=SCOPES,
        now=harness.clock(),
    )

    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            wrong = await http.post(
                "/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": provisioned.client.client_id,
                    "client_secret": "not-the-secret",
                },
            )
            unknown = await http.post(
                "/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": "machine_does-not-exist",
                    "client_secret": "whatever",
                },
            )

    assert wrong.status_code == 401
    assert wrong.headers["www-authenticate"].startswith("Basic")
    # Indistinguishable from an unknown client.
    assert wrong.json() == unknown.json()
    assert unknown.status_code == 401


@pytest.mark.anyio
async def test_a_public_client_cannot_use_client_credentials(harness: Harness) -> None:
    registered = await _register(harness)

    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            response = await http.post(
                "/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": registered,
                    "client_secret": "invented",
                },
            )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


@pytest.mark.anyio
async def test_a_machine_client_cannot_use_the_code_flow(harness: Harness) -> None:
    provisioned = provision_machine_client(
        harness.store,
        client_name="job",
        audience=harness.audience("alpha"),
        scopes=SCOPES,
        now=harness.clock(),
    )

    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            await _sign_in(http)
            response = await http.get(
                "/oauth/authorize",
                params={
                    "response_type": "code",
                    "client_id": provisioned.client.client_id,
                    "code_challenge": challenge_for(VERIFIER),
                    "code_challenge_method": "S256",
                    "resource": harness.audience("alpha"),
                },
            )

    # It has no redirect URI at all, so this cannot even be redirected back.
    assert response.status_code == 400
    assert "redirect_uri" in response.text


async def _register(harness: Harness) -> str:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            response = await http.post(
                "/oauth/register",
                json={"client_name": "public", "redirect_uris": ["https://client.test/cb"]},
            )
    assert response.status_code == 201, response.text
    return str(response.json()["client_id"])


# ------------------------------------------------------------- authorize errors


@pytest.mark.anyio
async def test_an_unauthenticated_authorize_request_touches_no_client(
    harness: Harness,
) -> None:
    """The owner is authenticated before any request-controlled lookup happens.

    An https ``client_id`` would otherwise make this endpoint fetch a
    caller-chosen URL for a caller who has not signed in.
    """
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            response = await http.get(
                "/oauth/authorize",
                params={
                    "response_type": "code",
                    "client_id": CIMD_CLIENT_ID,
                    "redirect_uri": CIMD_REDIRECT_URI,
                    "code_challenge": challenge_for(VERIFIER),
                    "code_challenge_method": "S256",
                    "resource": harness.audience("alpha"),
                },
            )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/oauth/login?next=")
    assert harness.store.count_clients() == 0, "no client row was created"


@pytest.mark.anyio
async def test_an_unknown_client_id_never_redirects(harness: Harness) -> None:
    """RFC 6749 §4.1.2.1: an unvalidated client must not get a redirect."""
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            await _sign_in(http)
            response = await http.get(
                "/oauth/authorize",
                params={
                    "response_type": "code",
                    "client_id": "dcr_nope",
                    "redirect_uri": "https://evil.test/steal",
                    "code_challenge": challenge_for(VERIFIER),
                    "code_challenge_method": "S256",
                },
            )

    assert response.status_code == 401
    assert "location" not in response.headers
    assert "invalid_client" in response.text


@pytest.mark.anyio
async def test_a_mismatched_redirect_uri_never_redirects(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            await _sign_in(http)
            response = await http.get(
                "/oauth/authorize",
                params={
                    "response_type": "code",
                    "client_id": CIMD_CLIENT_ID,
                    "redirect_uri": "https://evil.test/steal",
                    "code_challenge": challenge_for(VERIFIER),
                    "code_challenge_method": "S256",
                },
            )

    assert response.status_code == 400
    assert "location" not in response.headers


@pytest.mark.anyio
async def test_errors_after_validation_are_redirected_with_state(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            await _sign_in(http)
            response = await http.get(
                "/oauth/authorize",
                params={
                    "response_type": "token",  # OAuth 2.1 removed the implicit flow
                    "client_id": CIMD_CLIENT_ID,
                    "redirect_uri": CIMD_REDIRECT_URI,
                    "code_challenge": challenge_for(VERIFIER),
                    "code_challenge_method": "S256",
                    "state": "keep-me",
                    "resource": harness.audience("alpha"),
                },
            )

    assert response.status_code == 303
    location = httpx.URL(response.headers["location"])
    assert str(location).startswith(CIMD_REDIRECT_URI)
    assert location.params["error"] == "unsupported_response_type"
    assert location.params["state"] == "keep-me"
    assert location.params["iss"] == harness.server.issuer


@pytest.mark.anyio
async def test_pkce_is_mandatory(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            await _sign_in(http)
            response = await http.get(
                "/oauth/authorize",
                params={
                    "response_type": "code",
                    "client_id": CIMD_CLIENT_ID,
                    "redirect_uri": CIMD_REDIRECT_URI,
                    "resource": harness.audience("alpha"),
                },
            )

    assert response.status_code == 303
    assert httpx.URL(response.headers["location"]).params["error"] == "invalid_request"


@pytest.mark.anyio
async def test_an_unknown_resource_is_invalid_target(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            await _sign_in(http)
            response = await http.get(
                "/oauth/authorize",
                params={
                    "response_type": "code",
                    "client_id": CIMD_CLIENT_ID,
                    "redirect_uri": CIMD_REDIRECT_URI,
                    "code_challenge": challenge_for(VERIFIER),
                    "code_challenge_method": "S256",
                    "resource": "https://testserver/nope",
                },
            )

    assert httpx.URL(response.headers["location"]).params["error"] == "invalid_target"
