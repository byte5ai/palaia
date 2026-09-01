# Use-Case Walkthroughs

Five narrative traces of an Omadia UI session against the architecture in [`../CONCEPT.md`](../CONCEPT.md). Purpose: validate that the wire format, tier responsibilities, and event grammar carry real work end-to-end. Where a step has an architectural risk, it is called out.

| # | Lane | What it stresses uniquely |
|---|---|---|
| 1 | Data aggregation (Jira × ERP × HR) | Sentinel origin gating, referential continuity, patch composition, skeleton latency |
| 2 | Editor (crop + blur + AI removal) | Class-A direct gestures vs. Class-B Tier-2-routed local ops, durable-effect-then-patch contract, Class-D AI work with concurrent canvas responsiveness |
| 3 | Multi-step wizard (sales proposal) | Persistent form state across many turns, conditional branching, wizard composition idiom, external-effect actions with confirmation flow |
| 4 | Live research with parallel note-taking | Real concurrency — user chats while background Tier-3 sub-agents stream into a second pane; mid-research plan modification |
| 5 | Multi-canvas day flow | Spaces-style switching between canvases with different `contextKey`s; canvas-state isolation; persistence across restarts and back-switching |

---

## Walkthrough 1 — Multi-Source Comparison

**Scenario:** User opens Omadia UI on a Monday morning and types:

> "Show me all open Jira tickets grouped by owner, the remaining ERP hour budget per person next to it, and flag everyone under 8 hours."

| Step | Actor | Event / Action | Tier | Latency class |
|---|---|---|---|---|
| 1 | Host App starts | WebSocket open to `omadia-ui-channel` | Tier 1 Client → Tier 1 Server | — |
| 2 | Channel plugin | `handshake_offer { protocolVersions: ["1.0"], opsCatalogVersions: ["1.0"], handshakeId }` | Tier 1 Server → Tier 1 Client | — |
| 3 | Host App | `handshake_select { protocolVersion: "1.0", opsCatalogVersion: "1.0", localOperations: [<full v1.0 baseline>] }` | Tier 1 Client → Tier 1 Server | — |
| 4 | Channel plugin | `handshake_ack` — streaming phase active | Tier 1 Server → Tier 1 Client | — |
| 5 | User types request | `IncomingTurn { tenantId, userId, conversationId, canvasSessionId, text: "Show me…" }` | Tier 1 Client → Tier 1 Server → Tier 2 (`canvasChatAgent@1`) | D (content-bound) |
| 6 | Tier 2 acquires session mutex, loads canvas state + user prefs (`ui-prefs/<tenantId>/<userId>/default`) | reads from `memoryStore@1` | Tier 2 server-internal | <100ms |
| 7 | Tier 2 decides "content-bound", delegates to `chatAgent@1` with the Jira + ERP sub-agents | Tier 3 sub-agent calls in parallel | Tier 2 → Tier 3 | D |
| 8 | While Tier 3 works: Tier 2 emits initial skeleton | `surface_snapshot { producesRevision: 1, tree: { type: "container", title: "Pulling tickets and budgets…", children: [ skeleton-table ] } }` | Tier 2 → Tier 1 Client | ~500ms |
| 9 | Host App renders the skeleton table; user can scroll/hover (all Class A) | — | Tier 1 Client local | <16ms |
| 10 | Jira sub-agent returns first | `_pendingStructuredPayload { prose: "12 open tickets", data: { rows: [...] }, dataRefId: "jira-q1" }` | Tier 3 → Tier 2 (sentinel parse, origin-gated) | seconds |
| 11 | Tier 2 begins composing the merged table | emits `surface_data_ref_created { revision: 1, DataRef: { id: "jira-q1", signedToken, expiresAt }, schema, sizeHint }` | Tier 2 → Tier 1 Client | <100ms |
| 12 | Tier 2 emits incremental rows as ERP sub-agent returns budgets | `surface_patch { basedOnRevision: 1, producesRevision: 2, patches: [ append-rows ] }` repeated | Tier 2 → Tier 1 Client | several seconds |
| 13 | Tier 2 applies the business rule (budget < 8h), emits | `surface_patch { basedOnRevision: 2, producesRevision: 3, patches: [ highlight-rows: ["anna","bernd","cara"] ] }` | Tier 2 → Tier 1 Client | <500ms |
| 14 | Parallel `text_delta` for prose narration | "Three people are under budget: Anna, Bernd, Cara." | Tier 2 → Tier 1 Client | streamed |
| 15 | User clicks Anna's row | Host App captures Class-A gesture, sends `IncomingTurn { canvasSessionId, action: { type: "row-click", rowId: "anna" } }` | Tier 1 Client → Tier 1 Server → Tier 2 | B (routed) |
| 16 | Tier 2 reads canvas state, knows Anna's row is in the current tree, decides "expand inline" — emits | `surface_patch { basedOnRevision: 3, producesRevision: 4, patches: [ expand-row: anna with detail-list ] }` | Tier 2 → Tier 1 Client | <500ms |
| 17 | User types follow-up: "okay, which of them are on vacation?" | `IncomingTurn { text: "okay, which of them are on vacation?" }` | Tier 1 Client → Tier 2 | D |
| 18 | Tier 2 resolves "of them" against `canvas-state` (current tree includes anna/bernd/cara highlight), calls HR sub-agent through `chatAgent@1` | Tier 3 | seconds |
| 19 | HR sub-agent returns structured vacation data | `_pendingStructuredPayload` | Tier 3 → Tier 2 | — |
| 20 | Tier 2 emits column-add patch | `surface_patch { basedOnRevision: 4, producesRevision: 5, patches: [ add-column: { id: "vacation", label: "Out", data: [...] } ] }` — note the previous highlight + expansion state survives | Tier 2 → Tier 1 Client | <500ms |

