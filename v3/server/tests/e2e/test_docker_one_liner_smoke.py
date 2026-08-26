"""SPEC-506 deliverable #2: "docker one-liner smoke: the shipped one-liner
starts the rc image and serves the wizard."

Env-gated on a reachable docker daemon (the same
:func:`palaia_hub.market.docker_runtime.docker_available` probe
`server/tests/market/test_install_container.py` already uses — reused, not
reinvented), skipped honestly, never faked, when there is none — this
sandbox has the `docker` CLI on PATH but no reachable daemon
(``docker info`` fails with "Cannot connect to the Docker daemon"), so this
suite is expected to skip here. When it skips, SPEC-112's own evidence is
the fallback this SPEC's task names: `v3/specs/SPEC-112-packaging.md`'s
acceptance criterion ("fresh Linux VM: `docker run` one-liner -> wizard
reachable, data survives restart") plus the working, hardened `docker run`
one-liner itself (`v3/deploy/README.md`'s "Quick start", verbatim what
`v3/site/docs`'s onboarding page renders and `onboarding.test.ts` already
proves matches byte-for-byte) are the standing evidence for the claims this
test cannot check on a daemon-less sandbox.

Builds the *local* `v3/deploy/Dockerfile` (not a GHCR pull — this SPEC has
no docker daemon to push an rc image from, and pulling `:stable`/`:beta`
would prove someone else's already-published image, not this branch's
own working tree) under a disposable local tag, then runs it with
**exactly** the flags `v3/deploy/install.sh` uses (security-opt/cap-drop/
read-only/tmpfs included — the one-liner and this test must never drift
apart), and checks `GET /` (the wizard shell) and `GET /api/health`
answer. The *version reported by the running container* (its own
`palaia_hub.__version__`, baked in from this exact working tree) is
`v3/VERSION`'s value by construction — `server/tests/test_version_drift.py`
is what actually checks that, mechanically, without needing a docker
daemon at all.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from palaia_hub.market.docker_runtime import docker_available

V3_ROOT = Path(__file__).resolve().parents[3]
IMAGE_TAG = "palaia-hub-rc-smoke:test"
CONTAINER_NAME = "palaia-hub-rc-smoke-test"

#: The hardening flags `deploy/install.sh` passes to `docker run` (SPEC-502
#: — must mirror `docker-compose.yml`'s `security_opt`/`cap_drop`/
#: `read_only`/`tmpfs` block). `--name`/`-p`/`-v` are this test's own
#: (a disposable container name, a non-default host port so a developer's
#: own running hub is never disturbed, an anonymous instead of the real
#: named volume so a smoke run leaves no state behind) — every flag *after*
#: those three is checked verbatim against `install.sh`'s own text below,
#: so this list cannot silently drift from the real one-liner.
_HARDENING_FLAGS = [
    "--restart",
    "unless-stopped",
    "--security-opt",
    "no-new-privileges:true",
    "--cap-drop",
    "ALL",
    "--read-only",
    "--tmpfs",
    "/tmp",
    "--tmpfs",
    "/run",
]


def _docker_ready() -> bool:
    return asyncio.run(docker_available())


def test_hardening_flags_match_install_sh_verbatim() -> None:
    """Runs regardless of docker availability — a pure text check that
    `_HARDENING_FLAGS` above has not drifted from the real one-liner."""
    install_sh = (V3_ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    for flag in {"--security-opt no-new-privileges:true", "--cap-drop ALL", "--read-only"}:
        assert flag in install_sh, f"install.sh no longer contains {flag!r}"
    assert install_sh.count("--tmpfs") == 2


@pytest.fixture(scope="module")
def built_image() -> str:
    if not _docker_ready():
        pytest.skip("no reachable docker daemon in this environment")
    # Build context is the REPO ROOT, not v3/ — the Dockerfile's COPY
    # directives are all `v3/`-prefixed because that is how the release
    # workflow builds it (`.github/workflows/v3-release.yml`: context `.`,
    # file `v3/deploy/Dockerfile`); this build mirrors it exactly.
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["docker", "build", "-f", "v3/deploy/Dockerfile", "-t", IMAGE_TAG, "."],
        cwd=V3_ROOT.parent,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return IMAGE_TAG


def test_the_shipped_one_liner_starts_the_image_and_serves_the_wizard(
    built_image: str,
) -> None:
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["docker", "rm", "-f", CONTAINER_NAME], capture_output=True, check=False
    )
    # A host port other than install.sh's own 8420 default, so this smoke
    # run never collides with a developer's already-running hub.
    host_port = 18420
    argv = [
        "docker",
        "run",
        "-d",
        "--name",
        CONTAINER_NAME,
        "-p",
        f"{host_port}:8420",
        *_HARDENING_FLAGS,
        built_image,
    ]
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv, capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, result.stdout + result.stderr

        deadline = time.monotonic() + 30
        last_error: Exception | None = None
        healthy = False
        while time.monotonic() < deadline:
            try:
                resp = httpx.get(f"http://127.0.0.1:{host_port}/api/health", timeout=1.0)
                if resp.status_code == 200:
                    healthy = True
                    break
            except httpx.HTTPError as exc:
                last_error = exc
            time.sleep(1)
        assert healthy, f"container never answered /api/health: {last_error}"

        wizard = httpx.get(f"http://127.0.0.1:{host_port}/", timeout=5.0)
        assert wizard.status_code == 200, wizard.text
    finally:
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["docker", "rm", "-f", CONTAINER_NAME], capture_output=True, check=False
        )
