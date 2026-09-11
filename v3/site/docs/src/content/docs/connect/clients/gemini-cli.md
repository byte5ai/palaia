---
# Generated from v3/web/src/lib/clients.ts and skills.ts by v3/site/docs/scripts/generate-connect-pages.mjs. Do not hand-edit —
# change the source and run `npm run gen:connect` from v3/site/docs.
title: "Antigravity / Gemini CLI"
description: "Connect Antigravity / Gemini CLI to your shared memory."
---

Time: about one command · 1 min.

## Copy one line

Paste this into a terminal where the tool is already set up. It adds the connection; nothing else changes.

```bash
# add to ~/.gemini/settings.json under "mcpServers"
{"palaia": {"httpUrl": "http://palaia.local/mcp/default", "headers": {"Authorization": "Bearer <paste-your-token>"}}}
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

## Or save a file

Some setups read this from a file instead of a command. Save it as `palaia-gemini-settings.json`:

```json
{
  "mcpServers": {
    "palaia": {
      "httpUrl": "http://palaia.local/mcp/default",
      "headers": {
        "Authorization": "Bearer <paste-your-token>"
      }
    }
  }
}

```

Same here: replace `<paste-your-token>` with your token.

## Teach it to look things up and save things on its own

Gemini CLI supports Agent Skills.

1. Save SKILL.md into a folder named after the skill.
2. Put that folder in the skills directory your Gemini CLI version reads (its docs name the path).
3. Start a new session to pick it up.

## Check it worked

Ask it to remember something, then ask a different connected AI whether it knows the same thing. If both answer the same way, the connection is live — see [Your first shared memory](/first-shared-memory/) for the full walkthrough.
