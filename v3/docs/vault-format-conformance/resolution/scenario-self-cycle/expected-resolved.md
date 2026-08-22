# Resolved: Note Self

Entry note is `note-self.md`, which embeds itself directly — the
degenerate one-hop cycle. The first nested resolution already finds the
entry note on the chain, so it stops immediately with the `⟦cycle: …⟧`
marker plus an `embed-cycle` warning (see the chain-serialization caveat
in `AMBIGUITIES.md` #3, which also applies here).

---

This note embeds itself: ⟦cycle: Note Self → Note Self⟧

---

Warnings emitted during resolution: `embed-cycle` (chain: `Note Self → Note Self`).
