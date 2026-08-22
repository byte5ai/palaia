# SPEC-003 findings: vault engine round-trip proof

All numbers below were measured on this run's container: 4 vCPU, 15 GiB RAM,
Python 3.11.15, `uv` 0.8.17, git 2.43.0, SQLite 3.45.1, `/tmp` on the
container's root filesystem (not tmpfs). Re-running on different hardware
will shift absolute numbers but the *shapes* (round-trip fidelity, git
growth pattern, embed cost dominating everything else, kill-test safety)
should hold. Every number here comes from a script in this directory —
see [README.md](README.md) for exact invocations.

## Q1 — Round-trip: write → index → search → delete DB → rebuild → identical?

**Answer: yes, at every scale tested — 500 / 1,000 / 10,000 notes, search
results identical before and after rebuild in all three runs.**

| N notes | generate | fresh build | rebuild (after `rm db`) | search results | FTS5 db size |
|---|---|---|---|---|---|
| 500 | 0.04 s | 0.284 s | 0.278 s | identical (PASS) | 700 KiB |
| 1,000 | ~0.08 s | 0.591 s | 0.571 s | identical (PASS) | 1.31 MiB |
| 10,000 | 1.44 s | 5.649 s | 5.457 s | identical (PASS) | 12.84 MiB |

Build cost is close to linear (0.57 ms/note at 1k, 0.57 ms/note at 10k) —
mostly parse + insert cost, dominated by per-row `INSERT` statements
without a transaction-batching optimization (this spike does one implicit
transaction per file via autocommit-off default connection; SPEC-102
should batch inserts and it will be materially faster).

**Surprise:** none — this is the one question that came back exactly as
architecturally promised. The "database is disposable" claim in
MASTERPLAN §5.1 holds at 10k notes with zero special-cased recovery logic:
delete the `.db` file, re-run the same build function, get the same
answers back.

**What this changes for SPEC-102/103/104:** nothing structurally — proceed
with FTS5 content tables as planned. SPEC-104 should still batch writes in
one transaction per build (this spike is once-per-row) since that's the
easy 5-10x win visible in the per-note cost above.

## Q2 — External-edit loop: does the watcher pick up changes within ~2s?

**Answer: yes, with enormous margin — ~50-80 ms observed, not the ~2s
budget, at 200 ms debounce.** Ran against a 100-note vault (`watch_spike.py
--n 100 --debounce-ms 200`):

| Scenario | Latency (edit → watcher observes it) | Batches | Notes |
|---|---|---|---|
| Single content edit | 51.5 ms | 1 | well within 2s |
| Rapid rename + edit | 51.4 ms | 1 | reported as one `deleted` + one `added` change in the *same* debounce batch, not two |
| Burst of 20 near-simultaneous edits | 79.5 ms (first == only batch) | 1, 20 changes | all 20 coalesced into a single batch |

**Sane debounce:** 200 ms is already generous relative to observed
latency; even at that setting all three scenarios resolved in under 100 ms
of *watcher-observed* latency, well inside the ~2s target. Editors that
write in multiple syscalls close together (Obsidian's save-as-rename
pattern) do **not** produce a storm of separate reindex events — `watchfiles`
folds them into one batch per debounce window.

**Surprise:** a rename+edit is reported to the consumer as `deleted(old)` +
`added(new)`, not as a `renamed` event — there is no rename event type in
`watchfiles`'s output. A naive reindexer that treats `deleted` as
"forget this permalink" and `added` as "index this as a brand new entity"
will silently **lose the old entity's history/relations** on every
Obsidian-style rename unless the indexer explicitly does checksum-based
move detection (exactly the mitigation basic-memory research flagged,
research/basic-memory.md §2 — "move detection by checksum match").

**What this changes for SPEC-102/103:** SPEC-102's watcher consumer must
implement checksum-based move detection on `deleted`+`added` pairs inside
the *same* debounce batch (cheap: batches are small and same-batch
same-content deleted/added pairs are the common case), not treat them as
independent delete-then-create. This is now a named requirement, not an
optional nice-to-have.

