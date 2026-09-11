"""SPEC-307 deliverable #1/#6 and the acceptance criteria: real e2e delivery
for each new action kind, the loop guard, and delivery retry/dead-letter
using the exact same discipline as :mod:`palaia_hub.hooks.delivery`."""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.automations import dispatcher as dispatcher_module
from palaia_hub.automations.dispatcher import AutomationDispatcher
from palaia_hub.automations.models import (
    ConditionClause,
    MemoryWriteAction,
    NotificationAction,
    StashSetAction,
)
from palaia_hub.automations.outbox import AutomationOutbox
from palaia_hub.automations.store import AutomationStore
from palaia_hub.events.schema import Envelope
from palaia_hub.notifications.store import NotificationStore
from palaia_hub.stash.service import StashService
from palaia_hub.stash.store import StashStore
from palaia_hub.vault import EventBus as VaultEventBus
from palaia_hub.vault import VaultRegistry

pytestmark = pytest.mark.anyio


def _build(
    tmp_path: Path,
    *,
    vault_registry: VaultRegistry | None = None,
    stash_service: StashService | None = None,
    notification_store: NotificationStore | None = None,
    max_attempts: int = 5,
) -> tuple[AutomationStore, AutomationOutbox, AutomationDispatcher]:
    store = AutomationStore(tmp_path / "store")
    outbox = AutomationOutbox(tmp_path / "outbox.sqlite3")
    emitted: list[tuple[str, dict[str, object]]] = []
    dispatcher = AutomationDispatcher(
        store,
        outbox,
        vault_registry=vault_registry,
        stash_service=stash_service,
        notification_store=notification_store,
        emit=lambda name, data: emitted.append((name, data)),
        max_attempts=max_attempts,
    )
    dispatcher.emitted = emitted  # type: ignore[attr-defined]
    return store, outbox, dispatcher


async def _registry(tmp_path: Path) -> VaultRegistry:
    registry = VaultRegistry(tmp_path / "home", bus=VaultEventBus())
    await registry.create("work", tmp_path / "vaults/work")
    return registry


# ------------------------------------------------------------- memory_write


async def test_memory_write_action_lands_a_format_valid_capture(tmp_path: Path) -> None:
    registry = await _registry(tmp_path)
    store, outbox, dispatcher = _build(tmp_path, vault_registry=registry)
    store.create(
        name="capture findings",
        trigger_event="doctor.finding",
        action=MemoryWriteAction(
            vault="work",
            what_it_concerns_template="doctor finding {{data.code}}",
            why_keep_template="Severity {{data.severity}} needs a look.",
            content_template="{{data.detail}}",
        ),
    )

    envelope = Envelope(
        event="doctor.finding",
        data={"code": "E1", "severity": "high", "detail": "index drifted"},
        origin="index",
    )
    dispatcher.on_event(envelope)
    delivered = await dispatcher.deliver_due()

    assert delivered == 1
    engine = await registry.get("work")
    captures = [n for n in engine.catalog if n.startswith("inbox/")]
    assert len(captures) == 1
    note = await engine.read_note(captures[0].removesuffix(".md"))
    assert "doctor finding E1" in note.body or "doctor finding E1" in (note.title or "")
    assert "index drifted" in note.body
    assert note.frontmatter.get("type") == "capture"
    assert note.frontmatter.get("status") == "uncurated"
    assert any(name == "automation.fired" for name, _ in dispatcher.emitted)  # type: ignore[attr-defined]


async def test_memory_write_without_a_vault_registry_fails_with_a_plain_error(
    tmp_path: Path,
) -> None:
    store, outbox, dispatcher = _build(tmp_path, max_attempts=1)
    store.create(
        name="x",
        trigger_event="hub.started",
        action=MemoryWriteAction(
            vault="work",
            what_it_concerns_template="x",
            why_keep_template="y",
            content_template="z",
        ),
    )
    dispatcher.on_event(Envelope(event="hub.started", data={}, origin="hub"))
    await dispatcher.deliver_due()

    dead = outbox.all_rows()
    assert dead[0].status == "dead"
    assert "no vault registry" in dead[0].last_error


