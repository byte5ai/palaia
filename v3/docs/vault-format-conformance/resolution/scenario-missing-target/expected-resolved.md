# Resolved: Entry Note

Resolution of `entry.md`'s embeds against the notes in this scenario directory,
per spec §5.3. One embed resolves cleanly (the negative/happy-path case for
`embed-missing`); the other has no target anywhere in the vault (the positive
case) and produces the literal marker plus an `embed-missing` warning — never
a dropped reference or a thrown error.

---

Pricing baseline: - [base-rate] $0.02 per request ^base-rate

Nonexistent reference: ⟦missing: Ghost Note⟧

---

Warnings emitted during resolution: `embed-missing` (target: `Ghost Note`).
