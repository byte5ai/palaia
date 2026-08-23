# palaia Event Schema — v1

> **Normative.** This document defines the public event envelope every
> palaia hub subsystem emits, and the v1 event vocabulary. Implemented by
> [SPEC-201](../specs/SPEC-201-events-hooks.md) as
> `palaia_hub.events` (schema, bus, SSE, the vault bridge) and
> `palaia_hub.hooks` (outbound webhooks). MASTERPLAN §5.6 — "every palaia
> subsystem emits events; hooks are a platform property, not a memory
> feature."

## 1. One bus, three consumers

Before this SPEC, palaia had two parallel event mechanisms: the vault
engine's internal `ChangeEvent` vocabulary
(`palaia_hub.vault.events` — `NoteCreated`/`NoteModified`/`NoteMoved`/
`NoteDeleted`/`EntityRenamed`, vault-scoped, consumed by the index) and the
dashboard's own ad hoc `{"type", "data", "ts"}` SSE frames backed by a
raw filesystem watcher. Those are unified here onto **one public schema**,
carried by **one bus** (`palaia_hub.events.bus.EventBus`), reaching exactly
three kinds of consumer:

1. **In-process subscription** — `EventBus.on(callback)`, a plain
   synchronous callback. The webhook dispatcher
   (`palaia_hub.hooks.delivery.HookDispatcher`) is one such consumer; the
   curator (SPEC-206) is designed to be another.
2. **Server-Sent Events** — `GET /api/events`, one frame per envelope.
3. **Outbound webhooks** — a signed HTTP POST per configured hook per
   matching event (§4 below).

The vault engine's own `ChangeEvent` vocabulary is **not retired**: it stays
the index's incremental-update contract (richer, per-note, typed). What
changed is that the vault registry's `ChangeEvent` bus is now *also*
bridged, once, onto the public bus (`palaia_hub.events.bridge`) — so a
note write anywhere produces exactly one public `memory.entry.*` event, and
the SSE stream and every webhook observe the *same* event for the *same*
write.

## 2. Envelope shape

```json
{
  "event": "memory.entry.created",
  "ts": 1755999999.123,
  "vault": "work",
  "permalink": "projects/palaia-v3",
  "origin": "vault",
  "data": { "path": "projects/palaia-v3.md", "checksum": "…", "external": false },
  "id": "3f9c2e1a4b5d4f6a8b9c0d1e2f3a4b5c",
  "schema_version": 1
}
```

| Field | Type | Meaning |
|---|---|---|
| `event` | string | One of the v1 names (§3), or a future additive name. |
| `ts` | number | Unix timestamp (seconds, float) when the envelope was built. |
| `vault` | string \| null | The vault this event concerns, when there is one. |
| `permalink` | string \| null | The entry this event concerns, when there is one. |
| `origin` | string | Which subsystem published it: `vault`, `hub`, `auth`, `inbox`, `index`, `doctor`. |
| `data` | object | Event-specific payload (§3). May also repeat `vault`/`permalink` for a consumer reading only `data`. |
| `id` | string | Stable idempotency key for this occurrence — unchanged across webhook retries of the same delivery. |
| `schema_version` | integer | Currently `1`. See §5. |

On the wire, SSE frames carry this exact JSON as the `data:` line, with the
SSE `event:` field set to the same string as the envelope's own `event`
field — a browser `EventSource.addEventListener(envelope.event, ...)` and an
in-process/webhook subscriber are looking at the same name. Webhook
deliveries carry the same JSON as the POST body (§4).

## 3. v1 event vocabulary