# ---------------------------------------------------------------- stash_set


async def test_stash_set_action_lands_a_real_stash_entry(tmp_path: Path) -> None:
    stash = StashService(StashStore(":memory:"))
    store, outbox, dispatcher = _build(tmp_path, stash_service=stash)
    store.create(
        name="stash it",
        trigger_event="memory.entry.created",
        action=StashSetAction(
            namespace="automations",
            key_template="last-{{vault}}",
            value_template="{{data.path}}",
        ),
    )

    envelope = Envelope(
        event="memory.entry.created", data={"path": "x.md"}, origin="vault", vault="work"
    )
    dispatcher.on_event(envelope)
    delivered = await dispatcher.deliver_due()

    assert delivered == 1
    result = await stash.get("automations", "last-work")
    assert result.found is True
    assert result.entry is not None
    assert result.entry.value == "x.md"


async def test_stash_set_without_a_stash_service_fails_with_a_plain_error(tmp_path: Path) -> None:
    store, outbox, dispatcher = _build(tmp_path, max_attempts=1)
    store.create(
        name="x",
        trigger_event="hub.started",
        action=StashSetAction(namespace="ns", key_template="k", value_template="v"),
    )
    dispatcher.on_event(Envelope(event="hub.started", data={}, origin="hub"))
    await dispatcher.deliver_due()

    row = outbox.all_rows()[0]
    assert row.status == "dead"
    assert "no stash" in row.last_error


# ------------------------------------------------------------- notification


async def test_notification_action_is_visible_via_the_store(tmp_path: Path) -> None:
    notifications = NotificationStore(tmp_path / "notifications.sqlite3")
    store, outbox, dispatcher = _build(tmp_path, notification_store=notifications)
    store.create(
        name="notify",
        trigger_event="curator.capture.needs_review",
        action=NotificationAction(
            title_template="Review needed: {{data.permalink}}",
            body_template="reason: {{data.reason}}",
        ),
    )

    envelope = Envelope(
        event="curator.capture.needs_review",
        data={"permalink": "inbox/x", "reason": "ambiguous"},
        origin="curator",
    )
    dispatcher.on_event(envelope)
    delivered = await dispatcher.deliver_due()

    assert delivered == 1
    entries = notifications.list()
    assert len(entries) == 1
    assert entries[0].title == "Review needed: inbox/x"
    assert entries[0].body == "reason: ambiguous"
    assert entries[0].read is False


# ---------------------------------------------------------------- condition


async def test_condition_filters_out_non_matching_events(tmp_path: Path) -> None:
    notifications = NotificationStore(tmp_path / "notifications.sqlite3")
    store, outbox, dispatcher = _build(tmp_path, notification_store=notifications)
    store.create(
        name="only high severity",
        trigger_event="doctor.finding",
        condition=[ConditionClause(field="data.severity", op="equals", value="high")],
        action=NotificationAction(title_template="{{data.code}}"),
    )

    dispatcher.on_event(
        Envelope(event="doctor.finding", data={"code": "E1", "severity": "low"}, origin="index")
    )
    dispatcher.on_event(
        Envelope(event="doctor.finding", data={"code": "E2", "severity": "high"}, origin="index")
    )
    delivered = await dispatcher.deliver_due()

    assert delivered == 1
    assert [row.rendered_action["title"] for row in outbox.all_rows()] == ["E2"]


# --------------------------------------------------------------------- loop


async def test_dispatcher_never_matches_an_automation_dot_star_event_even_with_wildcard(
    tmp_path: Path,
) -> None:
    """Acceptance / deliverable #6: an automation never triggers on
    automation.* events. Exercised at the dispatcher level (bypassing the
    store's create-time refusal) to prove the runtime guard independently."""
    notifications = NotificationStore(tmp_path / "notifications.sqlite3")
    store, outbox, dispatcher = _build(tmp_path, notification_store=notifications)
    store.create(
        name="everything", trigger_event="*", action=NotificationAction(title_template="fired")
    )

    dispatcher.on_event(Envelope(event="automation.fired", data={}, origin="automations"))
    dispatcher.on_event(Envelope(event="automation.failed", data={}, origin="automations"))

    assert outbox.all_rows() == []


