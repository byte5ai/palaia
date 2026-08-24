"""SPEC-302 acceptance criterion #1: a real second FastMCP server, connected
as an ``http`` upstream, callable through a profile by a real
``fastmcp.Client``, namespaced, with a working rename.

The fixture upstream runs in **its own OS process** (see ``conftest.py``), so
a result carrying its literal ``fixture-http-upstream echo:`` prefix proves
the call actually left the hub. The authenticated variant proves the value
from the encrypted store reached the wire: the fixture rejects any request
whose bearer token does not match.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.dynamic import DynamicGateway
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.upstream.models import UpstreamAuthConfig, UpstreamConfig
from palaia_hub.upstream.secrets import SecretStore
from palaia_hub.upstream.service import UpstreamService

from .conftest import FIXTURE_BEARER_TOKEN, HttpUpstream

pytestmark = pytest.mark.anyio


def _gateway_config(upstream: UpstreamConfig) -> GatewayConfig:
    return GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work", purpose="Work vault.")],
        profiles=[ProfileConfig(path="default", vaults=["work"], upstreams=[upstream.key])],
        upstreams=[upstream],
    )


async def _started_gateway(
    upstream: UpstreamConfig, service: UpstreamService
) -> DynamicGateway:
    gateway = DynamicGateway(
        _gateway_config(upstream),
        {"work": FakeVaultService()},
        upstream_service=service,
    )
    await gateway.start()
    # Startup deliberately mounts no upstream (it never probes — see
    # DynamicGateway's docstring); this is what the health monitor's first
    # pass does in production.
    await service.probe_all()
    await gateway.refresh_upstreams([upstream.key])
    return gateway


async def test_an_http_upstream_is_callable_through_a_profile(
    http_upstream: HttpUpstream,
) -> None:
    upstream = UpstreamConfig(
        key="fixture",
        kind="http",
        display_name="Fixture server",
        url=http_upstream.url,
    )
    service = UpstreamService([upstream])
    gateway = await _started_gateway(upstream, service)
    try:
        async with Client(gateway.profile_servers["default"]) as client:
            names = {tool.name for tool in await client.list_tools()}
            assert "fixture_echo" in names
            assert "fixture_ping" in names
            # The profile's own memory tools are untouched.
            assert "work_memory_search" in names

            result = await client.call_tool("fixture_echo", {"text": "through the hub"})
        assert "fixture-http-upstream echo: through the hub" in str(result.content)
    finally:
        await gateway.aclose()
        await service.aclose()


async def test_the_profile_tells_a_client_whose_tools_those_are(
    http_upstream: HttpUpstream,
) -> None:
    """Deliverable #6: descriptions pass through, provenance is in the
    profile's IDENTITY block — and a real client can read it."""
    upstream = UpstreamConfig(
        key="fixture",
        kind="http",
        display_name="Fixture server",
        url=http_upstream.url,
    )
    service = UpstreamService([upstream])
    gateway = await _started_gateway(upstream, service)
    try:
        async with Client(gateway.profile_servers["default"]) as client:
            instructions = client.initialize_result.instructions or ""
            tools = {tool.name: tool.description or "" for tool in await client.list_tools()}
        assert "Fixture server" in instructions
        assert "connected by you" in instructions
        # The upstream's own description is untouched by palaia.
        assert "Echo text back" in tools["fixture_echo"]
    finally:
        await gateway.aclose()
        await service.aclose()


async def test_an_upstream_tool_can_be_renamed(http_upstream: HttpUpstream) -> None:
    upstream = UpstreamConfig(
        key="fixture",
        kind="http",
        display_name="Fixture server",
        url=http_upstream.url,
        # Pre-namespace value, per FINDINGS Q4 — the mount composes
        # "fixture_" in front of it. Typing the already-namespaced name here
        # is the documented foot-gun this contract avoids.
        tool_renames={"echo": "say"},
    )
    service = UpstreamService([upstream])
    gateway = await _started_gateway(upstream, service)
    try:
        async with Client(gateway.profile_servers["default"]) as client:
            names = {tool.name for tool in await client.list_tools()}
            assert "fixture_say" in names
            assert "fixture_echo" not in names
            assert "fixture_fixture_say" not in names

            result = await client.call_tool("fixture_say", {"text": "renamed"})
        assert "fixture-http-upstream echo: renamed" in str(result.content)
    finally:
        await gateway.aclose()
        await service.aclose()


async def test_a_bearer_token_from_the_secret_store_reaches_the_upstream(
    http_upstream_with_token: HttpUpstream, secret_store: SecretStore
) -> None:
    secret_store.put("fixture-token", FIXTURE_BEARER_TOKEN)
    upstream = UpstreamConfig(
        key="fixture",
        kind="http",
        display_name="Fixture server",
        url=http_upstream_with_token.url,
        auth=UpstreamAuthConfig(secret_name="fixture-token"),
    )
    service = UpstreamService([upstream], secret_store=secret_store)
    gateway = await _started_gateway(upstream, service)
    try:
        assert service.status("fixture").up is True
        async with Client(gateway.profile_servers["default"]) as client:
            result = await client.call_tool("fixture_echo", {"text": "authenticated"})
        assert "fixture-http-upstream echo: authenticated" in str(result.content)
    finally:
        await gateway.aclose()
        await service.aclose()


async def test_a_wrong_token_leaves_the_upstream_down_with_a_reason(
    http_upstream_with_token: HttpUpstream, secret_store: SecretStore
) -> None:
    secret_store.put("fixture-token", "not-the-right-token")
    upstream = UpstreamConfig(
        key="fixture",
        kind="http",
        display_name="Fixture server",
        url=http_upstream_with_token.url,
        auth=UpstreamAuthConfig(secret_name="fixture-token"),
    )
    service = UpstreamService([upstream], secret_store=secret_store)
    try:
        status = await service.probe("fixture")
        assert status.up is False
        assert status.detail
        # The rejected credential is never quoted back.
        assert "not-the-right-token" not in status.detail
    finally:
        await service.aclose()


async def test_a_missing_secret_is_reported_by_name_not_by_crashing(
    http_upstream_with_token: HttpUpstream, secret_store: SecretStore
) -> None:
    upstream = UpstreamConfig(
        key="fixture",
        kind="http",
        display_name="Fixture server",
        url=http_upstream_with_token.url,
        auth=UpstreamAuthConfig(secret_name="never-entered"),
    )
    service = UpstreamService([upstream], secret_store=secret_store)
    try:
        status = await service.probe("fixture")
        assert status.up is False
        assert "never-entered" in status.detail
    finally:
        await service.aclose()
