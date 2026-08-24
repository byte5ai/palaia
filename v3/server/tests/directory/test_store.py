"""Unit tests for :class:`DirectoryStore` — handle/secret lifecycle,
TTL/stale/prune, filtering (SPEC-402 acceptance criteria)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from palaia_hub.directory.models import (
    SessionNotFoundError,
    SessionRecord,
    SessionSecretMismatchError,
)
from palaia_hub.directory.store import PRUNE_TTL_MULTIPLIER, DirectoryStore


class _Clock:
    """A settable clock for exact TTL/staleness/prune edge assertions."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def store(clock: _Clock) -> DirectoryStore:
    return DirectoryStore(":memory:", clock=clock)


def _register(
    store: DirectoryStore,
    *,
    scope: str = "a",
    platform: str = "p",
    capabilities: Sequence[str] = (),
    ttl_seconds: float = 300.0,
) -> tuple[SessionRecord, str]:
    """Register with sensible defaults for host/agent_kind/model, which no
    test in this file needs to vary."""
    record, secret, _ = store.register(
        scope=scope,
        host="h",
        platform=platform,
        agent_kind="k",
        model="m",
        capabilities=capabilities,
        ttl_seconds=ttl_seconds,
    )
    return record, secret


# -- register / handle stability -------------------------------------------


def test_register_returns_a_handle_and_a_secret(store: DirectoryStore) -> None:
    record, secret = _register(store, scope="refactoring billing", platform="claude-code")
    assert record.handle
    assert secret
    assert record.scope == "refactoring billing"
    assert record.status == "active"


def test_two_registrations_get_different_handles_and_secrets(store: DirectoryStore) -> None:
    r1, s1 = _register(store, scope="a")
    r2, s2 = _register(store, scope="b")
    assert r1.handle != r2.handle
    assert s1 != s2


def test_handle_is_stable_across_heartbeats(store: DirectoryStore, clock: _Clock) -> None:
    record, secret = _register(store, ttl_seconds=100)
    clock.now += 10
    heartbeat_record, _ = store.heartbeat(record.handle, secret)
    assert heartbeat_record.handle == record.handle


# -- session secret / impersonation guard ----------------------------------


def test_wrong_secret_cannot_heartbeat(store: DirectoryStore) -> None:
    record, _secret = _register(store)
    with pytest.raises(SessionSecretMismatchError):
        store.heartbeat(record.handle, "not-the-real-secret")


def test_wrong_secret_cannot_update(store: DirectoryStore) -> None:
    record, _secret = _register(store)
    with pytest.raises(SessionSecretMismatchError):
        store.update(record.handle, "not-the-real-secret", scope="b")


def test_wrong_secret_cannot_deregister(store: DirectoryStore) -> None:
    record, _secret = _register(store)
    with pytest.raises(SessionSecretMismatchError):
        store.deregister(record.handle, "not-the-real-secret")


def test_a_different_sessions_secret_cannot_act_on_this_one(store: DirectoryStore) -> None:
    """The impersonation acceptance criterion, stated with two real
    sessions rather than a made-up string: peer B's real secret must not
    work on peer A's handle."""
    a, _a_secret = _register(store, scope="a")
    _b, b_secret = _register(store, scope="b")

    with pytest.raises(SessionSecretMismatchError):
        store.heartbeat(a.handle, b_secret)
    with pytest.raises(SessionSecretMismatchError):
        store.update(a.handle, b_secret, status="idle")
    with pytest.raises(SessionSecretMismatchError):
        store.deregister(a.handle, b_secret)


def test_correct_secret_succeeds(store: DirectoryStore) -> None:
    record, secret = _register(store)
    updated, _ = store.update(record.handle, secret, scope="b")
    assert updated.scope == "b"


def test_unknown_handle_raises_not_found(store: DirectoryStore) -> None:
    with pytest.raises(SessionNotFoundError):
        store.heartbeat("no-such-handle", "whatever")


# -- TTL / stale / prune -----------------------------------------------------


