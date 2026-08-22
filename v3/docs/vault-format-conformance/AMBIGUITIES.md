# Conformance corpus — open ambiguities

Format-first rule (ADR-003): when `vault-format.md` doesn't settle a case
precisely, we record the question here instead of inventing an expectation.
Each entry names the input, the plausible readings, and the spec section
that needs to be sharpened or exemplified. None of these are corrected by
edits to the spec, the ADR, or cases 01-07 in this PR — those stay read-only;
resolving an entry means a follow-up spec change.

## 1. Anchor cases 01 and 03 disagree with the corpus's own line-numbering convention

The README states "`line` numbers are 1-based over the raw file." Cases 02,
04, 06 and 07 follow that exactly (verified against the raw bytes with
`cat -n`). Cases 01 and 03 do not:

- `01-canonical-entity.md`: the `[rate-limit]` observation is on raw line 12,
  but `01-canonical-entity.expected.json` asserts `"line": 11` — every
  subsequent construct in that file is off by the same -1 (decision→12 vs.
  actual 13, `part_of`→13 vs. 14, `pairs well with`→14 vs. 15, the embed→16
  vs. actual 17).
- `03-exclusions.md`: the implicit-link prose line is raw line 25, but
  `03-exclusions.expected.json` asserts `"line": 26` — the opposite
  direction (+1).

Two different anchors, two different (and opposite) offsets, while a third
anchor (02) is exact — this reads as authoring slips in the anchors rather
than an alternate intentional convention, but per the task's read-only rule
for cases 01-07 it is recorded here rather than silently "corrected" by
example in a way that would contradict them. All new cases in this PR
(10-48) follow the README's stated rule literally: raw, 1-based file lines.
A spec/corpus follow-up should either fix 01 and 03's `line` values or
clarify that anchors are exempt from the rule.

## 2. Does `volatile-name` fire on volatility that isn't a semver/ISO-date/vX.Y token?

§4.1's WRONG-column examples are `[[OpenClaw 2026.5.7]]` (semver-like),
`[[Server offline]]` (a bare status word — no version or date token at
all), and `[[Preise Stand 2026-08]]` (a date). But the enforcement
paragraph narrows what the *parser* actually checks to "semver-like tokens,
ISO dates, `vX.Y` forms — the conformance corpus enumerates them." Case 06
and this PR's new volatile-name cases (30, 34, 35, 37, 38) all exercise
pattern-matchable tokens.

`[[Server offline]]` matches none of the three enumerated patterns. Two
readings:
1. The parser only checks the three enumerated patterns, so a title/target
   like "Server offline" does **not** get `volatile-name` at parse time —
   the WRONG-column example is illustrating the *concept* (enforced later
   by the writer/doctor/curator per the "layered enforcement" paragraph),
   not a parser obligation.
2. The parser is meant to also catch generic volatile-looking status words,
   making the "semver/ISO-date/vX.Y" list non-exhaustive.

No case was written for "Server offline"-shaped input because the correct
expectation (warn or not) depends on which reading is intended — §4.1 needs
either a fourth enumerated pattern or an explicit statement that non-token
volatility is writer/doctor-only.

## 3. `⟦cycle: <chain>⟧` — the `<chain>` serialization is not specified

§5.3 fixes the marker's outer shape but gives no worked example of
`<chain>`'s contents: separator (arrow? comma? something else), whether
titles or permalinks are used, and whether the closing (repeated) node is
repeated in the chain or elided. `resolution/scenario-simple-cycle/` and
`resolution/scenario-self-cycle/` had to pick a concrete rendering to be
useful as scaffolding — both use arrow-separated titles with the repeated
node written out (e.g. `Note A → Note B → Note A`) — but this is a best
effort for illustration, not an assertion the corpus can claim conformance
against. A normative worked example in §5.3 would settle this.

## 4. Depth-cap boundary — where exactly does "8 nested resolutions" start counting?

§5.3 says "Depth limit: 8 nested resolutions, then `⟦depth: <target>⟧`" with
no worked example. `resolution/scenario-depth-cap-chain/` was built on the
reading that counts start at the *first embed-hop* (the entry note's own
embed = hop 1), so hops 1-8 succeed and hop 9 is capped — requiring a
10-note chain to actually exercise the boundary. An equally plausible
reading counts the entry note itself as depth 0's occupant and the cap
lands one hop earlier (or later). Which reading is correct changes whether
a 9-note or 10-note (or different) chain is the minimal one that exercises
the cap; the scenario as built should be re-checked against SPEC-103's
actual implementation once it exists, or a worked example should be added
to §5.3.

## 5. Does a file with *no frontmatter fence at all* warn `frontmatter-malformed`?

§2 says "missing/malformed YAML → the whole file is a plain note ... warning
`frontmatter-malformed`." Case 05 (existing anchor) demonstrates the
*malformed* half unambiguously: a `---` fence is present and the YAML inside
it is broken. It does not demonstrate the *missing* half.

"Missing" could mean:
1. No `---` fence appears anywhere in the file — i.e. every ordinary
   Markdown note without a properties block warns on every parse. This
   seems like unwanted noise for extremely common, entirely valid content
   (a plain note a human just wrote in Obsidian with no properties), in
   tension with the "warn-first, never punish ordinary content" philosophy
   stated in invariant 3.
2. A `---` fence is opened but never closed (truncated frontmatter before
   EOF) — closer to "malformed" than "absent," and arguably what "missing"
   is meant to catch as a sibling of "malformed" rather than every
   frontmatter-less note.

