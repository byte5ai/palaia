---
title: Rate limit decision from PR review
permalink: inbox/rate-limit-decision-from-pr-review
type: capture
tags: [inbox]
status: uncurated
capture_id: cap-3f9a1c02d4
origin: { provider: anthropic, client: claude-code, session: s-9021 }
created: 2026-08-20T14:30:00Z
---

One sentence: what this capture is about.

- [entity] API Gateway
- [why] The limit was chosen deliberately; future work will trip over it otherwise.
- [raw] We capped ingest at 100 req/min because the embed queue saturates above that; raising it requires batching first.
- [source] PR #88 review, cwendler, 2026-08-22
