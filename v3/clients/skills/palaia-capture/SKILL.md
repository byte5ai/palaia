---
name: palaia-capture
description: Save what this person tells you into their shared memory, which every AI tool they use can read. Use it the moment they state a decision and the reason for it, a convention, a correction, or a detail that was expensive to work out — including when they mention it in passing on the way to a different question. Save it in the same turn, without asking permission first, then answer them.
license: MIT
---

# Capture

This person keeps one memory that every assistant they use can read. Your one
job here is to put things into it so they are not lost.

The tool is named after the memory it belongs to — `work_memory_capture`,
`personal_memory_capture`. Use the name your client lists. If several are
mounted, pick the one whose purpose covers the subject and use only that one.

It is the only tool to save with. Never `write` a note and never `edit` an
existing one to bolt your fact onto it: those notes belong to the person, ten
other sessions may be reading them, and rewriting one to fit something you just
heard is how a memory quietly stops being trustworthy.

The memory's own tool descriptions carry a general note-taking workflow:
*search first; write if nothing matches, edit what does.* That is for notes
someone asked you to write. It does not apply here. `capture` is not a lesser
`write` — it is the only way to add something nobody asked you to add, which is
exactly what everything you pick up in passing is.

## Do this before you answer

Before you write your reply, ask: did they just tell me something worth
keeping? If yes, `capture` it **now**, then answer. Answering first ends the
turn and loses it.

Acknowledging is not saving. "Got it, you pin that library to 3.4 because 3.5
breaks the parser" and then moving on means the next assistant works it out
again next week. Do not ask whether to save it; save it and mention it in one
line.

The phrasings that mean something just landed: *we settled on*, *we decided*,
*we went with*, *because otherwise*, *that's why*, *don't do X, it breaks Y*,
*turns out*, *from now on*, *actually, no —*.

## What to capture

- A decision, together with the reason for it.
- A convention: how this team names, formats, structures or ships things.
- A correction from the user. These are the most valuable of all.
- A detail that cost real time to work out and would cost it again.

Skip the conversation itself, anything already in the memory, anything you could
look up in seconds, and anything that was plainly thinking aloud.

## How

Four fields, no filing decisions:

- **what it concerns** — the thing this is about, in the name this team uses.
- **why keep it** — why a future reader should care. Write the consequence of
  not knowing it. Mandatory, and never guessed at.
- **content** — the substance in the fewest accurate words. Numbers, names,
  versions and paths verbatim.
- **source** — where it came from, if you know. Optional.

If you cannot say why it is worth keeping, do not capture it.

A worked example. They say, on the way to something else: *"By the way, we
capped ingest at 100 a minute because the embed queue saturates above that —
raising it needs batching first. Anyway, can you look at the auth bug?"* Your
first tool call, before the auth bug and before any reply:

```
capture(
  what_it_concerns="Rate limiting on the API gateway",
  why_keep="The cap was deliberate. Raising it without batching first re-breaks the embed queue.",
  content="Ingest capped at 100 req/min; the embed queue saturates above that. Raising it requires batching first.",
  source="conversation, 2026-08-22",
)
```

Then: "Saved that. On the auth bug —" and get on with it.

## Then move on

Capture is a drop target. Something else files it later.

- Capture in the turn the thing comes up, not at the end of the task.
- One capture per idea.
- Do not choose a folder, invent a title scheme, or tidy anything already
  stored.
- An exact duplicate is recognised and dropped — never hold back for fear of
  repeating yourself.
- Say in one short line what you captured, then get on with the work.
- If the tool reports a missing field, add it and retry once. Never fall back
  to writing a note by hand.

## Per-model notes

The line for your family wins; the unlabelled line is the default.

- Capture the fact, not the discussion around it.
- [anthropic] One capture, then straight back to the task — no summary of what
  you just saved.
- [openai] Do not wait to be asked. A stated decision is a capture.
- [google] Keep `content` to what was actually said or decided.
