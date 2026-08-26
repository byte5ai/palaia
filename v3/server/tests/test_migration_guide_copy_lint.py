"""SPEC-505 acceptance criterion "jargon lint on all new prose", applied to
the migration guide this SPEC adds.

Reuses the one shared blocklist (:mod:`palaia_addon_sdk.jargon` — see that
module's docstring: "the SDK now owns the canonical copy"), the same list
``skill_lint.py`` checks skills against and SPEC-503 commits to running over
the docs site's prose. Fenced code blocks, inline code and table rows are
stripped first (the same exemption those callers use): a table cell naming
the real v2 command (``palaia curate analyze``) or a code block showing the
real import invocation is not jargon, it is the string a reader has to type.
"""

from __future__ import annotations

from pathlib import Path

from palaia_addon_sdk.jargon import find_jargon

DOC = Path(__file__).resolve().parents[2] / "docs" / "migrate-from-v2.md"


def test_migration_guide_prose_has_no_jargon() -> None:
    text = DOC.read_text(encoding="utf-8")
    hits = find_jargon(text)
    assert hits == [], f"jargon found in {DOC}: {hits}"
