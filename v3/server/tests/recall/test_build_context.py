"""``build_context`` end to end: traversal, dedup, budget, degradation.

The integration half of SPEC-106's budget property test lives here: random
vaults, random budgets, and the two invariants that must hold over all of
them — the assembled package never exceeds its budget, and it never comes
back empty when matches exist. The pure half (over ``plan_budget`` alone) is
in ``test_budget.py``; both are needed, because the bound is only meaningful
if the *rendered* package obeys it too.
"""

from __future__ import annotations

import random
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from recall_helpers import frozen_clock, open_vault

from palaia_hub.index import VaultIndex
from palaia_hub.recall import RecallService
from palaia_hub.recall.budget import MIN_CONTEXT_TOKENS, estimate_tokens
from palaia_hub.recall.service import RecallError, render_context
from palaia_hub.recall.traversal import MAX_DEPTH
from palaia_hub.vault import NoteNotFoundError, VaultEngine

pytestmark = pytest.mark.anyio


@pytest.fixture
async def recall(golden_work: tuple[VaultEngine, VaultIndex]) -> RecallService:
    engine, index = golden_work
    return RecallService(index, vault=engine.name, track_access=False, clock=frozen_clock())


# --------------------------------------------------------------------------
# Starting points
# --------------------------------------------------------------------------

async def test_build_context_needs_a_starting_point(recall: RecallService) -> None:
    with pytest.raises(RecallError) as excinfo:
        await recall.build_context()
    assert "ref" in str(excinfo.value) and "query" in str(excinfo.value)


async def test_a_ref_seeds_the_walk(recall: RecallService) -> None:
    package = await recall.build_context(ref="projects/recall-engine", depth=1)
    assert package.seeds == ["projects/recall-engine"]
    permalinks = {node.permalink for node in package.nodes}
    assert "projects/recall-engine" in permalinks
    assert "projects/vault-engine" in permalinks
    assert "people/farah-al-sayed" in permalinks


async def test_a_query_seeds_the_walk_with_its_best_hits(recall: RecallService) -> None:
    package = await recall.build_context(query="api gateway", depth=1)
    assert package.seeds
    assert len(package.seeds) <= 3
    assert "projects/api-gateway" in package.seeds


async def test_a_glob_seeds_the_walk_with_every_match(recall: RecallService) -> None:
    package = await recall.build_context(ref="glossary/*", depth=0)
    assert sorted(package.seeds) == [
        "glossary/base-rate",
        "glossary/pricing",
        "glossary/pricing-summary",
    ]


async def test_a_ref_that_matches_nothing_is_a_caller_facing_error(
    recall: RecallService,
) -> None:
    with pytest.raises(NoteNotFoundError):
        await recall.build_context(ref="no/such/note")


async def test_a_query_that_matches_nothing_is_a_caller_facing_error(
    recall: RecallService,
) -> None:
    with pytest.raises(NoteNotFoundError):
        await recall.build_context(query="xyzzy-nonexistent-term-42")


# --------------------------------------------------------------------------
# Depth, dedup, cycles
# --------------------------------------------------------------------------

async def test_depth_zero_is_the_seed_alone(recall: RecallService) -> None:
    package = await recall.build_context(ref="projects/recall-engine", depth=0)
    assert [node.permalink for node in package.nodes] == ["projects/recall-engine"]
    assert package.depth == 0


async def test_greater_depth_never_returns_fewer_notes(recall: RecallService) -> None:
    sizes = []
    for depth in range(0, MAX_DEPTH + 1):
        package = await recall.build_context(
            ref="projects/recall-engine", depth=depth, max_tokens=200_000
        )
        sizes.append(len(package.nodes))
    assert sizes == sorted(sizes)


async def test_depth_is_clamped_and_reported(recall: RecallService) -> None:
    package = await recall.build_context(
        ref="projects/recall-engine", depth=99, max_tokens=200_000
    )
    assert package.depth == MAX_DEPTH


