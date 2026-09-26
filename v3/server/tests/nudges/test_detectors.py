"""The seeded Smart Nudge detectors (issue #301).

Two things are under test here. The obvious one is that each detector fires
on exactly its own condition and stays silent otherwise — the "never generic
filler" half of the issue. The less obvious one is the *house rules* every
nudge text has to satisfy (names a fix, stays under the length ceiling),
checked over the whole registry rather than per detector, so a detector added
later cannot quietly skip them.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from palaia_hub.nudges import (
    INBOX_BACKLOG_THRESHOLD,
    MAX_NUDGE_CHARS,
    Nudge,
    SimilarNote,
    VaultSignals,
    detect,
)
from palaia_hub.nudges.detectors import (
    DETECTORS,
    capture_was_duplicate,
    context_budget_pressure,
    inbox_backlog,
    recall_degraded,
    search_found_nothing,
    unresolved_values_on_read,
    write_resembles_existing,
)

# The worst case for the similar-note text: three matches, every title far
# longer than a nudge can carry, and deep permalinks. The registry-wide
# length check below runs on exactly this, so the ceiling is verified for the
# input most likely to break it rather than for a comfortable one.
LONG_SIMILAR_NOTES = (
    SimilarNote(
        permalink="projects/platform/api-gateway/health-endpoint-behaviour",
        title="Health endpoint behaviour of the public API gateway after the v2 migration",
    ),
    SimilarNote(
        permalink="projects/platform/api-gateway/status-codes",
        title="Status codes the public API gateway returns for liveness and readiness probes",
    ),
    SimilarNote(
        permalink="ops/runbooks/gateway-monitoring",
        title="Runbook: monitoring the gateway's health endpoint from the on-call dashboard",
    ),
)

# One signals record per detector that makes it fire, used both for the
# per-detector assertions and for the registry-wide text lint below.
FIRING_SIGNALS: dict[str, VaultSignals] = {
    "recall.degraded": VaultSignals(
        action="recall", degraded=True, degraded_reason="no vectors are ready yet"
    ),
    "search.no_hits": VaultSignals(action="search", hits=0),
    "context.dropped": VaultSignals(action="build_context", degraded=True, dropped_notes=3),
    "context.shortened": VaultSignals(action="build_context", degraded=True),
    "inbox.backlog": VaultSignals(action="inbox_status", inbox_count=14),
    "capture.duplicate": VaultSignals(
        action="capture", duplicate_capture=True, duplicate_permalink="inbox/rate-limit"
    ),
    "read.unresolved_values": VaultSignals(
        action="read", unresolved_values=("embed-missing: ops/limits#rate",)
    ),
    "write.similar_note": VaultSignals(action="write", similar_notes=LONG_SIMILAR_NOTES),
    "capture.similar_note": VaultSignals(action="capture", similar_notes=LONG_SIMILAR_NOTES),
}


def only_nudge(signals: VaultSignals) -> Nudge:
    fired = detect(signals)
    assert len(fired) == 1, f"expected exactly one nudge, got {[n.key for n in fired]}"
    return fired[0]


# --- each detector fires on its own condition -------------------------------


def test_recall_degraded_names_the_reason_and_the_fix() -> None:
    nudge = recall_degraded(FIRING_SIGNALS["recall.degraded"])
    assert nudge is not None
    assert nudge.key == "recall.degraded"
    assert "no vectors are ready yet" in nudge.text
    # The reason is the fingerprint: "pending" becoming "unavailable" is a
    # different condition and is allowed to speak up again.
    assert nudge.state == "no vectors are ready yet"


def test_recall_degraded_is_silent_on_a_healthy_recall() -> None:
    assert recall_degraded(VaultSignals(action="recall", hits=5)) is None


def test_recall_degraded_falls_back_to_a_reason_when_none_was_given() -> None:
    nudge = recall_degraded(VaultSignals(action="recall", degraded=True))
    assert nudge is not None
    assert nudge.state, "a degraded recall with no reason still needs a fingerprint"


def test_search_with_no_hits_points_at_recall() -> None:
    nudge = search_found_nothing(FIRING_SIGNALS["search.no_hits"])
    assert nudge is not None
    assert "recall" in nudge.text


@pytest.mark.parametrize("hits", [1, 10])
def test_search_with_hits_says_nothing(hits: int) -> None:
    assert search_found_nothing(VaultSignals(action="search", hits=hits)) is None


def test_search_detector_ignores_an_unmeasured_hit_count() -> None:
    """``hits=None`` means "this action does not report hits", not zero."""
    assert search_found_nothing(VaultSignals(action="search")) is None


def test_dropped_notes_are_reported_with_their_count() -> None:
    nudge = context_budget_pressure(FIRING_SIGNALS["context.dropped"])
    assert nudge is not None
    assert nudge.key == "context.dropped"
    assert "3" in nudge.text


def test_a_shortened_package_is_distinct_from_a_dropped_one() -> None:
    nudge = context_budget_pressure(FIRING_SIGNALS["context.shortened"])
    assert nudge is not None
    assert nudge.key == "context.shortened"


def test_a_context_package_that_fit_says_nothing() -> None:
    assert context_budget_pressure(VaultSignals(action="build_context", hits=4)) is None


def test_inbox_backlog_fires_at_the_threshold_and_not_below() -> None:
    below = VaultSignals(action="inbox_status", inbox_count=INBOX_BACKLOG_THRESHOLD - 1)
    at = VaultSignals(action="inbox_status", inbox_count=INBOX_BACKLOG_THRESHOLD)
    assert inbox_backlog(below) is None
    assert inbox_backlog(at) is not None


def test_inbox_backlog_state_is_bucketed_not_exact() -> None:
    """A count that merely wobbles must not re-fire the nudge; one that grows
    into the next bucket may."""
    eleven = inbox_backlog(VaultSignals(action="inbox_status", inbox_count=11))
    twelve = inbox_backlog(VaultSignals(action="inbox_status", inbox_count=12))
    twenty = inbox_backlog(VaultSignals(action="inbox_status", inbox_count=20))
    assert eleven is not None and twelve is not None and twenty is not None
    assert eleven.state == twelve.state
    assert twenty.state != eleven.state


def test_inbox_backlog_ignores_an_unmeasured_count() -> None:
    assert inbox_backlog(VaultSignals(action="inbox_status")) is None


def test_duplicate_capture_names_the_note_to_edit_instead() -> None:
    nudge = capture_was_duplicate(FIRING_SIGNALS["capture.duplicate"])
    assert nudge is not None
    assert "inbox/rate-limit" in nudge.text


def test_a_fresh_capture_says_nothing() -> None:
    assert capture_was_duplicate(VaultSignals(action="capture")) is None


def test_unresolved_values_are_counted_and_the_first_is_named() -> None:
    nudge = unresolved_values_on_read(
        VaultSignals(
            action="read",
            unresolved_values=("embed-missing: ops/limits#rate", "embed-cycle: a#b"),
        )
    )
    assert nudge is not None
    assert "2" in nudge.text
    assert "ops/limits#rate" in nudge.text


def test_a_clean_read_says_nothing() -> None:
    assert unresolved_values_on_read(VaultSignals(action="read")) is None


def test_a_similar_note_is_named_by_permalink_and_title() -> None:
    """Issue #187: the agent needs the id to act on and the title to
    recognize — and the warning must not claim more than it knows."""
    nudge = write_resembles_existing(
        VaultSignals(
            action="write",
            similar_notes=(SimilarNote(permalink="ops/health", title="Health endpoint"),),
        )
    )
    assert nudge is not None
    assert nudge.key == "write.similar_note"
    assert "'Health endpoint' (ops/health)" in nudge.text
    assert "Possible overlap or contradiction" in nudge.text
    assert "edit that note" in nudge.text


def test_up_to_three_similar_notes_are_named_when_they_fit() -> None:
    notes = tuple(SimilarNote(permalink=f"ops/n{i}", title=f"Note {i}") for i in range(5))
    nudge = write_resembles_existing(VaultSignals(action="write", similar_notes=notes))
    assert nudge is not None
    assert all(f"(ops/n{i})" in nudge.text for i in range(3))
    assert "(ops/n3)" not in nudge.text


def test_the_best_match_is_always_named_even_when_nothing_else_fits() -> None:
    nudge = write_resembles_existing(FIRING_SIGNALS["write.similar_note"])
    assert nudge is not None
    assert f"({LONG_SIMILAR_NOTES[0].permalink})" in nudge.text
    assert len(nudge.text) <= MAX_NUDGE_CHARS


def test_similar_note_state_is_the_closest_note() -> None:
    """The same note resembled again stays quiet for the cooldown; a
    different closest note is a different warning."""
    nudge = write_resembles_existing(FIRING_SIGNALS["write.similar_note"])
    assert nudge is not None
    assert nudge.state == LONG_SIMILAR_NOTES[0].permalink


def test_a_capture_that_resembles_a_note_gets_its_own_key() -> None:
    nudge = write_resembles_existing(FIRING_SIGNALS["capture.similar_note"])
    assert nudge is not None
    assert nudge.key == "capture.similar_note"


def test_a_write_with_no_similar_note_says_nothing() -> None:
    assert write_resembles_existing(VaultSignals(action="write")) is None
    assert write_resembles_existing(VaultSignals(action="capture")) is None


def test_a_deduplicated_capture_does_not_also_warn_about_similarity() -> None:
    """Nothing was written, and ``capture.duplicate`` already names the
    original — two nudges about one non-event would be noise."""
    signals = VaultSignals(
        action="capture",
        duplicate_capture=True,
        duplicate_permalink="inbox/health",
        similar_notes=(SimilarNote(permalink="ops/health", title="Health"),),
    )
    assert write_resembles_existing(signals) is None
    assert [nudge.key for nudge in detect(signals)] == ["capture.duplicate"]


# --- the action gate --------------------------------------------------------


@pytest.mark.parametrize("key", sorted(FIRING_SIGNALS))
def test_a_firing_condition_on_the_wrong_action_stays_silent(key: str) -> None:
    """Every detector matches on ``action`` first: the same facts arriving
    from a different operation are not that operation's problem."""
    assert detect(replace(FIRING_SIGNALS[key], action="list")) == []


