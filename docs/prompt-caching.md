# Prompt Caching vs. Auto-Recall

Palaia's Auto-Recall and an LLM provider's prompt caching pull in opposite
directions. Auto-Recall makes the prompt prefix *different* on every turn;
prompt caching only pays off when that prefix stays *identical*. You can run
either one well — running both means the cache is invalidated on most turns.

This page states what palaia actually injects, where, and how to configure the
trade-off. All claims below are read off the plugin source in
`packages/openclaw-plugin/`.

## How prompt caching works

Providers cache a prompt by its prefix: the request is matched against the
cached prompt from the start, and the reusable region ends at the first
difference. Everything from that point on is processed as fresh input.
Consequence: a change near the front (system prompt) invalidates far more than
a change near the end (the newest user message).

OpenClaw 2026.4.5 made its side of this deterministic — normalized system-prompt
fingerprints, deterministic MCP tool ordering, no duplicate in-band tool
inventories — so follow-up turns hit the cache. The plugin SDK mirror in
`packages/openclaw-plugin/src/types.ts` shows the telemetry OpenClaw hands to a
context engine: `promptCache.observation.broke` plus a change code naming the
cause — `systemPrompt`, `tools`, `model`, `transport`, `streamStrategy`,
`cacheRetention`. `systemPrompt` is the one palaia triggers.

## What palaia adds to a prompt

| What | Where it lands | Changes per turn? |
|------|----------------|-------------------|
| Auto-Recall block (`## Active Memory (palaia)`) — ContextEngine path | system prompt, via `systemPromptAddition` (`src/context-engine.ts`) | **yes** |
| Auto-Recall block — legacy hook path | prepended to the newest user message, via `prependContext` (`src/hooks/index.ts`) | **yes**, but at the end of the prefix |
| Recall marker instruction (`showMemorySources: true`) — legacy hook path | system prompt, via `appendSystemContext` | **yes** — present only on turns that recalled |
| Session briefing (`## Session Briefing (palaia)`) | same channel as the recall block | once per session start / model switch |
| Memory tool usage hints | system prompt, via `registerMemoryCapability` | no — static per available tool set |
| Memory tools (`memory_search`, `memory_get`, `memory_write`) | tool inventory | no |
| Auto-Capture | nothing — runs *after* the turn, as a separate LLM call | n/a |

Which of the two recall paths you get is decided at load time: palaia registers
a ContextEngine when the host offers `registerContextEngine`, otherwise it falls
back to the legacy hooks (`packages/openclaw-plugin/index.ts`). Hosts that expose
`registerContextEngine` — the interface the plugin mirrors is OpenClaw v2026.5.7 —
take the ContextEngine path, the one that writes into the system prompt.

## Why the injected block is different on almost every turn

Auto-Recall is not a fixed block of text. With the defaults:

- `recallMode: "query"` builds the search query from the last user message(s),
  so a new question produces a new result set.
- `recallRecencyBoost: 0.3` and `manualEntryBoost: 1.3` re-rank results by entry
  age and origin — the *same* query can return the same entries in a different
  order tomorrow.
- New memories arrive continuously: Auto-Capture writes after turns, and tier
  decay moves entries in and out of HOT.
- When query recall finds nothing, palaia falls back to injecting the HOT list —
  which changes whenever HOT changes.
- `recallMinScore` does **not** gate injection. It only decides whether a turn
  counts as a "relevant recall" for the 🧠 marker. Low-scoring hits are injected
  anyway.

The block is capped at `maxInjectedChars` (default 4000 characters, roughly
1000 tokens). That cap is also the size of the damage: on the ContextEngine
path, a changed block means the system prompt and everything after it —
conversation history included — is re-read as fresh input instead of served from
cache. The cache miss is not proportional to the 4000 characters; it is
proportional to the whole conversation that sits behind them.

We publish no measured token or cost numbers here: the actual price depends on
your provider's cache-read/cache-write rates, your conversation length, and how
often recall returns something new. Measure it on your own traffic — OpenClaw
2026.4.5 added `openclaw status --verbose` cache diagnostics for exactly this —
before assuming either direction is cheaper for you.

## Option A — caching first

Turn Auto-Recall off, keep memory as a tool the agent calls on demand:

```json5
// openclaw.config.json5
{
  plugins: {
    config: {
      palaia: {
        memoryInject: false,
      },
    },
  },
}
```

You get:

- A stable system prompt from palaia's side — no recall block, no toggling
  recall marker instruction. Cache hits on follow-up turns behave as OpenClaw
  intends.
- Memory is still fully available: `memory_search`, `memory_get` and (if allowed
  for the agent) `memory_write` stay registered, as do the static usage hints.
  Auto-Capture keeps writing — it runs after the turn and never touches the
  prompt prefix.

You lose:

- Proactive recall. The agent only remembers what it explicitly searches for, so
  it has to *decide* to look — or you have to ask it to.
- Session briefings. Both delivery points are behind `memoryInject`, so
  `memoryInject: false` also means no `## Session Briefing (palaia)` at session
  start or after a model switch, even with `sessionBriefing: true`.

## Option B — recall first (default)

Keep `memoryInject: true` and accept the cache misses. This is the default
because proactive recall is palaia's point: the agent brings up the relevant
decision, process or task without being asked.

If you stay here, you can still reduce the blast radius:

```json5
{
  plugins: {
    config: {
      palaia: {
        memoryInject: true,
        maxInjectedChars: 1500,   // default 4000 — smaller injected block
        maxResults: 5,            // default 10 — fewer entries, less churn
        tier: "hot",              // default — don't widen to warm/all
        showMemorySources: false, // default true — drops the toggling
                                  // system-prompt instruction (legacy path)
        recallRecencyBoost: 0,    // default 0.3 — stop age-based re-ranking
      },
    },
  },
}
```

These make the block smaller and less volatile. None of them makes it stable:
as long as recall is query-driven and the store keeps changing, the prefix keeps
changing. `recallMode: "list"` is context-independent and therefore varies less
from turn to turn, but it still follows the HOT tier and is not cache-stable
either.

## Which one for which use case

| Situation | Choose |
|---|---|
| Long, context-heavy sessions on one topic; the agent needs your history | **B** — this is where recall earns its keep |
| Short, repetitive, high-volume turns over a large fixed system prompt | **A** — the cached prefix is the dominant cost |
| Many parallel agents on one large shared prompt | **A**, plus `memory_search` in the agent's instructions |
| Human-facing assistant where "it remembered" is the product | **B** |
| Cost is the hard constraint and memory is a nice-to-have | **A** |

If you are unsure: start with the default (**B**), watch your cache-hit rate for
a few days, and switch if the numbers justify it. The toggle is a single config
key and a gateway restart — nothing in the store changes.

## What palaia does not do (yet)

- It does not read OpenClaw's cache telemetry. `ContextEnginePromptCacheInfo` is
  mirrored in the plugin's types but palaia's engine ignores it — recall does not
  back off when the host reports a broken cache.
- It has no cache-stable injection zone: there is no deterministic, rotate-only-
  on-threshold recall block. Every successful recall rewrites the block.

Both are tracked in
[#195](https://github.com/byte5ai/palaia/issues/195). Until one of them lands,
the choice above is the whole story.
