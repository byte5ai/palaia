"""Shared fixtures for the SPEC-113 e2e scenario suite.

Any other SPEC's tests can import :func:`golden_vault_copy` and
:class:`RunningHub` from here too — the SPEC-113 acceptance criterion "any
SPEC can import the simulator + golden vault as pytest fixtures" is why
these live in a plain fixtures module rather than being private to one test
file.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

#: The golden vault fixture tree (SPEC-113 deliverable #1): two physically
#: isolated vault roots, ``work/`` and ``personal/``, per vault-format.md.
GOLDEN_VAULT_ROOT = Path(__file__).parent.parent / "fixtures" / "golden-vault"

_HUB_SERVER_SCRIPT = Path(__file__).parent / "support" / "hub_server.py"
_STARTUP_TIMEOUT = 15.0


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def golden_vault_copy(dest: Path, name: str = "work") -> Path:
    """Copy one golden-vault vault (``"work"`` or ``"personal"``) to ``dest``.

    Returns the copy's root. The fixture tree itself is never mutated —
    every scenario gets its own disposable copy, since scenarios (S2, S3)
    deliberately mutate the vault on disk.
    """
    source = GOLDEN_VAULT_ROOT / name
    if not source.is_dir():
        raise FileNotFoundError(f"no golden-vault vault named {name!r} at {source}")
    target = dest / name
    shutil.copytree(source, target)
    return target


@pytest.fixture
def golden_work_vault(tmp_path: Path) -> Path:
    """A disposable copy of the golden vault's ``work`` vault."""
    return golden_vault_copy(tmp_path, "work")


@pytest.fixture
def golden_personal_vault(tmp_path: Path) -> Path:
    """A disposable copy of the golden vault's ``personal`` vault."""
    return golden_vault_copy(tmp_path, "personal")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(port: int, timeout: float = _STARTUP_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=0.5
            ) as resp:
                if resp.status == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"hub did not become healthy within {timeout}s: {last_error}")


@dataclass
class RunningHub:
    """A live hub subprocess, its port, and the profile URLs it mounts."""

    process: subprocess.Popen[bytes]
    port: int
    profiles: list[str]
    log_path: Path

    def profile_url(self, profile: str = "default") -> str:
        return f"http://127.0.0.1:{self.port}/mcp/{profile}/"

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def kill(self, *, wait: float = 10.0) -> None:
        """SIGKILL the hub process (simulates a crash, SPEC-113 S3)."""
        self.process.kill()
        self.process.wait(timeout=wait)

    def stop(self, *, wait: float = 10.0) -> None:
        """Terminate gracefully; escalate to kill if it does not exit in time."""
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def spawn_hub(
    *,
    vault_dir: Path,
    log_path: Path,
    vault_key: str = "work",
    vault_name: str = "work",
    profiles: list[str] | None = None,
) -> RunningHub:
    """Launch a real hub subprocess over ``vault_dir`` and wait for it to be healthy.

    Uses ``sys.executable`` directly (never a ``uv run`` wrapper) so a later
    ``kill()`` actually kills the server process — see SPEC-102/103's kill
    -9 findings, restated in ``support/hub_server.py``'s module docstring.
    """
    profiles = profiles or ["default"]
    port = free_port()
    args = [
        sys.executable,
        str(_HUB_SERVER_SCRIPT),
        "--port",
        str(port),
        "--vault-dir",
        str(vault_dir),
        "--vault-key",
        vault_key,
        "--vault-name",
        vault_name,
    ]
    for profile in profiles:
        args += ["--profile", profile]

    log_file = log_path.open("w")
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        args, stdout=log_file, stderr=subprocess.STDOUT
    )
    try:
        wait_for_health(port)
    except Exception:
        process.kill()
        process.wait(timeout=5)
        raise
    return RunningHub(process=process, port=port, profiles=profiles, log_path=log_path)


HubFactory = Callable[..., RunningHub]


@pytest.fixture
def hub_factory(tmp_path: Path) -> Iterator[HubFactory]:
    """Yield ``spawn_hub``-like factory; tears down every hub it started."""
    started: list[RunningHub] = []

    def factory(
        *,
        vault_dir: Path,
        vault_key: str = "work",
        vault_name: str = "work",
        profiles: list[str] | None = None,
        log_name: str = "hub.log",
    ) -> RunningHub:
        hub = spawn_hub(
            vault_dir=vault_dir,
            log_path=tmp_path / log_name,
            vault_key=vault_key,
            vault_name=vault_name,
            profiles=profiles,
        )
        started.append(hub)
        return hub

    yield factory

    for hub in started:
        hub.stop()
