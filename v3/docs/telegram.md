# palaia Telegram connector — setup, routing and permissions

> A hub-side channel between the people who own it and the agents that work
> for them. One hub serves several bots; each bot's traffic is routed by
> *where it came from* to one of the hub's existing surfaces; agents send
> back through MCP tools, fenced per profile. The design decision behind
> "there is no tool that reads Telegram" is
> [ADR-006](../decisions/006-telegram-reading-surface.md).
>
> Status: first cut (issue #411). Text messages only — media is recorded as
> a *reference* and not downloaded. The per-bot dashboard panel and the
> runtime wiring that starts the poller are named follow-ups; see §9.

## 1. What it does, in one picture

```
        a person, on their phone
                  │
           Telegram bot "support"
                  │  long poll (default) or webhook
                  ▼
   ┌──────────────────────────────┐
   │  normalise → route → deliver │      routing key: (bot, chat)
   └──────────────────────────────┘
        │             │           │
   messenger      vault inbox/   hub event
   envelope        capture       (→ automations)
```

and back the other way:

```
   agent  ──telegram_send/telegram_reply──▶  grant check  ──▶  Telegram
                                            (per MCP profile,
                                             default-deny)
```

## 2. Setup

### 2.1 Create the bot and store its token

Talk to [@BotFather](https://t.me/botfather) in Telegram, create a bot, copy
the token it gives you. Then store it in the hub's encrypted secret store —
**never in `config.yaml`**:

```
PUT /api/secrets/telegram_support      {"value": "123456789:AA…"}
```

(Dashboard: Settings → Secrets.) The token lives encrypted under
`<home>/secrets.sqlite3`; the config below names the *secret*, not the value.

### 2.2 Let the bot see messages

By default a bot in a group only receives messages that mention it. To have
it receive everything in a group or channel, turn **Group Privacy** off in
BotFather (`/setprivacy`) and add the bot to the chat. For a channel, add it
as an administrator.

### 2.3 Find the chat id

Send one message to the chat, then look at the hub's
`telegram.message.dropped` event (or the log line next to it): it prints the
numeric chat id and the exact `chat:` values a route could use. Group and
channel ids are negative — `-1001234567890` — which is normal.

## 3. Configuration

```yaml
telegram:
  bots:
    - key: support                      # the hub's own name for this bot
      token_secret: telegram_support    # a secret NAME, never the token
      label: Support bot
      transport: polling                # polling (default) | webhook
    - key: personal
      token_secret: telegram_personal

  routes:
    # everything through "support" in the ops channel → an agent's inbox
    - bot: support
      chat: "-1001234567890"
      destination:
        kind: messenger
        to: ops-agent                   # a session handle, or a broadcast query
        message_type: inform            # request|inform|question|handoff|broadcast
        urgency: normal
    # anything else through "support" → a note in the work vault's inbox/
    - bot: support
      chat: "*"
      destination:
        kind: inbox
        vault: work
    # the personal bot's direct chat → a hub event, which automations see
    - bot: personal
      chat: "987654321"
      destination:
        kind: event
        label: personal-dm

  grants:
    # which MCP profile may send, through which bots, to which chats
    - profile: default
      bots: [support]
      chats: ["-1001234567890"]

  poll_timeout_seconds: 30
```

And on the profile that should get the tools:

```yaml
gateway:
  profiles:
    - path: default
      vaults: [work]
      telegram: true
```

A cross-reference that does not resolve — a route naming a bot that is not
configured — is refused when the hub loads the file, not silently ignored.
A rule that can never match is the worst thing a routing table can contain.

## 4. The routing table

The key is `(bot, chat)`. For each inbound message three chat keys are tried,
**most specific first**:

1. the numeric chat id (`-1001234567890`)
2. the chat's public `@name`, when it has one (case-insensitive)
3. `*` — every chat this bot receives from

The first rule that exists wins. **Order in `config.yaml` does not matter**:
an operator who appends a catch-all to the bottom of the file and one who
puts it at the top get the same delivery.

A wildcard is a wildcard over *chats within one bot*. It never reaches across
bots — that is the whole point of the `(bot, chat)` key, and it is what lets
the same chat id mean different things through two different bots.

Nothing matched? The message is dropped, a `telegram.message.dropped` event
fires naming the three keys that *would* have matched, and the poll offset
advances anyway. Dropped is a normal outcome, not an error.

### Destinations

| `kind` | Lands in | Needs |
|---|---|---|
| `messenger` | A [messenger](messenger.md) envelope, sent **as the owner** to `to` | `to` |
| `inbox` | A capture in that vault's `inbox/`, for the curator | `vault` |
| `event` | A `telegram.routed` event on the hub's bus | — (optional `label`) |

There is no `kind: automation`. Automations fire off hub events, so
`kind: event` *is* how a Telegram message triggers one.

Why "as the owner" for a messenger route: the person who typed the message
is the hub's owner or someone talking to them, and neither has a session
handle to speak from. The envelope's `from` is `owner`, which no agent
handle can collide with.

## 5. Sending: the tools, and what they may do

| Tool | Does | Scope |
|---|---|---|
| `telegram_list_chats` | Every `(bot, chat)` this profile can see, where its inbound traffic goes, and whether this profile may send there | `telegram:read` |
| `telegram_send` | Send text | `telegram:send` |
| `telegram_reply` | Send text threaded under an existing message | `telegram:send` |
| `telegram_edit` | Replace the text of a message *this profile* sent | `telegram:send` |
| `telegram_delete` | Delete a message *this profile* sent | `telegram:send` |

There is deliberately **no tool that reads inbound messages** — see
[ADR-006](../decisions/006-telegram-reading-surface.md).

**Two independent fences, and both must pass.**

1. The **scope** on the client's token (`telegram:read` / `telegram:send`)
   says whether this client may use the connector at all.
2. The **grant** (`telegram.grants`) says which bots and chats this *profile*
   may address. It is **default-deny**: a profile with the tools mounted, a
   valid token and no grant entry sends nothing, and is refused by name.

The deny is at the level of the entry, not the fields. `- profile: default`
on its own means "every configured bot, every chat" — that is what an
operator who named the profile and nothing else meant. Narrow by listing
(`bots: [support]`, `chats: ["-1001234567890"]`); an explicit empty list
(`chats: []`) denies everything, which is how a profile is switched off
without deleting its entry.

The profile is fixed when the tool server is built — it is not a tool
argument and cannot be supplied by a caller.

**Edit and delete are fenced to this hub's own messages.** Telegram would let
a bot that administrates a group delete a member's message; that is group
moderation, which this connector does not do. A message sent before the hub
last restarted is also no longer tracked (the ledger is in memory and
bounded) and gets the same refusal, with the reason stated.

**The curator profile can never carry these tools.** It runs a model over
your notes unattended; a channel to people outside the hub is an
exfiltration path with a delivery receipt. Refused in the schema and again
at mount time.

## 6. Transports

**Long polling (the default).** An outbound HTTPS request that Telegram
holds open. Works behind NAT, works in `locked` mode, needs no public URL
and no certificate. A failed poll backs off (1s, doubling, capped at 60s)
and retries — the loop does not end.

**Webhook (opt-in, `cloud`/`open` hubs).** Telegram pushes to
`POST /telegram/webhook/<bot key>`. Set up:

1. Store a random value as a secret, e.g. `telegram_support_hook`.
2. Name it in the bot's `webhook_secret`, and set `transport: webhook`.
3. Call Telegram's `setWebhook` with `url` = your public hub URL +
   `/telegram/webhook/support` and `secret_token` = **the same value**.

Telegram then echoes that value in an `X-Telegram-Bot-Api-Secret-Token`
header on every delivery, and the hub compares it in constant time. The URL
is *not* a secret — it contains the bot key, which appears in `config.yaml`,
logs and the dashboard — so that header is the endpoint's only credential.
A webhook bot with no `webhook_secret` is refused by the config schema, and
one whose secret store entry is empty answers `503` rather than accepting an
unverified update.

Both transports run the same code after the update arrives. An update that
was received but could not be delivered still answers `200`: Telegram retries
anything else, and a hub-side failure must not become a redelivery loop.

## 7. Events

| Event | Carries | Note |
|---|---|---|
| `telegram.message.received` | Message metadata | Every inbound message, routed or not. **No text.** |
| `telegram.message.dropped` | Message metadata + the chat keys that would have matched | No route claimed it |
| `telegram.message.sent` | Bot, chat, message id, sending profile | **No text.** |
| `telegram.routed` | Message metadata **+ the text** | Only from a `kind: event` route |

The rule and its one exception: a human's words do not go on the event bus,
because the bus feeds every SSE listener and every outbound webhook this hub
is configured with — the same reason SPEC-403 keeps message bodies off it.
`telegram.routed` breaks that rule on purpose, because an operator who wrote
`kind: event` asked for exactly this. If you want a message to trigger an
automation without putting its text on the bus, route it to `inbox` or
`messenger` and have the automation trigger on
`telegram.message.received` instead.

## 8. The token, and where it is not

- Not in `config.yaml`: a bot names a *secret*, and the model has no field a
  token could be written into (an extra key is refused).
- Not in logs: a Telegram token travels in the URL *path*
  (`/bot<token>/sendMessage`), which the hub's other redaction patterns do
  not look at. `palaia_hub.logging` matches its shape, and the Bot API client
  scrubs it again before raising — an API error names the *method*, never the
  URL.
- Not in tool output: no result model has a field for it.

## 9. Not in this first cut

- **Media**: attachments are recorded as references (`file_id`, name, size)
  and passed into the destination as text. Nothing is downloaded or uploaded.
- **The dashboard panel**: per-bot connection state, last update received,
  routing table and recent deliveries. The data is all there
  (`check_bot`, the routing table, the events above); the panel is not.
- **Runtime wiring**: the poller and the webhook router are built and
  tested, but `palaia_hub.serve` does not yet start the poll tasks or mount
  the webhook route.
- **Telegram login** for hub access: out of scope — the hub's own sign-in is
  unchanged.
- **Group administration**: out of scope, and actively fenced off (§5).
