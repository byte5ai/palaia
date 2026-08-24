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
## MCP gateway (SPEC-105)

`palaia_hub.gateway` builds the streamable-HTTP MCP endpoint: one memory
tool family (`search`/`read`/`write`/`edit`/`move`/`delete`/`list`/
`recent_activity`, plus `capture`/`inbox_status` from SPEC-107 and
`recall`/`build_context` from SPEC-106) per configured vault, mounted into one
or more addressable profiles (`/mcp/<profile>`). It is written against a narrow
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

## Recall, traversal & context assembly (SPEC-106)

`palaia_hub.recall` — the intelligence layer *on top of* SPEC-104's search:
`memory://` addressing, decay-scored ranking, per-model variants, read-time
value references, and token-budgeted graph traversal. Two MCP tools
(`recall`, `build_context`) join the memory tool family; both are read-only.

```python
from palaia_hub.recall import RecallService

recall = RecallService(index, vault="work")
await recall.recall(query="how do we write commit messages", model="anthropic/opus-5")
await recall.recall(ref="memory://glossary/pricing")     # or a title, path, or glob
await recall.build_context(ref="projects/recall-engine", depth=2, max_tokens=4000)
```

- **`memory://` resolution** (format spec §3.2) in one fixed order: exact
  permalink → alias → exact title → unique path suffix. Ambiguity is an error
  listing the candidates, never a silent pick. Also globs (`projects/api-*`,
  `**`), block anchors (`note#^anchor`) and synthetic sub-note permalinks
  (`.../obs/...`, `.../rel/...`).
- **Decay-scored ranking** — relevance enters as its *reciprocal rank* (the
  one quantity all three retrieval modes agree on), multiplied by
  `1 + w_r·recency + w_a·access + w_s·significance`. Logical only: nothing on
  disk moves. Weights live in `config.yaml`'s `recall:` section; the bound is
  deliberate — decay reshuffles the top of the page and cannot overturn a
  large relevance gap.
- **Per-model variants** (§5.1) — `[how-to-apply | anthropic/opus-5]` resolves
  to the most specific applicable line: exact model > provider family >
  scopeless base; unknown model → base; a scoped-only group serves a
  non-matching caller nothing. A pure function
  (`palaia_hub.recall.variants`), table-tested.
- **Value references resolved at read time** (§5.3) — `![[Base Rate#^rate]]`
  shows the current source value in `recall` and `read` output, with
  `⟦missing: …⟧` / `⟦cycle: …⟧` / `⟦depth: …⟧` markers and their warnings for
  the three failure modes. The corpus scenarios in
  `docs/vault-format-conformance/resolution/` are the byte-exact contract.
- **`build_context`** walks relations in both directions with depth and
  timeframe limits, cycle-safe and deduplicated, then fits the result into
  `max_tokens` by *degrading* notes (full → title + key observations → one
  naming line) rather than cutting any note mid-body. It never returns
  nothing when something matched.
- **Ranking battery** — `server/tests/fixtures/ranking-battery.json` holds the
  expected top-3 per query over the golden vault, with the judgment each row
  encodes. Run it with
  `uv run pytest server/tests/recall/test_ranking_battery.py`.

## OAuth 2.1 authorization server (SPEC-203)

`palaia_hub.oauth` turns the hub into an authorization server *and* resource
server, so claude.ai, ChatGPT and mobile apps connect as ordinary remote
connectors. One authorization server fronts N resources: each MCP profile is a
distinct protected resource with its own canonical audience, and each verifies
access tokens locally against the published public key — no round trip back to
the auth layer per call. The SPEC-108 `plt_` tokens keep working on every
profile at the same time, so enabling this breaks no existing setup.

```yaml
# config.yaml — 'cloud'/'open' accept OAuth as the auth mandate
mode: cloud
oauth:
  enabled: true
  issuer: https://hub.example.com
  profiles: [default]
```

```bash
uv run palaia-hub oauth set-password --username you   # the single local owner
uv run palaia-hub oauth machine-client --name nightly-job \
    --profile default --scope vault:work:read         # pinned, secret shown once
uv run palaia-hub oauth clients                      # who is registered
uv run palaia-hub oauth gc                            # prune orphans now
```

Endpoints: `/.well-known/oauth-authorization-server` (also served at
`/.well-known/openid-configuration`), `/.well-known/jwks.json`,
`/.well-known/oauth-protected-resource/<profile>`, `/oauth/authorize`,
`/oauth/token`, `/oauth/revoke`, `/oauth/register`, `/oauth/login`.

Each of the three mcp-hub production lessons (MASTERPLAN §5.5) is a mechanism
in one place, with its own regression test:

- **Grace-windowed refresh rotation** (`store.rotate_refresh_token`) — a spent
  refresh token stays usable for `refresh_grace_window` seconds, so one
  connector fanned out over web, phone and desktop converges instead of
  tearing the grant down. Strict single-use caused daily re-logins.
- **Resolved resource indicators** (`resources.ResourceRegistry`) — the `aud`
  claim is always composed here; a client's RFC 8707 `resource` is *matched*
  against known profiles (tolerating `/mcp` and trailing slashes), never
  copied into a token nobody can use.
- **Registered-client GC** (`store.prune_clients`) — self-registered clients
  holding no live refresh token are pruned, throttled, and triggered from the
  token endpoint. Admin-provisioned machine clients never are.

Registration is CIMD-first (MCP 2026-07-28 deprecated RFC 7591 DCR): an https
`client_id` resolves to a metadata document, fetched through fastmcp's
SSRF-hardened fetcher, so reconnects reuse one row instead of creating one.
DCR remains as a fenced fallback — public clients only, PKCE mandatory, no way
to request `client_credentials`, hard ceiling, GC'd.

Access tokens are signed **ES256** rather than the Ed25519 the SPEC names:
fastmcp 3.4.7's `JWTVerifier` — which deliverable #4 requires the resource
side to use — accepts no `EdDSA`, and reimplementing JWT validation here is
exactly what that deliverable forbids. See `oauth/keys.py`'s module docstring.

## Running it

```bash
cd v3
uv run palaia-hub serve
```

Then `curl http://127.0.0.1:8420/api/health`.
