---
name: palaia-memory
description: Check this person's shared memory before answering anything about their own work, and add to it when something is worth keeping. It holds their projects, decisions and reasons, house conventions (naming, commit messages, tests, releases, review and escalation), people and hard-won details, and every AI tool they use reads and writes the same one. Use it before drafting or deciding on their behalf, when a project, service, person or term appears that you cannot place, when picking up earlier work, and whenever they state a decision, a correction, a convention or a detail that was expensive to work out.
license: MIT
---

# Shared memory

This person keeps one memory that every assistant they use can read and write.
It lives on their own machine as plain files, so anything you put in it is still
there next week, in a different tool, in a different conversation.

## Do this before you answer

Two checks, in this order, every turn — before you write your reply, not after:

1. **Did they just tell me something worth keeping?** A decision, a reason, a
   convention, a correction, a costly detail — even mentioned in passing on the
   way to a different question. If yes, `capture` it **now**. Answering first
   ends the turn and loses it.
2. **Do I need to look something up?** If the task touches their projects,
   their conventions, or a name you cannot place, `recall` before you decide.

Then answer, and mention in one short line what you saved.

Neither check is a favour to ask permission for. They are ordinary parts of
doing the work, like reading a file before editing it. "Want me to save that?"
is the wrong move: it spends the person's turn on something they already told
you, and if they do not reply, it is gone.

## The tools

The memory arrives as a family of tools whose names carry the memory they
belong to — `work_memory_recall`, `personal_memory_capture`, and so on. Use the
names your client actually lists; if two memories are mounted, the prefix is how
you tell them apart. Every tool description says what that memory is for.

The ones that matter here:

| Tool | Use it for |
|---|---|
| `recall` | What do we know about this topic? Ranked, most useful first. |
| `build_context` | Pick up where a previous session left off. |
| `search` | Find a specific note when you already know roughly what it is called. |
| `read` | Read one note in full. |
| `capture` | Save something you learned, and move on. |
| `write` / `edit` | Only when the person asked you to write or change a note. |

That last row is a hard line. Anything *you* learned goes in with `capture` —
never by writing a new note, and never by editing an existing one to bolt your
fact onto it. Those notes are the person's own, they may be read by ten other
sessions, and rewriting one to fit something you just heard is how a memory
quietly stops being trustworthy.

The memory's own tool descriptions carry a general note-taking workflow:
*search first; write if nothing matches, edit what does.* That is for notes
someone asked you to write, and it does not apply to what you picked up along
the way. Finding a related note is not permission to edit it. `capture` is not
a lesser `write` — it is the only way to add something nobody asked you to add,
which is exactly what everything you learn in passing is.

## Look before you act

Call `recall` — not `search` — when you want to *use* what the memory knows. It
ranks by relevance plus how recent, how often used and how load-bearing a note
is, resolves shared values to their current source, and narrows rules to the
model you are.

Recall at these moments, without being asked:

- **Starting anything non-trivial.** One `recall` on the subject of the task.
  A three-line answer costs nothing; guessing at a convention costs a review
  round.
- **Before a decision that has a house answer.** Naming, style, commit
  messages, test layout, release steps, escalation, tooling choices, how this
  team writes things down. Assume there is a rule and go look for it.
- **When you cannot place a name.** A service, repo, person, acronym, internal
  term. Look it up rather than inferring it from context.
- **Before proposing something that sounds like a fresh idea.** It may be a
  settled decision, or a road already tried. Both are in there.
- **When the user says "like last time", "as we discussed", "the usual".** That
  is a direct pointer into memory.

For continuity, `build_context` beats a second `recall`: give it a note (or a
query that finds one) and it walks the links those notes actually declare into
one package that fits your context window. It is the "continue where we left
off" tool — use it when resuming work, not when answering a fresh question.

If recall comes back empty, say so plainly and carry on. An empty memory is
information too, and it usually means you have something worth capturing.

## Which memory

If several memories are mounted, they are separate on purpose — work knowledge
does not belong in a personal memory and the reverse is worse. Choose by the
subject of what you are handling, not by which one you used last:

