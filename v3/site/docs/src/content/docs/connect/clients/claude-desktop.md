---
# Generated from v3/web/src/lib/clients.ts and skills.ts by v3/site/docs/scripts/generate-connect-pages.mjs. Do not hand-edit —
# change the source and run `npm run gen:connect` from v3/site/docs.
title: "Claude Code (Desktop app)"
description: "Connect Claude Code (Desktop app) to your shared memory."
---

One-click download — a signed bridge to your hub, no typing required

## Download and open it

1. Open your dashboard's connect page and choose this tool — the download button builds a file addressed to your own hub, so there is nothing to type or paste.
2. Open the downloaded file. The tool recognizes it and asks you to confirm the connection.
3. Confirm. You are connected.

## Teach it to look things up and save things on its own

Save the folder, or load the whole package for one session.

1. Create ~/.claude/skills/<name>/ and save SKILL.md into it — one folder per skill.
2. Start a new session; the skill is offered from then on, and loads itself when a task needs it.
3. Trying it out first: clone this repo and pass v3/clients as a plugin, which loads every skill in it for that session only.

```bash
claude --plugin-dir /path/to/palaia/v3/clients
```

## Check it worked

Ask it to remember something, then ask a different connected AI whether it knows the same thing. If both answer the same way, the connection is live — see [Your first shared memory](/first-shared-memory/) for the full walkthrough.
