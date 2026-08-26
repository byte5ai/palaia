"""The acceptance criterion "no secret/token/code ever logged".

Two layers, tested separately because they fail differently:

1. **The authorize and token paths do not log credentials in the first
   place.** These tests capture everything the whole hub logs while a
   complete flow runs, then search that text for every credential the flow
   produced — the password, the session id, the CSRF token, the code, the
   code_verifier, the access token, the refresh token, the machine secret.
2. **The redaction filter would catch them anyway.** ``palaia_hub.logging``'s
   filter is the net under the first layer, and these tests pin the OAuth
   parameter names it now covers — including the check that ``code`` does not
   accidentally swallow an innocent ``status_code=404``.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from palaia_hub.logging import REDACTED, redact
from palaia_hub.oauth import provision_machine_client
from palaia_hub.oauth.pkce import challenge_for

from .harness import CIMD_CLIENT_ID, CIMD_REDIRECT_URI, OWNER_PASSWORD, OWNER_USERNAME, Harness

BASE_URL = "https://testserver"
VERIFIER = "redaction-test-code-verifier-with-enough-entropy-ab"
SECRET = "sk-abcdef1234567890"  # noqa: S105 - test fixture, not a real credential


@pytest.mark.anyio
async def test_a_complete_flow_logs_no_credential(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="palaia_hub")
    caplog.set_level(logging.DEBUG, logger="uvicorn")

    async with harness.app.router.lifespan_context(harness.app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=harness.app),
            base_url=BASE_URL,
            follow_redirects=False,
        ) as http:
            await http.get("/oauth/login")
            csrf = http.cookies["palaia_oauth_csrf"]
            await http.post(
                "/oauth/login",
                data={
                    "username": OWNER_USERNAME,
                    "password": OWNER_PASSWORD,
                    "csrf_token": csrf,
                    "next": "",
                },
            )
            session = http.cookies["palaia_oauth_session"]
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
            code = httpx.URL(authorize.headers["location"]).params["code"]
            token_response = await http.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": CIMD_CLIENT_ID,
                    "redirect_uri": CIMD_REDIRECT_URI,
                    "code_verifier": VERIFIER,
                },
            )
            tokens = token_response.json()
            await http.post(
                "/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": tokens["refresh_token"],
                },
            )

    logged = "\n".join(record.getMessage() for record in caplog.records)
    credentials = {
        "password": OWNER_PASSWORD,
        "session id": session,
        "csrf token": csrf,
        "authorization code": code,
        "code_verifier": VERIFIER,
        "access token": str(tokens["access_token"]),
        "refresh token": str(tokens["refresh_token"]),
    }
    for name, value in credentials.items():
        assert value not in logged, f"the {name} reached the log"

    # The flow *was* logged — this test would pass trivially against silence.
    assert "issued an authorization code" in logged
    assert "refreshed tokens for client" in logged


@pytest.mark.anyio
async def test_a_failed_sign_in_logs_neither_the_password_nor_a_hash(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="palaia_hub")

    async with harness.app.router.lifespan_context(harness.app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=harness.app), base_url=BASE_URL
        ) as http:
            await http.get("/oauth/login")
            await http.post(
                "/oauth/login",
                data={
                    "username": OWNER_USERNAME,
                    "password": "the-wrong-password-entirely",
                    "csrf_token": http.cookies["palaia_oauth_csrf"],
                    "next": "",
                },
            )

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "the-wrong-password-entirely" not in logged
    assert "$argon2id$" not in logged


def test_provisioning_a_machine_client_does_not_log_its_secret(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="palaia_hub")

    provisioned = provision_machine_client(
        harness.store,
        client_name="nightly job",
        audience=harness.audience("alpha"),
        scopes=["vault:work:read"],
        now=harness.clock(),
    )

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert provisioned.client_secret not in logged
    assert provisioned.client.client_secret_hash not in logged  # type: ignore[operator]
    assert provisioned.client.client_id in logged, "the identifier is what belongs in a log"


# ------------------------------------------------- the filter under the floor


@pytest.mark.parametrize(
    "message",
    [
        f"GET /oauth/authorize?code={SECRET}&state=s",
        f"code_verifier={SECRET}",
        f"client_secret={SECRET}",
        f"refresh_token={SECRET}",
        f"access_token={SECRET}",
        f'{{"refresh_token": "{SECRET}"}}',
        f"session={SECRET}",
        f"csrf_token={SECRET}",
    ],
)
def test_the_filter_masks_every_oauth_credential_parameter(message: str) -> None:
    redacted = redact(message)

    assert SECRET not in redacted
    assert REDACTED in redacted


@pytest.mark.parametrize(
    "message",
    [
        "request finished with status_code=404",
        "http_code=500 on /api/health",
        "the exit_code was 0",
        "hub started on 127.0.0.1:8420 in locked mode",
    ],
)
def test_the_filter_leaves_innocent_code_suffixed_keys_alone(message: str) -> None:
    assert redact(message) == message


def test_a_redirect_with_a_code_is_masked_even_in_a_query_string() -> None:
    message = f"Location: https://client.test/cb?code={SECRET}&state=abc&iss=https://hub"

    redacted = redact(message)

    assert SECRET not in redacted
    # The non-secret parameters after it survive: the '&' terminates the match.
    assert "state=abc" in redacted