### Risk points exercised

- **Skeleton latency** (step 8): can we hit ~500ms? Empirically verifiable in spike. Falsifies if Haiku-class is too slow for initial tree synthesis.
- **Sentinel origin gating** (step 10): the Jira sub-agent must declare the `canvas-output` tool capability or Tier 2 rejects the structured payload. Tested by inserting an un-declared sub-agent.
- **Referential continuity** (step 17–18): "of them" must resolve against the current canvas state, not get rebuilt as a new table. Tested by inspecting the emitted patch shape — if it is `surface_snapshot`, consistency is broken.
- **Patch composition** (step 20): adding a column must preserve highlight and expansion state. Tested visually.

---

## Walkthrough 2 — Photo Edit Micro-Task

**Scenario:** User opens Omadia UI, drags a photo into the canvas, and types:

> "Crop this to 16:9, apply a slight blur to the background, and remove the lamp post in the upper right."

This exercises Class A (brush stroke), Class B (Tier-2-routed crop + blur), and Class D (Tier-3 AI lamp-post removal).

| Step | Actor | Event / Action | Tier | Latency class |
|---|---|---|---|---|
| 1–4 | Same handshake as Walkthrough 1 — Host App `localOperations` includes pixel ops, selection ops, layer ops | — | — | — |
| 5 | User drags image file onto the canvas | Host App captures the drop, computes a local `DataRef` (uploads bytes via signed pre-flight, gets `{id, signedToken, expiresAt}`), then sends `IncomingTurn { canvasSessionId, action: { type: "image-dropped", dataRef } }` | Tier 1 Client → Tier 2 | C (composition) |
| 6 | Tier 2 loads canvas state, decides on a Photoshop-workspace composition | emits `surface_snapshot { producesRevision: 1, tree: { type: "container", children: [ canvas-region (with image as dataRef), toolbar (tools), form (inspector, context-bound to selection), tree (layer-stack: "Background") ] } }` | Tier 2 → Tier 1 Client | C |
| 7 | User types: "Crop this to 16:9, apply a slight blur to the background, and remove the lamp post in the upper right." | `IncomingTurn { text: "…" }` | Tier 1 Client → Tier 2 | mixed |
| 8 | Tier 2 plans three operations: `crop` (durable, local), `blur` (durable, local), `remove-object` (Tier 3, AI) | — | Tier 2 internal | <500ms |
| 9 | Tier 2 emits | `surface_local_action { revision: 1, effect: "durable", operation: "crop", params: { aspect: "16:9", anchor: "centre" }, target: "<canvas-region-id>" }` | Tier 2 → Tier 1 Client | B |
| 10 | Host App looks up `crop` in its local catalog (declared in handshake), executes locally on the pixel buffer | — | Tier 1 Client local | <16ms |
| 11 | Tier 2 follows up with the revisioned patch (durable contract) | `surface_patch { basedOnRevision: 1, producesRevision: 2, patches: [ set canvas-region dimensions to 16:9 with new dataRef from the cropped buffer ] }` | Tier 2 → Tier 1 Client | B |
| 12 | Tier 2 needs to know "the background" — emits a select operation first | `surface_local_action { revision: 2, effect: "durable", operation: "select-magic-wand", params: { invertFrom: "lamp-post-area" }, target: "<canvas-region-id>" }` | Tier 2 → Tier 1 Client | B |
| 13 | Host App executes selection locally, captures selection-region trait | — | Tier 1 Client local | <16ms |
| 14 | Tier 2 follows with revisioned patch capturing the selection | `surface_patch { basedOnRevision: 2, producesRevision: 3, patches: [ canvas-region.selection = <lasso-region> ] }` | Tier 2 → Tier 1 Client | B |
| 15 | Tier 2 emits the blur op against the inverted selection | `surface_local_action { revision: 3, effect: "durable", operation: "blur", params: { radius: 4, target: "selection" }, target: "<canvas-region-id>" }` | Tier 2 → Tier 1 Client | B |
| 16 | Host App applies blur locally to the pixel buffer | — | Tier 1 Client local | <16ms |
| 17 | Tier 2 follows up | `surface_patch { basedOnRevision: 3, producesRevision: 4, patches: [ canvas-region.dataRef = new buffer hash ] }` | Tier 2 → Tier 1 Client | B |
| 18 | For lamp-post removal, Tier 2 calls Tier 3 AI tool `remove_object` (via `chatAgent@1`) with a region descriptor | Tier 3 | D |
| 19 | While Tier 3 works: Tier 2 emits a loading hint on the canvas-region | `surface_patch { basedOnRevision: 4, producesRevision: 5, patches: [ canvas-region.loading = "spinner" with overlay message "Removing object…" ] }` | Tier 2 → Tier 1 Client | <500ms |
| 20 | User can keep working (e.g. pan/zoom the partial result — Class A) — other parts of the canvas stay responsive | — | Tier 1 Client local | <16ms |
| 21 | Tier 3 returns processed buffer with `_pendingStructuredPayload { data: { newDataRefId, …}, prose: "removed the lamp post" }` | Tier 3 → Tier 2 | seconds |
| 22 | Tier 2 emits final patch | `surface_patch { basedOnRevision: 5, producesRevision: 6, patches: [ canvas-region.dataRef = newBufferRef, canvas-region.loading = "none" ] }` | Tier 2 → Tier 1 Client | <500ms |

