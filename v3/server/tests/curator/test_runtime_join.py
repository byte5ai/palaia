"""SPEC-301 deliverable #4 — closing SPEC-206's documented gap: a vault
created at runtime joins the curator profile (and its guard's tool-action
map) *and* actually gets curated, without a hub restart.

``test_the_guard_survives_a_profile_rebuild`` in ``test_scheduler_and_wiring.py``
already covers the raw :class:`~palaia_hub.gateway.dynamic.DynamicGateway`
behavior when *nothing* tells the curator about the new vault (still
fail-closed, by design — nobody asked it to know). This file is the other
half: what happens once the caller — :mod:`palaia_hub.dashboard_api`'s
``create_vault`` handler, in production — actually calls
:meth:`~palaia_hub.curator.wiring.CuratorWiring.add_vault`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripted import ScriptedSessionRunner, ingest_session

from palaia_hub.config import HubConfig
from palaia_hub.curator.profile import CURATOR_PROFILE_PATH, curator_profile
from palaia_hub.curator.wiring import build_curator
from palaia_hub.gateway.config import GatewayConfig, VaultMountConfig
from palaia_hub.gateway.dynamic import DynamicGateway
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.vault import VaultEngine


@pytest.mark.anyio
async def test_runtime_vault_is_curated_without_restart(
    engine: VaultEngine, vault_mount: VaultMountConfig, tmp_path: Path
) -> None:
    hub_config = HubConfig(curator={"enabled": True})
    session_runner = ScriptedSessionRunner(server=None, script=lambda *_: None)  # type: ignore[arg-type]

    wiring = build_curator(
        hub_config,
        {vault_mount.key: engine},
        [vault_mount],
        home=tmp_path,
        session_runner=session_runner,
        with_stash=False,
    )
    gateway = DynamicGateway(
        GatewayConfig(vaults=[vault_mount], profiles=[curator_profile([vault_mount.key])]),
        {vault_mount.key: FakeVaultService()},
        profile_middleware=wiring.profile_middleware,
    )
    await gateway.start()
    # Same trick production's real HTTP transport gets for free: the
    # scripted runner always talks to whichever profile generation is
    # *currently* mounted, not the one that existed when it was built.
    session_runner.server_factory = lambda: gateway.profile_servers[CURATOR_PROFILE_PATH]

    try:
        # A second vault, created "at runtime" — after the curator and the
        # gateway both already exist, exactly like the wizard's
        # `POST /api/vaults` handler creates one mid-flight.
        personal_root = tmp_path / "personal"
        personal_root.mkdir()
        personal_engine = VaultEngine(personal_root, name="personal")
        await personal_engine.open(purpose="Personal notes.", create=True)
        personal_mount = VaultMountConfig(
            key="personal", name="personal", purpose="Personal notes."
        )
        # The same real engine backs both the gateway's mounted tool server
        # and the runner's own verification pass — a fake here would make
        # the write and the verification look at two different vaults.
        personal_service = EngineVaultService(personal_engine)

        # The two calls production makes, in the same order
        # (palaia_hub.dashboard_api.build_dashboard_router's create_vault):
        # wire the curator first, then mount the vault on the gateway.
        await wiring.add_vault(personal_engine, personal_mount)
        await gateway.add_vault(
            personal_mount, personal_service, profile_paths=[CURATOR_PROFILE_PATH]
        )

        assert "personal" in wiring.runners
        session_runner.script = ingest_session(personal_mount.namespace)

        await personal_service.capture(
            what_it_concerns="the personal vault's rate limit",
            why_keep="needed to answer a support question later",
            content="The personal vault's ingest limit is 100 req/min.",
        )

        report = await wiring.runners["personal"].run_once()
    finally:
        await gateway.aclose()
        await personal_engine.close()

    assert report.records
    assert report.records[0].outcome == "ingested"
    # The curator profile's guard now recognizes the runtime-added vault's
    # tools (previously unmapped and fail-closed) — the ingest session's
    # write actually landed, not refused.
    calls = session_runner.calls
    write_calls = [c for c in calls if c[0] == "personal_memory_write"]
    assert write_calls and not write_calls[0][2], "the write must not have been refused"
