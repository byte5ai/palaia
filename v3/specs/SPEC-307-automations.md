---
id: SPEC-307
title: Automations — actions beyond webhooks + the editor
phase: 3
depends_on: [SPEC-201]
model: sonnet-5
effort: medium
status: ready
---

# SPEC-307: Automations editor

## Goal
MASTERPLAN §5.6's third step: hooks-as-config shipped in SPEC-201
(webhooks); this SPEC adds the remaining action kinds and the
trigger → condition → action editor in the dashboard.

## Deliverables
1. Action kinds beyond `webhook`, on the same outbox/delivery discipline
   (durable, retried, never blocking the bus): `memory_write` (a capture
   into a chosen vault's inbox, templated), `stash_set` (namespace/key/
   value template), `notification` (dashboard notification center — a new,
   small `/api/notifications` + bell in the shell; no email/push in v1).
2. Conditions: a small, safe expression form — field equals/contains/
   prefix on the envelope (`event`, `origin`, `vault`, `data.<key>`),
   AND-combined. **No general expression language** (fixed decision: a
   sandboxed template/matcher, not eval; document the grammar in
   docs/events.md §automations).
3. Templating: `{{event}}`, `{{vault}}`, `{{data.<key>}}` substitution into
   action payloads, escaped per sink; a template referencing a missing key
   renders empty and logs once, never fails delivery.
4. Dashboard "Automations" screen (extends SPEC-201's hooks screen):
   list/create/edit as trigger → condition → action cards, jargon-free
   (say "When a memory is created … then …"), test-fire button (sends a
   synthetic event through the real pipeline, marked `test: true`), per-
   automation delivery log with outcomes.
5. Recipes: 3-4 canned automations offered on the empty screen (e.g. "notify
   me when the curator needs a review", "webhook on doctor findings") —
   one click prefills the editor, nothing installs silently.
6. Events about automations themselves: `automation.fired`,
   `automation.failed` (additive; guard against loops: an automation never
   triggers on `automation.*` events — fixed rule, tested).

## Acceptance criteria
- [ ] each new action kind delivers e2e from a real bus event (memory_write
      lands a format-§7-valid capture; stash entry appears; notification
      visible via REST)
- [ ] loop guard: an automation on `automation.fired` is refused at create
      time
- [ ] conditions filter correctly incl. `data.<key>` paths; malformed
      condition rejected with a plain-language error
- [ ] test-fire runs the real pipeline and marks the delivery `test: true`
- [ ] delivery failures retry per SPEC-201's policy and surface in the log
- [ ] jargon lint on all screen copy

## Non-goals
Email/push notification channels; a visual multi-step workflow builder
(one trigger → one action in v1, multiple automations compose); tool
invocation as an action (needs per-automation auth design — Phase 4 with
the messenger).
