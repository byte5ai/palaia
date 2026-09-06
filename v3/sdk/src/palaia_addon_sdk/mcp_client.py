"""A minimal, stdlib-only MCP stdio client.

Just enough to drive ``initialize`` and ``tools/list`` against a running
add-on process, so ``palaia-addon test`` proves the add-on answers the way
a real MCP client would see it — without the SDK depending on ``fastmcp``
or the official ``mcp`` package (the SDK CLI is stdlib + pydantic only,
SPEC-406 deliverable #1). It speaks the MCP "stdio transport": newline-
delimited JSON-RPC 2.0 messages over the child's stdin/stdout.

This is a test client, not a general-purpose one: it only implements the
two calls the SDK needs and treats anything else (malformed JSON, a
timed-out response, a JSON-RPC error) as a clear, printable failure.
"""

from __future__ import annotations

import contextlib
import json
import queue
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from types import TracebackType
from typing import Any

#: The MCP protocol version this client negotiates. A server that speaks a
#: different (but compatible) version still answers — MCP servers respond
#: with the version *they* support, and this client accepts whatever a
#: well-formed ``initialize`` result reports rather than rejecting it.
PROTOCOL_VERSION = "2025-06-18"

CLIENT_NAME = "palaia-addon-sdk"

#: How many of the add-on's most recent stderr lines are kept for the
#: "did not answer" diagnostic (issue #354). Read on a background thread
#: from the moment the child starts, so asking for them never blocks.
STDERR_TAIL_LINES = 40
STDERR_LINE_CHARS = 500


class McpClientError(RuntimeError):
    """Raised for anything that means "this add-on did not behave like a
    real MCP client would expect" — a timeout, bad JSON, or a JSON-RPC
    error response."""


@dataclass(frozen=True, slots=True)
class ToolsListResult:
    server_name: str | None
    server_version: str | None
    tools: list[dict[str, Any]]


class StdioMcpClient:
    """Spawn ``command`` and speak MCP-over-stdio to it. Use as a context
    manager so the child process is always cleaned up::

        with StdioMcpClient(["uv", "run", "server.py"], cwd=addon_dir) as client:
            result = client.initialize_and_list_tools()
    """

    def __init__(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._command = command
        self._cwd = cwd
        self._timeout = timeout
        self._proc: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str] = queue.Queue()
        self._stderr_lines: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        self._stderr_lock = threading.Lock()
        self._next_id = 1

    def __enter__(self) -> StdioMcpClient:
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - the command is the add-on under test
                self._command,
                cwd=self._cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise McpClientError(
                f"could not run {self._command[0]!r} — is it installed and on PATH?"
            ) from exc
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001 - best-effort cleanup, never masks the real error
            proc.kill()
            # Reap it (issue #354): a killed child that is never waited for
            # lingers as a zombie for as long as this process runs.
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)

    def _pump_stdout(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            self._lines.put(line)

    def _pump_stderr(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stderr is not None
        for line in proc.stderr:
            with self._stderr_lock:
                self._stderr_lines.append(line.rstrip("\n")[:STDERR_LINE_CHARS])

    def _write(self, message: dict[str, Any]) -> None:
        proc = self._proc
        assert proc is not None and proc.stdin is not None
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    def _stderr_tail(self) -> str:
        """What the add-on wrote to stderr so far — never blocks.

        Reading the pipe here used to block until 4096 characters or EOF:
        an add-on that logged one line and then never answered
        ``initialize`` hung this client forever, in exactly the situation
        the timeout exists to report (issue #354).
        """
        with self._stderr_lock:
            return "\n".join(self._stderr_lines)

    def _read_message(self) -> dict[str, Any]:
        try:
            line = self._lines.get(timeout=self._timeout)
        except queue.Empty:
            stderr = self._stderr_tail().strip()
            hint = f" (stderr: {stderr})" if stderr else ""
            raise McpClientError(
                f"add-on did not answer within {self._timeout:.0f}s{hint}"
            ) from None
        stripped = line.strip()
        if not stripped:
            return self._read_message()
        try:
            parsed: Any = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise McpClientError(f"add-on wrote non-JSON on stdout: {stripped!r}") from exc
        if not isinstance(parsed, dict):
            raise McpClientError(f"add-on wrote a non-object JSON-RPC message: {stripped!r}")
        return parsed

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        while True:
            message = self._read_message()
            if message.get("id") != request_id:
                # A notification, or a stray response to an earlier call — ignore.
                continue
            if "error" in message:
                error = message["error"]
                detail = error.get("message", error) if isinstance(error, dict) else error
                raise McpClientError(f"{method} failed: {detail}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise McpClientError(f"{method} response has no 'result' object")
            return result

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize_and_list_tools(self) -> ToolsListResult:
        """The exact sequence a real MCP client performs before it can call
        anything: ``initialize`` → ``notifications/initialized`` →
        ``tools/list``."""
        init_result = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized")
        server_info = init_result.get("serverInfo")
        server_info = server_info if isinstance(server_info, dict) else {}
        tools_result = self._request("tools/list")
        tools = tools_result.get("tools")
        if not isinstance(tools, list):
            raise McpClientError("tools/list response has no 'tools' array")
        return ToolsListResult(
            server_name=server_info.get("name"),
            server_version=server_info.get("version"),
            tools=[tool for tool in tools if isinstance(tool, dict)],
        )


__all__ = ["CLIENT_NAME", "PROTOCOL_VERSION", "McpClientError", "StdioMcpClient", "ToolsListResult"]
