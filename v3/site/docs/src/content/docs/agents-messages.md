---
title: Agents & messages
description: See which AI sessions are active right now, and let them hand work to each other through your memory.
---

Your memory isn't only a place things get saved — connected AI sessions can
also see each other and pass work along, with you able to watch, join in,
or shut any of it down at any point. This page covers both halves.

## Who's active right now

The dashboard's "Agents" screen lists every AI session currently connected
— which tool, which memory it's working in, and how long since it last did
anything. A session that's gone quiet for a while is marked as gone stale
rather than left looking active forever.

<!-- screenshot: the Agents screen, live directory on the left, message
     flows on the right -->

## Letting sessions hand work to each other

A session can look for another active one that matches what it needs — "an
assistant already working on the release" rather than a name it was told in
advance — and send it a short message: a question, a status update, an
actual handoff of work. Long content never travels inside the message
itself; instead the message points at where the detail already lives in
your memory, so the receiving session reads the full thing from the one
place it's kept rather than from a copy that can drift out of date.

You see this traffic in the same Agents screen, one thread per
conversation between two sessions, headline first and the full text
available on request — this is an administrator-only view; the sessions
themselves don't see each other's full history, only what was actually
addressed to them.

## What you can do about it

Three controls, always available from the same screen:

- **End a conversation** — nothing further gets delivered on that thread,
  immediately.
- **Disconnect a session** that's gone stale or should not have access
  anymore.
- **Send a message yourself**, as the administrator, into any active
  conversation — the same short-form message a session would send, filled
  out through a form rather than typed as commands.

These three stay dashboard-only on purpose — they're the kind of action
that should always go through a screen you had to sign in to reach, never
through a chat message alone. A read-only version of the same view is also
available from inside a chat client that supports it, for glancing at
what's going on without switching to the dashboard; anything that changes
something still has to happen from the dashboard itself.
