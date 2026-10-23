---
# Generated from v3/web/src/lib/clients.ts and skills.ts by v3/site/docs/scripts/generate-connect-pages.mjs. Do not hand-edit —
# change the source and run `npm run gen:connect` from v3/site/docs.
title: "Claude"
description: "Connect Claude to your shared memory."
---

The Claude app on Mac, Windows and phones, and claude.ai — a custom connector

## What has to be true first

- **Locked mode.** Claude connects from the internet, so it needs cloud access. Turn it on in setup or in Settings › Access & sign-in; your dashboard stays on your private network.
- **Cloud mode or Open mode.** Claude signs in to palaia with your account, and sign-in is not on yet. Finish turning on cloud access, then come back here. Every plan (including Free) can add palaia as a custom connector.

## Once sign-in is on

In Claude, add a custom connector with this address. When it asks, sign in with your palaia account and allow access.

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
