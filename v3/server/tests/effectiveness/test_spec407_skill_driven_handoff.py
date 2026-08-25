"""SPEC-407 deliverable #3: the Phase-4 gate's skill-driven variant.

The scripted e2e in ``server/tests/e2e/test_spec407_phase4_gate.py`` proves
the *mechanism* works: told exactly what to do, session A can register,
save a fact, discover a peer through the directory and hand off a
``memory://`` reference — every one of the four steps spelled out. This
suite asks a different, harder question: with **only the task and the
skills loaded — the prompt never mentions the messenger, the directory, or
any tool by name — does a real agent reach for the handoff on its own?**

That question can only be answered by running a model, never by reading the
skill (see ``harness.py``'s module docstring), and the honest way to run it
is the one already built for exactly this in SPEC-404:
``messaging_harness.py``'s ``HANDOFF_PROMPT``/``CHECK_PROMPT`` probes, its
``sent_handoff_with_ref``/``registered`` predicates, and its seeded live
peer. This file adds nothing to that machinery — it runs it again, ``PALAIA_
EFFECTIVENESS_ATTEMPTS`` (default 3, this SPEC's stated budget) real times
per probe, and reports the rate **without a hard assert on the behaviour**.

This is the one difference from ``test_messenger_effectiveness.py``
(SPEC-404's own suite, which *does* hard-assert "at least one of N attempts
hit"): SPEC-407 asks for this evidence to be recorded honestly, as a rate,
"not a hard assert" — deliberately weaker than SPEC-404's own bar, because
this is gate evidence about how often the behaviour happens unprompted, not
a regression test for whether the skill still works at all (SPEC-404's
suite already is that test, stays green, and is not touched here). Every
run is still asserted to have actually completed (a non-empty reply) —
that is the harness working, not the skill.

Same opt-in gate as every effectiveness suite — real model calls, real
money, a CLI not every runner has::

    PALAIA_EFFECTIVENESS=1 uv run pytest \\
        server/tests/effectiveness/test_spec407_skill_driven_handoff.py -s -v
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
    run_messaging_series,
    sent_handoff_with_ref,
)

_SKIP = skip_reason()
pytestmark = pytest.mark.skipif(_SKIP is not None, reason=_SKIP or "")


def _report(label: str, results: list[ProbeResult]) -> None:
    print(f"\n## {label}")
    for result in results:
        print(result.summary())


def test_skill_driven_handoff_rate_is_recorded_honestly(tmp_path: Path) -> None:
    """SPEC-407 deliverable #3, session A's half: given only an end-of-shift
    task (never mentioning a tool by name) and the memory + messenger
    skills, how often does a real agent register itself *and* hand off with
    a memory:// reference, unprompted? Reported as a rate; not asserted
    either way — a low number is exactly as much this gate's evidence as a
    high one."""
    attempts = default_attempts()
    results = run_messaging_series(
        label="SPEC-407 skill-driven handoff",
        prompt=HANDOFF_PROMPT,
        workdir=tmp_path / "runs",
        skills=("palaia-memory", "palaia-messenger"),
        mount_vault=True,
        seed_peer_scope=SEED_PEER_SCOPE,
        attempts=attempts,
    )
    _report("skill-driven handoff", results)
    registered_rate = hit_rate(results, registered)
    handoff_rate = hit_rate(results, sent_handoff_with_ref)
    print("\n### SPEC-407 gate evidence — skill-driven handoff, unprompted")
    print(f"- attempts: {attempts}")
    print(f"- registered with the directory: {registered_rate}")
    print(f"- sent a handoff carrying a memory:// ref (not a pasted copy): {handoff_rate}")

    assert len(results) == attempts
    for result in results:
        assert result.reply.strip(), (
            f"a run produced no reply at all — the harness itself is broken, "
            f"not just a miss. Tools seen: {result.tools_used}"
        )


def test_skill_driven_check_rate_is_recorded_honestly(tmp_path: Path) -> None:
    """SPEC-407 deliverable #3, session B's half: given only a "get
    oriented" task that never says "message", "inbox" or "check", how often
    does a real agent check its inbox unprompted? Reported as a rate, not
    asserted."""
    attempts = default_attempts()
    results = run_messaging_series(
        label="SPEC-407 skill-driven check-on-start",
        prompt=CHECK_PROMPT,
        workdir=tmp_path / "runs",
        skills=("palaia-messenger",),
        mount_vault=False,
        attempts=attempts,
    )
    _report("skill-driven check-on-start", results)
    checked_rate = hit_rate(results, lambda r: r.called("messenger_check"))
    print("\n### SPEC-407 gate evidence — skill-driven check-on-start, unprompted")
    print(f"- attempts: {attempts}")
    print(f"- checked its inbox unprompted: {checked_rate}")

    assert len(results) == attempts
    for result in results:
        assert result.reply.strip(), (
            f"a run produced no reply at all — the harness itself is broken, "
            f"not just a miss. Tools seen: {result.tools_used}"
        )
