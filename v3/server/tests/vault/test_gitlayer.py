"""Git layer: changed-paths staging, attribution, gc policy, stale locks."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
from vault_helpers import TEST_ATTRIBUTION, TEST_POLICY, EngineFactory

from palaia_hub.vault import HUMAN, GitPolicy, GitRepo
from palaia_hub.vault.models import build_commit_message

pytestmark = pytest.mark.anyio


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> GitRepo:
    repository = GitRepo(tmp_path / "vault", TEST_POLICY)
    repository.root.mkdir(parents=True)
    repository.init()
    return repository


def test_init_writes_the_gc_policy(repo: GitRepo) -> None:
    assert git(repo.root, "config", "gc.auto").strip() == str(TEST_POLICY.gc_auto)
    assert git(repo.root, "config", "gc.autoPackLimit").strip() == str(
        TEST_POLICY.gc_auto_pack_limit
    )
    assert git(repo.root, "config", "gc.autoDetach").strip() == "false"
    assert repo.init() is False  # idempotent


def test_commit_paths_stages_only_the_given_paths(repo: GitRepo) -> None:
    (repo.root / "a.md").write_text("a\n", encoding="utf-8")
    (repo.root / "b.md").write_text("b\n", encoding="utf-8")
    sha = repo.commit_paths(["a.md"], "test: add a", TEST_ATTRIBUTION)
    assert sha is not None
    assert git(repo.root, "log", "-1", "--name-only", "--format=").split() == ["a.md"]
    assert [path for _, path in repo.status()] == ["b.md"]


def test_commit_paths_stages_deletions(repo: GitRepo) -> None:
    (repo.root / "a.md").write_text("a\n", encoding="utf-8")
    repo.commit_paths(["a.md"], "test: add a", TEST_ATTRIBUTION)
    (repo.root / "a.md").unlink()
    repo.commit_paths(["a.md"], "test: remove a", TEST_ATTRIBUTION)
    assert repo.status() == []
    assert repo.path_at_head("a.md") is False


def test_commit_paths_returns_none_when_nothing_changed(repo: GitRepo) -> None:
    (repo.root / "a.md").write_text("a\n", encoding="utf-8")
    repo.commit_paths(["a.md"], "test: add a", TEST_ATTRIBUTION)
    assert repo.commit_paths(["a.md"], "test: nothing", TEST_ATTRIBUTION) is None
    # Same, with unrelated untracked files present (git words that case
    # differently, and it must still not raise).
    (repo.root / "untracked.md").write_text("u\n", encoding="utf-8")
    assert repo.commit_paths(["a.md"], "test: still nothing", TEST_ATTRIBUTION) is None
    assert repo.commit_paths([], "test: no paths", TEST_ATTRIBUTION) is None


def test_commit_message_attribution_and_trailers(repo: GitRepo) -> None:
    (repo.root / "a.md").write_text("a\n", encoding="utf-8")
    message = build_commit_message(
        TEST_ATTRIBUTION, "write notes/a", operation="write", permalinks=["notes/a"]
    )
    repo.commit_paths(["a.md"], message, TEST_ATTRIBUTION)
    entry = repo.log(limit=1)[0]
    assert entry.subject == "curator/claude-code/anthropic: write notes/a"
    assert entry.author_name == "curator"
    assert entry.author_email == "curator@palaia.local"
    assert entry.trailers["operation"] == "write"
    assert entry.trailers["permalink"] == "notes/a"
    assert entry.trailers["session"] == "s-42"
    assert git(repo.root, "log", "-1", "--format=%cn").strip() == "palaia-hub"


def test_human_attribution_marks_external_edits(repo: GitRepo) -> None:
    (repo.root / "a.md").write_text("a\n", encoding="utf-8")
    repo.commit_paths(
        ["a.md"],
        build_commit_message(HUMAN, "external edits (1 path)", operation="external"),
        HUMAN,
    )
    entry = repo.log(limit=1)[0]
    assert entry.subject == "-/-/human: external edits (1 path)"
    assert entry.author_name == "human"
    assert entry.trailers["origin"] == "human"


def test_stale_lock_is_detected_and_removed(repo: GitRepo) -> None:
    lock = repo.git_dir / "index.lock"
    lock.write_text("", encoding="utf-8")
    time.sleep(TEST_POLICY.stale_lock_after + 0.05)
    recoveries = repo.recover_stale_locks()
    assert [(recovery.path, recovery.removed) for recovery in recoveries] == [("index.lock", True)]
    assert not lock.exists()


def test_fresh_lock_is_reported_but_left_alone(tmp_path: Path) -> None:
    repository = GitRepo(tmp_path / "vault", GitPolicy(stale_lock_after=30.0))
    repository.root.mkdir(parents=True)
    repository.init()
    lock = repository.git_dir / "index.lock"
    lock.write_text("", encoding="utf-8")
    recoveries = repository.recover_stale_locks()
    assert [(recovery.path, recovery.removed) for recovery in recoveries] == [("index.lock", False)]
    assert lock.exists()


def test_gc_keeps_the_repository_readable(repo: GitRepo) -> None:
    for index in range(5):
        (repo.root / f"note-{index}.md").write_text(f"note {index}\n", encoding="utf-8")
        repo.commit_paths([f"note-{index}.md"], f"test: note {index}", TEST_ATTRIBUTION)
    repo.gc()
    assert len(repo.log(limit=10)) == 5
    assert repo.size_bytes() > 0
    assert repo.content_size_bytes() > 0


async def test_engine_recovers_a_stale_lock_on_open(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    await engine.write_note("notes/a", body="x\n", title="A")
    lock = engine.git.git_dir / "index.lock"
    lock.write_text("", encoding="utf-8")
    time.sleep(TEST_POLICY.stale_lock_after + 0.05)

    # Re-opening the vault is the hub's normal startup path.
    await engine.open()
    assert not lock.exists()
    result = await engine.write_note("notes/b", body="x\n", title="B")
    assert result.commit is not None
