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
from .errors import VaultError
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

#: A raw batch with at least this many changes is treated as "something big
#: is happening" (a folder dropped into the vault, an import, a `git pull`):
#: instead of processing it at once, the watcher keeps collecting further
#: batches until the filesystem has been quiet for :data:`DEFAULT_SETTLE_MS`
#: (issue #357). One pass over the whole copy then replaces one pass per
#: 200 ms debounce window, and a rename that straddled two windows pairs up.
DEFAULT_COALESCE_THRESHOLD = 20

#: Quiet period a large batch waits for before it is processed.
DEFAULT_SETTLE_MS = 1000

#: Upper bound on that wait, so a source that never goes quiet (a very slow
#: copy, a sync client trickling files) still gets processed in slices.
DEFAULT_MAX_COALESCE_MS = 15_000


@dataclass(slots=True)
class WatcherStats:
    """Counters for observability and tests."""

    batches: int = 0
    events: int = 0
    moves_detected: int = 0
    ignored: int = 0
    echoes: int = 0
    #: Raw watchfiles batches that were folded into an earlier one because
    #: something big was landing (see :data:`DEFAULT_COALESCE_THRESHOLD`).
    coalesced: int = 0
    #: Permalinks minted for notes that arrived without one (issue #358).
    permalinks_assigned: int = 0
    per_kind: dict[str, int] = field(default_factory=dict)

    def record(self, event: ChangeEvent) -> None:
        """Count one emitted event."""
        self.events += 1
        name = type(event).__name__
        self.per_kind[name] = self.per_kind.get(name, 0) + 1


