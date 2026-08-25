"""``MessengerStore`` — the envelope's storage invariants (SPEC-403
deliverables #1/#2): the caps, delivery state, the TTL sweep, threads and
the outbox view."""

from __future__ import annotations

import pytest

from palaia_hub.messenger.models import (
    DEFAULT_TTL_SECONDS,
    MAX_BODY_BYTES,
    MAX_SUBJECT_CHARS,
    MAX_TTL_SECONDS,
    BodyTooLargeError,
    EnvelopeNotFoundError,
    InvalidEnvelopeError,
    SubjectTooLongError,
)
from palaia_hub.messenger.store import MessengerStore

from .conftest import Clock


def _send(
    store: MessengerStore,
    *,
    sender: str = "a",
    to: str = "b",
    subject: str = "subject",
    body: str = "body",
    reply_to: str | None = None,
    ttl_seconds: float | None = None,
    recipients: list[str] | None = None,
):  # noqa: ANN202 - returns the store's own tuple
    return store.create(
        type="request",
        sender=sender,
        addressed_to=to,
        recipients=recipients or [to],
        subject=subject,
        body=body,
        reply_to=reply_to,
        ttl_seconds=ttl_seconds,
    )


# -- the envelope shape -------------------------------------------------------


def test_created_envelope_carries_the_fixed_shape(store: MessengerStore) -> None:
    items, _ = _send(store, subject="ship it", body="please review")
    envelope = items[0].envelope
    assert set(envelope.model_dump()) == {
        "id",
        "type",
        "from",
        "to",
        "subject",
        "urgency",
        "expects_reply",
        "body",
        "refs",
        "reply_to",
        "created_at",
        "expires_at",
    }
    assert envelope.model_dump()["from"] == "a"


def test_id_is_server_minted_and_unique(store: MessengerStore) -> None:
    first, _ = _send(store)
    second, _ = _send(store)
    assert first[0].envelope.id != second[0].envelope.id


def test_default_ttl_is_24h(store: MessengerStore, clock: Clock) -> None:
    items, _ = _send(store)
    envelope = items[0].envelope
    assert envelope.expires_at == pytest.approx(clock.now + DEFAULT_TTL_SECONDS)
    assert DEFAULT_TTL_SECONDS == 86_400.0


# -- the caps -----------------------------------------------------------------


def test_a_5000_byte_body_is_refused_with_the_write_it_to_memory_message(
    store: MessengerStore,
) -> None:
    with pytest.raises(BodyTooLargeError) as excinfo:
        _send(store, body="x" * 5000)
    message = str(excinfo.value)
    assert "5000" in message
    assert str(MAX_BODY_BYTES) in message
    assert "write it to memory and reference it" in message
    assert "refs" in message


