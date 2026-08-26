"""The durable delivery outbox (SPEC-201 deliverable #2).

A hub-level SQLite database (one file, not per-vault like
:mod:`palaia_hub.index.db` — a webhook delivery concerns the hub, not one
vault's search index) recording every queued webhook delivery. Enqueuing a
delivery and committing the SQLite row happen before the HTTP call is ever
attempted, so a hub crash or restart between "event happened" and
"delivery succeeded" loses nothing — the row is still ``pending`` on the
next startup and the delivery worker picks it back up (SPEC-201 acceptance:
"restart loses no queued outbox deliveries").

WAL + ``synchronous=NORMAL`` — the same durability posture
:mod:`palaia_hub.index.db` uses for the same reason: durable across a
process crash/restart, which is what this SPEC's acceptance criterion
tests, without paying for the extra fsync ``FULL`` costs against a
crash class (bare-metal power loss) nothing here is verified against.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..security.files import harden_sqlite_database

OUTBOX_RELATIVE_PATH = "hooks_outbox.sqlite3"

DeliveryStatus = str  # "pending" | "delivered" | "dead"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hook_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_name TEXT NOT NULL,
    payload BLOB NOT NULL,
    signature TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    next_attempt_at REAL NOT NULL,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(hook_id, event_id)
);
CREATE INDEX IF NOT EXISTS idx_deliveries_due
    ON deliveries(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_deliveries_hook
    ON deliveries(hook_id, status);
"""


@dataclass(frozen=True, slots=True)
class OutboxRow:
    """One queued/delivered/dead-lettered delivery."""

    id: int
    hook_id: str
    event_id: str
    event_name: str
    payload: bytes
    signature: str
    attempts: int
    status: str
    last_error: str
    created_at: str


def _row_to_outbox_row(row: sqlite3.Row) -> OutboxRow:
    return OutboxRow(
        id=int(row["id"]),
        hook_id=str(row["hook_id"]),
        event_id=str(row["event_id"]),
        event_name=str(row["event_name"]),
        payload=bytes(row["payload"]),
        signature=str(row["signature"]),
        attempts=int(row["attempts"]),
        status=str(row["status"]),
        last_error=str(row["last_error"]),
        created_at=str(row["created_at"]),
    )


class HookOutbox:
    """The durable delivery queue: one connection, one lock, guarded by WAL."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        # SPEC-502: queued payloads carry the event bodies a webhook will
        # receive, and each row's signature is computed from a hook secret.
        # Owner-only, write-ahead siblings included.
        harden_sqlite_database(self.path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
        harden_sqlite_database(self.path)

    # ------------------------------------------------------------- mutations

    def enqueue(
        self,
        *,
        hook_id: str,
        event_id: str,
        event_name: str,
        payload: bytes,
        signature: str,
    ) -> None:
        """Queue one delivery. Idempotent per ``(hook_id, event_id)``: enqueuing
        the same event for the same hook twice (e.g. a subscriber re-notified
        after a restart) is a no-op, not a duplicate delivery."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO deliveries "
                "(hook_id, event_id, event_name, payload, signature, next_attempt_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(hook_id, event_id) DO NOTHING",
                (hook_id, event_id, event_name, payload, signature, time.time(), _now_iso()),
            )
            self._conn.commit()

    def claim_due(self, *, limit: int = 20) -> list[OutboxRow]:
        """Rows ready to attempt now, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM deliveries WHERE status = 'pending' AND next_attempt_at <= ? "
                "ORDER BY id LIMIT ?",
                (time.time(), limit),
            ).fetchall()
        return [_row_to_outbox_row(row) for row in rows]

    def mark_delivered(self, row_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE deliveries SET status = 'delivered', last_error = '' WHERE id = ?",
                (row_id,),
            )
            self._conn.commit()

    def mark_retry(self, row_id: int, *, delay_seconds: float, error: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE deliveries SET attempts = attempts + 1, "
                "next_attempt_at = ?, last_error = ? WHERE id = ?",
                (time.time() + delay_seconds, error, row_id),
            )
            self._conn.commit()

    def mark_dead(self, row_id: int, *, error: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE deliveries SET attempts = attempts + 1, "
                "status = 'dead', last_error = ? WHERE id = ?",
                (error, row_id),
            )
            self._conn.commit()

    # ----------------------------------------------------------------- queries

    def list_dead_letters(self, hook_id: str | None = None) -> list[OutboxRow]:
        with self._lock:
            if hook_id is None:
                rows = self._conn.execute(
                    "SELECT * FROM deliveries WHERE status = 'dead' ORDER BY id"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM deliveries WHERE status = 'dead' AND hook_id = ? ORDER BY id",
                    (hook_id,),
                ).fetchall()
        return [_row_to_outbox_row(row) for row in rows]

    def count_pending(self, hook_id: str | None = None) -> int:
        with self._lock:
            if hook_id is None:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM deliveries WHERE status = 'pending'"
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM deliveries WHERE status = 'pending' AND hook_id = ?",
                    (hook_id,),
                ).fetchone()
        return int(row["n"])

    def all_rows(self) -> Sequence[OutboxRow]:
        """Every row regardless of status — test/debug helper."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM deliveries ORDER BY id").fetchall()
        return [_row_to_outbox_row(row) for row in rows]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = ["OUTBOX_RELATIVE_PATH", "HookOutbox", "OutboxRow"]
