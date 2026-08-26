---
id: SPEC-206
title: The curator — inbox to knowledge
phase: 2
depends_on: [SPEC-201, SPEC-106]
model: opus-5
effort: medium
status: ready
---

# SPEC-206: The curator

## Goal
The asynchronous brain that turns inbox captures into well-formed vault
knowledge (MASTERPLAN §5.1). **The policy below is fixed** (owner-proven in
mcp-hub production; adapted to v3 by the spec author) — the implementation
job is the runner, the guards, and the apply pass. Policy changes require a
spec PR, not code drift.

## The policy (binding)

1. **Two tiers.** INGEST (create a new note in the right place, or append
   observations to an existing one) is autonomous. MAINTENANCE (rewrite,
   merge, rename, retire, move, dedupe existing notes) is NEVER autonomous:
   it becomes a `review/` proposal per format spec §8, and a human approves.
2. **The tool surface IS the policy — enforced server-side.** The curator
   session authenticates with a dedicated curator token whose profile exposes
   ONLY: `search`, `read`, `list`, `recent_activity`, `build_context`,
   `write` and `edit`. A curator-scope middleware additionally rejects, at
   the gateway: any `edit` with a replacing operation, any `write` with
   overwrite semantics, any write into `inbox/`, any edit of existing
   `review/` notes (creating new proposals is allowed — self-approval is
   not), and **any write missing the capture's provenance line**
   `- [source] inbox capture <capture_id>`. Server-side beats mcp-hub's
   client-side hooks: the model literally cannot hold a capability the
   policy forbids.
3. **Verification, not trust.** After each capture's session, the runner
   searches the vault for the capture_id and classifies: `ingested` (a real
   note carries it), `needs_review` (only a proposal carries it), or
   `unverified` (nothing does → capture stays, reason appended additively).
   Only verified outcomes delete the inbox entry. Retries capped (3), then
   `status: curation-failed`.
4. **Deterministic apply.** Approved proposals (`status: approved`, flipped in
   Obsidian, dashboard, or the future review-queue app — same frontmatter
   field) are applied by plain code executing the proposal's typed plan
   (format §8): pre-images appended to the proposal first, every exit stamps
   a terminal status. No model in the apply path.
5. **Conservative is correct.** Missing `[entity]`/`[why]`, ambiguous type,
   contradiction with an existing note, thin content → propose, don't guess.
   One capture may yield several notes, or none (extend instead).

## The prompt (binding starting point — tune via PR)

System prompt assembled at runtime from: (a) the fixed role block below,
(b) the vault's `meta/curation.md` note if present (per-vault rules, read
live; absence is fine — format-spec defaults apply), (c) the capture itself.

> You are the palaia curator for the vault "<name>" — <purpose>. Session
> agents drop raw captures into inbox/ while working on something else; this
> run turns ONE capture into well-formed, findable vault knowledge. You are
> unattended: you cannot ask questions — writing a proposal into review/ is
> how you raise one, and it is a first-class outcome, not a failure.
> INGEST is yours: a new note in the right place, or additive observations on
> an existing note. MAINTENANCE is never yours: rewriting, merging, renaming
> or retiring what exists — propose it in review/ and stop. The restriction
> is enforced, not advisory; a rejected call is information, not an obstacle.
> Search the vault at least twice (entity name, then the claim itself) before
> writing; the title is the key — extend rather than duplicate. Titles and
> link targets stay volatility-free. Every note you write carries
> `- [source] inbox capture <capture_id>`. Never invent facts the capture
> does not contain. Be conservative: a proposal costs the owner thirty
> seconds; a wrong note costs the vault its trustworthiness.
> End with one line of JSON: {"action":"ingested"|"needs_review",
> "targets":[…],"summary":"…","reason":"…"}

## Deliverables
1. Curator runner (`palaia-hub curator run` + scheduled): event-driven via
   SPEC-201 (`inbox.captured`, debounced) plus interval fallback; per-capture
   bounded LLM sessions via a **config-driven runner command** (default:
   headless `claude -p` with strict MCP config pointing only at the curator
   profile; the command template is provider-neutral config).
2. Curator gateway profile + scope middleware per policy rule 2.
3. Verification + retry + retirement per rule 3; apply pass per rule 4.
4. Audit: outcomes to stash (`ops:curator.*`) + events on the bus; failures
   surface as `doctor.finding`.
5. Empty inbox costs (almost) nothing: one status query, no session.

## Acceptance criteria
- [ ] guard matrix test: every forbidden call from policy rule 2 is rejected
      at the gateway with an explanatory error (table-driven)
- [ ] runner ignores the model's self-report: verification classifies via
      capture_id search (tests for all three outcomes, incl. a lying session)
- [ ] approved proposal applies deterministically; pre-images preserved;
      every exit path stamps a terminal status (state-machine test)
- [ ] 3-strikes retirement; failure notes appended additively
- [ ] e2e with a scripted fake LLM runner (no real model in CI): capture →
      curated note → inbox entry gone; capture → proposal → approve → applied
- [ ] real-runner smoke test behind an env flag (uses the sandbox claude CLI
      if present), excluded from CI