def _lacks_identity(event: ChangeEvent) -> bool:
    """A note event for a note that has no permalink (issue #358)."""
    return isinstance(event, (NoteCreated, NoteModified, NoteMoved)) and event.permalink is None


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
        coalesce_threshold: raw changes per batch from which the watcher
            starts collecting instead of processing (issue #357).
        settle_ms: how long the filesystem must be quiet before a collected
            batch is processed.
        max_coalesce_ms: the longest a collected batch may wait in total.

    Two things keep a big drop of files from stalling the hub (issue #357):
    the raw batch is processed in a worker thread under the engine's write
    lock, so requests keep being served while checksums are computed and
    engine writes simply queue behind the batch; and consecutive batches of
    a large change are collected into one pass (see the three knobs above).
    """

    def __init__(
        self,
        engine: VaultEngine,
        *,
        bus: EventBus | None = None,
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        step_ms: int = DEFAULT_STEP_MS,
        coalesce_threshold: int = DEFAULT_COALESCE_THRESHOLD,
        settle_ms: int = DEFAULT_SETTLE_MS,
        max_coalesce_ms: int = DEFAULT_MAX_COALESCE_MS,
    ) -> None:
        self.engine = engine
        self.bus = bus or engine.bus
        self.debounce_ms = debounce_ms
        self.step_ms = step_ms
        self.coalesce_threshold = coalesce_threshold
        self.settle_ms = settle_ms
        self.max_coalesce_ms = max_coalesce_ms
        self.stats = WatcherStats()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()

    @property
    def running(self) -> bool:
        """True while the watch task is alive."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the watch task and wait until it is running.

        ``watchfiles`` establishes its OS-level watch on the first iteration
        and offers no "ready" signal, so a change made within a few tens of
        milliseconds of this call may still be missed. Callers that need the
        very first change (tests, imports) should settle briefly after start.
        """
        if self.running:
            return
        self._stop.clear()
        self._ready.clear()
        self._task = asyncio.create_task(self._run(), name=f"vault-watcher:{self.engine.name}")
        await self._ready.wait()
        # "Assigned by the engine on first index" (format spec §3.1): notes
        # that arrived while no watcher was running get their identity now.
        await self.adopt_unidentified_notes()

    async def stop(self) -> None:
        """Stop watching and wait for the task to finish.

        A task that does not wind down within five seconds (a batch still
        being processed on a very slow disk) is cancelled and logged rather
        than left to raise into the caller's shutdown sequence.
        """
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except TimeoutError:
                logger.warning("vault watcher for %s did not stop in time", self.engine.name)
            except asyncio.CancelledError:
                pass

    async def __aenter__(self) -> VaultWatcher:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    async def _run(self) -> None:
        """Producer/consumer pair: ``_produce`` drains ``awatch`` into a queue
        (never cancelled mid-iteration — cancelling an async generator's
        ``__anext__`` is not something ``watchfiles`` promises to survive),
        ``_consume`` collects and processes batches from that queue."""
        queue: asyncio.Queue[set[tuple[Change, str]] | None] = asyncio.Queue()
        producer = asyncio.create_task(
            self._produce(queue), name=f"vault-watcher-source:{self.engine.name}"
        )
        self._ready.set()
        try:
            await self._consume(queue)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            producer.cancel()
            raise
        except Exception:  # noqa: BLE001 - a watcher crash must be visible, not fatal
            logger.exception("vault watcher for %s stopped unexpectedly", self.engine.name)
        finally:
            with contextlib.suppress(asyncio.CancelledError):
                await producer

    async def _produce(self, queue: asyncio.Queue[set[tuple[Change, str]] | None]) -> None:
        try:
            async for raw in awatch(
                self.engine.root,
                debounce=self.debounce_ms,
                step=self.step_ms,
                stop_event=self._stop,
                recursive=True,
                yield_on_timeout=False,
            ):
                await queue.put(set(raw))
        finally:
            await queue.put(None)

    async def _consume(self, queue: asyncio.Queue[set[tuple[Change, str]] | None]) -> None:
        while True:
            raw = await queue.get()
            if raw is None:
                return
            merged = await self._coalesce(queue, raw)
            if merged is None:
                return
            self.stats.batches += 1
            # Off the event loop, under the engine's write lock (issue #357 /
            # #331): checksums and directory walks for a big drop of files
            # run in a worker thread while requests keep being served, and an
            # engine write cannot interleave with the catalog updates.
            async with self.engine.lock:
                events = await asyncio.to_thread(self._process_batch_as_one_snapshot, merged)
            if events and self.bus is not None:
                await self.bus.publish_all(events)
            if any(_lacks_identity(event) for event in events):
                await self.adopt_unidentified_notes()

    async def adopt_unidentified_notes(self) -> list[str]:
        """Mint a permalink for every note that has none (issue #358).

        Format spec §3.1 promises that a note created outside the engine —
        in Obsidian, by an import — gets its identity "on first index via a
        write-back commit". The engine had the operation; nothing called it,
        so such notes stayed keyed by path and lost their relations on the
        next external rename. The watcher is the component that sees notes
        arrive, so it is the one that asks. Malformed (issue #335) and
        non-UTF-8 (issue #355) notes are left alone by the engine itself.
        """
        try:
            assigned = await self.engine.assign_missing_permalinks()
        except VaultError as exc:
            # A read-only vault (format version ahead of this engine) or a
            # commit that cannot be made: identity waits, nothing else stops.
            logger.warning("not assigning permalinks in vault %s: %s", self.engine.name, exc)
            return []
        if assigned:
            self.stats.permalinks_assigned += len(assigned)
            logger.info(
                "assigned permalinks to %d note(s) in vault %s", len(assigned), self.engine.name
            )
        return assigned

    def _process_batch_as_one_snapshot(
        self, raw: Iterable[tuple[Change, str]]
    ) -> list[ChangeEvent]:
        """`process_batch` under the engine's `catalog_batch`: readers see a
        batch of external changes land as one new catalog, not one entry at a
        time (issue #331)."""
        with self.engine.catalog_batch():
            return self.process_batch(raw)

    async def _coalesce(
        self,
        queue: asyncio.Queue[set[tuple[Change, str]] | None],
        first: set[tuple[Change, str]],
    ) -> set[tuple[Change, str]] | None:
        """Fold follow-up batches into ``first`` while something big is landing.

        A batch below :attr:`coalesce_threshold` is returned as is. A larger
        one keeps absorbing further batches until the queue has been quiet
        for :attr:`settle_ms`, or :attr:`max_coalesce_ms` has passed in
        total. Returns ``None`` when the producer signalled shutdown.
        """
        merged = set(first)
        if len(merged) < self.coalesce_threshold:
            return merged
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.max_coalesce_ms / 1000
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return merged
            try:
                more = await asyncio.wait_for(
                    queue.get(), timeout=min(self.settle_ms / 1000, remaining)
                )
            except TimeoutError:
                return merged
            if more is None:
                return None
            merged |= more
            self.stats.coalesced += 1

    # ------------------------------------------------------------ batch mapping

    def process_batch(self, raw: Iterable[tuple[Change, str]]) -> list[ChangeEvent]:
        """Translate one raw watchfiles batch into typed events.

        Deleted/added pairs with equal content checksums inside the same batch
        are emitted as a single :class:`NoteMoved`, preserving the permalink.

        Only *external* changes produce events. A change whose content the
        catalog already knows is the engine's own write coming back through
        inotify; the engine published that itself, so re-publishing it here
        would make every write index twice. Those are counted as ``echoes``.
        """
        root = self.engine.root
        added: list[str] = []
        modified: list[str] = []
        deleted: list[str] = []
        for change, raw_path in raw:
            if change is Change.deleted:
                # A vanished *directory* (a folder renamed or moved out in
                # Obsidian) arrives as one `deleted` for a path that no
                # longer exists and has no note suffix, so `_expand`/
                # `is_vault_content` below would drop it — leaving every
                # note it held in the catalog and the index (issue #357).
                # The catalog still knows those notes: report each of them
                # deleted, which also lets `_detect_moves` pair them by
                # checksum with the files that appeared under the new name.
                children = self._catalog_children(root, Path(raw_path))
                if children:
                    deleted.extend(children)
                    continue
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

    def _catalog_children(self, root: Path, path: Path) -> list[str]:
        """Catalog paths under ``path`` when ``path`` is gone and was a folder.

        Empty for a path that still exists (an ordinary file event), for a
        path the catalog knows as a *note* (an ordinary delete), and for a
        prefix nothing was catalogued under.
        """
        if path.exists():
            return []
        try:
            relative = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:  # pragma: no cover - outside the vault
            return []
        if relative in self.engine.catalog:
            return []
        prefix = relative + "/"
        return sorted(known for known in self.engine.catalog if known.startswith(prefix))

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
            entry = self.engine.known_entry(relative)
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
            old_entry = self.engine.known_entry(previous)
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
            # The writer's view, not the readers' snapshot: inside one batch a
            # file can be reported twice (its folder expanded, then itself),
            # and the second report must see the first one's catalog entry.
            known = self.engine.known_entry(relative)
            entry = self.engine.observe_external_change(relative)
            if entry is None:
                continue
            if known is not None and known.checksum == entry.checksum:
                self.stats.echoes += 1
                continue
            events.append(
                NoteCreated(
                    vault=self.engine.name,
                    external=True,
                    path=relative,
                    permalink=entry.permalink,
                    checksum=entry.checksum,
                )
            )
        return events

    def _modifications(self, modified: list[str]) -> list[ChangeEvent]:
        events: list[ChangeEvent] = []
        for relative in dict.fromkeys(modified):
            known = self.engine.known_entry(relative)
            entry = self.engine.observe_external_change(relative)
            if entry is None:
                continue
            if known is not None and known.checksum == entry.checksum:
                self.stats.echoes += 1
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
            if entry is None:
                # The engine already dropped it from the catalog: its own
                # delete, which it published itself.
                self.stats.echoes += 1
                continue
            events.append(
                NoteDeleted(
                    vault=self.engine.name,
                    external=True,
                    path=relative,
                    permalink=entry.permalink,
                )
            )
        return events
