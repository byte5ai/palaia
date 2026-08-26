"""Manual marketplace entries (SPEC-303 deliverable #3): the third source.

A REST-created entry, same :class:`~palaia_hub.market.models.MarketEntry`
shape as the other two sources, always ``verified=False`` and
``provenance="manual"`` — a human typed this in, palaia never vouches for
it. Stored in a small SQLite table, one row per entry, mirroring the
style of :mod:`palaia_hub.stash.store`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from ..config import palaia_home
from ..security.files import harden_sqlite_database
from .models import ManualEntryCreate, MarketEntry, SourceLocator

DB_RELATIVE_PATH = "market_manual.sqlite3"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS manual_entries (
    id TEXT PRIMARY KEY,
    entry_json TEXT NOT NULL
);
"""


class ManualEntryError(RuntimeError):
    """A manual-entry request was rejected (e.g. a duplicate id)."""


def _row_to_entry(entry_json: str) -> MarketEntry:
    raw = json.loads(entry_json)
    return MarketEntry(
        id=raw["id"],
        name=raw["name"],
        one_liner=raw["one_liner"],
        kind=raw["kind"],
        source=SourceLocator(**raw["source"]),
        config_schema=raw.get("config_schema"),
        permissions=list(raw.get("permissions", [])),
        maintainer=raw["maintainer"],
        verified=False,
        provenance="manual",
    )


class ManualEntryStore:
    """SQLite-backed CRUD for the manual source."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (palaia_home() / DB_RELATIVE_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA_SQL)
            self._conn.commit()
        # SPEC-502: a manually added entry names an internal server and the
        # locator to reach it. Owner-only, siblings included.
        harden_sqlite_database(self.db_path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
        harden_sqlite_database(self.db_path)

    def add(self, payload: ManualEntryCreate) -> MarketEntry:
        entry_dict = payload.model_dump(mode="json")
        with self._lock:
            existing = self._conn.execute(
                "SELECT 1 FROM manual_entries WHERE id = ?", (payload.id,)
            ).fetchone()
            if existing is not None:
                raise ManualEntryError(f"a manual entry with id {payload.id!r} already exists")
            self._conn.execute(
                "INSERT INTO manual_entries (id, entry_json) VALUES (?, ?)",
                (payload.id, json.dumps(entry_dict)),
            )
            self._conn.commit()
        return _row_to_entry(json.dumps(entry_dict))

    def get(self, entry_id: str) -> MarketEntry | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT entry_json FROM manual_entries WHERE id = ?", (entry_id,)
            ).fetchone()
        return _row_to_entry(row["entry_json"]) if row is not None else None

    def list(self) -> list[MarketEntry]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT entry_json FROM manual_entries ORDER BY id"
            ).fetchall()
        return [_row_to_entry(row["entry_json"]) for row in rows]


__all__ = ["DB_RELATIVE_PATH", "ManualEntryError", "ManualEntryStore"]
