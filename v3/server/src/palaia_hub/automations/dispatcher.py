"""The automation dispatcher: matches events, evaluates conditions, renders
templates, and executes one of the three action kinds (SPEC-307).

Same split as :class:`palaia_hub.hooks.delivery.HookDispatcher`:
:meth:`on_event` is the cheap, synchronous bus subscriber that only ever
enqueues a durable row (:mod:`.outbox`); :meth:`deliver_due` is the worker
loop that actually performs the action. An event is never lost in flight —
by the time ``on_event`` returns, every delivery it owes exists as a
committed SQLite row.

:meth:`test_fire` is deliverable #4's test-fire button: it builds one
synthetic :class:`~palaia_hub.events.schema.Envelope`, runs it through
*exactly* the same match/condition/render/execute code every real event
goes through — this is what "runs the real pipeline" means — but is scoped
to one automation (a test click must not also fire every other automation
subscribed to the same trigger event) and resolves synchronously rather
than going through the pending queue, so the caller gets an answer in one
request.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import Any

from ..events.schema import Envelope
from ..gateway.vault_protocol import VaultServiceError
from ..gateway.wiring import EngineVaultService
from ..notifications.store import NotificationStore
from ..stash.service import StashService
from ..vault import VaultNotFoundError, VaultRegistry
from . import conditions
from .models import (
    Action,
    AutomationRecord,
    MemoryWriteAction,
    NotificationAction,
    StashSetAction,
)
from .outbox import AutomationOutbox, DeliveryRow
from .store import LOOP_GUARD_PREFIX, AutomationStore
from .templates import render

logger = logging.getLogger("palaia_hub.automations.dispatcher")

#: Deliverable #4 acceptance: "delivery failures retry per SPEC-201's
#: policy" — reusing the exact same constants and backoff formula as
#: :mod:`palaia_hub.hooks.delivery`.
DEFAULT_MAX_ATTEMPTS = 5
_BASE_BACKOFF_SECONDS = 2.0
_MAX_BACKOFF_SECONDS = 300.0

#: ``(event_name, data)`` — the same narrow shape
#: :data:`palaia_hub.events.schema.HubEventHook` uses, so wiring this into
#: the public bus (``palaia_hub.events.bus.publish_from_hook``) is a
#: one-line call in ``palaia_hub.app``, same as the curator/index/stash.
Emit = Callable[[str, dict[str, Any]], None]


class ActionError(RuntimeError):
    """A rendered action could not be executed. Always a plain-language
    message — never a bare exception repr."""


def _backoff_seconds(attempt: int) -> float:
    delay = _BASE_BACKOFF_SECONDS * float(2 ** (attempt - 1))
    return min(delay, _MAX_BACKOFF_SECONDS)


def _matches_trigger(trigger_event: str, envelope: Envelope) -> bool:
    if envelope.event.startswith(LOOP_GUARD_PREFIX):
        # Dispatcher-level loop guard (belt-and-suspenders with the
        # create-time refusal in .store): even a "*" trigger never fires on
        # an automation.* event.
        return False
    return trigger_event == "*" or trigger_event == envelope.event


def render_action(action: Action, envelope: Envelope) -> dict[str, Any]:
    """Render ``action``'s templates against ``envelope`` into a plain dict
    the dispatcher can persist and later execute without needing the
    original envelope again."""
    if isinstance(action, MemoryWriteAction):
        return {
            "vault": action.vault,
            "what_it_concerns": render(action.what_it_concerns_template, envelope),
            "why_keep": render(action.why_keep_template, envelope),
            "content": render(action.content_template, envelope),
            "source": render(action.source_template, envelope) if action.source_template else None,
        }
    if isinstance(action, StashSetAction):
        return {
            "namespace": action.namespace,
            "key": render(action.key_template, envelope),
            "value": render(action.value_template, envelope),
        }
    if isinstance(action, NotificationAction):
        return {
            "title": render(action.title_template, envelope),
            "body": render(action.body_template, envelope),
        }
    raise ActionError(f"unknown action kind {action.kind!r}")  # pragma: no cover - closed union


class AutomationDispatcher:
    """Turns matching events into durable rows, then executes them."""

    def __init__(
        self,
        store: AutomationStore,
        outbox: AutomationOutbox,
        *,
        vault_registry: VaultRegistry | None = None,
        stash_service: StashService | None = None,
        notification_store: NotificationStore | None = None,
        emit: Emit | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._store = store
        self._outbox = outbox
        self._vault_registry = vault_registry
        self._stash_service = stash_service
        self._notification_store = notification_store
        self._emit = emit
        self._max_attempts = max_attempts

    # -------------------------------------------------------- event -> outbox

    def on_event(self, envelope: Envelope) -> None:
        """The in-process bus subscriber (see ``palaia_hub.app``)."""
        if envelope.event.startswith(LOOP_GUARD_PREFIX):
            return
        for automation in self._store.list_info():
            if not automation.enabled:
                continue
            if not _matches_trigger(automation.trigger_event, envelope):
                continue
            if not conditions.evaluate(automation.condition, envelope):
                continue
            try:
                rendered = render_action(automation.action, envelope)
            except Exception:  # noqa: BLE001 - a bad template must not break the publish
                logger.exception(
                    "automation %s failed to render its action for event %r",
                    automation.id,
                    envelope.event,
                )
                continue
            self._outbox.enqueue(
                automation_id=automation.id,
                event_id=envelope.id,
                event_name=envelope.event,
                action_kind=automation.action.kind,
                rendered_action=rendered,
            )

    # ------------------------------------------------------------- delivery

    async def deliver_due(self, *, limit: int = 20) -> int:
        rows = self._outbox.claim_due(limit=limit)
        for row in rows:
            await self._attempt(row)
        return len(rows)

    async def _attempt(self, row: DeliveryRow) -> None:
        automation = self._store.get(row.automation_id)
        if automation is None or not automation.enabled:
            self._outbox.mark_dead(row.id, error="automation was removed or disabled")
            self._emit_event("automation.failed", row, error="automation was removed or disabled")
            return
        attempt = row.attempts + 1
        try:
            await self._execute(row.action_kind, row.rendered_action)
        except (ActionError, VaultServiceError, VaultNotFoundError) as exc:
            self._fail(row, attempt, automation, error=str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - never let a delivery crash the worker
            self._fail(row, attempt, automation, error=f"unexpected error: {exc}")
            return
        self._outbox.mark_delivered(row.id)
        self._emit_event("automation.fired", row, automation=automation)

    def _fail(
        self, row: DeliveryRow, attempt: int, automation: AutomationRecord, *, error: str
    ) -> None:
        if attempt >= self._max_attempts:
            logger.warning(
                "automation %s delivery dead-lettered after %d attempt(s): %s",
                row.automation_id,
                attempt,
                error,
            )
            self._outbox.mark_dead(row.id, error=error)
            self._emit_event("automation.failed", row, automation=automation, error=error)
        else:
            logger.info(
                "automation %s delivery failed (attempt %d), retrying: %s",
                row.automation_id,
                attempt,
                error,
            )
            self._outbox.mark_retry(row.id, delay_seconds=_backoff_seconds(attempt), error=error)

    def _emit_event(
        self,
        event_name: str,
        row: DeliveryRow,
        *,
        automation: AutomationRecord | None = None,
        error: str | None = None,
    ) -> None:
        if self._emit is None:
            return
        data: dict[str, Any] = {
            "automation_id": row.automation_id,
            "name": automation.name if automation is not None else None,
            "action_kind": row.action_kind,
            "trigger_event": row.event_name,
        }
        if error is not None:
            data["error"] = error
        try:
            self._emit(event_name, data)
        except Exception:  # noqa: BLE001 - an event subscriber must not break delivery
            logger.exception("failed to emit %s for automation %s", event_name, row.automation_id)

    # ------------------------------------------------------------- execution

    async def _execute(self, action_kind: str, rendered: dict[str, Any]) -> None:
        if action_kind == "memory_write":
            await self._execute_memory_write(rendered)
        elif action_kind == "stash_set":
            await self._execute_stash_set(rendered)
        elif action_kind == "notification":
            self._execute_notification(rendered)
        else:  # pragma: no cover - closed union enforced at store level
            raise ActionError(f"unknown action kind {action_kind!r}")

    async def _execute_memory_write(self, rendered: dict[str, Any]) -> None:
        if self._vault_registry is None:
            raise ActionError(
                "this automation writes to a vault, but this hub has no vault "
                "registry configured — memory_write actions cannot run here."
            )
        try:
            engine = await self._vault_registry.get(rendered["vault"])
        except VaultNotFoundError as exc:
            raise ActionError(str(exc)) from exc
        service = EngineVaultService(engine)
        try:
            await service.capture(
                what_it_concerns=rendered["what_it_concerns"],
                why_keep=rendered["why_keep"],
                content=rendered["content"],
                source=rendered.get("source") or None,
            )
        except VaultServiceError as exc:
            raise ActionError(str(exc)) from exc

    async def _execute_stash_set(self, rendered: dict[str, Any]) -> None:
        if self._stash_service is None:
            raise ActionError(
                "this automation sets a stash entry, but this hub has no stash "
                "configured — stash_set actions cannot run here."
            )
        await self._stash_service.set(rendered["namespace"], rendered["key"], rendered["value"])

    def _execute_notification(self, rendered: dict[str, Any]) -> None:
        if self._notification_store is None:
            raise ActionError(
                "this automation posts a notification, but this hub has no "
                "notification center configured."
            )
        self._notification_store.create(
            title=rendered["title"], body=rendered.get("body", ""), source="automation"
        )

    # --------------------------------------------------------------- test-fire

    async def test_fire(
        self, automation_id: str, sample_data: dict[str, Any] | None = None
    ) -> DeliveryRow:
        """Deliverable #4: run one automation through the real pipeline with
        synthetic data, marked ``test: true`` in the resulting log entry."""
        automation = self._store.get(automation_id)
        if automation is None:
            raise ActionError(f"no automation with id {automation_id!r}.")
        envelope = Envelope(
            event=automation.trigger_event,
            data=dict(sample_data or {}),
            origin="automations_test",
            vault=(sample_data or {}).get("vault") if sample_data else None,
            id=f"test-{uuid.uuid4().hex}",
        )
        if not conditions.evaluate(automation.condition, envelope):
            return self._outbox.record_resolved(
                automation_id=automation.id,
                event_id=envelope.id,
                event_name=envelope.event,
                action_kind=automation.action.kind,
                rendered_action={},
                status="condition_not_matched",
                last_error="the sample data did not satisfy this automation's condition.",
                test=True,
            )
        rendered = render_action(automation.action, envelope)
        try:
            await self._execute(automation.action.kind, rendered)
        except (ActionError, VaultServiceError, VaultNotFoundError) as exc:
            return self._outbox.record_resolved(
                automation_id=automation.id,
                event_id=envelope.id,
                event_name=envelope.event,
                action_kind=automation.action.kind,
                rendered_action=rendered,
                status="dead",
                last_error=str(exc),
                test=True,
            )
        return self._outbox.record_resolved(
            automation_id=automation.id,
            event_id=envelope.id,
            event_name=envelope.event,
            action_kind=automation.action.kind,
            rendered_action=rendered,
            status="delivered",
            last_error="",
            test=True,
        )

    # --------------------------------------------------------------- lifecycle

    async def run_forever(self, *, poll_seconds: float = 2.0) -> None:
        """The background task ``palaia_hub.app`` starts in its lifespan."""
        while True:
            try:
                delivered_any = await self.deliver_due()
                if not delivered_any:
                    await asyncio.sleep(poll_seconds)
            except Exception:  # noqa: BLE001 - the worker must survive anything
                logger.exception("automation delivery loop failed")
                await asyncio.sleep(poll_seconds)


__all__ = ["DEFAULT_MAX_ATTEMPTS", "ActionError", "AutomationDispatcher", "render_action"]
