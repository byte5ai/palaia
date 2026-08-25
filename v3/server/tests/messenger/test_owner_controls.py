"""Owner controls: send-as-owner and end-a-conversation (SPEC-405
deliverable #2, MASTERPLAN §5.4 trust rule #7 — "the human can read along,
join in, or shut a conversation down"). "Reading along" is the existing
``/api/messenger`` mirror; "join in" is
:meth:`MessengerService.send_as_owner`; "shut down" is
:meth:`MessengerService.end_conversation`. Both are exercised here at the
service layer; :mod:`palaia_hub.messenger_api`'s own routes are covered in
``server/tests/test_messenger_api.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from palaia_hub.directory.service import DirectoryService
from palaia_hub.messenger.models import OWNER_HANDLE, EnvelopeNotFoundError
from palaia_hub.messenger.service import MessengerService

from .conftest import Clock

pytestmark = pytest.mark.anyio


async def _register(directory: DirectoryService, *, scope: str = "") -> tuple[str, str]:
    result = await directory.register(scope=scope, ttl_seconds=60)
    return result.session.handle, result.session_secret


# -- send_as_owner ------------------------------------------------------------


async def test_send_as_owner_is_delivered_with_the_owner_handle(
    service: MessengerService, directory: DirectoryService
) -> None:
    recipient, recipient_secret = await _register(directory)

    result = await service.send_as_owner(
        message_type="inform",
        to=recipient,
        subject="a note from the owner",
        body="reading along",
    )
    assert result.envelopes[0].from_ == OWNER_HANDLE

    inbox = await service.check(recipient, recipient_secret)
    assert [e.subject for e in inbox.envelopes] == ["a note from the owner"]
    assert inbox.envelopes[0].from_ == OWNER_HANDLE


async def test_send_as_owner_needs_no_session_secret(
    service: MessengerService, directory: DirectoryService
) -> None:
    """Unlike an ordinary session, the owner has no directory registration
    and no secret to present — and none is asked for."""
    recipient, _ = await _register(directory)
    # No `session_secret` keyword exists on this call at all; if it needed
    # one, this call would be a TypeError, not a runtime auth failure.
    result = await service.send_as_owner(
        message_type="inform", to=recipient, subject="hi"
    )
    assert result.recipients == [recipient]


async def test_send_as_owner_may_reply_to_a_thread_it_never_took_part_in(
    service: MessengerService, directory: DirectoryService
) -> None:
    """Trust rule #7's "join in": an ordinary session is fenced to threads
    it took part in (``test_you_cannot_reply_to_a_stranger_s_envelope`` in
    ``test_service.py``); the owner is not."""
    a_handle, a_secret = await _register(directory)
    b_handle, _ = await _register(directory)
    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="question",
        to=b_handle,
        subject="a question between a and b",
    )
    joined = await service.send_as_owner(
        message_type="inform",
        to=a_handle,
        subject="the owner is reading along",
        reply_to=sent.envelopes[0].id,
    )
    assert joined.envelopes[0].reply_to == sent.envelopes[0].id
    assert joined.envelopes[0].from_ == OWNER_HANDLE


async def test_send_as_owner_still_refuses_an_unknown_recipient(
    service: MessengerService,
) -> None:
    from palaia_hub.messenger.models import UnknownRecipientError

    with pytest.raises(UnknownRecipientError):
        await service.send_as_owner(message_type="inform", to="nobody", subject="hi")


# -- end_conversation ----------------------------------------------------------


async def test_end_conversation_expires_only_the_undelivered_copies(
    service: MessengerService,
    directory: DirectoryService,
    clock: Clock,
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    a_handle, a_secret = await _register(directory)
    b_handle, b_secret = await _register(directory)

    request = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="request",
        to=b_handle,
        subject="please do the thing",
        expects_reply=True,
    )
    request_id = request.envelopes[0].id

    # b checks (delivers) the request but never replies — that copy stays
    # `delivered`, never `pending`, so ending the conversation must leave it
    # standing.
    await service.check(b_handle, b_secret)

    # a sends a second, follow-up message in the same thread that b never
    # checks — this one stays `pending` and is what "undelivered" means.
    followup = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="inform",
        to=b_handle,
        subject="also, one more thing",
        reply_to=request_id,
    )
    followup_id = followup.envelopes[0].id
    events.clear()

    result = await service.end_conversation(request_id)

    assert result.root_id == request_id
    assert [e.id for e in result.expired] == [followup_id]
    expired_events = [data for name, data in events if name == "message.expired"]
    assert [data["id"] for data in expired_events] == [followup_id]

    # The delivered request is untouched: b can still re-read it via thread.
    thread = await service.thread(b_handle, b_secret, request_id)
    assert [e.id for e in thread.envelopes] == [request_id]

    # The undelivered follow-up is truly gone, not merely hidden.
    with pytest.raises(EnvelopeNotFoundError):
        await service.thread(a_handle, a_secret, followup_id)


async def test_end_conversation_on_an_unknown_envelope_is_refused(
    service: MessengerService,
) -> None:
    with pytest.raises(EnvelopeNotFoundError):
        await service.end_conversation("no-such-id")


async def test_end_conversation_needs_no_participant_at_all(
    service: MessengerService, directory: DirectoryService
) -> None:
    """The owner ends conversations it was never part of — that is the
    whole point of the control being dashboard-only rather than a
    participant action."""
    a_handle, a_secret = await _register(directory)
    b_handle, _ = await _register(directory)
    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="inform",
        to=b_handle,
        subject="a private matter",
    )
    result = await service.end_conversation(sent.envelopes[0].id)
    assert [e.id for e in result.expired] == [sent.envelopes[0].id]
