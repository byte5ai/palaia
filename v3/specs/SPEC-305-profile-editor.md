---
id: SPEC-305
title: Per-client tool profiles — dashboard editor
phase: 3
depends_on: [SPEC-301]
model: sonnet-5
effort: medium
status: ready
---

# SPEC-305: Profile editor

## Goal
MASTERPLAN §5.2's per-client profiles become editable by a person: "Codex
gets memory only; Claude Desktop gets everything" — as a screen, not a YAML
exercise. The URL already selects the tool surface (`/mcp/<profile>`,
SPEC-301); this SPEC is the UI and the last-mile conveniences.

## Deliverables
1. Dashboard "Tool profiles" screen: list profiles with their endpoint URL
   and a live tool count; create/edit assigns vaults, built-ins (stash),
   and SPEC-302 upstreams via checkboxes; per-tool rename inline (sanitized
   live, with the "connected clients may re-prompt for approval" warning
   from §5.2). Data layer is SPEC-301's REST — this SPEC adds no second
   write path.
2. Connect-page integration: the client picker gains a profile picker;
   every snippet/one-liner/bundle renders with the chosen profile's URL.
3. Per-tool visibility toggles within a mounted family (e.g. a profile
   mounts the work vault but hides `work_memory_delete`) — implemented with
   fastmcp's tool-filtering mechanism on the profile instance (Visibility
   is session-scoped on 3.4.7 — per-profile instances already exist, see
   SPEC-105 findings; do NOT mutate shared tool objects).
4. Optional **semantic tool routing** per profile (§5.2): the profile
   exposes `find_tool`/`invoke_tool` instead of the full surface, backed by
   the profile's real tool list. Off by default; marked experimental in the
   UI; plain-language explanation ("for very large tool collections").
5. Guardrails in the UI: the curator profile is visible but read-only
   (edited only via its SPEC — link out); deleting a profile warns with the
   connected-client consequence; the default profile cannot be deleted.

## Acceptance criteria
- [ ] create a profile in the UI → its endpoint serves exactly the chosen
      tools (e2e via `fastmcp.Client`), no restart
- [ ] hidden tool: absent from tools/list AND refused on call (not merely
      unlisted)
- [ ] rename via UI round-trips to config.yaml and the live gateway;
      invalid names are sanitized with the warning shown
- [ ] semantic routing profile: `find_tool` finds and `invoke_tool` invokes
      a real tool e2e; the full surface is absent
- [ ] jargon lint on the screen's copy; Lume tokens only

## Non-goals
Per-token (as opposed to per-profile) tool grants — scopes already govern
that; measuring tool-call success (masterplan metric, later phase).