| Event | Origin | `data` fields | Fired when |
|---|---|---|---|
| `hub.started` | `hub` | `version`, `mode` | The hub's ASGI app finishes starting up. |
| `client.connected` | `auth` | `token_id`, `client_name`, `profile` | A client token's *first* successful verification this process (mirrors `TokenInfo.last_used_at`'s own "resets on restart" trade — see `palaia_hub.auth.store`). |
| `memory.entry.created` | `vault` | `path`, `checksum`, `external`, `kind` | A new note lands in a vault (including a rename target, and a `capture` call's underlying write — see also `inbox.captured` below). |
| `memory.entry.updated` | `vault` | `path`, `checksum`, `previous_checksum`, `external`, `kind` (also carries an `EntityRenamed`'s `previous_permalink`/`title`/`previous_title`/`rewritten_links` when the update was a rename) | A note's content or identity changes in place. |
| `memory.entry.deleted` | `vault` | `path`, `external`, `kind` | A note is removed from a vault. |
| `memory.entry.moved` | `vault` | `path`, `previous_path`, `checksum`, `external`, `kind` | A note changes path while keeping its identity — including watcher-observed external renames. |
| `inbox.captured` | `inbox` | `permalink`, `capture_id`, `title`, `source`, `duplicate` | A `capture` tool call lands (or acknowledges a duplicate of) an `inbox/` note. Fires *in addition to* the `memory.entry.created` the underlying write itself produces — this event is the semantic "something was captured" signal; the other is the general "a file changed" signal. |
| `index.reindexed` | `index` | `count` | A vault's index finishes a full rebuild from files. |
| `index.embed_backlog_drained` | `index` | `embedded` | The embed backlog reaches zero after a batch of work (not fired on every batch — only once the backlog is actually caught up). |
| `doctor.finding` | `index` | `code`, `severity`, `detail` | One `verify()` finding — fired once per finding, not once per `verify()` call. |

`health` also travels the same bus and wire format (SSE only; it is not a
webhook-filterable v1 name — see §6) — it is the dashboard's periodic
liveness snapshot, carried over unchanged from before this SPEC.

## 4. Outbound webhooks

Configured per hook: a target `url`, an event-name filter (`["*"]` for
everything, or an explicit list of event names), and a secret minted at
creation time and never shown again. Every event whose name matches a
hook's filter is delivered:

- **Signed.** `X-Palaia-Signature: sha256=<hex hmac>` over the raw JSON
  body, keyed by the hook's secret (`palaia_hub.hooks.signing`).
- **Idempotent.** `X-Palaia-Event-Id` carries the envelope's `id` — the same
  value on every retry of the same delivery, so a receiver that already
  processed it can safely no-op.
- **At-least-once, durable.** Enqueuing a delivery commits a SQLite row
  (`palaia_hub.hooks.outbox`, one hub-level database — not per-vault)
  *before* any HTTP call is attempted; a hub crash or restart between
  "event happened" and "delivery succeeded" loses nothing.
- **Retried with backoff**, capped, and **dead-lettered** after a fixed
  number of attempts — a dead letter stays queryable via
  `GET /api/hooks/{id}/dead_letters`.
- **Never logged.** A hook's secret is stored in `hooks.yaml` (plain text —
  unlike a client token, HMAC signing needs the raw key back, so it cannot
  be hashed at rest) and appears in no log line anywhere in
  `palaia_hub.hooks`.

Management: `POST/GET/PATCH/DELETE /api/hooks`, opt-in on the running hub
(mounted when a `HookStore` is given to `create_app`), plus a minimal
dashboard list (create / enable / disable / delete) — the trigger →
condition → action automation *editor* is Phase 3 (MASTERPLAN §5.6), out of
this SPEC's scope.

## 5. Evolution rule

`schema_version` bumps only on a **breaking** change to the envelope shape
itself — a field renamed or removed. Everything else is additive and MUST
NOT bump it:

- A new event name.
- A new optional envelope field.
- A new key inside `data` for an existing event.

A consumer written against v1 MUST ignore any event name or field it does
not recognize rather than fail closed — this is what "unknown-event-version
consumers get a stable envelope" means in practice: the envelope's shape
(the fields listed in §2) is guaranteed not to disappear or change meaning
out from under an existing consumer; new information only ever arrives
alongside it.

## 6. Notes on scope

- `health` is a hub-internal heartbeat, not part of the v1 vocabulary a
  webhook can filter on (a webhook that requests `"*"` still receives it,
  since it travels the same bus — a filter naming it explicitly also
  works, it is simply not documented as a *meaningful* automation trigger).
- Inbound webhooks, a full automation editor, and messenger-sourced events
  (`message.received`, `session.*`) are explicitly out of scope for this
  SPEC (see its Non-goals) — planned for later phases per MASTERPLAN §5.6.