def test_the_cap_is_utf8_bytes_not_characters(store: MessengerStore) -> None:
    """A body of 4-byte emoji hits the cap at a quarter of the characters —
    the cap is what a transport pays for, not what a screen shows."""
    just_over = "🙂" * ((MAX_BODY_BYTES // 4) + 1)
    assert len(just_over) < MAX_BODY_BYTES
    with pytest.raises(BodyTooLargeError):
        _send(store, body=just_over)


def test_a_body_exactly_at_the_cap_is_accepted(store: MessengerStore) -> None:
    items, _ = _send(store, body="x" * MAX_BODY_BYTES)
    assert items[0].envelope.body_bytes == MAX_BODY_BYTES


def test_subject_over_200_chars_is_refused(store: MessengerStore) -> None:
    with pytest.raises(SubjectTooLongError):
        _send(store, subject="s" * (MAX_SUBJECT_CHARS + 1))


def test_empty_subject_is_refused(store: MessengerStore) -> None:
    with pytest.raises(InvalidEnvelopeError):
        _send(store, subject="   ")


def test_ttl_over_seven_days_is_refused(store: MessengerStore) -> None:
    with pytest.raises(InvalidEnvelopeError) as excinfo:
        _send(store, ttl_seconds=MAX_TTL_SECONDS + 1)
    assert "7 days" in str(excinfo.value)


def test_ttl_at_seven_days_is_accepted(store: MessengerStore, clock: Clock) -> None:
    items, _ = _send(store, ttl_seconds=MAX_TTL_SECONDS)
    assert items[0].envelope.expires_at == pytest.approx(clock.now + MAX_TTL_SECONDS)


def test_a_ref_without_the_memory_scheme_is_refused(store: MessengerStore) -> None:
    with pytest.raises(InvalidEnvelopeError) as excinfo:
        store.create(
            type="inform",
            sender="a",
            addressed_to="b",
            recipients=["b"],
            subject="s",
            refs=["projects/api-gateway"],
        )
    assert "memory://" in str(excinfo.value)


# -- delivery state -----------------------------------------------------------


def test_check_returns_pending_and_marks_delivered(store: MessengerStore) -> None:
    _send(store, to="b")
    items, _ = store.check("b")
    assert [item.state for item in items] == ["delivered"]
    assert items[0].delivered_at is not None


def test_check_twice_returns_nothing_the_second_time(store: MessengerStore) -> None:
    _send(store, to="b")
    assert len(store.check("b")[0]) == 1
    assert store.check("b")[0] == []


def test_check_only_sees_its_own_inbox(store: MessengerStore) -> None:
    _send(store, sender="a", to="b")
    assert store.check("c")[0] == []
    assert len(store.check("b")[0]) == 1


def test_ack_closes_the_envelope_and_is_idempotent(store: MessengerStore) -> None:
    items, _ = _send(store, to="b")
    envelope_id = items[0].envelope.id
    first, _ = store.ack(envelope_id, "b")
    assert first.state == "acked"
    assert first.acked_at is not None
    second, _ = store.ack(envelope_id, "b")
    assert second.acked_at == first.acked_at


def test_ack_from_another_inbox_is_refused(store: MessengerStore) -> None:
    items, _ = _send(store, to="b")
    with pytest.raises(EnvelopeNotFoundError):
        store.ack(items[0].envelope.id, "c")


# -- broadcast fan-out --------------------------------------------------------


def test_broadcast_fans_out_one_envelope_per_recipient(store: MessengerStore) -> None:
    items, _ = store.create(
        type="broadcast",
        sender="a",
        addressed_to="billing",
        recipients=["b", "c", "d"],
        subject="heads up",
        body="deploying",
    )
    assert [item.recipient for item in items] == ["b", "c", "d"]
    # Individual envelopes: distinct ids, but each keeps the query it was
    # cast with in `to`.
    assert len({item.envelope.id for item in items}) == 3
    assert {item.envelope.to for item in items} == {"billing"}
    for handle in ("b", "c", "d"):
        assert len(store.check(handle)[0]) == 1


# -- TTL expiry ---------------------------------------------------------------


def test_an_unchecked_envelope_past_expires_at_is_gone(
    store: MessengerStore, clock: Clock
) -> None:
    items, _ = _send(store, to="b", ttl_seconds=60)
    envelope_id = items[0].envelope.id
    clock.advance(61)
    expired = store.sweep()
    assert [metadata.id for metadata in expired] == [envelope_id]
    assert store.check("b")[0] == []
    assert store.item(envelope_id)[0] is None


def test_expiry_metadata_never_carries_a_body(store: MessengerStore, clock: Clock) -> None:
    _send(store, to="b", body="secret plan", ttl_seconds=60)
    clock.advance(61)
    expired = store.sweep()
    assert expired
    dumped = expired[0].model_dump()
    assert "body" not in dumped
    assert "secret plan" not in repr(dumped)
    assert dumped["body_bytes"] == len("secret plan")


def test_expiry_is_reported_once_then_the_row_is_gone(
    store: MessengerStore, clock: Clock
) -> None:
    _send(store, to="b", ttl_seconds=60)
    clock.advance(61)
    assert len(store.sweep()) == 1
    assert store.sweep() == []


def test_an_envelope_before_its_expiry_survives(store: MessengerStore, clock: Clock) -> None:
    _send(store, to="b", ttl_seconds=60)
    clock.advance(59)
    assert store.sweep() == []
    assert len(store.check("b")[0]) == 1


def test_every_read_sweeps_so_expiry_needs_no_background_task(
    store: MessengerStore, clock: Clock
) -> None:
    _send(store, to="b", ttl_seconds=60)
    clock.advance(61)
    _, expired = store.check("b")
    assert len(expired) == 1


# -- threads ------------------------------------------------------------------


def test_thread_links_through_reply_to(store: MessengerStore) -> None:
    first, _ = _send(store, sender="a", to="b", subject="question")
    root_id = first[0].envelope.id
    second, _ = _send(store, sender="b", to="a", subject="answer", reply_to=root_id)
    reply_id = second[0].envelope.id

    from_root, _ = store.thread(root_id)
    from_reply, _ = store.thread(reply_id)
    assert [item.envelope.id for item in from_root] == [root_id, reply_id]
    assert [item.envelope.id for item in from_reply] == [root_id, reply_id]


def test_thread_of_an_unknown_id_is_refused(store: MessengerStore) -> None:
    with pytest.raises(EnvelopeNotFoundError):
        store.thread("nope")


def test_thread_survives_an_expired_ancestor(store: MessengerStore, clock: Clock) -> None:
    first, _ = _send(store, sender="a", to="b", ttl_seconds=60)
    root_id = first[0].envelope.id
    second, _ = _send(store, sender="b", to="a", reply_to=root_id, ttl_seconds=6000)
    reply_id = second[0].envelope.id
    clock.advance(61)
    items, expired = store.thread(reply_id)
    assert [metadata.id for metadata in expired] == [root_id]
    assert [item.envelope.id for item in items] == [reply_id]


def test_thread_cannot_loop_forever_on_a_cycle(store: MessengerStore) -> None:
    """A reply_to cycle cannot exist through the service, but the walk is
    bounded anyway — a hang is the one failure mode that must not be
    reachable from stored data."""
    items, _ = _send(store, to="b")
    envelope_id = items[0].envelope.id
    store._conn.execute(  # noqa: SLF001 - reaching in to forge an impossible row
        "UPDATE messenger_envelopes SET reply_to = ? WHERE id = ?",
        (envelope_id, envelope_id),
    )
    store._conn.commit()  # noqa: SLF001
    walked, _ = store.thread(envelope_id)
    assert [item.envelope.id for item in walked] == [envelope_id]


# -- outbox / inbox / flows ---------------------------------------------------


def test_outbox_shows_every_copy_a_sender_sent(store: MessengerStore) -> None:
    store.create(
        type="broadcast",
        sender="a",
        addressed_to="*",
        recipients=["b", "c"],
        subject="s",
    )
    _send(store, sender="a", to="d")
    items, _ = store.outbox("a")
    assert sorted(item.recipient for item in items) == ["b", "c", "d"]
    assert store.outbox("b")[0] == []


def test_inbox_does_not_deliver(store: MessengerStore) -> None:
    _send(store, to="b")
    items, _ = store.inbox("b")
    assert [item.state for item in items] == ["pending"]
    assert len(store.check("b")[0]) == 1


def test_flows_matches_either_side_of_a_conversation(store: MessengerStore) -> None:
    _send(store, sender="a", to="b")
    _send(store, sender="c", to="d")
    for handle in ("a", "b"):
        assert len(store.flows(handle=handle)[0]) == 1
    assert len(store.flows()[0]) == 2


def test_flows_respects_its_limit(store: MessengerStore) -> None:
    for _ in range(5):
        _send(store, to="b")
    assert len(store.flows(limit=2)[0]) == 2
