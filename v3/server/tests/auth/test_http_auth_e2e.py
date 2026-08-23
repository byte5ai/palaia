"""End-to-end SPEC-108 acceptance criteria over real HTTP semantics.

Uses an ASGI-transport-backed ``fastmcp.Client`` (see ``_asgi_mcp_client.py``)
so these tests exercise FastMCP's real ``RequireAuthMiddleware``/
``BearerAuthBackend`` stack — the actual 401 + ``WWW-Authenticate`` a real
client would see — without a subprocess or a real socket.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from starlette.applications import Starlette

from palaia_hub.app import create_app
from palaia_hub.auth.store import TokenStore
from palaia_hub.auth.wiring import build_profile_verifiers
from palaia_hub.config import HubConfig
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService

from ._asgi_mcp_client import mcp_client_transport


def _build_app(tmp_path: Path) -> tuple[Starlette, TokenStore]:
    store = TokenStore(home=tmp_path)
    gateway_config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work", purpose="Work vault.")],
        profiles=[
            ProfileConfig(path="alpha", vaults=["work"]),
            ProfileConfig(path="beta", vaults=["work"]),
        ],
    )
    services = {"work": FakeVaultService()}
    verifiers = build_profile_verifiers(["alpha", "beta"], store)
    gateway = build_gateway(gateway_config, services, token_verifiers=verifiers)
    # cloud mode: the mode SPEC-108 says MUST have auth on every endpoint —
    # exercising these tests under it is itself part of the acceptance
    # evidence that mode's policy doesn't block a properly-authed gateway.
    app = create_app(HubConfig(mode="cloud", host="127.0.0.1"), gateway=gateway)
    return app, store


@pytest.mark.anyio
async def test_missing_token_gets_401_with_rfc_compliant_www_authenticate(
    tmp_path: Path,
) -> None:
    app, _store = _build_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get("/mcp/alpha/")

    assert response.status_code == 401
    www_authenticate = response.headers.get("www-authenticate", "")
    assert www_authenticate.lower().startswith("bearer")
    # RFC 6750 §3.1: no Authorization header at all -> no `error` attribute
    # (that's reserved for a header that *is* present but invalid, checked
    # in the next test) — FastMCP's RequireAuthMiddleware implements this
    # distinction; this assertion documents it rather than fighting it.
    assert "error=" not in www_authenticate


@pytest.mark.anyio
async def test_wrong_token_gets_401_with_error_attribute(tmp_path: Path) -> None:
    app, _store = _build_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get(
                "/mcp/alpha/",
                headers={"Authorization": "Bearer plt_bogus-id.not-a-real-secret-value-at-all"},
            )

    assert response.status_code == 401
    # RFC 6750 §3.1: an Authorization header that *is* present but invalid
    # gets the `error` attribute (unlike the missing-header case above).
    www_authenticate = response.headers.get("www-authenticate", "")
    assert 'error="invalid_token"' in www_authenticate


@pytest.mark.anyio
async def test_valid_token_with_write_scope_can_write(tmp_path: Path) -> None:
    app, store = _build_app(tmp_path)
    created = store.create("client", "alpha", ["vault:work:read", "vault:work:write"])

    async with app.router.lifespan_context(app):
        transport = mcp_client_transport(app, "http://testserver/mcp/alpha/", token=created.token)
        async with Client(transport) as client:
            result = await client.call_tool_mcp(
                "work_memory_write", {"title": "Hello", "body": "World"}
            )

    assert result.isError is not True


@pytest.mark.anyio
async def test_read_only_token_calling_write_tool_gets_clean_mcp_error(
    tmp_path: Path,
) -> None:
    app, store = _build_app(tmp_path)
    created = store.create("client", "alpha", ["vault:work:read"])

    async with app.router.lifespan_context(app):
        transport = mcp_client_transport(app, "http://testserver/mcp/alpha/", token=created.token)
        async with Client(transport) as client:
            result = await client.call_tool_mcp(
                "work_memory_write", {"title": "Hello", "body": "World"}
            )

    # A clean MCP-level tool error naming the missing scope, not a crash
    # and not an HTTP-level failure — the whole point of per-tool
    # enforcement living inside the tool, not the transport middleware.
    assert result.isError is True
    text = "".join(getattr(block, "text", "") for block in result.content)
    assert "vault:work:write" in text


@pytest.mark.anyio
async def test_read_only_token_can_still_search(tmp_path: Path) -> None:
    app, store = _build_app(tmp_path)
    created = store.create("client", "alpha", ["vault:work:read"])

    async with app.router.lifespan_context(app):
        transport = mcp_client_transport(app, "http://testserver/mcp/alpha/", token=created.token)
        async with Client(transport) as client:
            result = await client.call_tool_mcp("work_memory_search", {"query": "anything"})

    assert result.isError is not True


@pytest.mark.anyio
async def test_token_bound_to_profile_alpha_cannot_reach_profile_beta(
    tmp_path: Path,
) -> None:
    app, store = _build_app(tmp_path)
    created = store.create("client", "alpha", ["vault:work:read", "vault:work:write"])

    async with app.router.lifespan_context(app):
        transport = mcp_client_transport(app, "http://testserver/mcp/beta/", token=created.token)
        with pytest.raises(Exception):  # noqa: B017 - transport-level auth failure, not ours to name
            async with Client(transport) as client:
                await client.call_tool_mcp("work_memory_search", {"query": "anything"})


@pytest.mark.anyio
async def test_revoked_token_is_refused_at_the_transport(tmp_path: Path) -> None:
    app, store = _build_app(tmp_path)
    created = store.create("client", "alpha", ["vault:work:read"])
    store.revoke(created.info.id)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get(
                "/mcp/alpha/", headers={"Authorization": f"Bearer {created.token}"}
            )

    assert response.status_code == 401