### Risk points exercised

- **Class B preview vs. durable** (steps 9, 12, 15): each is `effect: "durable"`, each is followed by a revisioned patch from Tier 2. This is what makes the editor lane shared-canvas-safe by construction (forward-compat hook).
- **Local catalog completeness** (step 10, 13, 16): if the Host App declared `localOperations` does not include `crop` / `select-magic-wand` / `blur`, Tier 2 falls back to a Tier-3 tool — much slower. Test: drop one op from the handshake, observe fallback behaviour.
- **Canvas-region buffer integrity** (step 11, 17, 22): each durable op produces a new `DataRef` (signed, owner-bound). The dataRef lifecycle and content-hashing is non-trivial — design needs spike-level confirmation.
- **Class A responsiveness during Tier-3 work** (step 20): the pan/zoom must work while the AI service is running. Tests the responsiveness boundary — if the Tier-1 render loop is on the same queue as the WebSocket handler, this breaks.
- **`select-magic-wand` as catalog op** (step 12): magic-wand is a non-trivial algorithm. Tier 1 implements it natively. If a simpler client doesn't support it (declared in `handshake_select.localOperations`), Tier 2 falls back to a Tier-3 tool — the magic-wand becomes seconds-slow but still works.

---

---

## Walkthrough 3 — Multi-Step Wizard: Sales Proposal

**Scenario:** User says:

> "I need a proposal for a new insurance-industry customer who wants to evaluate our embedded-AI platform for claims processing."

