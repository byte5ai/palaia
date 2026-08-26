"""``/api/messenger`` REST mirror of the messenger (SPEC-403 deliverable
#6), for SPEC-405's team-observability screen and any other non-MCP reader.

**Reading is read-only, on purpose.** Checking, acking and threading *as a
session* all happen over MCP, from the session itself, holding its own
SPEC-402 session secret. Nothing here can read an inbox *as* somebody — no
route lets it, which is the whole point of the secret (see
:mod:`palaia_hub.messenger.service`'s docstring).

**Bodies.** The three listing routes (the flows feed, one sender's outbox,
one thread) return :class:`~palaia_hub.messenger.models.EnvelopeMetadata` —
the envelope with its body withheld — because a flows feed is a diagram of
who talked to whom, not a transcript. Exactly one *listing* route returns a
body: ``GET /api/messenger/envelopes/{id}``, the SPEC's "bodies only for the
owner via the admin surface". ``/api/*`` *is* that admin surface — everything
under it sits behind :mod:`palaia_hub.admin_session`'s sign-in gate wherever
the hub's mode requires one (MASTERPLAN §5.5), the same gate that already
protects note titles on ``/api/events`` and every vault read on
``/api/vaults``.

**Two owner controls live here** (SPEC-405 deliverable #2) — the other two
thirds of trust rule #7 (MASTERPLAN §5.4): "the human can read along, join
in, or shut a conversation down". Reading along is every ``GET`` above;
these two ``POST`` routes are "join in" and "shut down":

* ``POST /send`` — compose and send *as the owner*
  (:meth:`~palaia_hub.messenger.service.MessengerService.send_as_owner`;
  the sender always reads :data:`~palaia_hub.messenger.models.OWNER_HANDLE`).
  No session secret is asked for or accepted here — the admin session gate
  already proved who is calling, more strongly than a secret would.
* ``POST /threads/{envelope_id}/end`` — end a conversation
  (:meth:`~palaia_hub.messenger.service.MessengerService.end_conversation`):
  expires the thread's still-undelivered envelopes and fires
  ``message.expired`` for each.

Both are dashboard-only by the SPEC-304 rule this SPEC inherits: neither is
exposed as an MCP tool, and the session-monitor MCP App
(:mod:`palaia_hub.gateway.apps.team_app`) deep-links to the dashboard for
them instead of calling either itself.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .messenger.models import (
    MAX_BODY_BYTES,
    MAX_SUBJECT_CHARS,
    MAX_TTL_SECONDS,
    DeliveryState,
    EndConversationResult,
    EnvelopeDetailResult,
    EnvelopeNotFoundError,
    FlowsResult,
    MessageType,
    MessengerError,
    SendResult,
    ThreadMetadataResult,
    Urgency,
)
from .messenger.service import MessengerService
from .messenger.store import DEFAULT_FLOW_LIMIT


class SendAsOwnerRequest(BaseModel):
    """``POST /api/messenger/send``'s body — the owner compose form's exact
    schema (SPEC-405 deliverable #2: "the form IS the schema"). Every field
    here is the same one :mod:`palaia_hub.gateway.messenger_tools`'s
    ``messenger_send`` tool takes, minus ``handle``/``session_secret`` (the
    owner has neither — see this module's docstring)."""

    model_config = ConfigDict(extra="forbid")

    type: MessageType = "inform"
    to: str
    subject: str = Field(max_length=MAX_SUBJECT_CHARS)
    body: str = Field(default="", max_length=MAX_BODY_BYTES)
    urgency: Urgency = "normal"
    expects_reply: bool = False
    refs: list[str] | None = None
    reply_to: str | None = None
    ttl_seconds: float | None = Field(default=None, gt=0, le=MAX_TTL_SECONDS)


def build_messenger_router(service: MessengerService) -> APIRouter:
    router = APIRouter(prefix="/api/messenger", tags=["messenger"])

    @router.get("/", response_model=FlowsResult)
    async def list_flows(
        handle: str | None = None,
        type: MessageType | None = None,
        state: DeliveryState | None = None,
        limit: int = DEFAULT_FLOW_LIMIT,
    ) -> FlowsResult:
        """Recent message flows, newest first — metadata only.

        ``handle`` matches *either* side of a flow (sender or recipient), so
        one query answers "everything this session is involved in" rather
        than needing two.
        """
        return await service.flows(
            handle=handle, message_type=type, state=state, limit=limit
        )

    @router.get("/outbox/{handle}", response_model=FlowsResult)
    async def read_outbox(handle: str) -> FlowsResult:
        """One sender's outbox — metadata only (SPEC-403 deliverable #2).

        Distinct from ``GET /`` with ``handle=``, which matches either side
        of a flow: this is the sent side alone, with each copy's delivery
        state, so "did anyone actually pick up my broadcast" is one request.
        """
        return await service.outbox(handle)

    @router.get("/threads/{envelope_id}", response_model=ThreadMetadataResult)
    async def read_thread(envelope_id: str) -> ThreadMetadataResult:
        """One envelope's whole reply chain — metadata only."""
        try:
            return await service.thread_metadata(envelope_id)
        except EnvelopeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MessengerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/envelopes/{envelope_id}", response_model=EnvelopeDetailResult)
    async def read_envelope(envelope_id: str) -> EnvelopeDetailResult:
        """One envelope **with** its body — the owner's read (see the module
        docstring for why this route, and only this route, carries one)."""
        try:
            return await service.envelope_detail(envelope_id)
        except EnvelopeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MessengerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/send", response_model=SendResult)
    async def send_as_owner(body: SendAsOwnerRequest) -> SendResult:
        """Compose and send as the owner (SPEC-405 deliverable #2) — the
        dashboard's compose form's exact POST. See the module docstring for
        why no session secret appears here."""
        try:
            return await service.send_as_owner(
                message_type=body.type,
                to=body.to,
                subject=body.subject,
                body=body.body,
                urgency=body.urgency,
                expects_reply=body.expects_reply,
                refs=body.refs,
                reply_to=body.reply_to,
                ttl_seconds=body.ttl_seconds,
            )
        except EnvelopeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MessengerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/threads/{envelope_id}/end", response_model=EndConversationResult)
    async def end_conversation(envelope_id: str) -> EndConversationResult:
        """End a conversation (SPEC-405 deliverable #2): expire every
        still-undelivered envelope in ``envelope_id``'s whole thread."""
        try:
            return await service.end_conversation(envelope_id)
        except EnvelopeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MessengerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router


__all__ = ["SendAsOwnerRequest", "build_messenger_router"]
