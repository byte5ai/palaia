# Pre-Compaction Capture — feasibility and design (#185)

> **Intel/design doc.** Ground truth is the code in this repository as of
> commit `49adc34`. Every claim about palaia is cited as `file:line`.
> Every claim about OpenClaw's *external* behaviour that this repository
> cannot prove is marked **UNVERIFIED** — this analysis was produced
> offline, with no access to the OpenClaw source, its docs, or the
> referenced GitHub PR.

## 1. Verdict

**Feasible — and the seam already exists in this repository.** But the
proposal in #185 is wired to the wrong half of the plugin, and if
implemented as written it would be a **no-op for the configuration most
users run**.

Three findings decide the design:

1. **`before_compaction` is already part of this repo's hook contract**
   (`packages/openclaw-plugin/src/types.ts:55`). No handler is registered
   for it anywhere. So the *name* is in the contract; only the *wiring* is
   missing. Registering it is a one-line, zero-risk addition — `api.on()`
   takes `HookName | string` (`types.ts:662`) and a hook the host never
   fires is simply never called.
2. **palaia already declares `ownsCompaction: true`**
   (`packages/openclaw-plugin/src/context-engine.ts:397`, changelog entry
   `CHANGELOG.md:18`, v2.7.3). On every host new enough to offer
   `registerContextEngine` — which is the primary path, see
   `packages/openclaw-plugin/index.ts:88` — palaia *is* the compactor.
   OpenClaw's own auto-compaction is suppressed by that flag, so a
   host-emitted "compaction imminent" event plausibly never fires there
   (**UNVERIFIED**, §3). The real pre-compaction moment on that path is
   palaia's own `compact()` (`context-engine.ts:559`), which today runs
   `palaia gc` and captures **nothing** from the conversation.
3. **The reusable force-capture entry point is not the `agent_end`
   handler.** #185 proposes "reusing the existing agent_end auto-capture
   code with a force flag". That code is an inline closure
   (`src/hooks/index.ts:581`–`864`) and cannot be called from anywhere
   else. The reusable twins are `captureSessionSummary()`
   (`src/hooks/session.ts:145`, exported, already used for `/new` and
   `/restart`) and `runAutoCapture()` (`context-engine.ts:251`, module
   private). `captureSessionSummary()` is the right one — and it needs a
   force flag for a concrete reason: its dedupe guard
   (`src/hooks/session.ts:156`) would silently swallow every compaction
   capture after the first.

So: **two seams, not one.** Path A (ContextEngine, `compact()`) needs
nothing from OpenClaw and covers the common configuration. Path B
(`before_compaction` hook) covers legacy hosts and depends on host
behaviour this repo cannot verify.

## 2. What the code actually says

### 2.1 Hook registration seam

| Fact | Location |
|---|---|
| `before_compaction`, `after_compaction` in the `HookName` union | `packages/openclaw-plugin/src/types.ts:55-56` |
| Types are locally maintained, "Based on OpenClaw v2026.5.7 plugin-sdk" | `src/types.ts:1-9` |
| Peer dependency `openclaw: ">=2026.5.7"` | `packages/openclaw-plugin/package.json` |
| `api.on(hook: HookName \| string, handler, opts?)` | `src/types.ts:662` |
| `api.registerHook?(events, handler, opts?)` (alternative) | `src/types.ts:661` |
| No handler registered for either compaction hook | grep over `packages/`, `palaia/`, `v3/` — only the two type lines above |

There is **no `BeforeCompactionEvent` type** in `types.ts`, unlike
`BeforeResetEvent` (`src/types.ts:117-122`) and `AgentEndEvent`
(`src/types.ts:124-130`). The payload shape is therefore unknown in-repo —
see §3.

### 2.2 Two dispatch paths — this is what decides the design

`index.ts` registers session hooks **unconditionally**, then branches:

```
index.ts:83   registerSessionHooks(api, config);      // always
index.ts:88   if (api.registerContextEngine) { … }    // modern path
index.ts:97     registerHooks(api, config);           // legacy fallback only
```

Consequences a reviewer must not miss:

