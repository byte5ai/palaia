"""SPEC-307 deliverable #1/#2 and the loop-guard acceptance criterion."""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.automations.models import NotificationAction
from palaia_hub.automations.store import AutomationError, AutomationStore


def _action() -> NotificationAction:
    return NotificationAction(title_template="hello", body_template="{{event}}")


def test_create_and_list(tmp_path: Path) -> None:
    store = AutomationStore(tmp_path)
    created = store.create(name="Notify me", trigger_event="memory.entry.created", action=_action())

    listed = store.list_info()
    assert len(listed) == 1
    assert listed[0].id == created.id
    assert listed[0].enabled is True


def test_persists_across_reload(tmp_path: Path) -> None:
    store = AutomationStore(tmp_path)
    created = store.create(name="Notify me", trigger_event="memory.entry.created", action=_action())

    reloaded = AutomationStore(tmp_path)
    assert reloaded.get(created.id) is not None
    assert reloaded.get(created.id).name == "Notify me"  # type: ignore[union-attr]


def test_set_enabled_and_delete(tmp_path: Path) -> None:
    store = AutomationStore(tmp_path)
    created = store.create(name="x", trigger_event="hub.started", action=_action())

    disabled = store.set_enabled(created.id, False)
    assert disabled.enabled is False

    store.delete(created.id)
    assert store.get(created.id) is None


def test_delete_unknown_id_raises() -> None:
    store = AutomationStore(Path("/tmp/does-not-matter-unused"))
    with pytest.raises(AutomationError, match="no automation with id"):
        store.delete("nope")


@pytest.mark.parametrize(
    "trigger", ["automation.fired", "automation.failed", "automation.anything"]
)
def test_loop_guard_refuses_automation_dot_star_trigger_at_create_time(
    tmp_path: Path, trigger: str
) -> None:
    """Acceptance: 'an automation on automation.fired is refused at create time'."""
    store = AutomationStore(tmp_path)
    with pytest.raises(AutomationError, match="loop"):
        store.create(name="x", trigger_event=trigger, action=_action())


def test_loop_guard_also_applies_on_update(tmp_path: Path) -> None:
    store = AutomationStore(tmp_path)
    created = store.create(name="x", trigger_event="hub.started", action=_action())

    with pytest.raises(AutomationError, match="loop"):
        store.update(created.id, trigger_event="automation.fired")


def test_empty_trigger_event_is_rejected(tmp_path: Path) -> None:
    store = AutomationStore(tmp_path)
    with pytest.raises(AutomationError, match="trigger event"):
        store.create(name="x", trigger_event="", action=_action())


def test_malformed_condition_is_rejected_with_a_plain_language_error(tmp_path: Path) -> None:
    from palaia_hub.automations.models import ConditionClause

    store = AutomationStore(tmp_path)
    bad_condition = [ConditionClause(field="not_a_real_field", op="equals", value="x")]
    with pytest.raises(AutomationError, match="not recognized"):
        store.create(
            name="x", trigger_event="hub.started", action=_action(), condition=bad_condition
        )


def test_wildcard_trigger_is_allowed(tmp_path: Path) -> None:
    store = AutomationStore(tmp_path)
    created = store.create(name="x", trigger_event="*", action=_action())
    assert created.trigger_event == "*"
