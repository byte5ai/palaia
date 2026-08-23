"""Unit tests for :class:`StashStore` — TTL/stale expiry, budget eviction,
metadata (SPEC-202 acceptance criteria).
"""

from __future__ import annotations

import pytest

from palaia_hub.stash.models import StashError
from palaia_hub.stash.store import StashStore


class _Clock:
    """A settable clock for exact TTL/staleness edge assertions."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def store(clock: _Clock) -> StashStore:
    return StashStore(":memory:", clock=clock)


def test_set_then_get_round_trips_value(store: StashStore) -> None:
    store.set("jobs", "job-1", {"status": "running"})
    entry = store.get("jobs", "job-1")
    assert entry is not None
    assert entry.value == {"status": "running"}
    assert entry.namespace == "jobs"
    assert entry.key == "job-1"


def test_created_updated_accessed_metadata(store: StashStore, clock: _Clock) -> None:
    store.set("jobs", "job-1", "v1")
    clock.now += 10
    store.set("jobs", "job-1", "v2")  # overwrite: created_at stays, updated_at bumps
    clock.now += 5
    entry = store.get("jobs", "job-1")
    assert entry is not None
    assert entry.created_at == 1000.0
    assert entry.updated_at == 1010.0
    assert entry.accessed_at == 1015.0


def test_get_missing_key_returns_none(store: StashStore) -> None:
    assert store.get("jobs", "nope") is None


def test_ttl_hard_expiry_makes_get_act_as_absent(store: StashStore, clock: _Clock) -> None:
    store.set("jobs", "job-1", "v1", ttl_seconds=10)
    clock.now += 9.999
    assert store.get("jobs", "job-1") is not None
    clock.now += 1  # now at 11009.999... past ttl
    assert store.get("jobs", "job-1") is None


def test_stale_after_marks_entry_stale_but_still_returned(store: StashStore, clock: _Clock) -> None:
    store.set("jobs", "job-1", "v1", stale_after_seconds=5)
    clock.now += 4
    entry = store.get("jobs", "job-1")
    assert entry is not None
    assert entry.stale is False

    clock.now += 2  # past stale_after, still before any ttl
    entry = store.get("jobs", "job-1")
    assert entry is not None
    assert entry.stale is True
    assert entry.value == "v1"


def test_stale_then_hard_expiry_two_stage_lifecycle(store: StashStore, clock: _Clock) -> None:
    store.set("jobs", "job-1", "v1", ttl_seconds=10, stale_after_seconds=5)
    clock.now += 6
    entry = store.get("jobs", "job-1")
    assert entry is not None and entry.stale is True  # stale but present

    clock.now += 5  # past ttl
    assert store.get("jobs", "job-1") is None  # hard-expired


def test_delete_removes_entry(store: StashStore) -> None:
    store.set("jobs", "job-1", "v1")
    assert store.delete("jobs", "job-1") is True
    assert store.get("jobs", "job-1") is None
    assert store.delete("jobs", "job-1") is False


def test_list_returns_entries_most_recently_updated_first(store: StashStore, clock: _Clock) -> None:
    store.set("jobs", "a", "1")
    clock.now += 1
    store.set("jobs", "b", "2")
    entries = store.list("jobs")
    assert [e.key for e in entries] == ["b", "a"]


def test_list_excludes_hard_expired_entries(store: StashStore, clock: _Clock) -> None:
    store.set("jobs", "a", "1", ttl_seconds=5)
    store.set("jobs", "b", "2")
    clock.now += 6
    entries = store.list("jobs")
    assert [e.key for e in entries] == ["b"]


def test_list_is_scoped_to_namespace(store: StashStore) -> None:
    store.set("jobs", "a", "1")
    store.set("other", "a", "2")
    assert [e.key for e in store.list("jobs")] == ["a"]
    assert store.list("jobs")[0].value == "1"


def test_status_reports_totals_and_per_namespace_counts(store: StashStore) -> None:
    store.set("jobs", "a", "1")
    store.set("jobs", "b", "22")
    store.set("other", "a", "3")
    total_entries, total_bytes, namespaces = store.status()
    assert total_entries == 3
    assert total_bytes > 0
    assert namespaces == {"jobs": 2, "other": 1}


def test_per_entry_size_limit_rejects_oversized_value() -> None:
    store = StashStore(":memory:", entry_limit_bytes=16)
    with pytest.raises(StashError):
        store.set("jobs", "a", "x" * 100)


def test_budget_eviction_evicts_lru_first(clock: _Clock) -> None:
    # Each value below JSON-encodes to a fixed, known size; size the total
    # budget to hold exactly two of them so the third set must evict one.
    store = StashStore(":memory:", clock=clock, total_budget_bytes=0)
    value = "x" * 10
    entry_size = len(f'"{value}"'.encode())
    store.total_budget_bytes = entry_size * 2

    store.set("jobs", "a", value)
    clock.now += 1
    store.set("jobs", "b", value)
    clock.now += 1
    # "a" is now the least-recently-accessed; writing "c" must evict it.
    _, evicted = store.set("jobs", "c", value)

    assert evicted == ["jobs/a"]
    assert store.get("jobs", "a") is None
    assert store.get("jobs", "b") is not None
    assert store.get("jobs", "c") is not None


def test_budget_eviction_never_evicts_the_entry_being_written(clock: _Clock) -> None:
    """Overwriting the largest entry in a full store must not evict itself
    to make room for its own growth — SPEC-202 acceptance criterion."""
    store = StashStore(":memory:", clock=clock, total_budget_bytes=10_000)
    store.set("jobs", "only", "x" * 50)
    clock.now += 1
    # Grow well past the tiny budget: with only one entry in the store, the
    # sole eviction candidate is excluded (it is the entry being written),
    # so this must succeed rather than evict "only" out from under itself.
    store.total_budget_bytes = len(f'"{"x" * 50}"'.encode())
    _, evicted = store.set("jobs", "only", "x" * 5000)

    assert evicted == []
    entry = store.get("jobs", "only")
    assert entry is not None
    assert entry.value == "x" * 5000


def test_accessing_an_entry_protects_it_from_lru_eviction(clock: _Clock) -> None:
    store = StashStore(":memory:", clock=clock, total_budget_bytes=0)
    value = "x" * 10
    entry_size = len(f'"{value}"'.encode())
    store.total_budget_bytes = entry_size * 2

    store.set("jobs", "a", value)
    clock.now += 1
    store.set("jobs", "b", value)
    clock.now += 1
    store.get("jobs", "a")  # bump "a"'s accessed_at past "b"'s
    clock.now += 1
    _, evicted = store.set("jobs", "c", value)

    assert evicted == ["jobs/b"]