def test_session_is_active_before_ttl_elapses(store: DirectoryStore, clock: _Clock) -> None:
    record, _secret = _register(store, ttl_seconds=60)
    clock.now += 59
    sessions, _ = store.list()
    assert sessions[0].handle == record.handle
    assert sessions[0].status == "active"


def test_session_past_ttl_shows_stale_but_is_not_deleted(
    store: DirectoryStore, clock: _Clock
) -> None:
    record, _secret = _register(store, ttl_seconds=60)
    clock.now += 61
    sessions, _ = store.list()
    assert len(sessions) == 1
    assert sessions[0].handle == record.handle
    assert sessions[0].status == "stale"


def test_session_past_prune_multiplier_is_deleted(store: DirectoryStore, clock: _Clock) -> None:
    _register(store, ttl_seconds=60)
    clock.now += 60 * PRUNE_TTL_MULTIPLIER + 1
    sessions, _ = store.list()
    assert sessions == []


def test_heartbeat_clears_staleness(store: DirectoryStore, clock: _Clock) -> None:
    record, secret = _register(store, ttl_seconds=60)
    clock.now += 61
    store.heartbeat(record.handle, secret)
    sessions, _ = store.list()
    assert sessions[0].status == "active"


def test_list_reports_newly_stale_handles_exactly_once(
    store: DirectoryStore, clock: _Clock
) -> None:
    record, _secret = _register(store, ttl_seconds=60)
    clock.now += 61
    _, newly_stale_1 = store.list()
    assert newly_stale_1 == [record.handle]
    _, newly_stale_2 = store.list()
    assert newly_stale_2 == []


def test_reported_status_idle_is_shown_while_within_ttl(store: DirectoryStore) -> None:
    record, secret = _register(store)
    updated, _ = store.update(record.handle, secret, status="idle")
    assert updated.status == "idle"


# -- filtering (query by scope substring, capability) ------------------------


def test_query_filters_by_scope_substring_case_insensitive(store: DirectoryStore) -> None:
    _register(store, scope="Refactoring the billing service")
    _register(store, scope="writing docs")

    results, _ = store.query(scope_contains="billing")
    assert len(results) == 1
    assert "billing" in results[0].scope.lower()

    results_ci, _ = store.query(scope_contains="BILLING")
    assert len(results_ci) == 1


def test_query_filters_by_capability(store: DirectoryStore) -> None:
    _register(store, scope="a", capabilities=["review"])
    _register(store, scope="b", capabilities=["write-code"])

    results, _ = store.query(capability="review")
    assert len(results) == 1
    assert results[0].scope == "a"


def test_query_with_no_filters_returns_everything(store: DirectoryStore) -> None:
    _register(store, scope="a")
    _register(store, scope="b")
    results, _ = store.query()
    assert len(results) == 2


def test_list_filters_by_status_platform_capability(store: DirectoryStore, clock: _Clock) -> None:
    _register(store, scope="a", platform="claude-code", capabilities=["review"], ttl_seconds=60)
    _register(store, scope="b", platform="codex", ttl_seconds=60)

    by_platform, _ = store.list(platform="codex")
    assert len(by_platform) == 1 and by_platform[0].scope == "b"

    by_capability, _ = store.list(capability="review")
    assert len(by_capability) == 1 and by_capability[0].scope == "a"

    clock.now += 61
    by_status, _ = store.list(status="stale")
    assert {r.scope for r in by_status} == {"a", "b"}


# -- deregister ---------------------------------------------------------------


def test_deregister_removes_the_session(store: DirectoryStore) -> None:
    record, secret = _register(store)
    deregistered, _ = store.deregister(record.handle, secret)
    assert deregistered is True
    sessions, _ = store.list()
    assert sessions == []


def test_deregister_already_gone_handle_returns_false_not_error(store: DirectoryStore) -> None:
    deregistered, _ = store.deregister("no-such-handle", "whatever")
    assert deregistered is False
