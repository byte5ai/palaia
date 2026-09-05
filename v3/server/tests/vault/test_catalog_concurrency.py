"""Issue #331: the identity catalog is shared across threads — safely.

Writes mutate the catalog in worker threads under the engine lock. At the
same time :meth:`VaultEngine.resolve` reads it on the event-loop thread ahead
of every edit, move and delete; the doctor's verify and the index rebuild
read it from worker threads of their own; the gateway lists it for search.
Before the fix, one dict served all of them: a rebuild could swap it out
under a write (the write's entry lost), a lookup table could be built from a
catalog a write was still updating (a permalink then minted twice), and any
iteration could raise ``RuntimeError: dictionary changed size during
iteration`` — the index rebuild aborting on it.

Now readers take an immutable snapshot and writers publish a new one when
they are done. These tests drive the exact race the issue describes and pin
the snapshot contract that makes it safe.
"""

from __future__ import annotations

import asyncio
import threading

import pytest
from vault_helpers import EngineFactory, write_raw

from palaia_hub.vault import VaultEngine
from palaia_hub.vault.doctor import VaultDoctor
from palaia_hub.vault.models import Note

pytestmark = pytest.mark.anyio


class _CountingSink:
    def __init__(self) -> None:
        self.rounds = 0
        self.emitted = 0

    def begin(self, vault: str) -> None:
        self.rounds += 1

    def emit(self, note: Note) -> None:
        self.emitted += 1

    def finish(self) -> None:
        pass


async def _seed(engine: VaultEngine, count: int) -> None:
    for index in range(count):
        await engine.write_note(f"seed/n{index:03}", body="seed\n", title=f"Seed {index}")


async def test_a_rebuild_racing_writes_never_raises_and_keeps_every_permalink_unique(
    make_engine: EngineFactory,
) -> None:
    """The acceptance criterion, verbatim: reindex racing ``write_note`` never
    raises and never loses or duplicates a permalink — with a worker thread
    iterating the catalog the whole time, the way the doctor and the curator
    do."""
    engine = await make_engine("race")
    baseline = len(engine.catalog)  # whatever a fresh vault ships with
    # Enough entries that iterating the catalog takes real time — so an
    # in-flight write has every chance to land mid-iteration.
    await _seed(engine, 200)
    doctor = VaultDoctor(engine)
    sink = _CountingSink()

    stop = threading.Event()
    reader_failures: list[BaseException] = []

    def hammer_from_a_thread() -> None:
        while not stop.is_set():
            try:
                sorted(engine.catalog)
                for _entry in engine.catalog.values():
                    pass
                engine.resolve("seed/n000")
            except BaseException as exc:  # noqa: BLE001 - the point is to catch anything
                reader_failures.append(exc)
                return

    reader = threading.Thread(target=hammer_from_a_thread, name="catalog-reader")
    reader.start()

    async def write_a_burst(worker: int) -> None:
        for index in range(12):
            await engine.write_note(
                f"burst/w{worker}-{index}",
                body=f"{worker}/{index}\n",
                title=f"Burst {worker} {index}",
            )

    async def rebuild_repeatedly() -> None:
        for _ in range(6):
            await doctor.reindex(sink)

    async def resolve_from_the_loop() -> None:
        for _ in range(150):
            engine.resolve("seed/n001")
            list(engine.catalog)
            await asyncio.sleep(0)

    try:
        await asyncio.gather(
            *(write_a_burst(worker) for worker in range(4)),
            rebuild_repeatedly(),
            resolve_from_the_loop(),
        )
    finally:
        stop.set()
        reader.join(timeout=10)

    assert reader_failures == [], reader_failures
    assert sink.rounds == 6

    # Nothing lost: the incrementally maintained catalog equals a rebuild
    # from disk, entry for entry.
    live = dict(engine.catalog)
    await engine.refresh()
    assert dict(engine.catalog) == live
    assert len(live) == baseline + 200 + 4 * 12

    # Nothing duplicated: every permalink is claimed exactly once, and every
    # note written resolves by the permalink it was given.
    permalinks = [entry.permalink for entry in live.values()]
    assert len(set(permalinks)) == len(permalinks)
    for entry in live.values():
        assert entry.permalink is not None
        assert engine.resolve(entry.permalink).path == entry.path


