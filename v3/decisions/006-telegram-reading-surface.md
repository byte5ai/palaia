# ADR-006: Reading Telegram traffic — routed destinations, not an MCP App channel view

- **Status:** Accepted
- **Date:** 2026-09-20
- **Deciders:** Claude (issue #411 implementation), for owner review

## Context

MASTERPLAN §4 rule 8 makes the question mandatory, not optional: for every
user-facing feature, the design review must ask whether an in-client MCP App
surface (§5.7) is the right way to deliver it — and record the answer. Issue
#411 asks it explicitly for one half of the Telegram connector: **reading**
inbound traffic.

The shape of the thing is genuinely app-friendly. A Telegram channel is a
scrolling list of messages from named people, with threads; §5.7's own
argument for the recall explorer ("explore-then-select: only picked notes
enter context") applies almost word for word to a channel view. A panel
showing the last fifty messages in `#ops`, with a checkbox per message and a
reply box, is an obvious thing to want, and every host palaia targets can
render it.

Three constraints push the other way.

1. **Inbound Telegram traffic is untrusted input aimed at a model.** Anyone
   who can write into a group the bot is in can put text in front of an agent.
   A destination the operator configured — an envelope to a named recipient, a
   note in `inbox/` awaiting curation — is a place where that text arrives
   *already labelled as somebody else's words*, through a surface whose whole
   design assumes it. A channel panel that an agent opens on its own initiative
   inverts that: the agent goes and fetches arbitrary text, and the framing
   has to be re-established every time.
2. **A reading tool is a polling tool.** For an agent to read a panel, the
   connector needs a "give me recent messages" call, which means the hub keeps
   a message store, which means a second copy of a conversation that already
   lives in Telegram — with its own retention question, its own backup row,
   and its own place in the threat model. The issue's own framing avoids this:
   "inbound messages reach agents through the messenger/inbox/event
   destinations above rather than through polling tools."
3. **The destinations already exist and are already good.** SPEC-403's
   messenger is a working inbox with delivery state and threading; the vault's
   `inbox/` is a working capture queue with a curator behind it; the event bus
   is a working trigger. A channel view is a fourth way to read the same
   traffic, and MASTERPLAN §4's UX rules do not ask for a fourth way — §5.7's
   own division of labour is "apps put palaia's *content* where the user
   already is", and for Telegram the user is already in Telegram.

## Decision

**Inbound Telegram traffic is read through the routing table's destinations
only. This connector ships no tool that reads messages, and no MCP App
channel view.** The tool family is outbound plus discovery:
`telegram_send`, `telegram_reply`, `telegram_edit`, `telegram_delete`,
`telegram_list_chats`.

The *owner-facing* view — per bot: connection state, last update received,
routing table, recent deliveries — is a dashboard panel, which is where
system administration lives (§5.7: "the dashboard administers the system").
It is named as follow-up work in issue #411 and is not part of the first cut.

## Alternatives considered

- **An MCP App channel view (`telegram_channel`), read-only.** The strongest
  option, and the one this ADR exists to answer. Deferred rather than
  rejected outright: it needs a message store first (see constraint 2), and
  the store is a design decision of its own — retention, per-chat access,
  backup, and a threat-model row about the hub keeping a searchable copy of
  the operator's private chats. Revisit once a real operator says the routed
  destinations are not enough; the tool family's naming leaves room
  (`telegram_channel` is unused).
- **A `telegram_recent(chat, limit)` tool with no app.** All of the storage
  cost, none of the selective-context benefit that makes an app worth it, and
  it turns the connector into a polling surface for arbitrary third-party
  text. The worst of both.
- **An app for the *outbound* side — a compose-and-confirm panel.** Genuinely
  attractive: "here is what I am about to send to a human, press send". Not
  taken now because the confirmation that matters is the operator's grant
  (`telegram.grants`, default-deny), which is a configuration decision made
  once rather than a per-message dialog, and because a per-send confirmation
  panel with no one watching the chat is a prompt that blocks forever. Worth
  revisiting alongside the dashboard panel.

## Consequences

- **Easier:** no message store, so no retention policy, no backup row, no
  "the hub keeps a copy of your private chats" line in the threat model. The
  connector's inbound half is stateless apart from a poll offset.
- **Easier:** untrusted third-party text arrives only where a human wrote a
  rule saying it should, in a surface built for other people's words.
- **Harder:** an agent cannot look back at what was said before the message
  it was handed. It has what the routing destination gave it and nothing
  else; a conversation's history has to come from the destination (a
  messenger thread, a vault note) rather than from Telegram.
- **Harder:** answering "what did they say yesterday?" means opening
  Telegram. Accepted — that is where the conversation is.
- **Follow-up created:** the dashboard panel (issue #411's own acceptance
  list) and, if the read case turns out to be real, a message store plus the
  channel-view app this ADR defers.
