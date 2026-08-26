"""SPEC-404 deliverable #3: does the messenger skill change what a real
agent does, unprompted?

Same opt-in gate as SPEC-207's suite (`test_skill_effectiveness.py`) and for
the same reason — real model calls, real money, a CLI not every runner
has::

    PALAIA_EFFECTIVENESS=1 uv run pytest server/tests/effectiveness -s -v

Read `messaging_harness.py` first: it explains the two probes, why session
A's peer is seeded outside the recorded path, and why a `messenger_send`
call alone is not the finding for the handoff probe. As in SPEC-207: the
assertion is the floor (the behaviour is reachable with the skill at all),
the printed hit rate is the finding, and the no-skill baselines assert
nothing about tool use — only that the run completed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .harness import ProbeResult, default_attempts, skip_reason
from .messaging_harness import (
    CHECK_PROMPT,
    HANDOFF_PROMPT,
    SEED_PEER_SCOPE,
    hit_rate,
    registered,
    run_messaging_probe,
    run_messaging_series,
    sent_handoff_with_ref,
)

_SKIP = skip_reason()
pytestmark = pytest.mark.skipif(_SKIP is not None, reason=_SKIP or "")


def _report(label: str, results: list[ProbeResult]) -> None:
    print(f"\n## {label}")
    for result in results:
        print(result.summary())


# --- session A: register + handoff with a reference --------------------


def test_session_a_registers_and_hands_off_with_a_reference(tmp_path: Path) -> None:
    """The task never mentions the messenger. A full hit is registering
    *and* sending a `handoff` whose `refs` carries the decision instead of
    its body — the token rule, exercised rather than merely stated."""
    results = run_messaging_series(
        label="register + handoff-with-ref — palaia-messenger",
        prompt=HANDOFF_PROMPT,
        workdir=tmp_path / "runs",
        skills=("palaia-memory", "palaia-messenger"),
        mount_vault=True,
        seed_peer_scope=SEED_PEER_SCOPE,
    )
    _report("register + handoff-with-ref", results)
    print(f"- registered: {hit_rate(results, registered)}")
    print(f"- handoff carried a memory:// ref (not a pasted copy): "
          f"{hit_rate(results, sent_handoff_with_ref)}")

    assert any(registered(r) for r in results), (
        f"never registered in {len(results)} attempt(s). "
        f"Tools seen: {[r.tools_used for r in results]}"
    )
    assert any(sent_handoff_with_ref(r) for r in results), (
        f"never sent a handoff with a memory:// ref in {len(results)} attempt(s). "
        f"messenger_send calls: "
        f"{[r.calls_to('messenger_send') for r in results]}"
    )


# --- session B: check-on-start -------------------------------------------


def test_session_b_checks_its_inbox_unprompted(tmp_path: Path) -> None:
    """The task says nothing about messages. A hit is `messenger_check`
    appearing anyway, at the start of an ordinary "get oriented" task."""
    results = run_messaging_series(
        label="check-on-start — palaia-messenger",
        prompt=CHECK_PROMPT,
        workdir=tmp_path / "runs",
        skills=("palaia-messenger",),
        mount_vault=False,
    )
    _report("check-on-start", results)
    print(f"- checked its inbox: {hit_rate(results, lambda r: r.called('messenger_check'))}")

    assert any(r.called("messenger_check") for r in results), (
        f"never checked its inbox in {len(results)} attempt(s). "
        f"Tools seen: {[r.tools_used for r in results]}"
    )


# --- baselines ------------------------------------------------------------


def test_baseline_handoff_without_the_skill_is_recorded(tmp_path: Path) -> None:
    """Control: the identical handoff task, hub connected, no skill loaded.
    Asserted only to have completed — whether it registers or hands off
    anyway is reported, not demanded either way."""
    results = run_messaging_series(
        label="register + handoff-with-ref — BASELINE (no skill)",
        prompt=HANDOFF_PROMPT,
        workdir=tmp_path / "runs",
        skills=(),
        mount_vault=True,
        seed_peer_scope=SEED_PEER_SCOPE,
    )
    _report("register + handoff-with-ref — BASELINE", results)
    assert len(results) == default_attempts()
    for result in results:
        assert result.reply.strip(), "a baseline run produced no reply at all"


def test_baseline_check_without_the_skill_is_recorded(tmp_path: Path) -> None:
    """Control for the check-on-start probe."""
    results = run_messaging_series(
        label="check-on-start — BASELINE (no skill)",
        prompt=CHECK_PROMPT,
        workdir=tmp_path / "runs",
        skills=(),
        mount_vault=False,
    )
    _report("check-on-start — BASELINE", results)
    assert len(results) == default_attempts()
    for result in results:
        assert result.reply.strip(), "a baseline run produced no reply at all"


# --- the harness itself ---------------------------------------------------


def test_a_messaging_run_records_the_calls_it_makes(tmp_path: Path) -> None:
    """The recorder has to be trustworthy before any result above means
    anything, so one probe drives it with the tools named outright."""
    result = run_messaging_probe(
        label="messaging harness self-check",
        prompt=(
            "Call the directory_register tool with scope 'self-check', then call "
            "messenger_check with the handle and session_secret you just got back, "
            "then reply with the word DONE and nothing else."
        ),
        workdir=tmp_path / "run",
        skills=(),
        mount_vault=False,
    )
    print(result.summary())
    assert result.called("directory_register"), result.tools_used
    assert result.called("messenger_check"), result.tools_used
