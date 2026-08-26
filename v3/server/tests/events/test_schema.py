from __future__ import annotations

from palaia_hub.events.schema import KNOWN_EVENT_NAMES, SCHEMA_VERSION, Envelope


def test_known_event_names_cover_the_spec_201_v1_vocabulary() -> None:
    expected = {
        "hub.started",
        "client.connected",
        "memory.entry.created",
        "memory.entry.updated",
        "memory.entry.deleted",
        "memory.entry.moved",
        "inbox.captured",
        "index.reindexed",
        "index.embed_backlog_drained",
        "doctor.finding",
    }
    assert expected <= KNOWN_EVENT_NAMES


def test_the_messenger_events_are_additive_names_on_the_same_bus() -> None:
    """SPEC-403 deliverable #5: three additive names, so SPEC-307's
    automations can notify/webhook on them with no new automation work."""
    assert {"message.sent", "message.received", "message.expired"} <= KNOWN_EVENT_NAMES
    assert SCHEMA_VERSION == 1  # additive names never bump the envelope version


def test_envelope_to_json_carries_every_public_field() -> None:
    envelope = Envelope(
        event="memory.entry.created",
        data={"path": "x.md"},
        origin="vault",
        vault="work",
        permalink="x",
    )

    payload = envelope.to_json()

    assert payload == {
        "event": "memory.entry.created",
        "ts": envelope.ts,
        "vault": "work",
        "permalink": "x",
        "origin": "vault",
        "data": {"path": "x.md"},
        "id": envelope.id,
        "schema_version": SCHEMA_VERSION,
    }


def test_envelope_optional_fields_default_to_none() -> None:
    envelope = Envelope(event="hub.started", data={}, origin="hub")

    assert envelope.vault is None
    assert envelope.permalink is None


def test_to_sse_frame_uses_the_envelope_event_name_as_the_sse_topic() -> None:
    envelope = Envelope(event="memory.entry.deleted", data={"path": "x.md"}, origin="vault")

    frame = envelope.to_sse()

    assert frame.startswith(f"id: {envelope.id}\n")
    assert "event: memory.entry.deleted\n" in frame
    assert frame.endswith("\n\n")


def test_each_envelope_gets_a_distinct_id() -> None:
    a = Envelope(event="hub.started", data={}, origin="hub")
    b = Envelope(event="hub.started", data={}, origin="hub")

    assert a.id != b.id
