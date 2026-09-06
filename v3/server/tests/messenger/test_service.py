"""``MessengerService`` — authorization, addressing, ref validation and the
``message.*`` events (SPEC-403 deliverables #3–#5).

The heavyweight assertion in this module is
``test_no_event_ever_carries_a_body``: the SPEC's contract test, written
against the *whole* event stream rather than one event, so a future fourth
event cannot quietly start leaking bodies onto the bus.
"""

from __future__ import annotations

from typing import Any

import pytest

from palaia_hub.directory.service import DirectoryService
from palaia_hub.messenger.models import (
    MAX_BROADCAST_RECIPIENTS,
    BroadcastError,
    EnvelopeNotFoundError,
    InvalidEnvelopeError,
    NotYourEnvelopeError,
    SessionAuthError,
    StaleRecipientError,
    UnknownRecipientError,
    UnresolvableRefError,
)
from palaia_hub.messenger.service import MessengerService, envelope_summary
from palaia_hub.messenger.store import MessengerStore

from .conftest import Clock, StubRefValidator

pytestmark = pytest.mark.anyio


async def _register(
    directory: DirectoryService, *, scope: str = "", capabilities: list[str] | None = None
) -> tuple[str, str]:
    result = await directory.register(scope=scope, capabilities=capabilities or [], ttl_seconds=60)
    return result.session.handle, result.session_secret


# -- authentication: the session secret is the inbox fence --------------------


async def test_send_requires_the_senders_own_session_secret(
    service: MessengerService, directory: DirectoryService
) -> None:
    a_handle, _ = await _register(directory)
    b_handle, b_secret = await _register(directory)
    with pytest.raises(SessionAuthError):
        await service.send(
            sender=a_handle,
            session_secret=b_secret,
            message_type="inform",
            to=b_handle,
            subject="signed by somebody else",
        )


async def test_session_a_cannot_check_session_bs_inbox(
    service: MessengerService, directory: DirectoryService
) -> None:
    """SPEC-403 acceptance: "session A cannot messenger_check session B's
    inbox (secret test)" — A's own secret does not open B's mailbox, and
    holding a scope changes nothing about that."""
    a_handle, a_secret = await _register(directory)
    b_handle, b_secret = await _register(directory)
    await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="request",
        to=b_handle,
        subject="for B only",
        body="B's eyes",
    )
    with pytest.raises(SessionAuthError):
        await service.check(b_handle, a_secret)
    # ... and B, with B's own secret, gets it.
    received = await service.check(b_handle, b_secret)
    assert [envelope.subject for envelope in received.envelopes] == ["for B only"]


async def test_an_unregistered_handle_cannot_check_anything(
    service: MessengerService,
) -> None:
    with pytest.raises(SessionAuthError):
        await service.check("never-registered", "whatever")


async def test_ack_of_another_sessions_envelope_is_refused(
    service: MessengerService, directory: DirectoryService
) -> None:
    a_handle, a_secret = await _register(directory)
    b_handle, b_secret = await _register(directory)
    c_handle, c_secret = await _register(directory)
    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="request",
        to=b_handle,
        subject="s",
    )
    envelope_id = sent.envelopes[0].id
    with pytest.raises(EnvelopeNotFoundError):
        await service.ack(c_handle, c_secret, envelope_id)
    acked = await service.ack(b_handle, b_secret, envelope_id)
    assert acked.state == "acked"


async def test_thread_of_a_conversation_you_are_not_in_is_refused(
    service: MessengerService, directory: DirectoryService
) -> None:
    a_handle, a_secret = await _register(directory)
    b_handle, _ = await _register(directory)
    c_handle, c_secret = await _register(directory)
    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="request",
        to=b_handle,
        subject="s",
    )
    with pytest.raises(NotYourEnvelopeError):
        await service.thread(c_handle, c_secret, sent.envelopes[0].id)


async def test_you_cannot_reply_to_a_stranger_s_envelope(
    service: MessengerService, directory: DirectoryService
) -> None:
    a_handle, a_secret = await _register(directory)
    b_handle, _ = await _register(directory)
    c_handle, c_secret = await _register(directory)
    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="question",
        to=b_handle,
        subject="s",
    )
    with pytest.raises(NotYourEnvelopeError):
        await service.send(
            sender=c_handle,
            session_secret=c_secret,
            message_type="inform",
            to=a_handle,
            subject="butting in",
            reply_to=sent.envelopes[0].id,
        )


