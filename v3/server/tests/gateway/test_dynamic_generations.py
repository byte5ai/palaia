"""Issue #352: a rebuilt profile's previous generation is closed, not kept.

Every rebuild-and-swap used to leave the old FastMCP session manager open
until the gateway itself shut down — bounded only by the number of
rebuilds, which an upstream flapping in and out of reach drives once a
minute. Now each generation owns its own lifespan and closes itself as soon
as no request is in flight against it.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastmcp import Client

from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.dynamic import DynamicGateway, _Generation
from palaia_hub.gateway.fake_vault import FakeVaultService

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _gateway() -> DynamicGateway:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work", purpose="Work vault.")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    return DynamicGateway(config, {"work": FakeVaultService()})


async def test_a_swapped_out_generation_with_nothing_in_flight_closes_itself() -> None:
    gateway = _gateway()
    await gateway.start()
    try:
        first = gateway._generations["default"]
        await gateway.upsert_profile("default", ["work"])

        await asyncio.wait_for(first.closed.wait(), timeout=5)
        assert gateway._generations["default"] is not first
        assert gateway.retired_generations == 0
    finally:
        await gateway.aclose()


async def test_many_rebuilds_leave_exactly_one_open_generation() -> None:
    """The flapping-upstream case: a rebuild per minute must not grow anything."""
    gateway = _gateway()
    await gateway.start()
    try:
        seen = [gateway._generations["default"]]
        for _ in range(25):
            await gateway.upsert_profile("default", ["work"])
            seen.append(gateway._generations["default"])

        for generation in seen[:-1]:
            await asyncio.wait_for(generation.closed.wait(), timeout=5)
        assert gateway.retired_generations == 0
        assert not seen[-1].closed.is_set(), "the live generation stays open"

        async with Client(gateway.profile_servers["default"]) as client:
            assert any(t.name == "work_memory_search" for t in await client.list_tools())
    finally:
        await gateway.aclose()


class _FakeApp:
    """Stands in for a FastMCP ASGI app: a lifespan that records its state,
    and requests that hold until released."""

    def __init__(self) -> None:
        self.entered = False
        self.exited = False
        self.release = asyncio.Event()

    @contextlib.asynccontextmanager
    async def lifespan(self, app: Any) -> AsyncIterator[None]:
        self.entered = True
        try:
            yield
        finally:
            self.exited = True

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await self.release.wait()


async def test_a_retired_generation_waits_for_its_in_flight_request() -> None:
    app = _FakeApp()
    generation = _Generation("default", None, app)  # type: ignore[arg-type]
    await generation.start()
    assert app.entered

    request = asyncio.create_task(generation({}, None, None))
    await asyncio.sleep(0)
    assert generation.in_flight == 1

    generation.retire()
    await asyncio.sleep(0.05)
    assert not app.exited, "closing under a live request would be strictly worse"

    app.release.set()
    await request
    await asyncio.wait_for(generation.closed.wait(), timeout=2)
    assert app.exited


async def test_a_lifespan_that_fails_to_start_raises_and_leaves_nothing_behind() -> None:
    class _BrokenApp(_FakeApp):
        @contextlib.asynccontextmanager
        async def lifespan(self, app: Any) -> AsyncIterator[None]:
            raise RuntimeError("no session manager for you")
            yield  # pragma: no cover - unreachable, keeps this a generator

    generation = _Generation("default", None, _BrokenApp())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="no session manager"):
        await generation.start()
    assert generation.closed.is_set()


async def test_aclose_closes_live_and_retired_generations_alike() -> None:
    gateway = _gateway()
    await gateway.start()
    live_before = gateway._generations["default"]
    await gateway.upsert_profile("default", ["work"])
    live_after = gateway._generations["default"]

    await gateway.aclose()

    assert live_before.closed.is_set()
    assert live_after.closed.is_set()
    assert gateway.retired_generations == 0
