# MemPalace — competitive read against palaia v3

Issues [#200](https://github.com/byte5ai/palaia/issues/200) and
[#193](https://github.com/byte5ai/palaia/issues/193) · intel review · written
2026-09-27 against palaia `3.0.0-rc2` (commit `bec551f`) and MemPalace `v3.10.0`.

This is an analysis, not an implementation. It checks what the two issues say about
MemPalace against MemPalace's own primary sources, answers #193's direct question
("does palaia store verbatim?") from palaia v3's code, and ends with differentiation
copy and a list of follow-ups worth filing. Nothing is applied or filed here.

Both issues were written against palaia **v2** (WAL, hot/warm/cold tiers, `palaia gc`,
entry classes, the OpenClaw plugin). This document compares MemPalace with palaia
**v3** — the hub under `v3/` — only. Where an issue's argument rests on a v2 feature,
§5 maps it to v3 or drops it.

## Evidence base

Everything about **palaia** is read off this repository and cited by file and line
(paths in the body are relative to `v3/`; §9 gives them from the repository root).

Everything about **MemPalace** comes from its own primary sources, fetched on
**2026-09-27**: the GitHub REST API for repository metadata and releases, and the
following files on its default branch (`develop`):

| Short name | URL |
|---|---|
| README | https://github.com/MemPalace/mempalace/blob/develop/README.md |
| HISTORY | https://github.com/MemPalace/mempalace/blob/develop/docs/HISTORY.md |
| BENCHMARKS | https://github.com/MemPalace/mempalace/blob/develop/benchmarks/BENCHMARKS.md |
| CHANGELOG | https://github.com/MemPalace/mempalace/blob/develop/CHANGELOG.md |
| shared-brain | https://github.com/MemPalace/mempalace/blob/develop/website/guide/shared-brain.md |
| remote-server | https://github.com/MemPalace/mempalace/blob/develop/website/guide/remote-server.md |
| mining | https://github.com/MemPalace/mempalace/blob/develop/website/guide/mining.md |
| memory-stack | https://github.com/MemPalace/mempalace/blob/develop/website/concepts/memory-stack.md |
| the-palace | https://mempalaceofficial.com/concepts/the-palace.html |

These are MemPalace's *documentation*, not its code. This review did not read or run
MemPalace's source, so any claim below about how MemPalace behaves internally is
"as documented". Where a claim rests on something weaker than the docs (a changelog
line, an inference), it is marked **UNVERIFIED**.

## 1. Verdict

**MemPalace is no longer the competitor the issues describe.** #193 (April 2026)
saw a local ChromaDB store that keeps raw conversations. Five months and ~2,000
commits later it is also a **hub**: one `mempalace serve` process that every agent on
every machine talks to over MCP, with bearer-token HTTPS, a read-only mode, agent
diaries, and an agent-to-agent event stream with artifact handoffs
(shared-brain, remote-server). That is palaia v3's P1 (memory) and P4 (directory &
messenger) territory (`MASTERPLAN.md:63-87`). The overlap is now architectural, not
just "both are local memory".

**On storage philosophy the issues are right about MemPalace and half-right about
palaia.** MemPalace keeps conversations verbatim; palaia v3 does not store
conversations at all (§4). But "palaia stores knowledge, MemPalace stores text"
(#200) oversimplifies both: MemPalace has LLM-derived layers on top of its verbatim
drawers, and palaia's capture stores the *agent's own statement*, verbatim, before
a curator files it.

**On benchmarks, #193's numbers are stale and partly retracted by MemPalace
itself.** The durable figure is 96.6% R@5 on LongMemEval — a session-level
*retrieval* recall, not answer accuracy. The "100% hybrid" was pulled from the
headline in April as "teaching to the test" (§3).

**Where that leaves palaia v3:** it wins on ownership and governance (a Markdown vault
you open in Obsidian, a git commit per change, real per-client auth, a curator that
cannot rewrite what exists without approval, a tool marketplace). It loses on raw
recall fidelity (no verbatim archive), on capture reach (no transcript hooks), and
on proof (no published retrieval benchmark). "Recall costs no model call" is *not* a
differentiator against MemPalace — it is MemPalace's own headline (§7.3).

## 2. MemPalace, as published

### 2.1 Maturity and licence

From the GitHub API, 2026-09-27:

| Field | Value |
|---|---|
| Repository | `MemPalace/mempalace` (the `milla-jovovich/mempalace` URL in #193 redirects here) |
| Created | 2026-04-05 |
| Stars / forks | 59,295 / 7,565 (#193 said 23k / 3k four days after launch) |
| Open issues + PRs | 759 |
| Contributors | ≥100 (the API page is capped at 100; the true count is **UNVERIFIED**) |
| Commits on `develop` | 2,049 (repo page) |
| Latest release | `v3.10.0`, 2026-09-16; 15 releases since `v3.3.1` (2026-04-18), roughly every two to three weeks |
| Last push | 2026-09-25 |
| Licence | MIT |
| Language | Python ≥3.9; PyPI package `mempalace`, container `ghcr.io/mempalace/mempalace` |

It is actively maintained and moving fast. The changelog reads like a project
paying down reliability debt — data-loss fixes in `sync --apply`, integrity-probe
false positives, hooks that silently saved nothing on fresh installs (recent CHANGELOG
entries, 3.8.0 through Unreleased) — which is a sign of real users at scale, and also of a young
codebase.

The project had a rough launch week and documents it publicly: impostor domains
distributing malware, and a list of retracted README claims (HISTORY, 2026-04-07 and
2026-04-11). Its current posture on claims is visibly more careful than at launch.

### 2.2 Architecture and storage model

- **Verbatim storage.** "MemPalace stores your conversation history as verbatim text
  and retrieves it with semantic search. It does not summarize, extract, or
  paraphrase." (README, "What it is"). Content is **mined** into the palace:
  project files, or conversation exports with `--mode convos`, which "chunks by
  exchange pair (human + assistant turns)" and reads Claude, ChatGPT and Slack
  exports, Markdown and plain-text transcripts (mining). `mempalace sweep` stores
  "one verbatim drawer per user/assistant message" (README, "Auto-save hooks").
- **The palace metaphor is metadata.** *Wings* are people or projects, *rooms* are
  topics, *halls* are five fixed categories (facts, events, discoveries,
  preferences, advice), *tunnels* link the same room across wings, *drawers* hold
  the original chunks (the-palace). MemPalace itself now says wing/room scoping "is
  standard metadata filtering in the underlying vector store, not a novel retrieval
  mechanism" (the-palace, "Why Structure Matters").
- **It is not purely verbatim.** *Closets* are "the summary layer … compact notes
  that point back to the original content" (the-palace). The changelog calls them
  "LLM-derived from file content" and "the AAAK search-index layer" (CHANGELOG,
  entry for #2325 — **UNVERIFIED** beyond that line). `--extract general`
  auto-classifies conversation content into memory types (mining). `rooms propose`
  has an LLM propose a room set, behind a consent gate for external LLMs (commit
  message of #2576 on the repo page). The benchmark "diary mode" has Claude Haiku
  write topic summaries at ingest (BENCHMARKS, "Active Work: Diary Mode"). Verbatim
  is the primary layer, not the only one.
- **AAAK**, an abbreviation dialect once marketed as "30x lossless compression", is
  documented by its own authors as lossy: 84.2% vs 96.6% R@5 on LongMemEval
  (HISTORY, 2026-04-07).
- **Pluggable backends.** ChromaDB by default; `sqlite_exact`, `rust_exact`,
  Milvus, Qdrant and pgvector opt-in (README, "Storage backends"). The database *is*
  the store: there is no human-readable source-of-truth file layer comparable to a
  vault (**UNVERIFIED** as a negative — nothing in the docs read describes one).
- **A temporal knowledge graph** with validity windows (add, query, invalidate,
  timeline) in local SQLite (README, "Knowledge graph").

### 2.3 Retrieval

- Semantic search over drawers, with wing/room filters. Default embedding is
  `all-MiniLM-L6-v2`; onboarding recommends `embeddinggemma-300m` (multilingual,
  100+ languages); an OpenAI-compatible embedding endpoint is optional (README,
  "Requirements").
- A **hybrid** pipeline adds keyword boosting, temporal-proximity boosting and
  preference-pattern extraction; an optional LLM rerank promotes the best of the
  top 20 (README, "Benchmarks").
- A **4-layer wake-up stack**: L0 identity file (~50–100 tokens), L1 "essential
  story" (top 15 drawers by importance, capped at 3,200 characters), L2 room recall,
  L3 deep search. A typical wake-up is "~600–900 tokens" (memory-stack).

So MemPalace is not "flooding the context with verbose original text" by default, as
#200 suggests: the wake-up is bounded and search returns top-5. The token cost of
verbatim shows up in what a *hit* contains (a raw exchange pair rather than a
distilled fact), not in an unbounded dump.

### 2.4 Integrations

- **MCP server with 45 tools**, plus a 3-tool "light" server (about 2,100 vs 7,700
  schema tokens per model step, CHANGELOG 3.10.0 / DSH plugin entry) (README, "MCP
  server").
- **Auto-save hooks** for Claude Code, Codex CLI and Cursor — "save periodically and
  before context compression"; Cursor also gets session-start recall (README,
  "Auto-save hooks"). Plugins for Antigravity, OpenClaw and the DeepSeek Harness are
  documented (repo tree, website/guide).
- **Agent skills** installable with `npx skills add MemPalace/mempalace`:
  setup, search-before-answer recall, and logstream delegation (README, "Install").
- **Shared-brain hub.** `mempalace serve` owns the palace; local stdio servers
  auto-proxy to it; remote agents connect over HTTPS with a bearer token. The hub
  carries two layers: memory (drawers, KG, diary) and a *logstream* of events and
  artifacts for delegation between agents (shared-brain).
- **Auth is one shared token.** `serve` auto-generates a bearer token on a
  non-loopback bind; teammates connect "with the shared token"; `--read-only`
  hides every state-changing tool for the whole server (remote-server, §3–4).
  Agent identity is self-declared as `host:harness:project` by convention in the
  agent's instructions, not bound to a credential (shared-brain, "identity").

### 2.5 Positioning

"Local-first AI memory. Verbatim storage, pluggable backend, 96.6% R@5 raw on
LongMemEval — zero API calls." (README tagline). "The best-benchmarked open-source AI
memory system. And it's free." (repo description). The benchmark write-up frames the
thesis explicitly: every competitor "uses an LLM to manage memory"; MemPalace "just
stores the actual words" and argues the field "is over-engineering the memory
extraction step" (BENCHMARKS, "The Core Finding").

## 3. Benchmarks — what is claimed, and whether it holds up

| Claim | Status | Source |
|---|---|---|
| 96.6% R@5, LongMemEval, raw mode, no LLM | **Holds**, as a retrieval-recall number. Independently reproduced (M2 Ultra, issue #39) and re-run on the tagged v3.3.0 release on 2026-04-14; per-question result files are committed | HISTORY 2026-04-07 and 2026-04-14; README |
| 98.4% R@5, hybrid v4, held-out 450 questions | **Holds as stated.** Tuned on 50 dev questions, evaluated on the other 450; MemPalace calls it "the honest generalisable figure" | README; BENCHMARKS "New Results" |
| "100% hybrid" (#193) | **Retracted from the headline** by MemPalace on 2026-04-14. The step from 99.4% to 100% was engineered by inspecting three specific wrong answers — "teaching to the test" in their own words | HISTORY 2026-04-14; BENCHMARKS "Benchmark Integrity" |
| "Highest published score" (#193) | **Category error**, acknowledged by MemPalace. Competitors publish end-to-end *QA accuracy*; MemPalace publishes *retrieval recall*. Their competitor table was removed after a community audit (issue #875) | HISTORY 2026-04-14 |
| "+34% palace boost" | **Retracted** — it compared unfiltered search with metadata filtering | HISTORY 2026-04-07 |
| LoCoMo 100% R@10 with top-50 rerank | **Retracted** — with 19–32 sessions per conversation, top-50 returns every session, so it measures reading comprehension, not retrieval | HISTORY 2026-04-14 |
| LoCoMo R@10 60.3% (session) / 88.9% (hybrid v5); ConvoMem 92.9%; MemBench R@5 80.3% | Published with reproduction commands; not independently checked here | README "Other benchmarks" |

**What R@5 on LongMemEval measures, precisely.** "Is the labelled session for this
question inside the top-5 retrieved candidates?" (BENCHMARKS, caveat box). In
LongMemEval_S each question's history is roughly 115k tokens over about 40 sessions
(https://github.com/xiaowu0162/LongMemEval, accessed 2026-09-27). Picking the right
session into a top-5 out of ~40 is a real result — especially at zero model calls —
but it is a *session-level* hit rate. It says nothing about whether an LLM then
answers correctly, and nothing about fine-grained facts inside a session. MemPalace
says this itself: "a system can have 100% retrieval recall and 40% QA accuracy"
(HISTORY 2026-04-14).

**Net:** the benchmark story holds up better than it did at launch *because*
MemPalace corrected it in public. The honest pair is 96.6% (raw, free) and 98.4%
(hybrid, held-out). Anything palaia says about MemPalace should quote those two
figures and the metric name, never "100%".

**palaia v3 has no comparable number.** In-repo measurement covers index and
embedding speed (`server/src/palaia_hub/index/bench.py:1-18`) and whether an agent
*uses* the memory at all — skill activation rates measured with a real client
(`server/tests/effectiveness/harness.py:1-27`). Neither measures retrieval quality
on a public dataset. See follow-up F1.

## 4. Does palaia v3 store verbatim? (#193's question)

Three different questions hide in "verbatim". The answers differ.

### 4.1 Conversations — no

palaia v3 never stores a conversation transcript.

- There is no transcript or chat-export importer. The only importers are for palaia
  v2 stores and basic-memory vaults (`server/src/palaia_hub/importers/`:
  `v2_source.py`, `basic_memory_source.py`).
- Bulk ingestion of documents is listed as **Missing**: "`palaia ingest <source>`
  … No bulk 'index this folder of documents' command yet" (`docs/migrate-from-v2.md:87`).
  #193's suggestion that a verbatim mode is "already possible" refers to v2's
  `palaia ingest`; in v3 it is not.
- The capture skill tells agents the opposite of MemPalace's thesis: "Skip the
  conversation itself, anything already in the memory, anything you could look up
  in seconds, and anything that was plainly thinking aloud"
  (`clients/skills/palaia-capture/SKILL.md:49-50`).
- There are no transcript hooks in `clients/` (it holds only skills:
  `palaia-capture`, `palaia-install`, `palaia-memory`, `palaia-messenger`).

### 4.2 What the agent writes — yes, then curated

- The `capture` tool takes three required fields — what it concerns, why keep it,
  and `content`, "the knowledge itself, understandable without this conversation"
  (`server/src/palaia_hub/gateway/memory_tools.py:594-665`).
- The inbox note stores `content` unchanged in a `- [raw]` observation
  (`server/src/palaia_hub/gateway/inbox.py:103-118`); the skill asks for "numbers,
  names, versions and paths verbatim" (`clients/skills/palaia-capture/SKILL.md:59-60`).
  The MASTERPLAN's capture contract names the field "the knowledge verbatim"
  (`MASTERPLAN.md:268-269`).
- The asynchronous curator then turns the capture into vault knowledge — a new note
  or additive observations on an existing one. It is instructed "Never invent facts
  the capture does not contain" and may not rewrite, merge or retire existing notes
  (`server/src/palaia_hub/curator/prompt.py:28-45`). Its output is a model's
  restructuring, not a copy.
- After the curator's write is verified, the inbox note is **deleted**
  (`docs/vault-format.md:414`). The verbatim capture survives in the vault's git
  history (every change is a commit, `server/src/palaia_hub/vault/gitlayer.py:1-11`)
  but is no longer searchable.
- A note written directly with `write` is stored exactly as the agent wrote it.

So the verbatim unit in palaia is *what an agent decided to say*, not *what was said
in the session*. The distillation happens in the agent at capture time, not in the
hub — the hub adds a second, conservative pass in the curator.

### 4.3 Retrieval output — full notes, degraded, never cut

Recall and `build_context` return whole notes. When a context package exceeds its
token budget (default 4,000), a note degrades from full body to title plus three key
observations to a one-line stub — "never truncate a note mid-body"
(`server/src/palaia_hub/recall/budget.py:1-28,50`). Retrieval is an index query:
FTS5 and `sqlite-vec` fused with RRF k=60 (`server/src/palaia_hub/index/search.py:44-46`),
then a logical decay rerank that moves no files (`server/src/palaia_hub/recall/ranking.py:1-7`).
No model is called.

### 4.4 Provenance

MemPalace ties a drawer to its `source_file` and, in the unreleased changelog, to the source
directory's inode (CHANGELOG, #2367). palaia ties a curated note back to its capture
by a mandatory `- [source] inbox capture <capture_id>` line (`server/src/palaia_hub/curator/prompt.py:40-41`)
and records who wrote what in each git commit. Once the inbox note is gone, following
a curated fact back to its exact original wording means reading git history — there
is no one-hop link to a stored original. That is the gap a verbatim mode would fill
(F2).

## 5. Correcting the issues' premises for v3

| Issue claim | Holds for v3? | v3 reality |
|---|---|---|
| "Palaia: WAL-Sicherheit" (#193) | No — v2 | No WAL. Atomic writes (tmp + `fsync` + `os.replace` + directory `fsync`, `server/src/palaia_hub/vault/atomic.py:62-81`) plus a git commit per change; the SQLite index is derived and rebuildable (`MASTERPLAN.md:223-227`) |
| "Tiering (hot/warm/cold)" (#193) | No — v2 | Decay is logical, computed at query time; "Nothing on disk moves" (`server/src/palaia_hub/recall/ranking.py:1-7`) |
| "Verbatim storage skaliert nicht (keine GC, kein Tiering). Palaia's bounded GC … direkte Antworten" (#193) | **No** | v3 has no knowledge prune or GC: "`palaia prune`, `gc` … **Missing**" (`docs/migrate-from-v2.md:85`). The only GC is git housekeeping (`server/src/palaia_hub/vault/gitlayer.py:18-21`). This argument cannot be used for v3 today. MemPalace, meanwhile, ships `sync`, `tunnels prune`, `hallways --prune-spellings` and an `audit` command (CHANGELOG) |
| "ChromaDB-Abhängigkeit → Palaia ist zero-external-deps (SQLite)" (#193) | Partly | v3 uses SQLite + `sqlite-vec` and a local embedding model, and ships as a container (`docs/how-it-works.md:143-151`). MemPalace also offers pure-SQLite backends now (`sqlite_exact`, `rust_exact`). Not a differentiator any more |
| "Keine Scope-Kontrolle" at MemPalace (#193) | Partly | MemPalace has wing/room filters, backend namespaces and a server-wide `--read-only`. It has no per-client permissions. palaia v3 has per-vault `read`/`write` scopes on every token, fail-closed (`server/src/palaia_hub/auth/scopes.py:1-16`), and physically isolated vaults (`MASTERPLAN.md:247-251`) |
| "Keine Entry Classes / Tasks / Processes" (#193) | Partly | v3 has an entry-type taxonomy (`docs/vault-format.md:363-381`) and optional per-type schemas; v2's `process` and task workflows are **Missing** in v3 (`docs/migrate-from-v2.md:90`). MemPalace has halls (five fixed categories) and a temporal KG |
| "Highly token-efficient … MemPalace floods the context" (#200) | Overstated | Both bound their output (§2.3, §4.3). palaia's edge is the *unit*: a curated note with atomic observations degrades cleanly; a raw exchange pair does not |
| "Palaia stores knowledge, MemPalace stores text" (#200) | Directionally | True for the primary layers; both have exceptions (§2.2, §4.2) |
| "Knowledge OS / second brain for an agent team" (#200) | Needs care | MemPalace's shared-brain guide uses nearly the same words: "One memory, many minds" (shared-brain). The positioning is contested, not open |

## 6. Feature by feature

palaia column is code-grounded (cited in §4–5). MemPalace column is as documented
(§2), 2026-09-27.

| Dimension | palaia v3 | MemPalace 3.10 |
|---|---|---|
| **Primary store** | Markdown vault, YAML frontmatter, Obsidian-compatible, formally specified (`docs/vault-format.md`) | Vector DB (ChromaDB default, five alternatives) |
| **What is stored** | Agent-authored notes and captures; curated into entities, observations, relations | Verbatim file chunks and conversation exchange pairs; LLM-derived closets on top |
| **Conversation capture** | None (§4.1) | Mining, `sweep`, Stop/PreCompact/SessionEnd hooks for Claude Code, Codex, Cursor |
| **Who decides what to keep** | The agent at capture time, then a curator | Nobody — keep everything, search later |
| **Retrieval** | FTS5 + vectors, RRF, decay rerank, graph traversal, token-budgeted context | Semantic search + wing/room filters; hybrid boosts; optional LLM rerank; L0–L3 wake-up |
| **Model calls on recall** | 0 | 0 in raw/hybrid; ≥1 with rerank (optional) |
| **Human readability** | Plain files; edit in any editor; external edits re-indexed live (`MASTERPLAN.md:228-230`) | Through CLI/MCP; no file layer documented |
| **Audit and undo** | A git commit per change with agent, client and reason (`docs/how-it-works.md:18-20`) | Not documented (**UNVERIFIED**) |
| **Write governance** | Adding is autonomous; rewrite/merge/retire only as an approved proposal (`MASTERPLAN.md:270-273`) | Any client with the token can update or delete drawers |
| **Auth** | OAuth 2.1 with DCR + PKCE, IdP sign-in, per-client tokens, per-vault scopes, exposure modes (`docs/how-it-works.md:45-53,152-157`) | One shared bearer token per server; server-wide `--read-only` |
| **Multi-agent** | Session directory + structured messenger with `handoff` type (`server/src/palaia_hub/messenger/models.py:45`) | Logstream events + artifact handoffs; per-agent wings and diaries |
| **Beyond memory** | Tool gateway, add-on marketplace, external MCP servers, automations, dashboard (`docs/how-it-works.md:38-88`) | Memory and coordination only |
| **Retention / pruning** | Missing (`docs/migrate-from-v2.md:85`) | `sync`, prune commands, `audit` |
| **Default embedding** | `all-MiniLM-L6-v2`, English-only (`server/src/palaia_hub/index/embeddings.py:50`) | Same default; `embeddinggemma-300m` (multilingual) recommended at onboarding |
| **Published retrieval benchmark** | None | LongMemEval, LoCoMo, ConvoMem, MemBench |
| **Install** | Docker appliance + web wizard | `uv tool install`, pipx, Docker, agent-guided skill |
| **Licence** | MIT (`server/pyproject.toml:7`) | MIT |

## 7. Recommendations

### 7.1 Positioning

1. **Stop describing MemPalace as a local vector store.** The internal picture from
   #193 is five months old. Treat it as a direct competitor for the multi-agent
   memory hub, with a much larger community (59k stars) and a benchmark story that
   is now careful and reproducible.
2. **Differentiate on ownership and governance, not on retrieval cost.** palaia's
   defensible ground against MemPalace is: memory as files a person reads and edits,
   a git history of every change, a curator that cannot silently rewrite what
   exists, real per-client auth, and a hub that also carries the user's tools.
   MemPalace's strength — raw fidelity — is exactly what palaia gives up; say so
   rather than pretend otherwise.
3. **Frame the storage difference as a trade-off, not a win.** "Store everything,
   make it findable" and "store what matters, make it maintainable" answer
   different questions. MemPalace wins "what exactly did we say in March?". palaia
   wins "what do we currently believe, who decided it, and can I correct it?".

### 7.2 Differentiation copy (draft — not applied)

Suggested for a comparison or FAQ page on the docs site. Every clause is backed by
§4–§6.

> **Memory you can read, correct and audit.**
>
> Some memory systems keep every word of every conversation and search it later.
> That is great for recall of the exact wording, and it is the right tool if that is
> what you need. palaia keeps something different: what your agents decided was
> worth knowing, written down as plain Markdown notes in a folder you own.
>
> - **You can read it.** Open the vault in Obsidian or any editor. No database
>   client, no export step.
> - **You can correct it.** Edit a note by hand and every connected AI sees the fix
>   on its next lookup.
> - **You can see who changed what.** Every change is a git commit naming the agent,
>   the client and the reason. `git revert` is your undo.
> - **Nothing is silently rewritten.** Agents and the curator may add knowledge on
>   their own. Rewriting, merging or retiring a note only ever becomes a proposal
>   you approve.
> - **Each tool gets its own key.** Sign-in with GitHub, Google or OIDC, OAuth for
>   clients that support it, a separate token for those that don't — and each one
>   can be limited to read-only, per memory library.
>
> What palaia does not do: it does not archive raw transcripts. If you need the
> verbatim record of a session, keep it — palaia is where the conclusions go.

### 7.3 Claims we must not make

- ❌ "Recall costs no model call" *as a differentiator against MemPalace.* It is
  true for palaia (`docs/how-it-works.md:25-28`) and equally true for MemPalace's
  headline 96.6%. Keep the sentence in how-it-works — it is a real property — but
  do not use it in any comparison with MemPalace.
- ❌ "Verbatim storage doesn't scale; palaia's GC/tiering handles growth." v3 has no
  knowledge GC and no physical tiering (§5).
- ❌ "palaia is zero-dependency, MemPalace needs ChromaDB." MemPalace ships
  SQLite-only backends (`sqlite_exact`, `rust_exact`); palaia v3 ships as a container.
- ❌ "MemPalace scores 100%", or any MemPalace number without the words "retrieval
  recall (R@5)". Quote 96.6% raw and 98.4% hybrid held-out.
- ❌ "More accurate than MemPalace." palaia has no retrieval benchmark (§3).
- ❌ "MemPalace has no access control." It has a bearer token and a read-only mode;
  the accurate claim is "no per-client permissions".

### 7.4 Follow-ups worth filing (listed, not filed)

| # | Follow-up | Why | Effort |
|---|---|---|---|
| F1 | **Retrieval eval on LongMemEval_S.** A reproducible harness that loads each question's sessions into a scratch vault (one note per session) and reports R@5 / R@10 at the *same session-level metric* MemPalace uses, in FTS-only and hybrid mode. Commit per-question results | palaia has no public quality number; this is the only apples-to-apples comparison available, and #193 asked for it. Publish whatever it shows | M |
| F2 | **Optional verbatim source archive.** A physically separate vault (e.g. `sources`) that accepts raw transcripts or documents chunked into notes, with curated notes linking to the source note they came from (`[[…]]` or `memory://`) | Closes the fidelity gap without diluting the curated vault; reuses vault isolation (`MASTERPLAN.md:247-251`) and the missing `ingest` (`docs/migrate-from-v2.md:87`) | M–L |
| F3 | **Keep a link from curated note to original capture.** Today the capture is deleted after verification and only git remembers it (§4.4). Either keep the `[raw]` text as an observation on the target note, or record the capture's commit so `read` can show the original wording | Cheapest step toward "no information loss" without a transcript archive | S |
| F4 | **Pre-compaction / session-end capture hooks for v3 clients** (Claude Code, Codex), feeding the inbox. Continues #185's analysis on the v3 track | MemPalace's hooks capture by default; palaia v3 captures only when a skill persuades the agent to | M |
| F5 | **Retention and prune for v3.** Recompute decay and propose retirement of stale notes through the review queue | The scaling argument in #193 needs this to be true for v3 | M |
| F6 | **Offer a multilingual embedding model** as a documented choice in setup | Same English-only default as MemPalace, but MemPalace steers users to a multilingual model at onboarding; non-English vaults are a realistic case for palaia too | S |

F1 is the one to do first: every other positioning claim is stronger with a number
behind it, and weaker without one.

## 8. To verify

1. Does MemPalace keep any per-change history or undo for drawers (beyond backend
   snapshots)? §6's "Audit and undo" row assumes not.
2. Are closets and `--extract general` on by default for mining, or opt-in? This
   decides how "verbatim-only" a default palace really is.
3. Does MemPalace have per-client tokens on its roadmap? If it ships them, §6's auth
   row narrows.
4. How large is MemPalace's actual contributor count (the API page stops at 100)?

## 9. Sources

| Claim | Location |
|---|---|
| Capture tool fields and description | `v3/server/src/palaia_hub/gateway/memory_tools.py:594-665` |
| Recall and `build_context` tools | `v3/server/src/palaia_hub/gateway/memory_tools.py:498-592` |
| Capture body: `content` stored as `[raw]` | `v3/server/src/palaia_hub/gateway/inbox.py:103-118` |
| Capture skill: skip the conversation; values verbatim | `v3/clients/skills/palaia-capture/SKILL.md:49-50,59-60` |
| Capture contract "the knowledge verbatim" | `v3/MASTERPLAN.md:268-269` |
| Curator role prompt, provenance line, "never invent facts" | `v3/server/src/palaia_hub/curator/prompt.py:28-45` |
| Inbox note deleted after verification | `v3/docs/vault-format.md:414` |
| Entry taxonomy | `v3/docs/vault-format.md:363-381` |
| Token budget tiers, default 4,000 | `v3/server/src/palaia_hub/recall/budget.py:1-28,50` |
| RRF k=60 | `v3/server/src/palaia_hub/index/search.py:44-46` |
| Logical decay, no file moves | `v3/server/src/palaia_hub/recall/ranking.py:1-7` |
| Default embedding model | `v3/server/src/palaia_hub/index/embeddings.py:50` |
| Atomic writes | `v3/server/src/palaia_hub/vault/atomic.py:62-81` |
| Git layer and git gc | `v3/server/src/palaia_hub/vault/gitlayer.py:1-21` |
| Per-vault read/write scopes, fail-closed | `v3/server/src/palaia_hub/auth/scopes.py:1-16` |
| Messenger `handoff` type | `v3/server/src/palaia_hub/messenger/models.py:45` |
| Importers (v2, basic-memory only) | `v3/server/src/palaia_hub/importers/` |
| Benchmarks in repo (speed, skill activation) | `v3/server/src/palaia_hub/index/bench.py:1-18`, `v3/server/tests/effectiveness/harness.py:1-27` |
| Prune/gc, process, ingest missing in v3 | `v3/docs/migrate-from-v2.md:85,87,90` |
| Vault, index, isolation, curator, two-tier rule | `v3/MASTERPLAN.md:223-230,247-251,262-280` |
| Recall costs no model call; auth; exposure; beyond memory | `v3/docs/how-it-works.md:18-20,25-28,38-88,143-157` |
| P1/P4 pillars | `v3/MASTERPLAN.md:63-87` |
| palaia licence | `v3/server/pyproject.toml:7`, `LICENSE` |
| MemPalace metadata, releases | GitHub REST API, `repos/MemPalace/mempalace` and `/releases`, accessed 2026-09-27 |
| MemPalace README, HISTORY, BENCHMARKS, CHANGELOG, guides | URLs in "Evidence base", accessed 2026-09-27 |
| LongMemEval_S size (~115k tokens, ~40 sessions) | https://github.com/xiaowu0162/LongMemEval, accessed 2026-09-27 |
