"""Issue #361: a narrow filter must not empty the vector half of a search.

The KNN over-fetched a fixed number of rows and applied scope/type filters
afterwards; when none of those rows matched, the hybrid query silently fell
back to full-text search and *blamed the embed backlog* — although every
vector was ready. The filter now runs inside the nearest-neighbour scan, and
a genuinely empty vector result names the actual reason.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from stub_embedder import StubEmbedder

from palaia_hub.index import EmbeddingConfig, SearchFilters

pytestmark = pytest.mark.anyio

#: More than the KNN's minimum over-fetch, so the unfiltered top-k is made
#: entirely of these and the filtered note is never among them.
BULK_NOTES = 48


def _stub_config() -> EmbeddingConfig:
    return EmbeddingConfig(enabled=True, model="stub/hashed-bow", batch_size=64)


async def _vault_with_a_needle_in_a_haystack(golden_work_vault: Path, open_index: Any) -> Any:
    engine, index = await open_index(
        golden_work_vault, embedding=_stub_config(), embedder=StubEmbedder()
    )
    for i in range(BULK_NOTES):
        await engine.write_note(
            f"bulk/note-{i:02d}.md",
            title=f"Bulk {i}",
            body=f"alpha beta gamma delta epsilon {i}\n",
            frontmatter={"type": "note"},
        )
    await engine.write_note(
        "widgets/zeta.md",
        title="Zeta Omega",
        body="zeta omega works on something else entirely\n",
        frontmatter={"type": "widget"},
    )
    await index.drain_embeddings()
    assert index.status().embeds.pending == 0
    return engine, index


async def test_a_scope_filter_that_excludes_every_nearest_row_still_runs_hybrid(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await _vault_with_a_needle_in_a_haystack(golden_work_vault, open_index)

    results = await index.search(
        "alpha beta gamma delta epsilon",
        mode="hybrid",
        limit=1,
        filters=SearchFilters(scope="widgets"),
    )

    assert results.effective_mode == "hybrid", results.degraded_reason
    assert not results.degraded
    assert [hit.permalink for hit in results.hits] == ["widgets/zeta-omega"]


async def test_vector_mode_honours_the_filter_inside_the_knn(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await _vault_with_a_needle_in_a_haystack(golden_work_vault, open_index)

    results = await index.search(
        "alpha beta gamma delta epsilon",
        mode="vector",
        limit=3,
        filters=SearchFilters(types=("person",)),
    )

    assert results.effective_mode == "vector", results.degraded_reason
    assert results.hits, "the person notes are the only candidates, and they have vectors"
    assert all(hit.type == "person" for hit in results.hits)


async def test_an_honest_reason_when_the_filtered_notes_have_no_vectors_yet(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await _vault_with_a_needle_in_a_haystack(golden_work_vault, open_index)
    # A note that arrived after the backlog drained: indexed, not embedded.
    await engine.write_note(
        "fresh/just-now.md",
        title="Just now",
        body="alpha beta gamma delta epsilon fresh\n",
        frontmatter={"type": "note"},
    )
    assert index.status().embeds.pending > 0

    results = await index.search(
        "alpha beta gamma delta epsilon",
        mode="hybrid",
        limit=2,
        filters=SearchFilters(scope="fresh"),
    )

    assert results.degraded
    assert results.effective_mode == "fts"
    assert "matching the filter" in results.degraded_reason
    assert "no vectors are ready" not in results.degraded_reason
    assert [hit.permalink for hit in results.hits] == ["fresh/just-now"]