# -- request -> reply, threaded -----------------------------------------------


async def test_request_then_reply_threads_through_reply_to(
    service: MessengerService, directory: DirectoryService
) -> None:
    a_handle, a_secret = await _register(directory, scope="reviewing billing")
    b_handle, b_secret = await _register(directory, scope="refactoring billing")

    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="request",
        to=b_handle,
        subject="please rename the invoice model",
        body="it is called Bill everywhere else",
        expects_reply=True,
        urgency="high",
    )
    request_id = sent.envelopes[0].id

    inbox = await service.check(b_handle, b_secret)
    assert [envelope.id for envelope in inbox.envelopes] == [request_id]
    assert inbox.envelopes[0].expects_reply is True

    reply = await service.send(
        sender=b_handle,
        session_secret=b_secret,
        message_type="inform",
        to=a_handle,
        subject="renamed",
        body="done in 3 files",
        reply_to=request_id,
    )
    assert reply.envelopes[0].reply_to == request_id

    back = await service.check(a_handle, a_secret)
    assert [envelope.subject for envelope in back.envelopes] == ["renamed"]

    thread = await service.thread(a_handle, a_secret, request_id)
    assert [envelope.id for envelope in thread.envelopes] == [
        request_id,
        reply.envelopes[0].id,
    ]


# -- recipient resolution -----------------------------------------------------


async def test_unknown_recipient_is_refused_in_plain_language(
    service: MessengerService, directory: DirectoryService
) -> None:
    a_handle, a_secret = await _register(directory)
    with pytest.raises(UnknownRecipientError) as excinfo:
        await service.send(
            sender=a_handle,
            session_secret=a_secret,
            message_type="inform",
            to="not-a-handle",
            subject="s",
        )
    message = str(excinfo.value)
    assert "directory_list" in message or "directory_query" in message


async def test_stale_recipient_is_refused(
    service: MessengerService, directory: DirectoryService, clock: Clock
) -> None:
    a_handle, a_secret = await _register(directory)
    b_handle, _ = await _register(directory)
    clock.advance(61)  # past b's 60s directory TTL
    with pytest.raises(StaleRecipientError) as excinfo:
        await service.send(
            sender=a_handle,
            session_secret=a_secret,
            message_type="inform",
            to=b_handle,
            subject="s",
        )
    assert "stale" in str(excinfo.value)


async def test_empty_recipient_is_refused(
    service: MessengerService, directory: DirectoryService
) -> None:
    a_handle, a_secret = await _register(directory)
    with pytest.raises(InvalidEnvelopeError):
        await service.send(
            sender=a_handle,
            session_secret=a_secret,
            message_type="inform",
            to="  ",
            subject="s",
        )


# -- refs ---------------------------------------------------------------------


async def test_a_ref_that_resolves_nowhere_is_refused(
    service: MessengerService, directory: DirectoryService
) -> None:
    """SPEC-403 acceptance: "a refs entry that resolves nowhere is refused"."""
    a_handle, a_secret = await _register(directory)
    b_handle, _ = await _register(directory)
    with pytest.raises(UnresolvableRefError) as excinfo:
        await service.send(
            sender=a_handle,
            session_secret=a_secret,
            message_type="inform",
            to=b_handle,
            subject="s",
            refs=["memory://projects/does-not-exist"],
        )
    assert "memory://projects/does-not-exist" in str(excinfo.value)


async def test_a_ref_that_resolves_is_carried(
    service: MessengerService, directory: DirectoryService
) -> None:
    a_handle, a_secret = await _register(directory)
    b_handle, _ = await _register(directory)
    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="inform",
        to=b_handle,
        subject="s",
        refs=["memory://projects/api-gateway"],
    )
    assert sent.envelopes[0].refs == ["memory://projects/api-gateway"]


async def test_a_ref_in_a_vault_the_sender_cannot_read_is_refused(
    store: MessengerStore, directory: DirectoryService
) -> None:
    """ "validated to resolve in a vault the sender can read" — a note that
    exists in a vault outside the caller's scopes is as unusable as one that
    does not exist, and the error must not become an oracle for it."""
    service = MessengerService(
        store,
        directory,
        ref_validator=StubRefValidator({"private": {"memory://secrets/keys"}}),
    )
    a_handle, a_secret = await _register(directory)
    b_handle, _ = await _register(directory)
    with pytest.raises(UnresolvableRefError):
        await service.send(
            sender=a_handle,
            session_secret=a_secret,
            message_type="inform",
            to=b_handle,
            subject="s",
            refs=["memory://secrets/keys"],
            readable_vaults=frozenset({"work"}),
        )
    # The same ref, with that vault readable, goes through.
    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="inform",
        to=b_handle,
        subject="s",
        refs=["memory://secrets/keys"],
        readable_vaults=frozenset({"private"}),
    )
    assert sent.envelopes[0].refs == ["memory://secrets/keys"]


