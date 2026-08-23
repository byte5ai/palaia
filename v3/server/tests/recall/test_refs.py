"""``memory://`` addressing (format spec §3.2), against the golden vault.

Two halves: the pure syntactic split (:func:`parse_memory_ref`) and the
ordered resolution over a real index. The resolution-order tests matter more
than they look — every tier that silently reorders is a class of "recall
answered with the wrong note" bug that no other test would catch.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from recall_helpers import open_vault

from palaia_hub.index import VaultIndex
from palaia_hub.recall.refs import MemoryResolver, parse_memory_ref
from palaia_hub.vault import AmbiguousReferenceError, NoteNotFoundError, VaultEngine

pytestmark = pytest.mark.anyio


# --------------------------------------------------------------------------
# parse_memory_ref — pure
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "target", "anchor"),
    [
        ("projects/api-gateway", "projects/api-gateway", None),
        ("memory://projects/api-gateway", "projects/api-gateway", None),
        ("MEMORY://projects/api-gateway", "projects/api-gateway", None),
        ("memory:///projects/api-gateway", "projects/api-gateway", None),
        ("  memory://projects/api-gateway/  ", "projects/api-gateway", None),
        ("glossary/base-rate#^rate-limit", "glossary/base-rate", "^rate-limit"),
        ("memory://glossary/base-rate#^rate-limit", "glossary/base-rate", "^rate-limit"),
        ("notes/handbook#Onboarding", "notes/handbook", "Onboarding"),
        ("projects/api-*", "projects/api-*", None),
        ("projects/**", "projects/**", None),
        (r"projects\api-gateway", "projects/api-gateway", None),
    ],
)
def test_parse_memory_ref_table(raw: str, target: str, anchor: str | None) -> None:
    ref = parse_memory_ref(raw)
    assert ref.target == target
    assert ref.anchor == anchor


def test_block_id_strips_the_caret_only_for_block_anchors() -> None:
    assert parse_memory_ref("a#^rate-limit").block_id == "rate-limit"
    assert parse_memory_ref("a#Heading").block_id is None


def test_glob_detection() -> None:
    assert parse_memory_ref("projects/api-*").is_glob
    assert parse_memory_ref("projects/**").is_glob
    assert not parse_memory_ref("projects/api-gateway").is_glob


@pytest.mark.parametrize("raw", ["", "   ", "memory://", "memory:///", "#^anchor"])
def test_an_empty_reference_is_a_caller_facing_error(raw: str) -> None:
    with pytest.raises(NoteNotFoundError):
        parse_memory_ref(raw)


def test_address_round_trips_without_the_scheme() -> None:
    assert parse_memory_ref("memory://a/b#^c").address == "a/b#^c"
    assert parse_memory_ref("memory://a/b").address == "a/b"


# --------------------------------------------------------------------------
# Resolution over the golden vault
# --------------------------------------------------------------------------

@pytest.fixture
def resolver(golden_work: tuple[VaultEngine, VaultIndex]) -> MemoryResolver:
    engine, index = golden_work
    return MemoryResolver(index.graph, vault=engine.name)


async def test_exact_permalink_resolves(resolver: MemoryResolver) -> None:
    resolved = resolver.resolve_one("projects/api-gateway")
    assert resolved.permalink == "projects/api-gateway"
    assert resolved.kind == "note"


async def test_exact_title_resolves_case_insensitively(resolver: MemoryResolver) -> None:
    for spelling in ("API Gateway", "api gateway", "  API GATEWAY  "):
        assert resolver.resolve_one(spelling).permalink == "projects/api-gateway"


async def test_unique_path_suffix_resolves(resolver: MemoryResolver) -> None:
    # The note lives at work/projects/api-gateway.md; its file name alone is
    # a unique suffix within this vault.
    assert resolver.resolve_one("api-gateway.md").permalink == "projects/api-gateway"
    assert resolver.resolve_one("projects/api-gateway.md").permalink == "projects/api-gateway"


async def test_the_vault_name_prefix_is_optional(resolver: MemoryResolver) -> None:
    assert resolver.resolve_one("memory://work/projects/api-gateway").permalink == (
        "projects/api-gateway"
    )


async def test_a_glob_matches_every_note_in_a_folder(resolver: MemoryResolver) -> None:
    matches = resolver.resolve("memory://projects/*")
    permalinks = [match.permalink for match in matches]
    assert "projects/api-gateway" in permalinks
    assert "projects/recall-engine" in permalinks
    assert all(permalink.startswith("projects/") for permalink in permalinks)
    # `*` stays inside one segment.
    assert all(permalink.count("/") == 1 for permalink in permalinks)


async def test_a_star_glob_does_not_cross_a_slash_but_double_star_does(
    resolver: MemoryResolver,
) -> None:
    single = {match.permalink for match in resolver.resolve("*")}
    double = {match.permalink for match in resolver.resolve("**")}
    assert single == set(), "no golden note lives at the vault root"
    assert len(double) > 20


async def test_a_prefix_glob_narrows_within_a_segment(resolver: MemoryResolver) -> None:
    matches = {match.permalink for match in resolver.resolve("projects/api-*")}
    assert matches == {"projects/api-gateway"}


async def test_a_glob_matching_nothing_is_an_empty_answer_not_an_error(
    resolver: MemoryResolver,
) -> None:
    assert resolver.resolve("projects/zzz-*") == []


async def test_a_glob_matching_several_notes_is_ambiguous_for_resolve_one(
    resolver: MemoryResolver,
) -> None:
    with pytest.raises(AmbiguousReferenceError) as excinfo:
        resolver.resolve_one("projects/*")
    # The candidates must be listed, never silently narrowed.
    assert "projects/api-gateway" in str(excinfo.value)


async def test_an_unknown_reference_names_the_resolution_order(
    resolver: MemoryResolver,
) -> None:
    with pytest.raises(NoteNotFoundError) as excinfo:
        resolver.resolve_one("no/such/note")
    message = str(excinfo.value)
    assert "permalink" in message and "alias" in message and "title" in message


async def test_a_block_anchor_resolves_to_a_block_ref(resolver: MemoryResolver) -> None:
    resolved = resolver.resolve_one("memory://glossary/base-rate#^rate-limit")
    assert resolved.kind == "block"
    assert resolved.permalink == "glossary/base-rate"
    assert resolved.anchor == "^rate-limit"
    assert resolved.ref == "glossary/base-rate#^rate-limit"


async def test_a_synthetic_observation_permalink_resolves_to_its_observation(
    golden_work: tuple[VaultEngine, VaultIndex], resolver: MemoryResolver
) -> None:
    _, index = golden_work
    observations = index.graph.observations("glossary/base-rate")
    assert observations, "the golden note carries an observation"
    resolved = resolver.resolve_one(observations[0].ref)
    assert resolved.kind == "observation"
    assert resolved.observation is not None
    assert resolved.observation.category == "rate-limit"
    assert resolved.permalink == "glossary/base-rate"


async def test_a_synthetic_relation_permalink_resolves_to_its_relation(
    golden_work: tuple[VaultEngine, VaultIndex], resolver: MemoryResolver
) -> None:
    _, index = golden_work
    edges = index.graph.neighbors("projects/recall-engine")
    outbound = [edge for edge in edges if edge.direction == "out"]
    assert outbound
    resolved = resolver.resolve_one(outbound[0].ref)
    assert resolved.kind == "relation"
    assert resolved.relation is not None
    assert resolved.permalink == "projects/recall-engine"


async def test_a_synthetic_ref_wins_over_a_note_path_that_looks_like_it(
    golden_work: tuple[VaultEngine, VaultIndex], resolver: MemoryResolver
) -> None:
    # Synthetic sub-note permalinks are matched by exact equality before any
    # note tier, so a ref ending in /obs/... can never be mistaken for a
    # deeply nested note path.
    _, index = golden_work
    ref = index.graph.observations("glossary/base-rate")[0].ref
    assert "/obs/" in ref
    assert resolver.resolve_one(ref).kind == "observation"


# --------------------------------------------------------------------------
# Ambiguity: two notes answering to one name
# --------------------------------------------------------------------------

async def test_two_notes_with_the_same_title_are_an_error_listing_both(
    tmp_path: Path,
) -> None:
    root = tmp_path / "amb"
    root.mkdir()
    engine, index = await open_vault(root, "amb")
    try:
        await engine.write_note(
            "a/pricing.md", body="One.", title="Pricing", frontmatter={"type": "note"}
        )
        await engine.write_note(
            "b/pricing.md", body="Two.", title="Pricing", frontmatter={"type": "note"}
        )
        await index.reindex()
        resolver = MemoryResolver(index.graph, vault="amb")
        with pytest.raises(AmbiguousReferenceError) as excinfo:
            resolver.resolve_one("Pricing")
        message = str(excinfo.value)
        assert "a/pricing" in message and "b/pricing" in message
        # Each permalink on its own is still unambiguous.
        assert resolver.resolve_one("a/pricing").permalink == "a/pricing"
    finally:
        await index.close()
        await engine.close()


async def test_an_alias_resolves_after_a_rename(tmp_path: Path) -> None:
    root = tmp_path / "renamed"
    root.mkdir()
    engine, index = await open_vault(root, "renamed")
    try:
        await engine.write_note(
            "notes/old-name.md", body="Body.", title="Old Name", frontmatter={"type": "note"}
        )
        await index.reindex()
        await engine.rename_entity("notes/old-name", "New Name")
        await index.reindex()
        resolver = MemoryResolver(index.graph, vault="renamed")
        # The new identity resolves...
        new = resolver.resolve_one("New Name")
        # ...and so does every string the note used to answer to (§4.2).
        assert resolver.resolve_one("Old Name").permalink == new.permalink
        assert resolver.resolve_one("notes/old-name").permalink == new.permalink
    finally:
        await index.close()
        await engine.close()
