---
title: API Gateway
permalink: projects/api-gateway
type: note
tags: [infra, api]
created: 2026-08-22T10:00:00Z
scope: shared
---

The ingress layer for ACME.

- [rate-limit] 100 req/min #infra (set in PR #88) ^rate-limit
- [decision] We terminate TLS at [[Caddy]] only.
- part_of [[ACME Platform]]
- "pairs well with" [[Stash]] (cache offload)

Baseline pricing: ![[Pricing#^base-rate]]
