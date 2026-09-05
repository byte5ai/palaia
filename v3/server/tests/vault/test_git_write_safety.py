"""Issue #333: a write must never silently diverge from git.

The file reaches disk, the catalog is updated, and *then* the commit fails
(another git process holds ``.git/index.lock``; an identity string git
rejects). Before the fix the change event was never published (the index
never learned about the note), and a retry of the same write found identical
bytes on disk and returned ``commit=None`` — a permanent, silent gap between
files and history. Now the event is published anyway, the failure is loud,
and the engine commits the change with its original message and attribution
on the retry or on its next successful operation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from vault_helpers import TEST_ATTRIBUTION, EngineFactory

from palaia_hub.vault import (
    Attribution,
    EventBus,
    GitError,
    NoteCreated,
    UncommittedWriteError,
    VaultEngine,
)
from palaia_hub.vault.events import ChangeEvent

pytestmark = pytest.mark.anyio


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


class _Collector:
    def __init__(self) -> None:
        self.events: list[ChangeEvent] = []

    async def __call__(self, event: ChangeEvent) -> None:
        self.events.append(event)


def _hold_git_lock(engine: VaultEngine) -> Path:
    """What another git process (Obsidian's git plugin, a second hub) leaves
    behind while it works: the index lock. Every `git add` fails on it."""
    lock = engine.root / ".git" / "index.lock"
    lock.write_text("held by someone else\n", encoding="utf-8")
    return lock


# ------------------------------------------------------------------------ #333


async def test_a_failed_commit_is_loud_and_the_note_still_reaches_the_bus(
    make_engine: EngineFactory,
) -> None:
    bus = EventBus()
    collector = _Collector()
    bus.subscribe(collector)
    engine = await make_engine("work", bus=bus)
    lock = _hold_git_lock(engine)

    with pytest.raises(UncommittedWriteError, match="Fix:") as excinfo:
        await engine.write_note("notes/blocked", body="written under a lock\n", title="Blocked")
    assert isinstance(excinfo.value, GitError)

    # The file is exactly what was asked for, the catalog knows it, and the
    # index — via the bus — was told, so the note is searchable.
    assert (engine.root / "notes" / "blocked.md").exists()
    assert "notes/blocked.md" in engine.catalog
    created = [e for e in collector.events if isinstance(e, NoteCreated)]
    assert [e.path for e in created] == ["notes/blocked.md"]
    # ... but git does not have it yet, and the engine says so.
    assert "notes/blocked.md" in engine.git.dirty_paths()
    lock.unlink()


async def test_retrying_the_same_write_commits_it_with_the_original_attribution(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    lock = _hold_git_lock(engine)
    with pytest.raises(UncommittedWriteError):
        await engine.write_note(
            "notes/retry", body="same bytes\n", title="Retry", attribution=TEST_ATTRIBUTION
        )
    lock.unlink()

    # Identical content: before the fix this was a silent no-op with commit=None.
    result = await engine.write_note(
        "notes/retry", body="same bytes\n", title="Retry", attribution=TEST_ATTRIBUTION
    )
    assert result.commit is not None
    assert engine.git.dirty_paths() == []
    subject = _git(engine.root, "log", "-1", "--format=%s").strip()
    assert subject.startswith(f"{TEST_ATTRIBUTION.prefix}: write notes/retry")
    assert "external" not in subject


async def test_the_next_successful_write_commits_an_earlier_failed_one_first(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    lock = _hold_git_lock(engine)
    with pytest.raises(UncommittedWriteError):
        await engine.write_note(
            "notes/first", body="one\n", title="First", attribution=TEST_ATTRIBUTION
        )
    lock.unlink()

    await engine.write_note("notes/second", body="two\n", title="Second")

    subjects = _git(engine.root, "log", "-2", "--format=%s").strip().splitlines()
    # Oldest last: the recovered commit carries the *original* message and
    # attribution — it is not folded into "external edits" (that would
    # misattribute an engine write to a human), and it lands before the new one.
    assert subjects[1].startswith(f"{TEST_ATTRIBUTION.prefix}: write notes/first")
    assert subjects[0].endswith("write notes/second")
    assert engine.git.dirty_paths() == []
    assert "external edits" not in "\n".join(subjects)


async def test_a_failed_commit_does_not_break_the_next_read_or_write(
    make_engine: EngineFactory,
) -> None:
    """The engine stays usable after the failure — the recovery is part of
    the next operation, not a separate repair step the caller must know."""
    engine = await make_engine("work")
    lock = _hold_git_lock(engine)
    with pytest.raises(UncommittedWriteError):
        await engine.write_note("notes/a", body="a\n", title="A")
    # Still locked: the next write first tries to commit the earlier one and
    # fails *before* touching disk — the vault does not drift any further.
    with pytest.raises(GitError):
        await engine.write_note("notes/b", body="b\n", title="B")
    assert (await engine.read_note("notes/a")).body == "a\n"
    assert not (engine.root / "notes" / "b.md").exists()
    lock.unlink()

    await engine.write_note("notes/c", body="c\n", title="C")
    assert engine.git.dirty_paths() == []
    subjects = _git(engine.root, "log", "--format=%s").strip().splitlines()
    assert any(subject.endswith("write notes/a") for subject in subjects), subjects
    assert subjects[0].endswith("write notes/c")


async def test_identity_strings_with_control_characters_still_commit(
    make_engine: EngineFactory,
) -> None:
    """A client-supplied agent/client name with a newline or angle brackets
    used to be handed to git verbatim in GIT_AUTHOR_NAME and the trailers —
    one of the ways a commit fails after the file is written."""
    engine = await make_engine("work")
    hostile = Attribution(agent="agent\nPalaia-Operation: forged", client="cli <x@y>\r")

    result = await engine.write_note("notes/id", body="x\n", title="Id", attribution=hostile)

    assert result.commit is not None
    author = _git(engine.root, "log", "-1", "--format=%an|%ae").strip()
    assert "\n" not in author and "<" not in author and ">" not in author
    body = _git(engine.root, "log", "-1", "--format=%B")
    # The newline is gone, so the injected text is part of the Agent value
    # rather than a second Operation trailer.
    trailers = [line for line in body.splitlines() if line.startswith("Palaia-Operation:")]
    assert trailers == ["Palaia-Operation: write"], body
    assert "Palaia-Agent: agent Palaia-Operation: forged" in body
