# Smart Nudges — deterministic guidance in agent-facing output

> Implemented by [issue #301](https://github.com/byte5ai/palaia/issues/301) as
> `palaia_hub.nudges` (the detector layer) plus
> `palaia_hub.gateway.guidance` (the MCP adapter). Describes what exists
> today; §5 lists what is deliberately not built yet.

## 1. What a nudge is

A **Smart Nudge** is a live micro-skill: one contextual, actionable line
injected into the output stream an agent actually reads, at the moment
palaia deterministically sees the need.

Skills are how an agent *learns* a behavior. They are not enough on their
own, because an agent does not keep every skill in view at all times. A
nudge is the heads-up at the point of action — and it is the
token-efficient half of the pair: a one-liner delivered when it applies
costs a fraction of holding the same instruction in context on every call.

Two properties define it:

- **Deterministic origin.** Every nudge comes from a fact the hub already
  computed — a degraded index, a backlog count, an unresolved reference.
  Never from a model call. That is the point: these are exactly the signals
  an LLM is weakest at noticing on its own.
- **Context is the budget.** Guidance that rides along on results costs
  tokens on results. Hence the caps and the cooldown in §3.

## 2. Where it lands

Detection happens on the way out of a memory tool. Every *successful* result
goes through `_ok()` in `palaia_hub.gateway.memory_tools`, which hands the
result object to the detector layer and attaches whatever the rate policy
allows:

- the human-readable half gets a trailing `Guidance:` block, one `- ` line
  per nudge;
- `structured_content` gets a `guidance` list of the same strings.

Both halves, because different clients read different halves. The field
appears **only when there is something to say** — an always-present empty
list on every payload would be precisely the per-call cost this design
avoids, and these tools publish no fixed output schema that a stable shape
would serve.

Error results never carry guidance. An error already names its own fix, and
is the wrong moment to staple an unrelated instruction to it.

## 3. The rate policy

`NudgeEngine` (`palaia_hub.nudges.service`) enforces three things:

1. **Per-session cooldown.** A nudge's `(key, state)` identity stays quiet
   for 15 minutes after firing, per MCP session. A detector may set a coarse
   `state` fingerprint so a materially changed condition speaks up again
   before that expires — an inbox backlog crossing into the next bucket of
   ten, an index going from "still embedding" to "unavailable". A
   fingerprint that changed on every call would be the same as no rate limit
   at all, which is why detectors bucket rather than pass raw counts.
2. **Per-result cap.** At most two nudges on one result. A nudge crowded out
   by the cap is *not* marked as said, so it is still available next call.
3. **Bounded memory.** Sessions and identities are remembered in LRU order
   and evicted. Eviction can only ever re-allow a nudge, never suppress one:
   the failure mode is "said once more than strictly necessary".

## 4. The seeded detectors

Each is a pure function over `VaultSignals` — a flat record of
already-computed facts. No detector costs an extra read, query or model
call. Each text says what happened, then names the fix.

| Key | Fires on | Says |
|---|---|---|
| `recall.degraded` | `recall` answered with vectors pending/unavailable | results are text-only; rerun later or use the note's exact words |
| `search.no_hits` | `search` matched nothing | try `recall` — it ranks by meaning, not words |
| `context.dropped` | `build_context` could not fit notes it found | raise `max_tokens`, or narrow `depth`/`timeframe` |
| `context.shortened` | `build_context` summarized to fit | same fix, for notes you need in full |
| `inbox.backlog` | 10+ uncurated captures | let the curator propose filings |
| `capture.duplicate` | a capture was deduplicated | edit the named note instead of recapturing |
| `read.unresolved_values` | a note's value references did not resolve | what you read is missing current values |

## 5. Not built yet

Three detectors named in the issue need a signal that does not reach a tool
result today, and are left out rather than faked:

- **a write landed in a vault whose index rebuild is pending** — "just-saved
  notes may not be findable for a moment";
- **token near expiry / profile changed since the token was minted**;
- **vault doctor `verify` findings present** — `verify()` is an engine-side
  call behind the dashboard and the reindex/repair path
  (`palaia_hub.vault.doctor`); no memory tool returns its findings, so there
  is no result for a nudge to ride along on yet.

Each is one field on `VaultSignals` and one function in `detectors.py`, not
a change to this mechanism.

Also out of scope here, and deliberately: **LLM-generated nudges** (the
whole point is the deterministic origin), **nudging on every output** (the
context-window cost), and **replacing skills** (skills remain how an agent
learns behaviors; a nudge is the runtime heads-up).

## 6. Reusing the layer elsewhere

`palaia_hub.nudges` imports nothing from MCP, the gateway or the vault. A
second surface — the dashboard, the CLI (v2 precedent: nudges in CLI output)
— reuses the same detectors by filling the same `VaultSignals` record from
its own state and supplying its own session-key callable. The MCP adapter in
`palaia_hub.gateway.guidance` is the only place that knows about tool
results.
