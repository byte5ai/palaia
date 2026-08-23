# Resolved: Note A

Entry note is `note-a.md`. A → B → A is a two-hop cycle: A embeds B, and B
embeds A back. Resolution inlines B's content into A, then — while resolving
*that* nested embed — finds A already on the current resolution chain and
stops there with the literal `⟦cycle: …⟧` marker plus an `embed-cycle`
warning, rather than recursing forever.

NOTE (see `AMBIGUITIES.md` #3): the spec fixes the marker shape
`⟦cycle: <chain>⟧` but not the exact serialization of `<chain>` — this file
uses arrow-separated titles, repeating the closing node, as the most
readable concrete choice; a normative example would settle this precisely.

---

Content of A.

See also: Content of B.

Back-reference: ⟦cycle: Note A → Note B → Note A⟧

---

Warnings emitted during resolution: `embed-cycle` (chain: `Note A → Note B → Note A`).
