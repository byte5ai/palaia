"""Issue #272: an OAuth-authenticated client must fire `client.connected`.

Before this fix, `client.connected` (and so the SPEC-504 funnel's
`client_connected_at`, see `palaia_hub.funnel`) only ever fired from
`TokenStore.on_verified` — a SPEC-108 `plt_` token's own hook. A real OAuth
2.1 access token, verified by fastmcp's own `JWTVerifier`
(`palaia_hub.oauth.verifier.build_profile_auth`), never touched that hook at
all, so a hub whose very first connected client used OAuth (the common case
for the real `claude` CLI, `test_spec506_phase5_gate.py`'s own repro) never
recorded its first-client milestone until some *other*, `plt_`-token client
happened to connect too.

These tests exercise the real OAuth 2.1 + PKCE code flow over
`httpx.ASGITransport` (the same rig `test_flow_e2e.py` uses) and assert
`client.connected` fires on the harness's own event bus — the same bus
`palaia_hub.funnel.wire_funnel_tracking` subscribes to in production.
"""

from __future__ import annotations

import pytest

from palaia_hub.events.schema import Envelope
from palaia_hub.oauth.verifier import (
    build_jwt_verifier,
    build_profile_auth,
    summarize_profile_auth,
)

from .harness import CIMD_CLIENT_ID, CIMD_REDIRECT_URI, Harness
from .test_flow_e2e import _client


@pytest.mark.anyio
async def test_oauth_verify_fires_client_connected(harness: Harness) -> None:
    """A client that authenticates over OAuth alone still fires the event —
    no `plt_` token involved anywhere in this test."""
    seen: list[Envelope] = []
    harness.event_bus.on(seen.append)

    async with harness.app.router.lifespan_context(harness.app):
        scripted = await _client(harness)
        async with scripted.http:
            as_metadata = await scripted.authorization_server_metadata(harness.server.issuer)
            await scripted.sign_in()
            response = await scripted.authorize(
                as_metadata,
                client_id=CIMD_CLIENT_ID,
                redirect_uri=CIMD_REDIRECT_URI,
                resource=harness.audience("alpha"),
            )
            code = await scripted.code_from(response)
            tokens = await scripted.exchange(
                as_metadata,
                code=code,
                client_id=CIMD_CLIENT_ID,
                redirect_uri=CIMD_REDIRECT_URI,
            )
            result = await scripted.call_tool(
                "alpha", str(tokens["access_token"]), "work_memory_search", {"query": "x"}
            )

    assert result.isError is not True

    connected = [e for e in seen if e.event == "client.connected"]
    assert len(connected) == 1, seen
    envelope = connected[0]
    assert envelope.origin == "auth"
    assert envelope.data["profile"] == "alpha"
    assert envelope.data["client_id"] == CIMD_CLIENT_ID
    assert envelope.data["auth_method"] == "oauth"
    # Never leak the bearer token or a client secret onto the (dashboard-
    # observable) event.
    assert "token" not in envelope.data
    assert "access_token" not in envelope.data
    assert "client_secret" not in envelope.data


@pytest.mark.anyio
async def test_oauth_verify_fires_client_connected_only_once_per_client(
    harness: Harness,
) -> None:
    """Repeat calls with the same client (fresh tokens, same client_id) do
    not re-fire the event — same "first use this process" contract the
    `plt_` side's `TokenStore.on_verified` already gives."""
    seen: list[Envelope] = []
    harness.event_bus.on(seen.append)

    async with harness.app.router.lifespan_context(harness.app):
        scripted = await _client(harness)
        async with scripted.http:
            as_metadata = await scripted.authorization_server_metadata(harness.server.issuer)
            await scripted.sign_in()

            for _ in range(2):
                response = await scripted.authorize(
                    as_metadata,
                    client_id=CIMD_CLIENT_ID,
                    redirect_uri=CIMD_REDIRECT_URI,
                    resource=harness.audience("alpha"),
                )
                code = await scripted.code_from(response)
                tokens = await scripted.exchange(
                    as_metadata,
                    code=code,
                    client_id=CIMD_CLIENT_ID,
                    redirect_uri=CIMD_REDIRECT_URI,
                )
                result = await scripted.call_tool(
                    "alpha", str(tokens["access_token"]), "work_memory_search", {"query": "x"}
                )
                assert result.isError is not True

    connected = [e for e in seen if e.event == "client.connected"]
    assert len(connected) == 1, seen


@pytest.mark.anyio
async def test_a_token_rejected_at_verification_does_not_fire_the_event(
    harness: Harness,
) -> None:
    """A profile-B call with an alpha-scoped token 401s and must not count
    as a connection."""
    seen: list[Envelope] = []
    harness.event_bus.on(seen.append)

    async with harness.app.router.lifespan_context(harness.app):
        scripted = await _client(harness)
        async with scripted.http:
            as_metadata = await scripted.authorization_server_metadata(harness.server.issuer)
            await scripted.sign_in()
            response = await scripted.authorize(
                as_metadata,
                client_id=CIMD_CLIENT_ID,
                redirect_uri=CIMD_REDIRECT_URI,
                resource=harness.audience("alpha"),
            )
            code = await scripted.code_from(response)
            tokens = await scripted.exchange(
                as_metadata,
                code=code,
                client_id=CIMD_CLIENT_ID,
                redirect_uri=CIMD_REDIRECT_URI,
            )
            bad = await scripted.http.get(
                "/mcp/beta/",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
            assert bad.status_code == 401

    connected = [e for e in seen if e.event == "client.connected"]
    assert connected == []


def test_build_jwt_verifier_without_on_verified_is_unchanged(harness: Harness) -> None:
    """The default (no hook) path stays exactly the plain `JWTVerifier` it
    always was — no wrapper class in the way when nobody asked for one."""
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    verifier = build_jwt_verifier(harness.key, harness.resources, "alpha")
    assert type(verifier) is JWTVerifier


def test_summarize_profile_auth_still_labels_a_hooked_verifier_as_oauth(
    harness: Harness,
) -> None:
    """`summarize_profile_auth`'s `isinstance(source, JWTVerifier)` check
    (SPEC-203 deliverable #6's startup summary) must still recognize the
    wrapped verifier as OAuth, not fall through to its defensive branch."""
    providers = build_profile_auth(
        ["alpha"],
        key=harness.key,
        resources=harness.resources,
        on_oauth_verified=lambda profile, access: None,
    )
    lines = summarize_profile_auth(providers)
    assert len(lines) == 1
    assert "oauth2 (access JWT)" in lines[0]
