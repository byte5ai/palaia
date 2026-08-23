---
id: SPEC-201
title: Event bus & hooks v1
phase: 2
depends_on: [SPEC-102, SPEC-109]
model: sonnet-5
effort: high
status: ready
---

# SPEC-201: Event bus & hooks v1

## Goal
Every palaia subsystem emits events; users (and the curator) react to them.
The platform property from MASTERPLAN §5.6 — basic-memory's biggest gap.

## Deliverables
1. **Public event schema** (versioned, documented in `v3/docs/events.md`):
   envelope `{event, ts, vault?, permalink?, origin, data}` — v1 events:
   `memory.entry.created|updated|deleted|moved`, `inbox.captured`,
   `index.reindexed`, `index.embed_backlog_drained`, `doctor.finding`,
   `client.connected` (first authed call per token), `hub.started`.
   Unify the existing SSE stream (SPEC-109) and the vault engine's internal
   events onto this schema — one bus, three consumers (in-process subscribe
   API, SSE, webhooks).
2. **Outbound webhooks**: configured per hook (`url`, event filter, secret);
   HMAC-SHA256 signature header; at-least-once via a durable outbox
   (hub-level SQLite), retries with backoff, dead-letter after N attempts
   (visible via REST); idempotency key per event.
3. Hook management: config file + REST CRUD (`/api/hooks`) + minimal dashboard
   list (create/enable/disable/delete; the automation *editor* is Phase 3).
4. In-process subscription API typed for the curator (SPEC-206) to consume.

## Acceptance criteria
- [ ] vault write → webhook delivered with valid signature (integration test
      against a local receiver); receiver 500 → retried; permanent failure →
      dead-letter visible via REST
- [ ] SSE and webhook consumers observe the same event for the same write
- [ ] event schema documented; unknown-event-version consumers get a stable
      envelope (additive evolution rule stated)
- [ ] hook secrets never logged (redaction test)
- [ ] restart loses no queued outbox deliveries (durable outbox test)

## Non-goals
Automation editor UI, inbound webhooks, messenger events (Phase 4).
