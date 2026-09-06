"""Issue #339 for webhooks: the outbox prunes, the listing has a limit, and a
wildcard hook no longer banks the 15-second ``health`` heartbeat."""

from __future__ import annotations

import time
from pathlib import Path

from palaia_hub.hooks.models import HookRecord
from palaia_hub.hooks.outbox import RETENTION_MAX_AGE_SECONDS, RETENTION_PER_HOOK, HookOutbox


def _fill(outbox: HookOutbox, hook_id: str, count: int, *, status: str = "delivered") -> None:
    for index in range(count):
        outbox.enqueue(
            hook_id=hook_id,
            event_id=f"{hook_id}-e{index}",
            event_name="memory.entry.created",
            payload=b"{}",
            signature="sig",
        )
    if status == "pending":
        return
    for row in outbox.claim_due(limit=count):
        if status == "dead":
            outbox.mark_dead(row.id, error="boom")
        else:
            outbox.mark_delivered(row.id)


def test_prune_caps_resolved_rows_per_hook_and_never_touches_pending(tmp_path: Path) -> None:
    outbox = HookOutbox(tmp_path / "outbox.sqlite3")
    _fill(outbox, "h1", 25)
    _fill(outbox, "h2", 4, status="dead")
    _fill(outbox, "h3", 6, status="pending")

    removed = outbox.prune(keep_per_hook=10)

    assert removed == 15
    assert len([row for row in outbox.all_rows() if row.hook_id == "h1"]) == 10
    assert len(outbox.list_dead_letters("h2")) == 4
    assert outbox.count_pending("h3") == 6


def test_prune_drops_resolved_rows_past_the_age_window(tmp_path: Path) -> None:
    outbox = HookOutbox(tmp_path / "outbox.sqlite3")
    _fill(outbox, "h1", 3, status="dead")

    assert outbox.prune(now=time.time()) == 0
    assert outbox.prune(now=time.time() + RETENTION_MAX_AGE_SECONDS + 60) == 3
    assert outbox.list_dead_letters("h1") == []


def test_the_outbox_stays_bounded_under_sustained_delivery(tmp_path: Path) -> None:
    outbox = HookOutbox(tmp_path / "outbox.sqlite3")
    for _ in range(3):
        _fill(outbox, "busy", RETENTION_PER_HOOK)
        outbox.prune()
        assert len(outbox.all_rows()) <= RETENTION_PER_HOOK


def test_dead_letter_listing_is_limited(tmp_path: Path) -> None:
    outbox = HookOutbox(tmp_path / "outbox.sqlite3")
    _fill(outbox, "h1", 12, status="dead")

    assert len(outbox.list_dead_letters("h1", limit=5)) == 5
    assert len(outbox.list_dead_letters(limit=7)) == 7
    assert len(outbox.list_dead_letters("h1")) == 12


def test_a_wildcard_hook_does_not_receive_the_health_heartbeat() -> None:
    wildcard = HookRecord(id="h", url="https://x.test", secret="s", created_at="now")
    assert wildcard.matches("memory.entry.created")
    assert wildcard.matches("stash.set")
    assert not wildcard.matches("health"), "~5,760 rows a day, describing nothing"

    explicit = HookRecord(
        id="h", url="https://x.test", secret="s", created_at="now", events=["health"]
    )
    assert explicit.matches("health")
    assert not explicit.matches("stash.set")
