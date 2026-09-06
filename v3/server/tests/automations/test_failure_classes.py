"""Issues #366 and #367: what the dispatcher does with the failures it meets.

A ``StashError`` (a value over the stash's limit, an invalid key) is
permanent: retrying it five times over half a minute only delays the honest
answer, and ``test_fire`` used to let it escape as an HTTP 500 instead of a
``dead`` log row. A *disabled* automation is not a deleted one: its queued
deliveries wait and run when it is enabled again, instead of being
dead-lettered for good. And a hand-edited ``automations.yaml`` with a bad
record must fail with a message naming the record, not a pydantic traceback.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from palaia_hub.automations import dispatcher as dispatcher_module
from palaia_hub.automations.dispatcher import AutomationDispatcher
from palaia_hub.automations.models import NotificationAction, StashSetAction
from palaia_hub.automations.outbox import AutomationOutbox
from palaia_hub.automations.store import AutomationError, AutomationStore
from palaia_hub.events.schema import Envelope
from palaia_hub.stash.models import StashError
from palaia_hub.stash.service import StashService
from palaia_hub.stash.store import StashStore

pytestmark = pytest.mark.anyio


def _build(
    tmp_path: Path,
    *,
    stash_service: StashService | None = None,
    max_attempts: int = 5,
) -> tuple[AutomationStore, AutomationOutbox, AutomationDispatcher, list[tuple[str, dict]]]:
    store = AutomationStore(tmp_path / "store")
    outbox = AutomationOutbox(tmp_path / "outbox.sqlite3")
    emitted: list[tuple[str, dict]] = []
    dispatcher = AutomationDispatcher(
        store,
        outbox,
        stash_service=stash_service,
        emit=lambda name, data: emitted.append((name, data)),
        max_attempts=max_attempts,
    )
    return store, outbox, dispatcher, emitted


def _over_limit_stash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StashService:
    service = StashService(StashStore(tmp_path / "stash.sqlite3"))

    async def _refuse(namespace: str, key: str, value: str) -> None:
        raise StashError("value is 3 MB, over the 1 MB limit")

    monkeypatch.setattr(service, "set", _refuse)
    return service


# ------------------------------------------------------------------ issue #366


async def test_a_stash_error_is_dead_lettered_on_the_first_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dispatcher_module, "_backoff_seconds", lambda attempt: 0.0)
    store, outbox, dispatcher, emitted = _build(
        tmp_path, stash_service=_over_limit_stash(tmp_path, monkeypatch), max_attempts=5
    )
    store.create(
        name="x",
        trigger_event="hub.started",
        action=StashSetAction(namespace="ns", key_template="k", value_template="v"),
    )
    dispatcher.on_event(Envelope(event="hub.started", data={}, origin="hub"))

    await dispatcher.deliver_due()

    row = outbox.all_rows()[0]
    assert row.status == "dead"
    assert row.attempts == 1, "a permanent failure is not retried"
    assert "over the 1 MB limit" in row.last_error
    assert any(name == "automation.failed" for name, _ in emitted)


async def test_test_fire_reports_a_stash_error_as_a_dead_row_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _outbox, dispatcher, _ = _build(
        tmp_path, stash_service=_over_limit_stash(tmp_path, monkeypatch)
    )
    created = store.create(
        name="x",
        trigger_event="hub.started",
        action=StashSetAction(namespace="ns", key_template="k", value_template="v"),
    )

    row = await dispatcher.test_fire(created.id)

    assert row.status == "dead"
    assert row.test is True
    assert "over the 1 MB limit" in row.last_error


def test_a_malformed_record_in_the_yaml_is_a_plain_error_naming_it(tmp_path: Path) -> None:
    store = AutomationStore(tmp_path / "store")
    store.create(
        name="fine", trigger_event="hub.started", action=NotificationAction(title_template="hi")
    )
    path = store.store_path
    # The owner hand-edits the file and adds a record without a trigger.
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["automations"].append(
        {"id": "broken", "name": "no trigger", "action": {"kind": "notification"}}
    )
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    with pytest.raises(AutomationError) as info:
        AutomationStore(tmp_path / "store")

    message = str(info.value)
    assert "record #2" in message
    assert "trigger_event" in message
    assert "Fix:" in message
    assert str(path) in message
