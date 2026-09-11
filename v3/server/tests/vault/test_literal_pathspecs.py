"""Issue #334: a file name is a file name, never git pathspec magic.

Git reads a leading ``:`` in a pathspec as magic even after ``--``
(``git add -A -- ':todo.md'`` → "did not match any files"), so one
``:todo.md`` created in an editor failed the external-edit sweep at the start
of every engine write — the vault turned read-only for the engine until the
file was renamed. The git layer now runs with ``GIT_LITERAL_PATHSPECS=1``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from vault_helpers import TEST_ATTRIBUTION, EngineFactory, write_raw

from palaia_hub.vault import GitRepo
from palaia_hub.vault.models import build_commit_message

pytestmark = pytest.mark.anyio


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


def test_the_git_layer_stages_a_colon_prefixed_path_literally(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path / "vault")
    repo.root.mkdir()
    repo.init()
    (repo.root / ":colon.md").write_text("x\n", encoding="utf-8")

    sha = repo.commit_paths(
        [":colon.md"],
        build_commit_message(TEST_ATTRIBUTION, "add colon", operation="write"),
        TEST_ATTRIBUTION,
    )

    assert sha is not None
    assert ":colon.md" in _git(repo.root, "ls-files")
    assert repo.dirty_paths() == []


async def test_a_file_named_with_a_leading_colon_does_not_block_engine_writes(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    write_raw(engine, ":todo.md", "---\ntitle: Todo\n---\n\n- [ ] something\n")

    # The sweep at the start of this write stages ':todo.md' — with git's
    # pathspec magic that was `fatal: pathspec ':todo.md' did not match`.
    result = await engine.write_note("notes/after", body="fine\n", title="After")

    assert result.commit is not None
    assert engine.git.dirty_paths() == []
    assert ":todo.md" in _git(engine.root, "ls-files")
    # And the engine can address the note itself.
    assert (await engine.read_note(":todo.md")).title == "Todo"


async def test_the_engine_can_write_and_delete_a_colon_prefixed_note(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    written = await engine.write_note(":inbox", body="via the engine\n", title="Inbox")
    assert written.commit is not None
    deleted = await engine.delete_note(":inbox")
    assert deleted.commit is not None
    assert ":inbox.md" not in engine.catalog
    assert engine.git.dirty_paths() == []
