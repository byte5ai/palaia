"""Docker lifecycle for containerized marketplace add-ons (SPEC-304 #1).

palaia never talks to a docker daemon over a client library — the SPEC's
own words are "docker via subprocess against the local socket... no new
daemon dependency", meaning exactly the ``docker`` CLI, already on the
operator's machine if they use containers at all. Every container this
module ever starts is a plain ``docker run --rm -i <image>``, spawned as
the child process of an ordinary ``stdio`` upstream
(:class:`~palaia_hub.upstream.models.UpstreamConfig` ``kind="stdio"``) —
not a second thing palaia supervises. Docker's own ``--rm`` reaps the
container the moment that child process exits.

**Restart-on-crash is inherited, not reimplemented.** fastmcp's
``StdioTransport.connect()`` already detects a dead child session and
respawns it on the next use (verified against the installed fastmcp
3.4.7 / ``mcp`` SDK: ``connect()`` calls ``self.disconnect()`` first
whenever ``_is_session_dead()``), and
:class:`~palaia_hub.upstream.monitor.UpstreamHealthMonitor` already calls
``list_tools()`` on every configured upstream once a minute. A crashed
container add-on is therefore respawned by the very next health probe —
no extra supervision loop lives here.

**No secret ever reaches an argument list.** ``docker run -e NAME`` with
no ``=value`` forwards *docker's own process environment* variable
``NAME`` into the container — never the value on argv, which a process
listing (``ps``) would otherwise show in plain text. The actual value is
injected into the environment the CLI itself runs in, by
:class:`~palaia_hub.upstream.service.UpstreamService` at spawn time via
``UpstreamConfig.env_secrets`` (the same mechanism, and the same
docstring rule, an ordinary stdio upstream's own secrets already use — see
that model). :func:`build_stdio_run_args` only ever receives *names*.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_PULL_TIMEOUT_SECONDS = 300.0
DEFAULT_PROBE_TIMEOUT_SECONDS = 5.0
DEFAULT_REMOVE_TIMEOUT_SECONDS = 30.0


class DockerError(RuntimeError):
    """A docker subprocess call failed to do what it was asked.

    The message is the tail of the CLI's own stderr — never an argument
    list (see the module docstring's mount/env rule), so it is always safe
    to return verbatim in a REST error.
    """


def docker_binary() -> str | None:
    """Absolute path to the ``docker`` CLI, or ``None`` if it is not on ``PATH``."""
    return shutil.which("docker")


async def docker_available(*, timeout: float = DEFAULT_PROBE_TIMEOUT_SECONDS) -> bool:
    """Whether a usable docker CLI *and* a reachable daemon exist here.

    Every container-lifecycle test that needs a real daemon calls this
    first and skips honestly when it is ``False`` (SPEC-304 acceptance
    criterion: "env-gated on docker availability; skipped honestly
    otherwise") — never a silent no-op standing in for the real thing.
    """
    binary = docker_binary()
    if binary is None:
        return False
    try:
        process = await asyncio.create_subprocess_exec(
            binary,
            "info",
            "--format",
            "{{.ServerVersion}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError:
        return False
    try:
        await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return False
    return process.returncode == 0


@dataclass(frozen=True, slots=True)
class ContainerRunArgs:
    """The resolved ``docker run`` invocation for one add-on install."""

    command: str
    args: list[str]


def build_stdio_run_args(
    image: str,
    *,
    container_name: str,
    mounts: dict[str, str],
    plain_env: dict[str, str],
    secret_env_vars: list[str],
) -> ContainerRunArgs:
    """The argv for ``docker run --rm -i`` backing one container add-on.

    ``mounts`` is ``{config field: host path}`` — each bind-mounted
    read-write at the *same* absolute path inside the container (palaia's
    declared-mount convention: a ``config_schema`` string property with
    ``"format": "path"`` is a mount; every other non-secret property is a
    plain environment variable, its name upper-cased). ``secret_env_vars``
    names environment variables whose value never appears here at all —
    see the module docstring.
    """
    args = ["run", "--rm", "-i", "--name", container_name]
    for host_path in mounts.values():
        args += ["-v", f"{host_path}:{host_path}"]
    for key, value in sorted(plain_env.items()):
        args += ["-e", f"{key}={value}"]
    for key in sorted(secret_env_vars):
        args += ["-e", key]
    args.append(image)
    return ContainerRunArgs(command="docker", args=args)


async def pull_image(image: str, *, timeout: float = DEFAULT_PULL_TIMEOUT_SECONDS) -> None:
    """``docker pull <image>``.

    Raises:
        DockerError: docker is missing, the pull failed, or it did not
            finish within ``timeout`` — the message names the reason, the
            tail of stderr for a failed pull.
    """
    binary = docker_binary()
    if binary is None:
        raise DockerError("docker is not installed (or not on PATH) on this host.")
    try:
        process = await asyncio.create_subprocess_exec(
            binary,
            "pull",
            image,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise DockerError(f"could not run docker: {exc}") from exc
    try:
        _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise DockerError(f"pulling {image!r} did not finish within {timeout:.0f}s.") from None
    if process.returncode != 0:
        tail = stderr.decode("utf-8", "replace").strip().splitlines()[-5:]
        raise DockerError(f"docker pull {image!r} failed: {' | '.join(tail) or 'no output'}")


async def image_present(image: str, *, timeout: float = DEFAULT_PROBE_TIMEOUT_SECONDS) -> bool:
    """Whether ``image`` already exists in the local image store.

    ``docker image inspect`` exits 0 exactly when the image is present
    locally; any failure to ask (no CLI, no daemon, timeout) is ``False``.
    """
    binary = docker_binary()
    if binary is None:
        return False
    try:
        process = await asyncio.create_subprocess_exec(
            binary,
            "image",
            "inspect",
            image,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return False
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return False
    return process.returncode == 0


async def ensure_image(image: str, *, timeout: float = DEFAULT_PULL_TIMEOUT_SECONDS) -> None:
    """Make ``image`` available locally: pull it, or accept an already-local copy.

    A registry pull is always attempted first, so a published add-on
    receives updates. When the pull fails but the image already exists in
    the local store (a locally built image, an air-gapped host, a registry
    outage), the local copy is used rather than failing the install — the
    image the operator has is the image they asked for.

    Raises:
        DockerError: the pull failed and no local copy of ``image`` exists.
    """
    try:
        await pull_image(image, timeout=timeout)
    except DockerError:
        if await image_present(image):
            logger.warning(
                "pulling %r failed; using the locally present image instead", image
            )
            return
        raise


async def remove_container(
    container_name: str, *, timeout: float = DEFAULT_REMOVE_TIMEOUT_SECONDS
) -> None:
    """Best-effort ``docker rm -f`` — never raises.

    A container that already exited under ``--rm`` is not there to
    remove, and that is success, not failure: uninstall must never fail
    just because the container was already gone.
    """
    binary = docker_binary()
    if binary is None:
        return
    try:
        process = await asyncio.create_subprocess_exec(
            binary,
            "rm",
            "-f",
            container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
    except OSError:
        pass


__all__ = [
    "DEFAULT_PROBE_TIMEOUT_SECONDS",
    "DEFAULT_PULL_TIMEOUT_SECONDS",
    "DEFAULT_REMOVE_TIMEOUT_SECONDS",
    "ContainerRunArgs",
    "DockerError",
    "build_stdio_run_args",
    "docker_available",
    "docker_binary",
    "ensure_image",
    "image_present",
    "pull_image",
    "remove_container",
]
