---
id: SPEC-301
title: Gateway config in config.yaml — profiles as first-class objects
phase: 3
depends_on: [SPEC-210, SPEC-203, SPEC-205, SPEC-206]
model: sonnet-5
effort: high
status: ready
---

# SPEC-301: Gateway config in config.yaml

## Goal
The gateway's shape (profiles, vault mounts, tool renames) becomes durable,
operator-editable configuration instead of code-side assembly — the
foundation every other Phase-3 SPEC (external servers, marketplace installs,
profile editor) builds on. This also retires three documented bridges/debts:
the `oauth.profiles` config bridge (SPEC-203), the "enable OAuth still needs
a manual config.yaml edit" seam (SPEC-205 deviation), and the "a
wizard-created vault is not curated until restart" gap (SPEC-206 deviation).

## Deliverables
1. A `gateway:` section in `config.yaml`: profiles (path, mounted vaults,
   enabled built-ins like stash, tool renames per SPEC-105's `tool_renames`),
   with the same template-comment quality the `oauth:`/`curator:` sections
   set. `palaia_hub.serve.build_production_app` builds the DynamicGateway
   from it; with no section present, today's behavior (every vault on one
   `default` profile) is the generated default, so existing setups change
   nothing.
2. Runtime profile CRUD: REST under `/api/gateway/profiles` (create, rename,
   edit mounts/renames, delete), applied to the running DynamicGateway via
   its rebuild-and-swap and **persisted back to config.yaml** (the SPEC-205
   modes PATCH endpoint shows the write-back pattern). A profile path is
   immutable once clients connect to it — rename the display name, never the
   URL (document why: the path is the audience, SPEC-203).
3. `oauth.profiles` retired: the AS reads which resources exist from the
   gateway config (one source of truth). Config migration: a config carrying
   the old key gets it honored + a deprecation warning naming the fix; the
   template drops it.
4. The SPEC-206 gap closed: a vault created at runtime joins the profiles
   that mount "all vaults" (the default profile semantics) AND the curator's
   tool-action map without restart.
5. The SPEC-205 seam closed: the exposure wizard's "turn on remote access"
   step can enable OAuth (set issuer, enable flag) through the existing
   modes PATCH surface, now that profile/resource wiring no longer needs a
   hand edit.
6. Events: `gateway.profile.created/updated/deleted` (additive names,
   docs/events.md updated).

## Acceptance criteria
- [ ] zero-config hub behaves byte-identically to today (golden tools
      snapshot untouched; default profile serves every vault)
- [ ] a profile created via REST is MCP-reachable without restart and
      survives a restart (persisted to config.yaml)
- [ ] OAuth resources follow gateway profiles: token minted for a new
      profile's audience verifies on it e2e; `oauth.profiles` in an old
      config still works but warns
- [ ] wizard-created vault: curator curates a capture into it without
      restart (regression test on SPEC-206's documented gap)
- [ ] tool renames from config are applied and sanitized (SPEC-105 rules)

## Non-goals
External (non-palaia) servers in profiles — SPEC-302 adds that on this
foundation. A profile-editor UI — SPEC-305.