| Step | Actor | Event / Action | Tier | Latency class |
|---|---|---|---|---|
| 1–4 | Handshake (same as Walkthrough 1) | — | — | — |
| 5 | User types request | `IncomingTurn { text: "I need a proposal for…" }` | Tier 1 Client → Tier 2 | C |
| 6 | Tier 2 recognises "proposal" intent, picks the wizard composition idiom from Skill | emits `surface_snapshot { producesRevision: 1, tree: { container: { children: [ tabs (steps: Customer / Use Case / Pricing / Document), form (step 1: customer fields), toolbar ({back, next}) ] } } }` | Tier 2 → Tier 1 Client | C |
| 7 | User fills in company name "AcmeInsure", contact, branch (pre-filled: Insurance), clicks **Next** | Class-A typing local; submit-click triggers `IncomingTurn { action: { type: "wizard-next", step: 1, payload: { company, contact, branch } } }` | Tier 1 Client → Tier 2 | C |
| 8 | Tier 2 calls CRM sub-agent to check if customer exists | structured payload returns `{ exists: false }` | Tier 2 → Tier 3 → Tier 2 | D (sub-second to seconds) |
| 9 | Tier 2 emits patch: step 1 done, step 2 active with branch-based template pre-fill | `surface_patch { basedOnRevision: 1, producesRevision: 2, patches: [ tabs.activeStep = 2, form (step 2): use-case template "Insurance claims" pre-selected, customer-status indicator: "new contact" ] }` | Tier 2 → Tier 1 Client | C |
| 10 | User refines use-case description ("claims triage + automated damage assessment + escalation routing"), clicks **Next** | `IncomingTurn { action: { type: "wizard-next", step: 2, payload: {...} } }` | Tier 1 Client → Tier 2 | C |
| 11 | Tier 2 → ERP sub-agent for pricing tables | structured payload returns pricing tiers | Tier 2 → Tier 3 → Tier 2 | D |
| 12 | Tier 2 emits patch: step 3 (Pricing) active with `table` of tiers + `choice` for selection | `surface_patch { basedOnRevision: 2, producesRevision: 3, patches: [ tabs.activeStep = 3, form (step 3): pricing-table with choice ] }` | Tier 2 → Tier 1 Client | C |
| 13 | User selects "Enterprise + 12-month evaluation", clicks **Next** | `IncomingTurn { action: { type: "wizard-next", step: 3, payload: { tier: "enterprise-eval" } } }` | Tier 1 Client → Tier 2 | C |
| 14 | Tier 2 composes the full document from accumulated state and emits snapshot | `surface_snapshot { producesRevision: 4, tree: { container: [ tabs.activeStep = 4, container: { heading: "Proposal — AcmeInsure", text (multi-paragraph cover letter), heading: "Scope", text (use-case description), heading: "Pricing", table (tier + line items), heading: "Next Steps", list, toolbar: { Edit, Generate PDF, Send to Customer } } ] } }` | Tier 2 → Tier 1 Client | C |
| 15 | User reads, clicks **Generate PDF** | `IncomingTurn { action: { type: "generate-pdf", documentId: "wiz-acmeinsure" } }` | Tier 1 Client → Tier 2 | D |
| 16 | Tier 2 → PDF generator tool (Tier 3) → returns `DataRef` for the PDF | structured payload | Tier 2 → Tier 3 → Tier 2 | D |
| 17 | Tier 2 emits patch with download surface element | `surface_patch { basedOnRevision: 4, producesRevision: 5, patches: [ toolbar.children += { button: "Download PDF" with dataRef-action }, status: "PDF generated 14:23" ] }` | Tier 2 → Tier 1 Client | <500ms |
| 18 | User clicks **Send to Customer** | `IncomingTurn { action: { type: "send-proposal", documentId, recipient: <from-step-1> } }` | Tier 1 Client → Tier 2 | C |
| 19 | Tier 2 emits a **confirmation modal** (external-effect actions require it) | `surface_patch { basedOnRevision: 5, producesRevision: 6, patches: [ pane: { kind: "modal", container: { heading: "Confirm send", text: "Send proposal PDF to contact@acmeinsure.com?", toolbar: { Cancel, Send } } } ] }` | Tier 2 → Tier 1 Client | <500ms |
| 20 | User clicks **Send** in the modal | `IncomingTurn { action: { type: "confirm-send", documentId, recipient } }` | Tier 1 Client → Tier 2 | D |
| 21 | Tier 2 → Email-send tool (Tier 3) → returns success + timestamp | structured payload | Tier 2 → Tier 3 → Tier 2 | D |
| 22 | Tier 2 emits patch: modal removed, status shows confirmation | `surface_patch { basedOnRevision: 6, producesRevision: 7, patches: [ remove pane.modal, status: "Sent to contact@acmeinsure.com 14:25" ] }` | Tier 2 → Tier 1 Client | <500ms |