async def test_a_hub_with_no_ref_validator_refuses_refs_rather_than_guessing(
    store: MessengerStore, directory: DirectoryService
) -> None:
    service = MessengerService(store, directory, ref_validator=None)
    a_handle, a_secret = await _register(directory)
    b_handle, _ = await _register(directory)
    with pytest.raises(UnresolvableRefError):
        await service.send(
            sender=a_handle,
            session_secret=a_secret,
            message_type="inform",
            to=b_handle,
            subject="s",
            refs=["memory://anything"],
        )
    # A message with no refs still works on such a hub.
    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="inform",
        to=b_handle,
        subject="s",
    )
    assert sent.envelopes[0].refs == []


# -- broadcast ----------------------------------------------------------------


async def test_broadcast_delivers_to_every_scope_match(
    service: MessengerService, directory: DirectoryService
) -> None:
    a_handle, a_secret = await _register(directory, scope="reviewing billing")
    matches = [
        await _register(directory, scope="refactoring the billing service") for _ in range(3)
    ]
    await _register(directory, scope="writing docs")

    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="broadcast",
        to="billing service",
        subject="freeze",
    )
    assert sorted(sent.recipients) == sorted(handle for handle, _ in matches)
    assert sent.broadcast_query == "billing service"
    for handle, secret in matches:
        received = await service.check(handle, secret)
        assert [envelope.subject for envelope in received.envelopes] == ["freeze"]


async def test_broadcast_by_capability_and_by_star(
    service: MessengerService, directory: DirectoryService
) -> None:
    a_handle, a_secret = await _register(directory)
    reviewer, _ = await _register(directory, capabilities=["review"])
    writer, _ = await _register(directory, capabilities=["write"])

    by_capability = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="broadcast",
        to="capability:review",
        subject="s",
    )
    assert by_capability.recipients == [reviewer]

    everyone = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="broadcast",
        to="*",
        subject="s",
    )
    assert sorted(everyone.recipients) == sorted([reviewer, writer])
    assert a_handle not in everyone.recipients


async def test_broadcast_caps_at_twenty_recipients_and_sends_nothing_over_it(
    service: MessengerService, directory: DirectoryService
) -> None:
    """SPEC-403 acceptance: "caps at 20". Over the cap is a loud error with
    nothing delivered — a broadcast that silently reached half its audience
    is worse than none."""
    a_handle, a_secret = await _register(directory, scope="sender")
    peers = [
        await _register(directory, scope="team alpha") for _ in range(MAX_BROADCAST_RECIPIENTS + 1)
    ]
    with pytest.raises(BroadcastError) as excinfo:
        await service.send(
            sender=a_handle,
            session_secret=a_secret,
            message_type="broadcast",
            to="team alpha",
            subject="s",
        )
    message = str(excinfo.value)
    assert str(MAX_BROADCAST_RECIPIENTS + 1) in message
    assert str(MAX_BROADCAST_RECIPIENTS) in message
    for handle, secret in peers:
        assert await service.check(handle, secret) == await service.check(handle, secret)
        assert (await service.check(handle, secret)).envelopes == []


async def test_broadcast_at_exactly_twenty_is_delivered(
    service: MessengerService, directory: DirectoryService
) -> None:
    a_handle, a_secret = await _register(directory, scope="sender")
    peers = [await _register(directory, scope="team beta") for _ in range(MAX_BROADCAST_RECIPIENTS)]
    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="broadcast",
        to="team beta",
        subject="s",
    )
    assert len(sent.recipients) == MAX_BROADCAST_RECIPIENTS
    assert sorted(sent.recipients) == sorted(handle for handle, _ in peers)


async def test_broadcast_matching_nobody_is_refused(
    service: MessengerService, directory: DirectoryService
) -> None:
    a_handle, a_secret = await _register(directory, scope="alone")
    with pytest.raises(BroadcastError):
        await service.send(
            sender=a_handle,
            session_secret=a_secret,
            message_type="broadcast",
            to="nobody works on this",
            subject="s",
        )


