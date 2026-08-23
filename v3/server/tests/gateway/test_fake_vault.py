"""Round-trip coverage for the in-memory fake VaultService used by tests."""

from __future__ import annotations

import pytest

from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.gateway.vault_protocol import VaultServiceError


@pytest.mark.anyio
async def test_write_then_read_round_trips() -> None:
    vault = FakeVaultService()
    note = await vault.write("My Note", "hello world", folder="projects")
    assert note.permalink == "projects/my-note"

    read_back = await vault.read(note.permalink)
    assert read_back.title == "My Note"
    assert read_back.body == "hello world"


@pytest.mark.anyio
async def test_write_then_search_finds_it() -> None:
    vault = FakeVaultService()
    await vault.write("Rate Limit Decision", "capped ingest at 100 req/min")

    hits = await vault.search("rate limit")
    assert len(hits) == 1
    assert hits[0].permalink == "rate-limit-decision"


@pytest.mark.anyio
async def test_read_missing_permalink_raises_vault_service_error() -> None:
    vault = FakeVaultService()
    with pytest.raises(VaultServiceError):
        await vault.read("does/not-exist")


@pytest.mark.anyio
async def test_write_duplicate_permalink_raises() -> None:
    vault = FakeVaultService()
    await vault.write("Same Title", "first")
    with pytest.raises(VaultServiceError):
        await vault.write("Same Title", "second")


@pytest.mark.anyio
async def test_edit_replace_and_append() -> None:
    vault = FakeVaultService()
    note = await vault.write("Note", "original")

    replaced = await vault.edit(note.permalink, body="replaced")
    assert replaced.body == "replaced"

    appended = await vault.edit(note.permalink, append="more")
    assert appended.body == "replaced\nmore"


@pytest.mark.anyio
async def test_move_preserves_permalink_and_changes_folder() -> None:
    vault = FakeVaultService()
    note = await vault.write("Note", "body", folder="inbox")

    moved = await vault.move(note.permalink, "archive")
    assert moved.permalink == note.permalink
    assert moved.folder == "archive"


@pytest.mark.anyio
async def test_delete_returns_true_once_then_false() -> None:
    vault = FakeVaultService()
    note = await vault.write("Note", "body")

    assert await vault.delete(note.permalink) is True
    assert await vault.delete(note.permalink) is False


@pytest.mark.anyio
async def test_list_scoped_to_folder() -> None:
    vault = FakeVaultService()
    await vault.write("A", "a", folder="work")
    await vault.write("B", "b", folder="personal")

    work_notes = await vault.list_notes(folder="work")
    assert [n.title for n in work_notes] == ["A"]

    all_notes = await vault.list_notes()
    assert len(all_notes) == 2


@pytest.mark.anyio
async def test_recent_activity_orders_most_recent_first() -> None:
    vault = FakeVaultService()
    first = await vault.write("First", "1")
    await vault.edit(first.permalink, append="2")  # bumps First's modified time
    await vault.write("Second", "2")

    recent = await vault.recent_activity(limit=2)
    assert {n.permalink for n in recent} == {"first", "second"}