### Risk points exercised

- **Wizard composition idiom** (step 6): the Skill's composition-idiom-library must produce a consistent step-tab + form + toolbar structure. Tested by reading the emitted `tree` shape — if it deviates per step, the idiom is unreliable.
- **State preservation across many turns** (steps 7–14): each `surface_patch` mutates only what changed; previous steps' data stays in the form. Tested by inspecting that step 4's document composition reads from earlier steps without re-querying.
- **Conditional branching** (step 9): CRM-lookup result (`exists: false`) drives the "new contact" indicator. If the lookup returned `exists: true`, step 2 would have different pre-fill. Tested by injecting both branches.
- **External-effect action gate** (steps 18–22): "Send to Customer" must require explicit confirmation. The pattern is a modal `pane` with explicit Send button, never a direct fire. Action-payload whitelist (in CONCEPT.md § Security Surface) rejects un-declared action types — verified by trying a fake action.
- **Action audit trail** (step 22): the confirmation status persists in the canvas as a `status` primitive, so the user (and any v2+ co-member) can see what was sent and when.

---

## Walkthrough 4 — Live Research with Parallel Note Building

**Scenario:** User says:

> "I have a meeting with AcmeCorp tomorrow. Research them for me and build a structured briefing as you go."

Demonstrates **real concurrency**: the user keeps interacting with the canvas while background Tier-3 sub-agents stream results into a second pane.

| Step | Actor | Event / Action | Tier | Latency class |
|---|---|---|---|---|
| 1–4 | Handshake | — | — | — |
| 5 | User types request | `IncomingTurn { text: "I have a meeting with AcmeCorp tomorrow…" }` | Tier 1 Client → Tier 2 | C |
| 6 | Tier 2 picks a 2-pane composition: left for ongoing chat, right for note-building | emits `surface_snapshot { producesRevision: 1, tree: { container: { layout: 'split', children: [ pane (chat: text-history + input), pane (notes: container with heading "AcmeCorp briefing" + skeleton list) ] } } }` | Tier 2 → Tier 1 Client | C |
| 7 | Tier 2 plans 3 parallel sub-agent calls (web-search, CRM-lookup, news-feed), starts all three | parallel `chatAgent@1` calls to sub-agents | Tier 2 → Tier 3 | D (fan-out) |
| 8 | While Tier 3 is working: Tier 2 emits scaffolding patch on the notes pane | `surface_patch { basedOnRevision: 1, producesRevision: 2, patches: [ notes-pane.children += [ section "General" (skeleton list), section "News" (skeleton), section "CRM Status" (skeleton) ] ] }` | Tier 2 → Tier 1 Client | <500ms |
| 9 | **In parallel**: user types in chat input: "actually focus on their AI strategy first" | `IncomingTurn { text: "actually focus on their AI strategy first" }` | Tier 1 Client → Tier 2 | C (or D depending on revisions) |
| 10 | Tier 2 reads the request, modifies its plan: re-prioritises sub-agent queries, emits structural patch | `surface_patch { basedOnRevision: 2, producesRevision: 3, patches: [ insert at top of notes-pane: section "AI Strategy" (skeleton, prominent), reorder others below ] }` | Tier 2 → Tier 1 Client | <500ms |
| 11 | Web-search sub-agent returns first batch (3 articles on AcmeCorp + AI) | `_pendingStructuredPayload { prose: "found 3 sources on AI strategy", data: { articles: [...] }, dataRefId: "ai-strategy-search" }` | Tier 3 → Tier 2 | seconds |
| 12 | Tier 2 emits append patch on AI Strategy section | `surface_patch { basedOnRevision: 3, producesRevision: 4, patches: [ AI-Strategy-section.children += [text-paragraphs derived from data], dataRef-trait set ] }` | Tier 2 → Tier 1 Client | <500ms |
| 13 | **Asynchronously**: news-feed sub-agent returns headlines | `_pendingStructuredPayload { data: { headlines: [...] } }` | Tier 3 → Tier 2 | seconds (later) |
| 14 | Tier 2 emits append patch on News section | `surface_patch { basedOnRevision: 4, producesRevision: 5, patches: [ News-section.children = list of headlines, skeleton-trait removed ] }` | Tier 2 → Tier 1 Client | <500ms |
| 15 | **In parallel**: CRM-lookup returns "no existing record" | `_pendingStructuredPayload` | Tier 3 → Tier 2 | — |
| 16 | Tier 2 emits patch on CRM-Status section | `surface_patch { basedOnRevision: 5, producesRevision: 6, patches: [ CRM-section.children = text: "no record in CRM — new contact?" ] }` | Tier 2 → Tier 1 Client | <500ms |
| 17 | User types: "and how big are they in revenue?" | `IncomingTurn { text: "and how big are they in revenue?" }` | Tier 1 Client → Tier 2 | C |
| 18 | Tier 2 has enough data from earlier web-search payload — composes a "Size & Revenue" section without a new Tier-3 call | `surface_patch { basedOnRevision: 6, producesRevision: 7, patches: [ notes-pane: append section "Size & Revenue" (text from existing dataRef) ] }` | Tier 2 → Tier 1 Client | <500ms |
| 19 | User clicks the "AI Strategy" section heading to collapse it (Class-A gesture) | local accordion toggle | Tier 1 Client local | <16ms |
| 20 | User selects three bullet points from the "Size & Revenue" section (Class-A) | local selection state | Tier 1 Client local | <16ms |
| 21 | User clicks "Export selection to Confluence" (toolbar button on the notes pane) | `IncomingTurn { action: { type: "export-confluence", selectionId, content: <serialised selected primitives> } }` | Tier 1 Client → Tier 2 | D |
| 22 | Tier 2 → Confluence tool (Tier 3) → page created and linked | structured payload returns `{ pageUrl: "https://…" }` | Tier 2 → Tier 3 → Tier 2 | D |
| 23 | Tier 2 emits patch with status + link | `surface_patch { basedOnRevision: 7, producesRevision: 8, patches: [ status: "Exported to Confluence", button: { label: "Open page", action: { type: 'open-url', url } } ] }` | Tier 2 → Tier 1 Client | <500ms |

