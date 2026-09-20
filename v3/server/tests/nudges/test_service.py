"""The Smart Nudge rate policy (issue #301).

Detection is cheap to get right; *not repeating* is the part that decides
whether this feature costs an agent's context window on every single call.
The issue's constraint is explicit — "the same nudge does not repeat on every
call (dedup per session/state), and total guidance stays small" — so each
clause of it gets a test here, driven by a fake clock and a fake session key
rather than by a running server.
"""

from __future__ import annotations

from palaia_hub.nudges import MAX_NUDGES_PER_RESULT, Nudge, NudgeEngine, VaultSignals
from palaia_hub.nudges.service import ANONYMOUS_SESSION

DEGRADED_RECALL = VaultSignals(
    action="recall", degraded=True, degraded_reason="no vectors are ready yet"
)
EMPTY_SEARCH = VaultSignals(action="search", hits=0)


class FakeClock:
    """A monotonic clock the test advances by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def always(session: str):  # noqa: ANN201 - a zero-arg callable returning `session`
    return lambda: session


def detector_firing(key: str):  # noqa: ANN201 - a Detector always returning `key`
    """A stand-in detector, so the budget tests exercise the engine's policy
    rather than the seeded detectors' conditions."""

    def detect(signals: VaultSignals) -> Nudge:
        return Nudge(key=key, text=f"{key} happened. Fix: do the thing.")

    return detect


def test_a_nudge_fires_the_first_time() -> None:
    engine = NudgeEngine(clock=FakeClock())
    assert [n.key for n in engine.emit(DEGRADED_RECALL)] == ["recall.degraded"]


def test_the_same_nudge_does_not_repeat_on_the_next_call() -> None:
    """The headline requirement: guidance is a heads-up, not a banner."""
    clock = FakeClock()
    engine = NudgeEngine(clock=clock)
    assert engine.emit(DEGRADED_RECALL)
    clock.advance(1.0)
    assert engine.emit(DEGRADED_RECALL) == []
    clock.advance(30.0)
    assert engine.emit(DEGRADED_RECALL) == []


def test_it_fires_again_once_the_cooldown_expires() -> None:
    """A long session whose index is still degraded deserves the reminder."""
    clock = FakeClock()
    engine = NudgeEngine(clock=clock, cooldown_seconds=100.0)
    assert engine.emit(DEGRADED_RECALL)
    clock.advance(99.0)
    assert engine.emit(DEGRADED_RECALL) == []
    clock.advance(2.0)
    assert engine.emit(DEGRADED_RECALL)


def test_a_changed_condition_speaks_up_before_the_cooldown_expires() -> None:
    """``state`` is what lets a materially different situation through: the
    index going from "still embedding" to "unavailable" is news."""
    engine = NudgeEngine(clock=FakeClock())
    assert engine.emit(DEGRADED_RECALL)
    worse = VaultSignals(
        action="recall", degraded=True, degraded_reason="the vector table failed to load"
    )
    fired = engine.emit(worse)
    assert [n.key for n in fired] == ["recall.degraded"]
    assert "failed to load" in fired[0].text


def test_the_cooldown_is_per_session() -> None:
    """Two clients connected to the same vault each get told once — one
    agent's heads-up must not silence another's."""
    clock = FakeClock()
    session = "a"
    engine = NudgeEngine(clock=clock, session_key=lambda: session)
    assert engine.emit(DEGRADED_RECALL)
    assert engine.emit(DEGRADED_RECALL) == []
    session = "b"
    assert engine.emit(DEGRADED_RECALL)


def test_different_nudges_do_not_silence_each_other() -> None:
    engine = NudgeEngine(clock=FakeClock())
    assert [n.key for n in engine.emit(DEGRADED_RECALL)] == ["recall.degraded"]
    assert [n.key for n in engine.emit(EMPTY_SEARCH)] == ["search.no_hits"]


def test_one_result_never_carries_more_than_the_cap() -> None:
    many = tuple(detector_firing(f"test.{i}") for i in range(MAX_NUDGES_PER_RESULT + 3))
    engine = NudgeEngine(detectors=many, clock=FakeClock())
    assert len(engine.emit(VaultSignals(action="search"))) == MAX_NUDGES_PER_RESULT


def test_the_cap_drops_the_extras_rather_than_marking_them_said() -> None:
    """A nudge crowded out by the per-result cap has not been delivered, so
    it must still be available on the next call."""
    detectors = tuple(detector_firing(key) for key in ("test.a", "test.b", "test.c"))
    engine = NudgeEngine(detectors=detectors, clock=FakeClock(), max_per_result=2)
    first = [n.key for n in engine.emit(VaultSignals(action="search"))]
    second = [n.key for n in engine.emit(VaultSignals(action="search"))]
    assert first == ["test.a", "test.b"]
    assert second == ["test.c"]


def test_no_detector_fires_means_no_work_and_no_state() -> None:
    engine = NudgeEngine(clock=FakeClock())
    assert engine.emit(VaultSignals(action="search", hits=3)) == []
    assert engine.emit(VaultSignals(action="write")) == []


def test_sessions_are_forgotten_in_lru_order_once_the_table_is_full() -> None:
    """Bounded memory on a long-lived hub. Eviction may only ever *re-allow*
    a nudge, never suppress one."""
    clock = FakeClock()
    session = "s0"
    engine = NudgeEngine(clock=clock, session_key=lambda: session, max_sessions=2)
    engine.emit(DEGRADED_RECALL)
    for name in ("s1", "s2"):
        session = name
        engine.emit(DEGRADED_RECALL)
    session = "s0"
    assert engine.emit(DEGRADED_RECALL), "an evicted session is treated as new"


def test_identities_are_forgotten_in_lru_order_within_a_session() -> None:
    clock = FakeClock()
    reason = "reason-0"
    engine = NudgeEngine(clock=clock, max_identities_per_session=2)

    def degraded(text: str) -> VaultSignals:
        return VaultSignals(action="recall", degraded=True, degraded_reason=text)

    engine.emit(degraded(reason))
    for other in ("reason-1", "reason-2"):
        engine.emit(degraded(other))
    assert engine.emit(degraded(reason)), "an evicted identity is treated as new"


def test_without_a_session_key_rate_limiting_still_applies() -> None:
    """A direct in-process call (no MCP session) must not become a way to
    emit the same nudge forever."""
    engine = NudgeEngine(clock=FakeClock(), session_key=always(ANONYMOUS_SESSION))
    assert engine.emit(DEGRADED_RECALL)
    assert engine.emit(DEGRADED_RECALL) == []
