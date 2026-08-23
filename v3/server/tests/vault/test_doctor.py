"""Doctor primitives: verify findings, safe repairs, reindex hook."""

from __future__ import annotations

import time
from collections.abc import Iterable

import pytest
from conftest import TEST_POLICY, EngineFactory, write_raw

from palaia_hub.vault import IndexEntry, Note, VaultDoctor
from palaia_hub.vault.atomic import TEMP_SUFFIX
from palaia_hub.vault.doctor import summarize

pytestmark = pytest.mark.anyio


class FakeIndex:
    """Stand-in for the SPEC-104 index."""

    def __init__(self, entries: list[IndexEntry]) -> None:
        self._entries = entries

    def index_entries(self) -> Iterable[IndexEntry]:
        return list(self._entries)


class RecordingSink:
    """Records what a reindex feeds it."""

    def __init__(self) -> None:
        self.vault: str | None = None
        self.notes: list[Note] = []
        self.finished = False

    def begin(self, vault: str) -> None:
        self.vault = vault

    def emit(self, note: Note) -> None:
        self.notes.append(note)

    def finish(self) -> None:
        self.finished = True


async def test_clean_vault_has_no_error_findings(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    await engine.write_note("notes/a", body="No links.\n", title="A")
    findings = await VaultDoctor(engine).verify()
    assert [finding for finding in findings if finding.severity == "error"] == []


async def test_missing_and_duplicate_permalinks_are_reported(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    write_raw(engine, "notes/plain.md", "A bare note.\n")
    write_raw(engine, "notes/one.md", "---\ntitle: One\npermalink: notes/same\n---\n\nx\n")
    write_raw(engine, "notes/two.md", "---\ntitle: Two\npermalink: notes/same\n---\n\nx\n")
    await engine.refresh()

    counts = summarize(await VaultDoctor(engine).verify())
    assert counts["permalink-missing"] == 1
    assert counts["permalink-duplicate"] == 1


async def test_noncanonical_and_volatile_names_are_reported(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    write_raw(
        engine,
        "notes/legacy.md",
        "---\ntitle: Migration v2.3\npermalink: Notes/Legacy_Permalink\n---\n\nx\n",
    )
    await engine.refresh()
    counts = summarize(await VaultDoctor(engine).verify())
    assert counts["permalink-noncanonical"] == 1
    assert counts["volatile-name"] >= 1


async def test_forward_reference_is_a_dangling_link_not_a_partial_rename(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    await engine.write_note("notes/a", body="Points at [[Nothing Yet]].\n", title="A")
    findings = await VaultDoctor(engine).verify()
    codes = summarize(findings)
    assert codes.get("dangling-link") == 1
    assert codes.get("partial-rename", 0) == 0
    dangling = next(finding for finding in findings if finding.code == "dangling-link")
    assert dangling.path == "notes/a.md"
    assert dangling.line == 9  # file-absolute line: frontmatter occupies lines 1-8


async def test_uncommitted_external_changes_are_reported(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    write_raw(engine, "notes/b.md", "---\ntitle: B\npermalink: notes/b\n---\n\nhuman\n")
    counts = summarize(await VaultDoctor(engine).verify())
    assert counts["uncommitted-changes"] == 1


async def test_index_drift_is_reported_against_the_index_interface(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    kept = await engine.write_note("notes/kept", body="x\n", title="Kept")
    stale = await engine.write_note("notes/stale", body="x\n", title="Stale")
    await engine.write_note("notes/unindexed", body="x\n", title="Unindexed")
    assert kept.note is not None and stale.note is not None

    index = FakeIndex(
        [
            IndexEntry(permalink="notes/kept", path="notes/kept.md", checksum=kept.note.checksum),
            IndexEntry(permalink="notes/stale", path="notes/stale.md", checksum="0" * 64),
            IndexEntry(permalink="meta/vault", path="meta/vault.md", checksum=""),
            IndexEntry(permalink="notes/gone", path="notes/gone.md", checksum="0" * 64),
        ]
    )
    counts = summarize(await VaultDoctor(engine).verify(index))
    assert counts["index-stale-entry"] == 2  # notes/stale and meta/vault
    assert counts["index-orphan-entry"] == 1
    assert counts["index-missing-entry"] == 1


async def test_repair_sweeps_temp_files_and_stale_locks(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    await engine.write_note("notes/a", body="x\n", title="A")
    orphan = engine.root / f".notes.md.abc{TEMP_SUFFIX}"
    orphan.write_text("half", encoding="utf-8")
    lock = engine.git.git_dir / "index.lock"
    lock.write_text("", encoding="utf-8")
    time.sleep(TEST_POLICY.stale_lock_after + 0.05)

    doctor = VaultDoctor(engine)
    before = summarize(await doctor.verify())
    assert before["orphan-temp-file"] == 1
    # verify() performs the lock recovery itself: it is routine crash
    # recovery, not an exceptional path (SPEC-003 Q5).
    assert before["git-lock-stale"] == 1
    assert not lock.exists()

    repaired = summarize(await doctor.repair())
    assert repaired["orphan-temp-file"] == 1
    assert not orphan.exists()
    assert "orphan-temp-file" not in summarize(await doctor.verify())


async def test_repair_alone_recovers_a_stale_lock(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    await engine.write_note("notes/a", body="x\n", title="A")
    lock = engine.git.git_dir / "index.lock"
    lock.write_text("", encoding="utf-8")
    time.sleep(TEST_POLICY.stale_lock_after + 0.05)

    repaired = summarize(await VaultDoctor(engine).repair())
    assert repaired["git-lock-stale"] == 1
    assert not lock.exists()


async def test_manifest_and_format_version_findings(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    manifest = engine.root / "meta/vault.md"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("vault_format: 1", "vault_format: 99"),
        encoding="utf-8",
    )
    await engine.open()
    counts = summarize(await VaultDoctor(engine).verify())
    assert counts["format-version"] == 1

    manifest.unlink()
    engine2 = await make_engine("other", root=engine.root)
    counts = summarize(await VaultDoctor(engine2).verify())
    assert "manifest-missing" not in counts  # re-open with create=True rewrote it


async def test_engine_exposes_the_doctor_hook_points(make_engine: EngineFactory) -> None:
    """SPEC-102 deliverable 4: verify()/repair()/reindex() on the engine itself."""
    engine = await make_engine("work")
    await engine.write_note("notes/a", body="x\n", title="A")
    assert await engine.verify() == await VaultDoctor(engine).verify()
    assert await engine.repair() == []

    sink = RecordingSink()
    assert await engine.reindex(sink) == 2
    assert sink.finished is True


async def test_reindex_feeds_every_note_from_files(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    await engine.write_note("notes/a", body="a\n", title="A")
    await engine.write_note("projects/b", body="b\n", title="B")
    write_raw(engine, "notes/external.md", "---\ntitle: Ext\n---\n\nexternal\n")

    sink = RecordingSink()
    count = await VaultDoctor(engine).reindex(sink)

    assert count == 4  # two engine notes, the manifest, the external note
    assert sink.vault == "work"
    assert sink.finished is True
    paths = [note.path for note in sink.notes]
    assert paths == sorted(paths)
    assert "notes/external.md" in paths
    assert all(note.checksum for note in sink.notes)
