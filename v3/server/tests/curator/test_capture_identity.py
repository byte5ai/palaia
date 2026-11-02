"""Capture identity across retirement and restart (issue #602).

A capture's id is derived from its permalink (format spec §7). The curator
deletes a capture once it is verified, so the permalink's file is gone — but
the id is still carried by the curated note's provenance line. A later
capture about the same subject must not get that permalink again: it would
inherit the old id, and verification would accept the old note as proof
that the *new* content was saved.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from harness import build_harness
from scripted import ingest_session, silent_session

from palaia_hub.gateway.config import VaultMountConfig
from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.vault import VaultEngine
from palaia_hub.vault.gitlayer import GitPolicy, GitRepo
from palaia_hub.vault.models import ENGINE

FIRST = {
    "what_it_concerns": "Rate limit",
    "why_keep": "First fact",
    "content": "OLD_UNIQUE_FACT",
}
SECOND = {
    "what_it_concerns": "Rate limit",
    "why_keep": "Updated fact",
    "content": "NEW_UNIQUE_FACT",
}


async def _files_containing(engine: VaultEngine, needle: str) -> list[str]:
    await engine.refresh()
    found = []
    for path in engine.catalog:
        if needle in (await engine.read_note(path)).text:
            found.append(path)
    return sorted(found)


@pytest.mark.anyio
async def test_a_later_capture_about_the_same_subject_gets_its_own_identity(
    engine: VaultEngine, vault_mount: VaultMountConfig
) -> None:
    harness = build_harness(engine, vault_mount, ingest_session(vault_mount.namespace))
    first_id = await harness.capture(**FIRST)
    first_report = await harness.run_once()
    assert [r.outcome for r in first_report.records] == ["ingested"]
    # The first capture is retired: its inbox file is gone, its id lives on
    # in the curated note's provenance line.
    assert await harness.runner.pending_captures() == []

    # The second session fails without writing anything.
    harness.session_runner.script = silent_session()
    second_id = await harness.capture(**SECOND)
    second_report = await harness.run_once()

    assert second_id != first_id
    [record] = second_report.records
    assert record.capture_id == second_id
    assert record.outcome == "unverified"
    # Nothing was curated, so the new content stays pending in the inbox.
    [pending] = await harness.runner.pending_captures()
    assert pending.capture_id == second_id
    assert await _files_containing(engine, "NEW_UNIQUE_FACT") == [pending.path]


@pytest.mark.anyio
async def test_identities_stay_distinct_after_a_restart(
    vault_root: Path, vault_mount: VaultMountConfig
) -> None:
    """The record of used permalinks is the vault itself, not process memory."""
    engine = VaultEngine(vault_root, name="work")
    await engine.open(purpose=vault_mount.purpose, create=True)
    try:
        harness = build_harness(engine, vault_mount, ingest_session(vault_mount.namespace))
        first_id = await harness.capture(**FIRST)
        await harness.run_once()
        assert await harness.runner.pending_captures() == []
    finally:
        await engine.close()

    reopened = VaultEngine(vault_root, name="work")
    await reopened.open(purpose=vault_mount.purpose)
    try:
        second = await EngineVaultService(reopened).capture(**SECOND)
    finally:
        await reopened.close()

    assert second.capture_id != first_id
    assert second.permalink != "inbox/rate-limit"


@pytest.mark.anyio
async def test_a_never_used_permalink_is_still_handed_out_first(
    engine: VaultEngine,
) -> None:
    """The history check skips used paths only; a fresh subject gets the plain slug."""
    result = await EngineVaultService(engine).capture(**FIRST)
    assert result.permalink == "inbox/rate-limit"


def test_the_git_layer_remembers_deleted_paths(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path, GitPolicy())
    repo.init()
    assert not repo.path_in_history("inbox/rate-limit.md")  # unborn HEAD
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "rate-limit.md").write_text("x\n")
    repo.commit_paths(["inbox/rate-limit.md"], "add", ENGINE)
    (tmp_path / "inbox" / "rate-limit.md").unlink()
    repo.commit_paths(["inbox/rate-limit.md"], "remove", ENGINE)

    assert repo.path_in_history("inbox/rate-limit.md")
    assert not repo.path_in_history("inbox/rate-limit-2.md")
