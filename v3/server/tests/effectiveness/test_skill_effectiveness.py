"""SPEC-207 deliverable #4: does the skill actually change what an agent does?

Opt-in — every test here spends real money on real model calls through the
real ``claude`` CLI, so the whole module skips unless ``PALAIA_EFFECTIVENESS=1``
and the CLI is on PATH. That gate is also why it is excluded from CI (the
``python`` job in ``.github/workflows/v3-ci.yml`` runs pytest without the flag,
so these skip there by construction — no ignore list to keep in sync).

Read :mod:`harness` first: it explains why the prompts never name a tool, why
the evidence is collected server-side, and why each probe runs several times
instead of once. The tests below only decide what counts as a pass, and print
every run so a documented run can be pasted into a PR verbatim::

    PALAIA_EFFECTIVENESS=1 uv run pytest server/tests/effectiveness -s -v

What is asserted, and what is only reported. Skill activation is not
deterministic, so a test that demanded it every time would be a coin toss.
The assertion is therefore the floor — *with the skill, the behaviour happens
at all* — and the printed hit rate is the finding. The no-skill baselines
assert nothing about tool use for the same reason: a baseline that behaves
well is a fact to report, not a failure to fix.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from palaia_hub.gateway.inbox import capture_id_for
from palaia_hub.vault.parse import parse_note

from .harness import (
    CAPTURE_EXPECTED_TOOLS,
    CAPTURE_PROMPT,
    RECALL_EXPECTED_TOOLS,
    RECALL_PROMPT,
    RECALL_PROMPT_UNSEEN,
    ProbeResult,
    ProbeSeries,
    default_attempts,
    inbox_notes,
    run_probe,
    run_series,
    skip_reason,
)

_SKIP = skip_reason()
pytestmark = pytest.mark.skipif(_SKIP is not None, reason=_SKIP or "")

_CAPTURE_ID_RE = re.compile(r"^cap-[0-9a-f]{10}$")
_FRONTMATTER_RE = re.compile(r"\A---\n(?P<yaml>.*?)\n---\n", re.DOTALL)


def _report(item: ProbeSeries | ProbeResult) -> None:
    """Print the runs so ``-s`` output is the PR evidence, pass or fail."""
    print("\n" + item.summary())


def _assert_reachable(series: ProbeSeries) -> None:
    assert series.hits > 0, (
        f"{series.label}: the skill never used the memory in {series.attempts} "
        f"attempt(s). Tools seen: "
        f"{[result.tools_used for result in series.results]}"
    )


def _assert_capture_conforms_to_format_spec(path: Path) -> None:
    """The capture the agent produced must be a valid ``inbox/`` note (§7).

    Checked against the real parser rather than by eye: a capture that an
    agent wrote but the vault's own parser flags is not a capture, and this
    is SPEC-207's fourth acceptance criterion.
    """
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    assert match is not None, f"{path.name} has no frontmatter"
    front = yaml.safe_load(match.group("yaml"))

    assert front["type"] == "capture", front
    assert front["tags"] == ["inbox"], front
    assert front["status"] == "uncurated", front
    permalink = front["permalink"]
    assert permalink.startswith("inbox/"), permalink
    assert _CAPTURE_ID_RE.match(front["capture_id"]), front
    # §7: capture_id = "cap-" + sha256(permalink)[:10] — a pure function of
    # the permalink, so it is recomputable rather than merely well-shaped.
    assert front["capture_id"] == capture_id_for(permalink), front

    parsed = parse_note(text, str(path))
    categories = {observation.category for observation in parsed.observations}
    # The two mandatory bullets: a capture missing either is routed to review,
    # never guessed at (§7).
    assert "entity" in categories, parsed.observations
    assert "why" in categories, parsed.observations
    for observation in parsed.observations:
        if observation.category in ("entity", "why"):
            assert observation.text.strip(), observation

    blocking = [w for w in parsed.warnings if w.code in ("malformed-yaml", "format-version")]
    assert blocking == [], blocking


def _new_captures(result: ProbeResult) -> list[Path]:
    """Capture files this run added, as opposed to the golden vault's own.

    Matched by subject rather than by diffing the directory: the probe's
    decision is about the importer's batch size, and no seeded capture is.
    """
    assert result.vault_dir is not None
    return [
        note
        for note in inbox_notes(result.vault_dir)
        if "importer" in note.name or "batch" in note.name
    ]


# --- recall ------------------------------------------------------------


def test_recall_trigger_prompt_makes_the_agent_use_the_memory(tmp_path: Path) -> None:
    """A plain authoring task whose house answer only the memory knows.

    The prompt asks for a commit message and says nothing about memory. A
    hit means the agent went and looked; its reply then follows this team's
    rule instead of a generic convention.
    """
    series = run_series(
        label="recall trigger — palaia-memory",
        prompt=RECALL_PROMPT,
        workdir=tmp_path / "runs",
        expected=RECALL_EXPECTED_TOOLS,
    )
    _report(series)
    _assert_reachable(series)


def test_held_out_recall_prompt_makes_the_agent_use_the_memory(tmp_path: Path) -> None:
    """The same, on a prompt matching nothing the skill's description names."""
    series = run_series(
        label="recall trigger (held out) — palaia-memory",
        prompt=RECALL_PROMPT_UNSEEN,
        workdir=tmp_path / "runs",
        expected=RECALL_EXPECTED_TOOLS,
    )
    _report(series)
    _assert_reachable(series)


