"""S3 "hub killed mid-writes -> restart -> doctor verify clean" (SPEC-113).

One layer above SPEC-102's own engine-level kill test
(``tests/vault/test_kill_safety.py``): here the *hub process* is SIGKILLed
while a burst of writes is arriving over real streamable HTTP through the
gateway, then a fresh hub is started against the same vault directory.
Afterwards: every acknowledged write is present and readable through the
new hub, and a doctor pass directly against the vault reports no fatal
findings (the same tolerances the engine-level test uses — a still-held
git lock alone is not fatal, crash recovery on open clears it).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from simulator import SimulatedClient

if TYPE_CHECKING:
    from conftest import HubFactory

pytestmark = pytest.mark.anyio

_BURST_WORKER = Path(__file__).parent / "support" / "mcp_write_burst.py"
_BURST_DURATION_SECONDS = 3.0


async def test_kill_mid_write_burst_then_restart_recovers_cleanly(
    golden_work_vault: Path, hub_factory: HubFactory, tmp_path: Path
) -> None:
    from palaia_hub.vault import VaultDoctor, VaultEngine

    hub1 = hub_factory(vault_dir=golden_work_vault, log_name="hub1.log")

    progress_path = tmp_path / "progress.jsonl"
    progress_path.touch()
    worker = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [
            sys.executable,
            str(_BURST_WORKER),
            "--url",
            hub1.profile_url(),
            "--progress",
            str(progress_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(_BURST_DURATION_SECONDS)
        hub1.kill()
    finally:
        try:
            worker.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            worker.kill()
            worker.wait(timeout=5)

    acknowledged = [
        json.loads(line) for line in progress_path.read_text(encoding="utf-8").splitlines() if line
    ]
    assert acknowledged, "worker produced no acknowledged writes before the kill"

    # Restart a fresh hub against the SAME vault directory.
    hub2 = hub_factory(vault_dir=golden_work_vault, log_name="hub2.log")

    async with SimulatedClient(hub2.profile_url(), client_name="recover-check") as client:
        for record in acknowledged:
            result = await client.call_tool_ok(
                "work_memory_read", {"permalink": record["permalink"]}
            )
            assert result.structured is not None
            assert result.structured["title"] == record["title"], (
                f"acknowledged write {record['permalink']!r} did not survive the kill"
            )

    hub2.stop()

    # Doctor pass directly against the vault: no fatal findings, same
    # tolerance the engine-level kill test uses (a held git lock alone is
    # not fatal — crash recovery on open already cleared it by this point).
    engine = VaultEngine(golden_work_vault, "work")
    await engine.open()
    findings = await VaultDoctor(engine).verify()
    fatal = [f for f in findings if f.severity == "error" and f.code != "git-lock-held"]
    assert fatal == [], fatal
    await engine.close()
