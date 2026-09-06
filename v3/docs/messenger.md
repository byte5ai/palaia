# palaia Messenger — the agent-facing contract

> Written for skill authors and SDK users: what a session actually sees
> when it registers, sends, checks and replies. The envelope's wire shape
> and the hub-side storage/authorization rules are normative in
> [SPEC-403](../specs/SPEC-403-messenger.md) and
> [`docs/events.md` §3.6/§3.7](events.md); this document restates the parts
> an agent (or the prose of a skill teaching one) needs, without the
> implementation detail. Where a term below would read as internal
> plumbing to someone outside this repository, it says so in plain words
> instead — that is deliberate: this page is itself read by non-Anthropic
> tooling and the SKILL.md packages under
> [`v3/clients/skills/palaia-messenger`](../clients/skills/palaia-messenger/SKILL.md)
> lean on it.

## 1. Two tool families, one habit

**The session directory** (`directory_*`) is presence: who is connected,
doing what, on what host, for how long. **The messenger** (`messenger_*`)
is one message between two directory entries. Neither is memory — nothing
here is meant to outlive the conversation it is part of; anything that
should is written to memory once, and pointed at (§3).

A session registers once per task (`directory_register`), keeps that
registration alive with `directory_heartbeat`/`directory_update` for a long
task, and removes itself with `directory_deregister` when done. Everything
the messenger does afterward — sending, checking, replying — happens
against that one registration's handle and secret.

## 2. The envelope

Every message, in either direction, has this shape:

```json
{
  "id": "b3f1...c2",
  "type": "handoff",
  "from": "swift-otter-4a",
  "to": "calm-heron-7c",
  "subject": "billing retry batching — capped at 200, needs the queue split first",
  "urgency": "normal",
  "expects_reply": false,
  "body": "Wrote up the batching decision and why — see the reference below.",
  "refs": ["memory://projects/billing-service/retry-batching"],
  "reply_to": null,
  "created_at": 1755999999.123,
  "expires_at": 1756086399.123
}
```

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Minted by the hub when the message is sent. Never chosen by the sender. |
| `type` | `request \| inform \| question \| handoff \| broadcast` | What kind of message this is — see §4. |
| `from` | string | The sender's own handle, proven by its session secret at send time. |
| `to` | string | A recipient handle — or, for `type: "broadcast"`, the directory query it was cast with (§5). |
| `subject` | string, ≤200 characters | One line. Every listing a recipient sees before deciding to open something shows this and nothing else. |
| `urgency` | `low \| normal \| high` | Self-reported by the sender; a recipient's own habits decide what to do with it. |
| `expects_reply` | boolean | `true` means the sender is waiting on an answer — see §6. |
| `body` | string, ≤4096 UTF-8 bytes | The message itself. See §3 for the cap and what to do about it. |
| `refs` | array of `memory://` references | Pointers into whichever memory the sender can read, checked to actually resolve before the message sends. |
| `reply_to` | string or null | The id this answers, or null for a fresh message — this is what threads a conversation. |
| `created_at`, `expires_at` | number | Unix timestamps. A message not checked before `expires_at` is gone (default 24 hours; a sender may ask for up to 7 days). |

## 3. The body cap, and why

The body is capped at 4096 UTF-8 bytes, and a message over that limit is
refused — not truncated. Truncating would silently drop the half of a
decision nobody re-reads; refusing, with an error that names the fix,
keeps the sender in the conversation long enough to actually fix it.

The fix is always the same: **write the long content to memory once, and
put a reference to it in `refs` instead of pasting it into `body`.** A
message is a pointer between two working sessions, not a place to write
things down — the same distinction a note and a comment on it have. A
`refs` entry that resolves to nothing readable by the sender is refused
for the same reason a message would be otherwise useless: a recipient
cannot follow a reference that points nowhere.

This is not a quirk of one implementation — it is the whole reason `refs`
exists, and it is the one habit worth getting right before anything else
here: **short message, and a reference for anything long.**

## 4. Message types

| Type | Use it for |
|---|---|
| `request` | Asking for work to be done. |
| `inform` | Telling someone something. No reply implied. |
| `question` | Asking for an answer. |
| `handoff` | Passing a piece of work over to another session. |
| `broadcast` | One message, several recipients at once (§5). A broadcast cannot itself be a reply. |

## 5. Addressing, including broadcast

For every type but `broadcast`, `to` is one recipient's handle, taken from
the directory (`directory_list`/`directory_query`). An unknown or stale
handle is refused — a stale session may already be gone, and a message to
it would sit unread.

For `type: "broadcast"`, `to` is a small query grammar instead of a
handle, resolved against the directory *at send time*:

| `to` | Reaches |
|---|---|
| `*` | Every currently live session. |
| `capability:<tag>` | Every session that advertised that tag when it registered. |
| anything else | A case-insensitive substring match against sessions' self-reported scope (what they said they are doing). |

