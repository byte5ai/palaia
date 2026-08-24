"""Launching one bounded curation session (SPEC-206 deliverable #1).

The session is a **config-driven runner command**, not a hardcoded vendor
call: the default is a headless ``claude -p`` with a strict MCP config
pointing only at the curator profile, but the command is a template in
``config.yaml`` (:class:`palaia_hub.config.CuratorSettings`), so a different
provider's CLI is a config edit rather than a code change. palaia is
provider-neutral by design (MASTERPLAN §2) and the curator is no exception.

Contract with whatever command is configured:

- the **prompt arrives on stdin** — every CLI worth using reads a prompt
  there, and it keeps a multi-kilobyte prompt out of argv;
- ``{mcp_config}`` in any argument is replaced by the path to a generated,
  single-server MCP config file (the curator profile, with the curator
  token's ``Authorization`` header);
- ``{allowed_tools}`` is replaced by the comma-separated list of tools the
  session may call, ``{endpoint}``/``{vault}``/``{capture_id}`` by their
  obvious values;
- exit code, stdout and stderr are recorded, a timeout kills the process.

Nothing in the outcome depends on any of that succeeding: a session that
crashes, times out or lies is classified by :mod:`palaia_hub.curator.verify`
like any other.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .models import SessionResult

logger = logging.getLogger("palaia_hub.curator.session")

#: The MCP server name the generated config uses. It shows up in a client's
#: tool names (``mcp__palaia__work_memory_write``), which is why
#: :func:`palaia_hub.curator.profile.allowed_tool_specs` builds its
#: ``--allowed-tools`` values from the same constant.
MCP_SERVER_NAME = "palaia"

#: The default runner command (SPEC-206 deliverable #1). ``claude -p`` reads
#: the prompt from stdin; ``--strict-mcp-config`` makes the generated config
#: the *only* MCP config in effect, so the session cannot reach a vault
#: through some other server the user happens to have configured.
DEFAULT_RUNNER_COMMAND: tuple[str, ...] = (
    "claude",
    "-p",
    "--mcp-config",
    "{mcp_config}",
    "--strict-mcp-config",
    "--allowed-tools",
    "{allowed_tools}",
    "--output-format",
    "text",
)


@dataclass(frozen=True, slots=True)
class SessionRequest:
    """Everything one session needs to know."""

    vault: str
    capture_id: str
    prompt: str
    endpoint: str
    allowed_tools: tuple[str, ...] = ()
    token: str | None = None


class SessionRunner(Protocol):
    """Runs one curation session and reports how it went, mechanically.

    The seam tests replace: a scripted runner performs a fixed set of MCP
    calls with no model involved (``tests/curator/scripted.py``), while
    production spawns :class:`SubprocessSessionRunner`.
    """

    async def run(self, request: SessionRequest) -> SessionResult: ...


def mcp_config_document(request: SessionRequest) -> dict[str, object]:
    """The strict, single-server MCP config a session is launched with."""
    server: dict[str, object] = {"type": "http", "url": request.endpoint}
    if request.token:
        server["headers"] = {"Authorization": f"Bearer {request.token}"}
    return {"mcpServers": {MCP_SERVER_NAME: server}}


@dataclass
class SubprocessSessionRunner:
    """Spawns the configured command with the prompt on stdin.

    Args:
        command: the argv template (see :data:`DEFAULT_RUNNER_COMMAND`).
        timeout: seconds before the session is killed and reported as timed
            out. A curation session is a background job; a hung one must
            never wedge the runner.
        env: extra environment for the child process.
        cwd: working directory for the child process.
    """

    command: Sequence[str] = DEFAULT_RUNNER_COMMAND
    timeout: float = 300.0
    env: Mapping[str, str] = field(default_factory=dict)
    cwd: Path | None = None

    def argv(self, request: SessionRequest, mcp_config_path: Path) -> list[str]:
        """The concrete argv for ``request``, with every placeholder filled."""
        replacements = {
            "{mcp_config}": str(mcp_config_path),
            "{allowed_tools}": ",".join(request.allowed_tools),
            "{endpoint}": request.endpoint,
            "{vault}": request.vault,
            "{capture_id}": request.capture_id,
        }
        argv: list[str] = []
        for argument in self.command:
            filled = argument
            for placeholder, value in replacements.items():
                filled = filled.replace(placeholder, value)
            argv.append(filled)
        return argv

    async def run(self, request: SessionRequest) -> SessionResult:
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="palaia-curator-") as tmp:
            config_path = Path(tmp) / "mcp.json"
            config_path.write_text(
                json.dumps(mcp_config_document(request), indent=2), encoding="utf-8"
            )
            argv = self.argv(request, config_path)
            try:
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, **self.env},
                    cwd=str(self.cwd) if self.cwd else None,
                )
            except OSError as exc:
                logger.warning("curator runner command failed to start: %s", exc)
                return SessionResult(
                    exit_code=127,
                    stderr=(
                        f"could not start the curator runner command {argv[0]!r}: {exc}. "
                        "Fix: install it, or set `curator.runner_command` in "
                        "config.yaml to a command this hub can run."
                    ),
                    duration_seconds=time.monotonic() - started,
                    launched=False,
                )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(request.prompt.encode("utf-8")),
                    timeout=self.timeout,
                )
            except TimeoutError:
                process.kill()
                with contextlib.suppress(ProcessLookupError):
                    await process.wait()
                return SessionResult(
                    exit_code=-1,
                    stderr=f"curation session exceeded {self.timeout:.0f}s and was killed",
                    timed_out=True,
                    duration_seconds=time.monotonic() - started,
                )
        return SessionResult(
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            duration_seconds=time.monotonic() - started,
        )


__all__ = [
    "DEFAULT_RUNNER_COMMAND",
    "MCP_SERVER_NAME",
    "SessionRequest",
    "SessionRunner",
    "SubprocessSessionRunner",
    "mcp_config_document",
]