# --------------------------------------------------------------- retry/dead


async def test_delivery_failure_retries_then_dead_letters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dispatcher_module, "_backoff_seconds", lambda attempt: 0.0)
    store, outbox, dispatcher = _build(tmp_path, max_attempts=3)  # no stash configured -> fails
    store.create(
        name="x",
        trigger_event="hub.started",
        action=StashSetAction(namespace="ns", key_template="k", value_template="v"),
    )
    dispatcher.on_event(Envelope(event="hub.started", data={}, origin="hub"))

    for _ in range(3):
        await dispatcher.deliver_due()

    row = outbox.all_rows()[0]
    assert row.status == "dead"
    assert row.attempts == 3
    assert any(name == "automation.failed" for name, _ in dispatcher.emitted)  # type: ignore[attr-defined]


async def test_disabled_automation_is_not_matched_by_on_event(tmp_path: Path) -> None:
    notifications = NotificationStore(tmp_path / "notifications.sqlite3")
    store, outbox, dispatcher = _build(tmp_path, notification_store=notifications)
    created = store.create(
        name="x", trigger_event="hub.started", action=NotificationAction(title_template="x")
    )
    store.set_enabled(created.id, False)

    dispatcher.on_event(Envelope(event="hub.started", data={}, origin="hub"))

    assert outbox.all_rows() == []


async def test_deleted_automation_dead_letters_a_pending_delivery(tmp_path: Path) -> None:
    notifications = NotificationStore(tmp_path / "notifications.sqlite3")
    store, outbox, dispatcher = _build(tmp_path, notification_store=notifications, max_attempts=1)
    created = store.create(
        name="x", trigger_event="hub.started", action=NotificationAction(title_template="x")
    )
    dispatcher.on_event(Envelope(event="hub.started", data={}, origin="hub"))
    store.delete(created.id)

    await dispatcher.deliver_due()

    row = outbox.all_rows()[0]
    assert row.status == "dead"
    assert "removed" in row.last_error


# ---------------------------------------------------------------- test-fire


async def test_test_fire_runs_the_real_pipeline_and_marks_the_delivery_test(
    tmp_path: Path,
) -> None:
    notifications = NotificationStore(tmp_path / "notifications.sqlite3")
    store, outbox, dispatcher = _build(tmp_path, notification_store=notifications)
    created = store.create(
        name="notify",
        trigger_event="doctor.finding",
        action=NotificationAction(title_template="{{data.code}}", body_template="test body"),
    )

    result = await dispatcher.test_fire(created.id, {"code": "E1"})

    assert result.test is True
    assert result.status == "delivered"
    entries = notifications.list()
    assert len(entries) == 1
    assert entries[0].title == "E1"


async def test_test_fire_reports_condition_not_matched_without_running_the_action(
    tmp_path: Path,
) -> None:
    notifications = NotificationStore(tmp_path / "notifications.sqlite3")
    store, outbox, dispatcher = _build(tmp_path, notification_store=notifications)
    created = store.create(
        name="notify",
        trigger_event="doctor.finding",
        condition=[ConditionClause(field="data.severity", op="equals", value="high")],
        action=NotificationAction(title_template="{{data.code}}"),
    )

    result = await dispatcher.test_fire(created.id, {"code": "E1", "severity": "low"})

    assert result.test is True
    assert result.status == "condition_not_matched"
    assert notifications.list() == []


async def test_test_fire_unknown_automation_raises(tmp_path: Path) -> None:
    from palaia_hub.automations.dispatcher import ActionError

    _, _, dispatcher = _build(tmp_path)
    with pytest.raises(ActionError):
        await dispatcher.test_fire("does-not-exist")