### Risk points exercised

- **Concurrency on the Tier-2 mutex** (steps 7–16): the per-`canvasSessionId` mutex serialises turns, but Tier-3 sub-agents return asynchronously. Tier 2 must accept each return, acquire mutex briefly, emit patch, release. Tested by injecting overlapping returns — verify all patches land with strictly increasing `treeRevision`, no lost updates.
- **Plan modification mid-flight** (steps 9–10): the user changes focus while sub-agents are running. Tier 2 must update its plan AND modify the in-progress canvas structure without losing what's already populated. Tested by inspecting the emitted patch — if it's a `surface_snapshot`, the in-flight skeletons are lost.
- **Skeleton churn** (steps 8, 10): user-visible skeletons should not flicker. Tier 2 must compose patches that update structure incrementally, not redraw from scratch.
- **`treeRevision` monotonicity with async returns**: each return increments by exactly one, even when interleaved with user actions. Tested by logging all `treeRevision` values and asserting `+1` per emit.
- **No tier-3 re-call when not needed** (step 18): Tier 2 must reuse the earlier `dataRefId` payload to answer "how big are they in revenue" — calling Tier 3 again would be wasteful and slow. Tested by counting sub-agent calls per turn.
- **Selection persistence during async updates** (steps 19–20): while Tier 3 may still be streaming, the user's local selection in the Size & Revenue section must survive any patches that don't directly touch those primitives. Tested by inspecting selection trait after unrelated patches arrive.

---

## Walkthrough 5 — Multi-Canvas Day Flow

**Scenario:** User has three concurrent canvas sessions for three contexts. Morning: business budget review (compact, data-dense). Afternoon: private music library cleanup (photo-grid). Evening: project Q1 closing wizard (multi-step). The day exercises canvas-switching, per-canvas context preferences, and state persistence across restarts.

