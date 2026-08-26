"""The durable outbox (SPEC-307 deliverable #1: "same outbox/delivery
discipline" as :mod:`palaia_hub.hooks.outbox`) — restart durability and
idempotent enqueue."""

from __future__ import annotations

from pathlib import Path

from palaia_hub.automations.outbox import AutomationOutbox


def test_enqueue_is_idempotent_per_automation_and_event(tmp_path: Path) -> None:
    outbox = AutomationOutbox(tmp_path / "outbox.sqlite3")
    outbox.enqueue(
        automation_id="a1",
        event_id="e1",
        event_name="hub.started",
        action_kind="notification",
        rendered_action={"title": "x"},
    )
    outbox.enqueue(
        automation_id="a1",
        event_id="e1",
        event_name="hub.started",
        action_kind="notification",
        rendered_action={"title": "x"},
    )

    assert len(outbox.all_rows()) == 1


def test_restart_loses_no_queued_delivery(tmp_path: Path) -> None:
    path = tmp_path / "outbox.sqlite3"
    outbox = AutomationOutbox(path)
    outbox.enqueue(
        automation_id="a1",
        event_id="e1",
        event_name="hub.started",
        action_kind="notification",
        rendered_action={"title": "x"},
    )
    outbox.close()

    reopened = AutomationOutbox(path)
    rows = reopened.claim_due()
    assert len(rows) == 1
    assert rows[0].status == "pending"


def test_record_resolved_is_immediately_queryable_and_not_pending(tmp_path: Path) -> None:
    outbox = AutomationOutbox(tmp_path / "outbox.sqlite3")
    row = outbox.record_resolved(
        automation_id="a1",
        event_id="test-1",
        event_name="hub.started",
        action_kind="notification",
        rendered_action={"title": "x"},
        status="delivered",
        last_error="",
        test=True,
    )

    assert row.test is True
    assert row.status == "delivered"
    assert outbox.claim_due() == []
    assert outbox.list_for_automation("a1") == [row]


def test_mark_retry_then_delivered(tmp_path: Path) -> None:
    outbox = AutomationOutbox(tmp_path / "outbox.sqlite3")
    outbox.enqueue(
        automation_id="a1",
        event_id="e1",
        event_name="hub.started",
        action_kind="notification",
        rendered_action={"title": "x"},
    )
    row = outbox.claim_due()[0]
    outbox.mark_retry(row.id, delay_seconds=0.0, error="boom")
    retried = outbox.claim_due()[0]
    assert retried.attempts == 1
    assert retried.last_error == "boom"

    outbox.mark_delivered(retried.id)
    assert outbox.claim_due() == []
    assert outbox.all_rows()[0].status == "delivered"


def test_mark_dead(tmp_path: Path) -> None:
    outbox = AutomationOutbox(tmp_path / "outbox.sqlite3")
    outbox.enqueue(
        automation_id="a1",
        event_id="e1",
        event_name="hub.started",
        action_kind="notification",
        rendered_action={"title": "x"},
    )
    row = outbox.claim_due()[0]
    outbox.mark_dead(row.id, error="permanent failure")

    dead = outbox.all_rows()[0]
    assert dead.status == "dead"
    assert dead.attempts == 1
    assert dead.last_error == "permanent failure"


def test_count_pending(tmp_path: Path) -> None:
    outbox = AutomationOutbox(tmp_path / "outbox.sqlite3")
    outbox.enqueue(
        automation_id="a1",
        event_id="e1",
        event_name="hub.started",
        action_kind="notification",
        rendered_action={},
    )
    outbox.enqueue(
        automation_id="a2",
        event_id="e2",
        event_name="hub.started",
        action_kind="notification",
        rendered_action={},
    )
    assert outbox.count_pending() == 2
    assert outbox.count_pending("a1") == 1
