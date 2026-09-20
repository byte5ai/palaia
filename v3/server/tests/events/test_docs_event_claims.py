"""Issue #419: `v3/docs/how-it-works.md` advertised "a recall" as one of the
things the event bus can hook. No recall-side event exists — retrieval happens
when an agent calls the `recall` tool and emits nothing on the bus — so the
bullet promised an activation seam the code does not provide.

This pins the marketing bullet to the real vocabulary: every trigger it names
must be backed by an actual `KNOWN_EVENT_NAMES` entry.
"""

from __future__ import annotations

from pathlib import Path

from palaia_hub.events.schema import KNOWN_EVENT_NAMES

HOW_IT_WORKS = Path(__file__).resolve().parents[3] / "docs" / "how-it-works.md"

#: Each phrase the event-bus bullet names, and the event that makes it true.
ADVERTISED_TRIGGERS = {
    "a new note": "memory.entry.created",
    "a capture": "inbox.captured",
    "a message": "message.sent",
    "an idle session": "session.idle",
}


def _event_bus_bullet() -> str:
    lines = HOW_IT_WORKS.read_text(encoding="utf-8").splitlines()
    start = next(
        i for i, line in enumerate(lines) if "An event bus with a rules editor" in line
    )
    end = next(
        i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("- **")
    )
    # Normalized to one line: the bullet is hard-wrapped, so "an idle session"
    # is split across a line break in the source.
    return " ".join(" ".join(lines[start:end]).split())


def test_every_advertised_trigger_is_a_real_event() -> None:
    bullet = _event_bus_bullet().lower()
    for phrase, event in ADVERTISED_TRIGGERS.items():
        assert phrase in bullet, f"the bullet no longer names {phrase!r}"
        assert event in KNOWN_EVENT_NAMES, f"{event} backing {phrase!r} is gone"


def test_recall_is_not_advertised_as_hookable_while_it_fires_no_event() -> None:
    if any(name.startswith("recall.") for name in KNOWN_EVENT_NAMES):
        return  # a recall-side event landed — the bullet may advertise it again
    bullet = _event_bus_bullet()
    trigger_list = bullet.split(":", 1)[0]
    assert "recall" not in trigger_list.lower()