async def test_broadcast_skips_stale_sessions(
    service: MessengerService, directory: DirectoryService, clock: Clock
) -> None:
    a_handle, a_secret = await _register(directory, scope="team gamma")
    live_handle, live_secret = await _register(directory, scope="team gamma")
    stale_handle, _ = await _register(directory, scope="team gamma")
    clock.advance(61)
    # `live` heartbeats; `stale` does not.
    await directory.heartbeat(live_handle, live_secret)
    await directory.heartbeat(a_handle, a_secret)

    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="broadcast",
        to="team gamma",
        subject="s",
    )
    assert sent.recipients == [live_handle]
    assert stale_handle not in sent.recipients


async def test_a_broadcast_cannot_be_a_reply(
    service: MessengerService, directory: DirectoryService
) -> None:
    a_handle, a_secret = await _register(directory, scope="x")
    b_handle, _ = await _register(directory, scope="x")
    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="question",
        to=b_handle,
        subject="s",
    )
    with pytest.raises(InvalidEnvelopeError):
        await service.send(
            sender=a_handle,
            session_secret=a_secret,
            message_type="broadcast",
            to="*",
            subject="s",
            reply_to=sent.envelopes[0].id,
        )


# -- events -------------------------------------------------------------------


async def test_message_sent_fires_per_envelope(
    service: MessengerService,
    directory: DirectoryService,
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    a_handle, a_secret = await _register(directory, scope="x")
    peers = [await _register(directory, scope="x") for _ in range(2)]
    await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="broadcast",
        to="x",
        subject="s",
    )
    sent = [data for name, data in events if name == "message.sent"]
    assert len(sent) == 2
    assert sorted(item["recipient"] for item in sent) == sorted(h for h, _ in peers)


async def test_message_received_fires_on_the_delivery_check(
    service: MessengerService,
    directory: DirectoryService,
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    a_handle, a_secret = await _register(directory)
    b_handle, b_secret = await _register(directory)
    await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="request",
        to=b_handle,
        subject="subject line",
        body="the body",
    )
    assert [name for name, _ in events if name == "message.received"] == []
    await service.check(b_handle, b_secret)
    received = [data for name, data in events if name == "message.received"]
    assert len(received) == 1
    assert received[0]["subject"] == "subject line"
    assert received[0]["recipient"] == b_handle
    assert received[0]["state"] == "delivered"


async def test_message_received_fires_once_not_on_every_check(
    service: MessengerService,
    directory: DirectoryService,
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    a_handle, a_secret = await _register(directory)
    b_handle, b_secret = await _register(directory)
    await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="request",
        to=b_handle,
        subject="s",
    )
    await service.check(b_handle, b_secret)
    await service.check(b_handle, b_secret)
    assert len([1 for name, _ in events if name == "message.received"]) == 1


async def test_check_redelivers_an_unacked_envelope_and_says_so(
    service: MessengerService,
    directory: DirectoryService,
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    """Issue #340: the recipient's tool response can be lost after the hub
    marked the envelope delivered. `check` is at-least-once — the envelope
    comes back, flagged as a repeat, until the recipient acks it."""
    a_handle, a_secret = await _register(directory)
    b_handle, b_secret = await _register(directory)
    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="handoff",
        to=b_handle,
        subject="take over the deploy",
        body="the runbook is in memory://work/deploy",
    )
    envelope_id = sent.envelopes[0].id

    first = await service.check(b_handle, b_secret)
    assert [e.id for e in first.envelopes] == [envelope_id]
    assert first.redelivered == []

    # The response was lost; the recipient asks again.
    second = await service.check(b_handle, b_secret)
    assert [e.id for e in second.envelopes] == [envelope_id]
    assert second.envelopes[0].body == "the runbook is in memory://work/deploy"
    assert second.redelivered == [envelope_id]
    # Announced once, not on every re-read.
    assert len([1 for name, _ in events if name == "message.received"]) == 1

    await service.ack(b_handle, b_secret, envelope_id)
    third = await service.check(b_handle, b_secret)
    assert third.envelopes == [] and third.redelivered == []


