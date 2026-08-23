"""Write latency and repository growth — the SPEC-003 scaling bindings.

Two properties are asserted here at a size that fits a normal test run:

* **Commit latency stays flat as the vault grows.** The spike's failure mode
  was staging the whole index on every write (pygit2 ``add_all``: 9.2 ms at
  1k notes → 78.5 ms at 10k). Staging only changed paths makes per-write cost
  independent of vault size.
* **Repository size stays bounded.** One commit per write produces loose
  objects quadratically; the gc policy is what keeps ``.git`` proportional to
  content.

The full-scale numbers (10k notes) come from the same code paths, gated
behind ``PALAIA_VAULT_SCALE`` so a normal ``pytest`` run stays quick:

    PALAIA_VAULT_SCALE=10000 uv run pytest server/tests/vault/test_performance.py -s -k scale
"""

from __future__ import annotations

import os
import statistics
import time

import pytest
from conftest import TEST_ATTRIBUTION, EngineFactory

from palaia_hub.vault import VaultEngine

pytestmark = pytest.mark.anyio

#: Notes seeded into the vault before the scale run measures anything.
SCALE = int(os.environ.get("PALAIA_VAULT_SCALE", "0"))

#: Engine writes (one commit each) performed by the scale run. 10_000 is the
#: SPEC's gc-policy criterion; 200 is enough for a latency reading.
SCALE_WRITES = int(os.environ.get("PALAIA_VAULT_SCALE_WRITES", "200"))


def note_text(index: int) -> str:
    return (
        f"---\ntitle: Bulk {index}\npermalink: bulk/note-{index:05d}\ntype: note\n---\n\n"
        f"- [index] {index}\n- relates_to [[Bulk {max(index - 1, 0)}]]\n"
    )


def seed_notes(engine: VaultEngine, count: int, *, start: int = 0) -> None:
    """Create ``count`` notes on disk and commit them in one go.

    Deliberately not one commit per note: this is test *setup*, standing in
    for a vault that already has history, not the behaviour under test.
    """
    folder = engine.root / "bulk"
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(start, start + count):
        (folder / f"note-{index:05d}.md").write_text(note_text(index), encoding="utf-8")


async def measure_writes(engine: VaultEngine, count: int, *, prefix: str) -> list[float]:
    timings: list[float] = []
    for index in range(count):
        started = time.perf_counter()
        await engine.write_note(
            f"measured/{prefix}-{index:04d}",
            title=f"Measured {prefix} {index}",
            body=f"- [n] {index}\n",
            attribution=TEST_ATTRIBUTION,
        )
        timings.append((time.perf_counter() - started) * 1000)
    return timings


def measure_raw_git_baseline(engine: VaultEngine, count: int) -> float:
    """p50 of a bare ``status`` + ``add`` + ``commit`` loop on this machine.

    This is what SPEC-003's per-write budget actually measured: one commit per
    write through porcelain git. Measuring it in the same run makes the
    engine's own overhead visible independently of hardware.
    """
    timings: list[float] = []
    folder = engine.root / "baseline"
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        relative = f"baseline/b{index:04d}.md"
        (engine.root / relative).write_text(f"raw {index}\n" + "x" * 200, encoding="utf-8")
        started = time.perf_counter()
        engine.git.status()
        engine.git.commit_paths([relative], f"bench: raw {index}", TEST_ATTRIBUTION)
        timings.append((time.perf_counter() - started) * 1000)
    return statistics.median(timings)


async def test_commit_latency_stays_flat_as_the_vault_grows(
    make_engine: EngineFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = await make_engine("work")
    seed_notes(engine, 40)
    await engine.commit_external_changes()
    await engine.refresh()
    small = await measure_writes(engine, 12, prefix="small")

    seed_notes(engine, 800, start=40)
    await engine.commit_external_changes()
    await engine.refresh()
    assert len(engine.catalog) > 800
    large = await measure_writes(engine, 12, prefix="large")

    small_p50 = statistics.median(small)
    large_p50 = statistics.median(large)
    with capsys.disabled():
        print(
            f"\nwrite p50: {small_p50:.1f} ms at 40 notes, {large_p50:.1f} ms at 840 notes "
            f"(ratio {large_p50 / small_p50:.2f})"
        )
    # A 21x bigger vault must not cost materially more per write. The bound is
    # loose enough for CI noise but far below the growth add-all would show.
    assert large_p50 < small_p50 * 2.5


async def test_repo_size_stays_bounded_under_sustained_writes(
    make_engine: EngineFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = await make_engine("work")
    await measure_writes(engine, 250, prefix="growth")

    before = engine.git.size_bytes()
    await engine.gc()
    content = engine.git.content_size_bytes()
    after = engine.git.size_bytes()
    with capsys.disabled():
        print(
            f"\n250 writes: .git {before / 1e6:.2f} MB before gc, {after / 1e6:.2f} MB after, "
            f"content {content / 1e6:.2f} MB (ratio {after / content:.2f}x)"
        )
    # The gc policy must actually reclaim: loose objects from one commit per
    # write are the growth the spike measured.
    assert after <= before * 0.6
    # At this size the *content* is only ~60 KB while 250 commit+tree objects
    # are irreducible metadata, so the SPEC's ~2x-of-content bound is measured
    # by the scale run below (10k writes), not here.
    assert after <= 6 * content


@pytest.mark.skipif(
    SCALE < 1000 and SCALE_WRITES < 1000,
    reason="set PALAIA_VAULT_SCALE / PALAIA_VAULT_SCALE_WRITES to run the scale bench",
)
async def test_scale_write_latency_and_repo_size(
    make_engine: EngineFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    """Full-scale run: write p50 in a large vault, and gc-bounded repo size."""
    engine = await make_engine("scale")
    started = time.perf_counter()
    if SCALE:
        seed_notes(engine, SCALE)
        await engine.commit_external_changes()
        await engine.refresh()
    seeded = time.perf_counter() - started

    baseline = measure_raw_git_baseline(engine, 15)
    timings = await measure_writes(engine, SCALE_WRITES, prefix="scale")
    ordered = sorted(timings)
    p50 = statistics.median(ordered)
    p95 = ordered[int(len(ordered) * 0.95) - 1]

    before = engine.git.size_bytes()
    await engine.gc()
    content = engine.git.content_size_bytes()
    after = engine.git.size_bytes()
    with capsys.disabled():
        print(
            f"\nscale={SCALE} writes={SCALE_WRITES}: seed+index {seeded:.1f}s | "
            f"write p50 {p50:.1f} ms, p95 {p95:.1f} ms, max {ordered[-1]:.1f} ms | "
            f"raw git baseline p50 {baseline:.1f} ms (engine overhead "
            f"{(p50 / baseline - 1) * 100:.0f}%) | .git {before / 1e6:.1f} MB -> "
            f"{after / 1e6:.1f} MB, content {content / 1e6:.1f} MB "
            f"(ratio {after / content:.2f}x)"
        )
    # SPEC-003's budget is the cost of one-commit-per-write through porcelain
    # git (measured there as 113.4 ms p50 at 10k notes on the spike's
    # container; its findings state absolute numbers shift with hardware while
    # the shapes hold). The budget is therefore taken relative to the same
    # baseline measured on *this* machine: the engine may add at most 20% on
    # top of a bare status+add+commit loop.
    assert p50 < baseline * 1.2
    assert after <= 2 * content
