# Resolved: Chain 01

Entry note is `chain-01.md`, the head of a 10-note chain (`chain-01` embeds
`chain-02`, ... `chain-09` embeds `chain-10`) — nine embed-hops in total.
Spec §5.3 sets the nesting limit at 8; this scenario is sized so hops 1-8
succeed (inlining `chain-02` through `chain-09`) and hop 9 — the one that
would embed `chain-10` — is the one that gets capped, replaced by the
literal `⟦depth: Chain 10⟧` marker instead of `chain-10`'s real content.

NOTE (see `AMBIGUITIES.md` #4): the spec states "8 nested resolutions" as
the cap but does not give a worked example pinning down whether the count
starts at the first embed-hop (this file's reading) or at the entry note
itself; a normative example would settle the exact boundary.

---

Depth marker 0 (entry note). Next: Depth marker 1. Next: Depth marker 2. Next: Depth marker 3. Next: Depth marker 4. Next: Depth marker 5. Next: Depth marker 6. Next: Depth marker 7. Next: Depth marker 8. Next: ⟦depth: Chain 10⟧

---

`chain-10.md`'s real content ("Depth marker 9 (terminal)...") never appears
above — that is the behavior under test. No warning code is defined for the
depth cap in the closed list (§9.1); only `embed-missing` and `embed-cycle`
are documented as carrying a warning, so none is asserted here.
