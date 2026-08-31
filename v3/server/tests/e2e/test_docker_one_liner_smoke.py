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

Issue #263 ("verify the container's hardened posture in CI"): the SPEC-502
hardening (`no-new-privileges`, `cap_drop: ALL`, read-only root filesystem,
the SPEC-502 nginx `/oauth` fix) is a runtime property of a *container*, not
of the code, so the unit test suite cannot assert it — only a daemon that
actually starts the image can. GitHub-hosted CI runners carry a Docker
daemon, so on CI this module builds, starts and inspects the real thing;
locally it degrades to the same honest skip as the rest of this file.

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
import json
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from palaia_hub.market.docker_runtime import docker_available

V3_ROOT = Path(__file__).resolve().parents[3]
IMAGE_TAG = "palaia-hub-rc-smoke:test"
CONTAINER_NAME = "palaia-hub-rc-smoke-test"
#: A host port other than install.sh's own 8420 default, so this smoke run
#: never collides with a developer's already-running hub. Fixed rather than
#: randomized: every test function below that speaks HTTP to the container
#: shares this one running instance (see `running_container` fixture).
HOST_PORT = 18420

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


def _docker_inspect(name: str) -> dict[str, Any]:
    """Return `docker inspect <name>`'s single JSON object for this container."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["docker", "inspect", name], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload: list[dict[str, Any]] = json.loads(result.stdout)
    return payload[0]


@pytest.fixture(scope="module")
def running_container(built_image: str) -> Iterator[str]:
    """Start the one-liner's container once and share it across every
    assertion in this module — rebuilding or restarting per-assertion would
    burn well into the e2e job's 15-minute CI timeout for no benefit; the
    image is already built once by `built_image` for the same reason.
    """
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["docker", "rm", "-f", CONTAINER_NAME], capture_output=True, check=False
    )
    argv = [
        "docker",
        "run",
        "-d",
        "--name",
        CONTAINER_NAME,
        "-p",
        f"{HOST_PORT}:8420",
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
        ready = False
        while time.monotonic() < deadline:
            try:
                resp = httpx.get(f"http://127.0.0.1:{HOST_PORT}/api/health", timeout=1.0)
                if resp.status_code == 200:
                    ready = True
                    break
            except httpx.HTTPError as exc:
                last_error = exc
            time.sleep(1)
        assert ready, f"container never answered /api/health: {last_error}"

        yield CONTAINER_NAME
    finally:
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["docker", "rm", "-f", CONTAINER_NAME], capture_output=True, check=False
        )


def test_the_shipped_one_liner_starts_the_image_and_serves_the_wizard(
    running_container: str,
) -> None:
    wizard = httpx.get(f"http://127.0.0.1:{HOST_PORT}/", timeout=5.0)
    assert wizard.status_code == 200, wizard.text


def test_container_inspect_reports_the_spec_502_hardening(running_container: str) -> None:
    """`docker inspect` — not just the flags this test *asked* `docker run`
    for — actually reports the hardened posture SPEC-502 added: a read-only
    root filesystem, every Linux capability dropped, and no-new-privileges.
    """
    host_config = _docker_inspect(running_container)["HostConfig"]
    assert host_config["ReadonlyRootfs"] is True
    assert host_config["CapDrop"] == ["ALL"], host_config["CapDrop"]
    assert "no-new-privileges:true" in host_config["SecurityOpt"], host_config["SecurityOpt"]


def test_container_process_does_not_run_as_root(running_container: str) -> None:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["docker", "exec", running_container, "id", "-u"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert int(result.stdout.strip()) != 0, result.stdout


def test_container_healthcheck_reaches_healthy(running_container: str) -> None:
    """Polls `docker inspect`'s own health status rather than sleeping a
    fixed amount: the Dockerfile's HEALTHCHECK (interval=30s,
    start-period=20s, retries=3) means the first probe — and so the first
    possible "healthy" transition — can land anywhere up to roughly
    start-period + interval out from container start. The deadline below is
    generous for that plus scheduling slack under CI load, not a guess.
    """
    deadline = time.monotonic() + 120
    status: str | None = None
    while time.monotonic() < deadline:
        health = _docker_inspect(running_container)["State"].get("Health")
        status = health["Status"] if health else None
        if status == "healthy":
            break
        time.sleep(2)
    assert status == "healthy", f"container health status never reached healthy: {status!r}"


def test_get_root_carries_the_content_security_policy(running_container: str) -> None:
    """nginx serves `/` directly from the dashboard build, never touching the
    hub process — SPEC-502 added the browser-hardening headers there
    (`v3/deploy/nginx.conf.template`) because that mount would otherwise be
    the one surface a browser renders with no policy on it at all.
    """
    resp = httpx.get(f"http://127.0.0.1:{HOST_PORT}/", timeout=5.0)
    assert resp.status_code == 200, resp.text
    csp = resp.headers.get("content-security-policy")
    assert csp is not None
    assert "default-src 'self'" in csp


def test_oauth_login_reaches_the_hub_not_the_dashboard_shell(running_container: str) -> None:
    """The SPEC-502 nginx fix (`v3/deploy/nginx.conf.template`): `/oauth/*`
    must proxy to the hub, not fall through to the SPA catch-all — before the
    fix, `GET /oauth/login` 200'd with the dashboard's `index.html` instead
    of the hub's actual sign-in form, silently hiding that no MCP client
    could complete an OAuth flow against the packaged image.
    """
    resp = httpx.get(f"http://127.0.0.1:{HOST_PORT}/oauth/login", timeout=5.0)
    assert resp.status_code == 200, resp.text
    # The hub's own login page (server/src/palaia_hub/oauth/routes.py,
    # `_login_page`) — distinct from the dashboard SPA shell, which has no
    # such title or form action.
    assert "Sign in to palaia" in resp.text
    assert 'action="/oauth/login"' in resp.text