Cases 44 (`44-empty-file`, 0 bytes) and 45 (`45-whitespace-only-file`,
whitespace only, no fence) are exactly the files this question bites: both
are written *without* a `warnings` key in their `expected.json` (an
unasserted key under the corpus's subset-matching rule), deliberately
skipping the `frontmatter-malformed`/`title-defaulted`/`permalink-missing`
expectation rather than guessing which reading is intended. Everything else
about those two cases (title defaults to the filename stem, empty
observations/relations/embeds) is asserted normally.

## 6. User-supplied permalink violating the charset — parse-time behavior undefined

§3.1 fixes the permalink charset (`[a-z0-9]` and `-`, `/`-joined segments)
as a property of engine-*assigned* and canonical permalinks, but doesn't
say what a parser does when a note's frontmatter already supplies a
permalink that violates this charset (uppercase letters, underscores, a
leading slash, etc.) — normalize it, warn (no code in the §9.1 closed list
covers this), or pass it through verbatim as read. No case was written for
this input; §3.1 would need either a normalization rule or a new warning
code to test against.

## 7. Does the date/timestamp category exclusion (E4) extend beyond the three given examples?

E4 lists exactly `[2026-08-22]`, `[00:01:23]`, `[12:30]` as excluded,
timestamp/date-*shaped* categories. It's unclear whether a category that is
merely numeric but not in one of those three shapes — e.g. a bare year
`[2026]` — is meant to be caught by the same exclusion (transcripts/logs
sometimes key on year alone) or is a perfectly ordinary category charset-
wise (digits are valid `cat-char`s) that simply isn't date-shaped enough to
exclude. No case was written for the bare-year form; E4 would need either a
fourth pattern or an explicit "these three shapes only" statement.

## 8. Are block anchors on non-observation lines represented anywhere in the parse result?

§5.4 says a block anchor "at the end of any line" makes that line
addressable, and gives `- [rate-limit] 100 req/min ^rate-limit` (an
observation) as the example of an anchor making a *field*. The canonical
parse result (§9) only carries `block_id` inside observation objects — there
is no top-level array for anchors on ordinary prose/heading/list lines. It's
unclear whether such anchors are simply outside SPEC-103's parse-result
scope (only reachable later via `memory://...#^id` resolution against the
raw file) or are meant to surface somewhere in the JSON this corpus asserts
against. This PR's anchor-duplicate coverage (case 13) stays inside
observation lines, where the schema is unambiguous, and does not attempt a
prose-line-anchor case.

## 9. Does the E7 wikilink carve-out extend to E1/E3, or is it E7-specific?

E7 explicitly states its exclusion doesn't suppress wikilink extraction:
"`|`-rows and `#`-prefixed lines carry no observation/relation semantics
(wikilinks inside them still yield implicit `links_to`)." E1 (task markers)
and E3 (blockquotes/callouts) carry no equivalent clause. Two readings:
1. The carve-out is E7-specific by design — a checkbox or quoted line is
   fully inert, including for wikilink extraction, unlike a table/heading.
2. The general §5.2 rule ("any `[[Target]]` elsewhere ... → implicit
   `links_to`") applies everywhere prose is prose, and E7's clause is just
   the one place the spec bothered to spell it out because tables/headings
   might otherwise look "structural" rather than prose-like; E1/E3 wikilinks
   would extract identically.

No case was written putting a wikilink inside a checkbox line or a
blockquote/callout line, since the two readings produce different
`relations` array lengths and the corpus's whole-array assertion would force
a guess either way.

---

# Resolutions — spec 1.0-draft.2 (2026-08-22, spec author)

All nine entries above are RESOLVED by spec changes in `../vault-format.md`
(changelog 1.0-draft.2). Rulings:

1. **Anchor line numbers** — authoring slips in cases 01/03, now fixed to raw
   1-based lines (01: +1 shift, embed at 17, plus new `anchors` array;
   03: prose link at 25). The README rule stands unchanged.
2. **volatile-name scope** — parser checks token patterns ONLY (semver, ISO
   date, `vX.Y`); conceptual volatility is writer/doctor/curator territory.
   New case 49.
3. **Cycle chain** — arrow-separated titles, repeated node written out;
   self-cycle `⟦cycle: A → A⟧`. Normative example added to §5.3; the
   resolution scenarios as built are now conformant, not scaffolding.
4. **Depth cap** — entry note's own embed is hop 1; hops 1–8 resolve, hop 9
   caps. The 10-note chain scenario is the minimal boundary test, as built.
5. **Missing frontmatter** — no fence at all (incl. empty/whitespace files)
   is a plain note WITHOUT `frontmatter-malformed`; only present-but-broken
   fences warn. Cases 44/45 now assert `permalink-missing` +
   `title-defaulted`. Warning order rule added to the README.
6. **Non-canonical permalink** — kept verbatim, new warning
   `permalink-noncanonical` (added to §9.1 closed list); doctor canonicalizes
   via rename+alias. New case 51.
7. **E4 scope** — date shapes, time shapes, and purely-numeric categories are
   excluded; mixed alphanumeric stays valid. New case 50.
8. **Anchors on any line** — surfaced in a new top-level `anchors` array
   (§9); observation `block_id` unchanged. New case 52; case 01 asserts it.
9. **Wikilinks in excluded lines** — extraction applies on ALL excluded lines
   except code (E2). New case 53.
