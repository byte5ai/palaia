"""Does an agent use its memory? Per-client counts of lookups and saves.

Issue #524: a session with working memory tools skipped ``recall``
completely, and it only came out because the owner asked afterwards. The
hub sees every memory tool call, so it can say it directly, per client and
per day:

- **lookups**: ``recall``, ``search``, ``read``, ``build_context``, ``list``,
  ``recent_activity``,
- **saves**: ``write``, ``edit``, ``capture``,
- **sessions**: MCP sessions that made at least one of those calls, and how
  many of them **saved before looking anything up**. That last number is
  the signal the issue asks for: an agent that writes without ever reading
  what is already there.

Kept in ``<home>/client_usage.sqlite3`` so the numbers survive a restart
and can be compared across days; rows older than :data:`KEEP_DAYS` are
dropped. Only counts, days and client ids are stored — never a tool's
arguments, a query or note content.

A failure to record never fails the tool call it is counting.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import mcp.types as mt
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult

from ..security.files import harden_sqlite_database

logger = logging.getLogger("palaia_hub.auth.usage")

USAGE_DB_NAME = "client_usage.sqlite3"
#: How long daily rows are kept.
KEEP_DAYS = 90

LOOKUP_ACTIONS = frozenset({"recall", "search", "read", "build_context", "list", "recent_activity"})
SAVE_ACTIONS = frozenset({"write", "edit", "capture"})

Kind = Literal["lookup", "save"]


def classify(action: str) -> Kind | None:
    """``lookup``, ``save``, or ``None`` for everything else (move, delete,
    inbox and review tools, ``memory_status``)."""
    if action in LOOKUP_ACTIONS:
        return "lookup"
    if action in SAVE_ACTIONS:
        return "save"
    return None


def _day(now: float) -> str:
    return datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")


@dataclass
class DayUsage:
    day: str
    lookups: int = 0
    saves: int = 0


@dataclass
class ClientUsage:
    """One client's totals over the requested window, and its days."""

    client_id: str
    lookups: int = 0
    saves: int = 0
    sessions: int = 0
    sessions_saved_first: int = 0
    days: list[DayUsage] = field(default_factory=list)


class ClientUsageStore:
    """Daily lookup/save counts per client id, in SQLite."""

    def __init__(self, home: Path) -> None:
        self.path = Path(home) / USAGE_DB_NAME
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage (
                    client_id            TEXT NOT NULL,
                    day                  TEXT NOT NULL,
                    lookups              INTEGER NOT NULL DEFAULT 0,
                    saves                INTEGER NOT NULL DEFAULT 0,
                    sessions             INTEGER NOT NULL DEFAULT 0,
                    sessions_saved_first INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (client_id, day)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    client_id  TEXT NOT NULL,
                    day        TEXT NOT NULL
                )
                """
            )
        self._pruned_for: str | None = None
        harden_sqlite_database(self.path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
        harden_sqlite_database(self.path)

    def record(
        self,
        client_id: str,
        kind: Kind,
        *,
        session_id: str | None = None,
        now: float | None = None,
    ) -> None:
        """Count one lookup or save. A session seen for the first time counts
        as a session, and as "saved first" when its first counted call is a
        save."""
        day = _day(time.time() if now is None else now)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO usage (client_id, day) VALUES (?, ?)", (client_id, day)
            )
            column = "lookups" if kind == "lookup" else "saves"
            self._conn.execute(
                f"UPDATE usage SET {column} = {column} + 1 WHERE client_id = ? AND day = ?",  # noqa: S608 - fixed column
                (client_id, day),
            )
            if session_id:
                inserted = self._conn.execute(
                    "INSERT OR IGNORE INTO sessions (session_id, client_id, day) VALUES (?, ?, ?)",
                    (session_id, client_id, day),
                ).rowcount
                if inserted:
                    self._conn.execute(
                        "UPDATE usage SET sessions = sessions + 1, "
                        "sessions_saved_first = sessions_saved_first + ? "
                        "WHERE client_id = ? AND day = ?",
                        (1 if kind == "save" else 0, client_id, day),
                    )
            if self._pruned_for != day:
                cutoff = _day((time.time() if now is None else now) - KEEP_DAYS * 86400)
                self._conn.execute("DELETE FROM usage WHERE day < ?", (cutoff,))
                self._conn.execute("DELETE FROM sessions WHERE day < ?", (cutoff,))
                self._pruned_for = day

    def summary(self, *, days: int = 7, now: float | None = None) -> list[ClientUsage]:
        """Every client with any counted call in the last ``days`` days
        (today included), most active first."""
        today = datetime.fromtimestamp(time.time() if now is None else now, UTC).date()
        since = (today - timedelta(days=max(1, days) - 1)).strftime("%Y-%m-%d")
        with self._lock:
            rows = self._conn.execute(
                "SELECT client_id, day, lookups, saves, sessions, sessions_saved_first "
                "FROM usage WHERE day >= ? ORDER BY client_id, day",
                (since,),
            ).fetchall()
        clients: dict[str, ClientUsage] = {}
        for client_id, day, lookups, saves, sessions, saved_first in rows:
            usage = clients.setdefault(client_id, ClientUsage(client_id=client_id))
            usage.lookups += lookups
            usage.saves += saves
            usage.sessions += sessions
            usage.sessions_saved_first += saved_first
            usage.days.append(DayUsage(day=day, lookups=lookups, saves=saves))
        return sorted(clients.values(), key=lambda c: (-(c.lookups + c.saves), c.client_id))


class UsageMiddleware(Middleware):
    """Counts a profile's memory tool calls into a :class:`ClientUsageStore`.

    Args:
        store: where the counts go.
        tool_actions: ``{tool name as the client sees it: base action}`` for
            this profile's vaults (renames included), the same mapping the
            curator guard uses.
    """

    def __init__(self, store: ClientUsageStore, tool_actions: Mapping[str, str]) -> None:
        self._store = store
        self._actions = dict(tool_actions)

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        result = await call_next(context)
        try:
            kind = classify(self._actions.get(context.message.name, ""))
            if kind is not None and not getattr(result, "is_error", False):
                token = get_access_token()
                session_id: str | None = None
                ctx = context.fastmcp_context
                if ctx is not None:
                    try:
                        session_id = ctx.session_id
                    except RuntimeError:
                        session_id = None
                self._store.record(
                    token.client_id if token is not None else "",
                    kind,
                    session_id=session_id,
                )
        except Exception:  # noqa: BLE001 - counting must never fail the call
            logger.exception("could not count a memory tool call")
        return result


def memory_tool_actions(namespaces: Sequence[tuple[str, dict[str, str] | None]]) -> dict[str, str]:
    """``{final tool name: base action}`` for vaults given as
    ``(namespace, tool_renames)`` pairs."""
    from ..gateway.naming import compose_tool_name, resolve_tool_names

    mapping: dict[str, str] = {}
    for namespace, renames in namespaces:
        resolved = resolve_tool_names(namespace, renames)
        for action in LOOKUP_ACTIONS | SAVE_ACTIONS:
            mapping[compose_tool_name(namespace, resolved.get(action, action))] = action
    return mapping


__all__ = [
    "KEEP_DAYS",
    "LOOKUP_ACTIONS",
    "SAVE_ACTIONS",
    "USAGE_DB_NAME",
    "ClientUsage",
    "ClientUsageStore",
    "DayUsage",
    "UsageMiddleware",
    "classify",
    "memory_tool_actions",
]
