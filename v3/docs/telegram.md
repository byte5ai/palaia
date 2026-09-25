# palaia Telegram connector — setup, routing and permissions

> A hub-side channel between the people who own it and the agents that work
> for them. One hub serves several bots; each bot's traffic is routed by
> *where it came from* to one of the hub's existing surfaces; agents send
> back through MCP tools, fenced per profile. The design decision behind
> "there is no tool that reads Telegram" is
> [ADR-006](../decisions/006-telegram-reading-surface.md).
>
> Status: first cut (issue #411), running in the hub since issue #439, and
> set up from the dashboard since issue #463: the **Telegram** screen adds,
> changes and removes bots, routing rules and send permissions, stores a
> bot's token, and applies every change to the running hub — no restart,
> no hand-editing `config.yaml` (§8). The hub starts one long-poll task per
> polling bot, mounts the webhook route and gives `telegram: true` profiles
> the tools. Text messages only — media is recorded as a *reference* and
> not downloaded.

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

Everything in this section is done on the dashboard's **Telegram** screen
(§8). The configuration it writes is shown in §3, for reference and for
anyone who prefers the file.

### 2.1 Create the bot and store its token

Talk to [@BotFather](https://t.me/botfather) in Telegram, create a bot, copy
the token it gives you. On the **Telegram** screen, **Add a bot**: give it a
short name on the hub (`support` — what rules and agents call it), and paste
the token into **Bot token**. The token goes into the hub's encrypted secret
store — **never into `config.yaml`**, which only names the secret it is
filed under (`telegram_<name>` unless you choose another). Then **Check
connection**: Telegram answers with the bot's `@username`, or with why it
refused the token.

Without the dashboard, the same two steps are the secret store's write-only
route and the `telegram:` section of §3:

```
PUT /api/secrets/telegram_support      {"value": "123456789:AA…"}
```

The token lives encrypted under `<home>/secrets.sqlite3`.

### 2.2 Let the bot see messages

By default a bot in a group only receives messages that mention it. To have
it receive everything in a group or channel, turn **Group Privacy** off in
BotFather (`/setprivacy`) and add the bot to the chat. For a channel, add it
as an administrator.

### 2.3 Find the chat id

Send one message to the chat, then open the dashboard's **Telegram** screen:
under *Recent messages* the message shows as "No rule matched", followed by
the exact `chat:` values a route could use — the numeric chat id first (the
same keys are in the hub's `telegram.message.dropped` event). Click one and
the rule editor opens with the bot and that chat filled in: pick where its
messages go and save, and the next message follows the rule. Group and
channel ids are negative — `-1001234567890` — which is normal.

## 3. Configuration

This is the `telegram:` section the dashboard writes (§8) — or that you can
write by hand:

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

**Changes made on the dashboard apply at once; hand edits on restart.** The
Telegram screen writes each change to this section and hands it to the
running connector in the same step (§8): a new polling bot starts polling, a
removed or switched-off one stops, and the next message meets the new rules.
Editing `config.yaml` by hand is still possible, but the hub reads the file
once, when it starts — a hand edit applies after a restart. What is fixed at
startup either way is the set of vaults an `inbox` route can deliver into: a
vault created later, through the wizard, is reachable by such a route after
a restart. For every part of the section it can already tell will not work —
an `inbox` route to a vault it does not have, a `messenger` route on a hub
with no messenger, a webhook bot on a `locked` hub — the hub logs a warning
at startup, and the dashboard shows the same list after every save; the
rest runs.

A hub with no `telegram:` section at all runs an empty connector: no bot, so
nothing polls, every webhook address answers `404`, and a `telegram: true`
profile's tools list no chat and can send nowhere. The section appears the
first time a bot is added on the dashboard.

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
handle can collide with. Read it as "relayed by the owner's routing rule",
not "written by the owner": in a group the words may be anyone's, which is
why the body opens with who wrote them.

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
   says whether this client may use the connector at all. A token the
   dashboard issues for a `telegram: true` profile carries both, the same
   way it carries a vault's read/write pair.
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
`POST /telegram/webhook/<bot key>`. A webhook bot on a `locked` hub can never
receive anything — Telegram has no public URL to push to — so the hub logs a
warning for it at startup; use polling there. Set up:

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

Reaching the route from the internet:

- **The packaged image** proxies `/telegram/` to the hub, next to `/api`,
  `/mcp` and `/oauth` — the dashboard's static files never answer it.
- **`cloud` mode** keeps everything but the MCP endpoint and its sign-in
  pages off the tunnel. Once `config.yaml` has an enabled webhook bot, the
  exposure wizard's tunnel guidance (Tailscale and cloudflared) forwards
  `/telegram/webhook` as well; without one it does not. In `open` mode the
  whole hub is public already.
- **Guessing the secret is throttled** in `cloud`/`open`: every `401` from
  this route counts against the caller in one bucket shared by all bot
  keys, like a guessed sign-in, and after 10 in a minute that caller gets
  `429`. Telegram's own deliveries succeed, never count, and are never
  slowed by somebody else's guessing.

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
| `telegram.message.handled` | Message metadata + routed, destination, delivered | After delivery, once the outcome is recorded for the dashboard. **No text.** |
| `telegram.bot.state` | Bot, `ok` or `failing`, the error line | A polling bot's first answer or first failure, then each time it starts failing or recovers — once per change, not per poll. **No token.** |
| `telegram.config.updated` | What changed (`bot`, `route` or `grant`), how, and its key | After every change saved on the dashboard (§8). **No token, no secret name.** |

The rule and its one exception: a human's words do not go on the event bus,
because the bus feeds every SSE listener and every outbound webhook this hub
is configured with — the same reason SPEC-403 keeps message bodies off it.
`telegram.routed` breaks that rule on purpose, because an operator who wrote
`kind: event` asked for exactly this. If you want a message to trigger an
automation without putting its text on the bus, route it to `inbox` or
`messenger` and have the automation trigger on
`telegram.message.received` instead.

## 8. The dashboard

The dashboard's **Telegram** screen (under *Connections*) is where the owner
sets the connector up and sees it at work — a dashboard screen, not
something an agent can read or change (ADR-006, and MASTERPLAN §4 rule 8:
this is administration):

- **Bots** — per bot: *Connected*, *Failing* (with the last error),
  *Not checked yet*, *Disabled* or *Token missing*; when it last received a
  message; and a **Check connection** button, which asks Telegram whether
  the token works (`getMe`) and is the only thing on the screen that calls
  Telegram at all. **Add a bot**, **Edit** (display name, how messages
  reach the hub, switched on or off, a new token or delivery secret) and
  **Remove**. A bot's name on the hub cannot change — rules, grants and
  agents address it by that name. A bot still named by a rule or a grant
  cannot be removed until those are; switching it off keeps them. Its
  stored token stays in the secret store.
- **Where messages go** — the routing table (§4), in plain words, with
  **Add a rule**, **Edit** and **Remove**.
- **Who may send** — the grants of §5: which tool profiles may send,
  through which bots, to which chats. A profile with no entry sends
  nothing. The curator cannot be given one. The **Tool profiles** screen
  has the matching switch that gives a profile the tools in the first
  place.
- **Recent messages** — the last 50 across every bot, newest first: which
  bot, which chat, how long, and whether it was delivered, failed (with the
  kind of error — the hub log has the rest, since an error can quote the
  message), or matched no rule (with the `chat:` values a rule could use —
  click one to write that rule, see §2.3).

Every save is checked the way the hub checks `config.yaml` when it loads —
a rule naming a bot that does not exist is refused, and so is a webhook bot
without its delivery secret — then written to `config.yaml` (only the
`telegram:` section is rewritten; the rest of the file, comments included,
is left as it was), then applied to the running hub. The token never passes
through any of it: the screen stores it with the secret store's write-only
`PUT /api/secrets/<name>`, and storing one wakes a bot that was waiting for
it instead of leaving it to retry up to a minute later.

It keeps **metadata only, in memory**: no message text is ever stored or
shown, and everything on the screen starts over when the hub restarts. It
updates live off the `telegram.*` events in §7 — `telegram.message.handled`
once each outcome is recorded, and `telegram.bot.state`, which is how a bot
turns green on its first answer or red when it starts failing, without a
reload. Behind it: `GET /api/telegram/status`,
`POST /api/telegram/bots/<key>/check`, and the editor's
`POST /api/telegram/bots`, `PATCH`/`DELETE /api/telegram/bots/<key>`,
`POST /api/telegram/routes`, `PUT`/`DELETE /api/telegram/routes/<bot>/<chat>`
and `PUT`/`DELETE /api/telegram/grants/<profile>` — each answering with the
new status — owner-only like the rest of `/api/`.

## 9. The token, and where it is not

- Not in `config.yaml`: a bot names a *secret*, and the model has no field a
  token could be written into (an extra key is refused).
- Not in logs: a Telegram token travels in the URL *path*
  (`/bot<token>/sendMessage`), which the hub's other redaction patterns do
  not look at. `palaia_hub.logging` matches its shape, and the Bot API client
  scrubs it again before raising — an API error names the *method*, never the
  URL.
- Not in tool output: no result model has a field for it.
- Not in the dashboard's editor: no request to `/api/telegram` has a field
  for it — one that tries is refused, not silently dropped — and no answer
  or `telegram.config.updated` event carries it.

## 10. Not in this first cut

- **Media**: attachments are recorded as references (`file_id`, name, size)
  and passed into the destination as text. Nothing is downloaded or uploaded.
- **Telegram login** for hub access: out of scope — the hub's own sign-in is
  unchanged.
- **Group administration**: out of scope, and actively fenced off (§5).