async def test_the_package_is_deduplicated(recall: RecallService) -> None:
    package = await recall.build_context(
        ref="projects/recall-engine", depth=MAX_DEPTH, max_tokens=200_000
    )
    permalinks = [node.permalink for node in package.nodes]
    assert len(permalinks) == len(set(permalinks))


async def test_a_cyclic_relation_graph_terminates(recall: RecallService) -> None:
    # embeds/cycle-a and cycle-b embed each other; the walk must not loop and
    # the resolver must render the cycle marker rather than recursing.
    package = await recall.build_context(
        ref="embeds/cycle-a", depth=MAX_DEPTH, max_tokens=200_000
    )
    assert package.nodes
    seed = package.nodes[0]
    assert seed.permalink == "embeds/cycle-a"
    assert "⟦cycle:" in seed.text


async def test_every_non_seed_node_reports_how_it_was_reached(
    recall: RecallService,
) -> None:
    package = await recall.build_context(
        ref="projects/recall-engine", depth=2, max_tokens=200_000
    )
    for node in package.nodes:
        if node.depth == 0:
            assert node.via == "" and node.parent == ""
        else:
            assert node.via, f"{node.permalink} has no edge label"
            assert node.parent, f"{node.permalink} has no parent"


async def test_seeds_come_first_and_nearer_notes_before_farther_ones(
    recall: RecallService,
) -> None:
    package = await recall.build_context(
        ref="projects/recall-engine", depth=MAX_DEPTH, max_tokens=200_000
    )
    depths = [node.depth for node in package.nodes]
    assert depths[0] == 0
    assert depths == sorted(depths), "the budget must be spent nearest-first"


# --------------------------------------------------------------------------
# Timeframe
# --------------------------------------------------------------------------

async def test_a_timeframe_narrows_the_walk_and_reports_what_it_skipped(
    tmp_path: Path,
) -> None:
    root = tmp_path / "timeframe"
    root.mkdir()
    engine, index = await open_vault(root, "timeframe")
    try:
        await engine.write_note(
            "notes/hub.md",
            body="- relates_to [[Fresh]]\n- relates_to [[Stale]]\n",
            title="Hub",
            frontmatter={"type": "note", "modified": "2026-08-22T00:00:00Z"},
        )
        await engine.write_note(
            "notes/fresh.md",
            body="Recent.",
            title="Fresh",
            frontmatter={"type": "note", "modified": "2026-08-20T00:00:00Z"},
        )
        await engine.write_note(
            "notes/stale.md",
            body="Ancient.",
            title="Stale",
            frontmatter={"type": "note", "modified": "2020-01-01T00:00:00Z"},
        )
        await index.reindex()
        service = RecallService(
            index, vault="timeframe", track_access=False, clock=frozen_clock()
        )

        wide = await service.build_context(ref="notes/hub", depth=1)
        assert {node.permalink for node in wide.nodes} == {
            "notes/hub",
            "notes/fresh",
            "notes/stale",
        }

        narrow = await service.build_context(ref="notes/hub", depth=1, timeframe="30d")
        assert {node.permalink for node in narrow.nodes} == {"notes/hub", "notes/fresh"}
        assert narrow.skipped_by_timeframe == 1
        assert narrow.timeframe == "30d"
    finally:
        await index.close()
        await engine.close()


# --------------------------------------------------------------------------
# Budget behavior
# --------------------------------------------------------------------------

async def test_a_generous_budget_includes_every_note_in_full(
    recall: RecallService,
) -> None:
    package = await recall.build_context(
        ref="projects/recall-engine", depth=2, max_tokens=200_000
    )
    assert all(node.tier == "full" for node in package.nodes)
    assert package.dropped == []
    assert not package.degraded