- A `before_compaction` handler placed inside `registerHooks()`
  (`src/hooks/index.ts:188`) is **dead code on every modern host**, because
  that function is only called in the `else` branch. The handler belongs in
  `registerSessionHooks()` (`src/hooks/session.ts:297`), which runs on both
  paths.
- On the modern path palaia's `ContextEngine.compact()` is the compaction
  trigger. Its parameters already include everything needed —
  `force?: boolean`, `tokenBudget`, `currentTokenCount`,
  `compactionTarget`, `sessionFile`, `sessionKey`
  (`src/types.ts:505-515`) — but **not** `messages`.

### 2.3 Existing capture entry points

| Function | Location | Reusable? | Gates that a force flag must bypass |
|---|---|---|---|
| `captureSessionSummary(messages, sessionKey, api, config, logger)` | `src/hooks/session.ts:145-224` | **Yes, exported** | `state.summarySaved` dedupe (`:156`) |
| `runAutoCapture(messages, api, config, logger)` | `src/context-engine.ts:251-374` | module private | `config.autoCapture` (`:257`), `captureMinTurns` (`:265`), `shouldAttemptCapture` (`:292`, min 100 chars — `src/hooks/capture.ts:659-665`) |
| `agent_end` handler | `src/hooks/index.ts:581-864` | **No** — inline closure | `captureMinTurns` (`:600`), `shouldAttemptCapture` (`:636`) |

`captureSessionSummary()` already does exactly what #185 asks for: LLM
extraction via `extractWithLLM()` with a rule-based fallback
(`src/hooks/session.ts:161-190`), a tool-observation fallback when no
messages are available (`:191-199`), and a write tagged
`session-summary,auto-capture` (`:206-218`).

### 2.4 `/new` and `/restart` are already covered

#185 states the problem applies equally to `/new` and `/restart`. In this
repository it does not: `before_reset` is registered
(`src/hooks/session.ts:355`) and calls `captureSessionSummary()` with the
event's messages, gated on `messages.length >= 4` (`:361`).
`session_end` is a second safety net (`:330-350`). Compaction is the one
lifecycle event with **no** capture path — which makes #185 narrower and
cleaner than the issue text suggests.

## 3. UNVERIFIED — what this repository cannot prove

No network access was available; none of the following could be checked
against OpenClaw itself.

1. **Whether OpenClaw actually emits `before_compaction`.** The name is in
   *palaia's own* hand-maintained type file, not in an installed OpenClaw
   package (`packages/openclaw-plugin/node_modules` does not exist).
2. **The event payload.** Whether it carries `messages` (as
   `before_reset` does), only a `sessionFile`, or a `reason`/token
   figure. This determines whether Path B can capture content at all.
3. **Whether handlers are awaited.** A fire-and-forget emission makes the
   hook useless: compaction would proceed while the LLM extraction
   (seconds) is still running. `ContextEngineRuntimeContext.allowDeferredCompactionExecution`
   (`src/types.ts:412`) hints the runtime can defer compaction, but its
   semantics are unverified.
4. **Whether the event fires when a ContextEngine declares
   `ownsCompaction: true`.** If it does not — which is the likely reading
   of the flag's own changelog entry (`CHANGELOG.md:18`: it "prevent[s]
   OpenClaw's built-in Pi auto-compaction from running") — then Path B
   only ever helps legacy hosts, and Path A is load-bearing.
