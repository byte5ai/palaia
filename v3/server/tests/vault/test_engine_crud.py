"""Vault CRUD: synchronous write-through, identity, attribution, concurrency."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from conftest import TEST_ATTRIBUTION, TEST_POLICY, EngineFactory, write_raw

from palaia_hub.vault import (
    ChecksumConflictError,
    EventBus,
    NoteCreated,
    NoteExistsError,
    NoteModified,
    NoteMoved,
    NoteNotFoundError,
    VaultEngine,
    VaultFormatVersionError,
    VolatileNameError,
)
from palaia_hub.vault import frontmatter as fm
from palaia_hub.vault.atomic import sha256_bytes
from palaia_hub.vault.errors import (
    AmbiguousReferenceError,
    InvalidPathError,
    PermalinkConflictError,
)

pytestmark = pytest.mark.anyio


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


# --------------------------------------------------------------------- opening


async def test_open_initializes_layout_manifest_and_git(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    for reserved in ("meta", "inbox", "review"):
        assert (engine.root / reserved).is_dir()
    assert engine.engine_dir.is_dir()
    manifest = fm.parse((engine.root / "meta/vault.md").read_text(encoding="utf-8"))
    assert manifest.frontmatter["permalink"] == "meta/vault"
    assert manifest.frontmatter["vault_format"] == 1
    assert manifest.frontmatter["name"] == "work"
    assert engine.git.initialized
    assert engine.git.head() is not None
    gitignore = (engine.root / ".gitignore").read_text(encoding="utf-8")
    assert ".palaia/" in gitignore
    # .palaia/ must never be tracked: it is rebuildable engine state.
    (engine.engine_dir / "index.db").write_text("scratch", encoding="utf-8")
    assert engine.git.dirty_paths() == []


async def test_open_declares_gc_policy_in_repo_config(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    assert git(engine.root, "config", "gc.auto").strip() == str(TEST_POLICY.gc_auto)
    assert git(engine.root, "config", "gc.autoPackLimit").strip() == str(
        TEST_POLICY.gc_auto_pack_limit
    )


async def test_unknown_format_version_is_read_only(make_engine: EngineFactory) -> None:
    engine = await make_engine("future")
    manifest = engine.root / "meta/vault.md"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("vault_format: 1", "vault_format: 99"),
        encoding="utf-8",
    )
    reopened = VaultEngine(engine.root, "future", policy=TEST_POLICY)
    await reopened.open()
    assert reopened.writable is False
    note = await reopened.read_note("meta/vault")  # reads stay best-effort
    assert note.title == "Vault"
    with pytest.raises(VaultFormatVersionError):
        await reopened.write_note("notes/nope.md", body="x")


# ---------------------------------------------------------------------- writes


async def test_write_note_is_on_disk_and_committed(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    result = await engine.write_note(
        "projects/api-gateway",
        body="- [rate-limit] 100 req/min\n",
        title="API Gateway",
        attribution=TEST_ATTRIBUTION,
        summary="record the gateway rate limit",
    )
    assert result.created is True
    assert result.note is not None
    path = engine.root / "projects/api-gateway.md"
    assert path.exists()
    assert result.note.permalink == "projects/api-gateway"
    assert result.note.checksum == sha256_bytes(path.read_bytes())

    parsed = fm.parse(path.read_text(encoding="utf-8"))
    assert parsed.frontmatter["title"] == "API Gateway"
    assert parsed.frontmatter["type"] == "note"
    assert parsed.frontmatter["created"].endswith("Z")
    assert parsed.frontmatter["origin"] == {
        "provider": "anthropic",
        "client": "claude-code",
        "session": "s-42",
        "agent": "curator",
    }

    subject = git(engine.root, "log", "-1", "--format=%s").strip()
    assert subject == "curator/claude-code/anthropic: record the gateway rate limit"
    body = git(engine.root, "log", "-1", "--format=%b")
    assert "Palaia-Operation: write" in body
    assert "Palaia-Permalink: projects/api-gateway" in body
    assert git(engine.root, "log", "-1", "--format=%an").strip() == "curator"
    assert git(engine.root, "log", "-1", "--name-only", "--format=").split() == [
        "projects/api-gateway.md"
    ]


async def test_write_note_publishes_events(make_engine: EngineFactory) -> None:
    bus = EventBus()
    seen: list[object] = []
    bus.subscribe(seen.append)
    engine = await make_engine("work", bus=bus)
    await engine.write_note("notes/a", body="one\n", title="A")
    await engine.write_note("notes/a", body="two\n", title="A")
    assert isinstance(seen[0], NoteCreated)
    assert isinstance(seen[1], NoteModified)
    assert all(not event.external for event in seen)  # type: ignore[attr-defined]


async def test_write_note_must_create_refuses_existing(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    await engine.write_note("notes/a", body="one\n", title="A")
    with pytest.raises(NoteExistsError):
        await engine.write_note("notes/a", body="two\n", title="A", must_create=True)


async def test_identical_write_makes_no_commit(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    first = await engine.write_note("notes/a", body="one\n", title="A")
    assert first.note is not None
    text = (engine.root / "notes/a.md").read_text(encoding="utf-8")
    head = engine.git.head()
    second = await engine.write_note(
        "notes/a",
        body=first.note.body,
        title="A",
        frontmatter={
            "created": first.note.frontmatter["created"],
            "modified": first.note.frontmatter["modified"],
        },
    )
    assert second.commit is None
    assert engine.git.head() == head
    assert (engine.root / "notes/a.md").read_text(encoding="utf-8") == text


async def test_volatile_title_is_rejected(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    with pytest.raises(VolatileNameError, match="volatile"):
        await engine.write_note("notes/openclaw", body="x", title="OpenClaw 2026.5.7")


async def test_permalink_conflict_is_refused(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    await engine.write_note("notes/a", body="x", title="A")
    with pytest.raises(PermalinkConflictError):
        await engine.write_note("notes/b", body="x", title="B", permalink="notes/a")


async def test_paths_outside_the_vault_are_refused(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    with pytest.raises(InvalidPathError):
        await engine.write_note("../escape.md", body="x")
    with pytest.raises(InvalidPathError):
        await engine.write_note(".palaia/secret.md", body="x")


# ----------------------------------------------------------------------- edits


async def test_edit_note_preserves_identity_and_unknown_keys(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    created = await engine.write_note(
        "notes/a", body="one\n", title="A", frontmatter={"custom": "kept", "tags": ["x"]}
    )
    assert created.note is not None
    edited = await engine.edit_note(
        "notes/a", body="two\n", expected_checksum=created.note.checksum
    )
    assert edited.note is not None
    assert edited.note.body == "two\n"
    assert edited.note.permalink == created.note.permalink
    assert edited.note.frontmatter["custom"] == "kept"
    assert edited.note.frontmatter["tags"] == ["x"]
    assert edited.note.frontmatter["created"] == created.note.frontmatter["created"]


async def test_edit_note_rejects_stale_checksum(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    created = await engine.write_note("notes/a", body="one\n", title="A")
    assert created.note is not None
    await engine.edit_note("notes/a", body="two\n", expected_checksum=created.note.checksum)
    with pytest.raises(ChecksumConflictError, match="changed since you read it"):
        await engine.edit_note("notes/a", body="three\n", expected_checksum=created.note.checksum)


async def test_edit_note_on_missing_note_raises(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    await engine.write_note("notes/a", body="one\n", title="A")
    with pytest.raises(NoteNotFoundError):
        await engine.edit_note("notes/ghost", body="x", expected_checksum="0" * 64)


# ------------------------------------------------------------------ concurrency


async def test_concurrent_writers_to_different_notes_do_not_interleave(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    results = await asyncio.gather(
        *(
            engine.write_note(f"notes/n{index}", body=f"body {index}\n", title=f"N{index}")
            for index in range(12)
        )
    )
    assert all(result.created for result in results)
    permalinks = set()
    for index in range(12):
        note = await engine.read_note(f"notes/n{index}")
        assert note.body == f"body {index}\n"
        assert note.malformed_frontmatter is False
        permalinks.add(note.permalink)
    assert len(permalinks) == 12
    # One commit per acknowledged write, plus the initial commit.
    assert len(git(engine.root, "log", "--format=%H").split()) == 13


async def test_concurrent_writers_to_the_same_note_conflict(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    created = await engine.write_note("notes/shared", body="base\n", title="Shared")
    assert created.note is not None
    checksum = created.note.checksum

    async def writer(value: str) -> str:
        try:
            await engine.edit_note("notes/shared", body=value, expected_checksum=checksum)
        except ChecksumConflictError:
            return "conflict"
        return "ok"

    outcomes = await asyncio.gather(writer("first\n"), writer("second\n"))
    assert sorted(outcomes) == ["conflict", "ok"]
    note = await engine.read_note("notes/shared")
    assert note.body in ("first\n", "second\n")


# ------------------------------------------------------------------ move/delete


async def test_move_note_keeps_the_permalink(make_engine: EngineFactory) -> None:
    bus = EventBus()
    events: list[object] = []
    bus.subscribe(events.append)
    engine = await make_engine("work", bus=bus)
    created = await engine.write_note("inbox/capture", body="x\n", title="Capture")
    assert created.note is not None
    permalink = created.note.permalink
    assert permalink is not None

    moved = await engine.move_note("inbox/capture", "projects/capture.md")
    assert moved.note is not None
    assert moved.note.permalink == permalink  # identity is not in the path (§3.1)
    assert not (engine.root / "inbox/capture.md").exists()
    assert (engine.root / "projects/capture.md").exists()
    assert isinstance(events[-1], NoteMoved)

    # The note is still addressable by its permalink after the move.
    note = await engine.read_note(permalink)
    assert note.path == "projects/capture.md"
    history = await engine.history(permalink)
    assert len(history) == 2


async def test_delete_note_commits_the_removal(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    await engine.write_note("notes/a", body="x\n", title="A")
    result = await engine.delete_note("notes/a")
    assert result.commit is not None
    assert not (engine.root / "notes/a.md").exists()
    assert "delete" in git(engine.root, "log", "-1", "--format=%s")
    with pytest.raises(NoteNotFoundError):
        await engine.read_note("notes/a")


async def test_list_dir_reports_notes_dirs_and_attachments(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    await engine.write_note("projects/api", body="x\n", title="API")
    await engine.write_note("projects/sub/deep", body="x\n", title="Deep")
    (engine.root / "projects/diagram.png").write_bytes(b"\x89PNG")
    entries = await engine.list_dir("projects")
    kinds = {entry.path: entry.kind for entry in entries}
    assert kinds == {
        "projects/api.md": "note",
        "projects/diagram.png": "file",
        "projects/sub": "dir",
    }
    note_entry = next(entry for entry in entries if entry.kind == "note")
    assert note_entry.permalink == "projects/api"
    assert note_entry.title == "API"


# ----------------------------------------------------------------- resolution


async def test_resolution_order_permalink_alias_title_path(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    await engine.write_note(
        "projects/api", body="x\n", title="API Gateway", frontmatter={"aliases": ["Old Gateway"]}
    )
    for reference in (
        "projects/api-gateway",
        "memory://projects/api-gateway",
        "memory://work/projects/api-gateway",
        "Old Gateway",
        "API Gateway",
        "projects/api.md",
        "api.md",
    ):
        note = await engine.read_note(reference)
        assert note.path == "projects/api.md", reference


async def test_ambiguous_title_lists_candidates(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    await engine.write_note("a/dup", body="x\n", title="Duplicate")
    await engine.write_note("b/dup", body="x\n", title="Duplicate")
    with pytest.raises(AmbiguousReferenceError, match="matches 2 notes"):
        await engine.read_note("Duplicate")


# ------------------------------------------------------------- external edits


async def test_external_edit_is_committed_as_its_own_human_commit(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    await engine.write_note("notes/a", body="engine\n", title="A")
    write_raw(engine, "notes/b.md", "---\ntitle: B\npermalink: notes/b\n---\n\nhuman\n")

    await engine.write_note("notes/c", body="engine\n", title="C")

    subjects = git(engine.root, "log", "--format=%s").splitlines()
    assert subjects[0].startswith("-/-/engine: write notes/c")
    assert subjects[1] == "-/-/human: external edits (1 path)"
    external = git(engine.root, "log", "--skip=1", "-1", "--format=%an%n%b")
    assert external.splitlines()[0] == "human"
    assert "Palaia-Origin: human" in external
    # The engine's own commit contains only its own file.
    assert git(engine.root, "log", "-1", "--name-only", "--format=").split() == ["notes/c.md"]
    # The externally created note is now known to the engine.
    note = await engine.read_note("notes/b")
    assert note.body == "human\n"


async def test_commit_external_changes_can_be_called_directly(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    write_raw(engine, "notes/b.md", "---\ntitle: B\npermalink: notes/b\n---\n\nhuman\n")
    commit = await engine.commit_external_changes()
    assert commit is not None
    assert engine.git.dirty_paths() == []
    assert await engine.commit_external_changes() is None


async def test_assign_missing_permalinks_writes_back(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    write_raw(engine, "notes/plain.md", "Just a bare Obsidian note.\n")
    await engine.refresh()
    assert engine.catalog["notes/plain.md"].permalink is None

    assigned = await engine.assign_missing_permalinks()
    assert assigned == ["notes/plain"]
    note = await engine.read_note("notes/plain")
    assert note.permalink == "notes/plain"
    assert note.body == "Just a bare Obsidian note.\n"
    assert "assign permalinks" in git(engine.root, "log", "-1", "--format=%s")
