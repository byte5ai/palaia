"""SPEC-303 deliverable #3: manual entries — the third source."""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.market.manual import ManualEntryError, ManualEntryStore
from palaia_hub.market.models import ManualEntryCreate, SourceLocator


def _payload(entry_id: str = "manual.tool") -> ManualEntryCreate:
    return ManualEntryCreate(
        id=entry_id,
        name="Manual Tool",
        one_liner="Something someone typed in by hand.",
        kind="remote",
        source=SourceLocator(type="url", value="https://example.com/mcp"),
        maintainer="someone",
    )


def test_added_entry_is_always_unverified_and_manual_provenance(tmp_path: Path) -> None:
    store = ManualEntryStore(tmp_path / "manual.sqlite3")
    entry = store.add(_payload())

    assert entry.verified is False
    assert entry.provenance == "manual"
    assert entry.id == "manual.tool"


def test_a_duplicate_id_is_rejected(tmp_path: Path) -> None:
    store = ManualEntryStore(tmp_path / "manual.sqlite3")
    store.add(_payload())
    with pytest.raises(ManualEntryError):
        store.add(_payload())


def test_list_and_get_round_trip(tmp_path: Path) -> None:
    store = ManualEntryStore(tmp_path / "manual.sqlite3")
    store.add(_payload("a"))
    store.add(_payload("b"))

    assert {e.id for e in store.list()} == {"a", "b"}
    assert store.get("a") is not None
    assert store.get("missing") is None


def test_entries_persist_across_store_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "manual.sqlite3"
    ManualEntryStore(db_path).add(_payload())

    reopened = ManualEntryStore(db_path)
    assert reopened.get("manual.tool") is not None