5. **The issue's citation of OpenClaw's `compaction.md`** ("reminds agent
   to save important notes"). That wording describes a *nudge to the
   model*, not a plugin event. If that is all OpenClaw offers, there is no
   deterministic plugin hook to register and Path B does not exist at all.
   **This is the single most important thing to verify before
   implementing Path B.**
6. **PR #177 / `ownsCompaction`.** The PR contents could not be read. What
   is verifiable in-repo is the flag itself
   (`src/context-engine.ts:397`) and its changelog entry
   (`CHANGELOG.md:18`, v2.7.3 — "Fixed"). The design below is written
   against the in-repo artifact, not against the PR.

**Adjacent risk, out of scope for #185 but found at the same seam:**
palaia's `compact()` runs `palaia gc` — memory-store garbage collection —
and returns `{ ok: true, compacted: true }` (`src/context-engine.ts:559-568`)
without reducing the *transcript*. Combined with `ownsCompaction: true`,
that means a host trusting the return value would skip its own compaction
while the context window keeps filling. Worth its own issue.

## 4. Design

### 4.1 The two seams

**Path A — `ContextEngine.compact()` (primary, needs nothing from OpenClaw).**
Capture *before* the `gc` call, wrapped so a capture failure can never
block compaction:

```
compact(params)
  └─ if config.captureOnCompaction && params.sessionKey
        └─ try { captureBeforeContextLoss(recentMessages, …, "compaction") }
           catch → logger.warn, continue
  └─ run(["gc"])                       // unchanged
```

**Message availability is the one real implementation problem on this
path.** `compact()` receives no `messages`, and the engine's
`_lastMessages` buffer (`src/context-engine.ts:387`) is filled by
`ingest()` (`:435-440`) but **reset to `[]` at the end of every
`afterTurn()`** (`:457`) — so at compaction time it is typically empty.
Three options, in order of preference:

1. **Bounded rolling buffer** (recommended, ~6 lines): keep a separate
   capped array — say the last 200 ingested messages — that `afterTurn()`
   does *not* clear. Self-contained, no new host API, no unverified
   assumptions. This is what the patch in §5 does.
2. `params.sessionFile` + `api.runtime.agent?.session?.loadSessionStore`
   (`src/types.ts:604-607`). Richer, but the loader's signature and return
   shape are **UNVERIFIED** and no parser for OpenClaw's session format
   exists in-repo.
3. Fall through to the existing tool-observation summary
   (`src/hooks/session.ts:191-199`). Always available, much weaker content.
   Keep as the last resort — it already is one.

**Path B — the `before_compaction` hook (legacy hosts / belt and braces).**
Register in `registerSessionHooks()` (`src/hooks/session.ts:297`), *not*
in `registerHooks()`. Use `event.messages` when present, else fall through
to the same tool-observation path. A host that never emits the event makes
this a no-op; a host that emits it with no payload still gets the weak
summary.

If OpenClaw is to support this properly, it must expose:

- an event fired **before** any transcript is discarded or summarised;
- a payload carrying `messages` (the `BeforeResetEvent` shape,
  `src/types.ts:117-122`, is the natural precedent);
- **awaited** handlers, or a documented deferral (`allowDeferredCompactionExecution`);
- a statement of whether it fires when a ContextEngine owns compaction.

### 4.2 The force flag — where and why

`captureSessionSummary()` gains an options argument:

```ts
captureOpts?: { force?: boolean; extraTags?: string[] }
```

- `force: true` bypasses the `state.summarySaved` guard
  (`src/hooks/session.ts:156`). Without this, the *first* compaction
  capture sets the flag and every later compaction in the same session
  silently writes nothing.
- A forced write must **not** set `summarySaved`. If it did, the normal
  `session_end` summary (`:343`) would be suppressed for the rest of the
  session — the session continues after compaction and accrues new
  content that still deserves a summary. Forced writes record
  `lastForcedCaptureAt` instead (new field on `SessionState`,
  `src/hooks/state.ts:180-203`).
- A **60 s cooldown** on `lastForcedCaptureAt` bounds the cost if a host
  fires compaction repeatedly. Repeated compaction is exactly the
  situation #185 describes, and each capture costs an LLM extraction.
- `extraTags: ["pre-compaction"]` makes these entries identifiable for
  later analysis and GC, alongside the existing
  `session-summary`/`auto-capture` tags (`:210`).

Return type changes from `Promise<void>` to `Promise<boolean>` (did it
write?) — additive for the two existing callers, which ignore the result.

The `agent_end`/`runAutoCapture` gates (`captureMinTurns`,
`shouldAttemptCapture`'s 100-char floor) are deliberately **not** reused
here. A conversation about to be compacted is by definition long; the
gates that matter are the ones above.

### 4.3 Config key

| | |
|---|---|
| Key | `captureOnCompaction` |
| Type | `boolean` |
| Default | `true` |
| Declared in | `src/config.ts` interface (`:12-79`) + `DEFAULT_CONFIG` (`:87-109`) |
| Also needs | `openclaw.plugin.json` → `configSchema.properties` (+ `uiHints`), `docs/configuration.md:88` table (the plugin-config table, `autoCapture` is at `:98`), `CHANGELOG.md`, `packages/openclaw-plugin/README.md` |

Default `true` is right: the feature is a safety net against silent data
loss, and it writes through the same auto-capture machinery users have
already opted into via `autoCapture`. Users who want no capture at all
already set `autoCapture: false`.

**Open question for the owner:** should `captureOnCompaction` be gated on
`autoCapture` being true? Recommendation: **no** — `sessionSummary`
(`src/config.ts:68`) is independent of `autoCapture` today, and compaction
capture is a session-summary-class feature, not an exchange-capture one.
Keep it a sibling of `sessionSummary`.

### 4.4 Migration and compatibility

- **Config:** `resolveConfig()` merges by spread (`src/config.ts:114-126`),
  so an absent key takes the default and unknown keys are ignored. No
  migration, no breaking change for existing `openclaw.json` files.
- **Old hosts:** registering an unknown hook name is inert — `api.on()`
  accepts a bare `string` (`src/types.ts:662`). No version probe needed,
  no `try/catch` around registration.
- **New hosts:** if a host emits `before_compaction` *and* routes
  compaction through palaia's `compact()`, both paths could fire for one
  compaction. The 60 s cooldown (§4.2) makes that idempotent in practice.
- **Store shape:** entries are written through the existing `palaia write`
  CLI path with an extra tag. No schema change, no index migration.

### 4.5 Track constraint (read before opening a PR)

Everything in §4 lands in `packages/openclaw-plugin/` — **v2 code**.
`AGENTS.md` states that v2 is maintenance-only, that feature development
is frozen, that hotfixes target the `v2-maintenance` branch and never
`main`, and that a PR touches files of exactly one track. v3 has no
OpenClaw client at all (`v3/MASTERPLAN.md:499`: "v2 plugin keeps working
against v2; v3 adapter later — not a v3 launch target";
`v3/specs/SPEC-505-v2-sunset.md:57`).

So #185 is, procedurally, one of:

- **a v2 hotfix** — arguable: "silent loss of conversation content" is a
  data-loss class of bug, and the fix is small. It must then go on a
  branch off `v2-maintenance`, carry the config key + docs, and ship as a
  `v2.x.y` release; or
- **deferred to the v3 OpenClaw adapter**, where the same two seams must
  be implemented from the start, with capture routed through the hub's
  `capture` MCP tool (`v3/server/src/palaia_hub/gateway/memory_tools.py:472`)
  instead of the `palaia write` CLI.

This is the owner's call, not the agent's. It is also why the prototype
below was **not** committed (§5).

## 5. Prototype — scoped, not built

**Not built, for two independent reasons:**

1. **Track rules.** The code belongs in `packages/openclaw-plugin/` (v2),
   this branch is based on `main`, and `AGENTS.md` forbids both a v2
   feature change on `main` and a PR spanning two tracks (§4.5).
2. **No verification possible here.** `packages/openclaw-plugin/node_modules`
   does not exist and the environment has no network:
   `npm install --offline` fails with `ENOTCACHED` on a missing tarball,
   and installing `vitest` alone fails the same way. Neither `vitest` nor
   `tsc` can run, so neither the new test nor the existing suite
   (2,656 lines across 7 files) could be executed. (The v3 Python suite
   *is* runnable here — `uv sync --offline` resolves from cache — which is
   why the doc-only change in this branch could be checked and the patch
   below could not.) Committing unverified code into a frozen track is the
   wrong trade.

The patch below is complete and review-ready. It is **static analysis
output, not executed code** — no claim is made that it passes tests,
because no test could be run.

### 5.1 `src/config.ts`

```diff
   /** Enable tool observation tracking via after_tool_call hook (default: true) */
   captureToolObservations: boolean;
+  /** Force a session-summary capture when the host is about to compact (default: true) */
+  captureOnCompaction: boolean;
```

```diff
   captureToolObservations: true,
+  captureOnCompaction: true,
   recallRecencyBoost: 0.3,
```

### 5.2 `src/hooks/state.ts` — one field on `SessionState`

```diff
   /** Whether a session summary has already been saved. */
   summarySaved: boolean;
+  /** Timestamp of the last forced (pre-compaction) capture, 0 if none. */
+  lastForcedCaptureAt: number;
```

…and `lastForcedCaptureAt: 0` in the initializer at
`src/hooks/state.ts:234-248`.

### 5.3 `src/hooks/session.ts` — force flag + the new entry point

```diff
 export async function captureSessionSummary(
   messages: unknown[] | undefined,
   sessionKey: string,
   api: OpenClawPluginApi,
   config: PalaiaPluginConfig,
   logger: { info(...a: unknown[]): void; warn(...a: unknown[]): void },
-): Promise<void> {
+  captureOpts?: { force?: boolean; extraTags?: string[] },
+): Promise<boolean> {
   const opts = buildRunnerOpts(config);
   const state = getOrCreateSessionState(sessionKey);
+  const force = captureOpts?.force === true;
 
-  // Guard: prevent double-save (before_reset + session_end race)
-  if (state.summarySaved) return;
+  // Guard: prevent double-save (before_reset + session_end race).
+  // A forced capture (pre-compaction) deliberately bypasses it.
+  if (state.summarySaved && !force) return false;
   let summaryText: string | null = null;
```

```diff
-  if (!summaryText) return;
+  if (!summaryText) return false;
 
   // Save session summary
   try {
     const scope = await getEffectiveCaptureScope(config);
+    const tags = [...new Set(["session-summary", ...(captureOpts?.extraTags ?? []), "auto-capture"])];
     const args: string[] = [
       "write", summaryText,
       "--type", "memory",
-      "--tags", "session-summary,auto-capture",
+      "--tags", tags.join(","),
       "--scope", scope,
     ];
```

```diff
     await run(args, { ...opts, timeoutMs: 10_000 });
-    state.summarySaved = true;  // Only mark after successful write
+    // A forced capture must NOT set summarySaved: the session continues
+    // after compaction and still deserves its own session_end summary.
+    if (force) {
+      state.lastForcedCaptureAt = Date.now();
+    } else {
+      state.summarySaved = true;  // Only mark after successful write
+    }
     logger.info(`[palaia] Session summary saved (${summaryText.length} chars)`);
+    return true;
   } catch (error) {
     // Don't set summarySaved — allow retry from session_end if before_reset failed
     logger.warn(`[palaia] Failed to save session summary: ${error}`);
+    return false;
   }
 }
+
+/** Minimum gap between two forced captures in one session. */
+export const FORCED_CAPTURE_COOLDOWN_MS = 60_000;
+
+/**
+ * Force-capture the current conversation because the host is about to
+ * throw part of it away (compaction). Never throws: context loss is bad,
+ * but blocking compaction is worse.
+ */
+export async function captureBeforeContextLoss(
+  messages: unknown[] | undefined,
+  sessionKey: string,
+  api: OpenClawPluginApi,
+  config: PalaiaPluginConfig,
+  logger: { info(...a: unknown[]): void; warn(...a: unknown[]): void },
+  reason: string,
+): Promise<boolean> {
+  const state = getOrCreateSessionState(sessionKey);
+
+  const since = Date.now() - state.lastForcedCaptureAt;
+  if (state.lastForcedCaptureAt > 0 && since < FORCED_CAPTURE_COOLDOWN_MS) {
+    logger.info(`[palaia] ${reason} capture skipped: forced capture ${since}ms ago`);
+    return false;
+  }
+
+  const hasMessages = Array.isArray(messages) && messages.length > 0;
+  if (!hasMessages && state.toolObservations.length === 0) {
+    logger.info(`[palaia] ${reason} capture skipped: no messages, no tool observations`);
+    return false;
+  }
+
+  return captureSessionSummary(
+    hasMessages ? messages : undefined,
+    sessionKey, api, config, logger,
+    { force: true, extraTags: ["pre-compaction"] },
+  );
+}
```

Registration — inside `registerSessionHooks()`, next to the `before_reset`
handler:

```diff
+  // ── before_compaction: capture before the host summarises the context ──
+  // The hook name is part of the plugin contract (types.ts:55). A host that
+  // never emits it makes this registration inert — no version probe needed.
+  // NOTE: this must live here, not in registerHooks(), because
+  // registerHooks() is only called on the legacy (no-ContextEngine) path.
+  if (config.captureOnCompaction) {
+    api.on("before_compaction", async (event: any, ctx: any) => {
+      const sessionKey = ctx?.sessionKey || ctx?.sessionId;
+      if (!sessionKey) return;
+      try {
+        await captureBeforeContextLoss(
+          (event as any)?.messages, sessionKey, api, config, logger, "before_compaction",
+        );
+      } catch (error) {
+        logger.warn(`[palaia] before_compaction capture failed: ${error}`);
+      }
+    });
+  }
```

### 5.4 `src/context-engine.ts` — Path A

A rolling buffer that `afterTurn()` does not clear (§4.1):

```diff
   /** Last messages seen via ingest(), used by assemble() for query building. */
   let _lastMessages: AgentMessage[] = [];
+  /** Rolling window of recent messages, kept across turns for pre-compaction capture. */
+  let _recentMessages: AgentMessage[] = [];
+  const RECENT_MESSAGE_CAP = 200;
```

```diff
     async ingest(params) {
       if (params.message) {
         _lastMessages.push(params.message);
+        _recentMessages.push(params.message);
+        if (_recentMessages.length > RECENT_MESSAGE_CAP) {
+          _recentMessages.splice(0, _recentMessages.length - RECENT_MESSAGE_CAP);
+        }
       }
       return { ingested: true };
     },
```

```diff
     async compact(_params) {
+      // palaia declares ownsCompaction (info.ownsCompaction, above), so on
+      // this path OpenClaw routes compaction here instead of compacting
+      // itself — this call IS the pre-compaction moment (#185).
+      if (config.captureOnCompaction && _params?.sessionKey) {
+        try {
+          await captureBeforeContextLoss(
+            _recentMessages.length ? _recentMessages : undefined,
+            _params.sessionKey, api, config, logger, "compaction",
+          );
+        } catch (error) {
+          // Never let capture block compaction.
+          logger.warn(`[palaia] Pre-compaction capture failed: ${error}`);
+        }
+      }
       try {
         await run(["gc"], { ...opts, timeoutMs: 30_000 });
```

plus `captureBeforeContextLoss` added to the existing
`./hooks/session.js` import (`src/context-engine.ts:20`).

## 6. Test strategy

Unit tests (`packages/openclaw-plugin/tests/pre-compaction.test.ts`),
following the existing pattern of mocking `../src/runner.js` before
importing the module under test (`tests/session.test.ts:7-14`) and of
capturing handlers through a mock `api.on` (`tests/hooks.test.ts:1044-1059`):

**Registration**
1. `captureOnCompaction: true` → `registerSessionHooks()` registers a
   `before_compaction` handler.
2. `captureOnCompaction: false` → it does not.
3. The handler is registered on the **ContextEngine path too** — assert
   via `index.ts` with a mock api exposing `registerContextEngine`, since
   this is the exact trap described in §2.2.

**Force semantics**
4. `summarySaved: true` + `force: true` → `run()` is called (guard bypassed).
5. `summarySaved: true`, no force → `run()` is not called.
6. After a forced write, `state.summarySaved` is still `false` — then a
   normal `session_end` capture still writes.
7. Tags are exactly `session-summary,pre-compaction,auto-capture`.
8. Cooldown: two `captureBeforeContextLoss()` calls in a row → second
   returns `false`, `run()` called once. With `lastForcedCaptureAt`
   back-dated past `FORCED_CAPTURE_COOLDOWN_MS` → writes again.

**Guards**
9. Handler with no `sessionKey` in ctx → no `run()`, no throw.
10. No messages and no tool observations → no write.
11. No messages but tool observations present → writes the observation
    summary (`src/hooks/session.ts:191-199`).

**ContextEngine path**
12. `compact()` calls capture before `run(["gc"])` (assert call order).
13. `compact()` still runs `gc` and returns `{ ok: true }` when capture
    rejects.
14. `_recentMessages` survives `afterTurn()` (regression guard for the
    `_lastMessages` reset at `src/context-engine.ts:457`).

**Not coverable in-repo:** that OpenClaw *emits* `before_compaction` at
the right moment with a useful payload, and that it awaits the handler.
There is no OpenClaw host harness in this repository and `openclaw` is a
peer dependency, so this needs a manual check against a real host —
drive a session past the compaction threshold, confirm a
`pre-compaction`-tagged entry lands, then `/new` and confirm the briefing
(`src/hooks/session.ts:66`) surfaces it.

**Environment note:** the TypeScript suite could not be run while writing
this doc — `node_modules` is absent and offline `npm install` fails with
`ENOTCACHED`. Any implementer must run
`cd packages/openclaw-plugin && npx vitest run` on a networked machine
before review, and re-run the whole existing suite: the change touches
`captureSessionSummary`'s signature and the engine's `ingest`/`compact`,
both of which `tests/context-engine.test.ts` and `tests/hooks.test.ts`
already exercise.

## 7. Note for the v3 adapter

When the v3 OpenClaw adapter is built (`v3/MASTERPLAN.md:499`), both seams
must be there from day one — Path A is not optional, because an adapter
that owns compaction and does not capture first has the same silent hole.
Two v3-specific differences:

- Capture goes through the hub's `capture` MCP tool
  (`v3/server/src/palaia_hub/gateway/memory_tools.py:472`), not the
  `palaia write` CLI. The capture contract is documented in
  `v3/clients/skills/palaia-capture/SKILL.md`.
- The hub already has an event bus and outbound webhooks
  (`v3/docs/events.md`, SPEC-201), so a `pre-compaction` capture would
  additionally become an observable `memory.entry.created` event — useful
  for verifying the feature in the dashboard rather than by grepping logs.

## 8. Sources

| Claim | Location |
|---|---|
| `before_compaction` / `after_compaction` hook names | `packages/openclaw-plugin/src/types.ts:55-56` |
| `api.on()` accepts any string hook name | `packages/openclaw-plugin/src/types.ts:662` |
| `compact()` params incl. `force` | `packages/openclaw-plugin/src/types.ts:505-515` |
| `ownsCompaction` on `ContextEngineInfo` | `packages/openclaw-plugin/src/types.ts:292` |
| `allowDeferredCompactionExecution` | `packages/openclaw-plugin/src/types.ts:412` |
| `loadSessionStore` runtime surface | `packages/openclaw-plugin/src/types.ts:604-607` |
| Session hooks always registered; ContextEngine/legacy branch | `packages/openclaw-plugin/index.ts:83,88-98` |
| palaia declares `ownsCompaction: true` | `packages/openclaw-plugin/src/context-engine.ts:397` |
| `compact()` runs only `palaia gc` | `packages/openclaw-plugin/src/context-engine.ts:559-568` |
| `_lastMessages` filled by `ingest`, cleared by `afterTurn` | `packages/openclaw-plugin/src/context-engine.ts:387,435-440,457` |
| `runAutoCapture` (module private) | `packages/openclaw-plugin/src/context-engine.ts:251-374` |
| `captureSessionSummary` + dedupe guard | `packages/openclaw-plugin/src/hooks/session.ts:145-224,156` |
| `before_reset` / `session_end` already capture | `packages/openclaw-plugin/src/hooks/session.ts:330-368` |
| `registerSessionHooks` | `packages/openclaw-plugin/src/hooks/session.ts:297` |
| `agent_end` inline closure | `packages/openclaw-plugin/src/hooks/index.ts:581-864` |
| `shouldAttemptCapture` 100-char floor | `packages/openclaw-plugin/src/hooks/capture.ts:659-665` |
| `SessionState` shape | `packages/openclaw-plugin/src/hooks/state.ts:180-203,234-248` |
| Config interface / defaults / merge | `packages/openclaw-plugin/src/config.ts:12-79,87-109,114-126` |
| Plugin config schema (needs the new key) | `packages/openclaw-plugin/openclaw.plugin.json` |
| Plugin config docs table | `docs/configuration.md:88-105` |
| `ownsCompaction` changelog entry (v2.7.3) | `CHANGELOG.md:18` |
| v2 maintenance-only / one-track-per-PR rules | `AGENTS.md` |
| OpenClaw is not a v3 launch target | `v3/MASTERPLAN.md:499`, `v3/specs/SPEC-505-v2-sunset.md:57` |
| v3 `capture` MCP tool | `v3/server/src/palaia_hub/gateway/memory_tools.py:472` |
