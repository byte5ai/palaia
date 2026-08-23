"""FTS ranking, metadata filters and sub-note addressability."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from palaia_hub.index import SearchFilters, fts_match_expression

pytestmark = pytest.mark.anyio


async def test_build_indexes_notes_observations_and_relations(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(golden_work_vault)
    status = index.status()
    assert status.notes == len(list(golden_work_vault.rglob("*.md")))
    assert status.observations > 0
    assert status.relations > 0
    assert status.counts_by_type["project"] == 9


async def test_title_match_outranks_body_match(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(golden_work_vault)
    results = await index.search("API Gateway", mode="fts", limit=5)
    assert results.hits
    assert results.hits[0].permalink == "projects/api-gateway"


async def test_observation_hit_carries_its_synthetic_permalink(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(golden_work_vault)
    results = await index.search(
        "imperative phrasing",
        mode="fts",
        limit=10,
        filters=SearchFilters(kinds=("observation",)),
    )
    assert results.hits, "the observation line should be findable on its own"
    hit = results.hits[0]
    assert hit.kind == "observation"
    assert hit.permalink == "rules/how-to-write-commit-messages"
    # <permalink>/obs/<category-slug>/<h8> — format spec §9.2
    assert hit.ref.startswith("rules/how-to-write-commit-messages/obs/how-to-apply/")
    assert len(hit.ref.rsplit("/", 1)[-1]) == 8


async def test_relation_hit_carries_its_synthetic_permalink(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(golden_work_vault)
    results = await index.search(
        "owned_by Bob Chen",
        mode="fts",
        limit=10,
        filters=SearchFilters(kinds=("relation",)),
    )
    refs = {hit.ref for hit in results.hits}
    assert "projects/api-gateway/rel/owned-by/people/bob-chen" in refs


async def test_no_match_query_returns_nothing(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(golden_work_vault)
    results = await index.search("xyzzy-nonexistent-term-42", mode="fts", limit=10)
    assert list(results) == []


async def test_punctuation_only_query_is_a_result_not_a_crash(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(golden_work_vault)
    for query in ("", "   ", "*", '"', "NOT AND OR ( )".replace("A", "")):
        results = await index.search(query, mode="fts", limit=5)
        assert isinstance(results.hits, tuple)


async def test_fts_operators_in_user_query_are_not_fts_syntax(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(golden_work_vault)
    # A user typing FTS5 operators must get a normal search, not an error.
    results = await index.search('gateway OR "unbalanced', mode="fts", limit=5)
    assert any(hit.permalink == "projects/api-gateway" for hit in results.hits)


async def test_scope_filter_restricts_to_folder_subtree(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(golden_work_vault)
    results = await index.search(
        "vault", mode="fts", limit=50, filters=SearchFilters(scope="decisions")
    )
    assert results.hits
    assert {hit.path.split("/")[0] for hit in results.hits} == {"decisions"}


async def test_type_and_tag_filters(golden_work_vault: Path, open_index: Any) -> None:
    _, index = await open_index(golden_work_vault)
    typed = await index.search(
        "vault", mode="fts", limit=50, filters=SearchFilters(types=("decision",))
    )
    assert typed.hits
    assert {hit.type for hit in typed.hits} == {"decision"}

    tagged = await index.search(
        "vault", mode="fts", limit=50, filters=SearchFilters(tags=("adr",))
    )
    assert tagged.hits
    assert all("adr" in hit.tags for hit in tagged.hits)


async def test_exclude_types_hides_meta_notes(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(golden_work_vault)
    unfiltered = await index.search("vault", mode="fts", limit=50)
    filtered = await index.search(
        "vault", mode="fts", limit=50, filters=SearchFilters(exclude_types=("meta",))
    )
    assert any(hit.type == "meta" for hit in unfiltered.hits)
    assert all(hit.type != "meta" for hit in filtered.hits)


async def test_custom_frontmatter_key_is_a_filter(
    golden_work_vault: Path, open_index: Any
) -> None:
    """Format spec §2.1: unknown keys are indexed as searchable metadata."""
    engine, index = await open_index(golden_work_vault)
    await engine.write_note(
        "notes/quarterly-plan.md",
        body="Everything about the quarter.\n",
        title="Quarterly Plan",
        frontmatter={"type": "note", "quarter": "Q3", "owner": "alice"},
    )
    await index.reindex()
    hits = await index.search(
        "quarter", mode="fts", limit=10, filters=SearchFilters(meta=(("quarter", "Q3"),))
    )
    assert [hit.permalink for hit in hits.hits] == ["notes/quarterly-plan"]
    misses = await index.search(
        "quarter", mode="fts", limit=10, filters=SearchFilters(meta=(("quarter", "Q4"),))
    )
    assert list(misses) == []


async def test_date_filters_use_modified_then_created(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    await engine.write_note(
        "notes/dated.md",
        body="A dated note.\n",
        title="Dated",
        frontmatter={"type": "note", "created": "2026-01-01", "modified": "2026-06-15"},
    )
    await index.reindex()
    inside = await index.search(
        "dated", mode="fts", limit=10, filters=SearchFilters(since="2026-06-01")
    )
    outside = await index.search(
        "dated", mode="fts", limit=10, filters=SearchFilters(until="2026-06-01")
    )
    assert "notes/dated" in {hit.permalink for hit in inside.hits}
    assert "notes/dated" not in {hit.permalink for hit in outside.hits}


def test_match_expression_is_conjunctive_by_default() -> None:
    assert fts_match_expression("rate limit") == '"rate" AND "limit"'
    assert fts_match_expression("rate limit", operator="OR") == '"rate" OR "limit"'
    assert fts_match_expression("- / *") is None


async def test_snippet_points_at_the_matching_text(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(golden_work_vault)
    results = await index.search("disposable", mode="fts", limit=5)
    assert results.hits
    assert "disposable" in " ".join(hit.snippet.lower() for hit in results.hits)
