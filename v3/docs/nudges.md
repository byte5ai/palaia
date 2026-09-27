# Smart Nudges — deterministic guidance in agent-facing output

> Implemented by [issue #301](https://github.com/byte5ai/palaia/issues/301) as
> `palaia_hub.nudges` (the detector layer) plus
> `palaia_hub.gateway.guidance` (the MCP adapter). The similar-note check
> (§4.1) was added by [issue #187](https://github.com/byte5ai/palaia/issues/187).
> Describes what exists today; §5 lists what is deliberately not built yet.

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

One signal does not come for free: the similar-note check (§4.1). After a
successful `write`/`capture`, the tool asks the vault service
(`VaultService.similar_notes`) which existing notes the new one closely
resembles and hands that list to the detector layer alongside the result.
It is not a field on the result itself — `NoteRecord` is also what
`read`/`edit`/`move` return, and an always-present empty list there would be
exactly the per-call cost this design avoids.

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
| `write.similar_note` / `capture.similar_note` | the note just stored closely resembles an existing one (§4.1) | possible overlap or contradiction with the named note(s); edit that note instead of keeping two versions |

### 4.1 The similar-note check

The failure it targets is silent knowledge drift: an agent writes "GET
/health returns 404" while an older note still says "returns 200", and
recall serves both from then on. Nothing is blocked — the write has already
succeeded when the check runs — the result simply names the existing note(s)
(permalink and title, best match first, up to three as the 220-character
ceiling allows) so the agent can update the right note instead.

How it is measured:

- **A true similarity, never a rank.** The new note's text (title + body,
  shaped like the index's first chunk of a note; for a capture, what it
  concerns + its content) gets one query embedding, and the nearest indexed
  chunks are scored with sqlite-vec's `vec_distance_cosine`. A note's score
  is its best chunk's cosine similarity. BM25 and rank-fusion scores are
  only meaningful relative to one query's other hits
  ([#481](https://github.com/byte5ai/palaia/issues/481)) and are never
  held against the threshold.
- **Skipped, not guessed, without vectors.** With embeddings off, no index,
  or nothing embedded yet, the check answers nothing — there is no
  full-text fallback.
- **Never points at** the note just written, `meta` notes (format spec §6)
  or curator review proposals (§8). A deduplicated capture wrote nothing, so
  it gets `capture.duplicate` instead.
- **Bounded cost.** One query embedding per write/capture — about 15 ms on
  the default model, about 150 ms on bge-small — plus one vector lookup.
  The result waits at most 2 s for it (the first check after a restart may
  have to load the model); past that the write answers without the advice.
  This is the one place a write pays for an embedding; the note's own
  vectors still come only from the background worker.
- **Rate policy as usual.** The fingerprint (`state`) is the closest note's
  permalink: a second write resembling the same note stays quiet for the
  cooldown, one resembling a different note speaks up.

Configuration, in `config.yaml` (both optional):

```yaml
nudges:
  similar_note_check: true        # false skips the check entirely
  similar_note_threshold: 0.7     # cosine similarity, 0.5-1.0
```

The default threshold is measured, not guessed. On the default model
(all-MiniLM-L6-v2), pairs where one note updates or contradicts the other
scored 0.68-0.85; two notes on the same subject but different aspects
0.42-0.53; unrelated notes around 0.1. On BAAI/bge-small-en-v1.5 the same
contradiction pairs scored 0.77-0.87 and the same-subject pairs 0.63-0.65.
0.70 sits between the clusters for both. Note what it cannot tell apart:
templated notes (weekly meeting notes, two services described in the same
words) score 0.8+ without contradicting anything — which is why the text
says *possible* overlap or contradiction and leaves the judgment to the
agent. If you change the embedding model, re-check the threshold.

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

For the similar-note check, the v2-era proposal in issue #187 also asked
for a `contradiction` significance tag, a `superseded` marker, a review
workflow for flagged pairs and a confirm-to-override step. None of these is
built: significance tags are a v2 concept, a marker or review item would be
an automatic change to the vault that the nudge deliberately avoids (the
curator's review queue is where changes to existing notes are proposed), and
a warning that blocks would break the "never block the write" rule. What
exists is the advisory nudge.

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
