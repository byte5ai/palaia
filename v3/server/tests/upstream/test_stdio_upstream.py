"""SPEC-302 acceptance criterion #4: a ``stdio`` upstream — command spawned,
env-var secret injected, tools callable e2e, process reaped on shutdown.

The fixture server (``fixture_stdio_server.py``) reports the value of
``FIXTURE_TOKEN`` back through a tool, so "the secret was injected" is proven
by the call's own result rather than by inspecting our own plumbing.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest
from fastmcp import Client

from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.dynamic import DynamicGateway
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.upstream.models import UpstreamConfig
from palaia_hub.upstream.secrets import SecretStore
from palaia_hub.upstream.service import UpstreamService

pytestmark = pytest.mark.anyio

STDIO_SECRET = "stdio-secret-value-9182"


def _stdio_upstream(stdio_command: list[str]) -> UpstreamConfig:
    return UpstreamConfig(
        key="localbox",
        kind="stdio",
        display_name="Local box",
        command=stdio_command[0],
        args=stdio_command[1:],
        env_secrets={"FIXTURE_TOKEN": "localbox-token"},
    )


async def test_a_stdio_upstream_spawns_and_serves_tools_with_its_secret(
    stdio_command: list[str], secret_store: SecretStore
) -> None:
    secret_store.put("localbox-token", STDIO_SECRET)
    upstream = _stdio_upstream(stdio_command)
    service = UpstreamService([upstream], secret_store=secret_store)
    gateway = DynamicGateway(
        GatewayConfig(
            vaults=[VaultMountConfig(key="work", name="work", purpose="Work vault.")],
            profiles=[ProfileConfig(path="default", vaults=["work"], upstreams=["localbox"])],
            upstreams=[upstream],
        ),
        {"work": FakeVaultService()},
        upstream_service=service,
    )
    await gateway.start()
    await service.probe_all()
    await gateway.refresh_upstreams(["localbox"])
    try:
        assert service.status("localbox").up is True
        async with Client(gateway.profile_servers["default"]) as client:
            names = {tool.name for tool in await client.list_tools()}
            assert {"localbox_whoami", "localbox_add"} <= names

            identity = await client.call_tool("localbox_whoami", {})
            total = await client.call_tool("localbox_add", {"a": 2, "b": 3})
        assert f"token={STDIO_SECRET}" in str(identity.content)
        assert "5" in str(total.content)
    finally:
        await gateway.aclose()
        await service.aclose()


def _own_children() -> set[int]:
    """PIDs of this process's direct children, read from ``/proc``.

    Linux-only, which is what the hub's own container target is; the test
    using it skips elsewhere rather than pretending to check something.
    """
    task_dir = Path(f"/proc/{os.getpid()}/task")
    children: set[int] = set()
    for task in task_dir.iterdir():
        try:
            raw = (task / "children").read_text()
        except OSError:  # pragma: no cover - task exited mid-read
            continue
        children.update(int(pid) for pid in raw.split())
    return children


@pytest.mark.skipif(
    not Path("/proc/self/task").exists(), reason="needs /proc to observe child processes"
)
async def test_the_child_process_is_spawned_and_reaped_on_shutdown(
    stdio_command: list[str], secret_store: SecretStore
) -> None:
    secret_store.put("localbox-token", STDIO_SECRET)
    upstream = _stdio_upstream(stdio_command)
    service = UpstreamService([upstream], secret_store=secret_store)
    before = _own_children()

    await service.probe_all()
    proxy = await service.proxy_for("localbox")
    # A real call, so the child is definitely running before we tear down.
    async with Client(proxy) as client:
        await client.call_tool("whoami", {})
    spawned = _own_children() - before
    assert spawned, "the stdio upstream's command was never spawned"

    await service.aclose()

    # The child is gone — not merely forgotten by us. It may take a moment
    # for the kernel to reap it after the transport signalled its stop.
    deadline = time.time() + 15
    while time.time() < deadline and (_own_children() & spawned):
        await asyncio.sleep(0.1)
    assert not (_own_children() & spawned), "the stdio upstream's process outlived shutdown"

    # After aclose the cached transport is gone; asking again builds a fresh
    # one rather than handing back a dead session.
    rebuilt = await service.proxy_for("localbox")
    assert rebuilt is not proxy
    await service.aclose()


async def test_a_stdio_upstream_whose_command_does_not_exist_is_down_not_fatal(
    secret_store: SecretStore,
) -> None:
    upstream = UpstreamConfig(
        key="ghost",
        kind="stdio",
        display_name="Ghost box",
        command="/nonexistent/palaia-test-binary",
        connect_timeout=3.0,
    )
    service = UpstreamService([upstream], secret_store=secret_store)
    try:
        status = await service.probe("ghost")
        assert status.up is False
        assert status.detail
        assert status.tools == ()
    finally:
        await service.aclose()