async def test_a_snapshot_taken_before_a_write_is_left_untouched_by_it(
    make_engine: EngineFactory,
) -> None:
    """The contract every reader relies on: what ``catalog`` returned stays
    exactly that, however many writes land afterwards."""
    engine = await make_engine("snap")
    shipped = set(engine.catalog)  # whatever a fresh vault ships with
    await engine.write_note("notes/first", body="1\n", title="First")
    before = engine.catalog
    assert set(before) - shipped == {"notes/first.md"}

    await engine.write_note("notes/second", body="2\n", title="Second")
    await engine.delete_note("notes/first")

    assert set(before) - shipped == {"notes/first.md"}, "the old snapshot changed under its holder"
    assert set(engine.catalog) - shipped == {"notes/second.md"}
    with pytest.raises(TypeError):
        before["notes/x.md"] = before["notes/first.md"]  # type: ignore[index]


async def test_resolution_tables_follow_the_snapshot(make_engine: EngineFactory) -> None:
    """A note that exists in the current snapshot resolves by permalink,
    alias and title; one that was removed no longer does — the lookup tables
    are published together with the entries, never rebuilt lazily by a
    reader while a writer is half-way through."""
    engine = await make_engine("tables")
    await engine.write_note(
        "notes/a", body="a\n", title="Alpha", frontmatter={"aliases": ["first-letter"]}
    )
    assert engine.resolve("notes/alpha").path == "notes/a.md"
    assert engine.resolve("first-letter").path == "notes/a.md"
    assert engine.resolve("Alpha").path == "notes/a.md"

    await engine.rename_entity("notes/alpha", "Beta")
    assert engine.resolve("Beta").path == "notes/a.md"
    assert engine.resolve("notes/beta").path == "notes/a.md"
    # The old title lives on as an alias, by the rename contract (§4.2).
    assert engine.resolve("Alpha").path == "notes/a.md"

    await engine.delete_note("notes/beta")
    for reference in ("notes/beta", "Beta", "Alpha", "first-letter", "notes/a"):
        with pytest.raises(Exception, match="no note"):
            engine.resolve(reference)


async def test_an_external_batch_lands_as_one_snapshot(make_engine: EngineFactory) -> None:
    """The watcher applies a batch under ``catalog_batch``: readers see the
    catalog before the batch or after it, never a partially applied one.
    Outside a batch, a single observed change publishes on its own."""
    engine = await make_engine("batch")
    shipped = set(engine.catalog)  # whatever a fresh vault ships with
    write_raw(engine, "ext/one.md", "---\ntitle: One\npermalink: ext/one\n---\n\n1\n")
    write_raw(engine, "ext/two.md", "---\ntitle: Two\npermalink: ext/two\n---\n\n2\n")

    async with engine.lock:
        with engine.catalog_batch():
            engine.observe_external_change("ext/one.md")
            assert "ext/one.md" not in engine.catalog
            engine.observe_external_change("ext/two.md")
            assert "ext/two.md" not in engine.catalog
        assert set(engine.catalog) - shipped == {"ext/one.md", "ext/two.md"}

        write_raw(engine, "ext/three.md", "---\ntitle: Three\npermalink: ext/three\n---\n\n3\n")
        engine.observe_external_change("ext/three.md")
        assert "ext/three.md" in engine.catalog
        assert engine.resolve("ext/three").path == "ext/three.md"


async def test_a_failed_operation_still_publishes_what_it_did_change(
    make_engine: EngineFactory,
) -> None:
    """A move sweeps external edits into the catalog and then fails on the
    filesystem; the readers' snapshot must carry that sweep, not stay at the
    state from before the operation — the publish happens on the way out
    whether the operation succeeded or not."""
    engine = await make_engine("failed")
    await engine.write_note("notes/kept", body="k\n", title="Kept")
    write_raw(engine, "notes/external.md", "---\ntitle: External\npermalink: notes/external\n---\n")
    # A regular file where the move's destination folder would have to be.
    (engine.root / "notes" / "blocker").write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(OSError):
        await engine.move_note("notes/kept", "notes/blocker/kept")

    assert "notes/kept.md" in engine.catalog
    assert "notes/external.md" in engine.catalog
    assert engine.resolve("notes/external").path == "notes/external.md"
