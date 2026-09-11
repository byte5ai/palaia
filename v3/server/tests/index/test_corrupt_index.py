"""Issue #337: a corrupt or truncated index file must not stop the hub.

The index is derived data and rebuildable by design; ``IndexDatabase.open``
already promised to drop and recreate a file it cannot read. But the first
statements on a fresh connection (the ``PRAGMA`` setup) ran outside the
probe that made that promise, so a garbage file raised ``sqlite3.DatabaseError:
file is not a database`` straight out of ``VaultIndex.open()`` — and out of
the hub's startup with it. Power loss or a full disk truncating
``index.sqlite3`` then kept the hub down until someone deleted the file by
hand.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from palaia_hub.index.db import IndexDatabase

pytestmark = pytest.mark.anyio


def _index_path(vault_root: Path) -> Path:
    path = vault_root / ".palaia" / "index.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


async def test_a_garbage_index_file_is_dropped_and_rebuilt_on_open(
    golden_work_vault: Path, open_index: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="palaia_hub.index.db")
    path = _index_path(golden_work_vault)
    path.write_bytes(b"this is not a database, this is what a full disk left behind\n" * 20)
    # A stale write-ahead sibling from the previous life of the file.
    path.with_name(path.name + "-wal").write_bytes(b"\x00" * 64)

    _, index = await open_index(golden_work_vault)

    assert index.status().notes > 0
    hits = await index.search("gateway", mode="fts", limit=3)
    assert hits.hits, "the rebuilt index must answer queries"
    assert "dropped and recreated" in caplog.text
    assert "unreadable database" in caplog.text
    # The file is a real database now, siblings included.
    assert sqlite3.connect(path).execute("PRAGMA schema_version").fetchone() is not None


async def test_a_truncated_index_file_is_dropped_and_rebuilt_on_open(
    golden_work_vault: Path, open_index: Any
) -> None:
    """Not garbage — the first bytes of a real database, cut off mid-file,
    which is what a crash during a write leaves behind."""
    path = _index_path(golden_work_vault)
    _, first = await open_index(golden_work_vault)
    notes_before = first.status().notes
    await first.close()
    whole = path.read_bytes()
    assert len(whole) > 4096
    path.write_bytes(whole[:3000])
    for suffix in ("-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)

    _, index = await open_index(golden_work_vault)

    assert index.status().notes == notes_before


def test_the_database_layer_reports_garbage_instead_of_raising(tmp_path: Path) -> None:
    """The unit underneath: ``open()`` on garbage returns a working, empty
    schema rather than propagating ``DatabaseError``."""
    path = tmp_path / "index.sqlite3"
    path.write_bytes(b"\xff\xfe garbage \x00" * 100)
    db = IndexDatabase(path, "work")

    db.open()  # used to raise sqlite3.DatabaseError: file is not a database

    assert db.opened
    tables = {
        str(row["name"])
        for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"notes", "chunks", "meta"} <= tables
    db.close()
