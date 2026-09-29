---
title: Telegram
description: Talk to your AI tools through your own Telegram bots, with the hub deciding where each message goes and who may answer.
---

palaia can run your Telegram bots. A message someone sends one of them
reaches the right place on your hub, and your AI tools can answer through
the bot, but only in the chats you allowed. Everything is set up on the
dashboard's **Telegram** screen; you never edit a file or restart the hub
for it.

## What happens to a message

Each bot's messages are sorted by **which chat they came from**. For each
chat (or for "every chat of this bot") you choose where its messages go:

- **to an agent session**, as a message it picks up the next time it
  checks,
- **into one of your memories**, as a note waiting to be filed,
- **as an event**, which can start one of your
  [automations](/automations/).

A message from a chat with no rule is not delivered anywhere. It shows up
under *Recent messages* as "No rule matched", together with the chat keys
a rule could use.

Your AI tools can **not** read your Telegram chats. Messages only reach
them the way you routed them.

## Set up a bot

1. **Create the bot.** In Telegram, talk to
   [@BotFather](https://t.me/botfather), create a bot and copy the token it
   gives you.
2. **Add it on the dashboard.** Open **Telegram**, choose **Add a bot**,
   give it a short name (for example `support`) and paste the token. The
   token is stored encrypted on your hub and is never shown again.
3. **Check the connection.** **Check connection** asks Telegram whether the
   token works and shows the bot's `@username`, or why Telegram refused it.
4. **Let it see the chat.** In a group, a bot only sees messages that
   mention it, unless you turn **Group Privacy** off in BotFather
   (`/setprivacy`). For a channel, add the bot as an administrator.

## Decide where messages go

Send one message to the chat. Under *Recent messages* it appears as "No
rule matched", with the chat's id. Click the id, choose where messages from
that chat should go, and save. The next message follows the rule.

Group and channel ids start with a minus sign (`-1001234567890`); that is
normal. A rule for one exact chat always wins over a rule for "every chat".

## Let an AI tool answer

Sending is **off by default**. Under *Who may send*, choose which tool
profile may send through which bot to which chats. On the **Tool
profiles** screen, the same profile also needs its Telegram switch turned
on. An AI tool can then send, reply to, edit or delete its own messages in
exactly those chats, and nowhere else.

## Keep an eye on it

The Telegram screen shows each bot's state (connected, failing with the
last error, switched off, or missing its token), when it last received a
message, and the last 50 messages across all bots: where each one went, or
why it was not delivered. It never stores or shows the text of a message,
and the list starts over when the hub restarts.
