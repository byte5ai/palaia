"""SPEC-302 acceptance criterion #3: a down upstream — the profile still
initializes, its other tools still work, and the status endpoint says which
server is down and why.

Also covers the recovery direction: an upstream that was down when the hub
started is picked up by the health monitor's pass and appears without a
restart, and the reverse (it goes away again) removes its tools rather than
leaving a mount that times out on every ``tools/list``.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.dynamic import DynamicGateway
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.upstream.models import UpstreamConfig
from palaia_hub.upstream.monitor import UpstreamHealthMonitor
from palaia_hub.upstream.service import UpstreamService

from .conftest import HttpUpstream

pytestmark = pytest.mark.anyio

#: Port 9 ("discard") refuses connections immediately on every platform the
#: hub targets — a fast, dependency-free "this endpoint is down".
DEAD_URL = "http://127.0.0.1:9/mcp/"


def _config(upstreams: list[UpstreamConfig]) -> GatewayConfig:
    return GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work", purpose="Work vault.")],
        profiles=[
            ProfileConfig(
                path="default", vaults=["work"], upstreams=[u.key for u in upstreams]
            )
        ],
        upstreams=upstreams,
    )


async def test_a_down_upstream_leaves_the_rest_of_the_profile_working() -> None:
    dead = UpstreamConfig(
        key="dead",
        kind="http",
        display_name="Unplugged service",
        url=DEAD_URL,
        connect_timeout=2.0,
    )
    service = UpstreamService([dead])
    gateway = DynamicGateway(
        _config([dead]), {"work": FakeVaultService()}, upstream_service=service
    )
    await gateway.start()
    monitor = UpstreamHealthMonitor(service, on_change=gateway.refresh_upstreams)
    try:
        changed = await monitor.probe_once()
        assert changed == ["dead"]

        async with Client(gateway.profile_servers["default"]) as client:
            names = {tool.name for tool in await client.list_tools()}
            # The vault's own tools are all there…
            assert "work_memory_search" in names
            # …and the unreachable server simply contributes nothing.
            assert not any(name.startswith("dead_") for name in names)
            result = await client.call_tool("work_memory_search", {"query": "anything"})
        assert result.content is not None

        status = service.status("dead")
        assert status.up is False
        assert status.display_name == "Unplugged service"
        assert status.detail  # one line, naming why
        assert len(status.detail.splitlines()) == 1
    finally:
        await monitor.aclose()
        await gateway.aclose()
        await service.aclose()


async def test_an_upstream_that_comes_up_later_appears_without_a_restart(
    http_upstream: HttpUpstream,
) -> None:
    """The hub-start case: nothing is mounted until a probe says it is up."""
    upstream = UpstreamConfig(
        key="fixture", kind="http", display_name="Fixture server", url=http_upstream.url
    )
    service = UpstreamService([upstream])
    gateway = DynamicGateway(
        _config([upstream]), {"work": FakeVaultService()}, upstream_service=service
    )
    await gateway.start()
    monitor = UpstreamHealthMonitor(service, on_change=gateway.refresh_upstreams)
    try:
        # Startup itself never probes (deliverable #4: it must not block), so
        # the profile begins with no upstream tools at all.
        async with Client(gateway.profile_servers["default"]) as client:
            before = {tool.name for tool in await client.list_tools()}
        assert not any(name.startswith("fixture_") for name in before)

        await monitor.probe_once()

        async with Client(gateway.profile_servers["default"]) as client:
            after = {tool.name for tool in await client.list_tools()}
        assert "fixture_echo" in after
    finally:
        await monitor.aclose()
        await gateway.aclose()
        await service.aclose()


async def test_an_upstream_that_dies_stops_being_offered(
    http_upstream: HttpUpstream,
) -> None:
    upstream = UpstreamConfig(
        key="fixture",
        kind="http",
        display_name="Fixture server",
        url=http_upstream.url,
        connect_timeout=2.0,
    )
    service = UpstreamService([upstream])
    gateway = DynamicGateway(
        _config([upstream]), {"work": FakeVaultService()}, upstream_service=service
    )
    await gateway.start()
    monitor = UpstreamHealthMonitor(service, on_change=gateway.refresh_upstreams)
    try:
        await monitor.probe_once()
        async with Client(gateway.profile_servers["default"]) as client:
            assert "fixture_echo" in {tool.name for tool in await client.list_tools()}

        http_upstream.stop()
        assert await monitor.probe_once() == ["fixture"]

        async with Client(gateway.profile_servers["default"]) as client:
            names = {tool.name for tool in await client.list_tools()}
        assert not any(name.startswith("fixture_") for name in names)
        assert "work_memory_search" in names
        assert service.status("fixture").up is False
    finally:
        await monitor.aclose()
        await gateway.aclose()
        await service.aclose()


async def test_reachability_changes_publish_up_and_down_events(
    http_upstream: HttpUpstream,
) -> None:
    published: list[tuple[str, dict[str, object]]] = []
    upstream = UpstreamConfig(
        key="fixture",
        kind="http",
        display_name="Fixture server",
        url=http_upstream.url,
        connect_timeout=2.0,
    )
    service = UpstreamService(
        [upstream], publish=lambda event, data: published.append((event, data))
    )
    try:
        await service.probe("fixture")
        assert published[-1][0] == "gateway.upstream.up"
        assert published[-1][1]["upstream"] == "fixture"

        # A second successful probe is silent — only changes are published.
        await service.probe("fixture")
        assert len(published) == 1

        http_upstream.stop()
        await service.probe("fixture")
        assert published[-1][0] == "gateway.upstream.down"
        assert published[-1][1]["tool_count"] == 0
    finally:
        await service.aclose()


async def test_a_switched_off_upstream_is_never_connected_at_all() -> None:
    off = UpstreamConfig(
        key="off",
        kind="http",
        display_name="Paused service",
        url=DEAD_URL,
        enabled=False,
    )
    service = UpstreamService([off])
    try:
        status = await service.probe("off")
        assert status.up is False
        assert "off" in status.detail.lower()
    finally:
        await service.aclose()
