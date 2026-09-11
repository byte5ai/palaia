"""Issue #335: a note whose frontmatter does not parse is never re-rendered.

``frontmatter.parse`` returns an empty mapping (and ``malformed=True``) for a
fence whose YAML is broken. Every write that rebuilds the frontmatter from
the parsed mapping — an edit, a replace, a rename, the permalink write-back —
would render that emptiness back to disk and the user's original block
(custom keys, a half-typed edit, the permalink itself) would be gone. The
engine refuses those writes with a "Fix:" pointing at the file, and leaves
the bytes exactly as they were.
"""

from __future__ import annotations

import pytest
from vault_helpers import EngineFactory, write_raw

from palaia_hub.vault import MalformedFrontmatterError, VaultError

pytestmark = pytest.mark.anyio

BROKEN = "---\ntitle: [unclosed\ncustom_key: keep me\npermalink: notes/broken\n---\n\nbody\n"


async def test_an_edit_of_a_malformed_note_is_refused_and_the_file_is_untouched(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    path = write_raw(engine, "notes/broken.md", BROKEN)
    await engine.refresh()

    note = await engine.read_note("notes/broken")
    assert note.malformed_frontmatter
    assert note.frontmatter == {}

    with pytest.raises(MalformedFrontmatterError, match="Fix:"):
        await engine.edit_note("notes/broken", body="new body\n", expected_checksum=note.checksum)
    with pytest.raises(MalformedFrontmatterError):
        await engine.edit_note(
            "notes/broken", frontmatter={"tags": ["x"]}, expected_checksum=note.checksum
        )
    assert path.read_text(encoding="utf-8") == BROKEN
    assert isinstance(MalformedFrontmatterError("x"), VaultError)


async def test_a_replace_of_a_malformed_note_is_refused_too(make_engine: EngineFactory) -> None:
    """A replace keeps the identity keys of the existing frontmatter — which
    parsed to nothing, so it would silently mint a new permalink."""
    engine = await make_engine("work")
    path = write_raw(engine, "notes/broken.md", BROKEN)
    await engine.refresh()

    with pytest.raises(MalformedFrontmatterError):
        await engine.write_note("notes/broken", body="replaced\n", title="Broken")
    assert path.read_text(encoding="utf-8") == BROKEN


async def test_a_rename_of_a_malformed_note_is_refused(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    path = write_raw(engine, "notes/broken.md", BROKEN)
    await engine.refresh()

    with pytest.raises(MalformedFrontmatterError):
        await engine.rename_entity("notes/broken", "Fixed Title")
    assert path.read_text(encoding="utf-8") == BROKEN


async def test_the_permalink_write_back_skips_malformed_notes_but_serves_the_rest(
    make_engine: EngineFactory,
) -> None:
    """A malformed note has no *parsed* permalink, so it looks like a note
    that needs one — rewriting it would destroy the block that already
    carries one. The plain note next to it still gets its permalink."""
    engine = await make_engine("work")
    broken = write_raw(engine, "notes/broken.md", BROKEN)
    write_raw(engine, "notes/plain.md", "Just a body, no fence.\n")
    await engine.refresh()

    assigned = await engine.assign_missing_permalinks()

    assert broken.read_text(encoding="utf-8") == BROKEN
    assert assigned == ["notes/plain"]
    assert (await engine.read_note("notes/plain")).permalink == "notes/plain"


async def test_a_note_with_no_fence_at_all_is_not_malformed_and_stays_editable(
    make_engine: EngineFactory,
) -> None:
    """The guard is for a *broken* fence only — a plain Markdown file has no
    frontmatter to lose and keeps working as before."""
    engine = await make_engine("work")
    write_raw(engine, "notes/plain.md", "Just a body.\n")
    await engine.refresh()
    note = await engine.read_note("notes/plain")
    assert not note.malformed_frontmatter

    result = await engine.edit_note(
        "notes/plain", body="Edited.\n", expected_checksum=note.checksum
    )
    assert result.note.body == "Edited.\n"
    assert result.note.permalink == "notes/plain"


async def test_once_repaired_outside_the_engine_the_note_is_editable_again(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    path = write_raw(engine, "notes/broken.md", BROKEN)
    await engine.refresh()
    note = await engine.read_note("notes/broken")
    with pytest.raises(MalformedFrontmatterError):
        await engine.edit_note("notes/broken", body="x\n", expected_checksum=note.checksum)

    path.write_text(BROKEN.replace("[unclosed", "Fixed"), encoding="utf-8")
    await engine.refresh()
    repaired = await engine.read_note("notes/broken")
    assert not repaired.malformed_frontmatter
    result = await engine.edit_note(
        "notes/broken", body="edited after repair\n", expected_checksum=repaired.checksum
    )
    assert result.note.frontmatter["custom_key"] == "keep me"
    assert result.note.permalink == "notes/broken"
