---
# Generated from v3/web/src/lib/clients.ts and skills.ts by v3/site/docs/scripts/generate-connect-pages.mjs. Do not hand-edit —
# change the source and run `npm run gen:connect` from v3/site/docs.
title: "ChatGPT"
description: "Connect ChatGPT to your shared memory."
---

Developer mode / custom connectors

## What has to be true first

- **Locked mode.** ChatGPT connects from its own cloud, not from this device — Locked mode only answers inside your network, so it would time out whatever you paste into it. Switch to Cloud or Open mode to expose an endpoint it can reach.
- **Cloud mode or Open mode.** ChatGPT needs sign-in turned on for this hub, and it is not yet — turn it on from the Access mode page (Cloud and Open both support it), then come back here. Write access needs a Business, Enterprise or Edu workspace — Plus/Pro get a read-only profile so recall still works.

## Once sign-in is on

Paste this address into ChatGPT's custom connector settings, then sign in with your palaia account when it asks.

```text
https://palaia.example.com/mcp/default
```

## Teach it to look things up and save things on its own

Skills and connectors live in one plugin directory, shared with Codex.

1. Save SKILL.md into a folder named after the skill.
2. Add it to the plugin directory ChatGPT and Codex share.
3. Write access to the memory itself is plan-gated — see the connector note for this client.

## Check it worked

Ask it to remember something, then ask a different connected AI whether it knows the same thing. If both answer the same way, the connection is live — see [Your first shared memory](/first-shared-memory/) for the full walkthrough.
