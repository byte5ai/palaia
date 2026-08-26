---
# Generated from v3/web/src/lib/clients.ts and skills.ts by v3/site/docs/scripts/generate-connect-pages.mjs. Do not hand-edit —
# change the source and run `npm run gen:connect` from v3/site/docs.
title: "Grok"
description: "Connect Grok to your shared memory."
---

Custom (bring-your-own) `MCP` connectors — web/iOS/Android

## What has to be true first

- **Locked mode.** Grok connects from its own cloud, not from this device — Locked mode only answers inside your network, so it would time out whatever you paste into it. Switch to Cloud or Open mode to expose an endpoint it can reach.
- **Cloud mode or Open mode.** Grok needs sign-in turned on for this hub, and it is not yet — turn it on from the Access mode page (Cloud and Open both support it), then come back here. Connect from web, iOS or Android once it is on.

## Once sign-in is on

Paste this address into Grok's custom connector settings, then sign in with your palaia account when it asks.

```text
https://palaia.example.com/mcp/default
```

## Teach it to look things up and save things on its own

Grok connects custom `MCP` servers but does not load SKILL.md packages, so there is nothing here to install. The memory still works — the tool descriptions carry their own guidance; you just have to ask for it.

## Check it worked

Ask it to remember something, then ask a different connected AI whether it knows the same thing. If both answer the same way, the connection is live — see [Your first shared memory](/first-shared-memory/) for the full walkthrough.
