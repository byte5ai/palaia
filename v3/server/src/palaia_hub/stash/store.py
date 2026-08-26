"""SQLite-backed store for the stash tool family (SPEC-202).

Deliverable #1: a hub-level cache, deliberately separate from the vault
(knowledge) and index (search) stores — see the package docstring. One
SQLite file, namespaced keys, JSON values, per-entry TTL with a
stale-then-hard-expiry two-stage lifecycle, a per-entry size limit, a total
size budget enforced by LRU eviction, and created/updated/accessed
metadata on every entry.

**Stale vs. hard expiry.** An entry has two clocks: ``stale_after_seconds``
(optional) marks it stale but still readable — :meth:`get` still returns it,
with ``stale=True``, so a caller can decide whether "old but present" is
still useful. ``ttl_seconds`` is the hard expiry: once passed, the entry is
gone as far as any caller is concerned (:meth:`get` acts as if it never
existed), whether or not the row has actually been deleted from disk yet
(hard-expired rows are deleted lazily, on the next access or sweep, rather
than needing a background task).

**Budget eviction.** ``total_budget_bytes`` bounds the store's total
``size_bytes`` across all entries. A :meth:`set` that would push the total
over budget evicts least-recently-*accessed* entries first (LRU by
``accessed_at``) until it fits — the entry currently being written is never
a candidate (excluded from the eviction query by key), even when it is
itself the largest entry in the namespace.

**Clock-injectable.** Every method that needs "now" takes an optional
``now`` override (else the store's own ``clock`` callable, itself defaulting
to :func:`time.time`) so tests can assert exact TTL/staleness edges without
sleeping.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..security.files import harden_sqlite_database
from .models import StashEntry, StashError

#: Default per-entry size limit (bytes of the JSON-encoded value).
DEFAULT_ENTRY_LIMIT_BYTES = 256 * 1024
#: Default total budget across every namespace.
DEFAULT_TOTAL_BUDGET_BYTES = 64 * 1024 * 1024

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stash_entries (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    accessed_at REAL NOT NULL,
    expires_at REAL,
    stale_at REAL,
    size_bytes INTEGER NOT NULL,
    PRIMARY KEY (namespace, key)
);
CREATE INDEX IF NOT EXISTS idx_stash_accessed_at ON stash_entries(accessed_at);
CREATE INDEX IF NOT EXISTS idx_stash_expires_at ON stash_entries(expires_at);
"""


