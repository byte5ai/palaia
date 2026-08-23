# palaia_hub

Python core of the palaia v3 hub daemon.

## What's here (SPEC-101)

- `palaia_hub.app.create_app()` — FastAPI app factory serving `/api/health`
  and `/api/info`, plus (SPEC-105, below) an optional `gateway=` parameter
  that mounts the MCP gateway. Auth and persistence land in SPEC-108,
  SPEC-102 respectively.
- `palaia_hub.config` — single `config.yaml` in a platform data dir
  (override with `PALAIA_HOME`), pydantic-validated, with `PALAIA_*` env
  overrides. Precedence: defaults < file < env. Zero-config first run
  creates a commented default file. Invalid config fails startup with a
  message naming the file, the key, and a fix.
- `palaia_hub.logging` — structured logging (human default, JSON via
  `log_format: json`), per-component levels, and a mandatory redaction
  filter that masks tokens/keys/secrets/passwords before they reach output.
- `palaia_hub.cli` — the `palaia-hub` console script; `palaia-hub serve`
  runs the app under uvicorn with graceful shutdown (in-flight requests
  finish before the process exits on SIGTERM/SIGINT).
- `palaia_hub.__version__` is the single source of version truth;
  `pyproject.toml` reads it back dynamically via `[tool.hatch.version]`
  rather than restating it.

<<<<<<< HEAD
## Dashboard shell support (SPEC-109)

- `palaia_hub.events` — `/api/events`, a Server-Sent Events stream:
  periodic `health` snapshots plus `vault_changed` events from a
  filesystem watcher (opt-in via `PALAIA_WATCH_DIR`; unset means health
  events only — no error). Self-contained: it defines its own tiny
  in-process event bus rather than depending on SPEC-102's vault engine
  bus, since the two SPECs run in parallel on this package.
- `palaia_hub.static` — serves the dashboard's `npm run build` output
  (`v3/web/dist` by default, overridable via `PALAIA_WEB_DIST`) with SPA
  fallback, mounted last so `/api/*` always wins. Serving is optional: a
  checkout without a frontend build still starts with zero config.
=======
## MCP gateway (SPEC-105)

`palaia_hub.gateway` builds the streamable-HTTP MCP endpoint: one memory
tool family (`search`/`read`/`write`/`edit`/`move`/`delete`/`list`/
`recent_activity`) per configured vault, mounted into one or more
addressable profiles (`/mcp/<profile>`). It is written against a narrow
`VaultService` protocol, not against SPEC-102's vault engine directly (the
two lanes run in parallel; real wiring is SPEC-113's job) — tests use the
in-memory `FakeVaultService`.

```python
from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.gateway import (
    FakeVaultService, GatewayConfig, ProfileConfig, VaultMountConfig, build_gateway,
)

config = GatewayConfig(
    vaults=[VaultMountConfig(key="work", name="work", purpose="Team knowledge.")],
    profiles=[ProfileConfig(path="default", vaults=["work"])],
)
gateway = build_gateway(config, {"work": FakeVaultService()})
app = create_app(HubConfig(), gateway=gateway)  # /mcp/default now live
```

Building blocks: `gateway/vault_protocol.py` (the protocol + result types),
`gateway/memory_tools.py` (one vault's tool family — annotations, alias
absorption, dual text/json output, IDENTITY instructions,
`ai_assistant_guide` resource), `gateway/naming.py` (tool-name
sanitization and the FastMCP `mount()` pre-namespace rename composition
rule — see its module docstring), `gateway/build.py` (assembles
per-profile `FastMCP` instances + combined lifespans per
`v3/spikes/gateway/FINDINGS.md`).


## The vault engine (SPEC-102)

`palaia_hub.vault` — the memory core. Files are the only truth
([vault format v1.0](../docs/vault-format.md)); the database that lands in
SPEC-104 is a disposable index.

- `VaultRegistry` — many vaults, physically isolated (own directory, own git
  history, own `.palaia/` storage). Pointers live in `vaults.yaml` under the
  hub home; names and purposes come from each vault's `meta/vault.md`.
