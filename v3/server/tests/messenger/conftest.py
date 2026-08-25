"""Shared fixtures for the messenger tests (SPEC-403).

Everything here is clock-injectable and in-memory: the SPEC's expiry
criterion is a deterministic assertion, never a sleep.
"""

from __future__ import annotations

from typing import Any

import pytest

from palaia_hub.directory.service import DirectoryService
from palaia_hub.directory.store import DirectoryStore
from palaia_hub.messenger.service import MessengerService
from palaia_hub.messenger.store import MessengerStore


class Clock:
    """A hand-wound clock shared by the directory and messenger stores, so a
    session going stale and an envelope expiring happen on the same
    timeline."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class StubRefValidator:
    """A ref validator with a fixed set of refs that resolve, per vault.

    Stands in for :class:`palaia_hub.messenger.refs.VaultRefValidator` where
    a test cares about the messenger's behaviour rather than the index's.
    The real one is exercised against real vault indexes in ``test_refs.py``,
    and through a whole running hub in
    ``tests/test_serve_messenger_spec403.py``.
    """

    def __init__(self, resolvable: dict[str, set[str]] | None = None) -> None:
        self.resolvable = resolvable or {}

    def unresolvable(
        self, refs: list[str], *, readable_vaults: frozenset[str] | None = None
    ) -> list[str]:
        keys = [
            key
            for key in self.resolvable
            if readable_vaults is None or key in readable_vaults
        ]
        return [
            ref for ref in refs if not any(ref in self.resolvable[key] for key in keys)
        ]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def directory(clock: Clock) -> DirectoryService:
    return DirectoryService(DirectoryStore(":memory:", clock=clock))


@pytest.fixture
def store(clock: Clock) -> MessengerStore:
    return MessengerStore(":memory:", clock=clock)


@pytest.fixture
def ref_validator() -> StubRefValidator:
    return StubRefValidator({"work": {"memory://projects/api-gateway"}})


@pytest.fixture
def service(
    store: MessengerStore, directory: DirectoryService, ref_validator: StubRefValidator
) -> MessengerService:
    return MessengerService(store, directory, ref_validator=ref_validator)


@pytest.fixture
def events(service: MessengerService) -> list[tuple[str, dict[str, Any]]]:
    """Every event the service publishes, in order."""
    captured: list[tuple[str, dict[str, Any]]] = []
    service.publish = lambda name, data: captured.append((name, data))
    return captured
