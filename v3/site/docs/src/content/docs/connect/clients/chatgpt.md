---
# Generated from v3/web/src/lib/clients.ts and skills.ts by v3/site/docs/scripts/generate-connect-pages.mjs. Do not hand-edit —
# change the source and run `npm run gen:connect` from v3/site/docs.
title: "ChatGPT"
description: "Connect ChatGPT to your shared memory."
---

A custom connector in developer mode

## What has to be true first

- **Locked mode.** ChatGPT connects from the internet, so it needs cloud access. Turn it on in setup or in Settings › Access & sign-in; your dashboard stays on your private network.
- **Cloud mode or Open mode.** ChatGPT signs in to palaia with your account, and sign-in is not on yet. Finish turning on cloud access, then come back here. Write access needs a Business, Enterprise or Edu workspace — Plus/Pro get a read-only profile so recall still works.

## Once sign-in is on

In ChatGPT, add a custom connector with this address. When it asks, sign in with your palaia account and allow access.

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
