"""Filesystem watcher with checksum-based move detection.

``watchfiles`` has **no rename event**: an Obsidian-style rename arrives as
``deleted(old)`` + ``added(new)`` in the *same* debounce batch (SPEC-003 Q2,
measured at ~51 ms with a 200 ms debounce). A consumer that treats those as
independent delete-then-create silently loses the entity's identity, history
and relations on every rename — so pairing them by content checksum is a
named requirement here, not an optimization.

The engine's identity catalog supplies the *old* file's checksum and
permalink (the file itself is already gone by the time the batch arrives),
which is what makes the pairing possible at all. It also lets the watcher
label each event ``external``: a change whose checksum the catalog already
knows is the engine's own write coming back around, not user activity.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from watchfiles import Change, awatch

from .atomic import TEMP_SUFFIX, sha256_file
from .engine import VaultEngine
from .events import (
    ChangeEvent,
    EventBus,
    NoteCreated,
    NoteDeleted,
    NoteModified,
    NoteMoved,
)
from .models import IGNORED_DIRS, NOTE_SUFFIX

logger = logging.getLogger("palaia_hub.vault.watcher")

#: Debounce window in milliseconds. SPEC-003 Q2 measured 200 ms as generous
#: (observed watcher latency 51-80 ms, budget ~2 s) while still folding an
#: editor's multi-syscall save into a single batch.
DEFAULT_DEBOUNCE_MS = 200

#: How often watchfiles polls its backend within a debounce window.
DEFAULT_STEP_MS = 50


@dataclass(slots=True)
class WatcherStats:
    """Counters for observability and tests."""

    batches: int = 0
    events: int = 0
    moves_detected: int = 0
    ignored: int = 0
    per_kind: dict[str, int] = field(default_factory=dict)

    def record(self, event: ChangeEvent) -> None:
        """Count one emitted event."""
        self.events += 1
        name = type(event).__name__
        self.per_kind[name] = self.per_kind.get(name, 0) + 1


def is_vault_content(root: Path, path: Path) -> bool:
    """True when ``path`` is a note the engine cares about."""
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:  # pragma: no cover - outside the vault
        return False
    parts = relative.parts
    if any(part in IGNORED_DIRS for part in parts):
        return False
    if path.name.endswith(TEMP_SUFFIX) or path.name.startswith(".~"):
        return False
    return path.name.endswith(NOTE_SUFFIX)


class VaultWatcher:
    """Watches a vault for external changes and publishes typed events.

    Args:
        engine: the vault engine whose catalog is kept in sync.
        bus: event bus to publish on; defaults to the engine's bus.
        debounce_ms: debounce window handed to ``watchfiles``.
        step_ms: watchfiles' internal poll step.
    """

    def __init__(
        self,
        engine: VaultEngine,
        *,
        bus: EventBus | None = None,
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        step_ms: int = DEFAULT_STEP_MS,
    ) -> None:
        self.engine = engine
        self.bus = bus or engine.bus
        self.debounce_ms = debounce_ms
        self.step_ms = step_ms
        self.stats = WatcherStats()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()

    @property
    def running(self) -> bool:
        """True while the watch task is alive."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start watching in a background task and wait until it is armed."""
        if self.running:
            return
        self._stop.clear()
        self._ready.clear()
        self._task = asyncio.create_task(self._run(), name=f"vault-watcher:{self.engine.name}")
        await self._ready.wait()

    async def stop(self) -> None:
        """Stop watching and wait for the task to finish."""
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5.0)

    async def __aenter__(self) -> VaultWatcher:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    async def _run(self) -> None:
        self._ready.set()
        try:
            async for raw in awatch(
                self.engine.root,
                debounce=self.debounce_ms,
                step=self.step_ms,
                stop_event=self._stop,
                recursive=True,
                yield_on_timeout=False,
            ):
                self.stats.batches += 1
                events = self.process_batch(raw)
                if events and self.bus is not None:
                    await self.bus.publish_all(events)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception:  # noqa: BLE001 - a watcher crash must be visible, not fatal
            logger.exception("vault watcher for %s stopped unexpectedly", self.engine.name)

    # ------------------------------------------------------------ batch mapping

    def process_batch(self, raw: Iterable[tuple[Change, str]]) -> list[ChangeEvent]:
        """Translate one raw watchfiles batch into typed events.

        Deleted/added pairs with equal content checksums inside the same batch
        are emitted as a single :class:`NoteMoved`, preserving the permalink.
        """
        root = self.engine.root
        added: list[str] = []
        modified: list[str] = []
        deleted: list[str] = []
        for change, raw_path in raw:
            for path in self._expand(Path(raw_path)):
                if not is_vault_content(root, path):
                    self.stats.ignored += 1
                    continue
                relative = path.resolve().relative_to(root.resolve()).as_posix()
                if change is Change.added:
                    added.append(relative)
                elif change is Change.modified:
                    modified.append(relative)
                else:
                    deleted.append(relative)

        # watchfiles can report a path as both deleted and added within one
        # window (an editor's save-as-rename over itself); treat that as a
        # modification of the surviving file.
        for relative in list(deleted):
            if relative in added and (root / relative).exists():
                deleted.remove(relative)
                added.remove(relative)
                modified.append(relative)

        events: list[ChangeEvent] = []
        events.extend(self._detect_moves(added, deleted))
        events.extend(self._creations(added))
        events.extend(self._modifications(modified))
        events.extend(self._deletions(deleted))
        for event in events:
            self.stats.record(event)
        return events

    def _expand(self, path: Path) -> list[Path]:
        """Expand a reported path to the note files it stands for.

        A whole directory can appear at once — an import, a folder dragged
        into the vault, or simply a note written into a directory that did not
        exist yet: inotify reports the directory before a watch on it exists,
        so the notes inside it are never reported individually. Expanding the
        directory is what keeps those notes from being missed.
        """
        if not path.is_dir():
            return [path]
        if path.name in IGNORED_DIRS:
            self.stats.ignored += 1
            return []
        return [child for child in sorted(path.rglob(f"*{NOTE_SUFFIX}")) if child.is_file()]

    def _detect_moves(self, added: list[str], deleted: list[str]) -> list[ChangeEvent]:
        if not added or not deleted:
            return []
        # Group the known checksums of the vanished files: the engine catalog
        # is the only place their content still exists.
        vanished: dict[str, list[str]] = {}
        for relative in deleted:
            entry = self.engine.catalog.get(relative)
            if entry is None:
                continue
            vanished.setdefault(entry.checksum, []).append(relative)

        events: list[ChangeEvent] = []
        for relative in list(added):
            path = self.engine.root / relative
            if not path.exists():
                continue
            try:
                checksum = sha256_file(path)
            except OSError:  # pragma: no cover - vanished under us
                continue
            candidates = vanished.get(checksum)
            if not candidates:
                continue
            previous = candidates.pop(0)
            if not candidates:
                vanished.pop(checksum, None)
            added.remove(relative)
            deleted.remove(previous)
            old_entry = self.engine.catalog.get(previous)
            permalink = old_entry.permalink if old_entry else None
            self.engine.observe_external_change(previous, deleted=True)
            self.engine.observe_external_change(relative, permalink=permalink)
            self.stats.moves_detected += 1
            events.append(
                NoteMoved(
                    vault=self.engine.name,
                    external=True,
                    path=relative,
                    previous_path=previous,
                    permalink=permalink,
                    checksum=checksum,
                )
            )
        return events

    def _creations(self, added: list[str]) -> list[ChangeEvent]:
        events: list[ChangeEvent] = []
        for relative in added:
            known = self.engine.catalog.get(relative)
            entry = self.engine.observe_external_change(relative)
            if entry is None:
                continue
            external = known is None or known.checksum != entry.checksum
            events.append(
                NoteCreated(
                    vault=self.engine.name,
                    external=external,
                    path=relative,
                    permalink=entry.permalink,
                    checksum=entry.checksum,
                )
            )
        return events

    def _modifications(self, modified: list[str]) -> list[ChangeEvent]:
        events: list[ChangeEvent] = []
        for relative in dict.fromkeys(modified):
            known = self.engine.catalog.get(relative)
            entry = self.engine.observe_external_change(relative)
            if entry is None:
                continue
            if known is not None and known.checksum == entry.checksum:
                # The engine's own write, already reflected in the catalog.
                events.append(
                    NoteModified(
                        vault=self.engine.name,
                        external=False,
                        path=relative,
                        permalink=entry.permalink,
                        checksum=entry.checksum,
                        previous_checksum=known.checksum,
                    )
                )
                continue
            events.append(
                NoteModified(
                    vault=self.engine.name,
                    external=True,
                    path=relative,
                    permalink=entry.permalink,
                    checksum=entry.checksum,
                    previous_checksum=known.checksum if known else None,
                )
            )
        return events

    def _deletions(self, deleted: list[str]) -> list[ChangeEvent]:
        events: list[ChangeEvent] = []
        for relative in deleted:
            entry = self.engine.observe_external_change(relative, deleted=True)
            events.append(
                NoteDeleted(
                    vault=self.engine.name,
                    external=entry is not None,
                    path=relative,
                    permalink=entry.permalink if entry else None,
                )
            )
        return events
