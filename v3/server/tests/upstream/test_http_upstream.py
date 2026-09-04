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
from fastmcp.server.http import set_http_request
from starlette.requests import Request

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


async def _started_gateway(upstream: UpstreamConfig, service: UpstreamService) -> DynamicGateway:
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


# ------------------------------------------------ inbound headers (issue #314)


def _inbound_request(headers: dict[str, str]) -> Request:
    """A Starlette request carrying ``headers``, standing in for the HTTP
    request a real MCP client made to the hub."""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()],
        "client": ("127.0.0.1", 5555),
        "server": ("127.0.0.1", 8420),
        "root_path": "",
    }
    return Request(scope)


async def _upstream_headers_seen(
    gateway: DynamicGateway, inbound: dict[str, str]
) -> dict[str, str]:
    """Call the fixture's ``headers`` tool through the profile while the hub
    believes ``inbound`` is the current client request.

    fastmcp's proxy reads the inbound request through
    ``fastmcp.server.dependencies.get_http_headers`` — a ContextVar that a
    real deployment sets per HTTP request and that the in-memory transport
    used here leaves unset. Setting it around the client's lifetime is
    exactly what a real ``Authorization: Bearer plt_…`` call looks like to
    the proxy, minus the socket.
    """
    with set_http_request(_inbound_request(inbound)):
        async with Client(gateway.profile_servers["default"]) as client:
            result = await client.call_tool("fixture_headers", {})
    seen = result.structured_content or {}
    if "result" in seen and isinstance(seen["result"], dict):
        seen = seen["result"]
    return {str(k).lower(): str(v) for k, v in seen.items()}


async def test_a_clients_authorization_header_is_not_forwarded_to_an_upstream(
    http_upstream: HttpUpstream,
) -> None:
    """Issue #314: an upstream with no ``auth:`` must not receive the
    connecting client's own palaia credential (its ``plt_`` token or OAuth
    JWT), nor any other header the client sent to the hub."""
    upstream = UpstreamConfig(
        key="fixture",
        kind="http",
        display_name="Fixture server",
        url=http_upstream.url,
    )
    service = UpstreamService([upstream])
    gateway = await _started_gateway(upstream, service)
    try:
        seen = await _upstream_headers_seen(
            gateway,
            {"Authorization": "Bearer inbound-secret", "X-Palaia-Client": "leaky-client"},
        )
        assert seen, "the fixture reported no headers at all"
        assert "authorization" not in seen
        assert "x-palaia-client" not in seen
        assert "inbound-secret" not in " ".join(seen.values())
    finally:
        await gateway.aclose()
        await service.aclose()


async def test_a_configured_auth_header_still_reaches_the_upstream(
    http_upstream: HttpUpstream, secret_store: SecretStore
) -> None:
    """The counterpart of the test above: switching off header forwarding
    must not take the *configured* credential with it."""
    secret_store.put("fixture-token", FIXTURE_BEARER_TOKEN)
    upstream = UpstreamConfig(
        key="fixture",
        kind="http",
        display_name="Fixture server",
        url=http_upstream.url,
        auth=UpstreamAuthConfig(secret_name="fixture-token"),
    )
    service = UpstreamService([upstream], secret_store=secret_store)
    gateway = await _started_gateway(upstream, service)
    try:
        seen = await _upstream_headers_seen(gateway, {"Authorization": "Bearer inbound-secret"})
        assert seen.get("authorization") == f"Bearer {FIXTURE_BEARER_TOKEN}"
    finally:
        await gateway.aclose()
        await service.aclose()
