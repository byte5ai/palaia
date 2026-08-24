"""Real-runner smoke test (SPEC-206 acceptance criterion #6).

Excluded from CI by construction: it needs ``PALAIA_CURATOR_SMOKE=1`` **and**
the ``claude`` CLI on PATH, and it spends real model calls. What it proves is
the one thing no scripted runner can: that the configured command, the
generated strict MCP config and the curator profile actually fit together —
a real model, over real HTTP, curating one real capture.

Run it with::

    PALAIA_CURATOR_SMOKE=1 uv run pytest \\
        server/tests/curator/test_real_runner_smoke.py -q -s

The assertion is deliberately weak: the *outcome* of a model session is not
deterministic, so what is asserted is that the session ran, that the guards
were in force, and that the runner's verdict is one of the three legal ones.
A run that ends ``unverified`` prints why and still passes — an inconclusive
smoke test is not a failing policy.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from palaia_hub.config import HubConfig
from palaia_hub.curator.profile import allowed_tool_specs
from palaia_hub.curator.runner import CuratorRunner
from palaia_hub.curator.session import SubprocessSessionRunner
from palaia_hub.gateway.config import VaultMountConfig
from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.vault import VaultEngine

ENV_FLAG = "PALAIA_CURATOR_SMOKE"

pytestmark = [
    pytest.mark.skipif(
        os.environ.get(ENV_FLAG) != "1",
        reason=f"real-runner smoke test: set {ENV_FLAG}=1 to run it (spends model calls)",
    ),
    pytest.mark.skipif(
        shutil.which("claude") is None, reason="the `claude` CLI is not on PATH"
    ),
]

_HUB_SCRIPT = Path(__file__).parent / "support" / "curator_hub.py"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def running_hub(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    """A real hub process serving the curator profile over HTTP."""
    port = _free_port()
    root = tmp_path / "work"
    process = subprocess.Popen(  # noqa: S603 - fixed argv, test-only
        [sys.executable, str(_HUB_SCRIPT), str(root), str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20.0
    try:
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{base}/api/health", timeout=1.0) as response:
                    if response.status == 200:
                        break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.2)
        else:  # pragma: no cover - startup failure
            raise RuntimeError("the smoke-test hub did not start")
        yield base, root
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.mark.anyio
async def test_a_real_session_curates_one_capture(
    running_hub: tuple[str, Path],
) -> None:
    base, root = running_hub
    engine = VaultEngine(root, name="work")
    await engine.open(purpose="Smoke-test vault for the curator.", create=False)
    service = EngineVaultService(engine)
    capture = await service.capture(
        what_it_concerns="API Gateway",
        why_keep="The ingest limit was chosen deliberately.",
        content="We capped ingest at 100 req/min because the embed queue saturates.",
    )
    mount = VaultMountConfig(key="work", name="work", purpose="Smoke-test vault.")
    settings = HubConfig().curator
    runner = CuratorRunner(
        engine,
        session_runner=SubprocessSessionRunner(
            command=list(settings.runner_command), timeout=settings.session_timeout
        ),
        endpoint=f"{base}/mcp/curator",
        allowed_tools=allowed_tool_specs([mount]),
        purpose=mount.purpose,
    )

    report = await runner.run_once()
    await engine.close()

    assert report.sessions == 1
    [record] = report.records
    print(f"\nreal-runner outcome: {record.outcome} — {record.reason or 'no reason'}")
    print(f"targets: {record.targets}")
    assert record.capture_id == capture.capture_id
    assert record.outcome in ("ingested", "needs_review", "unverified")
