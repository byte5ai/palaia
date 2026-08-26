"""Property-based fuzzing of the vault-format parser (SPEC-502 #2).

The parser is the hub's widest *injection surface* that is not a network
endpoint: it reads whatever markdown a user, an importer or a connected AI
put in a vault, and its output feeds the index, recall, the dashboard and
every MCP tool. Format spec invariant 3 says it never raises on user content
— warn-first, always a ``ParsedNote``. A parser that raises on some byte
sequence turns "one bad file" into "the index rebuild dies", so that
invariant is the property under test here.

**Corpus-seeded, as the SPEC requires.** Random markdown is very unlikely to
produce an observation line, a relation with a scope, a reference-style
link or a block anchor — the constructs where the interesting code lives. So
the strategies here draw their raw material from the golden conformance
corpus in ``v3/docs/vault-format-conformance/``: whole cases, individual
lines from cases, and fragments spliced together, then mutated (truncated
mid-construct, doubled brackets, injected control characters, BOMs, lone
surrogates' safe cousins, very long runs). That is what makes the fuzz reach
the grammar rather than the "this is not markdown" fast path.

**Bounded, as the SPEC requires.** The whole module runs under an explicit
hypothesis profile (:data:`PROFILE`) with a fixed example count and a
per-example deadline, and :func:`test_the_fuzz_stays_inside_its_time_budget`
fails if the corpus-seeded run stops fitting in
:data:`TIME_BUDGET_SECONDS`. A fuzz test with no ceiling is a CI outage
waiting for a slow runner.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from palaia_hub.vault.frontmatter import normalize_newlines
from palaia_hub.vault.parse import VAULT_FORMAT_VERSION, ParsedNote, parse_note, to_json

CORPUS_DIR = Path(__file__).resolve().parents[3] / "docs" / "vault-format-conformance"

#: How many examples each property runs, and how long one example may take.
#: Small on purpose: this runs on every push, and the value of a fuzz in CI
#: is regression pressure, not exhaustive search.
PROFILE = settings(
    max_examples=250,
    deadline=2_000,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)

#: Wall-clock ceiling for the corpus-seeded property, asserted directly.
TIME_BUDGET_SECONDS = 60.0

#: Characters that have historically broken naive markdown parsers: the
#: construct delimiters, the whitespace the grammar is sensitive to, a BOM,
#: bidirectional overrides, a NUL and a lone combining mark.
_HOSTILE_CHARS = (
    "[]()#^|:-<>\"'`\\"
    "\n\r\t "
    "\x00"  # NUL
    "\u00a0"  # non-breaking space
    "\ufeff"  # byte-order mark
    "\u202e"  # right-to-left override
    "\u0301"  # a lone combining acute accent
)


def _corpus_texts() -> list[str]:
    texts = [
        path.read_bytes().decode("utf-8", errors="replace")
        for path in sorted(CORPUS_DIR.glob("*.md"))
    ]
    assert texts, f"no conformance corpus found under {CORPUS_DIR}"
    return texts


def _corpus_lines() -> list[str]:
    lines: list[str] = []
    for text in _corpus_texts():
        lines.extend(text.splitlines())
    return sorted({line for line in lines if line.strip()})


CORPUS_TEXTS = _corpus_texts()
CORPUS_LINES = _corpus_lines()

corpus_line = st.sampled_from(CORPUS_LINES)
hostile_run = st.text(alphabet=_HOSTILE_CHARS, min_size=0, max_size=24)


@st.composite
def spliced_note(draw: st.DrawFn) -> str:
    """A note built from corpus lines, mutated at the seams."""
    pieces: list[str] = []
    for _ in range(draw(st.integers(min_value=1, max_value=12))):
        line = draw(corpus_line)
        cut = draw(st.integers(min_value=0, max_value=len(line)))
        keep_whole = draw(st.booleans())
        pieces.append(line if keep_whole else line[:cut])
        pieces.append(draw(hostile_run))
    return "\n".join(pieces)


@st.composite
def mutated_case(draw: st.DrawFn) -> str:
    """One whole corpus case with a slice replaced by hostile bytes."""
    text = draw(st.sampled_from(CORPUS_TEXTS))
    start = draw(st.integers(min_value=0, max_value=max(0, len(text) - 1)))
    end = draw(st.integers(min_value=start, max_value=len(text)))
    return text[:start] + draw(hostile_run) + text[end:]


def _assert_well_formed(note: ParsedNote, text: str) -> None:
    """Every invariant the rest of the hub relies on downstream."""
    assert note.format_version == VAULT_FORMAT_VERSION
    assert isinstance(note.title, str)
    assert isinstance(note.body, str)
    assert isinstance(note.type, str)
    assert note.permalink is None or isinstance(note.permalink, str)
    assert isinstance(note.frontmatter, dict)
    # Line numbers are reported against the parser's own normalized view
    # (`frontmatter.normalize_newlines`: BOM stripped, CRLF *and* lone CR
    # folded to LF), so the expected count has to be computed the same way.
    line_count = len(normalize_newlines(text).split("\n"))
    for observation in note.observations:
        assert isinstance(observation.category, str)
        assert isinstance(observation.text, str)
        assert 1 <= observation.line <= line_count
    for relation in note.relations:
        assert isinstance(relation.type, str)
        assert isinstance(relation.target, str)
        assert 1 <= relation.line <= line_count
    for warning in note.warnings:
        assert isinstance(warning.code, str) and warning.code
        assert warning.line is None or warning.line >= 1
    # The parse result is what the index and every MCP tool serialize; a
    # value that cannot round-trip through JSON is a failure one layer up.
    json.dumps(to_json(note), default=str)


@PROFILE
@given(text=spliced_note())
def test_spliced_corpus_lines_never_break_the_parser(text: str) -> None:
    _assert_well_formed(parse_note(text, "fuzz/spliced.md"), text)


@PROFILE
@given(text=mutated_case())
def test_a_mutated_corpus_case_never_breaks_the_parser(text: str) -> None:
    _assert_well_formed(parse_note(text, "fuzz/mutated.md"), text)


@PROFILE
@given(text=st.text(max_size=2_000))
def test_arbitrary_text_never_breaks_the_parser(text: str) -> None:
    _assert_well_formed(parse_note(text, "fuzz/arbitrary.md"), text)


@PROFILE
@given(
    text=st.text(alphabet=_HOSTILE_CHARS, max_size=400),
    path=st.text(max_size=60),
)
def test_a_hostile_path_is_carried_through_without_a_crash(text: str, path: str) -> None:
    """``path`` is attacker-influenced too — an importer's filename."""
    note = parse_note(text, path)
    assert note.path == path


def test_the_corpus_is_actually_seeding_the_fuzz() -> None:
    """Guard the guard: a fuzz over an empty seed set proves nothing."""
    assert len(CORPUS_TEXTS) >= 40, len(CORPUS_TEXTS)
    assert len(CORPUS_LINES) >= 200, len(CORPUS_LINES)
    joined = "\n".join(CORPUS_LINES)
    for construct in ("[[", "![[", "^", "- [", "---"):
        assert construct in joined, construct


@pytest.mark.parametrize("case", ["spliced", "mutated"])
def test_the_fuzz_stays_inside_its_time_budget(case: str) -> None:
    """The SPEC's "within its time budget" criterion, asserted rather than hoped.

    Runs the corpus-seeded property once more under the same profile and
    fails if it no longer fits — which is what would happen if a future
    parser change turned a linear scan into a quadratic one.
    """
    started = time.monotonic()
    if case == "spliced":
        test_spliced_corpus_lines_never_break_the_parser()
    else:
        test_a_mutated_corpus_case_never_breaks_the_parser()
    elapsed = time.monotonic() - started
    assert elapsed < TIME_BUDGET_SECONDS, f"{case} fuzz took {elapsed:.1f}s"