| Step | Actor | Event / Action | Tier | Latency class |
|---|---|---|---|---|
| **08:30 — Morning, Business Budget** | | | | |
| 1 | Host App starts (single instance), opens last-active canvas (`canvasSessionId: biz-budget`) | WebSocket connect → handshake (full sequence) — same as Walkthrough 1 | Tier 1 Client ↔ Tier 1 Server | — |
| 2 | First `IncomingTurn` from Host App declares active canvas | `IncomingTurn { canvasSessionId: "biz-budget", action: { type: "canvas-activate" } }` | Tier 1 Client → Tier 2 | C |
| 3 | Tier 2 loads canvas state from `canvas-state/<tenantId>/biz-budget`, finds `contextKey: "business"`, loads `ui-prefs/<tenantId>/<userId>/business` ("compact, monospace tables, accent: graphite") | reads from `memoryStore@1` | Tier 2 internal | <500ms |
| 4 | Tier 2 emits the persisted snapshot in business compact theme | `surface_snapshot { producesRevision: 12 (from yesterday), tree: { container: { compact-table (Q1 budget vs. actual), kpi-grid, status-bar }, style-tokens: "compact, monospace, accent: graphite" } }` | Tier 2 → Tier 1 Client | <500ms |
| 5 | User works for 30 min: scroll, hover, click cells for details — all Class A. No server contact for these | local interactions | Tier 1 Client | <16ms each |
| 6 | User types: "flag departments over budget" | `IncomingTurn { text: "flag departments…" }` | Tier 1 Client → Tier 2 | C |
| 7 | Tier 2 already has data, applies rule locally in spec, emits patch | `surface_patch { basedOnRevision: 12, producesRevision: 13, patches: [ highlight rows: departments-over-budget ] }` | Tier 2 → Tier 1 Client | <500ms |
| **13:45 — Afternoon, Music Library** | | | | |
| 8 | User presses ⌘2 (canvas switch hotkey) — Class-A gesture | Host App switches active canvas locally to `canvasSessionId: privat-music`, sends notification | `IncomingTurn { canvasSessionId: "privat-music", action: { type: "canvas-activate" } }` (the biz-budget canvas remains intact server-side) | Tier 1 Client → Tier 2 | C |
| 9 | Tier 2 loads canvas state for privat-music, finds `contextKey: "private"`, loads `ui-prefs/<tenantId>/<userId>/private` ("card-grid layouts, soft accent, generous spacing") | reads from `memoryStore@1` | Tier 2 internal | <500ms |
| 10 | Tier 2 emits the music library snapshot | `surface_snapshot { producesRevision: 8, tree: { container: { kpi (album count), grid of card-image (album covers), toolbar (sort/filter) }, style-tokens: "spacious, soft-accent" } }` | Tier 2 → Tier 1 Client | <500ms |
| 11 | User browses, clicks on an album — Class A | local hover/click | Tier 1 Client | <16ms |
| 12 | User types: "delete everything I haven't played in 2 years" | `IncomingTurn { text: "delete everything…" }` | Tier 1 Client → Tier 2 | D |
| 13 | Tier 2 → music-library sub-agent (Tier 3) | structured payload returns list of stale albums (243 items, with dataRef) | Tier 2 → Tier 3 → Tier 2 | seconds |
| 14 | Tier 2 emits patch with bulk-selection highlights + confirmation toolbar (external effect = delete) | `surface_patch { basedOnRevision: 8, producesRevision: 9, patches: [ grid: 243 cards marked with selection.selected, toolbar add: { Cancel, Delete 243 } ] }` | Tier 2 → Tier 1 Client | <500ms |
| 15 | User clicks **Delete 243** — confirmation flow as in Walkthrough 3 step 18 → modal → confirm | (modal pattern) | Tier 1 Client → Tier 2 | D |
| 16 | Tier 2 → Tier 3 delete, emits patch removing those cards | `surface_patch { basedOnRevision: 9, producesRevision: 10, patches: [ grid: remove 243 children, status: "243 deleted" ] }` | Tier 2 → Tier 1 Client | seconds |
| **17:30 — Evening, Project Q1 Closing** | | | | |
| 17 | User presses ⌘3 — switches to `canvasSessionId: q1-closing` | `IncomingTurn { canvasSessionId: "q1-closing", action: { type: "canvas-activate" } }` | Tier 1 Client → Tier 2 | C |
| 18 | Tier 2 loads canvas state — wizard from yesterday at step 3 of 5 still active, `contextKey: "project-q1-closing"`, prefs "structured, large fonts" | reads from `memoryStore@1` | Tier 2 internal | <500ms |
| 19 | Tier 2 emits snapshot: wizard tree restored exactly where the user left it | `surface_snapshot { producesRevision: 19, tree: { wizard composition with tabs (1 ✓ 2 ✓ 3 active 4 5), form (step 3 partial fill from yesterday) } }` | Tier 2 → Tier 1 Client | <500ms |
| 20 | User completes the wizard (similar flow to Walkthrough 3 steps 13–22) | — | — | — |
| **22:00 — Back to morning canvas** | | | | |
| 21 | User presses ⌘1 to return to biz-budget canvas | `IncomingTurn { canvasSessionId: "biz-budget", action: { type: "canvas-activate" } }` | Tier 1 Client → Tier 2 | C |
| 22 | Tier 2 loads biz-budget state — unchanged since step 7 (`producesRevision: 13`) | reads from `memoryStore@1` | Tier 2 internal | <500ms |
| 23 | Tier 2 emits snapshot: compact business layout with the same highlights from the morning | `surface_snapshot { producesRevision: 13, tree: <same as step 7's outcome>, style-tokens: "compact, monospace, accent: graphite" } }` | Tier 2 → Tier 1 Client | <500ms |

