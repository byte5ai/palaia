from __future__ import annotations

from pathlib import Path

from palaia_hub.hooks.outbox import HookOutbox


def test_enqueue_then_claim_due_returns_the_row(tmp_path: Path) -> None:
    outbox = HookOutbox(tmp_path / "outbox.sqlite3")

    outbox.enqueue(
        hook_id="h1",
        event_id="e1",
        event_name="memory.entry.created",
        payload=b"{}",
        signature="sig",
    )

    rows = outbox.claim_due()
    assert len(rows) == 1
    assert rows[0].hook_id == "h1"
    assert rows[0].event_id == "e1"
    assert rows[0].status == "pending"
    assert rows[0].attempts == 0


def test_enqueue_is_idempotent_per_hook_and_event(tmp_path: Path) -> None:
    outbox = HookOutbox(tmp_path / "outbox.sqlite3")

    outbox.enqueue(hook_id="h1", event_id="e1", event_name="x", payload=b"{}", signature="sig")
    outbox.enqueue(hook_id="h1", event_id="e1", event_name="x", payload=b"{}", signature="sig")

    assert len(outbox.all_rows()) == 1


def test_mark_retry_delays_the_row_past_its_delay(tmp_path: Path) -> None:
    outbox = HookOutbox(tmp_path / "outbox.sqlite3")
    outbox.enqueue(hook_id="h1", event_id="e1", event_name="x", payload=b"{}", signature="sig")
    row = outbox.claim_due()[0]

    outbox.mark_retry(row.id, delay_seconds=3600.0, error="boom")

    assert outbox.claim_due() == []
    retried = outbox.all_rows()[0]
    assert retried.status == "pending"
    assert retried.attempts == 1
    assert retried.last_error == "boom"


def test_mark_dead_moves_the_row_to_dead_letters(tmp_path: Path) -> None:
    outbox = HookOutbox(tmp_path / "outbox.sqlite3")
    outbox.enqueue(hook_id="h1", event_id="e1", event_name="x", payload=b"{}", signature="sig")
    row = outbox.claim_due()[0]

    outbox.mark_dead(row.id, error="permanent failure")

    assert outbox.claim_due() == []
    dead = outbox.list_dead_letters()
    assert len(dead) == 1
    assert dead[0].id == row.id
    assert dead[0].last_error == "permanent failure"


def test_mark_delivered_removes_the_row_from_pending_and_dead(tmp_path: Path) -> None:
    outbox = HookOutbox(tmp_path / "outbox.sqlite3")
    outbox.enqueue(hook_id="h1", event_id="e1", event_name="x", payload=b"{}", signature="sig")
    row = outbox.claim_due()[0]

    outbox.mark_delivered(row.id)

    assert outbox.claim_due() == []
    assert outbox.list_dead_letters() == []
    assert outbox.count_pending() == 0


def test_deliveries_survive_a_restart(tmp_path: Path) -> None:
    """SPEC-201 acceptance: 'restart loses no queued outbox deliveries'."""
    path = tmp_path / "outbox.sqlite3"
    outbox = HookOutbox(path)
    outbox.enqueue(
        hook_id="h1", event_id="e1", event_name="memory.entry.created", payload=b'{"n":1}',
        signature="sig-1",
    )
    outbox.close()

    reopened = HookOutbox(path)
    rows = reopened.claim_due()

    assert len(rows) == 1
    assert rows[0].event_id == "e1"
    assert rows[0].payload == b'{"n":1}'
    assert rows[0].signature == "sig-1"


def test_claim_due_ignores_delivered_and_dead_rows(tmp_path: Path) -> None:
    outbox = HookOutbox(tmp_path / "outbox.sqlite3")
    outbox.enqueue(hook_id="h1", event_id="e1", event_name="x", payload=b"{}", signature="s1")
    outbox.enqueue(hook_id="h1", event_id="e2", event_name="x", payload=b"{}", signature="s2")
    outbox.enqueue(hook_id="h1", event_id="e3", event_name="x", payload=b"{}", signature="s3")
    rows = outbox.claim_due()
    outbox.mark_delivered(rows[0].id)
    outbox.mark_dead(rows[1].id, error="boom")

    remaining = outbox.claim_due()

    assert [r.event_id for r in remaining] == ["e3"]
