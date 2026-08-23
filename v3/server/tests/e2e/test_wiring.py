"""Unit tests for :class:`~palaia_hub.gateway.wiring.EngineVaultService`.

Not a scenario — a focused check that the adapter's translation of every
:class:`~palaia_hub.gateway.vault_protocol.VaultService` method onto a real
:class:`~palaia_hub.vault.VaultEngine` behaves like the fake one the memory
tool family was originally tested against, so SPEC-105's existing
``test_memory_tools.py``-style expectations still hold once the real vault
is behind the tools.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.gateway.vault_protocol import VaultServiceError
from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.vault import VaultEngine

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def service(tmp_path: Path) -> EngineVaultService:
    engine = VaultEngine(tmp_path / "work", "work")
    await engine.open(purpose="test vault")
    return EngineVaultService(engine)


async def test_write_then_read_round_trips(service: EngineVaultService) -> None:
    note = await service.write("My First Note", "hello world", folder="notes", tags=["a", "b"])
    assert note.permalink == "notes/my-first-note"
    assert note.folder == "notes"
    assert note.tags == ["a", "b"]

    read_back = await service.read(note.permalink)
    assert read_back.body.strip() == "hello world"
    assert read_back.title == "My First Note"


async def test_write_duplicate_title_in_same_folder_raises_service_error(
    service: EngineVaultService,
) -> None:
    await service.write("Dup", "one")
    with pytest.raises(VaultServiceError):
        await service.write("Dup", "two")


async def test_edit_replace_and_append(service: EngineVaultService) -> None:
    note = await service.write("Editable", "line one")
    replaced = await service.edit(note.permalink, body="new body")
    assert replaced.body.strip() == "new body"
    appended = await service.edit(note.permalink, append="line two")
    assert appended.body.strip() == "new body\nline two"


async def test_edit_updates_tags(service: EngineVaultService) -> None:
    note = await service.write("Tagged", "body", tags=["x"])
    updated = await service.edit(note.permalink, tags=["y", "z"])
    assert updated.tags == ["y", "z"]


async def test_move_preserves_permalink(service: EngineVaultService) -> None:
    note = await service.write("Movable", "body", folder="a")
    moved = await service.move(note.permalink, "b")
    assert moved.permalink == note.permalink
    assert moved.folder == "b"


async def test_delete_returns_true_then_false(service: EngineVaultService) -> None:
    note = await service.write("Deletable", "body")
    assert await service.delete(note.permalink) is True
    assert await service.delete(note.permalink) is False


async def test_list_notes_scoped_to_folder(service: EngineVaultService) -> None:
    await service.write("In A", "body", folder="a")
    await service.write("In B", "body", folder="b")
    only_a = await service.list_notes(folder="a")
    assert [n.permalink for n in only_a] == ["a/in-a"]
    everything = await service.list_notes()
    assert {n.permalink for n in everything} == {"a/in-a", "b/in-b"}


async def test_recent_activity_orders_most_recent_first(service: EngineVaultService) -> None:
    await service.write("Older", "body")
    await service.write("Newer", "body")
    recent = await service.recent_activity(limit=2)
    assert [n.title for n in recent] == ["Newer", "Older"]


async def test_read_missing_permalink_raises_service_error(service: EngineVaultService) -> None:
    with pytest.raises(VaultServiceError):
        await service.read("does/not-exist")


async def test_search_finds_body_text(service: EngineVaultService) -> None:
    await service.write("Findable", "a distinctive phrase lives here")
    hits = await service.search("distinctive phrase")
    assert [h.permalink for h in hits] == ["findable"]
