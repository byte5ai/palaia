"""SQLite connection management for the per-vault index.

Three things worth knowing before editing this module:

* **WAL**, so a reader (a search) never blocks on the writer (an incremental
  update), which is the whole point of an index that must answer queries
  while an embed backlog drains behind it.
* **One connection, one lock.** The index is touched from the event loop, from
  ``asyncio.to_thread`` workers, and from the doctor's reindex thread. Rather
  than a connection pool with per-thread affinity, there is a single
  connection created with ``check_same_thread=False`` and every statement
  runs under :attr:`IndexDatabase.lock`. SQLite serializes writes anyway, and
  a vault index is not a contended OLTP database.
* **Drop, don't migrate.** The index is disposable (format spec §10). A schema
  version mismatch deletes the file and lets the caller reindex, which is
  both simpler and better tested than an ALTER TABLE path nobody exercises.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from .schema import (
    META_SCHEMA_VERSION,
    META_VAULT,
    SCHEMA_SQL,
    SCHEMA_VERSION,
    VEC_TABLE_SQL,
)

logger = logging.getLogger("palaia_hub.index.db")

#: Where a vault's index lives: inside the engine-private, gitignored,
#: rebuildable ``.palaia/`` directory (format spec §1).
INDEX_RELATIVE_PATH = ".palaia/index.sqlite3"


class VectorSupport:
    """Whether sqlite-vec could be loaded, and why not when it could not."""

    __slots__ = ("available", "reason")

    def __init__(self, available: bool, reason: str = "") -> None:
        self.available = available
        self.reason = reason


def _load_sqlite_vec(conn: sqlite3.Connection) -> VectorSupport:
    try:
        import sqlite_vec
    except ImportError as exc:  # pragma: no cover - dependency is declared
        return VectorSupport(False, f"sqlite-vec is not installed ({exc})")
    if not hasattr(conn, "enable_load_extension"):  # pragma: no cover - stdlib build
        return VectorSupport(
            False,
            "this Python's sqlite3 was built without extension loading, so "
            "sqlite-vec cannot be loaded; search stays FTS-only",
        )
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
    except sqlite3.Error as exc:  # pragma: no cover - platform dependent
        return VectorSupport(False, f"sqlite-vec failed to load ({exc})")
    finally:
        try:
            conn.enable_load_extension(False)
        except (AttributeError, sqlite3.Error):  # pragma: no cover
            pass
    return VectorSupport(True)


class IndexDatabase:
    """One vault's index file: connection, schema, and the guarding lock."""

    def __init__(self, path: Path, vault: str) -> None:
        self.path = Path(path)
        self.vault = vault
        self.lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self.vectors = VectorSupport(False, "not opened yet")

    # ------------------------------------------------------------- lifecycle

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("index database is not open — call open() first")
        return self._conn

    @property
    def opened(self) -> bool:
        return self._conn is not None

    def open(self) -> None:
        """Open (creating or rebuilding) the index database."""
        if self._conn is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rebuilt = self._open_once()
        if rebuilt is not None:
            # Version mismatch or a corrupt file: the index is disposable, so
            # throw it away rather than trying to salvage it.
            logger.info("index at %s dropped and recreated: %s", self.path, rebuilt)
            self._close_conn()
            self.path.unlink(missing_ok=True)
            for suffix in ("-wal", "-shm"):
                self.path.with_name(self.path.name + suffix).unlink(missing_ok=True)
            self._open_once(force_create=True)

    def _open_once(self, *, force_create: bool = False) -> str | None:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        self._conn = conn
        self.vectors = _load_sqlite_vec(conn)
        if self.vectors.available:
            logger.debug("sqlite-vec loaded for index %s", self.path)
        else:
            logger.info("vector search unavailable for %s: %s", self.path, self.vectors.reason)

        try:
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            return f"unreadable database ({exc})"

        if existing is None or force_create:
            self._create_schema()
            return None

        version = self.meta_get(META_SCHEMA_VERSION)
        if version != str(SCHEMA_VERSION):
            return f"schema version {version!r} != {SCHEMA_VERSION}"
        return None

    def _create_schema(self) -> None:
        with self.lock:
            self.conn.executescript(SCHEMA_SQL)
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                (META_SCHEMA_VERSION, str(SCHEMA_VERSION)),
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                (META_VAULT, self.vault),
            )
            self.conn.commit()

    def _close_conn(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:  # pragma: no cover
                pass
            self._conn = None

    def close(self) -> None:
        """Close the connection (the file stays; it is rebuildable anyway)."""
        with self.lock:
            self._close_conn()

    # ------------------------------------------------------------------- meta

    def meta_get(self, key: str) -> str | None:
        with self.lock:
            row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def meta_set(self, key: str, value: str) -> None:
        """Set one metadata key, committing immediately.

        Committing matters: an uncommitted write leaves sqlite3's implicit
        transaction open, and the next ``BEGIN IMMEDIATE`` a rebuild issues
        would then fail with "cannot start a transaction within a transaction".
        """
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value)
            )
            self.conn.commit()

    # -------------------------------------------------------------- vec table

    def has_vec_table(self) -> bool:
        with self.lock:
            row = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE name='vec_chunks'"
            ).fetchone()
        return row is not None

    def ensure_vec_table(self, dim: int) -> bool:
        """Create the KNN table for ``dim``-dimensional vectors if needed.

        Returns ``True`` when a table exists afterwards. A dimension change
        (a different embedding model) drops the old table — vectors from
        another model are not comparable, and they are rebuildable.
        """
        if not self.vectors.available:
            return False
        with self.lock:
            current = self.meta_get("vec_dim")
            if self.has_vec_table() and current == str(dim):
                return True
            if self.has_vec_table():
                logger.info("embedding dimension changed %s -> %s; dropping vectors", current, dim)
                self.conn.execute("DROP TABLE vec_chunks")
                self.conn.execute("UPDATE chunks SET state='pending', attempts=0")
            self.conn.execute(VEC_TABLE_SQL.format(dim=dim))
            self.meta_set("vec_dim", str(dim))
            self.conn.commit()
        return True


__all__ = ["INDEX_RELATIVE_PATH", "IndexDatabase", "VectorSupport"]
