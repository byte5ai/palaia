"""SQLite-backed store for the messenger (SPEC-403 deliverable #2).

One row per **envelope copy**: a directed message is one row, a broadcast
is one row per resolved recipient (each with its own server-minted id —
"fans out as individual envelopes"). That is why ``recipient`` is a column
of its own next to ``addressed_to``: ``addressed_to`` is the protocol's
``to`` field exactly as the sender wrote it (a handle, or the directory
query for a broadcast), while ``recipient`` is whose inbox this copy is in.
Collapsing the two would either lose the query a broadcast was cast with or
make "my inbox" un-indexable.

**Delivery state, not a mailbox flag soup.** ``pending`` → ``delivered``
(a ``messenger_check`` handed it over) → ``acked`` (the recipient closed
it). :meth:`MessengerStore.check` is the only writer of ``delivered``, and
it only ever picks up ``pending`` rows — so "new envelopes for my handle"
means the same thing on every call, and an envelope is announced on the
event bus exactly once.

**TTL expiry is a lazy sweep, and it returns what it deleted.** Every
public method sweeps first (the same pattern
:class:`palaia_hub.stash.store.StashStore` and
:class:`palaia_hub.directory.store.DirectoryStore` use — no background
task), deletes every row past ``expires_at``, and hands the caller their
:class:`~palaia_hub.messenger.models.EnvelopeMetadata` so
:class:`~palaia_hub.messenger.service.MessengerService` can fire
``message.expired`` for each. Metadata, never the body: the row is gone and
its body goes with it, which is the point.

**Clock-injectable.** Every method takes an optional ``now``, else the
store's ``clock`` callable (default :func:`time.time`) — so the SPEC's
expiry acceptance criterion is a deterministic assertion, not a sleep. That
is also why every ordering here breaks ties on SQLite's own ``rowid``
(selected as ``seq``) rather than on the envelope id: a broadcast's copies,
or a request and its reply, can be minted inside one clock tick, and
"oldest first" then has to mean *insertion* order — sorting on a uuid would
shuffle them at random.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

from ..security.files import harden_sqlite_database
from .models import (
    DEFAULT_TTL_SECONDS,
    DeliveryState,
    Envelope,
    EnvelopeMetadata,
    EnvelopeNotFoundError,
    InboxItem,
    MessageType,
    Urgency,
    check_body,
    check_refs,
    check_subject,
    check_ttl,
)

#: How deep :meth:`MessengerStore.thread` will walk ``reply_to`` upwards
#: before it stops looking for a root. A reply chain longer than this is
#: pathological (or a cycle written by a future bug); walking forever is the
#: one outcome that must not happen.
MAX_THREAD_DEPTH = 200

#: Default cap on how many rows :meth:`MessengerStore.flows` returns — the
#: observability mirror's page size, not a limit on what is stored.
DEFAULT_FLOW_LIMIT = 200

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS messenger_envelopes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    sender TEXT NOT NULL,
    addressed_to TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    urgency TEXT NOT NULL,
    expects_reply INTEGER NOT NULL DEFAULT 0,
    body TEXT NOT NULL DEFAULT '',
    refs_json TEXT NOT NULL DEFAULT '[]',
    reply_to TEXT,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    delivered_at REAL,
    acked_at REAL
);
CREATE INDEX IF NOT EXISTS idx_messenger_inbox
    ON messenger_envelopes(recipient, state, created_at);
CREATE INDEX IF NOT EXISTS idx_messenger_outbox
    ON messenger_envelopes(sender, created_at);
CREATE INDEX IF NOT EXISTS idx_messenger_expires
    ON messenger_envelopes(expires_at);
CREATE INDEX IF NOT EXISTS idx_messenger_reply_to
    ON messenger_envelopes(reply_to);
"""


