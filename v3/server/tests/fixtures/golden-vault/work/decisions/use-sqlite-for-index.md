---
title: Use SQLite For Index
permalink: decisions/use-sqlite-for-index
type: decision
tags: [adr]
---

The hybrid search index is SQLite (FTS5 + a small vector table), not a separate service — it is disposable and rebuilt from files.

- decided_in [[Vault Engine]]