async def test_message_expired_fires_for_an_unchecked_envelope(
    service: MessengerService,
    directory: DirectoryService,
    clock: Clock,
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    """SPEC-403 acceptance: "an unchecked envelope past expires_at is gone
    and message.expired fired (clock-injectable)"."""
    a_handle, a_secret = await _register(directory)
    b_handle, b_secret = await _register(directory)
    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="request",
        to=b_handle,
        subject="s",
        ttl_seconds=120,
    )
    envelope_id = sent.envelopes[0].id
    events.clear()

    clock.advance(121)
    expired = await service.sweep()
    assert [metadata.id for metadata in expired] == [envelope_id]
    expired_events = [data for name, data in events if name == "message.expired"]
    assert [data["id"] for data in expired_events] == [envelope_id]

    # Gone, not merely flagged — and never delivered.
    await directory.heartbeat(b_handle, b_secret)
    assert (await service.check(b_handle, b_secret)).envelopes == []
    assert [name for name, _ in events if name == "message.received"] == []


async def test_no_event_ever_carries_a_body(
    service: MessengerService,
    directory: DirectoryService,
    clock: Clock,
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    """The SPEC's contract test, widened: **no** ``message.*`` event carries
    a body, ever — not ``sent``, not ``received``, not ``expired``. Asserted
    over the whole stream rather than one event name, so a future event
    cannot quietly start leaking one."""
    secret_body = "the-nuclear-launch-codes-are-1234"
    a_handle, a_secret = await _register(directory)
    b_handle, b_secret = await _register(directory)
    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="request",
        to=b_handle,
        subject="s",
        body=secret_body,
        ttl_seconds=120,
    )
    await service.check(b_handle, b_secret)
    await service.ack(b_handle, b_secret, sent.envelopes[0].id)
    clock.advance(121)
    await service.sweep()

    names = {name for name, _ in events}
    assert {"message.sent", "message.received", "message.expired"} <= names
    for name, data in events:
        assert "body" not in data, f"{name} carries a body field"
        assert secret_body not in repr(data), f"{name} leaked the body"
        # The honest substitute is there instead.
        if name.startswith("message."):
            assert data["body_bytes"] == len(secret_body)


# -- outbox / flows / compact rendering ---------------------------------------


async def test_outbox_is_metadata_only_and_shows_delivery_state(
    service: MessengerService, directory: DirectoryService
) -> None:
    """Deliverable #2's "sender outbox view": what I sent, how far it got —
    one row per recipient copy, no bodies."""
    a_handle, a_secret = await _register(directory, scope="team")
    b_handle, b_secret = await _register(directory, scope="team")
    c_handle, _ = await _register(directory, scope="team")
    await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="broadcast",
        to="team",
        subject="s",
        body="hello",
    )
    await service.check(b_handle, b_secret)

    outbox = await service.outbox(a_handle)

    assert {flow.recipient for flow in outbox.flows} == {b_handle, c_handle}
    states = {flow.recipient: flow.state for flow in outbox.flows}
    assert states[b_handle] == "delivered"
    assert states[c_handle] == "pending"
    for flow in outbox.flows:
        assert "body" not in flow.model_dump()
    # B sent nothing, so B's outbox is empty.
    assert (await service.outbox(b_handle)).flows == []


async def test_envelope_detail_is_the_one_place_a_body_appears(
    service: MessengerService, directory: DirectoryService
) -> None:
    a_handle, a_secret = await _register(directory)
    b_handle, _ = await _register(directory)
    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="inform",
        to=b_handle,
        subject="s",
        body="hello",
    )
    detail = await service.envelope_detail(sent.envelopes[0].id)
    assert detail.item.envelope.body == "hello"
    flows = await service.flows()
    assert "body" not in flows.flows[0].model_dump()


async def test_envelope_summary_is_compact_and_names_type_urgency_refs(
    service: MessengerService, directory: DirectoryService
) -> None:
    a_handle, a_secret = await _register(directory)
    b_handle, _ = await _register(directory)
    sent = await service.send(
        sender=a_handle,
        session_secret=a_secret,
        message_type="handoff",
        to=b_handle,
        subject="over to you",
        body="a very long body that should not appear in a summary line",
        urgency="high",
        expects_reply=True,
        refs=["memory://projects/api-gateway"],
    )
    summary = envelope_summary(sent.envelopes[0])
    assert "handoff/high" in summary
    assert "over to you" in summary
    assert "memory://projects/api-gateway" in summary
    assert "reply expected" in summary
    assert "very long body" not in summary
