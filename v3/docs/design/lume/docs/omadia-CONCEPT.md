# Omadia UI — Concept

> A persistent canvas surface for the Omadia Agentic OS. The agent synthesises UI live the way it synthesises prose today — on a blank canvas, in the layout and composition that fit the user's task and preferences in the moment.

Version 0.9 — typography architecture locked at the concept level: three registers (structural / prose / mono), bound to three families in `docs/visual-spec.md` v0.3 (Geist · Source Serif 4 · Geist Mono). UI Skill gains a `prose-vs-structure protocol` alongside the palette-binding protocol; `style` trait extends to carry `"prose"` and `"mono"` register markers. v0.8: material identity (Lume) named and locked; accent slot becomes user-bindable across three curated palettes (Petrol / Atelier / Lagoon, Lagoon default), bound via the existing context-aware prefs model. UI Skill gained a `palette-binding protocol`. Visual specification carved out to [`docs/visual-spec.md`](docs/visual-spec.md) v0.2. v0.7 baseline: DataRef lifecycle (content-addressed, buffer ownership, GC), per-mutation mutex semantics, sub-agent cancellation, Tier-2 data cache between turns, external-effect action classification with confirmation pattern, `canvas-activate` action type, Tier-2 statelessness wrt active canvas, referential-continuity contract. v0.6: direct-gesture vs. routed-local-op split, canonical `DataRef` shape, concrete boot handshake, editor-primitive required fields, preview-vs-durable ops, contextKey per canvas, sentinel mechanism, server-assigned `surfaceSeq`. v0.5: forward-compat hooks for shared canvases. v0.4: 2D architecture, editor primitives, local ops catalog, multiple canvases, context-aware prefs, protocol versioning.

---

## Vision

Chat is the "DOS era" of LLM interaction: powerful, but linear, text-only, single-stream. Omadia UI is the next layer: a desktop surface where the agent **materialises live UI** (text, lists, tables, panes, media, editor regions — composed from a fixed vocabulary of primitives) as it orchestrates a request across source systems.

The canvas is **persistent, multi-turn, stateful**, its own surface with a clean mode-switch next to the chat channels. The user's tools (Jira, ERP, HR, …) stay where they are — Omadia UI replaces only the manual aggregation, comparison, triage and editing work on top of them.

The UI is **not authored by a designer and not picked from a theme menu**. It is generated per turn from a fixed vocabulary of primitives, in a layout the agent infers from the user's preferences, the use case and conversational requests. Top-tier LLMs already know what a Norton Commander layout, a Photoshop workspace or a Dashboard look like — they can express any of these (and mix them) by composing the same primitive vocabulary, rendered in the single shipped Omadia theme.

The bottleneck for what the canvas can show should be the model, not the architecture. The concept must be ready for the next 1–2 LLM generations (Claude Mythos, GPT-6, real-time models) without architectural rework.

---

## Architecture — Two Dimensions

UI work is split across two orthogonal dimensions:

