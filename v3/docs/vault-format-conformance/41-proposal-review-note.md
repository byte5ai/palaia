---
title: Merge duplicate Stash notes
permalink: review/merge-duplicate-stash-notes
type: proposal
status: proposed
---

Two notes describe the same entity under different titles; propose a merge.

- [rationale] Both notes were created independently after a rename.
- supersedes [[Old Stash Note]]

```json plan
{"op": "merge", "from": "tools/old-stash-note", "into": "tools/stash"}
```
