---
# Generated from v3/web/src/lib/clients.ts and skills.ts by v3/site/docs/scripts/generate-connect-pages.mjs. Do not hand-edit —
# change the source and run `npm run gen:connect` from v3/site/docs.
title: "Claude Code CLI"
description: "Connect Claude Code CLI to your shared memory."
---

Time: about one command · 1 min.

## Copy one line

Paste this into a terminal where the tool is already set up. It adds the connection; nothing else changes.

```bash
claude mcp add --transport http palaia http://palaia.local/mcp/default --header "Authorization: Bearer <paste-your-token>"
```

Replace `<paste-your-token>` with the token the dashboard shows when you click **Issue token** on its connect page — it is shown once, so copy it then. Every request needs it; without it the hub turns the tool away.

## Or just ask it

If you would rather not touch a terminal, paste this to the AI itself and let it set itself up:

```text
Please connect yourself to my palaia hub as an MCP server:
http://palaia.local/mcp/default
Send the header "Authorization: Bearer <paste-your-token>" with every request.
Then run a test recall and tell me what you found.
```

Same here: replace `<paste-your-token>` with your token.

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