### Risk points exercised

- **Canvas-switch is a turn, not a free local switch** (steps 2, 8, 17, 21): the Host App switches the active surface locally (Class A for the visual hotkey response), but must immediately notify Tier 2 so the right `canvas-state` is loaded. Tested by inspecting that no `surface_*` events for the wrong canvas reach the client.
- **Per-canvas `contextKey` and prefs** (steps 3, 9, 18): each canvas loads its own `ui-prefs/<tenantId>/<userId>/<contextKey>` namespace. Tested by verifying the rendered tree uses the right style tokens.
- **State persistence across app restarts** (step 19): the wizard from yesterday is restored to exactly step 3. Tested by killing and restarting the Host App between sessions.
- **Multiple `canvasSessionId`s isolated in memoryStore** (parallel sessions): writes to one canvas state must not leak into another. Tested by inspecting that biz-budget state at step 22 has `producesRevision: 13` (where step 7 left it) and not 19 (where the wizard ended).
- **Per-session mutex independence** (concurrent canvases): the mutex is per `canvasSessionId`; switching does not block other sessions. Important when canvases run concurrent background work (e.g. a long Tier-3 fetch in the wizard while user is on the music canvas). Tested by triggering long-running work in one canvas and verifying responsiveness in another.
- **No global "current canvas" concept on Tier 2**: Tier 2 keeps per-session state, no global "active" pointer. The Host App is the only source of truth for "which canvas is on screen". Tested by verifying Tier 2 doesn't reject `IncomingTurn`s for non-displayed canvases (e.g. a background-running update can still apply).

---

## What all five walkthroughs validate

| Concern | Validated by |
|---|---|
| Three-tier latency split is real | Every walkthrough lists per-step latency class; no Class-A step round-trips the server, no Class-D step blocks the canvas |
| Class A / B / C / D boundary discipline | Walkthrough 2 (editor) and 5 (canvas switch) make the four classes concrete and distinguishable |
| `treeRevision` discipline | Every durable mutation produces a revisioned patch; preview-only ops never bump the revision; concurrent sub-agent returns each get exactly `+1` |
| Wire-format completeness | Every step uses only events, traits, primitives defined in CONCEPT.md — no inventions |
| Composition-idiom library is load-bearing | Walkthroughs 3 (wizard), 4 (split-pane with chat + notes), 5 (music card-grid) all rely on the Skill producing the right composition from natural-language intent |
| Editor lane has real Tier-1 work | Walkthrough 2 makes pixel buffers, selection regions, local catalog operations concrete |
| External-effect actions require confirmation | Walkthroughs 3 and 5 both gate Send / Delete behind modal `pane` + explicit confirmation toolbar |
| Async sub-agent fan-out works under per-session mutex | Walkthrough 4 shows three parallel Tier-3 returns, each landing as its own incremental patch |
| State persists across app restarts and canvas switches | Walkthrough 5 step 19 (yesterday's wizard at step 3) and step 22 (morning canvas unchanged since 08:30) |
| `contextKey` is per-canvas, not global | Walkthrough 5 shows three different prefs profiles loaded for three different canvases in one day |
| Forward-compatibility for shared canvases | Walkthrough 2 step 20 + Walkthrough 4 entire flow — Class-A responsiveness and per-canvasSession mutex independence are the v2 multi-cast prerequisites |

## What the walkthroughs do **not** validate

- Concrete UI design (visual mockups are separate work).
- Schema specification of each primitive (JSON Schemas are built during spike).
- Tech-stack-specific concerns (Tauri vs. Electron vs. native vs. PWA).
- Real-world latency numbers (need spike telemetry).
- Failure-mode UX (Tier 3 timeout, dataRef expiry mid-render, mutex deadlock recovery) — separate validation pass.
