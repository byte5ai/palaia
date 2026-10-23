---
title: Add-ons
description: Add a new tool to every connected AI app at once, from a browsable catalog with a consent step before anything installs.
---

Your memory is one kind of tool an AI can use. **Add-ons** is where you
add others — a web search, a project tracker, a code runner, anything
someone has packaged for palaia — and the point of adding one here rather
than per app is that every AI app you've connected gets it at once, the same
way they all already share your memory.

## Browsing and installing

The dashboard's **Add-ons** page shows what you have installed first, and
**Browse** lists what's available, each entry showing what it does, who
published it (when that is known), and whether it has been checked over
("Reviewed by palaia" — palaia's own review, not a guarantee about what the
tool itself does once running; everything else is marked "Unreviewed"). Installing one of these never happens silently:
every install shows a plain-language confirmation first — what it is, where
it comes from, and, for anything that runs its own program rather than just
connecting to an address, exactly what it can touch on your machine. You
confirm before anything is added.

<!-- screenshot: the install confirmation screen for a container-based tool,
     showing its declared permissions -->

If a tool needs something from you to work — an account key, a project ID —
the dashboard builds a plain form for it from what the tool declares it
needs. Anything you'd normally call a secret is stored separately and
encrypted; it is never shown back to you, or to the tool that asked for it,
in plain text again.

## A few kinds, one list

Tools arrive in a few different shapes, and the Add-ons page hides the
difference where it can:

- Some connect to an address somewhere else on the internet — installing
  one is just telling your hub where it lives.
- Some run as their own small program alongside your hub, started and
  stopped for you.
- Some are teaching material rather than a running program — a package of
  instructions a client's own AI reads to work better with your memory (the
  same kind of thing described in [Connect your
  AI](/connect/)'s "teach it to look things up and save things on its own"
  sections) — Add-ons lists these too, pointing you at where to add
  them.

Whichever kind, once it's installed it shows up for every AI app whose
connection is allowed to see it.

## Keeping tools current

When a newer version of an installed tool is published, the dashboard shows
an update badge on it rather than updating anything on its own — you decide
when, and the same consent step runs again before anything changes.

## If nothing here fits

Anyone can package their own tool as an add-on; see [For
developers](/developers/) for where that process starts. Until it's listed
there, a tool can still be added by hand from its address — the catalog is
a convenience for discovery and one-click setup, not the only way in.
