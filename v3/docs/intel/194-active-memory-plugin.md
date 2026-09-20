# OpenClaw's Active Memory plugin — competitive read and integration seam

Issue [#194](https://github.com/byte5ai/palaia/issues/194) · intel review · written
2026-09-20 against `3.0.0-rc1` and the v2 plugin at `2.8.0`.

This is an analysis, not an implementation. It grounds the issue's claims in this
repository's code, assesses the `memory-artifact` / `memory-prompt` seams as a place
to plug in, scopes the proposed bridge plugin (effort L) without building it, and
drafts the differentiation copy the issue asks for (effort S).

## Evidence base

Everything about **palaia** below is read off this repository and cited by file and
line. Everything about **OpenClaw's own Active Memory plugin** comes from the issue
text: this session had no network, and the `openclaw` package is a peer dependency
that is not vendored here (`packages/openclaw-plugin/package.json` declares
`openclaw >=2026.5.7`; there is no `node_modules`). Claims about OpenClaw's external
behaviour are therefore marked **UNVERIFIED** and must be confirmed against the real
SDK before anything is built on them.

One thing about OpenClaw *is* checkable offline: this repo keeps a hand-maintained
mirror of the plugin SDK's types in `packages/openclaw-plugin/src/types.ts`
("Based on OpenClaw v2026.5.7 plugin-sdk", lines 1–9). That mirror is evidence of
what palaia was built against and compiles against — it is not the upstream source,
and it can lag or be wrong. Where this document leans on it, it says so.

## 1. Palaia's active memory, as built

Palaia has **two** active-memory implementations, and they work in opposite
directions. That distinction drives everything downstream, so it comes first.

### 1.1 v2 — push, at prompt-build time

The v2 OpenClaw plugin injects memory into the prompt before the model sees it. Two
code paths do the same thing for different host generations:

- **Modern host:** the ContextEngine's `assemble()` —
  `packages/openclaw-plugin/src/context-engine.ts:466-554`, registered via
  `api.registerContextEngine("palaia", …)` (`packages/openclaw-plugin/index.ts:88-95`).
- **Legacy host:** the `before_prompt_build` hook —
  `packages/openclaw-plugin/src/hooks/index.ts:338-566`, gated on `config.memoryInject`
  (default `true`, `src/config.ts:91`).

Both funnel through the same steps:

1. **Build a query from the transcript, with string operations only.**
   `buildRecallQuery()` (`src/hooks/recall.ts:268-329`) filters out `inter_session` /
   `internal_system` messages, strips OpenClaw's channel envelope and `System:`
   prefixes (`recall.ts:200-233`), skips system-only content, scans at most the last
   3 user messages or 2000 characters, and hard-caps the query at 500 characters. No
   model is consulted to decide what to retrieve.
2. **Retrieve.** Fast path: a JSON-RPC `query` to the local embed server over a Unix
   socket (`hooks/index.ts:409-432`, client in `palaia/embed_client.py`, server in
   `palaia/embed_server.py`), with `config.timeoutMs || 3000`. Fallback: a
   `palaia query … --json` subprocess at a 15 s timeout (`hooks/index.ts:435-448`).
   Last resort: `palaia list --tier hot` (`hooks/index.ts:452-474`).
3. **Rerank, locally and arithmetically.** `rerankByTypeWeight()`
   (`src/hooks/recall.ts:366-398`) multiplies the retrieval score by a per-type weight
   (`process` 1.5, `task` 1.2, `memory` 1.0 — `openclaw.plugin.json`), a recency boost
   `1 + f·e^(−hours/24)` (`recall.ts:355-364`), and a 1.3× boost for human-written
   entries tagged `webui`/`cli` (`recall.ts:370,379-381`).
4. **Fit a budget and emit.** Entries are appended until `maxInjectedChars`
   (default 4000) is reached (`hooks/index.ts:497-502`); above 100 results the
   formatter switches to compact mode — title, first line, `[id:…]` — and tells the
   agent to call `memory_get` for the rest (`recall.ts:411-438`). The block is
   headed `## Active Memory (palaia)` (`hooks/index.ts:491`,
   `context-engine.ts:182`).

Palaia has been calling its injected block "Active Memory" since well before this
issue: the string is load-bearing in `palaia/doctor/checks.py:513`, which uses it to
detect recall context that got re-captured into the store.

The retrieval underneath is `SearchEngine.search()` (`palaia/search.py:124-309`):
pure-Python BM25 (`palaia/bm25.py:32-86`, zero dependencies) over a cached index,
plus cosine similarity over cached embeddings, fused as **0.4·BM25 + 0.6·embedding**
(`search.py:261-271`) — or BM25 alone when no embedding provider resolves
(`search.py:266-271`). Where the backend has `sqlite-vec` or pgvector, the vector
half runs as native KNN instead of Python cosine (`search.py:202-232`).

### 1.2 v3 — pull, at tool-call time

v3 has no equivalent of `before_prompt_build`, because it has no hook into the
client's prompt assembly: it is an MCP server, and the client owns the prompt. Recall
is a **tool the agent decides to call** — `recall` and `build_context`, registered at
`v3/server/src/palaia_hub/gateway/memory_tools.py:375-406` and `:408-460`, both
`readOnlyHint=True`.

What makes it "active" in practice is instruction, not interception: the tool
descriptions themselves (`memory_tools.py:377-385`) and the shipped client skill
`v3/clients/skills/palaia-memory/SKILL.md`, whose "Do this before you answer"
section tells the agent to `recall` before deciding and `capture` before replying.

The retrieval path is deeper than v2's and equally model-free:

- `RecallService.recall()` (`v3/server/src/palaia_hub/recall/service.py:158-196`) →
  `_candidates_from_query()` (`:293-312`) asks the index for a `hybrid` search at
  `limit × factor` depth, then ranks.
- The index (`v3/server/src/palaia_hub/index/search.py`) runs SQLite FTS5 with a
  10×-weighted title column (`:57-58`) and a sqlite-vec KNN pass with 8× over-fetch
  (`:48-52`), fused by **reciprocal rank fusion with k=60** (`:44-46`) — chosen over
  the spike's score-summing sketch for the reason documented at `:9-14`.
- Ranking on top is a pure function over decay, access counts and significance
  (`v3/server/src/palaia_hub/recall/ranking.py`; the package docstring at
  `recall/__init__.py:22-25` states that everything but `service` and `refs` is pure —
  no clock, no I/O, no SQL).
- Degradation is explicit rather than silent: with no embedder, no sqlite-vec, or an
  undrained embedding backlog, a hybrid query answers from FTS and sets
  `degraded` (`index/search.py:16-20`, surfaced through
  `recall/service.py:293-312`).

Embeddings are local-only in v3 — `build_embedder()` is "currently: fastembed only"
(`v3/server/src/palaia_hub/index/embeddings.py:158-160`), an ONNX model loaded in
process (`:108-137`). There is no remote-embedding provider at all, and a missing
model degrades to FTS instead of reaching for an API (`:118-125,154-156`).

### 1.3 Where a model *is* in the loop

Honesty matters more than the slogan here. Palaia does use an LLM — on the **write**
side, never on the read side:

- v2 auto-capture calls OpenClaw's embedded agent to extract entries from a finished
  exchange (`extractWithLLM`, `packages/openclaw-plugin/src/hooks/capture.ts:457-…`,
  via `runEmbeddedPiAgent` at `:188-191`), with a rule-based extractor as fallback
  when the model is unavailable (`hooks/index.ts:777-817`).
- v3's curator is an unattended model session that files captures into the vault
  (`v3/server/src/palaia_hub/curator/__init__.py:1-24`). It runs asynchronously, off
  the request path, and the step that actually mutates notes is "applied by plain
  code with no model in the path" (`curator/__init__.py:21-22`).

So the defensible claim is **zero-LLM *retrieval***, not a zero-LLM product. Any copy
that blurs the two will not survive a competitor's read of our own repo.

## 2. OpenClaw's Active Memory plugin, as described — UNVERIFIED

From the issue, not from code:

- An official plugin shipped in OpenClaw 2026.4.10.
- A memory sub-agent pulls relevant context immediately before the main reply.
- Cloud-first; retrieval requires an LLM sub-agent, hence tokens, cost and latency.
- 2026.4.7 added Plugin-SDK seams (`memory-artifact`, `memory-prompt`) so companion
  plugins and non-legacy context engines can consume active-memory state without
  reaching into internals.

Nothing in this repository confirms the sub-agent design, the cloud dependency, the
token cost, or the 2026.4.x version attributions. Treat every row of the comparison
table's OpenClaw column as provisional.

## 3. Feature by feature

Palaia columns are code-grounded and cited above. The OpenClaw column is UNVERIFIED
throughout.

| Dimension | palaia v2 Auto-Recall | palaia v3 recall | OpenClaw Active Memory (UNVERIFIED) |
|---|---|---|---|
| **Activation** | Host hook / ContextEngine `assemble()` — runs every prompt build, unprompted | Agent calls the `recall` tool; skills + tool descriptions make it habitual | Memory sub-agent runs before the main reply, unprompted |
| **Retrieval mechanism** | BM25 + embeddings, fused 0.4/0.6 | FTS5 + sqlite-vec KNN, fused by RRF (k=60), then decay/access/significance ranking | LLM sub-agent decides what to pull |
| **Model calls per retrieval** | **0** | **0** | ≥1 |
| **Marginal token cost of retrieval** | Only the injected block itself (≤ `maxInjectedChars`, default 4000) | Only the returned text (token-budgeted; notes degrade full → summary → stub rather than being cut, `recall/budget.py`) | Sub-agent prompt + completion, on top of the injected context |
| **Latency** | Unix-socket query at a 3 s timeout; 15 s CLI fallback (`hooks/index.ts:423,441`). In-code estimates: ~0.5 s warm socket vs ~3–14 s CLI (`hooks/index.ts:408`) — comments, not benchmarks | Index query. Measured in-repo, 4 vCPUs, golden vault: FTS 0.013 ms/chunk; embedding 15.6 ms/chunk at batch 8 (`index/embeddings.py:35-49`) | An extra model round-trip |
| **Offline** | Yes with a local provider (ollama / sentence-transformers / fastembed, `palaia/embeddings.py:46-176`); BM25 always works with none (`:264-303`). Not offline if configured for OpenAI/Gemini (`:178-262`) | Yes once the local model is cached; no remote provider exists (`index/embeddings.py:158-160`) | No — cloud-first |
| **Provider independence** | Chain-configurable, falls through to BM25 (`palaia/search.py:41-63`) | Independent of any LLM vendor for retrieval | Tied to whatever model the sub-agent runs on |
| **Degradation** | Embedding failure → BM25 only, logged (`search.py:256-259`); query failure → `list --tier hot` | Reports the mode it actually ran in; `degraded` + reason on every result | Unknown |
| **Persistence** | Markdown files in tiers + SQLite/Postgres backends; WAL (`palaia/wal.py:62-158`, `fsync`+rename at `:85-89`), replayed at plugin bootstrap (`context-engine.ts:403-411`) and by the `palaia-recovery` service (`hooks/index.ts:896-907`) | Markdown vault as source of truth; atomic write = tmp + `fsync` + `os.replace` + directory `fsync` (`vault/atomic.py:62-95`); every change is a real git commit (`vault/gitlayer.py:1-22`); the SQLite index is derived and rebuildable (`index/service.py:1-25`) | Unknown |
| **Data location** | The user's machine | The user's hub | Vendor cloud |
| **Transparency** | Injected block is visible and labelled; 🧠 reaction + footnotes when enabled | Results carry refs; `recall_explorer` MCP App | Unknown |

The honest summary: on **cost, offline capability and provider independence** palaia
wins on both tracks, and the win is real in code rather than in positioning. On
**activation** — the "active" in Active Memory — v2 is competitive and **v3 is
currently behind both v2 and OpenClaw**, because an MCP server cannot inject into a
prompt it never sees. That asymmetry is the single most important finding here.

## 4. The `memory-prompt` / `memory-artifact` seams

### 4.1 What the mirror says

`packages/openclaw-plugin/src/types.ts:558-587` defines both halves:

```ts
export type MemoryPromptSectionBuilder = (params: {
  availableTools: Set<string>;
  citationsMode?: string;
}) => string[];

export type MemoryPluginPublicArtifact = {
  kind: string;
  workspaceDir: string;
  relativePath: string;
  absolutePath: string;
  agentIds: string[];
  contentType: "markdown" | "json" | "text";
};

export type MemoryPluginCapability = {
  promptBuilder?: MemoryPromptSectionBuilder;
  publicArtifacts?: MemoryPluginPublicArtifactsProvider;
};
```

registered through `api.registerMemoryCapability(pluginId, capability)`
(`types.ts:660`), with the older `registerMemoryPromptSection` marked deprecated at
`:657-658`.

Read plainly, these are **not a retrieval seam**. `promptBuilder` contributes prompt
lines given the tool set and a citation mode. `publicArtifacts` *lists file-backed
artifacts* — a path, a workspace, the agents they belong to, a content type. Neither
carries memory items, scores, or a query. A companion plugin can learn *that* an
artifact exists and *where it lives on disk*; it cannot ask the host's active memory
what it retrieved this turn.

That matters for the bridge design in §5: the seams are good for **advertising and
exchanging files**, and thin for **sharing retrieval state**.

### 4.2 What palaia already consumes

- `memory-prompt`: **already wired.** `packages/openclaw-plugin/index.ts:60-78`
  builds tool-conditional guidance lines and registers them via
  `registerMemoryCapability("palaia", { promptBuilder })`, falling back to the
  deprecated call on older hosts. Shipped in 2.8.0 (`CHANGELOG.md:8`).
- The host's active-memory concept already reaches us elsewhere, too:
  `citationsMode` on `assemble()` is documented in the mirror as "Active memory
  citation mode" (`types.ts:499`) and palaia adapts to it by appending citation
  guidance (`context-engine.ts:530-533`).
- `memory-artifact` (`publicArtifacts`): **declared in the mirror, not implemented.**
  `grep` finds the type at `types.ts:586` and nowhere else.

### 4.3 What a bridge would need, and what is missing

Assuming the issue's description of upstream is right, an `active-memory-bridge`
that made palaia the durable store behind OpenClaw's Active Memory would need:

| Need | Status in palaia today |
|---|---|
| Register as a memory capability | ✅ `registerMemoryCapability` already used (`index.ts:74-78`) |
| Expose stored memories as file-backed artifacts | ⚠️ Possible but non-trivial. v2 entries *are* files (`<tier>/<id>.md`, `palaia/search.py:311-316`), so
`absolutePath`/`relativePath` exist; `agentIds` maps to palaia's agent field; `contentType` is `markdown`. v3 entries are also files — but they live in the hub's vault, potentially on a different machine from the OpenClaw host, and `MemoryPluginPublicArtifact` has no remote form |
| Receive what the host's active memory retrieved | ❌ No seam found. `promptBuilder` gets `availableTools` + `citationsMode`, nothing else |
| Write host-side memory state into palaia | ❌ No seam found. The existing write path is palaia's own `agent_end` / `afterTurn` capture |
| Avoid double injection | ❌ Unhandled. palaia injects `## Active Memory (palaia)`; a host Active Memory section would be a second block. There is no negotiation in the mirror, and `ownsCompaction` (`context-engine.ts:397`) is the only "who owns this" flag we declare |
| Recall-side event to hang automations on | ❌ v3's event vocabulary has `memory.entry.*`, `inbox.captured`, `index.*`, `curator.*`, `session.idle` — no recall event (`v3/server/src/palaia_hub/events/schema.py:41-…`) |
| A v3 ↔ OpenClaw adapter of any kind | ❌ Does not exist. v3 ships MCP clients and skills only (`v3/clients/`) |

## 5. The bridge (effort L) — scoped, not built

**Shape.** A separate OpenClaw plugin (`active-memory-bridge`), not a change to
`@byte5ai/palaia`. It would register a memory capability that publishes palaia
entries as `MemoryPluginPublicArtifact`s so the host's Active Memory can read them
from disk, and — if and only if upstream offers a write seam we have not seen —
persist what the host's sub-agent produced back into palaia.

**Work items, roughly ordered.**

1. Verify the upstream SDK. Read the real `memory-artifact` / `memory-prompt`
   contracts, the Active Memory plugin's own registration, and whether a
   retrieval-state or write seam exists at all. **This is a gate, not a task:** if
   there is no write seam, items 4–6 evaporate and the bridge shrinks to a read-only
   artifact exporter.
2. Artifact provider over the v2 store: enumerate entries per agent and tier, map to
   `MemoryPluginPublicArtifact`, honour scope isolation (`palaia/scope.py`) so
   `private` entries are not published to agents that cannot see them.
3. Injection negotiation: detect the host's Active Memory and suppress or slim
   palaia's own block, or accept two blocks deliberately. Needs a host signal that
   the mirror does not currently show.
4. Write-back path, if a seam exists: host memory item → `palaia write` with
   provenance tags, dedup against auto-capture, and WAL coverage.
5. Feedback-loop protection: palaia already detects and filters re-captured recall
   context (`palaia/doctor/checks.py:512-534`). A second injecting system multiplies
   that risk; the detector's patterns would need extending.
6. Version matrix and tests: the plugin must not break on hosts without the seams,
   which is exactly the fallback pattern already used at `index.ts:74-78`.

**Effort L is plausible**, and most of it is *not* code — it is protocol
archaeology, scope/permission mapping, and the dedup/loop problem. Items 2 and 6 are
a few days; items 3–5 are open-ended until item 1 lands.

**Which track would it live on?** This is the awkward part. The bridge targets
OpenClaw, and `v3/MASTERPLAN.md:499` states OpenClaw is *"not a v3 launch target — v2
serves it"*, with a "v3 adapter later". A bridge built today therefore belongs to the
**v2 plugin's** world, which is maintenance-only under `AGENTS.md`: feature work on
v2 targets `v2-maintenance` and is limited to critical hotfixes. Building it would
mean either reopening v2 feature development or building a v3 OpenClaw adapter that
the masterplan has deliberately deferred. Neither is a quiet decision.

## 6. Recommendation for 3.x

**1. Do not build the bridge now.** It fails three independent tests: the upstream
contract is unverified, the seams as mirrored carry no retrieval state (so the
integration would be shallower than the issue implies), and it lands on a track that
policy has frozen. Revisit only if (a) upstream is confirmed to expose a real
write/retrieval seam, **and** (b) OpenClaw users ask for palaia as the durable store
behind Active Memory — that demand signal does not exist in this repo today.

**2. Ship the differentiation messaging.** It is cheap, it is true, and it is the
part of the issue with no dependency on unverified facts. §7 has the copy.

**3. Treat the activation gap as the real competitive item.** OpenClaw's plugin is
active-by-default; v3's recall is active only insofar as a skill persuades the agent
to call it. Options, cheapest first:

- Keep leaning on skills and tool descriptions (status quo — already built, works,
  and is the only option that needs no client cooperation).
- Add a recall-side event to the v3 bus so automations can at least *observe*
  retrieval (small, unblocks dashboards and rules; does not make recall automatic).
- Per-client "active" adapters — an OpenClaw context engine, a Claude Code hook — one
  per host that offers a prompt-build seam. This is the v3 adapter the masterplan
  defers, and the bridge in §5 is a special case of it. If the bridge is ever built,
  build it as *this*, not as an Active Memory accessory.

**4. Do not race OpenClaw on "our memory sub-agent is smarter."** Their design spends
a model call per turn; ours spends none. Competing on retrieval *intelligence* would
mean giving up the exact property that makes us cheaper, offline-capable and
vendor-neutral. Compete on cost, control and durability.

## 7. Differentiation copy

### 7.1 Applied in this branch

`v3/docs/how-it-works.md`, "Memory that outlives the session" — the search bullet
gains two sentences on retrieval cost and offline operation. Every clause is backed
by §1.2 above. Applied here because it is v3-track, minimal, and states nothing the
code does not do.

### 7.2 Patch proposal for v2 surfaces — NOT applied

The head-to-head competitor of OpenClaw's plugin is **palaia v2's** OpenClaw plugin,
so that is where "Active Memory without tokens" belongs. It is not applied in this
branch for a hard reason: `AGENTS.md` allows a PR to touch exactly one track, and the
only sanctioned v2-root change on `main` is the top-level README cross-reference.
`packages/openclaw-plugin/README.md` is v2 and needs its own PR against
`v2-maintenance`.

Proposed insertion after the "Features" list of `packages/openclaw-plugin/README.md`:

> ## Active Memory without tokens
>
> palaia injects relevant memory into every prompt before the agent answers — and
> spends no model call doing it. The query is built from the transcript with string
> operations; retrieval is BM25 plus a vector index; ranking is arithmetic. There is
> no retrieval sub-agent, so recall costs you the injected text and nothing else.
>
> - **No model call to remember.** Retrieval never leaves your process for an LLM.
> - **Works offline.** With a local embedding provider (fastembed,
>   sentence-transformers, ollama) nothing leaves the machine. With no provider at
>   all, BM25 keyword search still answers — palaia degrades instead of failing.
> - **Provider-independent.** Your memory does not belong to whichever model you are
>   using this month.
> - **Crash-safe.** Writes go through a write-ahead log and are replayed on startup,
>   so a killed gateway does not cost you the last thing you learned.
>
> Auto-*capture* is a different story and we will not pretend otherwise: extracting
> entries from a finished exchange does use a model, with a rule-based fallback when
> none is available. Reading is free; deciding what was worth keeping is not.

Two corrections the same PR should carry, found while grounding this doc:

- `packages/openclaw-plugin/README.md` documents `memoryInject: false // default: false`;
  the actual default is `true` (`src/config.ts:91`, and `openclaw.plugin.json`). The
  copy above claims injection happens by default, so the drift has to go.
- The Features list says "BM25 search — Fast local search, no external API needed",
  which undersells a hybrid engine that has had embeddings since ADR-001
  (`palaia/search.py:1`).

### 7.3 Claims we must not make

For whoever writes the next version of this copy:

- ❌ "palaia never calls an LLM." It does, on capture (§1.3).
- ❌ "Always offline." v2 can be configured with OpenAI or Gemini embeddings
  (`palaia/embeddings.py:178-262`); v3 needs one network trip to download its local
  model the first time (`index/embeddings.py:112`).
- ❌ "Faster than OpenClaw's plugin." We have no measurement of theirs. The in-repo
  numbers we *can* quote are v3's embedding/FTS microbenchmarks
  (`index/embeddings.py:35-49`); v2's "~0.5 s vs ~3–14 s" figures are code comments
  (`hooks/index.ts:408`), not a benchmark, and should not be published as one.
- ❌ Anything asserting how OpenClaw's plugin works internally until §2 is verified.

## 8. Loose ends noticed while grounding this

Neither is in scope for #194; both are cheap follow-ups.

- `v3/docs/how-it-works.md:55-56` offers "a recall" as something the event bus can
  hook. There is no recall event in the vocabulary
  (`v3/server/src/palaia_hub/events/schema.py:41-…`). Either add the event (see §6.3,
  where it is useful anyway) or drop the word from the sentence.
- The v2 plugin README drift listed in §7.2.

## 9. To verify when online

1. Does OpenClaw 2026.4.10's Active Memory plugin exist as described, and does
   retrieval really require an LLM sub-agent?
2. What do `memory-artifact` and `memory-prompt` actually expose upstream? Does
   either carry retrieval state or accept writes — the question §4.3 and §5 both
   hinge on?
3. Is there a host signal a memory plugin can read to know Active Memory is active,
   so palaia can avoid injecting a second block?
4. Does the upstream `MemoryPluginPublicArtifact` have a non-filesystem form? Without
   one, a v3 hub on another machine cannot publish artifacts at all.
</content>
</invoke>
