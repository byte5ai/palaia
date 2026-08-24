"""When the curator runs, and how it is wired (SPEC-206 deliverable #1/#2).

Event-driven with a debounce, an interval fallback, and — the part that
matters most — the guard travelling with the profile: a curator profile
*rebuilt* at runtime comes back with its middleware still attached.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastmcp import Client

from palaia_hub.config import HubConfig
from palaia_hub.curator.apply import ProposalApplier
from palaia_hub.curator.policy import CURATOR_TOOL_ACTIONS
from palaia_hub.curator.profile import CURATOR_PROFILE_PATH, curator_profile
from palaia_hub.curator.service import CuratorScheduler
from palaia_hub.curator.wiring import TOKEN_ENV, build_curator, curator_token
from palaia_hub.events import EventBus, publish_event
from palaia_hub.gateway.config import GatewayConfig, VaultMountConfig
from palaia_hub.gateway.dynamic import DynamicGateway
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.vault import VaultEngine


class _CountingRunner:
    """Stands in for a CuratorRunner: counts passes, does nothing else."""

    def __init__(self) -> None:
        self.runs = 0

    async def run_once(self) -> Any:
        self.runs += 1
        return None


@pytest.mark.anyio
async def test_an_inbox_captured_event_triggers_a_debounced_pass() -> None:
    runner = _CountingRunner()
    bus = EventBus()
    scheduler = CuratorScheduler(
        {"work": runner},  # type: ignore[dict-item]
        debounce_seconds=0.01,
        interval_seconds=3600,
        subscribe=bus.on,
    )
    await scheduler.start()
    try:
        publish_event(bus, "inbox.captured", origin="test", data={"capture_id": "cap-1"})
        publish_event(bus, "inbox.captured", origin="test", data={"capture_id": "cap-2"})
        for _ in range(200):
            if runner.runs:
                break
            await asyncio.sleep(0.01)
    finally:
        await scheduler.aclose()
    # A burst coalesced into one pass, not one per capture.
    assert runner.runs == 1


@pytest.mark.anyio
async def test_a_duplicate_capture_does_not_wake_the_curator() -> None:
    runner = _CountingRunner()
    bus = EventBus()
    scheduler = CuratorScheduler(
        {"work": runner},  # type: ignore[dict-item]
        debounce_seconds=0.0,
        interval_seconds=3600,
        subscribe=bus.on,
    )
    await scheduler.start()
    try:
        publish_event(
            bus,
            "inbox.captured",
            origin="test",
            data={"capture_id": "cap-1", "duplicate": True},
        )
        await asyncio.sleep(0.1)
    finally:
        await scheduler.aclose()
    assert runner.runs == 0


@pytest.mark.anyio
async def test_the_interval_fallback_runs_without_any_event() -> None:
    runner = _CountingRunner()
    scheduler = CuratorScheduler(
        {"work": runner},  # type: ignore[dict-item]
        debounce_seconds=0.0,
        interval_seconds=1.0,
    )
    # The floor is one second, so drive the loop directly rather than waiting
    # it out: what matters here is that a pass needs no event to happen.
    await scheduler.run_all()
    assert runner.runs == 1
    await scheduler.aclose()


@pytest.mark.anyio
async def test_one_failing_vault_does_not_stop_the_others() -> None:
    class _Boom:
        async def run_once(self) -> Any:
            raise RuntimeError("vault on fire")

    good = _CountingRunner()
    scheduler = CuratorScheduler(
        {"broken": _Boom(), "work": good},  # type: ignore[dict-item]
    )
    runs, _applies = await scheduler.run_all()
    # The healthy vault still ran; the broken one contributed no report.
    assert good.runs == 1
    assert len(runs) == 1


@pytest.mark.anyio
async def test_the_guard_survives_a_profile_rebuild(
    engine: VaultEngine, vault_mount: VaultMountConfig
) -> None:
    """A vault added at runtime rebuilds profiles — the policy must return."""
    config = GatewayConfig(
        vaults=[vault_mount], profiles=[curator_profile([vault_mount.key])]
    )
    hub_config = HubConfig(curator={"enabled": True})
    wiring = build_curator(
        hub_config, {vault_mount.key: engine}, [vault_mount], with_stash=False
    )
    gateway = DynamicGateway(
        config,
        {vault_mount.key: FakeVaultService()},
        profile_middleware=wiring.profile_middleware,
    )
    await gateway.start()
    try:
        second = VaultMountConfig(key="personal", name="personal")
        await gateway.add_vault(
            second, FakeVaultService(), profile_paths=[CURATOR_PROFILE_PATH]
        )
        profile = gateway.profile_servers[CURATOR_PROFILE_PATH]
        async with Client(profile) as client:
            names = {tool.name for tool in await client.list_tools()}
            refused = await client.call_tool(
                f"{vault_mount.namespace}_delete",
                {"permalink": "projects/x"},
                raise_on_error=False,
            )
    finally:
        await gateway.aclose()
    # The rebuilt profile still hides the forbidden tools of the vault it
    # knows about, and still refuses them.
    assert f"{vault_mount.namespace}_write" in names
    assert f"{vault_mount.namespace}_delete" not in names
    assert refused.is_error
    # The vault added at runtime is fail-closed: its tools are unmapped, so
    # nothing of it is exposed until the hub restarts (documented limitation).
    assert not any(name.startswith("personal_memory_") for name in names)
    assert len(names) == len(CURATOR_TOOL_ACTIONS)


def test_the_token_comes_from_the_environment_first(monkeypatch) -> None:  # noqa: ANN001
    config = HubConfig(curator={"token": "from-config"})
    assert curator_token(config) == "from-config"
    monkeypatch.setenv(TOKEN_ENV, "from-env")
    assert curator_token(config) == "from-env"


@pytest.mark.anyio
async def test_wiring_builds_runners_appliers_and_the_guard(
    engine: VaultEngine, vault_mount: VaultMountConfig
) -> None:
    config = HubConfig(curator={"enabled": True, "auto_apply": True, "max_attempts": 2})
    wiring = build_curator(
        config, {vault_mount.key: engine}, [vault_mount], with_stash=False
    )
    try:
        assert set(wiring.runners) == {vault_mount.key}
        assert isinstance(wiring.appliers[vault_mount.key], ProposalApplier)
        assert CURATOR_PROFILE_PATH in wiring.profile_middleware
        # The same ActiveCaptures instance reaches both the runner and the
        # middleware — that is what binds a session to its own capture.
        middleware = wiring.profile_middleware[CURATOR_PROFILE_PATH][0]
        assert middleware.active_captures is wiring.active_captures  # type: ignore[attr-defined]
    finally:
        await wiring.aclose()


@pytest.mark.anyio
async def test_auto_apply_off_means_no_scheduled_applier(
    engine: VaultEngine, vault_mount: VaultMountConfig
) -> None:
    config = HubConfig(curator={"enabled": True, "auto_apply": False})
    wiring = build_curator(
        config, {vault_mount.key: engine}, [vault_mount], with_stash=False
    )
    try:
        assert wiring.appliers == {}
    finally:
        await wiring.aclose()
