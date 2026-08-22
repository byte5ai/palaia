# Vault-format conformance corpus

The executable contract for `../vault-format.md`. SPEC-103's parser MUST pass
every case; SPEC-106 additionally passes `resolution/`.

## Conventions

- Each case is `<nn>-<slug>.md` plus `<nn>-<slug>.expected.json`.
- **Subset matching:** every key present in an `expected.json` MUST match the
  parser output exactly; keys absent from the expectation are unasserted.
  Exception: the arrays `observations`, `relations`, `embeds`, `warnings` are
  asserted **whole** — exact length and order — with each element then
  subset-matched. An expected `[]` therefore means "none at all".
- `line` numbers are 1-based over the raw file.
- `warnings` array order: sorted by (line ascending, then code alphabetically);
  warnings without a line sort before all lined ones, alphabetically.
- Cases numbered 01–09 are the hand-written anchors (design intent); 10+ are
  systematic coverage. Every grammar rule and every warning code needs at
  least one positive and one negative case.
- `resolution/` holds multi-file scenarios (embed resolution: missing target,
  cycle, depth cap) as `scenario-<slug>/` directories with an
  `expected-resolved.md` per entry note — these test read-time behavior
  (SPEC-106), not the parser.
- Ambiguities discovered while authoring cases are NOT resolved by guessing:
  they go into `AMBIGUITIES.md` and get answered by a spec change first
  (format-first rule, ADR-003).
