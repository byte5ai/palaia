---
title: Profiles & access
description: How far your memory reaches, who can sign in, and what each connected tool is actually allowed to do.
---

Three separate questions live under this page, and it helps to keep them
separate: **where** your hub can be reached from, **who** can sign in to
manage it, and **what** each individual connected tool is allowed to do
once it's in.

## Where your hub can be reached from

Set during the first-run setup, and changeable later from the dashboard's
access page:

- **Just this device or network.** Nothing outside your own network can
  reach it, full stop. This is the safe default, and the right choice if
  every AI tool you use also runs on your own machine or network.
- **Reachable from the internet, sign-in required.** For tools that connect
  from a company's own service rather than from your device — a phone app,
  a web-based assistant — which need an address they can actually reach.
  Sign-in turns on the moment this does; there is no way to expose your
  memory to the internet without it.
- **Reachable from the internet, dashboard included.** The same as above,
  plus the management dashboard itself is reachable too, not just your
  memory's connection point. A stricter checklist runs before this is
  allowed, and it's the right choice for fewer situations than the option
  above — most people who want to reach their memory from the internet
  don't also need the dashboard exposed.

Whichever you pick, [Connect your AI](/connect/) tells you, per tool,
exactly what's needed for that specific tool to reach you — some need
nothing more than "just this device," others need the internet-reachable
option turned on.

## Who can sign in

The dashboard itself — the screen where you browse your memory, approve
proposals, add tools, and change any of this — has its own sign-in,
separate from anything an AI tool uses to connect. One person is set up as
the administrator during first-run setup; more can be added from the
dashboard's own settings if more than one person manages the same hub.

## What each connected tool can do

Every AI tool you connect gets its own named connection — "Claude Code on
my laptop," "the office assistant" — rather than one shared password
everyone uses. Each one can be limited to exactly what it needs:

- Which memory or memories it can see, if you keep more than one.
- Whether it can only look things up, or also save and change things.

<!-- screenshot: the connected-clients list, showing each tool's name, last
     activity, and read/write access -->

This matters most when a tool sits somewhere less trusted than your own
laptop — a shared service, something you're trying out — where you'd
rather it could look things up but never write anything. Revoking one
connection takes effect immediately and doesn't touch any of the others.

## If something looks wrong

A tool's connection status is checked independently by that tool and by
your hub, and the two checks don't always agree at the exact moment you
sign in — a tool can briefly report "not connected" right before it
actually connects successfully. [Troubleshooting & FAQ](/troubleshooting/)
covers this and the other rough edges worth knowing about up front.