def _row_to_entry(row: sqlite3.Row, *, now: float) -> StashEntry:
    expires_at = row["expires_at"]
    stale_at = row["stale_at"]
    return StashEntry(
        namespace=row["namespace"],
        key=row["key"],
        value=json.loads(row["value_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        accessed_at=row["accessed_at"],
        expires_at=expires_at,
        stale_at=stale_at,
        stale=stale_at is not None and now >= stale_at,
        size_bytes=row["size_bytes"],
    )


class StashStore:
    """One hub-wide stash: connection, schema, lock, eviction.

    Follows :class:`palaia_hub.index.db.IndexDatabase`'s pattern (one
    connection, ``check_same_thread=False``, one lock guarding every
    statement) — the stash is touched from the event loop via
    ``asyncio.to_thread`` and is not a contended OLTP database.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        entry_limit_bytes: int = DEFAULT_ENTRY_LIMIT_BYTES,
        total_budget_bytes: int = DEFAULT_TOTAL_BUDGET_BYTES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path)
        self.entry_limit_bytes = entry_limit_bytes
        self.total_budget_bytes = total_budget_bytes
        self.clock = clock
        self._lock = threading.Lock()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        # SPEC-502: stash entries are hand-off payloads between agents —
        # nothing about them is public. The database and its write-ahead
        # siblings stay readable only by the account running the hub.
        harden_sqlite_database(self.path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
        harden_sqlite_database(self.path)

    # -- helpers -------------------------------------------------------

    def _now(self, now: float | None) -> float:
        return now if now is not None else self.clock()

    def _purge_hard_expired_locked(self, now: float) -> None:
        self._conn.execute(
            "DELETE FROM stash_entries WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,)
        )

    def _total_bytes_locked(self) -> int:
        row = self._conn.execute("SELECT COALESCE(SUM(size_bytes), 0) AS total FROM stash_entries")
        return int(row.fetchone()["total"])

    def _evict_lru_locked(
        self, *, needed_bytes: int, protect_namespace: str, protect_key: str
    ) -> list[str]:
        """Evict least-recently-accessed entries (excluding the one being
        written) until ``needed_bytes`` more fits within the total budget.
        Returns the ``"namespace/key"`` labels of everything evicted.
        """
        evicted: list[str] = []
        total = self._total_bytes_locked()
        if total + needed_bytes <= self.total_budget_bytes:
            return evicted
        cursor = self._conn.execute(
            "SELECT namespace, key, size_bytes FROM stash_entries "
            "WHERE NOT (namespace = ? AND key = ?) ORDER BY accessed_at ASC",
            (protect_namespace, protect_key),
        )
        for row in cursor:
            if total + needed_bytes <= self.total_budget_bytes:
                break
            self._conn.execute(
                "DELETE FROM stash_entries WHERE namespace = ? AND key = ?",
                (row["namespace"], row["key"]),
            )
            total -= row["size_bytes"]
            evicted.append(f"{row['namespace']}/{row['key']}")
        return evicted

    # -- public API ------------------------------------------------------

    def set(
        self,
        namespace: str,
        key: str,
        value: Any,
        *,
        ttl_seconds: float | None = None,
        stale_after_seconds: float | None = None,
        now: float | None = None,
    ) -> tuple[int, list[str]]:
        """Write ``value`` under ``namespace``/``key``.

        Raises :class:`StashError` if the JSON-encoded value exceeds
        ``entry_limit_bytes``. Returns ``(size_bytes, evicted_labels)``.
        """
        current = self._now(now)
        encoded = json.dumps(value)
        size_bytes = len(encoded.encode("utf-8"))
        if size_bytes > self.entry_limit_bytes:
            raise StashError(
                f"value for {namespace}/{key} is {size_bytes} bytes, over the "
                f"{self.entry_limit_bytes}-byte per-entry limit"
            )
        # No pre-check against `total_budget_bytes` here: eviction (below)
        # frees whatever it can and the entry being written is never a
        # candidate, so a value that alone exceeds the total budget still
        # gets written — the budget is a best-effort LRU-eviction target,
        # not a hard admission gate that could otherwise reject an
        # overwrite of the store's only (or largest) entry.
        expires_at = current + ttl_seconds if ttl_seconds is not None else None
        stale_at = current + stale_after_seconds if stale_after_seconds is not None else None
        with self._lock:
            self._purge_hard_expired_locked(current)
            existing = self._conn.execute(
                "SELECT size_bytes, created_at FROM stash_entries WHERE namespace = ? AND key = ?",
                (namespace, key),
            ).fetchone()
            existing_size = existing["size_bytes"] if existing is not None else 0
            created_at = existing["created_at"] if existing is not None else current
            net_new_bytes = max(0, size_bytes - existing_size)
            evicted = self._evict_lru_locked(
                needed_bytes=net_new_bytes, protect_namespace=namespace, protect_key=key
            )
            self._conn.execute(
                "INSERT INTO stash_entries "
                "(namespace, key, value_json, created_at, updated_at, accessed_at, "
                " expires_at, stale_at, size_bytes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(namespace, key) DO UPDATE SET "
                "value_json=excluded.value_json, updated_at=excluded.updated_at, "
                "accessed_at=excluded.accessed_at, expires_at=excluded.expires_at, "
                "stale_at=excluded.stale_at, size_bytes=excluded.size_bytes",
                (
                    namespace,
                    key,
                    encoded,
                    created_at,
                    current,
                    current,
                    expires_at,
                    stale_at,
                    size_bytes,
                ),
            )
            self._conn.commit()
        return size_bytes, evicted

    def get(self, namespace: str, key: str, *, now: float | None = None) -> StashEntry | None:
        """Read one entry, bumping its ``accessed_at``. ``None`` if absent
        or hard-expired (see class docstring)."""
        current = self._now(now)
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM stash_entries WHERE namespace = ? AND key = ?", (namespace, key)
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] is not None and current >= row["expires_at"]:
                self._conn.execute(
                    "DELETE FROM stash_entries WHERE namespace = ? AND key = ?", (namespace, key)
                )
                self._conn.commit()
                return None
            self._conn.execute(
                "UPDATE stash_entries SET accessed_at = ? WHERE namespace = ? AND key = ?",
                (current, namespace, key),
            )
            self._conn.commit()
            entry = _row_to_entry(row, now=current)
            return entry.model_copy(update={"accessed_at": current})

    def delete(self, namespace: str, key: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM stash_entries WHERE namespace = ? AND key = ?", (namespace, key)
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def list(self, namespace: str, *, now: float | None = None) -> list[StashEntry]:
        """All non-hard-expired entries in ``namespace``, most recently
        updated first. Does not bump ``accessed_at`` (listing is not a
        read of any particular entry's value)."""
        current = self._now(now)
        with self._lock:
            self._purge_hard_expired_locked(current)
            self._conn.commit()
            rows = self._conn.execute(
                "SELECT * FROM stash_entries WHERE namespace = ? ORDER BY updated_at DESC",
                (namespace,),
            ).fetchall()
            return [_row_to_entry(row, now=current) for row in rows]

    def status(self, *, now: float | None = None) -> tuple[int, int, dict[str, int]]:
        """``(total_entries, total_bytes, {namespace: count})`` after
        purging hard-expired rows."""
        current = self._now(now)
        with self._lock:
            self._purge_hard_expired_locked(current)
            self._conn.commit()
            total_row = self._conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS total FROM stash_entries"
            ).fetchone()
            namespace_rows = self._conn.execute(
                "SELECT namespace, COUNT(*) AS n FROM stash_entries GROUP BY namespace"
            ).fetchall()
            namespaces = {row["namespace"]: row["n"] for row in namespace_rows}
            return int(total_row["n"]), int(total_row["total"]), namespaces


__all__ = ["DEFAULT_ENTRY_LIMIT_BYTES", "DEFAULT_TOTAL_BUDGET_BYTES", "StashStore"]
