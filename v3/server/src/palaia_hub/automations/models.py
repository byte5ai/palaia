"""Automation data shapes: trigger, condition, action, and the delivery log.

SPEC-307 deliverable #1/#2: an automation is a single ``trigger -> condition
-> action`` rule (one trigger, one action — MASTERPLAN's "v1: one trigger to
one action" non-goal). The three new action kinds this SPEC adds
(``memory_write``, ``stash_set``, ``notification``) share one discriminated
:class:`Action` union so the store/dispatcher/routes handle any of them
uniformly; ``webhook`` (SPEC-201) stays its own, separate configuration
surface (:mod:`palaia_hub.hooks`) — see this package's ``__init__`` docstring
for why the two are not merged into one model.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Deliverable #2: field/op/value clauses, AND-combined. No general
#: expression language — a fixed, closed vocabulary (docs/events.md
#: §automations).
ConditionField = Literal["event", "origin", "vault"]
ConditionOp = Literal["equals", "contains", "prefix"]


class ConditionClause(BaseModel):
    """One ``field <op> value`` clause.

    ``field`` is either one of :data:`ConditionField` or a ``data.<key>``
    path reaching into the envelope's ``data`` object — validated as a
    string here (not a stricter ``Literal``) precisely because ``<key>`` is
    open-ended; :mod:`.conditions` is what actually enforces the grammar.
    """

    model_config = ConfigDict(extra="forbid")

    field: str
    op: ConditionOp
    value: str


class MemoryWriteAction(BaseModel):
    """Capture into a chosen vault's inbox (format spec §7), templated."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["memory_write"] = "memory_write"
    vault: str
    what_it_concerns_template: str
    why_keep_template: str
    content_template: str
    source_template: str | None = None


class StashSetAction(BaseModel):
    """Set one stash entry (namespace/key/value), templated."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stash_set"] = "stash_set"
    namespace: str
    key_template: str
    value_template: str


class NotificationAction(BaseModel):
    """Post one entry to the dashboard notification center, templated."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["notification"] = "notification"
    title_template: str
    body_template: str = ""


Action = Annotated[
    MemoryWriteAction | StashSetAction | NotificationAction,
    Field(discriminator="kind"),
]


class AutomationRecord(BaseModel):
    """One automation as persisted in ``automations.yaml``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    #: The single event name this automation fires on. ``"*"`` matches
    #: every event except the ``automation.*`` loop-guarded ones (see
    #: :mod:`.store`'s ``LOOP_GUARD_PREFIX``).
    trigger_event: str
    condition: list[ConditionClause] = Field(default_factory=list)
    action: Action
    enabled: bool = True
    created_at: str


class AutomationInfo(BaseModel):
    """The REST-facing view of an :class:`AutomationRecord`.

    Unlike :class:`~palaia_hub.hooks.models.HookRecord`, nothing here is a
    secret — an automation's action config never carries credentials — so
    this is a plain pass-through, kept as its own type for the same reason
    ``HookInfo`` is: a stable contract independent of internal storage
    shape.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    trigger_event: str
    condition: list[ConditionClause]
    action: Action
    enabled: bool
    created_at: str

    @classmethod
    def from_record(cls, record: AutomationRecord) -> AutomationInfo:
        return cls(
            id=record.id,
            name=record.name,
            trigger_event=record.trigger_event,
            condition=record.condition,
            action=record.action,
            enabled=record.enabled,
            created_at=record.created_at,
        )


DeliveryStatus = Literal["pending", "delivered", "dead", "condition_not_matched"]


class DeliveryLogEntry(BaseModel):
    """One queued/delivered/dead/test delivery — the per-automation log
    (deliverable #4)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    automation_id: str
    event_id: str
    event_name: str
    status: DeliveryStatus
    attempts: int
    last_error: str
    created_at: str
    test: bool


__all__ = [
    "Action",
    "AutomationInfo",
    "AutomationRecord",
    "ConditionClause",
    "ConditionField",
    "ConditionOp",
    "DeliveryLogEntry",
    "DeliveryStatus",
    "MemoryWriteAction",
    "NotificationAction",
    "StashSetAction",
]
