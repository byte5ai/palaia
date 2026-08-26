---
id: SPEC-406
title: Add-on SDK + community submission flow
phase: 4
depends_on: [SPEC-303, SPEC-304]
model: sonnet-5
effort: medium
status: ready
---

# SPEC-406: Add-on SDK

## Goal
The ecosystem play (§5.3): third parties can build, validate and submit
add-ons for the curated index — palaia becomes distribution, like HACS is
for Home Assistant. The SDK is deliberately thin: the manifest IS the
SPEC-303 entry shape; the SDK's job is scaffolding, validation and an
honest local test loop.

## Deliverables
1. `v3/sdk/` (new top-level v3 package, not inside the server): the add-on
   author's toolkit. `palaia-addon` CLI (small, stdlib+pydantic only):
   - `init` — scaffold an add-on directory (manifest + README + a minimal
     working stdio MCP server example in Python, runnable via `uvx`);
   - `validate` — the manifest against the SPEC-303 entry schema, the
     config_schema subset (SPEC-304's fixed field kinds), permission
     declarations, jargon lint over user-facing strings (reuse the
     SPEC-207 lint's rules — one blocklist, one place: extract it to a
     shared location both import);
   - `test` — spin the add-on up locally and drive initialize/tools-list
     through a real MCP client, printing what a marketplace user would
     see (name, one-liner, config form fields, permissions).
2. Submission flow, documented in `v3/docs/addon-submission.md`: a PR
   against the curated-index source adds the entry; the index maintainer
   validates (`palaia-addon validate`), reviews permissions, and re-signs
   with `v3/tools/sign_market_index.py`. What "verified" means (and does
   not mean) stated plainly. No web submission portal in this phase.
3. Server-side: nothing new. The SDK consumes published contracts only —
   a test asserts the SDK's schema copy and `palaia_hub.market.models`
   cannot drift (parity test, both repos' shapes compared field-by-field).
4. `v3/sdk/README.md`: the five-minute author path (init → implement →
   validate → test → submit), jargon-free.

## Acceptance criteria
- [ ] `init` scaffold passes `validate` and `test` out of the box (the
      example server answers tools/list through a real client)
- [ ] `validate` rejects: bad kind, unknown permission, config field type
      outside the subset, jargon in user-facing strings — each with a
      plain-language error naming the fix
- [ ] parity test: SDK schema == server market models (field names, kinds,
      required-ness)
- [ ] SDK has no dependency on palaia_hub (importable standalone;
      `uv run --project v3/sdk` works in isolation)
- [ ] docs: submission flow complete enough that a stranger needs no other
      file

## Non-goals
A hosted submission portal; automatic index publication; ratings; paid
listings. Container image scanning (curation is a human review in this
phase).
