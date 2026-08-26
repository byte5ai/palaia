---
# Generated from v3/web/src/lib/clients.ts and skills.ts by v3/site/docs/scripts/generate-connect-pages.mjs. Do not hand-edit —
# change the source and run `npm run gen:connect` from v3/site/docs.
title: "claude.ai"
description: "Connect claude.ai to your shared memory."
---

Web, desktop, mobile and Cowork — custom connector on every plan

## What has to be true first

- **Locked mode.** claude.ai connects from its own cloud, not from this device — Locked mode only answers inside your network, so it would time out whatever you paste into it. Switch to Cloud or Open mode to expose an endpoint it can reach.
- **Cloud mode or Open mode.** claude.ai needs sign-in turned on for this hub, and it is not yet — turn it on from the Access mode page (Cloud and Open both support it), then come back here. Every plan (including Free) can add palaia as a custom connector.

## Once sign-in is on

Paste this address into claude.ai's custom connector settings, then sign in with your palaia account when it asks.

```text
https://palaia.example.com/mcp/default
```

## Teach it to look things up and save things on its own

Add it as a capability in your account settings.

1. Download SKILL.md and zip its folder (the folder name must match the skill's name).
2. In claude.ai, open Settings → Capabilities → Skills and upload the zip.
3. It then applies to web, desktop, mobile and Cowork — the memory itself still needs the connector below.

## Check it worked

Ask it to remember something, then ask a different connected AI whether it knows the same thing. If both answer the same way, the connection is live — see [Your first shared memory](/first-shared-memory/) for the full walkthrough.
