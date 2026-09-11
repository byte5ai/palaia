"""Issue #364: a pruned session keeps its identity for as long as its mail
could live.

Past five TTLs the directory hard-deleted a session's row. The messenger
authorises ``check`` through the directory's ``verify``, so a session that
went quiet for 25 minutes (at the default TTL) could never again read the
envelopes addressed to it — some of which live for seven days — and the
handle was not reusable either. Pruned rows are tombstones now: hidden from
every listing, unaddressable as a peer, but still verifiable with their own
secret, revived by a heartbeat, and forgotten only once every envelope they
could have been sent has expired.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from palaia_hub.directory.models import SessionNotFoundError
from palaia_hub.directory.store import PRUNE_TTL_MULTIPLIER, TOMBSTONE_SECONDS, DirectoryStore

TTL = 60.0


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def _register(store: DirectoryStore) -> tuple[str, str]:
    record, secret, _ = store.register(
        scope="a", host="h", platform="p", agent_kind="k", model="m", ttl_seconds=TTL
    )
    return record.handle, secret


def _pruned_store() -> tuple[DirectoryStore, _Clock, str, str]:
    clock = _Clock()
    store = DirectoryStore(":memory:", clock=clock)
    handle, secret = _register(store)
    clock.now += TTL * PRUNE_TTL_MULTIPLIER + 1
    return store, clock, handle, secret


def test_a_pruned_session_is_hidden_and_unaddressable_but_still_verifies() -> None:
    store, _clock, handle, secret = _pruned_store()

    records, _ = store.list()
    assert records == []
    with pytest.raises(SessionNotFoundError):
        store.get(handle)

    record, _ = store.verify(handle, secret)
    assert record.handle == handle
    assert record.status == "stale"


def test_a_pruned_sessions_handle_is_not_handed_out_again() -> None:
    store, _clock, handle, _secret = _pruned_store()
    for _ in range(20):
        other, _ = _register(store)
        assert other != handle


def test_a_heartbeat_brings_a_pruned_session_back() -> None:
    store, _clock, handle, secret = _pruned_store()

    record, _ = store.heartbeat(handle, secret)

    assert record.status == "active"
    records, _ = store.list()
    assert [r.handle for r in records] == [handle]
    assert store.get(handle)[0].handle == handle


def test_a_tombstone_is_forgotten_once_its_mail_could_no_longer_exist() -> None:
    store, clock, handle, secret = _pruned_store()
    store.list()  # a sweep runs: the row becomes a tombstone now
    clock.now += TOMBSTONE_SECONDS + 1

    with pytest.raises(SessionNotFoundError):
        store.verify(handle, secret)


def test_deregister_removes_a_tombstone_too() -> None:
    store, _clock, handle, secret = _pruned_store()
    assert store.deregister(handle, secret)[0] is True
    with pytest.raises(SessionNotFoundError):
        store.verify(handle, secret)


def test_a_database_from_before_tombstones_is_upgraded_in_place(tmp_path: Path) -> None:
    path = tmp_path / "directory.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE session_registry (
            handle TEXT PRIMARY KEY, secret_hash TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT '', host TEXT NOT NULL DEFAULT '',
            platform TEXT NOT NULL DEFAULT '', agent_kind TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '', reported_status TEXT NOT NULL DEFAULT 'active',
            capabilities_json TEXT NOT NULL DEFAULT '[]', registered_at REAL NOT NULL,
            last_seen_at REAL NOT NULL, ttl_seconds REAL NOT NULL,
            stale_notified INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    conn.commit()
    conn.close()

    store = DirectoryStore(path)
    handle, secret = _register(store)
    assert store.verify(handle, secret)[0].handle == handle
    columns = {row[1] for row in store._conn.execute("PRAGMA table_info(session_registry)")}
    assert "pruned_at" in columns
    store.close()
