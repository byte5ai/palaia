"""SQLite-backed store for the session directory (SPEC-402).

Deliverable #1: a hub-level registry of connected agent sessions —
deliberately separate from the vault, the index, and the stash (the
three-stores-plus-directory lesson: a session row is presence/liveness
metadata, never knowledge or cache content). One SQLite file, one row per
registered session.

**Handle vs. secret.** :meth:`register` mints two different strings:

- ``handle`` — the session's public, stable identity. Shown in every
  ``list``/``query`` result, safe to hand to a peer for addressing
  ("message handle X"). Generated with
  :func:`palaia_hub.oauth.secrets_util.new_secret` truncated to a short,
  URL-safe token (entropy is not the point here — collision-avoidance is;
  see :data:`HANDLE_CHARS`).
- ``session_secret`` — returned exactly once, from :meth:`register`, never
  again. Every subsequent :meth:`heartbeat`/:meth:`update`/:meth:`deregister`
  call must present it; stored only as its SHA-256 hash
  (:func:`palaia_hub.oauth.secrets_util.hash_secret`), compared constant-time
  (:func:`~palaia_hub.oauth.secrets_util.verify_hash`) — the exact pattern
  SPEC-203 established for opaque bearer secrets, reused rather than
  reinvented. A wrong secret raises :class:`SessionSecretMismatchError`
  rather than silently no-op'ing, so a caller can tell "someone is
  guessing" from "handle does not exist".

**Status: self-reported vs. computed.** ``status`` in a stored row is
either ``"active"`` or ``"idle"`` (:data:`~palaia_hub.directory.models.
ReportedStatus`) — whatever the session last told :meth:`update`. ``stale``
is never an input a caller can set; it is always derived, at read time,
from ``now - last_seen_at`` against ``ttl_seconds`` — a session cannot lie
about being alive. See :func:`_effective_status`.

**TTL lifecycle.** A session past ``ttl_seconds`` since its last heartbeat
is ``stale`` (still visible in ``list``/``query``, exactly as the SPEC
requires — "visible, not deleted"). Past ``5 * ttl_seconds``, it is pruned
(hard-deleted) — swept lazily on every store call that touches the table,
mirroring :class:`palaia_hub.stash.store.StashStore`'s lazy hard-expiry,
rather than needing a background task.

**Clock-injectable.** Every method that needs "now" takes an optional
``now`` override (else the store's own ``clock`` callable, defaulting to
:func:`time.time`), so tests can assert exact TTL/staleness/prune edges
without sleeping.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

from ..oauth.secrets_util import hash_secret, new_secret, verify_hash
from ..security.files import harden_sqlite_database
from .models import (
    DirectoryError,
    ReportedStatus,
    SessionNotFoundError,
    SessionRecord,
    SessionSecretMismatchError,
    SessionStatus,
)

#: Default TTL applied when a caller does not specify one at registration.
DEFAULT_TTL_SECONDS = 300.0

#: Bounds for a session's ``ttl_seconds`` (issue #363). Below the minimum a
#: row would be pruned by the very next call — ``register`` would hand back a
#: handle that no longer exists; above the maximum a row would never go
#: stale and never be pruned, polluting the directory for good.
MIN_TTL_SECONDS = 30.0
MAX_TTL_SECONDS = 24 * 60 * 60.0


def clamp_ttl(ttl_seconds: float) -> float:
    """``ttl_seconds`` forced into ``[MIN_TTL_SECONDS, MAX_TTL_SECONDS]``;
    anything that is not a finite number becomes the default."""
    try:
        value = float(ttl_seconds)
    except (TypeError, ValueError):
        return DEFAULT_TTL_SECONDS
    if value != value or value in (float("inf"), float("-inf")):
        return DEFAULT_TTL_SECONDS
    return min(max(value, MIN_TTL_SECONDS), MAX_TTL_SECONDS)


#: A session past this multiple of its own TTL, counted from its last
#: heartbeat, is pruned — it disappears from every listing and can no
#: longer be addressed — rather than merely shown ``stale``.
PRUNE_TTL_MULTIPLIER = 5.0

#: How long a pruned session's row is kept as a tombstone before it is
#: deleted for good (issue #364). While the tombstone stands, the session's
#: own handle + secret still :meth:`DirectoryStore.verify` — so it can still
#: read (and ack) the mail that was addressed to it — and a heartbeat brings
#: it back. Matches the longest TTL the messenger grants an envelope
#: (``palaia_hub.messenger.models.MAX_TTL_SECONDS``, seven days): once
#: every envelope it could have been sent has expired, nothing is lost by
#: forgetting the row.
TOMBSTONE_SECONDS = 7 * 24 * 60 * 60.0
#: Characters trimmed off ``new_secret()``'s URL-safe output for a
#: handle — short enough to type/read in a message, long enough that two
#: independently registered sessions colliding is not a practical concern
#: (roughly 96 bits from the underlying base64url alphabet).
HANDLE_CHARS = 16

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS session_registry (
    handle TEXT PRIMARY KEY,
    secret_hash TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT '',
    host TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    agent_kind TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    reported_status TEXT NOT NULL DEFAULT 'active',
    capabilities_json TEXT NOT NULL DEFAULT '[]',
    registered_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    ttl_seconds REAL NOT NULL,
    stale_notified INTEGER NOT NULL DEFAULT 0,
    pruned_at REAL
);
CREATE INDEX IF NOT EXISTS idx_session_last_seen_at ON session_registry(last_seen_at);
"""

