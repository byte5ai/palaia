"""REST surface for the automations editor (SPEC-307 deliverable #4).

Mounted at ``/api/automations`` by ``palaia_hub.app.create_app`` when given
an ``automation_store`` — same opt-in posture as ``/api/hooks``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from .dispatcher import ActionError, AutomationDispatcher
from .models import Action, AutomationInfo, ConditionClause, DeliveryLogEntry
from .outbox import AutomationOutbox, DeliveryRow
from .store import AutomationError, AutomationStore


class CreateAutomationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    trigger_event: str
    action: Action
    condition: list[ConditionClause] = []


class UpdateAutomationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    trigger_event: str | None = None
    action: Action | None = None
    condition: list[ConditionClause] | None = None


class SetEnabledRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class TestFireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: dict[str, object] = {}


def _to_log_entry(row: DeliveryRow) -> DeliveryLogEntry:
    return DeliveryLogEntry(
        id=row.id,
        automation_id=row.automation_id,
        event_id=row.event_id,
        event_name=row.event_name,
        status=row.status,  # type: ignore[arg-type]
        attempts=row.attempts,
        last_error=row.last_error,
        created_at=row.created_at,
        test=row.test,
    )


def build_automations_router(
    store: AutomationStore, outbox: AutomationOutbox, dispatcher: AutomationDispatcher
) -> APIRouter:
    router = APIRouter(prefix="/api/automations", tags=["automations"])

    @router.post("", response_model=AutomationInfo)
    async def create_automation(body: CreateAutomationRequest) -> AutomationInfo:
        try:
            return store.create(
                name=body.name,
                trigger_event=body.trigger_event,
                action=body.action,
                condition=body.condition,
            )
        except AutomationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("", response_model=list[AutomationInfo])
    async def list_automations() -> list[AutomationInfo]:
        return store.list_info()

    @router.get("/{automation_id}", response_model=AutomationInfo)
    async def get_automation(automation_id: str) -> AutomationInfo:
        record = store.get(automation_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"no automation with id {automation_id!r}")
        return AutomationInfo.from_record(record)

    @router.put("/{automation_id}", response_model=AutomationInfo)
    async def update_automation(
        automation_id: str, body: UpdateAutomationRequest
    ) -> AutomationInfo:
        try:
            return store.update(
                automation_id,
                name=body.name,
                trigger_event=body.trigger_event,
                action=body.action,
                condition=body.condition,
            )
        except AutomationError as exc:
            status = 404 if "no automation with id" in str(exc) else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @router.patch("/{automation_id}", response_model=AutomationInfo)
    async def set_enabled(automation_id: str, body: SetEnabledRequest) -> AutomationInfo:
        try:
            return store.set_enabled(automation_id, body.enabled)
        except AutomationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.delete("/{automation_id}", status_code=204)
    async def delete_automation(automation_id: str) -> None:
        try:
            store.delete(automation_id)
        except AutomationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/{automation_id}/deliveries", response_model=list[DeliveryLogEntry])
    async def deliveries(automation_id: str) -> list[DeliveryLogEntry]:
        if store.get(automation_id) is None:
            raise HTTPException(status_code=404, detail=f"no automation with id {automation_id!r}")
        return [_to_log_entry(row) for row in outbox.list_for_automation(automation_id)]

    @router.post("/{automation_id}/test_fire", response_model=DeliveryLogEntry)
    async def test_fire(automation_id: str, body: TestFireRequest) -> DeliveryLogEntry:
        try:
            row = await dispatcher.test_fire(automation_id, body.data)
        except ActionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _to_log_entry(row)

    return router


__all__ = ["build_automations_router"]
