"""The notification store: a small, durable SQLite log backing the
dashboard's notification bell (SPEC-307 deliverable #1).

Same WAL posture as :mod:`palaia_hub.hooks.outbox` /
:mod:`palaia_hub.automations.outbox` for the same reason: a notification
must survive a hub restart between "the automation fired" and "the person
opened the dashboard next". Capped at :data:`MAX_NOTIFICATIONS` — a
notification center is a recent-activity feed, not an archive; the oldest
entries are trimmed on insert once the cap is exceeded.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from .models import NotificationRecord

NOTIFICATIONS_RELATIVE_PATH = "notifications.sqlite3"

#: A notification center is a recent-activity feed, not an archive.
MAX_NOTIFICATIONS = 500

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    read INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read);
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _row_to_record(row: sqlite3.Row) -> NotificationRecord:
    return NotificationRecord(
        id=int(row["id"]),
        title=str(row["title"]),
        body=str(row["body"]),
        source=str(row["source"]),
        created_at=str(row["created_at"]),
        read=bool(row["read"]),
    )


class NotificationStore:
    """Create, list, mark-read, and count notifications."""

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

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create(self, *, title: str, body: str = "", source: str = "") -> NotificationRecord:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO notifications (title, body, source, created_at) "
                "VALUES (?, ?, ?, ?)",
                (title, body, source, _now_iso()),
            )
            self._conn.execute(
                "DELETE FROM notifications WHERE id IN ("
                "SELECT id FROM notifications ORDER BY id DESC "
                "LIMIT -1 OFFSET ?)",
                (MAX_NOTIFICATIONS,),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM notifications WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return _row_to_record(row)

    def list(self, *, unread_only: bool = False, limit: int = 100) -> list[NotificationRecord]:
        with self._lock:
            if unread_only:
                rows = self._conn.execute(
                    "SELECT * FROM notifications WHERE read = 0 ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [_row_to_record(row) for row in rows]

    def unread_count(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM notifications WHERE read = 0"
            ).fetchone()
        return int(row["n"])

    def mark_read(self, notification_id: int) -> NotificationRecord | None:
        with self._lock:
            self._conn.execute(
                "UPDATE notifications SET read = 1 WHERE id = ?", (notification_id,)
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM notifications WHERE id = ?", (notification_id,)
            ).fetchone()
        return _row_to_record(row) if row is not None else None

    def mark_all_read(self) -> None:
        with self._lock:
            self._conn.execute("UPDATE notifications SET read = 1 WHERE read = 0")
            self._conn.commit()


__all__ = ["MAX_NOTIFICATIONS", "NOTIFICATIONS_RELATIVE_PATH", "NotificationStore"]
