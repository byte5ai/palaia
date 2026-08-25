"""``/api/messenger`` read-only mirror of the messenger (SPEC-403
deliverable #6), for SPEC-405's team-observability screen and any other
non-MCP reader.

**Read-only, on purpose.** Sending, checking, acking and threading all
happen over MCP, from the session itself, holding its own SPEC-402 session
secret. Nothing here can send a message or read an inbox *as* somebody —
there is no route that would let it, which is the whole point of the secret
(see :mod:`palaia_hub.messenger.service`'s docstring).

**Bodies.** The three listing routes (the flows feed, one sender's outbox,
one thread) return :class:`~palaia_hub.messenger.models.EnvelopeMetadata` —
the envelope with its body withheld — because a flows feed is a diagram of
who talked to whom, not a transcript. Exactly one route returns a body: ``GET
/api/messenger/envelopes/{id}``, the SPEC's "bodies only for the owner via
the admin surface". ``/api/*`` *is* that admin surface — everything under it
sits behind :mod:`palaia_hub.admin_session`'s sign-in gate wherever the hub's
mode requires one (MASTERPLAN §5.5), the same gate that already protects
note titles on ``/api/events`` and every vault read on ``/api/vaults``.
Trust rule #7 (MASTERPLAN §5.4): "the human can read along, join in, or shut
a conversation down" — reading along is this route.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .messenger.models import (
    DeliveryState,
    EnvelopeDetailResult,
    EnvelopeNotFoundError,
    FlowsResult,
    MessageType,
    MessengerError,
    ThreadMetadataResult,
)
from .messenger.service import MessengerService
from .messenger.store import DEFAULT_FLOW_LIMIT


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

    return router


__all__ = ["build_messenger_router"]
