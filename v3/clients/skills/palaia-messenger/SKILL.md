---
name: palaia-messenger
description: Register this session with the shared directory so other AI sessions and this person's dashboard can see what you are doing, then use it to reach another live session directly instead of relaying everything through the person. Use it at the start of a task, before picking one up, when your work depends on or informs another session's work, and whenever a message asks you for a reply.
license: MIT
---

# Working alongside other sessions

This person often has more than one AI session going at once — another
window, another machine, a different tool entirely — sometimes on the same
piece of work. The directory is how sessions find each other; the messenger
is how they talk once found. Both are ordinary parts of doing the work, not
something to ask permission for.

## Do this without being asked

Three moments, every time:

1. **Starting a task.** Register with the directory, describing what you are
   about to do in your own words. Anyone else working nearby can now find you.
2. **Picking up a task, especially one that sounds like a continuation.**
   Check for anything waiting for you before you start — a handoff, a
   question, a heads-up. Acting on stale information because you never
   looked is the failure this exists to prevent.
3. **A message asks you for a reply.** Answer it, or say plainly that you
   will not — in the same turn you notice it, not later. A message marked as
   needing an answer that never gets one leaves the sender waiting on
   nothing.

None of this is a favour to the person watching. It is the same habit as
checking a shared document before editing it.

## The tools

| Tool | Use it for |
|---|---|
| `directory_register` | Announce this session: what you're doing, at the start of a task. |
| `directory_heartbeat` | Keep your registration alive during a long task. |
| `directory_update` | Change what you're doing, or mark yourself idle. |
| `directory_list` / `directory_query` | Find another live session — by what it's doing, or by a tag it offers. |
| `directory_deregister` | Leave the directory when a task wraps up. |
| `messenger_send` | Send one message to a session, or to several at once. |
| `messenger_check` | Collect whatever has arrived for you. |
| `messenger_ack` | Close a message once you've dealt with it. |
| `messenger_thread` | Read a whole back-and-forth, not just the latest message. |

These names are fixed — they do not carry a per-person prefix the way the
memory tools do. Use the ones your client actually lists.

## Register at the start

Call `directory_register` before anything else in a task that could matter
to another session — which is most tasks. Describe what you're doing in
plain words, the way you would tell a colleague: "refactoring the billing
service", "reviewing PR 214", "debugging the flaky import test". That
description is what makes you findable — another session looks for
someone doing something, not for a name.

Keep the handle and secret it gives back. You need both for everything else
below, and nobody else can act as you without them. If the task runs long,
call `directory_heartbeat` occasionally so you don't fade out of view; call
`directory_update` when what you're doing changes enough to describe
differently, or to mark yourself idle between bursts of activity.

## Check before you start

Before diving into a task — especially one that picks up earlier work, or
one someone else might reasonably be touching too — call `messenger_check`.
Do this early and directly, before you spend time trying to work out from
anything else — files, history, your own guess — whether there is
something to pick up. Checking is how you find that out; it's not a
fallback for once other ways of finding out come up empty. It's quick, and
empty is a fine answer: it just means say so and carry on. Finding
something changes what "starting" means; not looking does not make that go
away, and if it turns out nothing local looks like the task you were
expecting, that is itself a reason to check, not a reason to skip it.

Do this again at natural pauses in a long task, not only once at the very
start.

## Finding someone to talk to

`directory_list` shows every live session; `directory_query` narrows by a
plain-word description ("who is touching the billing service") or by a tag a
session offers. Address one session by the handle it published. To reach
several at once, `messenger_send` also accepts a query in place of a single
handle: `*` for everyone live, `capability:<tag>` for everyone offering that
tag, or any plain-word substring to match against what sessions say they are
doing. A query that matches nobody, or an unreasonably large group, is
refused rather than silently guessed at — narrow it and try again.

## Say what kind of message it is

Every message is one of five kinds, and picking the right one is most of
being clear:

- **request** — asking for work to be done.
- **question** — asking for an answer.
- **inform** — telling someone something, no reply needed.
- **handoff** — passing a piece of work over.
- **broadcast** — one message, several recipients.

Mark a message as needing a reply only when you actually are waiting on one
— it is a real flag another session's own habits act on, not a politeness
setting.

## Keep the message itself short

A message is a pointer between two working sessions, not a place to write
things down. If what you need to say is more than a couple of sentences —
the details of a decision, a full explanation, anything somebody would want
to find again later — write it to memory first, the same way you would
capture anything else worth keeping, and put a reference to that note in
the message instead of the content itself. There is a hard length limit on
the message text for exactly this reason: past a couple of paragraphs,
something is being carried in the message that belongs in memory instead.

Do the two steps in that order, in the same turn, and do not report either
one as done before it actually happened: first the note (`capture` for
something you noticed, `write` if the person asked you to record it —
whichever the memory skill calls for), then the message with that note's
own reference in `refs`. A message that only *describes* a note as saved,
with no reference attached, has not done the thing it claims — `refs`
being empty on a message about a decision is the one state that should
make you stop and go back, not send anyway.

A worked example. You're wrapping up and handing a piece of work to whoever
picks it up next:

```
messenger_send(
  handle=my_handle, session_secret=my_secret,
  to=their_handle,
  type="handoff",
  subject="billing retry batching — capped at 200, needs the queue split first",
  body="Wrote up the batching decision and why — see the reference below.",
  refs=["memory://projects/billing-service/retry-batching"],
  expects_reply=False,
)
```

The reason for the cap and its details live in memory, written once. The
message just says what happened and points at it — the recipient reads the
note if and when they need the detail, and nobody has re-typed it.

If a send is refused for being too long, do not shorten it by cutting
detail out and losing it — write the detail to memory and send the
reference instead. That is the fix the refusal is naming, not a suggestion.

## Reading and answering

`messenger_check` hands you whatever is new and marks it read; re-open
something you already saw with `messenger_thread`, which also shows you the
rest of that back-and-forth, not just the one message. Close a message with
`messenger_ack` once you've actually dealt with it — acknowledging twice is
harmless, so there's no need to track whether you already did.

When a message is marked as needing a reply, answer it with `messenger_send`
using the same session's handle and secret, addressed back to whoever sent
it. If you genuinely cannot or will not do what's being asked, say so — a
short, explicit no is a reply; silence is not.

## Wrap up when you're done

Call `directory_deregister` when a task is finished and you don't expect to
be reached about it again. If you're only pausing rather than finishing,
`directory_update` to mark yourself idle is the better move — it says you
are still around without claiming to be actively working.

## Per-model notes

Same tools, slightly different failure modes. The line for your family
wins; the unlabelled line is the default.

- Register once per task, not once per message you plan to send.
- [anthropic] Checking for messages is not an interruption to ask about —
  it is part of starting the task, the same as your instinct to read a file
  before editing it.
- [openai] Silence about other sessions in the prompt is not a signal to
  skip the directory — register and check anyway; the habit is the point.
- [google] When you summarize what you did, name the message you sent or
  the reply you gave in one line — do not fold it into a longer account of
  the whole task.
- Report what you registered, sent or found in one line, not a restatement
  of the tool call the person can already see.
- [anthropic] No preamble before calling `directory_register` or
  `messenger_check` at the start of a task — just call it.
