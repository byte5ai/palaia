"""Conformance runner for ``docs/vault-format-conformance/resolution/``.

Each ``scenario-<slug>/`` directory is a tiny vault: a set of ``.md`` notes
plus one ``expected-resolved.md`` describing what resolving the entry note's
embeds must produce. The corpus README assigns these scenarios to SPEC-106
("SPEC-106 additionally passes ``resolution/``"), and this module is that
pass.

**The comparison is byte-exact.** ``expected-resolved.md`` wraps the resolved
payload between two ``---`` rules, with prose above (what the scenario tests)
and below (the warnings it asserts); the block between the rules is compared
character for character against the resolver's output. Nothing is normalized
beyond stripping the blank lines the fence itself introduces.

The scenarios are read by a **directory-backed** note source rather than
through the engine or the index: these files are not a vault (no manifest, no
git, no permalink assignment), and resolution semantics must be provable
without either. The live, index-backed path is covered by
``test_recall_service.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from palaia_hub.recall.embeds import (
    EMBED_CYCLE,
    EMBED_MISSING,
    ResolvedText,
    SourceNote,
    resolve_references,
)
from palaia_hub.vault import frontmatter as fm

CORPUS_DIR = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "vault-format-conformance"
    / "resolution"
)


@dataclass(frozen=True, slots=True)
class Scenario:
    """One ``scenario-<slug>/`` directory: its notes and its entry note."""

    name: str
    entry: SourceNote
    notes: tuple[SourceNote, ...]
    expected_body: str
    expected_codes: tuple[str, ...]


class DirectorySource:
    """A :class:`~palaia_hub.recall.NoteSource` over one scenario directory.

    Resolution order is the corpus's own: permalink first, then exact title
    (case-insensitive) — the two tiers these scenarios exercise (§3.2's alias
    and path-suffix tiers need a vault to be meaningful).
    """

    def __init__(self, notes: tuple[SourceNote, ...]) -> None:
        self._by_permalink = {note.permalink: note for note in notes}
        self._by_title = {note.title.casefold(): note for note in notes}

    def resolve(self, target: str) -> SourceNote | None:
        key = target.strip()
        if key in self._by_permalink:
            return self._by_permalink[key]
        return self._by_title.get(key.casefold())


def _read_note(path: Path) -> SourceNote:
    # Bytes, then UTF-8 — never text mode, so a scenario's exact line endings
    # survive into the comparison (same rule as the parser's own runner).
    text = path.read_bytes().decode("utf-8")
    parsed = fm.parse(text)
    title, _ = fm.string_value(parsed.frontmatter, "title")
    permalink, _ = fm.string_value(parsed.frontmatter, "permalink")
    return SourceNote(
        permalink=permalink or path.stem,
        title=title or path.stem,
        body=parsed.body,
    )


#: The entry note of each scenario, and the codes its footer asserts. Both are
#: read off the scenario's own `expected-resolved.md` prose — see each file.
_ENTRY_AND_CODES: dict[str, tuple[str, tuple[str, ...]]] = {
    "scenario-missing-target": ("entry.md", (EMBED_MISSING,)),
    "scenario-simple-cycle": ("note-a.md", (EMBED_CYCLE,)),
    "scenario-self-cycle": ("note-self.md", (EMBED_CYCLE,)),
    # The depth cap has no warning code in §9.1's closed list, and the
    # scenario's footer says so explicitly.
    "scenario-depth-cap-chain": ("chain-01.md", ()),
}

_FOOTER_CODE_RE = re.compile(r"`(embed-[a-z-]+)`")


def _expected_block(text: str) -> str:
    """The payload between the first and second ``---`` rule, stripped."""
    parts = [part for part in text.split("\n---\n")]
    assert len(parts) >= 3, "expected-resolved.md must fence its payload in --- rules"
    return parts[1].strip("\n")


def _footer_codes(text: str) -> tuple[str, ...]:
    """Warning codes the footer prose mentions, as a cross-check on the table."""
    for line in text.split("\n"):
        if line.startswith("Warnings emitted during resolution:"):
            return tuple(_FOOTER_CODE_RE.findall(line))
    return ()


def _load(directory: Path) -> Scenario:
    entry_name, codes = _ENTRY_AND_CODES[directory.name]
    notes = tuple(
        _read_note(path)
        for path in sorted(directory.glob("*.md"))
        if path.name != "expected-resolved.md"
    )
    expected_text = (directory / "expected-resolved.md").read_bytes().decode("utf-8")
    # Cross-check the table above against the scenario's own footer prose, so
    # a corpus edit that changes the asserted warnings cannot go unnoticed.
    assert _footer_codes(expected_text) == codes, (
        f"{directory.name}: footer prose lists {_footer_codes(expected_text)}, "
        f"this module's table says {codes}"
    )
    return Scenario(
        name=directory.name,
        entry=_read_note(directory / entry_name),
        notes=notes,
        expected_body=_expected_block(expected_text),
        expected_codes=codes,
    )


def _scenarios() -> list[Scenario]:
    return [
        _load(path)
        for path in sorted(CORPUS_DIR.iterdir())
        if path.is_dir() and (path / "expected-resolved.md").exists()
    ]


def _resolve(scenario: Scenario) -> ResolvedText:
    return resolve_references(
        scenario.entry.body,
        entry=scenario.entry,
        source=DirectorySource(scenario.notes),
    )


SCENARIOS = _scenarios()


def test_the_corpus_has_every_scenario_this_module_knows_about() -> None:
    assert {scenario.name for scenario in SCENARIOS} == set(_ENTRY_AND_CODES)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_resolved_output_matches_expected_byte_for_byte(scenario: Scenario) -> None:
    resolved = _resolve(scenario)
    assert resolved.text.strip("\n") == scenario.expected_body, (
        f"{scenario.name}: resolved output differs from expected-resolved.md\n"
        f"--- got ---\n{resolved.text}\n--- want ---\n{scenario.expected_body}"
    )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_resolution_warnings_match_the_scenario(scenario: Scenario) -> None:
    resolved = _resolve(scenario)
    assert resolved.codes == scenario.expected_codes


def test_the_depth_capped_note_content_never_appears() -> None:
    # The behavior under test in scenario-depth-cap-chain, stated as its own
    # assertion: chain-10 is the note the cap refuses to reach.
    scenario = next(s for s in SCENARIOS if s.name == "scenario-depth-cap-chain")
    resolved = _resolve(scenario)
    assert "⟦depth: Chain 10⟧" in resolved.text
    assert "Depth marker 9" not in resolved.text
    assert "Depth marker 8" in resolved.text


def test_a_missing_target_is_a_marker_not_an_exception() -> None:
    scenario = next(s for s in SCENARIOS if s.name == "scenario-missing-target")
    resolved = _resolve(scenario)
    assert "⟦missing: Ghost Note⟧" in resolved.text
    # ...and the sibling embed on the same page still resolved cleanly.
    assert "$0.02 per request" in resolved.text
