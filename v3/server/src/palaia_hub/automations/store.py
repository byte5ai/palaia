"""The automation store: trigger -> condition -> action configuration.

Persisted as ``automations.yaml`` under the hub's home directory, same
shape of module as :class:`palaia_hub.hooks.store.HookStore` (atomic writes,
same directory, same YAML-list-of-records shape). No secret ever lives
here — unlike a webhook, none of the three action kinds this SPEC adds
carries a credential — so there is no plaintext-vs-hashed trade-off to make
and no "shown once" response shape.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..config import palaia_home
from ..security.files import harden_file
from ..vault.atomic import atomic_write_text
from .conditions import ConditionError, validate_condition
from .models import Action, AutomationInfo, AutomationRecord, ConditionClause

logger = logging.getLogger("palaia_hub.automations.store")

AUTOMATIONS_FILE = "automations.yaml"

#: Deliverable #6 / acceptance: "an automation on automation.fired is
#: refused at create time" — the fixed loop-guard rule. Checked against the
#: trigger event exactly, and against the wildcard (which would also catch
#: automation.* events) — a trigger of "*" is allowed (it is meaningful for
#: every other event), but the dispatcher's own runtime guard (see
#: dispatcher.py) is what actually keeps a "*" trigger from ever firing on
#: an automation.* event, belt-and-suspenders with this create-time check.
LOOP_GUARD_PREFIX = "automation."

_HEADER = (
    "# palaia automations — trigger -> condition -> action rules.\n"
    "# See v3/docs/events.md §automations for the condition/template grammar.\n"
)


class AutomationError(RuntimeError):
    """Raised for a caller-facing automation-store failure."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_trigger(trigger_event: str) -> None:
    if not trigger_event or not trigger_event.strip():
        raise AutomationError(
            "an automation needs a trigger event. Fix: pick one of the event "
            "names in docs/events.md, or '*' for every event."
        )
    if trigger_event.startswith(LOOP_GUARD_PREFIX):
        raise AutomationError(
            f"an automation cannot trigger on {trigger_event!r} — automations "
            f"never trigger on their own automation.* events, to avoid a loop. "
            f"Fix: pick a different trigger event."
        )


class AutomationStore:
    """Create, list, update, enable/disable, and delete automations."""

    def __init__(self, home: Path | None = None) -> None:
        self.home = Path(home).expanduser() if home is not None else palaia_home()
        self._records: dict[str, AutomationRecord] = {}
        self._load()

    @property
    def store_path(self) -> Path:
        return self.home / AUTOMATIONS_FILE

    # ------------------------------------------------------------- persistence

    def _load(self) -> None:
        path = self.store_path
        if not path.exists():
            return
        try:
            raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise AutomationError(
                f"{path}: could not parse YAML ({exc}). Fix: correct the syntax, "
                f"or delete the file to start with no automations configured."
            ) from exc
        if not raw:
            return
        if not isinstance(raw, Mapping) or not isinstance(raw.get("automations"), list):
            raise AutomationError(
                f"{path}: expected an 'automations:' list of records. Fix: "
                f"correct the file, or delete it to start over."
            )
        for item in raw["automations"]:
            record = AutomationRecord.model_validate(item)
            self._records[record.id] = record

    def _save(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        payload = {
            "automations": [r.model_dump(mode="json") for r in self._records.values()]
        }
        text = _HEADER + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        atomic_write_text(self.store_path, text)
        # SPEC-502: `atomic_write_text` already lands a 0600 file (its temp
        # file comes from `tempfile.mkstemp`), but the mode is then an
        # accident of that helper rather than a stated property of this
        # store — and an automation's action template can carry a webhook
        # URL. Say it here, like the token and hook stores do.
        harden_file(self.store_path)

    # ----------------------------------------------------------------- queries

    def list_info(self) -> list[AutomationInfo]:
        return [AutomationInfo.from_record(r) for r in self._records.values()]

    def get(self, automation_id: str) -> AutomationRecord | None:
        return self._records.get(automation_id)

    # ------------------------------------------------------------- mutations

    def create(
        self,
        *,
        name: str,
        trigger_event: str,
        action: Action,
        condition: list[ConditionClause] | None = None,
    ) -> AutomationInfo:
        condition = condition or []
        _validate_trigger(trigger_event)
        try:
            validate_condition(condition)
        except ConditionError as exc:
            raise AutomationError(str(exc)) from exc
        automation_id = secrets.token_urlsafe(9)
        record = AutomationRecord(
            id=automation_id,
            name=name.strip() or "Untitled automation",
            trigger_event=trigger_event,
            condition=condition,
            action=action,
            enabled=True,
            created_at=_now(),
        )
        self._records[automation_id] = record
        self._save()
        logger.info(
            "created automation %s %r (trigger=%r, action=%r)",
            automation_id,
            record.name,
            trigger_event,
            action.kind,
        )
        return AutomationInfo.from_record(record)

    def update(
        self,
        automation_id: str,
        *,
        name: str | None = None,
        trigger_event: str | None = None,
        action: Action | None = None,
        condition: list[ConditionClause] | None = None,
    ) -> AutomationInfo:
        record = self._records.get(automation_id)
        if record is None:
            raise AutomationError(
                f"no automation with id {automation_id!r}. Fix: check the id with list_info()."
            )
        new_trigger = trigger_event if trigger_event is not None else record.trigger_event
        new_condition = condition if condition is not None else record.condition
        _validate_trigger(new_trigger)
        try:
            validate_condition(new_condition)
        except ConditionError as exc:
            raise AutomationError(str(exc)) from exc
        updated = record.model_copy(
            update={
                "name": (name.strip() or record.name) if name is not None else record.name,
                "trigger_event": new_trigger,
                "condition": new_condition,
                "action": action if action is not None else record.action,
            }
        )
        self._records[automation_id] = updated
        self._save()
        logger.info("updated automation %s", automation_id)
        return AutomationInfo.from_record(updated)

    def set_enabled(self, automation_id: str, enabled: bool) -> AutomationInfo:
        record = self._records.get(automation_id)
        if record is None:
            raise AutomationError(
                f"no automation with id {automation_id!r}. Fix: check the id with list_info()."
            )
        updated = record.model_copy(update={"enabled": enabled})
        self._records[automation_id] = updated
        self._save()
        logger.info("automation %s %s", automation_id, "enabled" if enabled else "disabled")
        return AutomationInfo.from_record(updated)

    def delete(self, automation_id: str) -> None:
        if self._records.pop(automation_id, None) is None:
            raise AutomationError(
                f"no automation with id {automation_id!r}. Fix: check the id with list_info()."
            )
        self._save()
        logger.info("deleted automation %s", automation_id)


__all__ = ["AUTOMATIONS_FILE", "LOOP_GUARD_PREFIX", "AutomationError", "AutomationStore"]