#: Columns added after the first release, applied to a database created
#: before them (``CREATE TABLE IF NOT EXISTS`` leaves an existing table alone).
_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("pruned_at", "ALTER TABLE session_registry ADD COLUMN pruned_at REAL"),
)


def _effective_status(
    reported_status: str, *, last_seen_at: float, ttl_seconds: float, now: float
) -> SessionStatus:
    if now - last_seen_at > ttl_seconds:
        return "stale"
    if reported_status == "idle":
        return "idle"
    return "active"


def _row_to_record(row: sqlite3.Row, *, now: float) -> SessionRecord:
    return SessionRecord(
        handle=row["handle"],
        scope=row["scope"],
        host=row["host"],
        platform=row["platform"],
        agent_kind=row["agent_kind"],
        model=row["model"],
        status=_effective_status(
            row["reported_status"],
            last_seen_at=row["last_seen_at"],
            ttl_seconds=row["ttl_seconds"],
            now=now,
        ),
        capabilities=json.loads(row["capabilities_json"]),
        registered_at=row["registered_at"],
        last_seen_at=row["last_seen_at"],
        ttl_seconds=row["ttl_seconds"],
    )


class DirectoryStore:
    """One hub-wide session directory: connection, schema, lock, sweep.

    Follows :class:`palaia_hub.stash.store.StashStore`'s pattern (one
    connection, ``check_same_thread=False``, one lock guarding every
    statement) — touched from the event loop via ``asyncio.to_thread``,
    not a contended OLTP database.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA_SQL)
        present = {
            str(row["name"]) for row in self._conn.execute("PRAGMA table_info(session_registry)")
        }
        for column, statement in _MIGRATIONS:
            if column not in present:
                self._conn.execute(statement)
        self._conn.commit()
        # SPEC-502: this database holds every session's hashed secret and
        # the roster of what each agent is doing. It, and its write-ahead
        # siblings, stay readable only by the account running the hub.
        harden_sqlite_database(self.path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
        harden_sqlite_database(self.path)

    # -- helpers ---------------------------------------------------------

    def _now(self, now: float | None) -> float:
        return now if now is not None else self.clock()

    def _sweep_locked(self, now: float) -> list[str]:
        """Prune hard-expired rows into tombstones, delete tombstones past
        :data:`TOMBSTONE_SECONDS`, and return handles newly crossing into
        ``stale`` since the last sweep (for the caller to emit
        ``session.stale`` events on — each handle is returned at most once,
        ever, because this also flips ``stale_notified``)."""
        rows = self._conn.execute(
            "SELECT handle, last_seen_at, ttl_seconds, stale_notified, pruned_at "
            "FROM session_registry"
        ).fetchall()
        newly_stale: list[str] = []
        to_prune: list[str] = []
        to_delete: list[str] = []
        to_mark_stale: list[str] = []
        for row in rows:
            if row["pruned_at"] is not None:
                if now - row["pruned_at"] > TOMBSTONE_SECONDS:
                    to_delete.append(row["handle"])
                continue
            age = now - row["last_seen_at"]
            if age > row["ttl_seconds"] * PRUNE_TTL_MULTIPLIER:
                to_prune.append(row["handle"])
            elif age > row["ttl_seconds"] and not row["stale_notified"]:
                to_mark_stale.append(row["handle"])
                newly_stale.append(row["handle"])
        if to_prune:
            # A tombstone, not a deletion (issue #364): the handle stays
            # taken, the secret still verifies, the row is hidden from every
            # listing — and the mail addressed to it stays readable.
            self._conn.executemany(
                "UPDATE session_registry SET pruned_at = ? WHERE handle = ?",
                [(now, h) for h in to_prune],
            )
        if to_delete:
            self._conn.executemany(
                "DELETE FROM session_registry WHERE handle = ?", [(h,) for h in to_delete]
            )
        if to_mark_stale:
            self._conn.executemany(
                "UPDATE session_registry SET stale_notified = 1 WHERE handle = ?",
                [(h,) for h in to_mark_stale],
            )
        if to_prune or to_delete or to_mark_stale:
            self._conn.commit()
        return newly_stale

    def _get_row_locked(self, handle: str, *, include_pruned: bool = False) -> sqlite3.Row | None:
        # `fetchone()` types as `Any` in typeshed (the row factory's actual
        # return type is not tracked statically) — `cast` states what we
        # know to be true at runtime (``row_factory = sqlite3.Row`` is set
        # in ``__init__``) rather than declaring this method `Any` and
        # losing the type at every call site.
        #
        # A pruned session's tombstone (issue #364) is visible only to the
        # calls that carry its own secret — verify, heartbeat, update,
        # deregister — and to register's handle-collision check. Addressing
        # it as a peer (`get`, `list`, `query`) finds nothing.
        sql = "SELECT * FROM session_registry WHERE handle = ?"
        if not include_pruned:
            sql += " AND pruned_at IS NULL"
        row = self._conn.execute(sql, (handle,)).fetchone()
        return cast("sqlite3.Row | None", row)

    def _check_secret_locked(self, row: sqlite3.Row, session_secret: str) -> None:
        if not verify_hash(session_secret, row["secret_hash"]):
            raise SessionSecretMismatchError(
                f"session secret does not match handle {row['handle']!r}"
            )

    # -- public API --------------------------------------------------------

    def register(
        self,
        *,
        scope: str,
        host: str,
        platform: str,
        agent_kind: str,
        model: str,
        capabilities: Sequence[str] = (),
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        now: float | None = None,
    ) -> tuple[SessionRecord, str, list[str]]:
        """Register a new session. Returns
        ``(record, session_secret, newly_stale_handles)``."""
        current = self._now(now)
        ttl_seconds = clamp_ttl(ttl_seconds)
        handle = new_secret()[:HANDLE_CHARS]
        secret = new_secret()
        with self._lock:
            newly_stale = self._sweep_locked(current)
            # A handle collision is astronomically unlikely (see
            # HANDLE_CHARS's docstring) but checked anyway rather than
            # trusting entropy alone against a PRIMARY KEY constraint.
            while self._get_row_locked(handle, include_pruned=True) is not None:
                handle = new_secret()[:HANDLE_CHARS]
            self._conn.execute(
                "INSERT INTO session_registry "
                "(handle, secret_hash, scope, host, platform, agent_kind, model, "
                " reported_status, capabilities_json, registered_at, last_seen_at, "
                " ttl_seconds, stale_notified) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, 0)",
                (
                    handle,
                    hash_secret(secret),
                    scope,
                    host,
                    platform,
                    agent_kind,
                    model,
                    json.dumps(list(capabilities)),
                    current,
                    current,
                    ttl_seconds,
                ),
            )
            self._conn.commit()
            row = self._get_row_locked(handle)
            assert row is not None
            record = _row_to_record(row, now=current)
        return record, secret, newly_stale

    def heartbeat(
        self, handle: str, session_secret: str, *, now: float | None = None
    ) -> tuple[SessionRecord, list[str]]:
        """Bump ``last_seen_at`` (and clear any stale mark). Returns
        ``(record, newly_stale_handles)`` — the sweep runs before the bump,
        so this session's own staleness (if any) is resolved by this same
        heartbeat, never reported as newly-stale against itself."""
        current = self._now(now)
        with self._lock:
            newly_stale = self._sweep_locked(current)
            row = self._get_row_locked(handle, include_pruned=True)
            if row is None:
                raise SessionNotFoundError(f"no session registered at handle {handle!r}")
            self._check_secret_locked(row, session_secret)
            # A pruned session that comes back with its own secret is back
            # (issue #364): its handle, and the mail addressed to it, are its
            # own again.
            self._conn.execute(
                "UPDATE session_registry SET last_seen_at = ?, stale_notified = 0, "
                "pruned_at = NULL WHERE handle = ?",
                (current, handle),
            )
            self._conn.commit()
            row = self._get_row_locked(handle)
            assert row is not None
            record = _row_to_record(row, now=current)
        return record, [h for h in newly_stale if h != handle]

    def update(
        self,
        handle: str,
        session_secret: str,
        *,
        scope: str | None = None,
        status: ReportedStatus | None = None,
        capabilities: Sequence[str] | None = None,
        now: float | None = None,
    ) -> tuple[SessionRecord, list[str]]:
        """Apply a partial self-report (scope/status/capabilities), also
        counting as a heartbeat (bumps ``last_seen_at``). Any field left
        ``None`` keeps its current value."""
        current = self._now(now)
        with self._lock:
            newly_stale = self._sweep_locked(current)
            row = self._get_row_locked(handle, include_pruned=True)
            if row is None:
                raise SessionNotFoundError(f"no session registered at handle {handle!r}")
            self._check_secret_locked(row, session_secret)
            new_scope = scope if scope is not None else row["scope"]
            new_status = status if status is not None else row["reported_status"]
            new_capabilities = (
                json.dumps(list(capabilities))
                if capabilities is not None
                else row["capabilities_json"]
            )
            self._conn.execute(
                "UPDATE session_registry SET scope = ?, reported_status = ?, "
                "capabilities_json = ?, last_seen_at = ?, stale_notified = 0, "
                "pruned_at = NULL WHERE handle = ?",
                (new_scope, new_status, new_capabilities, current, handle),
            )
            self._conn.commit()
            row = self._get_row_locked(handle)
            assert row is not None
            record = _row_to_record(row, now=current)
        return record, [h for h in newly_stale if h != handle]

    def verify(
        self, handle: str, session_secret: str, *, now: float | None = None
    ) -> tuple[SessionRecord, list[str]]:
        """Confirm ``handle`` + ``session_secret`` without changing anything.

        Added for the messenger (SPEC-403 deliverable #4), whose inbox
        authorization reuses *this* secret rather than minting a second
        credential for the same session. Deliberately **not** a heartbeat:
        reading your own mail says nothing about whether you are still
        working, and the directory already has
        :meth:`heartbeat`/:meth:`update` for liveness. Raises the same
        :class:`SessionNotFoundError`/:class:`SessionSecretMismatchError`
        the mutating methods do, so a caller cannot tell "guessing a secret"
        apart from "unknown handle" by which error it gets.

        A *pruned* session still verifies for :data:`TOMBSTONE_SECONDS`
        (issue #364): the messenger keeps envelopes for up to seven days, and
        the session they were addressed to must be able to read them even
        after a long silence — without that, mail to a session that missed
        five heartbeats was lost for good.
        """
        current = self._now(now)
        with self._lock:
            newly_stale = self._sweep_locked(current)
            row = self._get_row_locked(handle, include_pruned=True)
            if row is None:
                raise SessionNotFoundError(f"no session registered at handle {handle!r}")
            self._check_secret_locked(row, session_secret)
            record = _row_to_record(row, now=current)
        return record, newly_stale

    def get(self, handle: str, *, now: float | None = None) -> tuple[SessionRecord, list[str]]:
        """One session by handle, no secret required — addressing a *peer*.

        The public half of a handle (SPEC-402: "safe to hand to a peer for
        addressing"). Used by the messenger to check that a recipient exists
        and is not stale before accepting a message for them. Returns the
        same record ``list``/``query`` would, so nothing is exposed here that
        was not already listable.
        """
        current = self._now(now)
        with self._lock:
            newly_stale = self._sweep_locked(current)
            row = self._get_row_locked(handle)
            if row is None:
                raise SessionNotFoundError(f"no session registered at handle {handle!r}")
            record = _row_to_record(row, now=current)
        return record, newly_stale

    def deregister(
        self, handle: str, session_secret: str, *, now: float | None = None
    ) -> tuple[bool, list[str]]:
        """Remove a session's row entirely. Returns
        ``(deregistered, newly_stale_handles)``; ``False`` if the handle
        was already gone (e.g. already pruned) — never raised as
        :class:`SessionNotFoundError` for that specific case, since
        "already gone" is an idempotent success for a deregister call. A
        *wrong secret* on an existing handle still raises
        :class:`SessionSecretMismatchError`."""
        current = self._now(now)
        with self._lock:
            newly_stale = self._sweep_locked(current)
            row = self._get_row_locked(handle, include_pruned=True)
            if row is None:
                return False, newly_stale
            self._check_secret_locked(row, session_secret)
            self._conn.execute("DELETE FROM session_registry WHERE handle = ?", (handle,))
            self._conn.commit()
        return True, [h for h in newly_stale if h != handle]

    def admin_deregister(self, handle: str, *, now: float | None = None) -> tuple[bool, list[str]]:
        """Owner control: remove a session's row with no secret required
        (SPEC-405 deliverable #2 — "deregister a stale session").

        Has exactly one caller in production,
        :mod:`palaia_hub.directory_api`'s ``POST /api/directory/{handle}/
        deregister``, which sits behind the owner's signed-in session and
        CSRF token (:mod:`palaia_hub.admin_session`) — a *stronger* proof of
        "the owner really did this" than the session secret :meth:`deregister`
        demands of an ordinary caller, not a weaker substitute for it. Same
        idempotent-success shape as :meth:`deregister`: an already-gone
        handle answers ``False``, never :class:`SessionNotFoundError`.
        """
        current = self._now(now)
        with self._lock:
            newly_stale = self._sweep_locked(current)
            row = self._get_row_locked(handle, include_pruned=True)
            if row is None:
                return False, newly_stale
            self._conn.execute("DELETE FROM session_registry WHERE handle = ?", (handle,))
            self._conn.commit()
        return True, [h for h in newly_stale if h != handle]

    # `list` is defined last among this class's methods, deliberately: a
    # method literally named `list` shadows the builtin `list[...]` inside
    # every *subsequent* return-type annotation in this class body (mypy
    # resolves them against the class namespace) — defining it last means
    # no other method here ever needs `list[...]` after it exists.
    def query(
        self,
        *,
        scope_contains: str | None = None,
        capability: str | None = None,
        now: float | None = None,
    ) -> tuple[list[SessionRecord], list[str]]:
        """Sessions whose ``scope`` contains ``scope_contains`` (case
        -insensitive substring) and/or that carry ``capability`` — "who is
        working on repo X" (MASTERPLAN §5.4). Both filters are optional;
        neither given returns every session (same as :meth:`list` with no
        filters). Returns ``(records, newly_stale_handles)``."""
        records, newly_stale = self.list(now=now)
        if scope_contains is not None:
            needle = scope_contains.lower()
            records = [r for r in records if needle in r.scope.lower()]
        if capability is not None:
            records = [r for r in records if capability in r.capabilities]
        return records, newly_stale

    def list(
        self,
        *,
        status: SessionStatus | None = None,
        platform: str | None = None,
        capability: str | None = None,
        now: float | None = None,
    ) -> tuple[list[SessionRecord], list[str]]:
        """Every session, most recently registered first, optionally
        filtered by effective status / platform / a capability tag it
        carries. Returns ``(records, newly_stale_handles)``."""
        current = self._now(now)
        with self._lock:
            newly_stale = self._sweep_locked(current)
            rows = self._conn.execute(
                "SELECT * FROM session_registry WHERE pruned_at IS NULL ORDER BY registered_at DESC"
            ).fetchall()
            records = [_row_to_record(r, now=current) for r in rows]
        if status is not None:
            records = [r for r in records if r.status == status]
        if platform is not None:
            records = [r for r in records if r.platform == platform]
        if capability is not None:
            records = [r for r in records if capability in r.capabilities]
        return records, newly_stale


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "HANDLE_CHARS",
    "MAX_TTL_SECONDS",
    "MIN_TTL_SECONDS",
    "PRUNE_TTL_MULTIPLIER",
    "TOMBSTONE_SECONDS",
    "DirectoryError",
    "DirectoryStore",
    "clamp_ttl",
]