- `VaultEngine` — `write_note` / `read_note` / `edit_note` / `move_note` /
  `delete_note` / `list_dir` / `history`, plus `rename_entity` (new
  title+permalink, old ones kept as aliases, **every** inbound wikilink
  rewritten, all in one commit). Writes are synchronous write-through: tmp
  file → fsync → atomic rename → fsync dir → one attributed git commit.
  `edit_note` takes the checksum you read, so a concurrent writer gets a
  conflict instead of silently losing an edit.
- `VaultWatcher` — debounced `watchfiles` watching with **checksum-based move
  detection**: an external rename arrives as `deleted`+`added` in one batch
  and is emitted as a single `NoteMoved`, keeping the note's identity.
- `vault.events` — the typed change-event vocabulary and an in-process bus
  stub (the real bus is Phase 2).
- `VaultDoctor` — `verify()` findings (stale git locks, permalink problems,
  partial renames, dangling links, repo bloat, file↔index drift against the
  SPEC-104 `IndexView` interface), `repair()` for the safe repairs, and
  `reindex(sink)` as the rebuild-from-files hook.
- Git backend: porcelain `git` via subprocess, staging **only changed paths**,
  with an explicit gc policy (`gc.auto` far below git's default plus a
  scheduled `git gc`) — both bindings from the SPEC-003 findings. A vault
  repository the engine creates also gets `commit.gpgsign=false`: a vault
  commits on every write, and an inherited global signing program on that path
  multiplies write latency and adds an outside failure mode. Set it back in
  the vault repo if you want signed history — the engine writes the default
  only at creation and never reconfigures a repository it adopts.

Scale knobs for the performance tests:

```bash
PALAIA_KILL_TRIALS=25 uv run pytest server/tests/vault/test_kill_safety.py
PALAIA_VAULT_SCALE=10000 uv run pytest server/tests/vault/test_performance.py -s -k scale
PALAIA_VAULT_SCALE_WRITES=10000 uv run pytest server/tests/vault/test_performance.py -s -k scale
```
>>>>>>> claude/palaia-major-rewrite-lj5v9x

## Index & hybrid search (SPEC-104)

`palaia_hub.index` — the disposable projection over one vault: SQLite (WAL)
with FTS5 over notes, observations and relations, sqlite-vec KNN over chunk
embeddings, and metadata filters (scope, type, tags, dates, custom
frontmatter keys). Drop the file at any time; `reindex` rebuilds it from
files and reproduces identical query results.

```python
from palaia_hub.index import VaultIndex
from palaia_hub.vault import EventBus, VaultEngine

engine = VaultEngine(path, "work", bus=EventBus())
await engine.open()
index = VaultIndex(engine)      # embeddings on by default
await index.open()              # builds, subscribes to change events, starts the embed worker
results = await index.search("who owns the gateway?", mode="hybrid", limit=5)
index.status()                  # notes/observations/relations + embed backlog
```

- **Modes** `fts | vector | hybrid`. Hits are addressable below note
  granularity: an observation hit carries its synthetic permalink
  (`<permalink>/obs/<category>/<h8>`, format spec §9.2).
- **Embeddings are always off the write path.** SPEC-003 measured 437 ms to
  embed a note versus 0.6 ms to FTS-index it, so a write acks once chunks are
  written as `pending` and a background worker drains them. Any query issued
  meanwhile answers from FTS and says so (`SearchResults.degraded`).
- **Default model** `sentence-transformers/all-MiniLM-L6-v2`, chosen by
  benchmark (~10x faster than `bge-small-en-v1.5` at the same 384 dims on 4
  vCPUs). Re-measure on your hardware:
  `uv run python -m palaia_hub.index.bench --notes 200`.
- **Incremental** from SPEC-102's change events, including forward references:
  `- depends_on [[Q3 Roadmap]]` stays unresolved until a note answering to
  that name appears, then resolves without a reindex.
- **Doctor** — `index.verify()` runs SPEC-102's checks plus file↔index drift;
  `index.reindex()` is the rebuild-from-files path.
- Embeddings need the `embeddings` extra (`fastembed`); without it the index
  is FTS-only and reports why.

## Running it

```bash
cd v3
uv run palaia-hub serve
```

Then `curl http://127.0.0.1:8420/api/health`.
