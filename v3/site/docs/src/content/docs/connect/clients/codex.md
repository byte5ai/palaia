---
# Generated from v3/web/src/lib/clients.ts and skills.ts by v3/site/docs/scripts/generate-connect-pages.mjs. Do not hand-edit —
# change the source and run `npm run gen:connect` from v3/site/docs.
title: "Codex"
description: "Connect Codex to your shared memory."
---

Time: about one command · 1 min.

## Copy one line

Paste this into a terminal where the tool is already set up. It adds the connection; nothing else changes.

```bash
export PALAIA_TOKEN=<paste-your-token>
codex mcp add palaia --url http://palaia.local/mcp/default --bearer-token-env-var PALAIA_TOKEN
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

Some setups read this from a file instead of a command. Save it as `palaia-codex-mcp.toml`:

```toml
# Paste this into ~/.codex/config.toml (or merge it into an existing
# [mcp_servers] table).
[mcp_servers.palaia]
url = "http://palaia.local/mcp/default"
bearer_token_env_var = "PALAIA_TOKEN"
# Codex reads the token from that variable — set it where Codex starts:
#   export PALAIA_TOKEN=<paste-your-token>

```

Same here: replace `<paste-your-token>` with your token.

## Teach it to look things up and save things on its own

Codex reads Agent Skills from its own skills directory.

1. Save SKILL.md into a folder named after the skill.
2. Move that folder into the skills directory Codex reads (shared with ChatGPT plugins since July 2026 — your Codex version's docs name the exact path).
3. Start a new Codex session and the skill is available.

## Check it worked

Ask it to remember something, then ask a different connected AI whether it knows the same thing. If both answer the same way, the connection is live — see [Your first shared memory](/first-shared-memory/) for the full walkthrough.
