---
title: Your memory
description: What a note actually is, how something you say becomes one, and how to look through it yourself.
---

Everything palaia stores is a plain text file on your machine — nothing
lives only inside a database you'd need special software to read. This page
explains what's actually happening, in the order things happen.

## Notes are files

A note is a short document: a title, a body, a couple of tags, and a folder
it lives in. Open one in any text editor and you'll recognize it instantly —
it reads like a well-kept wiki page, not a row in a spreadsheet. Every
change to every note is tracked, the same way source code is tracked, so you
can see exactly what changed and when, and nothing is ever silently
overwritten.

Notes can point at each other — "see also" links inside the text — so
related ideas stay connected without needing a folder structure to capture
every possible relationship. The dashboard's explorer shows a note alongside
the handful of others it's directly connected to, so you can follow a thread
without getting lost in everything else that's ever been saved.

## How something you say becomes a note

When a connected AI tool saves something on your behalf — a decision, a
correction, a detail worth keeping — it doesn't write directly into a
polished note. It drops a short, structured record: what it concerns, why
it's worth keeping, the actual content, and where it came from. Think of
this as a stack of quick, unreviewed entries rather than a finished
document.

A quiet background process reads that stack shortly after and does one of
two things:

- **Files it away on its own**, when the job is simple: create a new note,
  or add a new detail to a note that already exists. This happens without
  asking you anything.
- **Proposes a change instead of making it**, whenever the job would touch
  something that already exists in a bigger way — merging two notes,
  renaming one, retiring one that's gone stale. Nothing like that ever
  happens automatically. You see the proposal and approve or reject it
  yourself, in the dashboard.

That split is deliberate: adding something new is low-risk and constant, so
it stays automatic; changing something that already exists can lose
information if it goes wrong, so a person stays in the loop for every
instance of it.

<!-- screenshot: a pending proposal in the dashboard, with its diff against
     the existing note and an approve/reject choice -->

## Finding things again

The search bar in the dashboard looks for both the words you type and notes
that mean roughly the same thing even if the wording differs — so
"deploy process" can surface a note titled "release checklist" if that's
what actually answers the question. The same lookup is what an AI tool uses
when it checks your memory before answering something on your behalf; see
[Your first shared memory](/first-shared-memory/) for what that looks
like from the AI's side.

## More than one memory

You can keep separate memories — work and personal is the common split —
and decide per AI tool, or per connection, which one it can see. They stay
genuinely separate: nothing crosses from one into the other on its own.
[Profiles & access](/access/) covers how that's set up.

## Starting from something, instead of nothing

If you're moving from an existing setup rather than starting empty, an
importer can read your old palaia notes, or notes from other markdown-based
note tools, and bring them in with their original dates and tags intact —
ask in the dashboard's setup for the option that matches what you're coming
from. [For developers](/developers/) has the technical detail on the file
format itself, for anyone who wants to script against it directly.
