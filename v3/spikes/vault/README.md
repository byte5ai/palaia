# Vault engine spike (SPEC-003)

Throwaway-quality code that proves (or disproves) five load-bearing claims
in [MASTERPLAN.md §5.1](../../MASTERPLAN.md) about the files-as-truth vault
architecture, before [SPEC-102](../../specs/SPEC-102-vault-engine.md) builds
it for real. See [FINDINGS.md](FINDINGS.md) for the answers.

**Self-contained by design:** every script below is a [PEP 723](https://peps.python.org/pep-0723/)
inline-metadata script, runnable directly with [`uv`](https://docs.astral.sh/uv/)
— no `pyproject.toml`, no shared virtualenv, nothing outside this directory.
`uv run <script>.py` resolves and caches each script's own dependencies on
first run. Nothing here touches `v3/pyproject.toml` (it does not exist) or
the repo root.

## Layout

| File | Question | Purpose |
|---|---|---|
| `grammar.py` | — | Shared toy note parser (frontmatter + observations + relations). Not the formal v3 grammar — SPEC-004 owns that. |
| `gen_vault.py` | — | Generates N toy notes (with ~15% forward references, tags, relations). Importable + standalone CLI. |
| `index_lib.py` | — | Build/rebuild a SQLite FTS5 index from a vault dir; search by phrase. |
| `round_trip.py` | Q1 | Generate → index → search → delete DB → rebuild → re-search → diff. |
| `watch_spike.py` | Q2 | `watchfiles`-based watcher; scripted single-edit, rename+edit, and 20-file-burst scenarios with latency measurement. |
| `git_bench.py` | Q3 | Per-commit cost, pygit2 vs `git` subprocess, percommit vs batch mode, at configurable N. |
| `vector_spike.py` | Q4 | `fastembed` + `sqlite-vec`: cold start, per-note embed cost, a rank-fusion hybrid-merge sketch. |
| `writer.py`, `checker.py`, `kill_test.sh` | Q5 | Atomic-write-then-commit loop, repeated SIGKILL at randomized delays, and a post-mortem vault/git/index inspector. |

## Running it

```bash
# Q1 — round trip, at whatever scale you want numbers for
uv run round_trip.py --n 1000
uv run round_trip.py --n 10000

# Q2 — watcher latency
uv run watch_spike.py --n 200 --debounce-ms 200

# Q3 — git cost. Repeat with --backend {pygit2,subprocess} and --mode {percommit,batch}
uv run git_bench.py --n 1000  --backend pygit2
uv run git_bench.py --n 1000  --backend subprocess
uv run git_bench.py --n 10000 --backend pygit2

# Q4 — vector search (slow: ~0.4s/note to embed on this hardware, see FINDINGS.md)
uv run vector_spike.py --n 500

# Q5 — kill -9 atomicity, N trials, results as JSONL + a summary table
./kill_test.sh 25 /tmp/kill_test_results.jsonl
```

## Non-goals (per SPEC-003)

No production quality, no full/formal grammar (SPEC-004 defines it), no
recall logic. The note grammar here is deliberately the minimum needed to
exercise parsing + FTS5 + relations — it is not a preview of the real
format.