- **Tier** = latency/LLM-load class (1 = none/instant, 2 = small/fast, 3 = full/long-running).
- **Side** = where it runs (Client = user's machine; Server = omadia core deployment).

| | **Client** (user's machine) | **Server** (omadia core) |
|---|---|---|
| **Tier 1 — Surface** *(deterministic, no LLM, instant)* | **Canvas Host App** (Omadia UI)<br>• renders primitive tree<br>• holds local state (selections, scroll, drag, brush buffer, …)<br>• **local operations catalog** (brush, blur, curves, audio-trim, video-cut, …)<br>• schema-validate + style-normalise | **`omadia-ui-channel`** *(kind: channel)*<br>• WebSocket endpoint + auth<br>• `IncomingTurn` forming<br>• stream forwarding<br>• no LLM logic |
| **Tier 2 — UI Orchestrator** *(small/fast LLM, sub-second)* | — | **`omadia-ui-orchestrator`** *(kind: extension)*<br>• UI Skill (composition-idiom library)<br>• Haiku-class LLM (configurable)<br>• primitive selection + composition<br>• action routing (local Tier-1 vs Tier-3)<br>• canvas-state + user-prefs store<br>• per-session turn serialisation |
| **Tier 3 — Content / Tools** *(heavy LLM + slow tools OK)* | — | **Existing omadia plugins** *(kind: agent / tool / integration)*<br>• Sonnet, Opus, GPT, Gemini, …<br>• Jira, ERP, HR, AI-background-removal, …<br>• long-running operations |

```mermaid
flowchart TB
  subgraph T1["Tier 1 — Surface · deterministic · no LLM · instant"]
    direction LR
    HOST["<b>Client</b><br/>Canvas Host App (Omadia UI)<br/><i>renders primitive tree</i><br/><i>local state · local ops catalog</i><br/><i>schema-validate · style-normalize</i>"]
    CHAN["<b>Server</b><br/>omadia-ui-channel<br/><i>kind: channel</i><br/>WebSocket · auth<br/>IncomingTurn forming<br/>stream forwarding"]
    HOST <-->|"WebSocket<br/>turns + surface_* events"| CHAN
  end

  subgraph T2["Tier 2 — UI Orchestrator · fast LLM · sub-second"]
    ORCH["<b>Server only</b><br/>omadia-ui-orchestrator<br/><i>kind: extension</i><br/>UI Skill · Haiku-class LLM<br/>primitive selection + composition<br/>canvas-state + user-prefs<br/>action routing"]
  end

  subgraph T3["Tier 3 — Content / Tools · heavy LLM · slow OK"]
    CONT["<b>Server only</b><br/>existing omadia plugins<br/><i>kind: agent · tool · integration</i><br/>Sonnet · Opus · GPT · Gemini<br/>Jira · ERP · AI-services · …"]
  end

  CHAN -->|"canvasChatAgent@1"| ORCH
  ORCH -->|"chatAgent@1<br/>structured payloads via sentinels"| CONT
  ORCH -.->|"surface_local_action<br/>(blur, brush, curves, …)<br/>via surface stream"| HOST
```

**Latency paths** — four distinct classes; the split between Class A and Class B is load-bearing:

| Class | Trigger | Path | Latency |
|---|---|---|---|
| **A — Direct Tier-1 gesture** | scroll, hover, drag, brush stroke, pinch-zoom, pane move/resize, click on a tool-mode toggle, accordion open/close, local form typing pre-submit | Tier 1 Client only — no server contact, no tokens | <16ms (60fps target) |
| **B — Tier-2-routed local op** | semantic command from the agent or user that resolves to a catalog operation: "apply blur to selection", "normalize this audio", "crop to selection" | Tier 1 → Channel → Tier 2 → `surface_local_action` back to Tier 1 → Tier 1 executes from local catalog | sub-second |
| **C — UI composition** | "change to dashboard layout", "show me this as a kanban", style/layout preference change | Tier 1 → Channel → Tier 2 → tree mutation back | sub-second |
| **D — Content request** | "which of them are on vacation?", "regenerate this background with AI", "fetch the Q1 invoices from ERP" | Tier 1 → Channel → Tier 2 → Tier 3 → Tier 2 → Tier 1 | seconds+; Tier 1 shows skeletons, rest of canvas stays responsive |

**Class A vs Class B is the most-violated boundary in early implementations.** A direct gesture (the user dragging the brush across pixels) is Class A — it must never round-trip the server. Triggering a named operation from a semantic intent (the agent applying that brush stroke after a user prompt, or the user clicking a "Blur Selection" button) is Class B — Tier 2 decides which operation, Tier 1 executes from its local catalog. The first Tier-1 implementation must encode this split.

---

## Tier 1 — Surface (Client + Server)

### Client: Canvas Host App (Omadia UI)

The desktop application. **Electron** for v1 — full reasoning, candidate comparison, risks, reversibility and the spike plan are in [`docs/tech-stack.md`](docs/tech-stack.md).

**Responsibilities:**

- Render the current primitive tree against the single Omadia theme.
- Apply tree mutations from Tier 2 (snapshot replace, patch, local action, action result, errors) via the streaming event grammar. Honours `surfaceSeq` and `treeRevision` — discards out-of-order or stale events.
- Hold all local UI state: scroll, hover, focus, accordion state, unsubmitted form inputs, selections, drag positions, undo stacks.
- **Local operations catalog**: deterministic, instant operations the host implements natively. Declared at capability handshake. Editor-class operations live here for performance — see "Local Operations Catalog" below.
- Send to Tier 2: user actions with semantic consequence (button clicks, form submits, conversational input, layout-change requests). Each is a new turn.
- Optimistic UI for tier-2-bound actions; skeleton states for tier-3-bound waits.
- **Schema-validate every incoming tree** against the primitive whitelist and trait spec. Reject anything else hard.
- **Apply deterministic style normaliser** after Tier-2 output (light job now since style is theme-fixed: trims any out-of-theme style hints, applies default tokens).

**Multiple canvases (Spaces-style):** Host App holds N canvases per running instance (default 1, user can add). Switching between canvases is client-local (hotkey, indicator). Each canvas has its own `canvasSessionId`. Single Host App instance per user system; runs fullscreen (Win-3-in-DOS analogy, fully overlays host OS) or windowed.

### Server: `omadia-ui-channel` (kind: channel)

Thin server-side counterpart to the Host App. Server-hosted plugin under `middleware/packages/omadia-ui-channel/`, manifested as `kind: channel` with `capabilities: [text, canvas]`, `dispatchService: "canvasChatAgent@1"`.

**Responsibilities:**

- Host the WebSocket endpoint the Host App connects to.
- Authenticate the user (reuses omadia core auth — local + OIDC).
- Form `IncomingTurn` from client events (`channelId`, `tenantId`, `userId`, `conversationId`, `canvasSessionId`, payload).
- Forward the stream of surface events from Tier 2 back to the client. No transformation, no LLM, no domain logic.
- Honour the `dispatchService` field — wire its `TurnDispatcher` to `canvasChatAgent@1`.

The channel is intentionally thin — if a second Canvas surface ever ships (web-PWA, mobile, …), it ships as a separate channel plugin against the same Tier-2 API.

---

## Tier 2 — UI Orchestrator (extension plugin)

Server-side. New plugin under `middleware/packages/omadia-ui-orchestrator/`, kind `extension`, publishes `canvasChatAgent@1`.

**Plugin manifest sketch:**

```yaml
identity:
  kind: extension
  id: omadia-ui-orchestrator
provides: ["canvasChatAgent@1"]
requires: ["chatAgent@1", "memoryStore@1", "crossChannelConversationMemory@1"]
permissions:
  llm_models_allowed: ["claude-haiku-4-5*", "claude-sonnet-4-*"]
  llm_calls_per_invocation: 8
  memory_reads: ["ui-prefs/**", "canvas-state/**"]
  memory_writes: ["ui-prefs/**", "canvas-state/**"]
config:
  ui_orchestrator_model: "claude-haiku-4-5-…"
  canvas_protocol_version: "1.0"
```

**Per-mutation mutex** (refined from earlier "per-turn" wording): the mutex is **per `canvasSessionId`**, but it protects each individual state mutation, **not the whole turn**. Tier 2 holds the mutex only while reading + writing the canvas-state. While Tier 3 sub-agents run, the mutex is released so that other mutations (a user typing a follow-up, another sub-agent returning) can proceed without blocking on a long-running Tier-3 call. Concurrent sub-agent returns and incoming user turns serialise via repeated short mutex acquisitions, each producing exactly one revisioned patch.

**Tier-2 is stateless wrt active canvas.** Each `IncomingTurn` carries its own `canvasSessionId`; Tier 2 never holds a "current canvas" variable. Background Tier-3 work for canvas A can emit updates even while the client displays canvas B — those updates simply land in canvas A's state and are visible when the user switches back. (Important for v2+ multi-user as well.)

**What it does per turn:**

1. Receives incoming turn from the canvas channel.
2. Acquires the session mutex briefly to load canvas state from `memoryStore@1` at `canvas-state/<tenantId>/<canvasSessionId>` (tree, selections, dataRef refs, `treeRevision`, `contextKey`) and user preferences from `ui-prefs/<tenantId>/<userId>/<contextKey>`. Releases the mutex.
3. **Referential continuity contract**: every composition or patch synthesis decision uses the loaded state as truth. References like "of them", "this row", "the highlighted ones" resolve against the in-memory tree; Tier 2 never re-asks Tier 3 for data it already has in state or in the dataRef cache (see below).
4. Decides: **local action** (Tier-1 catalog), **UI composition** (style/layout), or **content-bound** (needs new data from Tier 3).
5. Local action → emit `surface_local_action` event to Tier 1.
6. UI composition → small LLM call with UI Skill + current tree + prefs → emit `surface_snapshot` (rare; only for fundamental restructure) or `surface_patch` (default, preserves user state).
7. Content-bound → delegate to `chatAgent@1`. Sub-agents return structured data via sentinel envelope. Each return acquires the mutex briefly, mutates state, emits one revisioned patch, releases.
8. **Update written incrementally**: each patch increments `treeRevision` by 1 under the mutex; canvas-state and user prefs are written through to `memoryStore@1` at the same time.

### Per-canvas data cache (Tier-2 internal)

Between turns, Tier 2 keeps a **per-`canvasSessionId` data cache** of structured payloads returned by Tier-3 sub-agents. Cache key: the `DataRef.id`. Backing: `memoryStore@1` under `canvas-state/<tenantId>/<canvasSessionId>/cache/<dataRefId>` with the same `expiresAt` as the corresponding signed token.

Before any Tier-3 call, Tier 2 checks the cache. If the data is present and unexpired, the call is skipped and the existing dataRef is reused. This is what allows queries like "how big are they in revenue?" (Walkthrough 4 step 18) to be answered from the earlier web-search payload without a second sub-agent call.

### Sub-agent cancellation (best-effort)

When the user changes direction mid-flight (Walkthrough 4 step 9: "actually focus on their AI strategy first"), Tier 2 marks already-dispatched Tier-3 calls as obsolete. v1 uses **soft cancellation**: the Tier-3 call runs to completion (Omadia's tool API has no hard-cancel), but its return is dropped without state mutation and without patch emission. Tier 2 logs the cancellation for observability. Hard cancellation is a v2+ topic that depends on omadia-core support.

### The UI Skill

Large system-prompt block, prompt-cached. Contains:

- **Primitive catalogue with schemas, traits and examples.**
- **Composition-idiom library**: when the user references a classic UI layout (Norton Commander, Spotlight, Wizard, Dashboard, Photoshop workspace, OS/2 Workplace Shell, …), translate it into the equivalent primitive composition in the Omadia theme. **Do not attempt visual mimicry** — the Omadia theme always renders the visuals; idioms are layout/composition hints only. Examples:
  - "Norton Commander" → two `pane` side-by-side, each with a `list`, shared `toolbar` below.
  - "Wizard" → `container` with step-`tabs` + `form` per step + `toolbar` (back/next).
  - "Spotlight" → centred `input` + `list` of hits beneath.
  - "Dashboard" → `grid` of `container` with `chart`, `status`, KPI-`text`.
  - "Photoshop workspace" → `canvas-region` centre, `toolbar` left, `inspector` (`form` with context-binding) right, `tree` (layer stack) bottom-right.
- **Composition heuristics**: when in doubt, prefer fewer panes and more containers; prefer table over many cards when data has uniform shape; align controls in toolbars.
- **Style-negotiation protocol**: when the user expresses a layout preference, paraphrase the interpretation in one sentence, render the proposal, offer micro-corrections.
- **Palette-binding protocol**: when the user expresses an accent-palette preference ("mach es wärmer", "switch to Lagoon", "petrol bitte", "I want something cooler"), bind one of the three curated Lume palettes (Petrol / Atelier / Lagoon — see [`docs/visual-spec.md`](docs/visual-spec.md) §2.5) to the `accent` token. Mechanic: write the chosen palette name to `ui-prefs/<tenantId>/<userId>/<contextKey>/accent`, emit a `surface_patch` that re-tints accent tokens, brief paraphrase of the change in prose ("Lagoon — lit water"). Never offer a Settings UI; the binding happens conversationally. The Skill never picks a palette unprompted.
- **Prose-vs-structure protocol**: every `text` primitive carries a typographic register. Default is **structural** — labels, captions, instructions, eyebrows, inline UI text, all headings. The Skill opts a primitive into the **prose** register by emitting `style: "prose"` when the content is multi-sentence narration, analysis, summary, explanation, or long-form response (Walkthrough-1 step-14 narration "Three people are under budget — Anna, Bernd, Cara"; Walkthrough-4 live-research analysis pane; confirmation-modal explanatory body). The **mono** register (`style: "mono"`) carries code, terminal output, file paths, version strings, and dense IDs. Register markers map to typographic families per [`docs/visual-spec.md`](docs/visual-spec.md) §2.7; the Skill never names a font. **When in doubt, default to structural** — prose is the opt-in, not the assumption. A single sentence of narration may stay structural; two or more sentences should usually be prose.
- **Consistency rule**: preserve structure across turns unless the user signals a change.
- **Interaction model**: every user action arrives as a new turn — you receive the last tree and the action.
- **Action-routing rule**: before calling Tier 3, check whether the action is in the Tier-1 local operations catalog. If yes, emit `surface_local_action` and skip Tier 3.
- **Safety clause**: only the listed primitives are valid; if a use case seems to need a new one, express it as a composition or say it cannot be done.

---

## Tier 3 — Content Agents (with one new convention)

Existing omadia agents/tools/integrations, unchanged in interface. New optional convention for canvas-aware tools/sub-agents: return result as a **pure-JSON sentinel envelope** (the orchestrator's parser is `JSON.parse`-based):

```json
{
  "_pendingStructuredPayload": {
    "prose": "Three people are under budget — Anna, Bernd, Cara.",
    "data": { "rows": [{"owner":"Anna","budgetRemaining":5}, …] },
    "dataRefId": "qry-abc",
    "actions": []
  }
}
```

Mirrors the existing **JSON-parsed sentinel** pattern (`_pendingUserChoice`, `_pendingRoutineList` — parsed by the orchestrator via `JSON.parse` of the tool result content; see `orchestrator.ts:514+`). `_pendingSlotCard` follows a separate path (direct drain from a built-in tool state), but for tools and sub-agents emitting canvas-aware payloads the **JSON-sentinel-parse mechanism is canonical** — that is what `_pendingCanvasTree` and `_pendingStructuredPayload` use. Classic channels render `prose` and ignore the rest.

**Tools with editor-class operations** (e.g. `apply_ai_background_removal`, `transcribe_audio`, `extract_subjects_from_image`) live here — anything that takes time, calls an external service, or invokes an AI model. Standard editor operations (blur, brush, curves, …) live in the Tier-1 local catalog, not here.

**Plugin-API change** (PR for `byte5ai/omadia` main): documented optional `structured?` output-envelope convention for tools/sub-agents.

---

## Service Naming Convention (versioned ↔ unversioned)

Capability names in manifests are **versioned** (`canvasChatAgent@1`). Runtime service-registry lookups use the **unversioned base name** (`canvasChatAgent`) — existing pattern in `pluginContext.ts:213-216` and `plugin.ts:114`.

**Convention:**

- Manifests declare `provides: ["canvasChatAgent@1"]` and `requires: ["chatAgent@1", "memoryStore@1"]`. Versions participate in capability-resolution at boot.
- Boot wiring strips the `@N` suffix when populating the runtime service map.
- All `ctx.services.get(...)` calls use the unversioned key.
- Version conflicts at boot fail fast, never silent picks.
- Same convention applies to `channel.dispatchService`.

---

## Channel ↔ Tier-2 Routing

`CoreApi.handleTurnStream` has no service-selector parameter; `TurnDispatcher` is wired at boot to one orchestrator service.

**Additive SDK extension**: `channel.dispatchService?: string` in the channel manifest. Boot wires the channel-specific dispatcher to the resolved service. Defaults to `chatAgent@1` for classic channels.

---

## Streaming Surface Event Grammar

`SemanticAnswer` carries the final shape. The streaming grammar carries incremental updates during a turn. Existing `ChatStreamEvent` union (`chatAgent.ts:374-500`) gets additive new members — classic channels ignore unknown types.

**Every surface event carries:**

```ts
{
  canvasSessionId: string;
  surfaceSeq: number;        // server-assigned, monotonic per canvasSessionId
  treeRevision: RevisionId;  // opaque revision identifier of the tree
  // event-specific payload below
}
```

`treeRevision` is deliberately specified as an **opaque identifier**. v1 implementation is a monotonic integer (single-writer model); v2+ (shared canvases) may use Lamport timestamps, vector clocks, or CRDT op-ids — wire format unchanged. Patches reference revisions by equality only, never by arithmetic.

`surfaceSeq` is **server-assigned** by the channel plugin / Tier 2. Clients may attach a separate `clientSeq` to outbound user actions for round-trip mapping, but it is never authoritative.

The **channel plugin acts as the fan-out point** for surface events: in v1 it forwards 1:1 to a single connected client; in v2+ it multi-casts to all currently-connected members of a shared canvas. The event grammar itself is unchanged between v1 and v2 — fan-out is a channel-implementation detail, not a protocol concern.

### Canonical `DataRef` shape (used in every trait and event that references bulk data)

```ts
type DataRef = {
  id: string;             // content-addressed identifier (see below)
  signedToken: string;    // HMAC signature (see Security Surface for input composition)
  expiresAt: string;      // ISO 8601 timestamp
};
```

This is the single shape. The cross-cutting `dataRef` trait carries a `DataRef`. The `surface_data_ref_created` event carries a `DataRef`. The `surface_data_ref_invalidated` event carries `{id: string, reason: string}`. No stringly-typed signed-string variant.

### DataRef lifecycle

| Aspect | v1.0 spec |
|---|---|
| **ID derivation** | Content-addressed: `id = "<kind>-<sha256(content)[:16]>"`, where `kind` is `"pixel"`, `"vector"`, `"audio"`, `"video"`, `"struct"`, etc. Same content → same id, dedup automatic |
| **Buffer ownership — pixel/audio/video/vector** | Held by **Tier 1 client** in its render-detail layer (large binary buffers never leave the client unless explicitly uploaded for a Tier-3 op). Tier 2 holds only `{id, signedToken, expiresAt}` plus content metadata in canvas-state |
| **Buffer ownership — structured payload from Tier 3** (Jira tickets, ERP rows, …) | Held by Tier 2 in the per-canvas data cache (see Tier 2). Server-fetchable via signed token for re-render or sub-agent re-use |
| **Creation — Class B durable op** | Tier 1 computes the new buffer locally, hashes it, sends `IncomingTurn { action: { type: "buffer-mutated", target, newDataRef } }`. Tier 2 confirms via `surface_patch` referencing the new id; Tier 2 also emits `surface_data_ref_created` so the system knows the ref is now live |
| **Creation — Tier-3 structured payload** | Sub-agent returns payload; Tier 2 hashes, places in cache under namespace `canvas-state/<…>/cache/<dataRefId>`, emits `surface_data_ref_created` |
| **Reference from primitive** | The `dataRef` trait on a primitive holds `{id, signedToken, expiresAt}`; the client uses the token to fetch the buffer (if buffer lives server-side) or look up its local store (if buffer is client-held) |
| **Invalidation** | (a) `expiresAt` reached → automatic; (b) explicit `surface_data_ref_invalidated` from Tier 2 when a durable op replaces the buffer or when the cache TTL fires |
| **Garbage collection** | Tier 1: drops local buffer when no live primitive references it AND its expiry has passed. Tier 2: drops cache entry on TTL. Canvas-state retains only the metadata, not the bulk content |
| **Cross-turn stability** | DataRefs survive across turns until invalidated. The next turn can reference them by id; Tier 2 looks up in cache, or the client fetches by token |

The content-addressed id is what makes durable editing tractable: every "blur applied" produces a deterministic new id, the old one stays addressable until GC. Undo/redo (v2+) can navigate the id chain.

| Event | Causal fields | Carries | Purpose |
|---|---|---|---|
| `surface_snapshot` | `producesRevision: N` | full primitive tree + active `omadia-canvas-protocol` + ops-catalog version | Initial render / full replace; starts new revision |
| `surface_patch` | `basedOnRevision: N`, `producesRevision: N+1` | tree-path-targeted mutations | Incremental update; client rejects if `basedOnRevision` mismatches and requests snapshot |
| `surface_data_ref_created` | `revision: N` | `DataRef + {schema, sizeHint}` | Bulk data available behind signed reference (canonical shape, see above) |
| `surface_data_ref_invalidated` | `revision: N` | `{id, reason}` | Reference expired / changed |
| `surface_action_result` | `forActionId, basedOnRevision: N` | `{status, message?, followUpPatch?}` | Result of a user-triggered action |
| `surface_local_action` | `revision: N`, `effect: 'preview' \| 'durable'` | `{operation, params, target}` | Tier 2 instructs Tier 1 to execute a catalog operation. `effect: 'preview'` does **not** mutate `treeRevision` (transient visual, undo-able locally). `effect: 'durable'` is always followed by a `surface_patch` from Tier 2 that mutates `treeRevision` — so the durable result is reflected in canvas state and (in v2+) visible to all members. Durable ops on buffer-backed primitives (canvas-region, media, vector-path) trigger Tier 1 to report the new content-addressed `DataRef` back to Tier 2 via the next `IncomingTurn` |
| `surface_error` | `revision: N` | `{severity, message, scope}` | Render-side validation / dataRef denied / catalog op unknown / protocol mismatch |

**Client rules:**

- Snapshots reset state to `producesRevision`.
- Patches require matching `basedOnRevision`; otherwise drop and request snapshot.
- `surface_local_action` is processed against the current local state, no revision change unless followed by a patch.
- `surfaceSeq` is the transport-layer tie-breaker; gaps trigger a snapshot request.

---

## The Primitive Vocabulary (omadia-canvas-protocol/1.0)

**24 primitives** in three groups. Criterion for inclusion: must be composable into useful structures across data-aggregation, media, and editor workloads; must be implementable by Tier 1 against the Omadia theme.

### Core (data + UI building blocks)

| # | Primitive | Purpose |
|---|---|---|
| 1 | `text` | Block or inline copy |
| 2 | `heading` | Section title |
| 3 | `container` | Group of children, optional title / border / padding |
| 4 | `list` | Ordered collection of items |
| 5 | `table` | Rows × columns |
| 6 | `tree` | Hierarchical list (also serves as layer-stack with editor traits) |
| 7 | `button` | Action trigger |
| 8 | `input` | Text entry |
| 9 | `choice` | Single-select from N (radio, dropdown) |
| 10 | `toggle` | Boolean (checkbox, switch) |
| 11 | `image` | Static bitmap content |
| 12 | `chart` | Static data-driven visual (bar, line, pie) |
| 13 | `form` | Group of inputs + submit; with context-binding trait acts as an inspector |
| 14 | `toolbar` | Action strip |
| 15 | `menubar` | Cascading menu |
| 16 | `tabs` | Sibling containers with selector |
| 17 | `pane` | Positionable / resizable container (Miro-hybrid: technically a window, visually theme-driven) |
| 18 | `status` | Read-only display |
| 19 | `progress` | Progress of an ongoing operation |
| 20 | `divider` | Visual separator |

### Editor-class primitives

| # | Primitive | Purpose | Required props (v1.0) | Optional props |
|---|---|---|---|---|
| 21 | `media` | Audio/video with playback, scrubbing, volume; Tier 1 holds buffer | `mediaType: 'audio' \| 'video'`, `dataRef: DataRef`, `duration: ms` | `frameRate` (video), `resolution` (video), `sampleRate` (audio), `channels` (audio), `poster: DataRef` |
| 22 | `canvas-region` | Pixel-editor region (Photoshop-style); Tier 1 holds buffer as opaque local state | `width: int`, `height: int`, `pixelFormat: 'rgba8' \| 'rgba16'` | `dataRef` (initial content), `colorSpace`, `dpi` |
| 23 | `timeline` | Multi-track, frame/sample-precise time-axis (DaVinci, Logic, Premiere) | `tracks: Array<{id: string, kind: 'audio'\|'video'\|'marker'}>`, `timebase: {frameRate?: number, sampleRate?: number}` | `duration`, `playhead`, `loopRegion` |
| 24 | `vector-path` | Pen-tool curves (Photoshop paths, audio EQ curves, etc.) | `points: Array<{x: number, y: number, ctrlIn?, ctrlOut?}>` | `closed: boolean`, `strokeStyle`, `fillStyle` |

### Cross-cutting traits

Every primitive optionally carries these:

| Trait | Type | Purpose |
|---|---|---|
| `id` | string | Stable reference (patches, actions, selections) |
| `dataRef` | `DataRef` (see canonical shape above) | Reference to bulk data behind the primitive |
| `selection` | `"none" \| "single" \| "multi"` + `selected: id[]` | Selection state |
| `loading` | `"none" \| "skeleton" \| "spinner"` | Loading hint |
| `error` | `{message, severity}` \| null | Per-primitive error |
| `virtualized` | boolean | Lazy-render hint for large lists/tables |
| `action` | `{type, payload}` | Click/submit/change binding |
| `style` | restricted to theme tokens (`compact` / `spacious`, `accent` on/off, …) | Density and emphasis hints within the fixed Omadia theme |
| `continuous-input` | boolean | High-frequency input (brush pressure, slider drag values) |
| `selection-region` | shape descriptor (`{kind: 'rect'\|'lasso'\|'magic-wand', …}`) | Lasso / rectangle / magic-wand result regions |
| `realtime-output` | boolean | Tier 1 may render at 60fps from local state |
| `frame-precise-time` | `{unit: 'frame'\|'sample'\|'ms', value: number}` (required when present) | Editor-grade time precision |

**Spec format**: JSON tree, delivered as Anthropic tool-use argument (`canvas_render(tree)` or `canvas_patch(patches)`). Forced schema = reliable LLM output. Schema-versioned (see "UI Standard Versioning").

**Extension process for new primitives**: maintained by Omadia/Omadia UI developers, bound to a `omadia-canvas-protocol` minor version increment, dropped via RFC + PR. Documented from day one.

---

## Local Operations Catalog (Tier 1 Client)

Tier 1 declares a catalog of operations it implements natively — deterministic, instant, no LLM needed. Tier 2 reads the catalog at capability handshake and routes actions accordingly.

**v1.0 baseline catalog** (Host App must implement). Each entry has an `effect` class:

- **`preview`** — transient visual / audio modification, undo-able locally, does **not** change `treeRevision` or canvas state. Tier 1 keeps the preview in render-detail layer.
- **`durable`** — modifies the underlying buffer / structure. Tier 2 follows the `surface_local_action` with a `surface_patch` that mutates `treeRevision` and persists in canvas state.

| Domain | Operations | Effect |
|---|---|---|
| **Pixel** (operates on `canvas-region`) | brush, erase, fill, blur, sharpen, levels, curves | `durable` |
| **Pixel transforms** | crop, resize, rotate, flip | `durable` |
| **Pixel preview** | preview-blur, preview-curves, preview-levels (for live filter dialogs) | `preview` |
| **Vector** (operates on `vector-path`) | move, scale, rotate, smooth, bezier-edit | `durable` |
| **Audio** (operates on `media`/`timeline`) | trim, fade, normalize, gain, mute | `durable` |
| **Audio preview** | preview-gain, preview-eq, scrub | `preview` |
| **Video** (operates on `media`/`timeline`) | trim, splice, speed, mute-track | `durable` |
| **Video preview** | scrub, preview-speed | `preview` |
| **Geometry** (operates on any pane/container) | move, rotate, scale, snap | `durable` |
| **Layer** (operates on `tree` with layer trait) | visibility, opacity, blend-mode, lock, reorder | `durable` |
| **Selection** | rectangle, lasso, magic-wand, invert, deselect | `durable` (selection is part of canvas state) |

**Mechanic**: Tier 2 emits `surface_local_action` with `{operation, params, target, effect}`. Tier 1 looks up `operation` in its catalog, verifies the declared `effect` matches, executes locally. If `operation` unknown or `effect` mismatched, Tier 1 responds with `surface_error`, Tier 2 falls back to a Tier-3 tool call.

For **shared canvases (v2+)**: `preview` ops stay client-local per member; `durable` ops still follow the Tier-2-revision-then-patch pattern, so all members see the same authoritative state. The mechanic does not need changing — it is already shared-canvas-safe.

**Extension**: catalog versioning aligns with `omadia-canvas-protocol`. New operations require a minor protocol bump. Catalog version is negotiated separately from protocol version at boot (see handshake).

---

## Style — single material identity (Lume), user-bindable accent palette

**No dynamic skinning in v1.** Omadia UI ships a single material identity — **Lume** (light-as-material). Era-skinning (Norton-Commander-as-visuals vs. Photoshop-as-visuals) is **not** delivered.

**Within Lume, the accent slot is user-bindable** to one of three curated palettes:

| Palette | Story | Default |
|---|---|---|
| **Petrol** | computational ambient — cool steel-blue | — |
| **Atelier** | studio warmth — burnt-amber | — |
| **Lagoon** | lit water / bioluminescence — teal-cyan | ✓ |

This is **not** dynamic skinning. The material (Lume), the typography, the spacing, the composition idioms, the motion language are all single-source. Only the value bound to the `accent` token slot varies. The Skill never picks a palette — it references only the abstract token name. The user binds via conversational preference, and the binding persists in `memory://ui-prefs/<tenantId>/<userId>/<contextKey>/accent`. CONCEPT.md's existing context-aware prefs model carries it: a finance-canvas can bind Petrol while a creative-canvas binds Atelier. Default if unset: Lagoon.

**The agent can still receive era-style requests** ("zeig mir das im Norton-Commander-Stil") — but interprets them as **layout-composition hints**, not visual mimicry. The result is the requested layout (two panes with lists side by side) rendered in the active Lume palette.

**`style` trait** stays on every primitive but in v1 only accepts **theme tokens** (`compact` / `spacious`, `accent` on/off, density levels, emphasis, `center-glyph` for the donut-glow rule, and the typographic registers `"prose"` / `"mono"` on `text` primitives — see UI Skill prose-vs-structure protocol). Free-form style descriptions are clipped by the Tier-1 normaliser.

**Visual specification:** see [`docs/visual-spec.md`](docs/visual-spec.md) v0.2 for the full Lume token model, palette values, implementation primitives (two-stop glow, donut glow, patch-condensation animation, surface gradient), per-primitive notes and the five composition idioms rendered in Lume.

**Reversibility**: more palettes can be added additively; per-era visual skinning can be re-introduced later (the `style` trait already exists, the Skill would gain era-knowledge sections, the normaliser would handle cross-era conflicts) without an architecture change.

---

## Multiple Canvases (Spaces-style)

Single Omadia UI Host App instance per user system. Within that instance:

- N canvases, each with its own `canvasSessionId`, persistent across app restarts.
- User-controlled switch between canvases (hotkey, swipe gesture, palette).
- Visible indicator of current canvas (small marker, no full sidebar).
- All canvases share the user's preference store; **context-aware preferences** can be per-canvas (see Identity Model).
- No cross-canvas drag in v1 (deferred).
- Host App can run fullscreen or windowed (user choice, persistent).

**Fullscreen mode** = Win-3-in-DOS analogy: overlays the host OS entirely, Omadia UI is the workspace. **Windowed mode** = lives alongside other apps in the host OS.

### Canvas activation as an explicit action

Canvas switching is local (Class A) for the visual response, but the Host App **must** notify Tier 2 of the active canvas so the right state is loaded. The notification is an `IncomingTurn` carrying:

```ts
{
  canvasSessionId: "<the-newly-active-canvas-id>",
  action: { type: "canvas-activate", effect: "internal" }
}
```

Tier 2's response: load canvas-state + user prefs for the named session, emit `surface_snapshot` to restore the persisted tree. New canvases are bootstrapped the same way — Host App sends `canvas-activate` with a freshly generated `canvasSessionId`; Tier 2 finds no state, treats it as a blank canvas, emits an empty `surface_snapshot` with `producesRevision: 0`.

The Host App may also send `canvas-deactivate` (`{type: "canvas-deactivate", effect: "local"}`) when closing a canvas tab — Tier 2 finalises any pending cache/mutex state. Background Tier-3 work for a deactivated canvas continues; results just land in the persisted state without an immediate client emission.

---

## Identity Model

| Id | Scope | Source |
|---|---|---|
| `tenantId` | Per omadia deployment | Server config; propagated into `IncomingTurn.tenantId` (additive SDK change); defaults to `"default"` |
| `userId` | Across channels for the same human (best effort today; cross-channel merging on omadia Slice-2.5 roadmap) | Channel auth → `IncomingTurn.userRef` |
| `conversationId` | Per channel-level chat thread | Channel-native |
| `canvasSessionId` | Per persistent canvas surface | Tier-2 generated, stable across reconnects, persists across Host App restarts |
| `canvasOwnership` | Per canvas — who owns / has access | Opaque structure; v1 always `{kind: "single-user", userId}`; v2+ can extend to `{kind: "group", groupId, members: userId[]}` without breaking the wire format |
| `contextKey` | **Bound per canvas**: each `canvasSessionId` stores its own `contextKey` in canvas state, persisted across restores. Distinct canvases may run in different contexts simultaneously | Initially user-named or agent-inferred from conversation; mutable per turn |

**Scoping rules:**

- User preferences: `memory://ui-prefs/<tenantId>/<userId>/<contextKey>` — **context-aware**. Anchored at `<contextKey>="default"`; agent infers context switches from conversation ("Now I'm working on project Q1 Closing") or per-canvas convention.
- Canvas state: `memory://canvas-state/<tenantId>/<canvasSessionId>`
- Cross-channel conversation memory: provided by omadia core via `crossChannelConversationMemory@1` capability — depends on omadia core (see "Cross-Channel" below).

**SDK change**: add `tenantId?: string` to `IncomingTurn` (`incoming.ts:6-19`), additive.

**Context-aware prefs are required** because different work contexts demand different UIs — a private-music-collection canvas should not have to share its dense-grid preference with a business-budget canvas in compact mode.

---

## Cross-Channel — Depends on omadia core

**Requirement**: a user researching on Telegram during the morning commute and continuing in Omadia UI at the office must have their canvas materialise the prior context seamlessly. This is a quality-of-life must-have.

**Dependency**: this requires a `crossChannelConversationMemory@1` capability in omadia core — a durable, user-scoped conversation memory accessible to any channel/orchestrator. Today's `ConversationHistory` is channel-local, in-memory, 10 turns / 2h TTL (`inMemoryConversationHistory.ts`) — insufficient.

**Resolution path**: separate concept/PR-stream against `byte5ai/omadia` main, owned by an agent task outside this repo. The Omadia UI orchestrator (`requires: ["crossChannelConversationMemory@1"]`) loads from this capability at the start of each turn.

**This concept does not specify the omadia core change.** It marks the dependency and assumes the capability exists by the time Omadia UI ships.

---

## Security Surface

| Risk | Mitigation |
|---|---|
| Any tool can emit a canvas sentinel; extractor today sees only content + error | SDK change: extractor receives **origin metadata** `{toolName, pluginId, declaredCapabilities}`. New extractors (`_pendingCanvasTree`, `_pendingStructuredPayload`) reject sentinels whose origin lacks the canvas-output capability. Existing sentinels unchanged |
| `dataRef` could leak cross-session | HMAC-signed: `HMAC(serverSecret, tenantId ‖ userId ‖ canvasSessionId ‖ dataRefBody ‖ expiryEpoch)`. Server endpoint re-validates signature, scope, expiry |
| LLM-injected `action` payloads could trick Tier 2 | Action types whitelisted per-primitive in schema; unknown types dropped. Handlers map to declared semantic operations only |
| Renderer rendering arbitrary JSON | Whitelist parser at Tier 1: unknown primitive type → reject. Unknown trait → reject or strip |
| `surface_local_action` could trigger arbitrary local code | Operations catalog is closed: only catalog-listed operations execute. Unknown op → `surface_error` |
| External-effect actions (email send, file delete, payment, …) fired without user awareness | **Action-effect classification** (see below) makes external-effect intent declarable; Tier 2 enforces a confirmation modal before invoking such a tool |
| Server-secret leak | Rotating secret (24h lifetime), short-lived `dataRef` (≤ secret lifetime), graceful rotation (next-secret accepted alongside current for one rotation period) |

### Action-effect classification + confirmation contract

Every action declared on a primitive (via the `action` trait) carries an **`effect` classification**:

| Effect | Meaning | Tier-2 behaviour |
|---|---|---|
| `local` | Tier-1 catalog op (Class B). No external side effects | Tier 2 emits `surface_local_action` directly |
| `internal` | Reversible work via Tier 3 (data fetch, recompute, transient note, …) | Tier 2 calls the tool, emits patch with result |
| `external-effect` | Non-reversible effect outside the system (email send, file delete, payment, calendar invite, public publish, …) | **Tier 2 MUST emit a confirmation modal first** (see pattern below). The original tool call happens only after the user emits the `confirm-<actionType>` action |

**Standard confirmation pattern** (Tier 2 emits this on first contact with an `external-effect` action):

```jsonc
surface_patch {
  basedOnRevision: N, producesRevision: N+1,
  patches: [
    add pane: {
      kind: "modal",
      container: {
        heading: "<agent-authored short title>",
        text: "<agent-authored explanation of what will happen, irreversible aspects, recipient/target identifiers>",
        toolbar: {
          children: [
            { button: { label: "Cancel", action: { type: "cancel-modal", effect: "local" } } },
            { button: { label: "<verb, e.g. Send>", action: { type: "confirm-<actionType>", effect: "internal", payload: <original action payload> } } }
          ]
        }
      }
    }
  ]
}
```

The `external-effect` action's payload travels through the confirmation modal; on confirm, Tier 2 receives `confirm-<actionType>` and now executes the actual tool. If the user clicks Cancel, the modal is removed via patch and nothing else happens. The original `external-effect` action **never directly invokes its tool** — only its confirmation gate does.

This pattern is shared-canvas-safe by construction: in v2+ multi-user canvases, the modal becomes visible to all members, but only the originating user (per `canvasOwnership` and presence) sees the confirm/cancel buttons as actionable.

---

## omadia-canvas-protocol Versioning

The wire format between Tier 1 (Host App + Channel) and Tier 2 is versioned as **`omadia-canvas-protocol/1.0`** from day one.

**Boot handshake (concrete):**

The handshake is the **first message exchange** after WebSocket-open. It is server-initiated (the channel plugin sends first) — this avoids ambiguity about who has to know what.

1. **Server → Client: `handshake_offer`**
   ```ts
   {
     type: 'handshake_offer',
     protocolVersions: string[],        // e.g. ["1.0"] — channel plugin manifest declares this
     opsCatalogVersions: string[],      // e.g. ["1.0"] — Tier 2 publishes this
     serverFeatures: string[],          // optional capabilities (telemetry, replay, …)
     handshakeId: string                // for correlation
   }
   ```

2. **Client → Server: `handshake_select`**
   ```ts
   {
     type: 'handshake_select',
     handshakeId: string,
     protocolVersion: string,           // single chosen value from offer
     opsCatalogVersion: string,         // single chosen value from offer
     clientFeatures: string[],
     localOperations: string[]          // catalog of operations this client actually implements
   }
   ```

3. **Mismatch → Server: `handshake_error`**
   ```ts
   {
     type: 'handshake_error',
     handshakeId: string,
     reason: 'protocol-version-unsupported' | 'ops-catalog-version-unsupported' | 'local-ops-incomplete',
     supported: { protocolVersions, opsCatalogVersions }
   }
   ```
   Client may downgrade and re-send `handshake_select` once. Second mismatch → connection closes.

4. **Success → Server: `handshake_ack`** — connection enters the streaming phase, surface events flow normally.

**Versioning policy:**

- **Protocol** and **ops catalog** are versioned independently. Catalog may grow faster than protocol (more operations don't need wire-grammar changes).
- **Minor bump** (`1.1`, `1.2`, …) = additive. Old clients ignore unknown fields/types/operations gracefully.
- **Major bump** (`2.0`) = breaking. Reserved; not expected in v1 lifecycle.
- Addition process: maintained by Omadia/Omadia UI developers; RFC + PR; documented in `docs/protocol/<version>.md`.

**`localOperations` declaration in `handshake_select`** is the authoritative truth for what the connected Tier-1 client can do. Tier 2 reads it and routes Class-B actions accordingly: if the client claims `blur`, Tier 2 sends `surface_local_action(blur, …)`. If not, Tier 2 falls back to a Tier-3 tool. The Host App can ship a subset of the catalog and still work — composition idioms gracefully degrade.

**Versioned components:**

- Primitive vocabulary (20 core + editor primitives in 1.0; 21st primitive = 1.1 minor bump).
- Cross-cutting traits.
- Surface event grammar.
- Local operations catalog baseline.
- Sentinel envelope format.

**Documented in this repo** under `docs/protocol/1.0.md` (TBD — written during spike).

---

## SDK changes (minimal, additive against `byte5ai/omadia` main)

| Change | Where | Size |
|---|---|---|
| Add `'canvas'` value to channel manifest capabilities enum | `middleware/src/api/admin-v1.ts:136-144` + `manifestLoader.ts:409-463` | trivial |
| Add `channel.dispatchService?: string` to channel manifest | same files | one optional field |
| Add `channel.canvas_protocol_version?: string` to channel manifest | same files | one optional field |
| Service-name version-stripping convention in boot wiring | `middleware/src/index.ts:1700-1716`, `pluginContext.ts:213-216` | small additive helper |
| Wire `TurnDispatcher` to honour `dispatchService` at boot | `middleware/src/index.ts:1700-1716` + `coreApi.ts:16-25` | small refactor |
| Add `tenantId?: string` to `IncomingTurn` | `harness-channel-sdk/src/incoming.ts:6-19` | one optional field |
| Add `surface?: OutgoingSurface` to `SemanticAnswer` | `harness-channel-sdk/src/outgoing.ts:25-81` | one optional field + type |
| Add `surface_*` event family (incl. `surface_local_action`) with revision metadata to `ChatStreamEvent` union | `harness-channel-sdk/src/chatAgent.ts:374-500` | seven new discriminated members |
| Origin-metadata carry-through in sentinel extraction | `orchestrator.ts:903-919` + extractor signatures | small carry-through |
| New extractors (`_pendingCanvasTree`, `_pendingStructuredPayload`) origin-gated | `orchestrator.ts:514-590` | new parsers |
| Add `surface?: PendingCanvasSurface` to `ChatTurnResult` | `harness-channel-sdk/src/chatAgent.ts:250-326` | one optional field |
| Document `structured?` output-envelope convention | `plugin-api/src/` (new types + doc) | small interface |
| Document `canvas-output` tool capability declaration | `admin-v1.ts` permissions block | one entry |
| Document HMAC `dataRef` signing scheme + server-secret rotation | new doc + server middleware spec | doc + middleware in spike |

**Depends on omadia core (separate work-stream):**

| Required capability | Why | Status |
|---|---|---|
| `crossChannelConversationMemory@1` | Cross-channel state continuity (Telegram → Omadia UI seamless) | Out of scope for this repo; tracked as omadia-core RFC/PR-stream |

---

## State Model

| Layer | Lives in | Backed by | Concurrency |
|---|---|---|---|
| **Active canvas state** (tree, style tokens, selections, pending dataRefs, current `treeRevision`) | Tier 2 | `memoryStore@1`, namespace `canvas-state/<tenantId>/<canvasSessionId>` | Tier-2 per-session mutex (single-writer model, v1). v2+ shared canvases require CRDT-capable store or leader election — store-backend swap, no wire-format change |
| **Data refs** (bulk rows behind `dataRef`) | Tier 2 datastore | thin scoped store inside the orchestrator plugin, signed-token addressable | Append-only with TTL |
| **Render detail** (scroll, hover, accordion, unsubmitted inputs, brush buffer, audio cursor) | Tier 1 client, in memory | not persisted, lost on app close (acceptable) | single-client |
| **User preferences** | `memoryStore@1`, namespace `ui-prefs/<tenantId>/<userId>/<contextKey>` | filesystem-backed; **context-aware** | low-frequency, same per-user mutex pattern |
| **Cross-channel conversation memory** | omadia core (`crossChannelConversationMemory@1`) | depends on omadia core | provided by core |

**Editor-class state** (canvas-region buffer, timeline audio/video, vector-path geometry) lives in Tier 1 client render-detail layer. Tier 2 holds metadata + dataRefs to the underlying media files, not the pixel/sample data itself.

---

## What classic channels see

Nothing. All changes additive, conditionally engaged via the `'canvas'` capability flag and `dispatchService` field.

- `SemanticAnswer.surface` ignored by channels not declaring `'canvas'`.
- New `surface_*` events default-ignored in existing switch statements.
- `_pendingCanvasTree` and `_pendingStructuredPayload` sentinels origin-gated.
- `canvasChatAgent@1` invoked only by channels with `dispatchService`.
- `IncomingTurn.tenantId` defaults to `"default"`.

One smoke test per existing channel proves clean ignore. Migration risk negligible.

---

## Forward Compatibility: Shared Canvases (v2+)

A planned future capability: multiple users collaborating on the same canvas, conceptually parallel to a Teams group. Omadia core already supports group conversations where memory entries are scoped to all users present at creation time; Omadia UI should be able to ride on that.

**Not in scope for v1.** Not built, not implemented. But the v1 architecture has to leave room for it — refactors of identity, state, and event semantics are expensive once production users are on the system.

### Hooks already in place (v1)

| Hook | What it enables later |
|---|---|
| `canvasOwnership` as opaque structure (v1: `{kind: "single-user", userId}`) | Extends to `{kind: "group", groupId, members: userId[]}` without breaking the identity scheme |
| `treeRevision` specified as opaque identifier (v1: integer) | Wire format unchanged when the implementation moves to Lamport clocks / CRDT op-ids |
| Channel plugin as fan-out point | v2 multi-cast to all connected members is a channel-implementation detail, not a protocol change |
| Memory-Scoping delegated to omadia core (we consume `memoryStore@1` / `crossChannelConversationMemory@1`) | Group memory comes for free when core delivers group-scope on those capabilities |
| Single-instance Tier-2 assumption explicitly documented as v1 constraint | Multi-instance / CRDT store is a backend swap, expected, not a surprise |
| Reserved future event family `presence_*` (separate from `surface_*`) | Awareness data (cursor positions, "X is editing this widget", selection highlights) lands in its own stream without overloading the tree-state events |
| Local operations catalog routes through Tier 2 (not Tier 1 client direct) | Tier 2 stays the conflict-arbitration point when multiple members trigger operations simultaneously |

### Decisions explicitly deferred (v2 work)

- **Conflict resolution strategy**: CRDT (Figma-style), operational transformation (Google-Docs-style), or pessimistic locking (Miro-style per-element locks). Selection follows a survey of the field at v2 spike time, not now.
- **Awareness UX**: cursor rendering, presence indicators, "X is editing this widget" affordances. UX work, follows once the data model is set.
- **Permissions model**: view / comment / edit / admin per member. Depends on omadia core's group model — we consume what core provides.
- **Branching / forking** of a shared canvas (e.g. "experiment offline, merge back"). Open question, likely v3+.

### Things v1 must NOT do that would block v2

- Hard-code `userId` into anything that should logically be "canvas owner". Use `canvasOwnership.userId` (single-user) instead, so the swap to group is a one-line extension.
- Assume `treeRevision` is comparable with `<` or `>`. Use equality only.
- Embed presence state into `surface_*` events. Keep tree mutation events clean.
- Tie the per-session mutex to anything user-facing. It is an internal correctness mechanism, not part of the protocol.
- Treat `surfaceSeq` as client-originated. It is server-assigned from v1, exactly so that v2 channel-side fan-out + multi-cast remains consistent.
- Have `surface_local_action` with `effect: 'durable'` skip the Tier-2-revision-then-patch step. Even in v1, `durable` ops produce a revisioned patch — this is what makes them shared-canvas-safe by construction.

This section becomes the input for the v2 design phase. It is not a v1 deliverable.

---

## Riskiest Assumptions

1. **Top-tier and fast LLMs can reliably emit valid primitive trees as tool-use JSON.** Likely yes for Sonnet/Opus; unproven for Haiku-class on UI-tree synthesis (omadia uses Haiku only as classifier today). Mitigation: `ui_orchestrator_model` configurable; spike with Haiku first, fall back to Sonnet if reliability below threshold.
2. **The 24 primitives + traits + local-ops catalog are expressive enough for v1's range** (data aggregation + media + basic editor workloads). Provable only after real sessions. Mitigation: protocol-versioned addition process.
3. **The Tier-1 local operations catalog is comprehensive enough that editor workloads don't constantly fall back to Tier 3.** A Photoshop-like brush stroke must not hit the server. We assume the v1.0 baseline catalog covers the common cases; AI-driven operations and external-service calls remain Tier 3 as designed.
4. **Per-session mutex in Tier 2 is enough for production concurrency.** True as long as Tier 2 runs single-instance per deployment. Multi-instance Tier 2 requires CAS-capable store or leader election — out of v1 scope, architecture allows the swap.
5. **HMAC-signed `dataRef` with rotating server secret is operationally manageable.** Standard pattern; spike must validate the rotation procedure.
6. **`crossChannelConversationMemory@1` will be delivered by omadia core in time.** Outside this repo's control. If it slips, Omadia UI can ship with per-channel context only (degraded experience) until the core capability lands.
7. **Composition-idiom library is sufficient to give era-style requests visible value** without dynamic skinning. Empirically falsifiable; if users reject "Norton Commander-as-layout-only", dynamic skinning becomes a v2 addition (reversible).

---

## Verification (no code)

1. **Use-case walkthroughs**: at least two scenarios traced step-by-step with tier responsibility and event sequence:
   - **Multi-source comparison** (Jira × ERP × HR) — data aggregation lane.
   - **Photo edit micro-task** (apply blur to selection, then AI background removal) — editor lane that exercises both Tier-1 local catalog and Tier-3 AI tool.
2. **Mockups**: 5 key screens for the data-aggregation walkthrough plus 3 for the editor walkthrough, in the single Omadia theme. Demonstrates the theme works across workload classes.
3. **Schema specification**: JSON schemas for the 24 primitives, the traits, the surface event envelope, the sentinel envelope, the local operations catalog. Built during spike; informs PR scoping.
4. **PR plan** for `byte5ai/omadia` main, ordered for smallest mergeable atomic units:
   1. `'canvas'` capability + `dispatchService` + `canvas_protocol_version` + version-stripping helper
   2. `IncomingTurn.tenantId?`
   3. `surface_*` event family with revision metadata
   4. `SemanticAnswer.surface` + `ChatTurnResult.surface`
   5. Origin-metadata carry-through + new sentinel extractors
   6. `structured?` output-envelope convention + canvas-output tool capability
   7. New `omadia-ui-orchestrator` extension plugin
   8. New `omadia-ui-channel` channel plugin
   9. `omadia-canvas-protocol/1.0` documentation in this repo
5. **Separate work-stream** against `byte5ai/omadia` main: `crossChannelConversationMemory@1` capability proposal + implementation.

---

## Critical files

**Omadia main repo (`byte5ai/omadia`):**

- `middleware/src/api/admin-v1.ts` — `'canvas'` capability, `dispatchService`, `canvas_protocol_version`, canvas-output tool capability, version-stripping
- `middleware/src/plugins/manifestLoader.ts` — accept new manifest fields
- `middleware/src/index.ts:1700-1716` — wire `TurnDispatcher`; service-name version normalisation
- `middleware/src/platform/pluginContext.ts:213-216` — service-registry version-stripping
- `middleware/packages/harness-channel-sdk/src/incoming.ts:6-19` — `tenantId?` additive
- `middleware/packages/harness-channel-sdk/src/coreApi.ts` — service-aware dispatch
- `middleware/packages/harness-channel-sdk/src/outgoing.ts` — `OutgoingSurface`, `SemanticAnswer.surface`
- `middleware/packages/harness-channel-sdk/src/chatAgent.ts:374-500` — surface event family with revision metadata
- `middleware/packages/harness-channel-sdk/src/chatAgent.ts:250-326` — `ChatTurnResult.surface`
- `middleware/packages/harness-orchestrator/src/orchestrator.ts:514-590, 903-919` — origin-metadata + new extractors
- `middleware/packages/plugin-api/src/` — `structured?` envelope convention
- new package `middleware/packages/omadia-ui-orchestrator/` — Tier-2 extension plugin
- new package `middleware/packages/omadia-ui-channel/` — Tier-1 server-side channel plugin

**This repo (`byte5ai/omadia-ui`):**

- `CONCEPT.md` — this document
- `docs/protocol/1.0.md` — protocol specification (written during spike)
- Tier-1 Host App source — tech stack TBD
