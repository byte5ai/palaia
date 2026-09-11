"""Issue #360: ``memory://`` title and alias resolution is Unicode-aware.

``GraphReader`` compared SQLite's ``lower(title)`` — which folds ASCII only —
with a Python-lowercased needle, so ``recall(ref="über uns")`` failed for a
note titled "Über uns" while the engine's own resolver (Python on both
sides) succeeded. Both sides now fold with Python's case mapping.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.anyio


async def test_non_ascii_titles_and_aliases_resolve_like_the_engine_does(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    await engine.write_note(
        "pages/ueber-uns.md",
        title="Über uns",
        body="Wer wir sind.\n",
        frontmatter={"type": "note", "aliases": ["Ünïcode Alias", "ÉQUIPE"]},
    )
    permalink = (await engine.read_note("pages/ueber-uns")).permalink
    assert permalink is not None

    for needle in ("über uns", "ÜBER UNS", "Über uns"):
        assert index.graph.by_title(needle) == [permalink], needle
        assert engine.resolve(needle).permalink == permalink, needle

    for alias in ("ünïcode alias", "ÜNÏCODE ALIAS", "équipe"):
        assert index.graph.by_alias(alias) == [permalink], alias
        assert engine.resolve(alias).permalink == permalink, alias

    # ASCII names keep working exactly as before.
    assert index.graph.by_title("api gateway") == ["projects/api-gateway"]