## Q3 — Git layer cost: is one-commit-per-write viable, or is batching needed?

**Answer: commit *latency* stays acceptable even per-write at 10k notes
(≤240 ms), but per-write commits without periodic `git gc` cause
quadratic-looking `.git` growth that is not viable unmanaged past a
few thousand notes. Batching (or gc'ing) fixes it completely.**

### Per-commit latency, one commit per write

| N notes | backend | mean | p50 | p95 | max | `git status` (median) |
|---|---|---|---|---|---|---|
| 50 | pygit2 | 4.8 ms | 4.3 ms | 6.9 ms | 7.3 ms | 3.3 ms |
| 50 | subprocess | 93.6 ms | 93.0 ms | 105.9 ms | 122.5 ms | 3.0 ms |
| 1,000 | pygit2 | 9.2 ms | 8.8 ms | 15.9 ms | 32.2 ms | 5.6 ms |
| 1,000 | subprocess | 94.7 ms | 90.6 ms | 107.6 ms | 1,202.7 ms | 5.6 ms |
| 10,000 | pygit2 | 78.5 ms | 78.6 ms | 152.4 ms | 238.2 ms | 19.5 ms |
| 10,000 | subprocess | 117.8 ms | 113.4 ms | 147.7 ms | 1,876.9 ms | 19.8 ms |

`git status` **does** stay fast (single-digit to low-double-digit
milliseconds even at 10k commits / 10k tracked files) — that specific
worry from the SPEC is unfounded. What is *not* fast is the ~8.5x growth in
pygit2 per-commit latency from 1k→10k (9.2 ms → 78.5 ms mean): index
add-all + write rescans the whole working tree every call, so per-commit
cost grows with vault size, not just commit count. subprocess's overhead is
dominated by process-spawn cost (~90 ms baseline) at small N but the same
rescan effect pushes it up too (94.7 ms → 117.8 ms).

### Repo size: this is the real problem with naive one-commit-per-write

| N notes, mode | backend | working-tree+.git size | `.git` alone |
|---|---|---|---|
| 1,000, percommit | pygit2 | 13.9 MiB | **13.4 MiB** |
| 1,000, batch (1 commit) | pygit2 | 1.0 MiB | 0.43 MiB |
| 10,000, percommit | pygit2 | 1,255.3 MiB (1.17 GiB) | **1,249.7 MiB (1.16 GiB)** |
| 10,000, percommit | subprocess | 148.2 MiB | **142.6 MiB** |
| 10,000, batch (1 commit) | pygit2 | 10.07 MiB | 4.51 MiB |
| 10,000, batch (1 commit) | subprocess | 10.09 MiB | 4.54 MiB |

**Surprise #1:** at 10k notes, one-commit-per-write with **pygit2** bloats
`.git` to **1.16 GiB** for a vault whose actual content is ~10 MiB — a
~116x blow-up, and the pattern (13.4 MiB at 1k → 1,249.7 MiB at 10k, a
~93x increase for a 10x increase in N) is consistent with each commit
writing an unpacked tree object listing the entire (growing) flat
directory, i.e. **O(n²) loose-object growth** for one-commit-per-write into
a flat directory, not O(n). This is the actual scaling risk the SPEC asked
about — not commit latency.

**Surprise #2:** the **subprocess `git`** backend does *not* show the same
blow-up (142.6 MiB vs pygit2's 1.16 GiB for the identical 10k-commit
workload) despite being slower per commit. The most likely explanation is
git's built-in `gc.auto` housekeeping (default threshold ~6,700 loose
objects) firing transparently partway through the 10,000 commit
invocations and incrementally repacking — a safety net porcelain `git`
gives you for free that **libgit2 (pygit2) does not**. This is a concrete
backend trade-off, not just a speed one.

**Confirmed fix — `git gc` recovers the bloat completely:** ran
`git gc --aggressive` (via `git_gc_bench.py`) against the 1k-note
pygit2 percommit repo:

```
git_dir_bytes_before: 13,389,707  (13.4 MiB)
git_dir_bytes_after:   1,231,076  (1.23 MiB)
gc_seconds: 1.77
shrink_ratio: 10.9x
```

**Verdict: one-commit-per-write is viable, but only paired with periodic
`git gc`** (either scheduled, or delegate to `git` subprocess and rely on
its `gc.auto`, or both). Pure in-process libgit2 with no gc plan is not
viable past low thousands of notes on flat storage.

**What this changes for SPEC-102:** (1) do not call an unconditional
index add-all + write-tree on the *whole* index every write — stage
only the changed path(s) to keep per-commit cost flat instead of growing
with vault size; (2) schedule `git gc --auto` (cheap, incremental) after
every N commits or on a timer, and document the loose-object bloat as an
explicit operational concern, not an edge case; (3) prefer sharding notes
into subdirectories (e.g. by first two chars of permalink hash) over one
flat directory once vault size is expected to exceed a few thousand notes,
since tree-object cost per commit scales with *directory* size, not vault
size, if sharded.

## Q4 — Vector search: fastembed + sqlite-vec cold-start, per-note cost, hybrid sketch

Ran against a 500-note vault (`vector_spike.py --n 500`), model
`BAAI/bge-small-en-v1.5` (fastembed's default, dim 384), matching the
research dossier's stated default.

| Metric | Value |
|---|---|
| Cold start (embedding-model object construction, model already cached) | 0.59 s |
| Embed cost, 500 notes (title+body+observations text) | 218.6 s total → **437.3 ms/note** |
| sqlite-vec insert cost | 0.031 ms/note (negligible) |
| Query embed (single query string) | 107.8 ms |
| vec0 kNN search (top 10, 500 rows) | 1.27 ms |
| FTS5 search (top 10, 500 rows) | 5.6 ms |
| DB size, FTS5 only | 696 KiB |
| DB size, FTS5 + 500×384-dim float vectors | 2.24 MiB |

**Surprise (the big one):** embedding is **by far** the slowest operation
in this entire spike — 437 ms/note, roughly **1,500x slower than the FTS5
index build** (0.57 ms/note) on the same hardware. Extrapolated (not
re-measured, since a real run would take this long): embedding 1,000 notes
would take **~7.3 minutes**; 10,000 notes **~73 minutes**, serially,
single-threaded, on this 4-vCPU container. This is a hard operational
constraint the masterplan's "hybrid search by default" language does not
currently price in.

**Hybrid merge sketch:** implemented simple rank-fusion
(`score = 1/(rank_fts+1) + 1/(rank_vec+1)`), confirmed it runs and produces
a merged top-10 that differs from either individual ranking (FTS and
vector top-10 for the same query shared only 2 of 10 results before
fusion) — proof of concept only, no claim this is the right fusion formula
(SPEC-104's job).

**What this changes for SPEC-102/103/104:** (1) embedding cannot run
synchronously on the write path if "synchronous writes" (MASTERPLAN §5.1)
is to remain true for perceived latency — FTS indexing can stay on the
synchronous path (sub-millisecond), but vector embedding needs to be
async/deferred/batched-in-the-background from day one, not treated as a
"just add embeddings too" afterthought; (2) initial vault import / first-run
cold-embed of an existing large vault (e.g. a basic-memory import) is a
multi-minute-to-multi-hour operation at realistic vault sizes and needs a
visible progress/background-job story in SPEC-111; (3) investigate
fastembed batch-size/thread tuning or a smaller/faster model before
committing to `bge-small-en-v1.5` as *the* default — 437 ms/note on 4
vCPUs is worth a follow-up spike of its own before SPEC-104 locks it in.

## Q5 — Atomicity: does `kill -9` during a write burst ever corrupt the vault?

**Answer: no corruption in 28 trials (3 smoke + 25 full run) of the
write-then-commit loop, with kill delays randomized across 0.05-1.2s to
land at different points in the loop.** Method
(`writer.py` + `checker.py` + `kill_test.sh`): loop of
{write to temp file in the vault dir → fsync → atomic rename into place →
git add/commit via pygit2}, SIGKILLed from outside at a
randomized point, then inspected.

25-trial aggregate (`./kill_test.sh 25`):

| Check | Result |
|---|---|
| Vault corrupt (truncated/unparseable note, or index rebuild crashed) | **0 / 25** |
| Zero-byte or partially-written `.md` files | **0 / 25** |
| Stray orphaned temp files left behind (expected/harmless — a write-in-flight when killed, never renamed into place) | 7 / 25 trials, always exactly 1 |
| git/libgit2 index lock left behind (kill landed mid index-write) | **2 / 25** |
| ...of those, was removing the stale lock file alone sufficient to recover? | **2 / 2 (100%)** — no further repair needed |
| SQLite index rebuildable from files after the kill, with entity count == on-disk `.md` file count | **25 / 25** |

**Commands used** (see `kill_test.sh` in full): for each trial, launch
`uv run writer.py --vault-dir <unique tmp dir> --n 200000 &`, `sleep
<seed-derived random 0.05-1.2s delay>`, then `pkill -9 -f "writer.py
--vault-dir <that dir>"` (looped up to 10x100ms to confirm the process
tree is actually gone — see surprise below), then
`uv run checker.py --vault-dir <dir> ...`.

**Surprise:** `uv run <script>.py &`, backgrounded from bash and killed by
its `$!` PID, does **not** kill the actual work — `uv run` execs a *child*
Python interpreter process rather than replacing itself on this platform
(confirmed with process listing: the `uv run writer.py` PID and the real
python-interpreter `writer.py` PID are different processes, parent/child).
The first version of this test killed only the `uv` wrapper, leaving the
real writer alive and racing the checker — it produced internally
inconsistent-looking results (fewer `.md` files present than the writer's
own progress log claimed to have confirmed) purely from that race, not
from any real corruption. Fixed by matching-and-killing on the unique
`--vault-dir` argument via `pkill -9 -f`, confirmed dead before inspecting.
**This is a real gotcha for anyone building process-supervision or crash
tests around `uv run`-launched processes, not specific to this spike.**

**What this changes for SPEC-102:** the write protocol (temp file, fsync,
atomic rename) as described in MASTERPLAN §5.1 is validated — no note
file was ever observed corrupted or partially written across 25 kill
trials. The one real operational finding: **pygit2's index-write path can
leave a stale index-lock file after a kill** (8% of trials here) that
blocks further git operations until removed; SPEC-102's hub startup
sequence must check for and clear a stale lock file (with a
staleness/liveness check — not blindly delete one belonging to a live
process) as a normal part of crash recovery, not an exceptional path. No
other repair was ever needed in any trial — a doctor/rebuild-from-files
step as designed is sufficient beyond that.

## Summary: what changes for SPEC-102/103/104

1. **Round-trip and crash-safety claims hold as designed** — no changes to
   the core files-as-truth model. (Q1, Q5)
2. **Watcher must do checksum-based move detection** on same-batch
   delete+add pairs — `watchfiles` reports renames as delete+add, not as a
   rename event. (Q2)
3. **Git layer needs an explicit gc plan and narrower per-write staging** —
   naive add-all-every-write is roughly quadratic in loose-object growth
   and linear-growing in per-commit latency; stage only the changed path,
   and schedule `git gc` (or shell out to `git` and lean on its
   `gc.auto`). Startup must clear a stale index lock file as routine crash
   recovery. (Q3, Q5)
4. **Vector embedding cannot be on the synchronous write path** — at
   ~437 ms/note on modest hardware it is 2-3 orders of magnitude slower
   than everything else measured here; needs an async/background job
   design from SPEC-102 onward, and the default model choice deserves its
   own follow-up spike before SPEC-104 locks it in. (Q4)