- Read from the memory whose purpose covers the topic. When genuinely unsure
  between two, read both and write to neither until you know.
- Write to exactly one. Never copy a note across memories to be safe.
- Never move content from one memory into another on your own initiative.

## Save what you learn

The commonest way to fail this person is to nod at something and let it go:
"got it, you pin that library to 3.4 because 3.5 breaks the parser" — and then
the next assistant, next week, has to work it out again. Acknowledging is not
saving. If it was worth them saying, save it in the same turn.

Watch for the phrasings that mean a decision just landed: *we settled on*, *we
decided*, *we went with*, *because otherwise*, *that's why*, *don't do X, it
breaks Y*, *turns out*, *from now on*, *actually, no —*.

Not everything is worth keeping; four things almost always are.

1. **Decisions, with the reason.** "We chose X" is half a note. "We chose X
   because Y, and Z is what changes it back" is the note.
2. **Conventions.** How this team names, formats, structures, releases,
   reviews. Anything a newcomer would get wrong.
3. **Corrections.** The user telling you that you had it wrong is the single
   highest-value thing to keep. Capture the correction, not your mistake.
4. **Gotchas that cost real time.** The flag that has to be set, the version
   that breaks, the config that looks optional and is not.

What not to keep: the conversation itself, anything already in the memory,
anything you could look up in seconds, speculation, and anything the user was
plainly thinking aloud about. When in doubt, look at the cost of rediscovering
it. Cheap to rediscover means do not capture.

### How to capture

`capture` takes four fields and needs no decisions about where the note goes:

- **what it concerns** — the thing this is about. A project, service, person,
  convention. One noun phrase, the name this team actually uses.
- **why keep it** — why a future reader should care. This is the field that
  makes a capture worth having; write the consequence of not knowing it.
- **content** — the substance, in the fewest words that stay accurate. Include
  numbers, names, versions, paths verbatim.
- **source** — where it came from, if you know: a PR, a file, a person, a
  conversation date. Optional, but cheap.

`what it concerns` and `why keep it` are mandatory and are never guessed at. If
you cannot say why something is worth keeping, that is the answer: do not
capture it.

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

Before you capture, spend one `recall` or `search` on the subject. If it is
already there and unchanged, do nothing. If it is there and now wrong, capture
the correction and say what it replaces.

That check is for deciding *whether* to capture — not for finding a note to
append to. Finding a related note changes nothing: still `capture`, never
`edit`. The related note is why your capture is worth having, not somewhere to
put it.

### Then move on

`capture` is a drop target, not a filing task. Something else sorts what you
drop, removes repeats and files it properly later; that is deliberate, and it is
not your job.

- Do not decide where the note belongs, or invent a folder or a title scheme.
- Do not tidy, merge, rewrite or delete anything that is already in the memory.
- Do not batch captures to the end of the task — you will forget the detail
  that made it worth keeping. Capture it in the turn it comes up.
- One capture per idea. Two decisions are two captures.
- An exact duplicate is harmless — it is recognised and dropped. Never suppress
  a capture out of fear of repeating yourself.
- Say in one short line what you captured, then continue the actual work. Never
  turn a capture into its own agenda item.
- Never ask permission first. "Want me to save that?" is the wrong move: it
  costs the user a turn to approve something they already told you, and if they
  do not answer, the thing is lost. Save it and mention it in passing.

If a capture is refused for a missing field, add the field and retry once. Do
not retry a third time and do not fall back to writing a note by hand.

## Per-model notes

Same memory, slightly different failure modes. The line for your family wins;
the unlabelled line is the default.

- Recall once per subject, then work from what you got.
- [anthropic] You will be tempted to read the whole neighbourhood of a topic.
  Prefer one `build_context` over a chain of `read` calls. And your instinct to
  ask before acting is wrong here: saving is not a change to their work, it is
  part of doing it.
- [openai] Do not wait to be asked. Silence about memory is not permission to
  skip it — the first tool call of a real task is a `recall`.
- [google] Keep captures to what happened. Do not summarise the conversation
  around it.
- Report what you did in one line, not a summary of the memory's contents.
- [anthropic] No preamble before the tool call, and no report of the tool call
  the user can already see.
