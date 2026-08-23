"""Typed vault change events and the in-process bus stub.

The real event bus (public schema, subscriptions, webhook/notify actions) is
Phase 2 work per MASTERPLAN §5.6. What this SPEC owns is the *event vocabulary*:
the dataclasses below are what the watcher and the engine emit today and what
the Phase-2 bus will carry unchanged, plus a deliberately small in-memory
fan-out so SPEC-103/104 have something to subscribe to.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

logger = logging.getLogger("palaia_hub.vault.events")

ChangeKind = Literal["created", "modified", "moved", "deleted"]


@dataclass(frozen=True, slots=True)
class VaultEvent:
    """Base class: which vault, when, and whether the engine caused it."""

    vault: str
    at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    external: bool = False


@dataclass(frozen=True, slots=True)
class NoteCreated(VaultEvent):
    """A note appeared in the vault."""

    path: str = ""
    permalink: str | None = None
    checksum: str = ""
    kind: ChangeKind = "created"


@dataclass(frozen=True, slots=True)
class NoteModified(VaultEvent):
    """A note's content changed in place."""

    path: str = ""
    permalink: str | None = None
    checksum: str = ""
    previous_checksum: str | None = None
    kind: ChangeKind = "modified"


@dataclass(frozen=True, slots=True)
class NoteMoved(VaultEvent):
    """A note changed path while keeping its identity.

    Emitted for engine moves and — crucially — for external renames, which
    ``watchfiles`` reports as ``deleted(old)`` + ``added(new)`` in the same
    debounce batch (SPEC-003 Q2). ``permalink`` is the identity carried over.
    """

    path: str = ""
    previous_path: str = ""
    permalink: str | None = None
    checksum: str = ""
    kind: ChangeKind = "moved"


@dataclass(frozen=True, slots=True)
class NoteDeleted(VaultEvent):
    """A note disappeared from the vault."""

    path: str = ""
    permalink: str | None = None
    kind: ChangeKind = "deleted"


@dataclass(frozen=True, slots=True)
class EntityRenamed(VaultEvent):
    """A note's identity was renamed (§4.2): new permalink, aliases, backlinks."""

    path: str = ""
    permalink: str | None = None
    previous_permalink: str | None = None
    title: str = ""
    previous_title: str = ""
    rewritten_links: int = 0
    kind: ChangeKind = "modified"


type ChangeEvent = NoteCreated | NoteModified | NoteMoved | NoteDeleted | EntityRenamed

type Subscriber = Callable[[ChangeEvent], Awaitable[None] | None]


class EventBus:
    """In-process fan-out of vault change events (Phase-1 stub).

    Subscribers may be sync or async callables. A failing subscriber is
    logged and skipped — never allowed to break a vault write, which has
    already been committed to disk by the time events are published.
    """

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []

    def subscribe(self, subscriber: Subscriber) -> Callable[[], None]:
        """Register ``subscriber``; returns a callable that unsubscribes it."""
        self._subscribers.append(subscriber)

        def unsubscribe() -> None:
            try:
                self._subscribers.remove(subscriber)
            except ValueError:  # pragma: no cover - already removed
                pass

        return unsubscribe

    @property
    def subscriber_count(self) -> int:
        """How many subscribers are currently registered."""
        return len(self._subscribers)

    async def publish(self, event: ChangeEvent) -> None:
        """Deliver ``event`` to every subscriber, in registration order."""
        for subscriber in list(self._subscribers):
            try:
                result = subscriber(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001 - a subscriber must not break a write
                logger.exception(
                    "vault event subscriber failed",
                    extra={"event": type(event).__name__},
                )

    async def publish_all(self, events: list[ChangeEvent]) -> None:
        """Publish a batch of events in order."""
        for event in events:
            await self.publish(event)
