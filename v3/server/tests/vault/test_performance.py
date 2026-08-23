"""Write latency and repository growth — the SPEC-003 scaling bindings.

Two properties are asserted here at a size that fits a normal test run:

* **Commit latency stays flat as the vault grows.** The spike's failure mode
  was staging the whole index on every write (pygit2 ``add_all``: 9.2 ms at
  1k notes → 78.5 ms at 10k). Staging only changed paths makes per-write cost
  independent of vault size.
* **Repository size stays bounded.** One commit per write produces loose
  objects quadratically; the gc policy is what keeps ``.git`` proportional to
  content.

Notes are laid out in shard directories of ~200 files and are of realistic
size, matching both the format spec's §1 layout guidance ("keep directories
under ~500 files — git tree-object cost per commit scales with directory
size") and the SPEC-003 fixture. Both choices are load-bearing, and getting
them wrong was measured here first: a 10k-write run into **one flat
directory** with toy-sized notes ended at write p50 145 ms and a post-gc
``.git`` of 10.9 MB against 2.5 MB of content (4.45x), because every commit
rewrites a tree object listing all 10k entries and because git's fixed
overhead dwarfs 110-byte notes. The doctor reports oversized directories
(``directory-large``) so a real vault cannot drift into that case unnoticed.

The full-scale numbers come from the same code paths, gated behind env vars so
a normal ``pytest`` run stays quick:

    # write latency in a 10k-note vault
    PALAIA_VAULT_SCALE=10000 uv run pytest server/tests/vault/test_performance.py -s -k scale
    # gc policy over a 10k-write run
    PALAIA_VAULT_SCALE_WRITES=10000 uv run pytest server/tests/vault/test_performance.py -s -k scale
"""

from __future__ import annotations

import os
import statistics
import time

import pytest
from vault_helpers import TEST_ATTRIBUTION, EngineFactory

from palaia_hub.vault import VaultEngine

pytestmark = pytest.mark.anyio

#: Notes seeded into the vault before the scale run measures anything.
SCALE = int(os.environ.get("PALAIA_VAULT_SCALE", "0"))

#: Engine writes (one commit each) performed by the scale run. 10_000 is the
#: SPEC's gc-policy criterion; 200 is enough for a latency reading.
SCALE_WRITES = int(os.environ.get("PALAIA_VAULT_SCALE_WRITES", "200"))


#: Files per shard directory — under the format spec's ~500 guidance (§1).
SHARD_SIZE = 200

#: SPEC-003 Q3's measured per-write budget: p50 of one commit per write
#: through porcelain git at 10k notes.
SPEC003_WRITE_P50_MS = 113.4


def shard(prefix: str, index: int) -> str:
    """Return a vault-relative path in a shard directory of SHARD_SIZE files."""
    return f"{prefix}/{index // SHARD_SIZE:03d}/note-{index:05d}.md"


#: A realistically sized note body (~500 bytes), matching the SPEC-003
#: fixture. Note size matters for the repository-size criterion: with
#: 100-byte toy notes, git's own fixed overhead (the index file, the reflog)
#: dwarfs the content and makes the ratio meaningless.
def note_body(index: int) -> str:
    return (
        f"# Bulk {index}\n\n"
        "Files are the only truth: the index is derived, the vault is not. This "
        "note exists to give the benchmark a body of realistic size so that "
        "repository growth is measured against realistic content.\n\n"
        "## Observations\n"
        f"- [index] {index} #bench\n"
        "- [rate-limit] 100 req/min (set during the load test)\n"
        "- [decision] one commit per write, with a gc policy behind it\n\n"
        "## Relations\n"
        f"- relates_to [[Bulk {max(index - 1, 0)}]]\n"
        f"- part_of [[Shard {index // SHARD_SIZE}]]\n"
    )


def note_text(index: int) -> str:
    return (
        f"---\ntitle: Bulk {index}\npermalink: bulk/note-{index:05d}\ntype: note\n"
        f"tags: [bench]\n---\n\n" + note_body(index)
    )


def seed_notes(engine: VaultEngine, count: int, *, start: int = 0) -> None:
    """Create ``count`` notes on disk and commit them in one go.

    Deliberately not one commit per note: this is test *setup*, standing in
    for a vault that already has history, not the behaviour under test.
    """
    for index in range(start, start + count):
        path = engine.root / shard("bulk", index)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(note_text(index), encoding="utf-8")


async def measure_writes(engine: VaultEngine, count: int, *, prefix: str) -> list[float]:
    timings: list[float] = []
    for index in range(count):
        started = time.perf_counter()
        await engine.write_note(
            shard(f"measured-{prefix}", index),
            title=f"Measured {prefix} {index}",
            body=note_body(index),
            attribution=TEST_ATTRIBUTION,
        )
        timings.append((time.perf_counter() - started) * 1000)
    return timings


def measure_raw_git_baseline(engine: VaultEngine, count: int, *, prefix: str) -> float:
    """p50 of a bare ``status`` + ``add`` + ``commit`` loop on this machine.

    This is what SPEC-003's per-write budget actually measured: one commit per
    write through porcelain git. Measuring it in the same run makes the
    engine's own overhead visible independently of hardware.
    """
    timings: list[float] = []
    for index in range(count):
        relative = shard(prefix, index)
        path = engine.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(note_text(index), encoding="utf-8")
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
    # gc never makes it worse, and the repository stays proportional to
    # content. The bound is looser than the SPEC's ~2x because at 250 notes
    # git's fixed overhead (index file, reflog) is still a large share of a
    # small repository; the SPEC's bound is asserted by the scale run below.
    assert after <= before
    assert after <= 3 * content


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

    # The raw-git cost of one commit per write is sampled on both sides of the
    # engine's writes: before them (this vault size, shallow history) and after
    # (same size, deeper history). The "after" sample is the like-for-like
    # comparison for the engine's own overhead; the cheaper of the two is the
    # sanity floor, since no engine can be faster than the git it calls.
    baseline_before = measure_raw_git_baseline(engine, 15, prefix="baseline-pre")
    timings = await measure_writes(engine, SCALE_WRITES, prefix="scale")
    baseline_after = measure_raw_git_baseline(engine, 15, prefix="baseline-post")
    baseline = min(baseline_before, baseline_after)
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
            f"engine write p50 {p50:.1f} ms, p95 {p95:.1f} ms, max {ordered[-1]:.1f} ms "
            f"(SPEC-003 budget {SPEC003_WRITE_P50_MS * 1.2:.1f} ms) | raw git p50 "
            f"{baseline_before:.1f} ms before / {baseline_after:.1f} ms after the writes | "
            f"engine vs raw-after {(p50 / baseline_after - 1) * 100:+.0f}% | "
            f".git {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB, content "
            f"{content / 1e6:.1f} MB (ratio {after / content:.2f}x)"
        )
    # SPEC-003's budget: 113.4 ms p50 for one-commit-per-write through
    # porcelain git at 10k notes, +20% tolerance. The raw-git baseline is
    # printed alongside so the engine's own share stays visible — it is
    # context, not the bar; the bar is the SPEC's number.
    assert p50 < SPEC003_WRITE_P50_MS * 1.2
    assert baseline < p50  # sanity: the engine cannot be cheaper than raw git
    assert after <= 2 * content