def _row_to_item(row: sqlite3.Row) -> InboxItem:
    envelope = Envelope(
        id=row["id"],
        type=cast("MessageType", row["type"]),
        from_=row["sender"],
        to=row["addressed_to"],
        subject=row["subject"],
        urgency=cast("Urgency", row["urgency"]),
        expects_reply=bool(row["expects_reply"]),
        body=row["body"],
        refs=json.loads(row["refs_json"]),
        reply_to=row["reply_to"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )
    return InboxItem(
        envelope=envelope,
        recipient=row["recipient"],
        state=cast("DeliveryState", row["state"]),
        delivered_at=row["delivered_at"],
        acked_at=row["acked_at"],
    )


class MessengerStore:
    """The hub's one messenger database: inboxes, outboxes, threads, TTL.

    Follows :class:`palaia_hub.directory.store.DirectoryStore`'s shape (one
    connection, ``check_same_thread=False``, one lock around every
    statement, touched from the event loop through ``asyncio.to_thread``) —
    this is a mailbox, not a contended OLTP database.
    """

    def __init__(self, path: Path | str, *, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        # SPEC-502: envelope bodies are whatever one agent said to another —
        # the most sensitive plaintext the hub stores outside a vault. The
        # database and its write-ahead siblings stay owner-only.
        harden_sqlite_database(self.path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
        harden_sqlite_database(self.path)

    # -- helpers ---------------------------------------------------------

    def _now(self, now: float | None) -> float:
        return now if now is not None else self.clock()

    def _sweep_locked(self, now: float) -> list[EnvelopeMetadata]:
        """Hard-delete every envelope past ``expires_at``; return their
        metadata (never their bodies — those are gone with the row) so the
        caller can fire ``message.expired`` once per envelope."""
        rows = self._conn.execute(
            "SELECT rowid AS seq, * FROM messenger_envelopes WHERE expires_at <= ?", (now,)
        ).fetchall()
        if not rows:
            return []
        expired = [EnvelopeMetadata.of(_row_to_item(row)) for row in rows]
        self._conn.executemany(
            "DELETE FROM messenger_envelopes WHERE id = ?", [(row["id"],) for row in rows]
        )
        self._conn.commit()
        return expired

    def _row_locked(self, envelope_id: str) -> sqlite3.Row | None:
        # `fetchone()` types as `Any` in typeshed (the row factory's real
        # return type is not tracked statically); `cast` states what
        # `row_factory = sqlite3.Row` in `__init__` already guarantees,
        # rather than letting `Any` leak into every call site.
        row = self._conn.execute(
            "SELECT rowid AS seq, * FROM messenger_envelopes WHERE id = ?", (envelope_id,)
        ).fetchone()
        return cast("sqlite3.Row | None", row)

    # -- write -----------------------------------------------------------

    def create(
        self,
        *,
        type: MessageType,
        sender: str,
        addressed_to: str,
        recipients: Sequence[str],
        subject: str,
        urgency: Urgency = "normal",
        expects_reply: bool = False,
        body: str = "",
        refs: list[str] | None = None,
        reply_to: str | None = None,
        ttl_seconds: float | None = None,
        now: float | None = None,
    ) -> tuple[list[InboxItem], list[EnvelopeMetadata]]:
        """Mint one envelope per recipient. Returns ``(items, expired)``.

        The caps are enforced *here*, at the storage boundary, not only in
        the service: :func:`~palaia_hub.messenger.models.check_body` and
        friends are the protocol's invariants, and a future second caller
        (an importer, a REST write, a test) must not be able to write a row
        the protocol forbids.
        """
        current = self._now(now)
        clean_subject = check_subject(subject)
        clean_body = check_body(body)
        clean_refs = check_refs(refs)
        ttl = check_ttl(ttl_seconds)
        expires_at = current + ttl
        refs_json = json.dumps(clean_refs)
        ids = [uuid.uuid4().hex for _ in recipients]
        with self._lock:
            expired = self._sweep_locked(current)
            self._conn.executemany(
                "INSERT INTO messenger_envelopes "
                "(id, type, sender, addressed_to, recipient, subject, urgency, "
                " expects_reply, body, refs_json, reply_to, created_at, expires_at, "
                " state, delivered_at, acked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL)",
                [
                    (
                        envelope_id,
                        type,
                        sender,
                        addressed_to,
                        recipient,
                        clean_subject,
                        urgency,
                        int(expects_reply),
                        clean_body,
                        refs_json,
                        reply_to,
                        current,
                        expires_at,
                    )
                    for envelope_id, recipient in zip(ids, recipients, strict=True)
                ],
            )
            self._conn.commit()
            items = [_row_to_item(row) for row in self._rows_by_ids_locked(ids)]
        return items, expired

    def _rows_by_ids_locked(self, ids: Sequence[str]) -> list[sqlite3.Row]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT rowid AS seq, * FROM messenger_envelopes "
            f"WHERE id IN ({placeholders}) ORDER BY created_at ASC, seq ASC",
            tuple(ids),
        ).fetchall()
        return cast("list[sqlite3.Row]", rows)

    def check(
        self, recipient: str, *, now: float | None = None
    ) -> tuple[list[InboxItem], list[EnvelopeMetadata]]:
        """Every ``pending`` envelope for ``recipient``, marked ``delivered``.

        Returns ``(items, expired)``, the items carrying their *new*
        (delivered) state — so the caller's ``message.received`` event and
        the caller's own returned envelope agree. Calling this twice returns
        nothing the second time: ``delivered`` is what "already announced"
        means, and re-announcing would double every automation downstream.
        """
        current = self._now(now)
        with self._lock:
            expired = self._sweep_locked(current)
            rows = self._conn.execute(
                "SELECT rowid AS seq, * FROM messenger_envelopes "
                "WHERE recipient = ? AND state = 'pending' "
                "ORDER BY created_at ASC, seq ASC",
                (recipient,),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                self._conn.executemany(
                    "UPDATE messenger_envelopes SET state = 'delivered', delivered_at = ? "
                    "WHERE id = ?",
                    [(current, envelope_id) for envelope_id in ids],
                )
                self._conn.commit()
            items = [_row_to_item(row) for row in self._rows_by_ids_locked(ids)]
        return items, expired

    def ack(
        self, envelope_id: str, recipient: str, *, now: float | None = None
    ) -> tuple[InboxItem, list[EnvelopeMetadata]]:
        """Close one envelope in ``recipient``'s inbox.

        Idempotent: acking an already-acked envelope returns it unchanged
        rather than erroring. A row belonging to somebody else's inbox reads
        as :class:`~palaia_hub.messenger.models.EnvelopeNotFoundError` here —
        the caller-facing distinction between "not yours" and "not there" is
        made one layer up, by
        :class:`~palaia_hub.messenger.service.MessengerService`, which knows
        both sides of the fence.
        """
        current = self._now(now)
        with self._lock:
            expired = self._sweep_locked(current)
            row = self._row_locked(envelope_id)
            if row is None or row["recipient"] != recipient:
                raise EnvelopeNotFoundError(
                    f"no envelope {envelope_id!r} in the inbox of {recipient!r}. Fix: "
                    "run messenger_check first — an envelope past its expires_at is "
                    "gone, and an id from another session's inbox is not yours to ack."
                )
            if row["state"] != "acked":
                self._conn.execute(
                    "UPDATE messenger_envelopes SET state = 'acked', acked_at = ? "
                    "WHERE id = ?",
                    (current, envelope_id),
                )
                self._conn.commit()
                row = self._row_locked(envelope_id)
                assert row is not None
            item = _row_to_item(row)
        return item, expired

    # -- read ------------------------------------------------------------

    def item(
        self, envelope_id: str, *, now: float | None = None
    ) -> tuple[InboxItem | None, list[EnvelopeMetadata]]:
        """One envelope copy by id, or ``None`` (never sent, or expired)."""
        current = self._now(now)
        with self._lock:
            expired = self._sweep_locked(current)
            row = self._row_locked(envelope_id)
            item = _row_to_item(row) if row is not None else None
        return item, expired

    def _collect_thread_rows_locked(self, envelope_id: str) -> list[sqlite3.Row]:
        """Every row in ``envelope_id``'s whole thread (its root's full
        subtree), oldest first. Must be called already holding ``self._lock``,
        after a sweep. Shared by :meth:`thread` (read) and
        :meth:`expire_thread` (SPEC-405's "end a conversation") so both walk
        the *identical* tree — the second was added as this method's own
        second caller, not as a hand-copied variant of the walk below.

        Walks ``reply_to`` up to the root (bounded by
        :data:`MAX_THREAD_DEPTH`, so a cycle cannot hang the hub), then
        collects every descendant breadth-first. An envelope whose ancestor
        has already expired away roots the thread at itself — the chain is
        what still exists, honestly, rather than an error about a message
        nobody can read any more.
        """
        row = self._row_locked(envelope_id)
        if row is None:
            raise EnvelopeNotFoundError(
                f"no envelope {envelope_id!r}. Fix: check the id — an envelope "
                "past its expires_at is deleted, threads included."
            )
        root = row
        seen_up = {root["id"]}
        for _ in range(MAX_THREAD_DEPTH):
            parent_id = root["reply_to"]
            if parent_id is None or parent_id in seen_up:
                break
            parent = self._row_locked(parent_id)
            if parent is None:
                break
            root = parent
            seen_up.add(root["id"])
        collected: dict[str, sqlite3.Row] = {root["id"]: root}
        frontier = [root["id"]]
        while frontier:
            placeholders = ",".join("?" for _ in frontier)
            children = self._conn.execute(
                "SELECT rowid AS seq, * FROM messenger_envelopes "
                f"WHERE reply_to IN ({placeholders})",
                tuple(frontier),
            ).fetchall()
            frontier = []
            for child in children:
                if child["id"] in collected:
                    continue
                collected[child["id"]] = child
                frontier.append(child["id"])
        return sorted(collected.values(), key=lambda r: (r["created_at"], r["seq"]))

    def thread(
        self, envelope_id: str, *, now: float | None = None
    ) -> tuple[list[InboxItem], list[EnvelopeMetadata]]:
        """One envelope's whole reply chain, oldest first.

        See :meth:`_collect_thread_rows_locked` for how the chain is found.
        """
        current = self._now(now)
        with self._lock:
            expired = self._sweep_locked(current)
            rows = self._collect_thread_rows_locked(envelope_id)
            items = [_row_to_item(row) for row in rows]
        return items, expired

    def expire_thread(
        self, envelope_id: str, *, now: float | None = None
    ) -> tuple[str, list[EnvelopeMetadata], list[EnvelopeMetadata]]:
        """Owner control: end a conversation (SPEC-405 deliverable #2) by
        expiring every still-``pending`` (undelivered) copy in
        ``envelope_id``'s whole thread. Returns ``(root_id, thread_expired,
        swept_expired)`` — ``thread_expired`` is what this call itself
        deleted; ``swept_expired`` is whatever the routine TTL sweep found
        stale on the way in, same as every other method here.

        Delivered/acked copies are left standing: this ends the parts of
        the conversation that have not reached anyone yet, not the record
        of what already has (see :class:`~palaia_hub.messenger.models.
        EndConversationResult`'s docstring for why).
        """
        current = self._now(now)
        with self._lock:
            swept = self._sweep_locked(current)
            rows = self._collect_thread_rows_locked(envelope_id)
            root_id = rows[0]["id"]
            pending = [row for row in rows if row["state"] == "pending"]
            thread_expired = [EnvelopeMetadata.of(_row_to_item(row)) for row in pending]
            if pending:
                self._conn.executemany(
                    "DELETE FROM messenger_envelopes WHERE id = ?",
                    [(row["id"],) for row in pending],
                )
                self._conn.commit()
        return root_id, thread_expired, swept

    def outbox(
        self, sender: str, *, now: float | None = None
    ) -> tuple[list[InboxItem], list[EnvelopeMetadata]]:
        """Everything ``sender`` sent that has not expired, newest first —
        the SPEC's "sender outbox view" (deliverable #2). One row per
        recipient copy, so a broadcast shows who it actually reached."""
        current = self._now(now)
        with self._lock:
            expired = self._sweep_locked(current)
            rows = self._conn.execute(
                "SELECT rowid AS seq, * FROM messenger_envelopes WHERE sender = ? "
                "ORDER BY created_at DESC, seq DESC",
                (sender,),
            ).fetchall()
            items = [_row_to_item(row) for row in rows]
        return items, expired

    def inbox(
        self,
        recipient: str,
        *,
        state: DeliveryState | None = None,
        now: float | None = None,
    ) -> tuple[list[InboxItem], list[EnvelopeMetadata]]:
        """One recipient's whole inbox, newest first, without delivering
        anything (unlike :meth:`check`, this never changes state)."""
        current = self._now(now)
        with self._lock:
            expired = self._sweep_locked(current)
            rows = self._conn.execute(
                "SELECT rowid AS seq, * FROM messenger_envelopes WHERE recipient = ? "
                "ORDER BY created_at DESC, seq DESC",
                (recipient,),
            ).fetchall()
            items = [_row_to_item(row) for row in rows]
        if state is not None:
            items = [item for item in items if item.state == state]
        return items, expired

    def flows(
        self,
        *,
        handle: str | None = None,
        message_type: MessageType | None = None,
        state: DeliveryState | None = None,
        limit: int = DEFAULT_FLOW_LIMIT,
        now: float | None = None,
    ) -> tuple[list[InboxItem], list[EnvelopeMetadata]]:
        """Recent envelope copies across every inbox, newest first — the
        observability mirror's feed (SPEC-403 deliverable #6). ``handle``
        matches either side of a flow (sender *or* recipient)."""
        current = self._now(now)
        with self._lock:
            expired = self._sweep_locked(current)
            rows = self._conn.execute(
                "SELECT rowid AS seq, * FROM messenger_envelopes "
                "ORDER BY created_at DESC, seq DESC"
            ).fetchall()
            items = [_row_to_item(row) for row in rows]
        if handle is not None:
            items = [
                item
                for item in items
                if item.envelope.from_ == handle or item.recipient == handle
            ]
        if message_type is not None:
            items = [item for item in items if item.envelope.type == message_type]
        if state is not None:
            items = [item for item in items if item.state == state]
        return items[: max(limit, 0)], expired

    def sweep(self, *, now: float | None = None) -> list[EnvelopeMetadata]:
        """Run the expiry sweep on its own, with no other work attached.

        Every other method sweeps as a side effect; this is for a caller
        that wants only that — a scheduled tick, or a test asserting the
        SPEC's expiry criterion without reading anything first.
        """
        current = self._now(now)
        with self._lock:
            return self._sweep_locked(current)


__all__ = [
    "DEFAULT_FLOW_LIMIT",
    "DEFAULT_TTL_SECONDS",
    "MAX_THREAD_DEPTH",
    "MessengerStore",
]
