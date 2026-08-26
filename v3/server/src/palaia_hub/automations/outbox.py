"""The durable delivery log (SPEC-307 deliverable #1: "same outbox/delivery
discipline" as :mod:`palaia_hub.hooks.outbox` — durable, retried, never
blocking the bus).

One hub-level SQLite database, same WAL + ``synchronous=NORMAL`` posture as
:class:`palaia_hub.hooks.outbox.HookOutbox` and the same reasoning: a
delivery row commits before any action is attempted, so a crash between
"event matched" and "action executed" loses nothing — the row is still
``pending`` on the next startup.

Unlike the hooks outbox, a row here does not carry a signature (no action
kind signs anything) — instead it carries the *rendered* action payload
(the templated fields, already substituted), so a retry replays exactly
what was decided at match time rather than re-rendering against
whatever the envelope's data might be by then (there is no re-read of the
original envelope on retry).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..security.files import harden_sqlite_database

OUTBOX_RELATIVE_PATH = "automations_outbox.sqlite3"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    automation_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_name TEXT NOT NULL,
    action_kind TEXT NOT NULL,
    rendered_action TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    next_attempt_at REAL NOT NULL,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    test INTEGER NOT NULL DEFAULT 0,
    UNIQUE(automation_id, event_id)
);
CREATE INDEX IF NOT EXISTS idx_automation_deliveries_due
    ON deliveries(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_automation_deliveries_automation
    ON deliveries(automation_id, status);
"""


@dataclass(frozen=True, slots=True)
class DeliveryRow:
    """One queued/delivered/dead/test-fired delivery."""

    id: int
    automation_id: str
    event_id: str
    event_name: str
    action_kind: str
    rendered_action: dict[str, Any]
    attempts: int
    status: str
    last_error: str
    created_at: str
    test: bool


def _row_to_delivery(row: sqlite3.Row) -> DeliveryRow:
    return DeliveryRow(
        id=int(row["id"]),
        automation_id=str(row["automation_id"]),
        event_id=str(row["event_id"]),
        event_name=str(row["event_name"]),
        action_kind=str(row["action_kind"]),
        rendered_action=json.loads(row["rendered_action"]),
        attempts=int(row["attempts"]),
        status=str(row["status"]),
        last_error=str(row["last_error"]),
        created_at=str(row["created_at"]),
        test=bool(row["test"]),
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class AutomationOutbox:
    """The durable delivery queue + log: one connection, one lock, WAL."""

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
        # SPEC-502: same reasoning as the hooks outbox — queued rows hold
        # rendered action payloads. Owner-only, siblings included.
        harden_sqlite_database(self.path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
        harden_sqlite_database(self.path)

    # ------------------------------------------------------------- mutations

    def enqueue(
        self,
        *,
        automation_id: str,
        event_id: str,
        event_name: str,
        action_kind: str,
        rendered_action: dict[str, Any],
    ) -> None:
        """Queue one pending delivery. Idempotent per ``(automation_id, event_id)``."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO deliveries "
                "(automation_id, event_id, event_name, action_kind, rendered_action, "
                "next_attempt_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(automation_id, event_id) DO NOTHING",
                (
                    automation_id,
                    event_id,
                    event_name,
                    action_kind,
                    json.dumps(rendered_action),
                    time.time(),
                    _now_iso(),
                ),
            )
            self._conn.commit()

    def record_resolved(
        self,
        *,
        automation_id: str,
        event_id: str,
        event_name: str,
        action_kind: str,
        rendered_action: dict[str, Any],
        status: str,
        last_error: str,
        test: bool,
    ) -> DeliveryRow:
        """Insert one already-resolved row (used by test-fire, which runs
        synchronously rather than going through the pending queue)."""
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO deliveries "
                "(automation_id, event_id, event_name, action_kind, rendered_action, "
                "attempts, status, next_attempt_at, last_error, created_at, test) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
                (
                    automation_id,
                    event_id,
                    event_name,
                    action_kind,
                    json.dumps(rendered_action),
                    status,
                    time.time(),
                    last_error,
                    _now_iso(),
                    1 if test else 0,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM deliveries WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return _row_to_delivery(row)

    def claim_due(self, *, limit: int = 20) -> list[DeliveryRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM deliveries WHERE status = 'pending' AND next_attempt_at <= ? "
                "ORDER BY id LIMIT ?",
                (time.time(), limit),
            ).fetchall()
        return [_row_to_delivery(row) for row in rows]

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

    def list_for_automation(self, automation_id: str) -> list[DeliveryRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM deliveries WHERE automation_id = ? ORDER BY id DESC",
                (automation_id,),
            ).fetchall()
        return [_row_to_delivery(row) for row in rows]

    def count_pending(self, automation_id: str | None = None) -> int:
        with self._lock:
            if automation_id is None:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM deliveries WHERE status = 'pending'"
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM deliveries WHERE status = 'pending' "
                    "AND automation_id = ?",
                    (automation_id,),
                ).fetchone()
        return int(row["n"])

    def all_rows(self) -> Sequence[DeliveryRow]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM deliveries ORDER BY id").fetchall()
        return [_row_to_delivery(row) for row in rows]


__all__ = ["OUTBOX_RELATIVE_PATH", "AutomationOutbox", "DeliveryRow"]
