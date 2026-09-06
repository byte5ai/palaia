"""Issue #363: a session's ``ttl_seconds`` is bounded.

``ttl_seconds=1e15`` made a row that never went stale and was never pruned;
``ttl_seconds=-1`` made a row the very next call pruned, so ``register``
returned a handle that already did not exist. Both ends are clamped now.
"""

from __future__ import annotations

import pytest

from palaia_hub.directory.store import (
    DEFAULT_TTL_SECONDS,
    MAX_TTL_SECONDS,
    MIN_TTL_SECONDS,
    DirectoryStore,
    clamp_ttl,
)


def _register(store: DirectoryStore, ttl_seconds: float) -> tuple[str, str, float]:
    record, secret, _ = store.register(
        scope="a", host="h", platform="p", agent_kind="k", model="m", ttl_seconds=ttl_seconds
    )
    return record.handle, secret, record.ttl_seconds


@pytest.mark.parametrize(
    ("requested", "effective"),
    [
        (1e15, MAX_TTL_SECONDS),
        (float("inf"), DEFAULT_TTL_SECONDS),
        (float("nan"), DEFAULT_TTL_SECONDS),
        (-1, MIN_TTL_SECONDS),
        (0, MIN_TTL_SECONDS),
        (60, 60.0),
    ],
)
def test_clamp_ttl(requested: float, effective: float) -> None:
    assert clamp_ttl(requested) == effective


def test_a_negative_ttl_no_longer_registers_a_handle_that_is_already_gone() -> None:
    store = DirectoryStore(":memory:")
    handle, secret, ttl = _register(store, ttl_seconds=-1)
    assert ttl == MIN_TTL_SECONDS

    record, _ = store.heartbeat(handle, secret)  # the handle exists
    assert record.handle == handle


def test_an_absurd_ttl_is_capped_so_the_row_can_still_go_stale() -> None:
    store = DirectoryStore(":memory:")
    _, _, ttl = _register(store, ttl_seconds=1e15)
    assert ttl == MAX_TTL_SECONDS
