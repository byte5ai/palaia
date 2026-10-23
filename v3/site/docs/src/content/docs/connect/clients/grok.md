---
# Generated from v3/web/src/lib/clients.ts and skills.ts by v3/site/docs/scripts/generate-connect-pages.mjs. Do not hand-edit —
# change the source and run `npm run gen:connect` from v3/site/docs.
title: "Grok"
description: "Connect Grok to your shared memory."
---

Custom (bring-your-own) `MCP` connectors — web/iOS/Android

## What has to be true first

- **Locked mode.** Grok connects from the internet, so it needs cloud access. Turn it on in setup or in Settings › Access & sign-in; your dashboard stays on your private network.
- **Cloud mode or Open mode.** Grok signs in to palaia with your account, and sign-in is not on yet. Finish turning on cloud access, then come back here. Connect from web, iOS or Android once it is on.

## Once sign-in is on

In Grok, add a custom connector with this address. When it asks, sign in with your palaia account and allow access.

```text
https://palaia.example.com/mcp/default
```

## Teach it to look things up and save things on its own

Grok connects custom `MCP` servers but does not load SKILL.md packages, so there is nothing here to install. The memory still works — the tool descriptions carry their own guidance; you just have to ask for it.

## Check it worked

Ask it to remember something, then ask a different connected AI whether it knows the same thing. If both answer the same way, the connection is live — see [Your first shared memory](/first-shared-memory/) for the full walkthrough.
