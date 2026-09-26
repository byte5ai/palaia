# OpenClaw prompt caching vs. palaia Auto-Recall — audit (#195)

Issue [#195](https://github.com/byte5ai/palaia/issues/195) · intel review · written
2026-09-26.

> **Audit, not an implementation.** It answers the issue's question — does palaia's
> OpenClaw Auto-Recall break OpenClaw's prompt caching? — from source on both sides,
> and scopes a fix without building it. The fix, if accepted, lands in the frozen v2
> plugin and needs its own PR against `v2-maintenance`; nothing under `packages/` is
> touched here.

## Evidence base

| Side | Source | Version |
|---|---|---|
| palaia | `packages/openclaw-plugin/` read via `git show origin/v2-maintenance:…` | `origin/v2-maintenance` @ `830fdfa` (plugin `2.8.0`, peer dep `openclaw >=2026.5.7`) |
| OpenClaw | shallow clone of [github.com/openclaw/openclaw](https://github.com/openclaw/openclaw), accessed 2026-09-26 | `main` @ `be46e69` (`package.json` version `2026.9.6`) |
| Provider caching semantics | [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), via a cached reference copy, 2026-09-26 | re-check rates before quoting them externally |

palaia citations are `packages/openclaw-plugin/<path>:<line>` on `origin/v2-maintenance`
(abbreviated `src/…` below). OpenClaw citations are `<path>:<line>` at `be46e69`. Unlike
#185 and #194, this audit had network access, so claims about OpenClaw's behaviour are
read off its source rather than inferred from palaia's type mirror. Everything that is
still an inference — mostly runtime behaviour nobody has measured — is marked
**UNVERIFIED**.

Prior art on `v2-maintenance`: `docs/prompt-caching.md` (#199, 2026-09-20) already
documents the trade-off and a `memoryInject: false` escape hatch, and names #195 as the
tracking issue for a real fix. It was written from palaia's side only. §6 lists where the
upstream source corrects it.

## 1. Verdict

**Yes, there is a cache-miss problem — but not the one the issue describes, and the
issue's gating question has a surprising answer.**

1. **The normalized system-prompt fingerprint is not affected.** OpenClaw fingerprints
   only the *stable prefix* of the system prompt, above an internal cache boundary.
   palaia's recall block lands *below* that boundary. So the 2026.4.5 fingerprint change
   neither helps nor hurts palaia — the fingerprint was never the problem.
2. **The prefix is still invalidated, from the boundary onward, on every turn the block
   changes.** On Anthropic-style routes (explicit checkpoints; OpenClaw's default provider
   family) the conversation checkpoint covers tools, the whole system prompt and all
   messages. A changed volatile suffix therefore misses the **entire conversation
   history** every turn; only tools and the stable system prefix are still read from
   cache. OpenClaw's own docs say so. OpenAI Responses routes behave the same way. Direct
   Gemini is the exception: it moves the volatile suffix out of the cached prefix.
3. **The block changes almost every turn, some of it self-inflicted.** The recall query
   follows the latest user message. Auto-capture writes the previous turn into the store,
   where it gets a recency boost into the next turn's results. Order is by a score that
   includes a continuously decaying recency term. One-shot nudges and the session
   briefing come and go.
4. **Gating finding, outside the issue's scope: with the documented configuration,
   Auto-Recall may not run at all on supported hosts.** palaia registers a context engine
   whenever the host offers `registerContextEngine` — which every host at palaia's
   declared floor (`>=2026.5.7`) does. When it does, palaia skips its legacy hooks. But
   OpenClaw only runs a plugin engine that is selected via `plugins.slots.contextEngine`,
   and palaia's docs only set `plugins.slots.memory`. If that reading holds, the
   documented setup gets **neither Auto-Recall nor Auto-Capture**, and the cache problem
   only affects users who selected the engine by hand. This is read from source, not
   observed at runtime (**UNVERIFIED**, §5). It needs its own issue.

**Recommendation:** the fix belongs in the v2 plugin, so this PR uses `Refs #195`, not
`Closes`. §7 scopes the fix; start with its cheap part (deterministic rendering plus
hysteresis). Moving recall to the user-turn side, as the issue suggests, does **not** fix
this by itself (§4.3).

## 2. What palaia injects, and where

### 2.1 Which path runs

`index.ts:88-98` chooses the path once, at load:

- `api.registerContextEngine` exists → register the `palaia` context engine
  (`createPalaiaContextEngine`), and **do not** call `registerHooks()`.
- otherwise → `registerHooks(api, config)`, the legacy hook path.

In current OpenClaw, `registerContextEngine` is a non-optional member of the plugin API
(`src/plugins/plugin-api.types.ts:340`), accepted from any plugin regardless of its
`kind` (`src/plugins/registry-registrars-capabilities.ts:89-130`). **On every supported
host, palaia therefore takes the context-engine path.** The legacy path matters here only
because its injection style — `prependContext` — is what the issue proposes as the fix
(§4.3).

### 2.2 Context-engine path — `assemble()` → `systemPromptAddition`

`src/context-engine.ts:466-554`. On each call:

1. `buildMemoryContext()` (`:94-245`) builds a query from the transcript
   (`buildRecallQuery`), retrieves up to `maxResults` entries (embed server → CLI → HOT
   list fallback), reranks them (`rerankByTypeWeight`), and renders
   `## Active Memory (palaia)` (`:182`) up to `min(maxInjectedChars, …)` characters
   (`:110`, default 4000, `src/config.ts:92`).
2. It appends a static `USAGE_NUDGE` (`:196`), any one-shot nudges from `checkNudges()`
   — it increments a persisted `successfulRecalls` counter on every call (`:200`) — and
   config-dependent isolation nudges (`:218`, `:228`).
3. Once per session, or after a model switch, it prepends `## Session Briefing (palaia)`
   (`:506-526`).
4. It returns everything as **`systemPromptAddition`** (`:545`).

### 2.3 Legacy hook path — `before_prompt_build` → `prependContext` + `appendSystemContext`

`src/hooks/index.ts:340-566`. The same retrieval and render, returned as
`{ prependContext: briefingText + text, appendSystemContext: … }` (`:556-561`).
`appendSystemContext` is the 🧠-marker instruction whenever `showMemorySources` is on
(default `true`, `src/config.ts:97`). It is present on every turn that returns entries and
absent on turns that return none (`:470`, `:479`, `:483`). The hook never uses
`prependSystemContext` or `systemPrompt`.

### 2.4 Static contributions (cache-neutral)

- Memory tool guidance via `registerMemoryCapability({ promptBuilder })`
  (`index.ts:60-78`). It depends only on the available tool set. Upstream renders the
  memory section inside the stable prefix: `src/agents/system-prompt.ts:1022` sits before
  the boundary push at `:1104`.
- Tool definitions `memory_search` / `memory_get` / `memory_write` — static per config.
- Auto-capture runs after the turn (`afterTurn`) and never touches the prompt. It does,
  however, change the next turn's recall results (§3).

## 3. Is the injected block deterministic across turns?

No. The rendered text contains no timestamps and no scores — `formatEntryLine()` emits
scope/type tag, title, body and optional id (`src/hooks/recall.ts:411-432`). But nearly
everything upstream of the renderer varies:

| Source of churn | Where | Effect |
|---|---|---|
| Query built from the latest user messages | `buildRecallQuery`, `recall.ts:268-329` | a new question produces a new result set — by design |
| Order is `weightedScore` descending | `recall.ts:397` | order is part of the bytes |
| Recency boost `1 + f·e^(−hours/24)` computed against `Date.now()` | `recall.ts:355-361`, default `f = 0.3` (`config.ts:107`) | the same entries can swap places between two turns with no data change |
| Auto-capture writes the finished turn into the store | `afterTurn` → `runAutoCapture` | the new entry is maximally recency-boosted and on-topic, so it tends to enter the **next** turn's block — self-inflicted churn on every capturing turn (**UNVERIFIED** as a frequency; the mechanism is in code) |
| HOT-list fallback when query recall is empty | `context-engine.ts:153-170` | follows tier movement |
| One-shot nudges; `successfulRecalls` counter | `context-engine.ts:197-210` | one extra change when a nudge fires; the counter itself is not rendered |
| Session briefing, with relative "`Nm ago`" text | `src/hooks/session.ts:117-122` | present on the first turn (or after a model switch), gone on the next → one change each time |
| Legacy only: `appendSystemContext` toggles with "entries found" | `hooks/index.ts:470-483, 556-561` | a system-suffix change on every flip |

Within a turn it is stable. `assemble()` runs once per attempt: its only call site is
`src/agents/embedded-agent-runner/run/attempt-history-prepare.ts:203`. The system prompt
it produces is therefore reused across the model calls of that attempt's tool loop.
Overflow retries re-assemble and can differ.

## 4. Where OpenClaw places it, and what that costs

### 4.1 The cache boundary and the fingerprint

- OpenClaw's system prompt carries a marker `<!-- OPENCLAW_CACHE_BOUNDARY -->`
  (`packages/ai/src/utils/system-prompt-cache-boundary.ts:8`), pushed at the end of the
  stable part (`src/agents/system-prompt.ts:1104`).
- **`systemPromptAddition`** goes through `prependSystemPromptAddition()` →
  `prependSystemPromptAdditionAfterCacheBoundary()`
  (`src/agents/embedded-agent-runner/run/attempt-prompt-helpers.ts:440-445`,
  `system-prompt-cache-boundary.ts:82-110`). It lands at the **start of the volatile
  suffix**, directly after the marker. The docs still say "prepended to the system prompt"
  (`docs/concepts/context-engine.md:116`, `:304-306`); the code puts it after the
  boundary.
- **`appendSystemContext`** is joined after the base prompt
  (`attempt-thread-helpers.ts:22-41`), so it also lands in the volatile suffix.
  **`prependSystemContext`** would land above the boundary. The hook types say so:
  "Prepended to the agent system prompt so providers can cache it … Use for static plugin
  guidance instead of prependContext" (`src/plugins/hook-before-agent-start.types.ts:40-50`).
- **The fingerprint.** Cache observation hashes the stable prefix as `systemPromptDigest`
  and the suffix separately as `systemPromptSuffixDigest`
  (`src/agents/embedded-agent-runner/prompt-cache-observability.ts:290-306`), reporting
  change codes `systemPrompt` and `systemPromptSuffix` respectively (`:14-22`, `:216-227`).
  The 2026.4.5 "normalized system-prompt fingerprints" item (`CHANGELOG/2026.4.5.md:36`,
  detail at `:38`) normalizes whitespace, line endings, hook-added context and capability
  ordering (`packages/ai/src/utils/prompt-cache-stability.ts:30-35`). It canonicalizes
  bytes; it does not exclude content. **palaia's block therefore shows up as
  `systemPromptSuffix`, never as `systemPrompt`.**

### 4.2 What a changed suffix costs, per provider family

Anthropic transport, `packages/ai/src/transports/anthropic-payload-policy.ts`:

- The system text is split at the boundary. The stable prefix gets `cache_control`; the
  dynamic suffix becomes a separate block **without** a marker (`:262-311`).
- The last tool gets a marker, and the latest user message (or tool result) gets the
  conversation marker (`:236-259`, `:331-409`). Only host-owned runtime-context carriers
  opt out of that marker (`packages/ai/src/transports/anthropic-messages.ts:199-204`).
- Render order is tools → system → messages, so the conversation checkpoint's prefix
  contains the volatile suffix.

OpenClaw's own reference states the consequence: *"A conversation checkpoint covers all
preceding tools, system content, and messages, so changing the volatile system suffix
still invalidates that later checkpoint; the earlier stable-system checkpoint remains
reusable"* (`docs/reference/prompt-caching.md:217-220`).

| Route (OpenClaw @ `be46e69`) | Suffix change invalidates | Source |
|---|---|---|
| Anthropic direct / Vertex, Bedrock Claude, Anthropic-marker Chat Completions (OpenRouter, DeepInfra, Model Studio) | everything after the stable-system checkpoint — **all history** | `anthropic-payload-policy.ts:236-409`; `docs/reference/prompt-caching.md:156, 207-224` |
| OpenAI Responses | from the changed point on — the suffix precedes history, so **all history** | `docs/reference/prompt-caching.md:151` |
| Google Gemini direct | nothing in history — the suffix travels in the current turn's transient carrier | `docs/reference/prompt-caching.md:189`; `src/agents/embedded-agent-runner/google-prompt-cache.ts:551-592` |
| CLI harnesses (Claude Code, Gemini CLI) | no OpenClaw-controlled markers; provider-internal | `docs/reference/prompt-caching.md` § CLI-harness providers |

### 4.3 Why "inject on the user-turn side instead" is not a fix by itself

The issue's item 2 suggests moving recall into a cache-stable zone, and the obvious
candidate is the user message — `prependContext`, which is what the legacy hook path
already does and what OpenClaw's own Active Memory plugin returns
(`extensions/active-memory/index.ts:449-518`). Upstream handles it like this:

- `prependContext` is added to `effectivePrompt`
  (`src/agents/embedded-agent-runner/run/attempt-prompt-build.ts:201-216`). The transcript
  keeps the bare prompt (`runtime-context-prompt.ts:65-88`,
  `attempt-prompt-phase.ts:406-440`: `transcriptPrompt: promptContext.promptForSession`).
- The model sees the recall-prefixed text only through a **model-only projection of the
  active user message** (`installModelPromptTransform`, `attempt-llm-boundary.ts:380-470`),
  pinned by the test *"replaces only the armed prompt with model prompt context"*
  (`attempt.llm-boundary.test.ts:856-922`).

On the next turn, that user message is replayed **without** its recall block, so it no
longer matches the bytes that were cached. On explicit-checkpoint routes, a read can only
land where an earlier request wrote a checkpoint, and every conversation checkpoint of
every earlier turn contained some since-stripped block. The history therefore misses
again, even though the block now sits at the tail. The Anthropic guidance calls the same
pattern out for per-turn reminders: a block injected and then removed on the next request
is a history edit. On automatic-prefix providers (OpenAI Chat Completions), reuse at
least extends to the start of the previous user message.

This is an inference from checkpoint semantics and has not been measured
(**UNVERIFIED**). The practical conclusion stands either way: **the user-turn side only
helps if past blocks are replayed byte-identically** (§7.3).

### 4.4 How big

Only a formula can be given without a measurement. Per turn, let **T** be tokens of tools
plus the stable prefix, **S** the volatile suffix (palaia's block **B** is ≤ ~1000 tokens
at the default 4000 characters), **H** the history before the current turn, and **U** the
new input. Anthropic multipliers, relative to base input price: cache write 1.25× (5-minute
TTL) or 2× (1-hour TTL); cache read ~0.1×. Read the current rates off the Anthropic page
before quoting them — Claude Fable 5.1 and Claude Opus 5.5 have cheaper reads.

| | Suffix unchanged | Suffix changed (today, most turns) |
|---|---|---|
| read from cache | T + S + H | T |
| written to cache | U | S + H + U |
| extra cost vs. unchanged | — | ≈ **(1.25 − 0.1) · (S + H) ≈ 1.15 · H** base-input tokens per turn (5 min TTL), ≈ 1.9 · H at 1 h TTL |

Illustration, arithmetic only and not measured: with H = 50 000 tokens of history, a turn
whose block changed costs ~57 500 base-input-token equivalents more than one whose block
did not. That is 1.25 × 50 000 written instead of 0.1 × 50 000 read. The damage grows
with conversation length, not with the size of the block, which is the point #199's doc
already made. Latency grows too, since uncached prefill is slower. Compaction resets H,
but palaia's engine declares `ownsCompaction: true` and does not reduce the transcript
(`context-engine.ts:397`, `:567-590`), so H keeps growing until the host's safeguards
step in.

## 5. Gating finding: the engine may not be selected at all

| Fact | Source |
|---|---|
| palaia skips legacy hooks whenever `registerContextEngine` exists | `index.ts:88-98` |
| `registerContextEngine` always exists on current hosts | `src/plugins/plugin-api.types.ts:340` |
| The engine that runs is `plugins.slots.contextEngine`, default `"legacy"` | `src/context-engine/registry.ts:684-705`, `registry-selection.ts:12-29`, `src/plugins/slots.ts:17-25`; docs: `docs/concepts/context-engine.md:129` |
| No coupling from the memory slot to the engine slot | `src/plugins/config-state.ts:66-83` (no `slots.memory` reference in `src/context-engine/`) |
| palaia's manifest declares `kind: "memory"` only, so enabling it cannot claim the engine slot | `openclaw.plugin.json:4`; `slots.ts` `applyExclusiveSlotSelection` maps kind → slot |
| palaia's docs activate it with `plugins.slots.memory` only | `README.md:25`, `skill/SKILL.md:87`, root `SKILL.md:87`; `palaia/doctor/checks.py:274-310` checks only `slots.memory` |

If this holds at runtime, a user who followed the docs has palaia's tools and session
hooks, but `assemble()` and `afterTurn()` never run. That means no `## Active Memory
(palaia)` block and no auto-capture — the capturing `agent_end` handler lives in
`registerHooks()`, which is skipped. Such a user sees no cache problem, because there is
nothing to cache-miss on.

**Status: UNVERIFIED at runtime.** Quick check on a live gateway:
`jq '.plugins.slots.contextEngine' ~/.openclaw/openclaw.json` (null or `"legacy"` means
palaia's engine is not active), then look for `## Active Memory (palaia)` in a
`--raw-stream-path` capture or `openclaw status --verbose`. The candidate fixes — docs plus
a doctor check for `slots.contextEngine: "palaia"`, or `kind: ["memory",
"context-engine"]` in the manifest — are out of scope here and belong in a new v2 issue.

## 6. Corrections to the existing v2 doc (`docs/prompt-caching.md`, #199)

| v2 doc says | Upstream says |
|---|---|
| "`systemPrompt` is the one palaia triggers" | palaia triggers **`systemPromptSuffix`**. The addition lands below the cache boundary, so the fingerprinted stable prefix is untouched (§4.1). The plugin's type mirror (`src/types.ts:380-392`) predates the `systemPromptSuffix` code. |
| ContextEngine path writes "into the system prompt" | into the **volatile suffix** after the cache boundary. The practical effect is still the full-history miss on Anthropic- and OpenAI-Responses-style routes, but tools and the stable prefix keep hitting, and **direct Gemini is unaffected** (§4.2). |
| Legacy path: "yes, but at the end of the prefix" | too optimistic on explicit-checkpoint routes: the block is a model-only projection, stripped from history next turn (§4.3). The path is also unreachable on supported hosts (§2.1). |
| "Hosts that expose `registerContextEngine` … take the ContextEngine path" | they register it; it only **runs** if `plugins.slots.contextEngine` selects it (§5). |

`packages/openclaw-plugin/tests/docs-prompt-caching.test.ts` pins parts of that doc, so a
v2 PR that edits it must update the test in the same change.

## 7. Fix proposal — scoped for a `v2-maintenance` PR

It targets the context-engine path only, the one that runs on supported hosts. It is
ordered cheapest first; each step is independently shippable and measurable. Whether a
performance fix qualifies for the maintenance-only v2 track (`AGENTS.md`) is a
maintainer's call — this proposal only sizes the work.

### 7.1 Step A — deterministic rendering (S)

The goal is to make the block's bytes a pure function of **which** entries were selected
and their content.

1. Keep ranking for **membership**: the budget still fills in `weightedScore` order. Then
   **render in a canonical order**, by entry id. Order stops depending on the
   clock-dependent recency term.
2. Move the static `USAGE_NUDGE` out of the block into the `memoryPromptBuilder` lines
   (`index.ts:60-72`), which upstream renders in the stable prefix (§2.4).
3. Move one-shot nudges and isolation nudges out of the block, into the same prompt
   builder, into `palaia doctor`, or into a log line. Nothing that fires once should sit
   in the per-turn block.
4. Session briefing: render an absolute date instead of "`Nm ago`"
   (`session.ts:117-122`). The appear-once/disappear-next change remains — one miss per
   session start or model switch, which is acceptable.

On its own, Step A only helps turns where the result **set** is unchanged. Its real value
is making Step B possible.

### 7.2 Step B — hysteresis: rotate only past a threshold (M)

Keep a per-session **pinned block**: the selected ids, a content hash per entry, and the
rendered bytes. Each turn, compute the candidate set as today, then re-render only if:

- **overlap drops** — `|candidates ∩ pinned| / |candidates| < θ` (proposed default
  θ = 0.5); or
- **a clearly better entry appears** — a candidate not in the pinned set has
  `weightedScore ≥ ρ × min(pinned score)` and `score ≥ recallMinScore` (proposed
  ρ = 1.5); or
- **a pinned entry was edited or deleted** — its content hash changed or it is gone; or
- **age** — the pinned block is older than N turns (proposed N = 20), as a staleness
  bound.

Otherwise, return the previous `systemPromptAddition` **byte-identically**. Entries that
auto-capture wrote during the current session never trigger a rotation on their own —
their content is already in the conversation. That removes the self-inflicted churn from
§3.

A new config key would gate this, for example `recallStability: "sticky" | "per-turn"`,
plus `θ`/`ρ`/`N`. The default has to be decided in review. `"sticky"` saves money by
default but can hold a less relevant block for a few turns. `"per-turn"` is today's
behaviour. Every rotation still costs one full-history write (§4.4); Step B reduces how
often that happens, not how much it costs.

Optionally, `afterTurn()` receives `runtimeContext.promptCache.observation`
(`src/context-engine/types.ts:325`). Logging a `systemPromptSuffix` break counter there
turns the effect into something users can see. A later iteration could adapt θ from it.

### 7.3 Step C — user-turn side with byte-stable replay (L, only if A+B are not enough)

`assemble()` owns the message list it returns: *"The engine returns an ordered set of
messages … that fit within the token budget"* (`docs/concepts/context-engine.md:77`). An
engine can therefore attach the recall block to the user message it was computed for,
and **replay every earlier block verbatim** from a per-session ledger keyed by message
identity. The history prefix then stays byte-stable, the system suffix carries no recall,
and each turn pays only for its own new block at the tail.

This is also the only design in which "inject on the user-turn side" actually works
(§4.3). Costs and risks:

- Context grows by up to one block per turn — combine with Step B, so only turns that
  rotate add a block.
- Ledger keys must survive compaction and transcript rewrites.
- An in-memory ledger lost on gateway restart costs one full miss.
- Whether synthetic content added in `assemble()` survives OpenClaw's sanitize, repair
  and boundary normalization byte-identically is **UNVERIFIED**.

Size it only after A+B are measured.

### 7.4 Not recommended

- **Using `prependSystemContext` for recall.** It sits above the boundary, so a changing
  block there would break the stable prefix *and* the fingerprint — strictly worse.
- **Using `prependContext` without replay.** It does not fix the problem (§4.3).
- **Doing nothing but documenting it.** #199's doc already covers that option.

## 8. Test plan

**Unit tests** — vitest, `packages/openclaw-plugin/tests/`, with the runner and embed
server mocked:

1. `assemble()` twice with the same messages and the same mocked entries → identical
   `systemPromptAddition`.
2. The same entries returned in a different score order → identical bytes (fails today).
3. Fake timers advanced by 24 h, same entries → identical bytes (fails today whenever the
   recency boost reorders them).
4. The candidate set differs by one low-ranked entry, above θ → identical bytes (Step B).
5. The candidate set drops below θ → new bytes, and exactly one change across the two
   calls.
6. A pinned entry's content changes → rotation.
7. An entry tagged `auto-capture` and created in this session enters the candidates →
   no rotation.
8. The static usage text appears in the `promptBuilder` output and not in
   `systemPromptAddition`.
9. `docs-prompt-caching.test.ts` updated alongside the doc corrections from §6.

**Host-level measurement** — manual, recorded in the PR:

- OpenClaw ≥ 2026.9.x, `plugins.slots.contextEngine: "palaia"`, an Anthropic model with
  `cacheRetention: "short"`.
- A scripted 10-turn conversation on one topic, then 5 turns on a second topic.
- Per turn, record `cacheRead` / `cacheWrite` from `openclaw status --verbose`, and
  `systemPromptSuffix` in the cache observation changes.
- Three arms: `memoryInject: false` (baseline), current plugin, and the fixed plugin.
- **Acceptance:** in the fixed arm, `systemPromptSuffix` changes only on rotation turns
  (≈ 1–3 in the topic switch, not 15), and `cacheRead` on non-rotation turns is within a
  few percent of the baseline arm.

**Slot check (§5)** — before any of the above, one run with only `slots.memory` set, to
confirm or refute that no recall block appears.

## 9. Documentation wording (issue item 3)

The issue asks for a SKILL.md/docs statement that Auto-Recall does **not** hurt prompt
caching, as a selling point. **That statement would be false today and must not ship.**
Proposed wording for the v2 surfaces, to go into the same v2 PR as the fix:

Until the fix ships, add to `SKILL.md` and the plugin README, next to `memoryInject`:

> **Prompt caching.** Auto-Recall changes the system prompt's dynamic part whenever the
> recalled memories change. On Anthropic and OpenAI models that means the conversation
> history is re-read instead of served from cache on those turns. Tools and OpenClaw's
> stable system prompt still hit the cache. Gemini is not affected. See
> `docs/prompt-caching.md` for the trade-off and the `memoryInject: false` option.

After Steps A+B ship, with numbers from the §8 measurement:

> **Prompt caching.** Auto-Recall keeps its memory block byte-stable while the recalled
> memories stay relevant, and replaces it only when the topic moves. In our measurement
> *<N of M>* turns reused the full cached conversation; the rest paid one cache rewrite
> each. Retrieval itself never calls a model.

Only the second version is a selling point, and only with the measured numbers filled in.

## 10. Remaining work

| Item | Where | Size |
|---|---|---|
| New issue: context-engine slot not selected by the documented config (§5) | v2 issue | S to verify, S–M to fix |
| Steps A + B, tests 1–9 | PR against `v2-maintenance` | M |
| Doc corrections (§6) and wording (§9), plus `docs-prompt-caching.test.ts` | same v2 PR | S |
| Host-level measurement (§8) | recorded in that PR | S |
| Step C, only if the measurement shows rotations dominate | later | L |

v3 is not affected. It has no prompt-build hook into any client and serves recall as an
MCP tool result inside the conversation (see #194, §1.2). Tool results sit at the tail of
the history and are replayed verbatim.

## 11. To verify

1. §5 at runtime: does a gateway configured per palaia's docs run palaia's engine?
2. §4.3 by measurement: on Anthropic, does a `prependContext`-only plugin (palaia legacy
   path, or OpenClaw's own Active Memory) really lose the whole history checkpoint on the
   next turn?
3. §7.3: does synthetic content returned from `assemble()` reach the provider
   byte-identically across turns?
4. Current Anthropic cache rates for the models palaia users run; §4.4 uses the generic
   1.25× / 2× / 0.1× multipliers.
