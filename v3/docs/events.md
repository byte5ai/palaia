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
| `origin` | string | Which subsystem published it: `vault`, `hub`, `auth`, `inbox`, `index`, `doctor`, `gateway`. |
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
| `hub.mode_changed` | `hub` | `from_mode`, `to_mode`, `restart_required`, `changed_keys` | The `POST /api/mode` exposure wizard endpoint (SPEC-205) accepts and persists an operating-mode/exposure change. `restart_required` is `true` whenever the change needs a hub restart to actually take effect (a mode/host/auth change) — a pure `exposure.public_url`/`exposure.tunnel` update needs none. |
| `client.connected` | `auth` | `token_id`, `client_name`, `profile` | A client token's *first* successful verification this process (mirrors `TokenInfo.last_used_at`'s own "resets on restart" trade — see `palaia_hub.auth.store`). |
| `memory.entry.created` | `vault` | `path`, `checksum`, `external`, `kind` | A new note lands in a vault (including a rename target, and a `capture` call's underlying write — see also `inbox.captured` below). |
| `memory.entry.updated` | `vault` | `path`, `checksum`, `previous_checksum`, `external`, `kind` (also carries an `EntityRenamed`'s `previous_permalink`/`title`/`previous_title`/`rewritten_links` when the update was a rename) | A note's content or identity changes in place. |
| `memory.entry.deleted` | `vault` | `path`, `external`, `kind` | A note is removed from a vault. |
| `memory.entry.moved` | `vault` | `path`, `previous_path`, `checksum`, `external`, `kind` | A note changes path while keeping its identity — including watcher-observed external renames. |
| `inbox.captured` | `inbox` | `permalink`, `capture_id`, `title`, `source`, `duplicate` | A `capture` tool call lands (or acknowledges a duplicate of) an `inbox/` note. Fires *in addition to* the `memory.entry.created` the underlying write itself produces — this event is the semantic "something was captured" signal; the other is the general "a file changed" signal. |
| `index.reindexed` | `index` | `count` | A vault's index finishes a full rebuild from files. |
| `index.embed_backlog_drained` | `index` | `embedded` | The embed backlog reaches zero after a batch of work (not fired on every batch — only once the backlog is actually caught up). |
| `doctor.finding` | `index` | `code`, `severity`, `detail` | One `verify()` finding — fired once per finding, not once per `verify()` call. |

### 3.1 Curator events (SPEC-206, additive)

`origin` is `curator` for all of them. Added after v1 shipped, which is
exactly what the evolution rule in §5 is for: a consumer that has never heard
of them ignores them.

| Event | `data` | Fires when |
|---|---|---|
| `curator.capture.ingested` | the capture record: `capture_id`, `permalink`, `outcome`, `targets`, `attempts`, `reason`, `self_reported`, `duration_seconds` | A real vault note is verified to carry a capture's provenance line — the capture is filed and its `inbox/` entry removed. |
| `curator.capture.needs_review` | same shape | Only a `review/` proposal carries it: a human decision is pending, and the capture is done. |
| `curator.capture.unverified` | same shape | Nothing in the vault carries it. The capture stays, with a `- [curation-failed]` line appended. Also raises a `doctor.finding`. |
| `curator.capture.retired` | same shape (`retired: true`) | The retry cap is reached; the capture is stamped `status: curation-failed` and will not be retried. |
| `curator.run.finished` | `vault`, `pending`, `sessions`, `records`, `summary` | One curation pass over one vault ends (including a pass that found an empty inbox). |
| `curator.proposal.applied` | `permalink`, `status`, `operations`, `applied`, `reason` | An approved proposal's plan ran to completion. |
| `curator.proposal.apply_failed` | same shape | An operation failed mid-plan; the proposal is stamped `apply-failed` and a `doctor.finding` is raised. |
| `curator.proposal.manual` | same shape | The proposal carries no executable plan (or an unparseable one) — a human has to apply it. |

### 3.2 Marketplace event (SPEC-303, additive)

| Event | Origin | `data` fields | Fires when |
|---|---|---|---|
| `market.index.updated` | `market` | `generated_at`, `entry_count`, `stale`, `warning` | The curated add-on index (`palaia_hub.market.curated.CuratedIndexClient`) is (re)fetched — on a fresh, verified document `stale` is `false` and `warning` empty; on a refused/tampered document or an offline network, `stale` is `true` and `warning` names the exact reason (the same reason logged as a WARNING), and `generated_at`/`entry_count` describe whichever copy (last-verified, or none) was served instead. |

### 3.3 Gateway profile events (SPEC-301, additive)

| Event | Origin | `data` fields | Fires when |
|---|---|---|---|
| `gateway.profile.created` | `gateway` | `path`, `vaults`, `stash` | `POST /api/gateway/profiles` creates a new MCP profile. |
| `gateway.profile.updated` | `gateway` | `path`, `vaults`, `stash` | `PATCH /api/gateway/profiles/{path}` changes an existing profile's label, mounted vaults, or stash flag. |
| `gateway.profile.deleted` | `gateway` | `path` | `DELETE /api/gateway/profiles/{path}` removes a profile. |

### 3.4 External MCP server events (SPEC-302, additive)

Reachability is reported only when it **changes** — a healthy external server
is silent, so these are safe to route to a phone. No event here ever carries a
credential: an upstream's stored secrets are referenced by name and never
included in `data` at all.

| Event | Origin | `data` fields | Fires when |
|---|---|---|---|
| `gateway.upstream.up` | `gateway` | `upstream`, `display_name`, `namespace`, `kind`, `detail`, `tool_count` | A probe (periodic or `POST /api/gateway/upstreams/{key}/probe`) reaches an external server that was previously unreachable or never checked. `detail` is the same one-line status the REST surface shows. |
| `gateway.upstream.down` | `gateway` | same shape (`tool_count` is `0`) | A probe cannot reach a server that was up, or the first check of a server fails. `detail` says why, in plain language. |
| `gateway.upstream.connected` | `gateway` | `upstream`, `display_name`, `kind`, `namespace`, `profiles` | `POST /api/gateway/upstreams` connects a new external server. |
| `gateway.upstream.updated` | `gateway` | `upstream`, `display_name`, `enabled`, `profiles` | `PATCH /api/gateway/upstreams/{key}` changes one (including switching it off). |
| `gateway.upstream.disconnected` | `gateway` | `upstream` | `DELETE /api/gateway/upstreams/{key}` removes one; every profile that mounted it is rebuilt without it. |

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
dashboard list (create / enable / disable / delete). The trigger →
condition → action automation *editor* — everything beyond a webhook — is
§7 below (SPEC-307).

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
- Inbound webhooks and messenger-sourced events (`message.received`,
  `session.*`) are explicitly out of scope for SPEC-201/307 (see their
  Non-goals) — planned for later phases per MASTERPLAN §5.6.

## 7. Automations (SPEC-307)

The trigger → condition → action editor `docs/events.md §4` pointed at as
future work: pick one event name (or `"*"`), an optional AND-combined
condition, and one action. Implemented as `palaia_hub.automations` — its
own store/outbox/dispatcher, deliberately separate from the hooks package
above (see that package's docstring for why a webhook's secret makes a
shared model the wrong shape).

### 7.1 Trigger

Any v1 event name (§3), including the curator's and stash's, or `"*"` for
every event. **Never** an `automation.*` event (§7.4) — refused at create
time with a plain-language error.

### 7.2 Condition grammar

A **fixed, closed vocabulary — not a general expression language.** A
condition is a list of clauses, **AND-combined**; an empty list always
matches. Each clause is `{field, op, value}`:

- `field`: `event`, `origin`, `vault`, or `data.<key>` — a path into the
  envelope's `data` object. A `data.<key>` clause never matches when the
  key is absent (never raises).
- `op`: `equals`, `contains`, or `prefix` — plain substring/prefix string
  comparison. No regex, no numeric/boolean coercion beyond stringifying
  the envelope's value, no nesting, and nothing here ever calls `eval`.
- `value`: a plain string.

A condition naming an unrecognized field, or an operator outside the three
above, is rejected at create/update time with an error naming exactly what
is wrong — never a bare stack trace.

### 7.3 Templating

`{{event}}`, `{{origin}}`, `{{vault}}`, `{{permalink}}`, `{{data.<key>}}` —
substituted into an action's template fields at match time (the *rendered*
result, not the template, is what the durable outbox persists — a retry
replays the original render, it does not re-read the envelope). A
placeholder naming a missing key renders empty and logs once per render
call; a bad template **never fails delivery**.

### 7.4 Action kinds

| Kind | Config | Effect |
|---|---|---|
| `webhook` | see §4 above | unchanged — configured through the hooks surface, not this one |
| `memory_write` | `vault`, plus templates for `what_it_concerns`/`why_keep`/`content`/(optional) `source` | Lands a format-spec §7 capture in the named vault's inbox — the same shape a real `capture` tool call produces. |
| `stash_set` | `namespace`, plus templates for `key`/`value` | Sets one stash entry (`palaia_hub.stash`). |
| `notification` | templates for `title`/(optional) `body` | Posts one entry to the dashboard notification center (`GET/POST /api/notifications/*`) — no email/push in v1. |

Delivery is durable and retried with the exact backoff/dead-letter policy
§4 describes for webhooks (`palaia_hub.automations.outbox`, a separate
hub-level SQLite database from the hooks one) — an event match commits a
row before the action ever runs, so a crash between "matched" and
"executed" loses nothing. A delivery whose action kind has no backing
service configured on this hub (no vault registry for `memory_write`, no
stash for `stash_set`) fails with a plain-language error rather than
crashing the worker.

### 7.5 Automation events, and the loop guard

Every delivery outcome fires `automation.fired` (delivered) or
`automation.failed` (dead-lettered), `origin: "automations"` — additive to
the v1 vocabulary, same as the curator's own events.

**Fixed rule, enforced twice:** an automation never triggers on its own
kind of event. A create/update call is refused outright if the trigger
event starts with `automation.`; independently, the dispatcher's runtime
match never fires on an `automation.*` event even for a `"*"` trigger.
Both are tested.

### 7.6 Test-fire

`POST /api/automations/{id}/test_fire` builds one synthetic envelope from
caller-supplied sample data and runs it through the *same* match →
condition → render → execute code every real event goes through — real
vault write, real stash set, real notification — scoped to the one
automation being tested (it does not also fire every other automation
subscribed to the same trigger) and resolved synchronously. Its delivery
log entry carries `test: true`, same shape as every other row, distinct in
the per-automation log (`GET /api/automations/{id}/deliveries`) from real
traffic.
