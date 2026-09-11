"""The headline acceptance criterion, end to end over real HTTP semantics.

"A scripted OAuth client completes discovery → CIMD/DCR → PKCE code flow →
token → authenticated MCP call." :class:`ScriptedClient` below *is* that
scripted client: it starts from nothing but a profile URL, follows the RFC 9728
pointer out of the 401 it gets, reads the authorization server's metadata,
registers (both ways), runs the code flow with PKCE, exchanges the code, and
calls an MCP tool with the resulting access token — through
``httpx.ASGITransport`` and ``fastmcp.Client``, i.e. the real middleware stack
and the real wire protocol, with no socket and no subprocess.

The audience-isolation criterion ("token for profile A rejected by profile B")
rides on the same client at the bottom of the file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from auth._asgi_mcp_client import mcp_client_transport
from fastmcp import Client

from palaia_hub.oauth.login import CSRF_FIELD
from palaia_hub.oauth.pkce import challenge_for

from .harness import (
    CIMD_CLIENT_ID,
    CIMD_REDIRECT_URI,
    OWNER_PASSWORD,
    OWNER_USERNAME,
    Harness,
    approve_consent,
    is_consent_page,
)

BASE_URL = "https://testserver"
DCR_REDIRECT_URI = "http://127.0.0.1:7777/callback"
VERIFIER = "scripted-client-code-verifier-with-enough-entropy-x"


@dataclass
class ScriptedClient:
    """A minimal OAuth 2.1 + MCP client, driving the hub over ASGI."""

    http: httpx.AsyncClient
    harness: Harness

    # ------------------------------------------------------------- discovery

    async def discover_from_401(self, profile: str) -> str:
        """Hit the MCP endpoint unauthenticated; return the metadata URL it names."""
        response = await self.http.get(f"/mcp/{profile}/")
        assert response.status_code == 401, response.text
        challenge = response.headers["www-authenticate"]
        assert challenge.lower().startswith("bearer")
        assert "resource_metadata=" in challenge, challenge
        return challenge.split('resource_metadata="', 1)[1].split('"', 1)[0]

    async def protected_resource_metadata(self, metadata_url: str) -> dict[str, Any]:
        response = await self.http.get(urlsplit(metadata_url).path)
        assert response.status_code == 200, response.text
        return dict(response.json())

    async def authorization_server_metadata(self, issuer_url: str) -> dict[str, Any]:
        # RFC 8414 §3: insert /.well-known/oauth-authorization-server after the
        # issuer's authority. Our issuer has no base path, so this is the root.
        response = await self.http.get("/.well-known/oauth-authorization-server")
        assert response.status_code == 200, response.text
        metadata = dict(response.json())
        assert metadata["issuer"] == issuer_url
        return metadata

    # ---------------------------------------------------------- registration

    async def register_dynamically(self, metadata: dict[str, Any]) -> str:
        response = await self.http.post(
            urlsplit(str(metadata["registration_endpoint"])).path,
            json={"client_name": "scripted", "redirect_uris": [DCR_REDIRECT_URI]},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert "client_secret" not in body
        return str(body["client_id"])

    # ----------------------------------------------------------------- login

    async def sign_in(self) -> None:
        form = await self.http.get("/oauth/login")
        assert form.status_code == 200
        csrf = self.http.cookies["palaia_oauth_csrf"]
        response = await self.http.post(
            "/oauth/login",
            data={
                "username": OWNER_USERNAME,
                "password": OWNER_PASSWORD,
                CSRF_FIELD: csrf,
                "next": "",
            },
        )
        assert response.status_code == 303, response.text
        assert "palaia_oauth_session" in self.http.cookies

    # ------------------------------------------------------------- code flow

    async def authorize(
        self,
        metadata: dict[str, Any],
        *,
        client_id: str,
        redirect_uri: str,
        resource: str,
        verifier: str = VERIFIER,
        scope: str | None = None,
    ) -> httpx.Response:
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge_for(verifier),
            "code_challenge_method": "S256",
            "state": "opaque-state",
            "resource": resource,
        }
        if scope is not None:
            params["scope"] = scope
        page = await self.authorize_page(metadata, params)
        if not is_consent_page(page):
            return page
        # Issue #328: a browser user clicks "Allow" on the consent page; the
        # tests that only care about the resulting code get that click here.
        return await approve_consent(self.http, page)

    async def authorize_page(
        self, metadata: dict[str, Any], params: dict[str, str]
    ) -> httpx.Response:
        """The raw ``GET /oauth/authorize`` — the consent page, when signed in."""
        return await self.http.get(
            urlsplit(str(metadata["authorization_endpoint"])).path, params=params
        )

    async def code_from(self, response: httpx.Response) -> str:
        assert response.status_code == 303, response.text
        query = parse_qs(urlsplit(response.headers["location"]).query)
        assert "error" not in query, query
        assert query["state"] == ["opaque-state"]
        assert query["iss"] == [self.harness.server.issuer]
        return query["code"][0]

    async def exchange(
        self,
        metadata: dict[str, Any],
        *,
        code: str,
        client_id: str,
        redirect_uri: str,
        verifier: str = VERIFIER,
    ) -> dict[str, Any]:
        response = await self.http.post(
            urlsplit(str(metadata["token_endpoint"])).path,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
        )
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        return dict(response.json())

    # ------------------------------------------------------------- MCP calls

    async def call_tool(self, profile: str, access_token: str, tool: str, args: dict[str, Any]):
        transport = mcp_client_transport(
            self.harness.app, f"{BASE_URL}/mcp/{profile}/", token=access_token
        )
        async with Client(transport) as client:
            return await client.call_tool_mcp(tool, args)


async def _client(harness: Harness) -> ScriptedClient:
    http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app),
        base_url=BASE_URL,
        follow_redirects=False,
    )
    return ScriptedClient(http=http, harness=harness)


@pytest.mark.anyio
async def test_dcr_client_completes_the_whole_flow_and_calls_a_tool(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        scripted = await _client(harness)
        async with scripted.http:
            metadata_url = await scripted.discover_from_401("alpha")
            resource_metadata = await scripted.protected_resource_metadata(metadata_url)
            assert resource_metadata["resource"] == harness.audience("alpha")
            assert resource_metadata["authorization_servers"] == [harness.server.issuer]

            as_metadata = await scripted.authorization_server_metadata(
                str(resource_metadata["authorization_servers"][0])
            )
            assert as_metadata["code_challenge_methods_supported"] == ["S256"]
            assert as_metadata["client_id_metadata_document_supported"] is True

            client_id = await scripted.register_dynamically(as_metadata)
            await scripted.sign_in()
            response = await scripted.authorize(
                as_metadata,
                client_id=client_id,
                redirect_uri=DCR_REDIRECT_URI,
                resource=str(resource_metadata["resource"]),
            )
            code = await scripted.code_from(response)
            tokens = await scripted.exchange(
                as_metadata, code=code, client_id=client_id, redirect_uri=DCR_REDIRECT_URI
            )
            assert tokens["token_type"] == "Bearer"
            assert tokens["expires_in"] == harness.server.settings.access_token_ttl
            assert "refresh_token" in tokens

            result = await scripted.call_tool(
                "alpha",
                str(tokens["access_token"]),
                "work_memory_write",
                {"title": "Hello", "body": "World"},
            )

    assert result.isError is not True


@pytest.mark.anyio
async def test_cimd_client_needs_no_registration_step_at_all(harness: Harness) -> None:
    """The MCP 2026-07-28 path: the client_id *is* the metadata document URL."""
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
    # No registration request was made, and exactly one client row exists.
    assert harness.store.count_clients() == 1
    assert harness.store.get_client(CIMD_CLIENT_ID) is not None


@pytest.mark.anyio
async def test_a_token_for_profile_alpha_is_rejected_by_profile_beta(
    harness: Harness,
) -> None:
    """Audience isolation, end to end: same hub, same key, different resource."""
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
            access_token = str(tokens["access_token"])

            # Same credential, wrong resource: refused at the transport.
            beta = await scripted.http.get(
                "/mcp/beta/", headers={"Authorization": f"Bearer {access_token}"}
            )
            assert beta.status_code == 401
            assert 'error="invalid_token"' in beta.headers.get("www-authenticate", "")

            # And it still works on the profile it was issued for.
            alpha = await scripted.call_tool(
                "alpha", access_token, "work_memory_search", {"query": "x"}
            )
    assert alpha.isError is not True


@pytest.mark.anyio
async def test_the_resource_indicator_with_a_trailing_mcp_segment_works_end_to_end(
    harness: Harness,
) -> None:
    """`<issuer>/<name>/mcp` is what some clients send; it must resolve."""
    async with harness.app.router.lifespan_context(harness.app):
        scripted = await _client(harness)
        async with scripted.http:
            as_metadata = await scripted.authorization_server_metadata(harness.server.issuer)
            await scripted.sign_in()
            response = await scripted.authorize(
                as_metadata,
                client_id=CIMD_CLIENT_ID,
                redirect_uri=CIMD_REDIRECT_URI,
                resource=f"{harness.audience('alpha')}/mcp",
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


@pytest.mark.anyio
async def test_a_read_only_grant_cannot_call_a_write_tool(harness: Harness) -> None:
    """The SPEC-108 per-tool scope check reads OAuth scopes unchanged."""
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
                scope="vault:work:read",
            )
            code = await scripted.code_from(response)
            tokens = await scripted.exchange(
                as_metadata,
                code=code,
                client_id=CIMD_CLIENT_ID,
                redirect_uri=CIMD_REDIRECT_URI,
            )
            assert tokens["scope"] == "vault:work:read"
            result = await scripted.call_tool(
                "alpha",
                str(tokens["access_token"]),
                "work_memory_write",
                {"title": "t", "body": "b"},
            )

    assert result.isError is True
    text = "".join(getattr(block, "text", "") for block in result.content)
    assert "vault:work:write" in text


@pytest.mark.anyio
async def test_a_spec_108_token_still_works_on_an_oauth_enabled_profile(
    harness: Harness,
) -> None:
    """Both verifiers, one profile — an existing setup does not break."""
    created = harness.token_store.create("Codex", "alpha", ["vault:work:read"])

    async with harness.app.router.lifespan_context(harness.app):
        scripted = await _client(harness)
        async with scripted.http:
            result = await scripted.call_tool(
                "alpha", created.token, "work_memory_search", {"query": "x"}
            )

    assert result.isError is not True


@pytest.mark.anyio
async def test_an_unauthenticated_authorize_request_lands_on_the_sign_in_form(
    harness: Harness,
) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        scripted = await _client(harness)
        async with scripted.http:
            as_metadata = await scripted.authorization_server_metadata(harness.server.issuer)
            response = await scripted.authorize(
                as_metadata,
                client_id=CIMD_CLIENT_ID,
                redirect_uri=CIMD_REDIRECT_URI,
                resource=harness.audience("alpha"),
            )

            assert response.status_code == 303
            location = response.headers["location"]
            assert location.startswith("/oauth/login?next=")
            form = await scripted.http.get(location)
            assert form.status_code == 200
            assert "Sign in to palaia" in form.text


# ------------------------------------------------------- consent (issue #328)


def _authorize_params(client_id: str, redirect_uri: str, resource: str) -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge_for(VERIFIER),
        "code_challenge_method": "S256",
        "state": "opaque-state",
        "resource": resource,
    }


@pytest.mark.anyio
async def test_a_get_on_authorize_shows_the_consent_page_and_mints_nothing(
    harness: Harness,
) -> None:
    """A link alone never authorizes: the GET renders who is asking and what
    for; only the owner's POST issues a code."""
    async with harness.app.router.lifespan_context(harness.app):
        scripted = await _client(harness)
        async with scripted.http:
            as_metadata = await scripted.authorization_server_metadata(harness.server.issuer)
            client_id = await scripted.register_dynamically(as_metadata)
            await scripted.sign_in()
            page = await scripted.authorize_page(
                as_metadata,
                _authorize_params(client_id, DCR_REDIRECT_URI, harness.audience("alpha")),
            )
            assert page.status_code == 200
            assert "location" not in page.headers
            assert "scripted" in page.text  # the client's registered name
            assert "Allow" in page.text and "Deny" in page.text
            assert "Read the \u201calpha-work\u201d memory" in page.text or "memory" in page.text
            assert "code=" not in page.text

            approved = await approve_consent(scripted.http, page)
            code = await scripted.code_from(approved)
            assert code


