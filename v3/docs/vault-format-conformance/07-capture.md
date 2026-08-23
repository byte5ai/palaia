---
title: Embed queue saturation
permalink: inbox/embed-queue-saturation
type: capture
tags: [inbox]
status: uncurated
capture_id: cap-3f9a1c02d4
origin: { provider: anthropic, client: claude-code }
---

Why the ingest cap exists.

- [entity] API Gateway
- [why] Future work will trip over the cap otherwise.
- [raw] Ingest capped at 100 req/min; embed queue saturates above that.
- [source] PR #88 review, 2026-08-22
