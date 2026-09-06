"""Issue #355: a note that is not UTF-8 is never silently corrupted.

The engine decoded every note with replacement characters and wrote the
result back on edit — a Latin-1 note lost its umlauts for good on its first
engine edit. The rename walk and the doctor's link check decoded strictly
and caught only ``OSError``: one such note aborted a rename half-way (some
backlinks rewritten, nothing committed, no event) and crashed ``verify``.
"""

from __future__ import annotations

import pytest
from vault_helpers import TEST_ATTRIBUTION, EngineFactory

from palaia_hub.vault import EntityRenamed, EventBus, NoteEncodingError, VaultDoctor, VaultEngine
from palaia_hub.vault.doctor import summarize

pytestmark = pytest.mark.anyio

LATIN1_NOTE = (
    b"---\ntitle: Cafe Notes\npermalink: notes/cafe\ntype: note\n---\n"
    b"Caf\xe9 au lait, see [[API Gateway]] \xfcber alles.\n"
)


async def _with_latin1_note(engine: VaultEngine) -> None:
    path = engine.root / "notes" / "cafe.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(LATIN1_NOTE)
    await engine.commit_external_changes()


async def test_reading_marks_the_note_and_editing_refuses_to_corrupt_it(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    await _with_latin1_note(engine)

    note = await engine.read_note("notes/cafe")
    assert note.undecodable is True
    assert "�" in note.body, "still readable, with replacement characters"

    with pytest.raises(NoteEncodingError, match="iconv"):
        await engine.edit_note(
            "notes/cafe",
            frontmatter={"tags": ["coffee"]},
            expected_checksum=note.checksum,
            attribution=TEST_ATTRIBUTION,
        )

    assert (engine.root / "notes" / "cafe.md").read_bytes() == LATIN1_NOTE


async def test_rename_rewrites_the_backlink_and_keeps_every_other_byte(
    make_engine: EngineFactory,
) -> None:
    bus = EventBus()
    events: list[object] = []

    async def record(event: object) -> None:
        events.append(event)

    bus.subscribe(record)
    engine = await make_engine("work", bus=bus)
    await engine.write_note(
        "projects/api-gateway", title="API Gateway", body="Gateway.\n", attribution=TEST_ATTRIBUTION
    )
    await _with_latin1_note(engine)

    result = await engine.rename_entity(
        "API Gateway", "Gateway Service", attribution=TEST_ATTRIBUTION
    )

    raw = (engine.root / "notes" / "cafe.md").read_bytes()
    assert b"[[Gateway Service]]" in raw
    assert b"[[API Gateway]]" not in raw
    assert b"Caf\xe9 au lait" in raw and b"\xfcber alles" in raw, "original bytes untouched"
    assert "notes/cafe.md" in result.rewritten
    assert any(isinstance(event, EntityRenamed) for event in events)
    assert result.commit, "one atomic commit, as the format spec promises"


async def test_the_doctor_reports_the_encoding_and_still_checks_links(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    await _with_latin1_note(engine)

    findings = await VaultDoctor(engine).verify()

    codes = summarize(findings)
    assert codes.get("not-utf8") == 1
    finding = next(f for f in findings if f.code == "not-utf8")
    assert finding.path == "notes/cafe.md"
    assert "iconv" in finding.fix
    # The link check ran over the note instead of crashing on it.
    assert codes.get("dangling-link") == 1
