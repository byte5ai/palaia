"""Issue #339: the delivery log is a window, not an archive.

Every matched event inserts a row that used to stay forever, and the
per-automation deliveries endpoint returned the whole history in one
response. Resolved rows now expire by age and by count; pending rows are
never touched; the endpoint pages.
"""

from __future__ import annotations

import time
from pathlib import Path

from palaia_hub.automations.outbox import (
    RETENTION_MAX_AGE_SECONDS,
    RETENTION_PER_AUTOMATION,
    AutomationOutbox,
)


def _fill(
    outbox: AutomationOutbox, automation_id: str, count: int, *, resolve: bool = True
) -> None:
    for index in range(count):
        outbox.enqueue(
            automation_id=automation_id,
            event_id=f"{automation_id}-e{index}",
            event_name="stash.set",
            action_kind="notification",
            rendered_action={"title": "t", "body": "b"},
        )
    if resolve:
        for row in outbox.claim_due(limit=count):
            outbox.mark_delivered(row.id)


def test_prune_caps_resolved_rows_per_automation_and_keeps_the_newest(tmp_path: Path) -> None:
    outbox = AutomationOutbox(tmp_path / "outbox.sqlite3")
    _fill(outbox, "a1", 30)
    _fill(outbox, "a2", 5)

    removed = outbox.prune(keep_per_automation=10)

    assert removed == 20
    kept = outbox.list_for_automation("a1", limit=500)
    assert len(kept) == 10
    assert [row.event_id for row in kept][:2] == ["a1-e29", "a1-e28"], "newest survive"
    assert len(outbox.list_for_automation("a2", limit=500)) == 5


def test_prune_never_touches_pending_rows(tmp_path: Path) -> None:
    outbox = AutomationOutbox(tmp_path / "outbox.sqlite3")
    _fill(outbox, "a1", 12, resolve=False)
    _fill(outbox, "a1", 0)

    assert outbox.prune(keep_per_automation=3, max_age_seconds=0) == 0
    assert outbox.count_pending("a1") == 12


def test_prune_drops_resolved_rows_older_than_the_retention_window(tmp_path: Path) -> None:
    outbox = AutomationOutbox(tmp_path / "outbox.sqlite3")
    _fill(outbox, "a1", 4)

    # Nothing is old yet ...
    assert outbox.prune(now=time.time()) == 0
    # ... until the clock moves past the window.
    assert outbox.prune(now=time.time() + RETENTION_MAX_AGE_SECONDS + 3600) == 4
    assert outbox.list_for_automation("a1") == []


def test_the_outbox_stays_bounded_under_sustained_delivery(tmp_path: Path) -> None:
    """The acceptance criterion: after N deliveries the file holds at most
    the retention count, however large N is."""
    outbox = AutomationOutbox(tmp_path / "outbox.sqlite3")
    for batch in range(3):
        _fill(outbox, "busy", RETENTION_PER_AUTOMATION)
        # What the delivery loop does on its cadence.
        outbox.prune()
        assert len(outbox.all_rows()) <= RETENTION_PER_AUTOMATION, batch
        # And the newest delivery is always still there.
        newest = outbox.list_for_automation("busy", limit=1)[0]
        assert newest.event_id == f"busy-e{RETENTION_PER_AUTOMATION - 1}"


def test_list_for_automation_pages_newest_first(tmp_path: Path) -> None:
    outbox = AutomationOutbox(tmp_path / "outbox.sqlite3")
    _fill(outbox, "a1", 7)

    first = outbox.list_for_automation("a1", limit=3)
    assert [row.event_id for row in first] == ["a1-e6", "a1-e5", "a1-e4"]
    second = outbox.list_for_automation("a1", limit=3, before_id=first[-1].id)
    assert [row.event_id for row in second] == ["a1-e3", "a1-e2", "a1-e1"]
    third = outbox.list_for_automation("a1", limit=3, before_id=second[-1].id)
    assert [row.event_id for row in third] == ["a1-e0"]
    assert outbox.list_for_automation("a1", limit=3, before_id=third[-1].id) == []


def test_count_recent_counts_rows_created_inside_the_window(tmp_path: Path) -> None:
    outbox = AutomationOutbox(tmp_path / "outbox.sqlite3")
    _fill(outbox, "a1", 5)
    _fill(outbox, "a2", 2)

    assert outbox.count_recent("a1", window_seconds=60) == 5
    assert outbox.count_recent("a2", window_seconds=60) == 2
    assert outbox.count_recent("a3", window_seconds=60) == 0
