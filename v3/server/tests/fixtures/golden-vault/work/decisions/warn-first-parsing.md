---
title: Warn First Parsing
permalink: decisions/warn-first-parsing
type: decision
tags: [adr]
---

The parser never rejects user content; anything that fails a rule degrades to plain Markdown plus a machine-readable warning.

- relates_to [[Vault Engine]]
