"""Conformance runner — SPEC-103 against the vault-format golden corpus.

Every ``<nn>-<slug>.md`` / ``<nn>-<slug>.expected.json`` pair in
``docs/vault-format-conformance/`` (case numbers 01-53, the ``resolution/``
subdirectory excluded per its own README: it tests SPEC-106 read-time embed
resolution, not the parser) is asserted with the corpus's own matching rules:

* Every key present in an ``expected.json`` must match the parser output
  exactly; keys absent from the expectation are unasserted.
* The arrays ``observations``, ``relations``, ``embeds``, ``warnings`` are
  the exception: asserted whole (exact length and order), each element then
  subset-matched.

Files are read as raw bytes and decoded as UTF-8 (never opened in text mode)
so a case's BOM or CRLF line endings survive exactly as authored — cases 42
and 47 exist to exercise that.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from palaia_hub.vault.parse import parse_note, to_json

CORPUS_DIR = Path(__file__).resolve().parents[3] / "docs" / "vault-format-conformance"

WHOLE_ARRAY_KEYS = {"observations", "relations", "embeds", "warnings"}


def _case_files() -> list[Path]:
    return sorted(
        path
        for path in CORPUS_DIR.glob("*.md")
        if path.with_suffix("").with_suffix(".expected.json").exists()
    )


def assert_subset(expected: Any, actual: Any, path: str = "$") -> None:
    """Recursive subset match per the corpus README's conventions."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected an object, got {actual!r}"
        for key, value in expected.items():
            assert key in actual, f"{path}.{key}: missing from parser output"
            assert_subset(value, actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: expected a list, got {actual!r}"
        assert len(expected) == len(actual), (
            f"{path}: expected {len(expected)} entries, got {len(actual)}: "
            f"expected={expected!r} actual={actual!r}"
        )
        for index, (exp_item, act_item) in enumerate(zip(expected, actual, strict=True)):
            assert_subset(exp_item, act_item, f"{path}[{index}]")
    else:
        assert expected == actual, f"{path}: expected {expected!r}, got {actual!r}"


@pytest.mark.parametrize("case_path", _case_files(), ids=lambda p: p.stem)
def test_corpus_case(case_path: Path) -> None:
    expected_path = case_path.with_suffix("").with_suffix(".expected.json")
    assert expected_path.exists(), f"missing expectation file for {case_path.name}"

    raw = case_path.read_bytes().decode("utf-8")
    expected = json.loads(expected_path.read_text(encoding="utf-8"))

    note = parse_note(raw, case_path.name)
    actual = to_json(note)

    assert_subset(expected, actual)


def test_corpus_has_the_expected_case_count() -> None:
    # README: 51 case pairs (numbered 01-07 hand-written anchors, 10-53
    # systematic coverage; 08/09 reserved and unused).
    assert len(_case_files()) == 51
