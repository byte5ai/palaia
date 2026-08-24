---
id: SPEC-403
title: Messenger core — structured envelopes, pull delivery
phase: 4
depends_on: [SPEC-402, SPEC-106]
model: opus-5
effort: medium
status: ready
---

# SPEC-403: Messenger core

## Goal
MASTERPLAN §5.4's second half: typed, token-disciplined messages between
sessions, brokered by the hub. Pull (MCP tools) is the universal baseline —
MCP 2026-07-28 removed server-initiated requests, so polling carries the
async semantics; push adapters are SPEC-404's.

## Deliverables
1. **Envelope, fixed shape** (implemented verbatim — this is the protocol):
   `{id (server-minted), type: request | inform | question | handoff |
   broadcast, from (sender handle), to (recipient handle, or a directory
   query for broadcast), subject (≤200 chars), urgency: low | normal |
   high, expects_reply: bool, body (≤4096 UTF-8 bytes — hard cap, loud
   error naming the fix: "write it to memory and reference it"), refs
   (list of `memory://` references, validated to resolve in a vault the
   sender can read), reply_to (envelope id | null), created_at,
   expires_at}`. The body cap is the token-discipline rule as a mechanism:
   long content goes into the vault once and is pointed at.
2. `palaia_hub.messenger`: SQLite store (hub home) — per-recipient inbox
   with `delivered`/`acked` state, TTL expiry (default 24h, per-message
   override ≤7d), sender outbox view. Broadcast resolves its directory
   query at send time to ≤20 recipients (hard cap, loud error) and fans
   out as individual envelopes.
3. MCP tool family `messenger_*` (opt-in per profile, like directory):
   `messenger_send` (validates envelope, resolves recipient handle via the
   directory, refuses a stale/unknown recipient with a plain-language
   error), `messenger_check` (new envelopes for MY handle — requires the
   SPEC-402 session secret, so a session reads only its own inbox; marks
   delivered), `messenger_ack` (acknowledge/close), `messenger_thread`
   (an envelope's reply chain). Dual output; the text rendering is compact
   by design (subject + type + refs, body only on the single-envelope
   read).
4. Authorization: sending requires `messenger:send` scope; checking
   requires the session secret from SPEC-402's registration (a scope
   alone must not read another session's inbox). The curator profile gets
   NO messenger tools (same fail-closed map as SPEC-302's fence).
5. Events (additive): `message.sent`, `message.received` (fires on
   delivery-check, carrying envelope metadata, never the body),
   `message.expired`. Automations can notify/webhook on them (SPEC-307's
   action kinds compose — no new automation work here).
6. REST read-only mirror `/api/messenger` (threads/flows metadata for
   SPEC-405's observability screen; bodies only for the owner via the
   admin surface).

## Acceptance criteria
- [ ] two real `fastmcp.Client` sessions (registered via SPEC-402) exchange
      request → reply e2e; thread links via `reply_to`
- [ ] a 5000-byte body is refused with the write-it-to-memory message; a
      `refs` entry that resolves nowhere is refused
- [ ] session A cannot `messenger_check` session B's inbox (secret test)
- [ ] broadcast over a directory query delivers to every match, caps at 20
- [ ] expiry: an unchecked envelope past `expires_at` is gone and
      `message.expired` fired (clock-injectable)
- [ ] `message.received` carries metadata only — the body never appears on
      the event bus (contract test)
- [ ] golden tools snapshot regenerated via the documented command

## Non-goals
Push delivery, messaging skills, effectiveness runs (SPEC-404); the
observability UI (SPEC-405); message search; cross-hub delivery.