# --- capture -----------------------------------------------------------


def test_capture_trigger_prompt_makes_the_agent_capture(tmp_path: Path) -> None:
    """A decision stated in passing, on the way to a different question.

    The failure this guards against is the polite one: acknowledge the
    decision in prose, answer the question, save nothing.
    """
    series = run_series(
        label="capture trigger — palaia-memory",
        prompt=CAPTURE_PROMPT,
        workdir=tmp_path / "runs",
        expected=CAPTURE_EXPECTED_TOOLS,
    )
    _report(series)
    _assert_reachable(series)

    hit = series.first_hit()
    assert hit is not None
    call = hit.calls_to("capture")[0]
    for field_name in ("what_it_concerns", "why_keep", "content"):
        value = call.arguments.get(field_name)
        assert isinstance(value, str) and value.strip(), (field_name, call.arguments)
    # The substance has to survive into the note, not just the topic.
    assert "500" in str(call.arguments["content"]), call.arguments

    notes = _new_captures(hit)
    assert notes, "capture was called but no inbox note appeared"
    for note in notes:
        _assert_capture_conforms_to_format_spec(note)


def test_minimal_skill_alone_still_captures(tmp_path: Path) -> None:
    """``palaia-capture`` is for agents that cannot carry the core skill.

    It has to work on its own, with no recall guidance anywhere in context.
    """
    series = run_series(
        label="capture trigger — palaia-capture only",
        prompt=CAPTURE_PROMPT,
        workdir=tmp_path / "runs",
        expected=CAPTURE_EXPECTED_TOOLS,
        skills=("palaia-capture",),
    )
    _report(series)
    _assert_reachable(series)

    hit = series.first_hit()
    assert hit is not None
    notes = _new_captures(hit)
    assert notes, "capture was called but no inbox note appeared"
    for note in notes:
        _assert_capture_conforms_to_format_spec(note)


# --- baselines ---------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "prompt", "expected"),
    [
        ("recall trigger", RECALL_PROMPT, RECALL_EXPECTED_TOOLS),
        ("recall trigger (held out)", RECALL_PROMPT_UNSEEN, RECALL_EXPECTED_TOOLS),
        ("capture trigger", CAPTURE_PROMPT, CAPTURE_EXPECTED_TOOLS),
    ],
)
def test_baseline_without_any_skill_is_recorded(
    tmp_path: Path, label: str, prompt: str, expected: tuple[str, ...]
) -> None:
    """The control: identical prompt, hub connected, no skill loaded.

    Asserts only that the runs completed. Whether the agent used the memory
    anyway is the interesting part, and it is *reported* rather than
    asserted — an assertion either way would be a claim about the model, not
    about this SPEC's deliverable.
    """
    series = run_series(
        label=f"{label} — BASELINE (no skill)",
        prompt=prompt,
        workdir=tmp_path / "runs",
        expected=expected,
        skills=(),
    )
    _report(series)
    assert series.attempts == default_attempts()
    for result in series.results:
        assert result.reply.strip(), "a baseline run produced no reply at all"


# --- the harness itself ------------------------------------------------


def test_a_run_records_the_calls_it_makes(tmp_path: Path) -> None:
    """The recorder has to be trustworthy before any result above means
    anything, so one probe drives it with the tool named outright."""
    result = run_probe(
        label="harness self-check",
        prompt=(
            "Call the palaia recall tool with the query 'commit messages', then "
            "reply with the word DONE and nothing else."
        ),
        workdir=tmp_path / "run",
        skills=(),
    )
    _report(result)
    assert result.called("recall"), result.tools_used
    assert result.calls_to("recall")[0].arguments.get("query")
