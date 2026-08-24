---
id: SPEC-304
title: Marketplace v1 — install flows, add-on lifecycle, marketplace MCP App
phase: 3
depends_on: [SPEC-302, SPEC-303]
model: sonnet-5
effort: high
status: ready
---

# SPEC-304: Marketplace v1

## Goal
The P3 pillar's first shippable slice: browse (SPEC-303's merged model),
install with one click, configure through a generated form, see health and
updates — in the dashboard AND as a marketplace MCP App. "Like Home
Assistant's add-on store."

## Deliverables
1. Install flows per entry kind, each landing in existing machinery:
   - `remote` → creates a SPEC-302 `http` upstream (secret prompts from
     `config_schema`, values into the secret store, never echoed back);
   - `container` → pulls and runs the declared image with the declared
     mounts/env (docker via subprocess against the local socket — no new
     daemon dependency), then connects it as a SPEC-302 upstream;
     restart-on-crash policy, stop/remove on uninstall;
   - `stdio` command entries → SPEC-302 `stdio` upstream;
   - `skill`/`mcpb` → hand off to the connect page (SPEC-207's skill panel /
     SPEC-306's bundle download) — the marketplace lists them, it does not
     reinvent their delivery.
2. Config UIs generated from the entry's `config_schema` (JSON Schema
   subset: string/number/boolean/enum/secret — fixed here; a `secret` field
   writes to the secret store by name). Jargon-free labels come from the
   schema's `title`s; the form renderer is one shared component.
3. **Consent screen before every install** (dashboard-only, per §5.7's
   "security-sensitive administration stays dashboard-only"): shows kind,
   source, `verified` flag, declared permissions, and — for containers —
   image + mounts; the confirm button names the action ("Install and
   connect"). An unverified/manual entry gets a visibly stronger warning.
4. Update surface: `addon.update_available` event (curated index version vs
   installed), one-click update for containers, dashboard badge. No
   auto-update in v1.
5. Marketplace MCP App (§5.7 table): browse/search as a card grid inside
   the client, detail view; **Install itself always deep-links to the
   dashboard consent screen** — the app never performs the install (same
   security rule as #3). Shares the SPEC-208 app shell; plain-text
   fallback lists top results.
6. Lume adherence for all dashboard screens (normative source
   `v3/docs/design/lume/`, serif only for memory content — none here).

## Acceptance criteria
- [ ] e2e: from a curated-index entry, one-click install of a `remote`
      fixture upstream → its tool callable through a profile without restart
- [ ] container lifecycle against a fixture image: install → running →
      health visible → update → uninstall leaves no container behind
      (env-gated on docker availability; skipped honestly otherwise)
- [ ] a `secret` config field round-trips into the secret store and is
      never present in any subsequent GET (contract test)
- [ ] consent screen renders permissions + verified state; install without
      consent POST is impossible (REST requires the consent token)
- [ ] marketplace app renders in a host harness (SPEC-208 pattern), and its
      install action deep-links instead of installing
- [ ] jargon lint on all new UI copy (SPEC-205's DOM-scan pattern)

## Non-goals
Auto-updates; third-party submission flow; ratings/reviews; MCPB authoring
(SPEC-306); semantic tool routing (SPEC-305 option).
