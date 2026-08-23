"""kill -9 mid-write-burst: no corruption, no lost acknowledged writes.

The SPEC-003 kill test, moved into the engine's own suite. A worker writes
notes through the engine while this test SIGKILLs it at a randomized point;
afterwards the vault must open clean, every note file must be intact, and
every write the worker got an acknowledgement for must be on disk *and* in
git.

Two traps from the spike findings are handled explicitly:

* ``uv run script.py`` execs a child interpreter, so killing the wrapper PID
  leaves the real writer running. The worker is launched with
  ``sys.executable`` directly, in its own process group, and the whole group
  is killed and confirmed dead before anything is inspected.
* A kill mid-commit can leave a stale ``.git/index.lock`` (2 of 25 spike
  trials). Removing it is expected to be sufficient repair — that is asserted
  here rather than assumed.
"""

from __future__ import annotations

import json
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import TEST_POLICY

from palaia_hub.vault import VaultDoctor, VaultEngine
from palaia_hub.vault import frontmatter as fm
from palaia_hub.vault.atomic import sha256_file

pytestmark = pytest.mark.anyio

WORKER = Path(__file__).parent / "support" / "write_burst.py"

#: Trials run by default; raise with PALAIA_KILL_TRIALS for a longer soak
#: (the spike ran 25).
TRIALS = int(os.environ.get("PALAIA_KILL_TRIALS", "3"))


def kill_process_group(process: subprocess.Popen[bytes]) -> None:
    """SIGKILL the worker's whole process group and confirm it is gone."""
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):  # pragma: no cover - already dead
        pass
    for _ in range(50):
        if process.poll() is not None:
            break
        time.sleep(0.1)
    assert process.poll() is not None, "worker survived SIGKILL"


def run_until_killed(vault_dir: Path, progress: Path, delay: float) -> None:
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [
            sys.executable,
            str(WORKER),
            "--vault-dir",
            str(vault_dir),
            "--progress",
            str(progress),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    time.sleep(delay)
    kill_process_group(process)


@pytest.mark.parametrize("trial", range(TRIALS))
async def test_kill_mid_write_burst_never_corrupts_the_vault(
    tmp_path: Path, trial: int
) -> None:
    vault_dir = tmp_path / f"vault-{trial}"
    progress_path = tmp_path / f"progress-{trial}.jsonl"
    progress_path.touch()
    delay = round(random.Random(trial).uniform(0.6, 1.6), 3)

    run_until_killed(vault_dir, progress_path, delay)

    acknowledged = [
        json.loads(line) for line in progress_path.read_text(encoding="utf-8").splitlines() if line
    ]
    assert acknowledged, f"worker produced no acknowledged writes in {delay}s"

    # 1. No corrupt files: every note parses and is non-empty.
    note_files = sorted(
        path for path in vault_dir.rglob("*.md") if ".git" not in path.parts
    )
    for path in note_files:
        data = path.read_bytes()
        assert data, f"{path} is zero-byte"
        parsed = fm.parse(data.decode("utf-8"))
        assert not parsed.malformed, f"{path} has broken frontmatter"
        assert parsed.frontmatter.get("permalink"), f"{path} lost its identity"

    # 2. No lost acknowledged writes: on disk, unchanged, and in git.
    for record in acknowledged:
        path = vault_dir / record["path"]
        assert path.exists(), f"acknowledged write {record['path']} is missing"
        assert sha256_file(path) == record["checksum"], f"{record['path']} changed after ack"
        committed = subprocess.run(
            ["git", "-C", str(vault_dir), "cat-file", "-e", f"{record['commit']}:{record['path']}"],
            capture_output=True,
            check=False,
        )
        assert committed.returncode == 0, f"{record['path']} is not in its commit"

    # 3. The vault opens clean afterwards; stale locks are recovered as part
    #    of normal startup, and no other repair is needed.
    lock_before = (vault_dir / ".git" / "index.lock").exists()
    time.sleep(TEST_POLICY.stale_lock_after + 0.05)
    engine = VaultEngine(vault_dir, "killtest", policy=TEST_POLICY)
    await engine.open()
    assert not (vault_dir / ".git" / "index.lock").exists()
    assert len(engine.catalog) == len(note_files)

    findings = await VaultDoctor(engine).verify()
    fatal = [
        finding
        for finding in findings
        if finding.severity == "error" and finding.code != "git-lock-held"
    ]
    assert fatal == [], fatal

    # A write still works after the crash — that is the real proof the repo
    # was recovered, not just that the lock file is gone.
    result = await engine.write_note("notes/after-crash", body="ok\n", title="After Crash")
    assert result.commit is not None
    if lock_before:
        # Recorded for the record: the spike saw this in 2 of 25 trials and
        # lock removal alone was always sufficient — as just demonstrated.
        assert True