@pytest.mark.anyio
async def test_the_consent_post_needs_the_sessions_csrf_token(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        scripted = await _client(harness)
        async with scripted.http:
            as_metadata = await scripted.authorization_server_metadata(harness.server.issuer)
            client_id = await scripted.register_dynamically(as_metadata)
            await scripted.sign_in()
            params = _authorize_params(client_id, DCR_REDIRECT_URI, harness.audience("alpha"))
            page = await scripted.authorize_page(as_metadata, params)
            assert is_consent_page(page)

            forged = await scripted.http.post(
                "/oauth/authorize",
                data={**params, "decision": "allow", "csrf_token": "not-the-cookie-value"},
            )
            assert forged.status_code == 403, forged.text
            assert "location" not in forged.headers
            assert "could not be confirmed" in forged.text

            missing = await scripted.http.post(
                "/oauth/authorize", data={**params, "decision": "allow"}
            )
            assert missing.status_code == 403


@pytest.mark.anyio
async def test_denying_consent_sends_the_client_access_denied(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        scripted = await _client(harness)
        async with scripted.http:
            as_metadata = await scripted.authorization_server_metadata(harness.server.issuer)
            client_id = await scripted.register_dynamically(as_metadata)
            await scripted.sign_in()
            page = await scripted.authorize_page(
                as_metadata,
                _authorize_params(client_id, DCR_REDIRECT_URI, harness.audience("alpha")),
            )
            denied = await approve_consent(scripted.http, page, decision="deny")

    assert denied.status_code == 303, denied.text
    query = parse_qs(urlsplit(denied.headers["location"]).query)
    assert query["error"] == ["access_denied"]
    assert query["state"] == ["opaque-state"]
    assert "code" not in query