def test_an_ordinary_result_earns_no_guidance() -> None:
    """The common case, and the one that matters for context cost."""
    assert detect(VaultSignals(action="search", hits=7)) == []
    assert detect(VaultSignals(action="write")) == []


@pytest.mark.parametrize("key", sorted(FIRING_SIGNALS))
def test_each_condition_fires_exactly_its_own_nudge(key: str) -> None:
    assert only_nudge(FIRING_SIGNALS[key]).key == key


# --- house rules over the whole registry ------------------------------------


@pytest.mark.parametrize("key", sorted(FIRING_SIGNALS))
def test_every_nudge_names_a_fix(key: str) -> None:
    """The repository-wide rule for anything an agent reads: say what
    happened, then name the concrete next action."""
    text = only_nudge(FIRING_SIGNALS[key]).text
    assert "Fix:" in text, f"{key} does not name a fix"
    assert not text.endswith("Fix:"), f"{key} has an empty fix"


@pytest.mark.parametrize("key", sorted(FIRING_SIGNALS))
def test_every_nudge_stays_within_the_context_budget(key: str) -> None:
    text = only_nudge(FIRING_SIGNALS[key]).text
    assert len(text) <= MAX_NUDGE_CHARS, f"{key} is {len(text)} chars, over {MAX_NUDGE_CHARS}"


def test_every_registered_detector_has_a_firing_case_in_this_table() -> None:
    """Without this, a detector added later would silently skip the
    name-a-fix and length checks above — they only see what the table fires.
    """
    silent = [
        detector.__name__
        for detector in DETECTORS
        if not any(detector(signals) for signals in FIRING_SIGNALS.values())
    ]
    assert not silent, f"detector(s) with no firing case in FIRING_SIGNALS: {silent}"


def test_the_table_has_no_stale_entries() -> None:
    """The other direction: a key whose detector was removed or renamed."""
    produced = {
        nudge.key
        for signals in FIRING_SIGNALS.values()
        for detector in DETECTORS
        if (nudge := detector(signals)) is not None
    }
    assert produced == set(FIRING_SIGNALS)
