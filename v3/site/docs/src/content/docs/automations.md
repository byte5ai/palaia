---
title: Automations
description: "When this happens, do that — small rules that react to what's going on in your memory, no typing required."
---

An automation is a plain "when this happens, then do that" rule, set up
from a form in the dashboard — nothing here requires writing code.

## The shape of a rule

Every automation has the same three parts:

1. **When** — something that happened. A new note was saved, a proposal
   showed up waiting for your approval, a specific kind of activity
   occurred.
2. **If** — an optional narrowing condition, so the rule only fires for the
   cases you actually care about (only for one particular memory, say, or
   only when a saved note is tagged a certain way).
3. **Then** — what happens: a message sent somewhere outside palaia, a
   quick note saved automatically, or a notification shown in the
   dashboard itself.

<!-- screenshot: the automations editor, three cards (when / if / then)
     stacked in a rule -->

## A few to start from

The automations screen offers a handful of ready-made rules on an empty
list — "notify me when something needs my approval," for instance. Picking
one fills in the editor with it already built; nothing runs until you
review and save it yourself.

## Trying a rule before it's live

Every rule has a test button that fires it once, right now, with made-up
data standing in for a real event — useful for checking that the "then"
part does what you expect before it's watching for anything real. Every
time a rule actually fires, live or as a test, it's logged with the
outcome, so you can tell at a glance whether a rule you set up a while ago
is still doing anything.