@pytest.fixture
async def sized_recall(tmp_path: Path) -> AsyncIterator[RecallService]:
    """A vault built to exercise all three tiers deterministically.

    ``hub`` links to one long note *with* observations (so it has a summary
    tier) and one long note *without* any (so its only fallback is a stub).
    """
    root = tmp_path / "sized"
    root.mkdir()
    engine, index = await open_vault(root, "sized")
    try:
        filler = " ".join("padding" for _ in range(1200))
        await engine.write_note(
            "notes/hub.md",
            body="- relates_to [[With Facts]]\n- relates_to [[Prose Only]]\n",
            title="Hub",
            frontmatter={"type": "note"},
        )
        await engine.write_note(
            "notes/with-facts.md",
            body=f"{filler}\n\n- [rate] 100 req/min ^rate\n- [owner] Alice\n- [note] Extra\n",
            title="With Facts",
            frontmatter={"type": "note"},
        )
        await engine.write_note(
            "notes/prose-only.md",
            body=filler,
            title="Prose Only",
            frontmatter={"type": "note"},
        )
        await index.reindex()
        yield RecallService(index, vault="sized", track_access=False, clock=frozen_clock())
    finally:
        await index.close()
        await engine.close()


async def test_a_tight_budget_summarizes_rather_than_truncating(
    sized_recall: RecallService,
) -> None:
    package = await sized_recall.build_context(ref="notes/hub", depth=1, max_tokens=400)
    assert package.degraded
    summarized = next(node for node in package.nodes if node.permalink == "notes/with-facts")
    assert summarized.tier == "summary"
    # A summary is title + key observations, and says so.
    assert "summarized to fit the token budget" in summarized.text
    assert summarized.observations
    # No prefix of the long body leaked in.
    assert "padding padding padding" not in summarized.text


async def test_the_summary_keeps_anchored_observations_first(
    sized_recall: RecallService,
) -> None:
    package = await sized_recall.build_context(ref="notes/hub", depth=1, max_tokens=400)
    summarized = next(node for node in package.nodes if node.permalink == "notes/with-facts")
    # `^rate` is the field other notes embed, so it leads the summary (§5.4).
    assert summarized.text.index("[rate]") < summarized.text.index("[owner]")


async def test_a_note_with_no_observations_degrades_to_a_stub_not_a_cut_body(
    sized_recall: RecallService,
) -> None:
    package = await sized_recall.build_context(ref="notes/hub", depth=1, max_tokens=400)
    node = next(node for node in package.nodes if node.permalink == "notes/prose-only")
    assert node.tier == "stub"
    assert "notes/prose-only" in node.text
    assert "padding" not in node.text


async def test_the_budget_is_never_exceeded_and_is_reported(
    recall: RecallService,
) -> None:
    for budget in (1, 50, MIN_CONTEXT_TOKENS, 300, 1000, 4000):
        package = await recall.build_context(
            ref="projects/recall-engine", depth=MAX_DEPTH, max_tokens=budget
        )
        assert package.requested_max_tokens == budget
        assert package.max_tokens == max(budget, MIN_CONTEXT_TOKENS)
        assert package.estimated_tokens <= package.max_tokens
        assert estimate_tokens(render_context(package)) <= package.max_tokens
        assert package.nodes, f"budget {budget} returned nothing"


async def test_the_rendered_text_is_the_text_the_estimate_covers(
    recall: RecallService,
) -> None:
    package = await recall.build_context(ref="projects/recall-engine", depth=2)
    rendered = render_context(package)
    # `estimated_tokens` is the sum of per-node estimates, each rounded up,
    # so it is never *below* the estimate of the concatenation — the budget is
    # accounted for conservatively, never optimistically.
    assert estimate_tokens(rendered) <= package.estimated_tokens
    assert package.estimated_tokens - estimate_tokens(rendered) <= len(package.nodes) + 1
    for node in package.nodes:
        assert node.text in rendered


async def test_the_walk_limit_is_reported_as_a_warning(
    golden_work: tuple[VaultEngine, VaultIndex],
) -> None:
    engine, index = golden_work
    service = RecallService(
        index, vault=engine.name, track_access=False, clock=frozen_clock(), max_nodes=3
    )
    package = await service.build_context(
        ref="projects/recall-engine", depth=MAX_DEPTH, max_tokens=200_000
    )
    assert package.walk_truncated
    assert any("walk stopped" in warning for warning in package.warnings)


