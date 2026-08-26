---
id: SPEC-405
title: Team observability — directory & message flows, session-monitor app
phase: 4
depends_on: [SPEC-402, SPEC-403, SPEC-208]
model: sonnet-5
effort: high
status: ready
---

# SPEC-405: Team observability

## Goal
§5.4's trust rule: the human can read along, join in, or shut a
conversation down. The dashboard shows the live directory and message
flows; the session-monitor MCP App brings the same view (and the compose
form) into the chat clients; the stash browser app rounds out the §5.7
table's Phase-4 rows.

## Deliverables
1. Dashboard "Agents" screen: the live directory (scope, platform, model,
   status, idle time — `stale` visibly aged out), plus per-session message
   flows (threads from `/api/messenger`, metadata first, body on expand —
   owner-only surface). Live updates via the existing SSE bus
   (`session.*`, `message.*` events), no polling loop.
2. Owner controls, plain-language: end a conversation (expire a thread's
   undelivered envelopes), deregister a stale session, and **send as
   owner** — a compose form producing a schema-valid envelope (the form IS
   the schema: type picker, subject, urgency, expects-reply, body with the
   4KB counter, ref picker from recall search).
3. Session-monitor MCP App (`/mcp/team` or similar hub-level mount,
   SPEC-208 shell): live directory + flows read-only, plus the compose
   form posting through the app bridge under the caller's own token
   scopes. Plain-text fallback: a compact directory listing. Same
   security rule as SPEC-304: destructive owner controls (ending
   conversations, deregistering) stay dashboard-only; the app links out.
4. Stash browser MCP App (§5.7 Phase-4 row): cache entries with
   namespace/TTL/size, read-only inspection utility on the SPEC-208 shell.
   Small by design.
5. Lume adherence throughout (mono for handles/metadata, Signal rule, no
   serif — none of this is memory content); jargon-free copy (lint, both
   screens and both apps' visible text).

## Acceptance criteria
- [ ] directory screen renders live updates from real `session.*` events
      (vitest with SSE fixture); stale sessions visually distinct
- [ ] owner compose posts a valid envelope e2e (REST → SPEC-403 store →
      recipient's `messenger_check` sees it, sender shown as the owner
      handle)
- [ ] end-conversation expires the thread's undelivered envelopes and
      fires `message.expired`
- [ ] session-monitor app renders in the SPEC-208 host harness; its
      destructive controls are links to the dashboard, not tool calls
- [ ] stash browser app lists real entries via the app bridge
- [ ] jargon lint green on all new copy

## Non-goals
Editing messages; message search/archive; analytics.
