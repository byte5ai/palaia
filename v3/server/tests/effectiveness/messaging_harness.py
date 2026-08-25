"""SPEC-404 deliverable #3: does the messenger skill actually change what a
real agent does — unprompted?

Reads on `harness.py`'s own docstring for why this can only be answered by
running a model (never by reading the skill), why the evidence is collected
server-side, and why a probe runs several times rather than once. This
module keeps every one of those constraints and differs only in what is
being measured and in the hub script it spawns
(`support/messaging_hub_server.py`, which mounts the session directory and
messenger tool families — SPEC-402/403 — rather than a lone vault).

Two probes, matching SPEC-404 deliverable #3 verbatim:

- **Session A** (:data:`HANDOFF_PROMPT`): a real end-of-shift task with a
  decision to hand off. A hit is not just "it called `messenger_send`" —
  :func:`sent_handoff_with_ref` checks that the send was typed `handoff`
  *and* carried a `memory://` reference, which is the only way to tell
  "wrote it to memory once and pointed at it" apart from "pasted the whole
  decision into the message body", the exact failure the skill's token
  rule exists to prevent.
- **Session B** (:data:`CHECK_PROMPT`): a task that never mentions messages
  at all. A hit is `messenger_check` appearing in the call log with nothing
  in the prompt that could have suggested it — "checks its inbox
  unprompted at task start".

A stand-in peer is registered directly against the hub's directory store
*before* session A's CLI process ever starts (`seed_peer_scope`), so the
agent has someone real to find — via `directory_list`/`directory_query`,
the same as it would with a live peer — rather than a name typed into the
prompt.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .harness import (
    CLIENTS_ROOT,
    GOLDEN_VAULT_ROOT,
    ProbeError,
    ProbeResult,
    ToolCall,
    claude_cli,
    default_attempts,
    stage_plugin,
)

_MESSAGING_HUB_SCRIPT = Path(__file__).resolve().parent / "support" / "messaging_hub_server.py"

_STARTUP_TIMEOUT = 20.0
_CLAUDE_TIMEOUT = 420.0

#: The scope the stand-in peer registers with — a substring session A's
#: prompt names, so a plain `directory_query`/`directory_list` finds it the
#: way it would find a real live session.
SEED_PEER_SCOPE = "cleaning up the billing service outage"

#: Should trigger: register, write the decision to memory, then a `handoff`
#: whose body stays short because the decision travels as a `memory://`
#: reference instead. Nothing here names a tool or "the messenger" — it is
#: an ordinary end-of-shift handoff, the shape the skill is meant for.
HANDOFF_PROMPT = (
    "It's the end of your shift on the billing-refactor branch. Before you go: "
    "save this to memory so it is not lost — we capped the API retry batch at "
    "200 items because a bigger batch trips the downstream rate limiter, and "
    "raising it needs the request queue split first. Then hand the branch off "
    "to whichever other session is already working on the billing service, so "
    "they can pick it up first thing. Reply with one line confirming both are "
    "done."
)

#: Should trigger: get oriented for resuming shared work, which under the
#: skill means checking what arrived while this session was away. Nothing
#: here says "message", "inbox" or "check" — the task is just "get
#: oriented". Deliberately says "another session" rather than naming a
#: literal file or branch to pick up: an early version of this prompt
#: ("picking up the billing-refactor branch") led the agent to go looking
#: for a git branch in an intentionally empty project directory instead of
#: checking for anything left for it — a miss worth fixing in the prompt,
#: not just in the skill (see the PR notes for the run that caught it).
CHECK_PROMPT = (
    "Another session was working on the billing-refactor work with you earlier "
    "today and may have left you something. Get yourself oriented before doing "
    "anything else, then tell me in two lines where things stand."
)

HANDOFF_EXPECTED_TOOLS: tuple[str, ...] = ("messenger_send",)
CHECK_EXPECTED_TOOLS: tuple[str, ...] = ("messenger_check",)


def sent_handoff_with_ref(result: ProbeResult) -> bool:
    """Session A's actual bar: a `handoff` send carrying a `memory://` ref.

    A `messenger_send` call alone is not the finding — a handoff whose body
    contains the whole decision, with `refs` left empty, is the exact
    failure the token rule exists to catch, and would still make
    ``result.called("messenger_send")`` true.
    """
    for call in result.calls_to("messenger_send"):
        if call.arguments.get("message_type") != "handoff":
            continue
        refs = call.arguments.get("refs") or []
        if isinstance(refs, list) and any(str(ref).strip() for ref in refs):
            return True
    return False


def registered(result: ProbeResult) -> bool:
    """Did this session call ``directory_register`` at all — the other half
    of SPEC-404 deliverable #3's first question."""
    return result.called("directory_register")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(port: int, timeout: float = _STARTUP_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last = exc
            time.sleep(0.1)
    raise ProbeError(f"messaging hub did not become healthy within {timeout}s: {last}")


def run_messaging_probe(
    *,
    label: str,
    prompt: str,
    workdir: Path,
    skills: tuple[str, ...],
    mount_vault: bool,
    seed_peer_scope: str | None = None,
    model: str | None = None,
) -> ProbeResult:
    """Run one messaging probe end to end and return what the agent did.

    ``mount_vault`` decides whether a `default` vault profile exists at
    all — session A's probe needs one (somewhere to write the note it hands
    off a reference to); session B's does not, and leaving it out keeps
    that probe's tool surface to exactly what is being measured.
    """
    cli = claude_cli()
    if cli is None:  # pragma: no cover - guarded by skip_reason()
        raise ProbeError("claude CLI not on PATH")

    workdir.mkdir(parents=True, exist_ok=True)
    record_path = workdir / "tool-calls.jsonl"
    record_path.touch()
    hub_log = workdir / "hub.log"
    project_dir = workdir / "project"
    project_dir.mkdir()

    vault_dir: Path | None = None
    port = _free_port()
    server_args = [
        sys.executable,
        str(_MESSAGING_HUB_SCRIPT),
        "--port",
        str(port),
        "--record",
        str(record_path),
    ]
    if mount_vault:
        vault_dir = workdir / "vault"
        shutil.copytree(GOLDEN_VAULT_ROOT / "work", vault_dir)
        server_args += ["--vault-dir", str(vault_dir), "--vault-key", "work"]
        server_args += ["--vault-name", "work"]
    if seed_peer_scope:
        server_args += ["--seed-peer-scope", seed_peer_scope]

    with hub_log.open("w") as log_file:
        hub = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            server_args, stdout=log_file, stderr=subprocess.STDOUT
        )
        try:
            _wait_for_health(port)

            servers: dict[str, dict[str, str]] = {
                "messaging": {"type": "http", "url": f"http://127.0.0.1:{port}/mcp/messaging/"}
            }
            allowed_servers = ["mcp__messaging"]
            if mount_vault:
                servers["palaia"] = {"type": "http", "url": f"http://127.0.0.1:{port}/mcp/default/"}
                allowed_servers.append("mcp__palaia")
            mcp_config = json.dumps({"mcpServers": servers})

            args = [
                cli,
                "-p",
                prompt,
                "--mcp-config",
                mcp_config,
                "--strict-mcp-config",
                "--allowedTools",
                " ".join(["Skill", *allowed_servers]),
                "--output-format",
                "json",
                "--no-session-persistence",
            ]
            if model:
                args += ["--model", model]
            if skills:
                args += ["--plugin-dir", str(stage_plugin(workdir, skills))]

            try:
                completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                    args,
                    cwd=project_dir,
                    capture_output=True,
                    text=True,
                    timeout=_CLAUDE_TIMEOUT,
                )
            except subprocess.TimeoutExpired as exc:
                raise ProbeError(f"{label}: claude did not finish in {_CLAUDE_TIMEOUT}s") from exc
            if completed.returncode != 0:
                raise ProbeError(
                    f"{label}: claude exited {completed.returncode}\n{completed.stderr[-2000:]}"
                )
            try:
                payload = json.loads(completed.stdout)
            except json.JSONDecodeError as exc:
                raise ProbeError(
                    f"{label}: claude output was not JSON:\n{completed.stdout[:2000]}"
                ) from exc
        finally:
            hub.terminate()
            try:
                hub.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                hub.kill()
                hub.wait(timeout=5)

    recorded = [
        json.loads(line)
        for line in record_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    calls = [ToolCall(tool=e["tool"], arguments=e.get("arguments", {})) for e in recorded]
    models = sorted((payload.get("modelUsage") or {}).keys())
    (workdir / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return ProbeResult(
        label=label,
        prompt=prompt,
        skills=skills,
        calls=calls,
        reply=str(payload.get("result", "")),
        model=", ".join(models),
        cost_usd=float(payload.get("total_cost_usd") or 0.0),
        duration_ms=int(payload.get("duration_ms") or 0),
        num_turns=int(payload.get("num_turns") or 0),
        permission_denials=[
            str(entry.get("tool_name", entry)) for entry in payload.get("permission_denials") or []
        ],
        vault_dir=vault_dir,
    )


def run_messaging_series(
    *,
    label: str,
    prompt: str,
    workdir: Path,
    skills: tuple[str, ...],
    mount_vault: bool,
    seed_peer_scope: str | None = None,
    attempts: int | None = None,
) -> list[ProbeResult]:
    """Run one messaging probe ``attempts`` times, each with its own hub, its
    own directory/messenger state and its own fresh session — same
    isolation reasoning as `harness.run_series`, and for the same reason:
    attempt *n+1* must not inherit a registration or a delivered envelope
    from attempt *n*."""
    count = attempts if attempts is not None else default_attempts()
    return [
        run_messaging_probe(
            label=f"{label} — attempt {index + 1}/{count}",
            prompt=prompt,
            workdir=workdir / f"attempt-{index + 1}",
            skills=skills,
            mount_vault=mount_vault,
            seed_peer_scope=seed_peer_scope,
        )
        for index in range(count)
    ]


def hit_rate(results: list[ProbeResult], predicate: Callable[[ProbeResult], bool]) -> str:
    """``k/n`` — how many of ``results`` satisfy ``predicate``, printable
    straight into a PR the same way `ProbeSeries.hit_rate` is."""
    hits = sum(1 for result in results if predicate(result))
    return f"{hits}/{len(results)}"


__all__ = [
    "CHECK_EXPECTED_TOOLS",
    "CHECK_PROMPT",
    "CLIENTS_ROOT",
    "HANDOFF_EXPECTED_TOOLS",
    "HANDOFF_PROMPT",
    "SEED_PEER_SCOPE",
    "hit_rate",
    "registered",
    "run_messaging_probe",
    "run_messaging_series",
    "sent_handoff_with_ref",
]
