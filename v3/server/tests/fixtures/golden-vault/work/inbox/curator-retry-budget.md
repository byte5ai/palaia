---
title: Curator retry budget
permalink: inbox/curator-retry-budget
type: capture
tags: [inbox]
status: uncurated
capture_id: cap-7b21d94ee1
origin: { provider: anthropic, client: claude-code, session: s-9021 }
created: 2026-08-20T14:30:00Z
---

One sentence: what this capture is about.

- [entity] Curator
- [why] Three retries balances noisy transient failures against runaway apply loops.
- [raw] Curator apply attempts cap at 3 before status flips to curation-failed.
