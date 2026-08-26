"""Unit tests for :mod:`palaia_hub.market.docker_runtime` — the pure argv
builder always runs; the subprocess-touching functions are exercised with
a faked ``asyncio.create_subprocess_exec`` so this file needs no real
docker at all (the real daemon is exercised by
``test_install_container.py``, itself skipped honestly without one).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from palaia_hub.market import docker_runtime


def test_build_stdio_run_args_shape() -> None:
    run_args = docker_runtime.build_stdio_run_args(
        "ghcr.io/palaia/addon-fetch:1.0.0",
        container_name="palaia-addon-fetch",
        mounts={"mount_path": "/data/notes"},
        plain_env={"USER_AGENT": "palaia/1.0"},
        secret_env_vars=["API_KEY"],
    )

    assert run_args.command == "docker"
    assert run_args.args[:4] == ["run", "--rm", "-i", "--name"]
    assert "palaia-addon-fetch" in run_args.args
    assert "-v" in run_args.args
    mount_idx = run_args.args.index("-v")
    assert run_args.args[mount_idx + 1] == "/data/notes:/data/notes"
    assert "-e" in run_args.args
    assert "USER_AGENT=palaia/1.0" in run_args.args
    # The secret's *name* appears bare — never a value, and the value
    # itself never appears anywhere in the argv (SPEC-304's own rule).
    assert "API_KEY" in run_args.args
    assert not any("API_KEY=" in arg for arg in run_args.args)
    assert run_args.args[-1] == "ghcr.io/palaia/addon-fetch:1.0.0"


def test_build_stdio_run_args_with_no_mounts_or_env() -> None:
    run_args = docker_runtime.build_stdio_run_args(
        "ghcr.io/acme/tool:1.0.0",
        container_name="palaia-addon-tool",
        mounts={},
        plain_env={},
        secret_env_vars=[],
    )

    assert run_args.args == [
        "run", "--rm", "-i", "--name", "palaia-addon-tool", "ghcr.io/acme/tool:1.0.0",
    ]


@pytest.mark.anyio
async def test_docker_available_is_false_when_the_binary_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docker_runtime, "docker_binary", lambda: None)

    assert await docker_runtime.docker_available() is False


@dataclass
class _FakeProcess:
    returncode: int
    stdout_bytes: bytes = b""
    stderr_bytes: bytes = b""

    async def communicate(self) -> tuple[bytes, bytes]:
        return self.stdout_bytes, self.stderr_bytes

    def kill(self) -> None:
        pass

    async def wait(self) -> int:
        return self.returncode


@pytest.mark.anyio
async def test_docker_available_true_when_daemon_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_runtime, "docker_binary", lambda: "/usr/bin/docker")

    async def fake_exec(*args: object, **kwargs: object) -> _FakeProcess:
        return _FakeProcess(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    assert await docker_runtime.docker_available() is True


@pytest.mark.anyio
async def test_pull_image_raises_with_stderr_tail_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docker_runtime, "docker_binary", lambda: "/usr/bin/docker")

    async def fake_exec(*args: object, **kwargs: object) -> _FakeProcess:
        return _FakeProcess(returncode=1, stderr_bytes=b"Error: no such image\nunauthorized\n")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    with pytest.raises(docker_runtime.DockerError, match="unauthorized"):
        await docker_runtime.pull_image("ghcr.io/does-not/exist:1.0.0")


@pytest.mark.anyio
async def test_pull_image_raises_when_docker_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_runtime, "docker_binary", lambda: None)

    with pytest.raises(docker_runtime.DockerError, match="not installed"):
        await docker_runtime.pull_image("ghcr.io/acme/tool:1.0.0")


@pytest.mark.anyio
async def test_remove_container_never_raises_when_docker_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docker_runtime, "docker_binary", lambda: None)

    await docker_runtime.remove_container("palaia-addon-anything")  # must not raise


@pytest.mark.anyio
async def test_ensure_image_pull_success_never_asks_the_local_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_pull(image: str, *, timeout: float = 0) -> None:
        calls.append("pull")

    async def fake_present(image: str, *, timeout: float = 0) -> bool:
        calls.append("present")
        return True

    monkeypatch.setattr(docker_runtime, "pull_image", fake_pull)
    monkeypatch.setattr(docker_runtime, "image_present", fake_present)

    await docker_runtime.ensure_image("ghcr.io/acme/tool:1.0.0")

    assert calls == ["pull"]


@pytest.mark.anyio
async def test_ensure_image_falls_back_to_a_locally_present_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_pull(image: str, *, timeout: float = 0) -> None:
        raise docker_runtime.DockerError("pull access denied")

    async def fake_present(image: str, *, timeout: float = 0) -> bool:
        return True

    monkeypatch.setattr(docker_runtime, "pull_image", fake_pull)
    monkeypatch.setattr(docker_runtime, "image_present", fake_present)

    # A locally built image (or an air-gapped host) must install even though
    # no registry serves the reference — the fallback swallows the pull error.
    await docker_runtime.ensure_image("palaia-test-fixture-addon:latest")


@pytest.mark.anyio
async def test_ensure_image_raises_when_pull_fails_and_nothing_is_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_pull(image: str, *, timeout: float = 0) -> None:
        raise docker_runtime.DockerError("pull access denied")

    async def fake_present(image: str, *, timeout: float = 0) -> bool:
        return False

    monkeypatch.setattr(docker_runtime, "pull_image", fake_pull)
    monkeypatch.setattr(docker_runtime, "image_present", fake_present)

    with pytest.raises(docker_runtime.DockerError, match="pull access denied"):
        await docker_runtime.ensure_image("ghcr.io/does-not/exist:1.0.0")