A broadcast fans out to at most 20 recipients, each getting its own message
id. A query matching nobody, or matching more than the cap, is refused
outright rather than delivered to part of the audience — a broadcast that
silently reached half its intended readers is worse than one that visibly
sent nothing.

## 6. Checking, replying, and threads

Delivery is pull, by design: a session calls `messenger_check` to collect
whatever has arrived for its own handle. New items are marked delivered;
items an earlier check already returned and nobody acked since come back
again, listed under `redelivered` — at-least-once, because the hub marks
a message delivered before its reply reaches the client, and a reply lost
to a timeout must not lose the message with it. Only `messenger_ack`
takes a message out of what `messenger_check` returns, so a session that
acts on a message should ack it. An empty result is a normal result, not a
failure — most checks, for most sessions, most of the time, will be empty.

When `expects_reply` is `true`, the receiving session is expected to
either answer it (`messenger_send` with `reply_to` set to the original
message's id) or say plainly that it will not — silence is the one wrong
move, because the sender is specifically waiting. `messenger_thread` reads
a whole back-and-forth by that same `reply_to` chain, not just the latest
message, and `messenger_ack` closes a message once a recipient has
actually dealt with it (acking twice is harmless).

## 7. Authorization: a scope is not an identity

A client needs the `messenger:send` or `messenger:read` scope on its token
to use the messenger at all — an ordinary per-tool permission, enforced the
same way every other palaia tool family enforces one. That answers *may
this client use the messenger*, and nothing more: it does not say which
session is calling.

*Which session is calling* is answered by the session secret
`directory_register` returned, passed on every `messenger_*` call
alongside the caller's handle. A scope alone must never be enough to read
another session's messages — that is what the secret is for, and it is
never re-minted: one registration, one secret, reused for every messenger
call that registration ever makes. Two different sessions can hold tokens
with identical scopes and still be unable to read each other's messages;
that is the property this design exists to guarantee.

A session that stops heartbeating disappears from the directory after five
of its TTLs, but its handle and secret keep working for `messenger_check`
and `messenger_ack` for another seven days — as long as any message it was
sent can live — and a heartbeat brings the session back. Nobody can send it
anything new in between: an unlisted session is an unknown recipient.

## 8. Push adapters (beyond polling)

Pull (`messenger_check`) is the universal baseline — nothing about it
depends on the calling client. Two adapters exist on top of it, so a
message's arrival can also reach somewhere other than the next poll:

- **Outbound webhook on `message.received`.** No new mechanism: the hub's
  existing webhook management (`docs/events.md` §4) already matches a hook
  against any event name on the bus, and the messenger already publishes
  `message.received` there (metadata only — see `docs/events.md` §3.7).
  Registering one is exactly registering any other hook:

  ```bash
  curl -X POST http://<hub>/api/hooks \
    -H 'Content-Type: application/json' \
    -d '{"url": "https://my-other-tooling.example/webhook", "events": ["message.received"]}'
  ```

  The response's `secret` signs every delivery (`X-Palaia-Signature`) —
  store it once, it is not shown again. From there, delivery is signed,
  retried and dead-lettered exactly like every other webhook (§4 of
  `docs/events.md`); nothing about the message pipeline is special-cased.
  `server/tests/messenger/test_push_recipe.py` runs this recipe against a
  real local receiver as the SPEC-404 acceptance evidence: two sessions
  exchange a message, and the webhook fires with a signature that verifies
  and a payload that carries the same metadata as the bus event — no body,
  ever.

- **Claude Code's `claude/channel` capability — not verified here.** Claude
  Code documents an MCP-server capability that can push an event into an
  already-open session rather than waiting for it to poll (the research
  dossier names this as a live precedent for exactly this use case). This
  hub does not implement it, and this repository does not claim to have
  exercised it: the pinned `fastmcp` 3.4.7 has no support for declaring it,
  making it would mean hand-rolling a capability outside any documented,
  version-pinned surface this project relies on elsewhere, and doing that
  without being able to verify the exact wire behavior against a real
  Claude Code session would be worse than not shipping it. The integration
  path, for whoever picks this up once `fastmcp` (or a raw MCP transport
  layer alongside it) supports declaring the capability: the messenger's
  own `message.received` event already carries everything a push needs
  (§3.7 of `docs/events.md`) — the missing piece is purely the transport
  announcement, not new domain logic.

## 9. See also

- [SPEC-403](../specs/SPEC-403-messenger.md) — the envelope's normative
  definition and the hub-side store/authorization contract.
- [`docs/events.md` §3.6/§3.7](events.md) — the `session.*`/`message.*`
  events this contract's checking and replying produce on the bus, for
  automations and webhooks.
- [`v3/clients/skills/palaia-messenger`](../clients/skills/palaia-messenger/SKILL.md)
  — the habits (register on start, check before starting work, reply or
  decline, keep it short) written for a model to actually follow, rather
  than read about.