async def test_variants_and_value_references_resolve_inside_a_package(
    recall: RecallService,
) -> None:
    package = await recall.build_context(ref="glossary/pricing", depth=0, max_tokens=200_000)
    assert "100 req/min" in package.nodes[0].text

    scoped = await recall.build_context(
        ref="rules/how-to-write-commit-messages",
        depth=0,
        max_tokens=200_000,
        model="openai",
    )
    assert "Use imperative phrasing throughout." in scoped.nodes[0].text
    assert "Prefer the compact form" not in scoped.nodes[0].text


# --------------------------------------------------------------------------
# The property test, over random vaults
# --------------------------------------------------------------------------

_WORDS = (
    "gateway index vault recall curator dashboard release incident secret token "
    "budget context traversal ranking decay embed anchor permalink alias observation"
).split()


def _random_vault_notes(rng: random.Random, count: int) -> list[tuple[str, str, str, str]]:
    """``(path, title, type, body)`` for a random vault of ``count`` notes."""
    titles = [f"Note {index:02d}" for index in range(count)]
    types = ["note", "decision", "rule", "process", "project", "person", "capture"]
    notes: list[tuple[str, str, str, str]] = []
    for index, title in enumerate(titles):
        paragraphs = [
            " ".join(rng.choice(_WORDS) for _ in range(rng.randint(3, 60)))
            for _ in range(rng.randint(0, 6))
        ]
        lines = list(paragraphs)
        for _ in range(rng.randint(0, 4)):
            text = " ".join(rng.choice(_WORDS) for _ in range(6))
            lines.append(f"- [{rng.choice(_WORDS)}] {text}")
        # Relations, including deliberate self-references and cycles.
        for _ in range(rng.randint(0, 4)):
            lines.append(f"- relates_to [[{rng.choice(titles)}]]")
        # An embed, sometimes dangling, sometimes cyclic.
        if rng.random() < 0.35:
            target = rng.choice([*titles, "Ghost Note"])
            lines.append(f"![[{target}]]")
        notes.append((f"notes/note-{index:02d}.md", title, rng.choice(types), "\n\n".join(lines)))
    return notes


@pytest.mark.parametrize("seed", range(8))
async def test_property_context_fits_the_budget_and_is_never_empty(
    seed: int, tmp_path: Path
) -> None:
    rng = random.Random(seed)
    root = tmp_path / f"random-{seed}"
    root.mkdir()
    engine, index = await open_vault(root, "random")
    try:
        notes = _random_vault_notes(rng, rng.randint(3, 18))
        for path, title, note_type, body in notes:
            await engine.write_note(
                path, body=body, title=title, frontmatter={"type": note_type}
            )
        await index.reindex()
        service = RecallService(
            index, vault="random", track_access=False, clock=frozen_clock()
        )

        for _ in range(6):
            seed_note = rng.choice(notes)
            budget = rng.choice([0, 1, 17, MIN_CONTEXT_TOKENS, 200, 900, 5000, 50_000])
            depth = rng.randint(0, MAX_DEPTH + 2)
            package = await service.build_context(
                ref=seed_note[1], depth=depth, max_tokens=budget
            )

            # (1) never over budget — asserted on the rendered text, not just
            #     on the bookkeeping.
            assert package.estimated_tokens <= package.max_tokens, (
                f"seed={seed} ref={seed_note[1]!r} budget={budget}: "
                f"{package.estimated_tokens} > {package.max_tokens}"
            )
            assert estimate_tokens(render_context(package)) <= package.max_tokens

            # (2) never zero results when a match exists.
            assert package.nodes, (
                f"seed={seed} ref={seed_note[1]!r} budget={budget}: empty package "
                f"for a reference that resolved"
            )

            # (3) no note appears twice, and none is cut mid-body.
            permalinks = [node.permalink for node in package.nodes]
            assert len(permalinks) == len(set(permalinks))
            for node in package.nodes:
                assert node.tier in ("full", "summary", "stub")
    finally:
        await index.close()
        await engine.close()
