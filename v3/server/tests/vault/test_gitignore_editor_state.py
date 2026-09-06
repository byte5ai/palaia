"""Issue #359: editor state never becomes vault history.

``_sweep_external_edits`` committed every dirty path, and the vault's
``.gitignore`` ignored only engine storage and temp files — so Obsidian's
constantly rewritten ``.obsidian/workspace.json`` rode along as a "human:
external edits" commit on nearly every engine write, and ``.trash/`` became
committed history. Both directories are ignored now, existing vaults are
upgraded once, and the sweep itself skips ``IGNORED_DIRS`` whatever the
``.gitignore`` says.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from vault_helpers import EngineFactory, write_raw

from palaia_hub.vault.engine import GITIGNORE_MARKER

pytestmark = pytest.mark.anyio

OLD_GITIGNORE = (
    "# palaia engine-private storage: rebuildable index/state, never vault content\n"
    ".palaia/\n"
    "# in-flight atomic writes\n"
    "*.tmp\n"
)


def _subjects(root: Path) -> list[str]:
    return subprocess.run(
        ["git", "-C", str(root), "log", "--format=%s"], capture_output=True, text=True, check=True
    ).stdout.splitlines()


async def test_a_new_vault_ignores_editor_state_and_trash(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    gitignore = (engine.root / ".gitignore").read_text(encoding="utf-8")
    assert ".obsidian/" in gitignore
    assert ".trash/" in gitignore
    assert GITIGNORE_MARKER in gitignore

    write_raw(engine, ".obsidian/workspace.json", '{"leaf": "changes constantly"}\n')
    write_raw(engine, ".trash/old-note.md", "---\ntitle: Old\n---\nbinned\n")
    assert engine.git.dirty_paths() == []

    before = _subjects(engine.root)
    await engine.write_note("notes/a", body="engine\n", title="A")
    after = _subjects(engine.root)
    assert len(after) == len(before) + 1, "one engine commit, no 'external edits' rider"
    assert not any("external edits" in subject for subject in after)


async def test_an_existing_vault_is_upgraded_once_and_then_left_alone(
    make_engine: EngineFactory, tmp_path: Path
) -> None:
    root = tmp_path / "old-vault"
    root.mkdir()
    (root / ".gitignore").write_text(OLD_GITIGNORE, encoding="utf-8")

    engine = await make_engine("old", root=root)
    upgraded = (root / ".gitignore").read_text(encoding="utf-8")
    assert upgraded.startswith(OLD_GITIGNORE.rstrip("\n"))
    assert upgraded.count(".obsidian/") == 1 and ".trash/" in upgraded
    await engine.close()

    # The owner decides to track their Obsidian settings after all.
    trimmed = upgraded.replace(".obsidian/\n", "")
    (root / ".gitignore").write_text(trimmed, encoding="utf-8")
    engine = await make_engine("old", root=root)
    assert (root / ".gitignore").read_text(encoding="utf-8") == trimmed, "not re-added"
    await engine.close()


async def test_the_sweep_skips_ignored_dirs_even_without_the_gitignore_rules(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    # A vault whose owner stripped the rules: git now sees editor trash.
    (engine.root / ".gitignore").write_text(".palaia/\n*.tmp\n", encoding="utf-8")
    write_raw(engine, ".trash/old-note.md", "---\ntitle: Old\n---\nbinned\n")
    write_raw(engine, ".obsidian/workspace.json", "{}\n")
    assert any(path.startswith(".trash/") for path in engine.git.dirty_paths())

    write_raw(engine, "notes/b.md", "---\ntitle: B\npermalink: notes/b\n---\n\nhuman\n")
    commit = await engine.commit_external_changes()

    assert commit is not None
    committed = subprocess.run(
        ["git", "-C", str(engine.root), "show", "--name-only", "--format=", commit],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert "notes/b.md" in committed
    assert not any(path.startswith((".trash/", ".obsidian/")) for path in committed)


@pytest.mark.parametrize("ignored", [".obsidian/app.json", ".trash/gone.md"])
async def test_only_editor_state_dirty_means_nothing_to_commit(
    make_engine: EngineFactory, ignored: str
) -> None:
    engine = await make_engine("work")
    (engine.root / ".gitignore").write_text(".palaia/\n*.tmp\n", encoding="utf-8")
    await engine.commit_external_changes()  # the .gitignore edit itself
    write_raw(engine, ignored, "x\n")

    assert await engine.commit_external_changes() is None
