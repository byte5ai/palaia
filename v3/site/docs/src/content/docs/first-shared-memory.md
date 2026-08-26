---
title: Your first shared memory
description: Install, connect two AI tools, and watch them share one fact — the whole point, in one walkthrough.
---

This is the moment palaia is for: two different AI tools, given the same
question, give the same answer — because they share one memory instead of
starting from nothing every time. Fifteen minutes end to end, most of it
waiting for downloads.

## 1. Install (about five minutes)

Follow [Install it](/install/) if you haven't already: one command,
then the browser-based setup creates your first memory. This walkthrough
assumes you named it something you'll recognize, like "work" or "home".

## 2. Connect your first AI tool

Pick one from [Connect your AI](/connect/) — [Claude Code
CLI](/connect/clients/claude-code-cli/) is a good first choice if you
already have it installed. Open a terminal where it's set up and paste
this to it directly, letting it configure itself:

```text
Please connect yourself to my palaia hub as an MCP server:
http://palaia.local/mcp/default
Then run a test recall and tell me what you found.
```

(Replace the address with your own hub's, if `palaia.local` doesn't resolve
on your network — the wizard showed you the working one.) It should report
back that the connection worked and that your memory is currently empty —
that's expected, you haven't saved anything yet.

Now give it something worth keeping:

> We're calling this project "Fieldnotes." Commit messages start with the
> ticket number in brackets, like `[FN-42] fix the export bug`. We settled
> on that after a PR got merged without one and nobody could tell which
> release it belonged to.

A well-connected tool saves that on its own, in the same turn, without you
asking it to. If it doesn't, you can ask directly: "please save that."

## 3. Connect a second, different AI tool

This is the part that matters — a memory only one tool uses is just that
tool's notes. Pick a *different* tool from the same list —
[Codex](/connect/clients/codex/) is a natural second if the first one was
Claude Code, or use anything else on the list. Same pattern: paste the same
kind of self-configuring message (each tool's page has its own exact
wording), swapping in your address.

Then ask it something the first tool was never told directly:

> What do you know about the Fieldnotes project's commit message format?

If the connection worked, it answers correctly — `[FN-42] fix the export
bug` — even though *this* tool never saw that conversation. It found it
because the first tool saved it, and both tools were pointed at the same
memory.

## 4. What just happened

Nothing was copied between the two tools. There is one memory; both tools
read from and wrote to it directly, over their own connection, at whatever
moment each one needed to. Add a third tool tomorrow and it starts already
knowing everything the first two taught it.

<!-- screenshot: the memory explorer showing the Fieldnotes note, with both
     tools' recent activity visible in the connected-clients list -->

From here:

- [Your memory](/memory/) explains what's actually happening when something
  gets saved, and how to look through it yourself.
- [Teach it to look things up and save things on its own](/connect/) (each
  tool's connect page has this section) makes the behavior above automatic
  rather than something you have to ask for every time.
- [Troubleshooting & FAQ](/troubleshooting/) covers what to check if step 2
  or 3 didn't go the way this page describes.
