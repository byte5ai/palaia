"""The SPEC-207 effectiveness harness: does an agent with the skill installed
actually use the memory?

Everything else in this SPEC can be verified by reading it. This cannot. A
skill is prose aimed at a model, and the only honest test of prose aimed at a
model is to give a model a task that does not mention memory and see what it
reaches for. So: a real hub over the golden vault, the real ``claude`` CLI as
the client, the real skill package loaded the way a user would load it
(``--plugin-dir`` over ``v3/clients``), a task prompt that never says
"remember" or "recall", and a log of which vault calls actually happened.

What makes the result trustworthy:

- **The prompts never name the tools.** :data:`RECALL_PROMPT` asks for a
  commit message; the vault happens to hold this team's commit-message rule.
  :data:`CAPTURE_PROMPT` states a decision in passing and then asks for
  something else. An agent that calls nothing has done the task; whether it
  *also* consults and feeds the memory is what the skill is for.
- **Evidence is server-side.** ``support/hub_server.py`` logs every call at
  the vault-service boundary, so a result does not depend on parsing a
  transcript.
- **A baseline is available.** :func:`run_probe` with ``skills=()`` runs the
  identical prompt with no skill loaded, which is the only way to tell a
  working skill from a prompt the model would have handled anyway.
- **Nothing is retried into a pass.** A probe runs a fixed number of times
  (:func:`default_attempts`) and *every* run is reported, hit or miss. The
  measured rate is the evidence; see :class:`ProbeSeries`.

Why repeats at all: skill activation is not deterministic. Measured on the
capture probe, the same skill and the same prompt fired between two and three
times in five. A single-run assertion would therefore be a coin toss dressed up
as a test — it would go red on a good skill and green on a bad one. So the
assertion is the floor ("this behaviour is reachable with the skill, and the
no-skill baseline never reaches it") and the number in the output is the claim.

Not part of CI: it costs real model calls and depends on a CLI that is not on
every runner. Gated on ``PALAIA_EFFECTIVENESS=1`` plus ``claude`` on PATH.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

#: ``v3/clients`` — the plugin root a real user would install.
CLIENTS_ROOT = Path(__file__).resolve().parents[3] / "clients"
#: SPEC-113's golden vault, reused as the seeded memory (its ``work`` vault
#: already holds decisions, conventions and projects with real relations).
GOLDEN_VAULT_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "golden-vault"
_HUB_SCRIPT = Path(__file__).resolve().parent / "support" / "hub_server.py"

ENV_FLAG = "PALAIA_EFFECTIVENESS"
ENV_MODEL = "PALAIA_EFFECTIVENESS_MODEL"
ENV_ATTEMPTS = "PALAIA_EFFECTIVENESS_ATTEMPTS"
#: Runs per probe. Three is the smallest number that distinguishes "fires
#: sometimes" from "never fires" without turning one suite run into an
#: afternoon; raise it via :data:`ENV_ATTEMPTS` when tuning a skill.
DEFAULT_ATTEMPTS = 3

_STARTUP_TIMEOUT = 20.0
#: A turn that recalls, thinks and captures is not fast. Generous on purpose:
#: a timeout is an inconclusive run, not a failed skill, and inconclusive runs
#: waste money.
_CLAUDE_TIMEOUT = 420.0

# --- the probes ---------------------------------------------------------

#: Should trigger recall. A plain authoring task whose "right" answer is
#: written down in the seeded memory (``rules/how-to-write-commit-messages``,
#: which even carries a per-model variant). Nothing in it hints at memory.
RECALL_PROMPT = (
    "Write the commit message for a change that adds retry handling to the "
    "importer suite. Reply with the message text only."
)

#: A held-out recall probe. :data:`RECALL_PROMPT` asks for a commit message,
#: and the skill's own description happens to name commit messages as an
#: example of a house convention — so on its own it cannot distinguish "the
#: skill works" from "the skill matched a keyword". This one names nothing the
#: description mentions: it just uses two words the agent cannot possibly place
#: (a colleague, and a term whose meaning in this memory is a rate limit, not a
#: price) and relies on the description's "when a term appears that you cannot
#: place" clause.
RECALL_PROMPT_UNSEEN = (
    "Deepa is asking whether the base rate needs to change for the new gateway "
    "work. Give me a two-line answer I can send her."
)

#: Should trigger capture. A decision with its reason, dropped in passing on
#: the way to a different question — the shape of the thing that gets lost
#: today. The trailing question matters: it gives the agent a legitimate way
#: to answer without ever touching the memory.
CAPTURE_PROMPT = (
    "Quick heads-up before I hand you the importer work: we settled on capping "
    "the basic-memory importer at 500 notes per batch, because above that the "
    "index write lock starves the file watcher and imports stall. Raising it "
    "means batching the index writes first. Now, separately: in one sentence, "
    "what is the importer suite for?"
)

#: The bullets the recall probe is looking for: this team's commit-message
#: convention, which is only knowable from the memory.
RECALL_EXPECTED_TOOLS: tuple[str, ...] = ("recall", "build_context", "search")
CAPTURE_EXPECTED_TOOLS: tuple[str, ...] = ("capture",)


# --- results ------------------------------------------------------------


@dataclass(frozen=True)
class ToolCall:
    """One recorded call at the vault-service boundary."""

    tool: str
    arguments: dict[str, object]


@dataclass
class ProbeResult:
    """One run: what was asked, what was loaded, what the agent actually did."""

    label: str
    prompt: str
    skills: tuple[str, ...]
    calls: list[ToolCall]
    reply: str
    model: str = ""
    cost_usd: float = 0.0
    duration_ms: int = 0
    num_turns: int = 0
    permission_denials: list[str] = field(default_factory=list)
    vault_dir: Path | None = None

    @property
    def tools_used(self) -> list[str]:
        seen: list[str] = []
        for call in self.calls:
            if call.tool not in seen:
                seen.append(call.tool)
        return seen

    def called(self, *names: str) -> bool:
        return any(call.tool in names for call in self.calls)

    def calls_to(self, name: str) -> list[ToolCall]:
        return [call for call in self.calls if call.tool == name]

    def summary(self) -> str:
        """One block, copy-pasteable into a PR — the run as it happened."""
        loaded = ", ".join(self.skills) if self.skills else "none (baseline)"
        lines = [
            f"### {self.label}",
            f"- skill loaded: {loaded}",
            f"- model: {self.model or 'unknown'}",
            f"- tools called: {', '.join(self.tools_used) if self.tools_used else 'NONE'}",
            f"- turns: {self.num_turns}, cost: ${self.cost_usd:.4f}, "
            f"wall: {self.duration_ms / 1000:.1f}s",
        ]
        if self.permission_denials:
            lines.append(f"- permission denials: {self.permission_denials}")
        for call in self.calls:
            shown = {
                key: (value[:120] + "…" if isinstance(value, str) and len(value) > 120 else value)
                for key, value in call.arguments.items()
                if value not in ("", None, [])
            }
            lines.append(f"  - `{call.tool}` {json.dumps(shown, ensure_ascii=False)}")
        reply = self.reply.strip().replace("\n", " ⏎ ")
        lines.append(f"- reply: {reply[:400]}{'…' if len(reply) > 400 else ''}")
        return "\n".join(lines)


@dataclass
class ProbeSeries:
    """Several runs of one probe, and how often the behaviour actually showed.

    The unit a test asserts on. ``hit_rate`` is the honest number; a single
    run of a probe says almost nothing, because whether a loader activates a
    skill for a given prompt varies between attempts.
    """

    label: str
    expected: tuple[str, ...]
    results: list[ProbeResult]

    @property
    def hits(self) -> int:
        return sum(1 for result in self.results if result.called(*self.expected))

    @property
    def attempts(self) -> int:
        return len(self.results)

    @property
    def hit_rate(self) -> str:
        return f"{self.hits}/{self.attempts}"

    @property
    def cost_usd(self) -> float:
        return sum(result.cost_usd for result in self.results)

    def first_hit(self) -> ProbeResult | None:
        return next((r for r in self.results if r.called(*self.expected)), None)

    def summary(self) -> str:
        header = (
            f"## {self.label}\n"
            f"- expected one of: {', '.join(self.expected)}\n"
            f"- **{self.hit_rate}** runs used it — total ${self.cost_usd:.4f}"
        )
        return "\n".join([header, *(result.summary() for result in self.results)])


class ProbeError(RuntimeError):
    """The run did not produce a usable result (CLI failure, timeout)."""


def default_attempts() -> int:
    raw = os.environ.get(ENV_ATTEMPTS, "").strip()
    return max(1, int(raw)) if raw.isdigit() else DEFAULT_ATTEMPTS


# --- gating -------------------------------------------------------------


def claude_cli() -> str | None:
    return shutil.which("claude")


def enabled() -> bool:
    return os.environ.get(ENV_FLAG, "").strip() not in ("", "0", "false", "no")


def skip_reason() -> str | None:
    """Why this suite should not run here, or ``None`` to run it."""
    if not enabled():
        return f"effectiveness runs are opt-in: set {ENV_FLAG}=1 (real model calls, real money)"
    if claude_cli() is None:
        return "claude CLI not on PATH"
    if not GOLDEN_VAULT_ROOT.is_dir():
        return f"golden vault fixture missing at {GOLDEN_VAULT_ROOT}"
    return None


# --- the runner ---------------------------------------------------------


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
    raise ProbeError(f"hub did not become healthy within {timeout}s: {last}")


def stage_plugin(workdir: Path, skills: tuple[str, ...]) -> Path:
    """Assemble a plugin root holding exactly ``skills``.

    Copies the shipped ``.claude-plugin/plugin.json`` verbatim, so the run
    also proves that manifest is one a real loader accepts — the alternative
    (dropping loose SKILL.md files into a project) would test the prose while
    quietly skipping the packaging.
    """
    root = workdir / "plugin"
    (root / ".claude-plugin").mkdir(parents=True)
    shutil.copy2(
        CLIENTS_ROOT / ".claude-plugin" / "plugin.json", root / ".claude-plugin" / "plugin.json"
    )
    (root / "skills").mkdir()
    for slug in skills:
        source = CLIENTS_ROOT / "skills" / slug
        if not source.is_dir():
            raise ProbeError(f"no skill package named {slug!r} in {CLIENTS_ROOT / 'skills'}")
        shutil.copytree(source, root / "skills" / slug)
    return root


def run_probe(
    *,
    label: str,
    prompt: str,
    workdir: Path,
    skills: tuple[str, ...] = ("palaia-memory",),
    vault: str = "work",
    model: str | None = None,
) -> ProbeResult:
    """Run one probe end to end and return what the agent did.

    ``skills=()`` runs the same prompt with nothing loaded — the baseline.
    """
    cli = claude_cli()
    if cli is None:  # pragma: no cover - guarded by skip_reason()
        raise ProbeError("claude CLI not on PATH")

    workdir.mkdir(parents=True, exist_ok=True)
    vault_dir = workdir / "vault"
    shutil.copytree(GOLDEN_VAULT_ROOT / vault, vault_dir)
    record_path = workdir / "tool-calls.jsonl"
    record_path.touch()
    hub_log = workdir / "hub.log"
    # A directory of its own, outside any git checkout: no project files, no
    # CLAUDE.md to discover, nothing for the agent to read instead of asking
    # the memory.
    project_dir = workdir / "project"
    project_dir.mkdir()

    port = _free_port()
    with hub_log.open("w") as log_file:
        hub = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [
                sys.executable,
                str(_HUB_SCRIPT),
                "--port",
                str(port),
                "--vault-dir",
                str(vault_dir),
                "--vault-key",
                vault,
                "--vault-name",
                vault,
                "--record",
                str(record_path),
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_for_health(port)

            mcp_config = json.dumps(
                {
                    "mcpServers": {
                        "palaia": {
                            "type": "http",
                            "url": f"http://127.0.0.1:{port}/mcp/default/",
                        }
                    }
                }
            )
            args = [
                cli,
                "-p",
                prompt,
                "--mcp-config",
                mcp_config,
                # Only the hub — never this machine's own MCP servers, which
                # would change both the tool surface and the context size.
                "--strict-mcp-config",
                "--allowedTools",
                "Skill mcp__palaia",
                "--output-format",
                "json",
                "--no-session-persistence",
            ]
            chosen_model = model or os.environ.get(ENV_MODEL, "").strip()
            if chosen_model:
                args += ["--model", chosen_model]
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


def run_series(
    *,
    label: str,
    prompt: str,
    workdir: Path,
    expected: tuple[str, ...],
    skills: tuple[str, ...] = ("palaia-memory",),
    attempts: int | None = None,
    vault: str = "work",
) -> ProbeSeries:
    """Run one probe ``attempts`` times and keep every result.

    Each attempt gets its own hub, its own copy of the vault and its own
    fresh session, so attempt *n+1* cannot inherit anything from attempt
    *n* — including a capture the previous attempt already wrote, which
    would otherwise be deduplicated and never recorded.
    """
    count = attempts if attempts is not None else default_attempts()
    results = [
        run_probe(
            label=f"{label} — attempt {index + 1}/{count}",
            prompt=prompt,
            workdir=workdir / f"attempt-{index + 1}",
            skills=skills,
            vault=vault,
        )
        for index in range(count)
    ]
    return ProbeSeries(label=label, expected=expected, results=results)


def inbox_notes(vault_dir: Path) -> list[Path]:
    """Every capture file in a run's vault, oldest name first."""
    inbox = vault_dir / "inbox"
    return sorted(inbox.glob("*.md")) if inbox.is_dir() else []
