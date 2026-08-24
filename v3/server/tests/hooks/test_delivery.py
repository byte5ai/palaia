"""SPEC-201 deliverable #2's acceptance criteria: signed delivery, retry on
failure, dead-lettering after N attempts, and durability across a restart —
against :class:`~webhook_receiver.LocalReceiver`, a real local HTTP server
rather than a mock, per the SPEC's own wording ("against a local receiver")."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from webhook_receiver import LocalReceiver

from palaia_hub.events.schema import Envelope
from palaia_hub.hooks import delivery
from palaia_hub.hooks.delivery import HookDispatcher
from palaia_hub.hooks.outbox import HookOutbox
from palaia_hub.hooks.signing import verify
from palaia_hub.hooks.store import HookStore


def _make_dispatcher(tmp_path: Path, *, max_attempts: int = 5) -> tuple[HookStore, HookDispatcher]:
    store = HookStore(tmp_path)
    outbox = HookOutbox(tmp_path / "outbox.sqlite3")
    return store, HookDispatcher(store, outbox, max_attempts=max_attempts)


def test_on_event_enqueues_only_for_matching_enabled_hooks(tmp_path: Path) -> None:
    store, dispatcher = _make_dispatcher(tmp_path)
    matching = store.create("https://example.com/a", ["memory.entry.created"])
    store.create("https://example.com/b", ["inbox.captured"])  # non-matching
    disabled = store.create("https://example.com/c", ["memory.entry.created"])
    store.set_enabled(disabled.info.id, False)

    envelope = Envelope(event="memory.entry.created", data={"path": "x.md"}, origin="vault")
    dispatcher.on_event(envelope)

    rows = dispatcher._outbox.all_rows()  # noqa: SLF001 - test introspection
    assert [r.hook_id for r in rows] == [matching.info.id]
    assert rows[0].event_id == envelope.id


@pytest.mark.anyio
async def test_vault_write_style_event_delivers_with_a_valid_signature(
    tmp_path: Path, local_receiver: LocalReceiver
) -> None:
    """The acceptance-criterion scenario: an event is delivered with a
    signature the receiver can independently verify."""
    store, dispatcher = _make_dispatcher(tmp_path)
    created = store.create(local_receiver.url, ["memory.entry.created"])

    envelope = Envelope(
        event="memory.entry.created", data={"path": "work/x.md"}, origin="vault", vault="work"
    )
    dispatcher.on_event(envelope)
    delivered = await dispatcher.deliver_due()
    await dispatcher.aclose()

    assert delivered == 1
    assert len(local_receiver.requests) == 1
    request = local_receiver.requests[0]
    signature = request.headers["X-Palaia-Signature"]
    assert verify(created.secret, request.body, signature)
    body = json.loads(request.body)
    assert body["event"] == "memory.entry.created"
    assert body["vault"] == "work"
    assert request.headers["X-Palaia-Event-Id"] == envelope.id
    assert request.headers["X-Palaia-Delivery-Attempt"] == "1"


@pytest.mark.anyio
async def test_a_failing_receiver_is_retried_then_succeeds(
    tmp_path: Path, local_receiver: LocalReceiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """'receiver 500 -> retried' (SPEC-201 acceptance)."""
    monkeypatch.setattr(delivery, "_backoff_seconds", lambda attempt: 0.0)
    local_receiver.status_code = 500
    store, dispatcher = _make_dispatcher(tmp_path)
    store.create(local_receiver.url)
    envelope = Envelope(event="hub.started", data={}, origin="hub")
    dispatcher.on_event(envelope)

    await dispatcher.deliver_due()
    row = dispatcher._outbox.all_rows()[0]  # noqa: SLF001
    assert row.status == "pending"
    assert row.attempts == 1

    local_receiver.status_code = 200
    await dispatcher.deliver_due()
    await dispatcher.aclose()

    row = dispatcher._outbox.all_rows()[0]  # noqa: SLF001
    assert row.status == "delivered"
    assert len(local_receiver.requests) == 2
    assert local_receiver.requests[1].headers["X-Palaia-Delivery-Attempt"] == "2"


@pytest.mark.anyio
async def test_permanent_failure_is_dead_lettered_after_max_attempts(
    tmp_path: Path, local_receiver: LocalReceiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """'permanent failure -> dead-letter visible via REST' (SPEC-201 acceptance).

    REST visibility itself is proven in test_routes.py; this proves the
    dispatcher/outbox half the REST endpoint reads from.
    """
    monkeypatch.setattr(delivery, "_backoff_seconds", lambda attempt: 0.0)
    local_receiver.status_code = 500
    store, dispatcher = _make_dispatcher(tmp_path, max_attempts=3)
    store.create(local_receiver.url)
    envelope = Envelope(event="hub.started", data={}, origin="hub")
    dispatcher.on_event(envelope)

    for _ in range(3):
        await dispatcher.deliver_due()
    await dispatcher.aclose()

    dead = dispatcher._outbox.list_dead_letters()  # noqa: SLF001
    assert len(dead) == 1
    assert dead[0].attempts == 3
    assert "500" in dead[0].last_error
    assert len(local_receiver.requests) == 3


@pytest.mark.anyio
async def test_hook_secret_never_appears_in_log_output_during_create_or_delivery(
    tmp_path: Path, local_receiver: LocalReceiver, caplog: pytest.LogCaptureFixture
) -> None:
    """SPEC-201 acceptance: 'hook secrets never logged (redaction test)'.

    Uses ``caplog`` (raw formatted records, ahead of any log-output
    filter) rather than ``palaia_hub.logging``'s global redaction filter —
    this proves the hooks package itself never emits the secret, not that
    the filter successfully hid a leak.
    """
    local_receiver.status_code = 500
    store, dispatcher = _make_dispatcher(tmp_path, max_attempts=1)
    created = store.create(local_receiver.url)  # logs id/url/events, not the secret

    envelope = Envelope(event="hub.started", data={}, origin="hub")
    with caplog.at_level(logging.DEBUG):
        dispatcher.on_event(envelope)
        await dispatcher.deliver_due()  # fails -> logs the failure, dead-letters it
        await dispatcher.aclose()

    assert created.secret not in caplog.text
