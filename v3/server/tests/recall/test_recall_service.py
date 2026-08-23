"""``RecallService`` end to end over a real engine + index.

Covers what the pure-function suites cannot: value references resolved live
against the vault (not a scenario directory), per-model variants reaching the
body text and not just the observation list, and the whole recall path's
behavior on references, globs and sub-note addresses.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from recall_helpers import frozen_clock, open_vault

from palaia_hub.index import VaultIndex
from palaia_hub.recall import RecallService
from palaia_hub.recall.service import RecallError
from palaia_hub.vault import AmbiguousReferenceError, NoteNotFoundError, VaultEngine

pytestmark = pytest.mark.anyio


@pytest.fixture
async def recall(golden_work: tuple[VaultEngine, VaultIndex]) -> RecallService:
    engine, index = golden_work
    return RecallService(index, vault=engine.name, track_access=False, clock=frozen_clock())


# --------------------------------------------------------------------------
# Starting points
# --------------------------------------------------------------------------

async def test_recall_needs_a_query_or_a_ref(recall: RecallService) -> None:
    with pytest.raises(RecallError) as excinfo:
        await recall.recall()
    assert "query" in str(excinfo.value) and "ref" in str(excinfo.value)


async def test_recall_by_permalink_returns_that_note(recall: RecallService) -> None:
    result = await recall.recall(ref="memory://projects/api-gateway")
    assert [entry.permalink for entry in result.entries] == ["projects/api-gateway"]
    assert result.entries[0].title == "API Gateway"


async def test_recall_by_title_returns_that_note(recall: RecallService) -> None:
    result = await recall.recall(ref="API Gateway")
    assert [entry.permalink for entry in result.entries] == ["projects/api-gateway"]


async def test_a_ref_wins_over_a_query(recall: RecallService) -> None:
    result = await recall.recall(query="pricing", ref="projects/api-gateway")
    assert [entry.permalink for entry in result.entries] == ["projects/api-gateway"]


async def test_recall_by_glob_returns_every_match_up_to_the_limit(
    recall: RecallService,
) -> None:
    result = await recall.recall(ref="memory://glossary/*", limit=10)
    permalinks = {entry.permalink for entry in result.entries}
    assert permalinks == {"glossary/base-rate", "glossary/pricing", "glossary/pricing-summary"}


async def test_recall_of_a_missing_ref_is_a_caller_facing_error(
    recall: RecallService,
) -> None:
    with pytest.raises(NoteNotFoundError):
        await recall.recall(ref="no/such/note")


async def test_recall_of_an_empty_glob_is_a_caller_facing_error(
    recall: RecallService,
) -> None:
    # A glob matching nothing is an empty *resolution*; recall turns that
    # into an explicit "nothing matched" rather than an empty success, so a
    # model does not read silence as "the vault knows nothing".
    with pytest.raises(NoteNotFoundError):
        await recall.recall(ref="glossary/zzz-*")


async def test_recall_by_observation_ref_targets_the_observation(
    golden_work: tuple[VaultEngine, VaultIndex], recall: RecallService
) -> None:
    _, index = golden_work
    observation = index.graph.observations("glossary/base-rate")[0]
    result = await recall.recall(ref=observation.ref)
    entry = result.entries[0]
    assert entry.ref == observation.ref
    assert entry.kind == "observation"
    assert "100 req/min" in entry.snippet


async def test_meta_notes_are_excluded_from_query_recall_but_not_by_ref(
    recall: RecallService,
) -> None:
    # Format spec §6: meta is "excluded from normal recall".
    by_query = await recall.recall(query="vault manifest", limit=10)
    assert "meta/vault" not in {entry.permalink for entry in by_query.entries}
    by_ref = await recall.recall(ref="meta/vault")
    assert [entry.permalink for entry in by_ref.entries] == ["meta/vault"]


# --------------------------------------------------------------------------
# Value references resolved live (deliverable #5)
# --------------------------------------------------------------------------

async def test_an_anchored_embed_resolves_to_the_current_source_line(
    recall: RecallService,
) -> None:
    result = await recall.recall(ref="glossary/pricing")
    body = result.entries[0].body
    assert "100 req/min" in body, body
    assert "![[Base Rate#^rate-limit]]" not in body
    assert not result.entries[0].warnings


async def test_a_nested_embed_resolves_through_two_hops(recall: RecallService) -> None:
    # pricing-summary embeds Pricing, which embeds Base Rate's block.
    result = await recall.recall(ref="glossary/pricing-summary")
    assert "100 req/min" in result.entries[0].body


async def test_editing_the_source_changes_what_the_referencing_note_shows(
    golden_work: tuple[VaultEngine, VaultIndex], recall: RecallService
) -> None:
    """The whole point of read-time resolution: no stale copies anywhere."""
    engine, index = golden_work
    before = await recall.recall(ref="glossary/pricing")
    assert "100 req/min" in before.entries[0].body

    await engine.write_note(
        "glossary/base-rate.md",
        body="- [rate-limit] 250 req/min ^rate-limit",
        title="Base Rate",
        frontmatter={"type": "note", "permalink": "glossary/base-rate"},
    )
    await index.reindex()

    after = await recall.recall(ref="glossary/pricing")
    assert "250 req/min" in after.entries[0].body
    assert "100 req/min" not in after.entries[0].body


async def test_a_cycle_in_the_vault_renders_the_marker_and_warns(
    recall: RecallService,
) -> None:
    result = await recall.recall(ref="embeds/cycle-a")
    entry = result.entries[0]
    assert "⟦cycle: Cycle A → Cycle B → Cycle A⟧" in entry.body
    assert any("embed-cycle" in warning for warning in entry.warnings)


async def test_a_missing_target_renders_the_marker_and_warns(
    golden_work: tuple[VaultEngine, VaultIndex], recall: RecallService
) -> None:
    engine, index = golden_work
    await engine.write_note(
        "notes/dangling.md",
        body="Value: ![[No Such Note]]",
        title="Dangling",
        frontmatter={"type": "note"},
    )
    await index.reindex()
    result = await recall.recall(ref="notes/dangling")
    entry = result.entries[0]
    assert "⟦missing: No Such Note⟧" in entry.body
    assert any("embed-missing" in warning for warning in entry.warnings)


async def test_an_embed_inside_a_code_fence_is_left_verbatim(
    golden_work: tuple[VaultEngine, VaultIndex], recall: RecallService
) -> None:
    engine, index = golden_work
    await engine.write_note(
        "notes/documented.md",
        body="How to embed:\n\n```markdown\n![[Base Rate#^rate-limit]]\n```\n",
        title="Documented",
        frontmatter={"type": "note"},
    )
    await index.reindex()
    body = (await recall.recall(ref="notes/documented")).entries[0].body
    assert "![[Base Rate#^rate-limit]]" in body
    assert "100 req/min" not in body


async def test_a_heading_embed_resolves_to_its_section(
    golden_work: tuple[VaultEngine, VaultIndex], recall: RecallService
) -> None:
    engine, index = golden_work
    await engine.write_note(
        "notes/handbook.md",
        body="## Onboarding\n\nDay one: read the runbook.\n\n## Offboarding\n\nRevoke tokens.\n",
        title="Handbook",
        frontmatter={"type": "note"},
    )
    await engine.write_note(
        "notes/quickstart.md",
        body="Start here: ![[Handbook#Onboarding]]",
        title="Quickstart",
        frontmatter={"type": "note"},
    )
    await index.reindex()
    body = (await recall.recall(ref="notes/quickstart")).entries[0].body
    assert "Day one: read the runbook." in body
    assert "Revoke tokens." not in body


async def test_a_missing_anchor_inside_an_existing_note_is_a_missing_marker(
    golden_work: tuple[VaultEngine, VaultIndex], recall: RecallService
) -> None:
    engine, index = golden_work
    await engine.write_note(
        "notes/bad-anchor.md",
        body="Value: ![[Base Rate#^no-such-anchor]]",
        title="Bad Anchor",
        frontmatter={"type": "note"},
    )
    await index.reindex()
    entry = (await recall.recall(ref="notes/bad-anchor")).entries[0]
    assert "⟦missing: Base Rate#^no-such-anchor⟧" in entry.body
    assert any("embed-missing" in warning for warning in entry.warnings)


# --------------------------------------------------------------------------
# Per-model variants, live (deliverable #4)
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("model", "expected", "unexpected"),
    [
        (
            "anthropic/opus-5",
            "Use the extended form with a one-paragraph rationale.",
            "Prefer the compact form",
        ),
        ("openai", "Use imperative phrasing throughout.", "Prefer the compact form"),
        ("openai/gpt-5.2", "Use imperative phrasing throughout.", "Prefer the compact form"),
        ("google/gemini-3", "Prefer the compact form: subject line only.", "imperative phrasing"),
        ("", "Prefer the compact form: subject line only.", "imperative phrasing"),
    ],
)
async def test_recall_serves_one_variant_per_caller(
    recall: RecallService, model: str, expected: str, unexpected: str
) -> None:
    result = await recall.recall(ref="rules/how-to-write-commit-messages", model=model)
    entry = result.entries[0]
    assert [obs.text for obs in entry.observations] == [expected]
    # The body text is filtered too — the losing variants must not arrive as
    # prose the model then has to ignore.
    assert expected in entry.body
    assert unexpected not in entry.body


async def test_variant_filtering_leaves_a_single_line_per_group_in_the_body(
    recall: RecallService,
) -> None:
    entry = (
        await recall.recall(ref="rules/how-to-write-commit-messages", model="openai")
    ).entries[0]
    how_to_apply_lines = [
        line for line in entry.body.split("\n") if line.startswith("- [how-to-apply")
    ]
    assert len(how_to_apply_lines) == 1


async def test_a_note_with_no_variants_is_untouched(recall: RecallService) -> None:
    plain = await recall.recall(ref="rules/tool-usage-etiquette", model="openai")
    assert len(plain.entries[0].observations) == 2


async def test_variant_filtering_reaches_embedded_content(
    golden_work: tuple[VaultEngine, VaultIndex], recall: RecallService
) -> None:
    engine, index = golden_work
    await engine.write_note(
        "notes/style-guide.md",
        body="Our commit rules:\n\n![[How To Write Commit Messages]]\n",
        title="Style Guide",
        frontmatter={"type": "note"},
    )
    await index.reindex()
    body = (await recall.recall(ref="notes/style-guide", model="openai")).entries[0].body
    assert "Use imperative phrasing throughout." in body
    assert "Prefer the compact form" not in body


async def test_an_unknown_model_never_gets_a_scoped_only_group(
    golden_work: tuple[VaultEngine, VaultIndex], recall: RecallService
) -> None:
    engine, index = golden_work
    await engine.write_note(
        "rules/scoped-only.md",
        body="- [tone | anthropic] Warm.\n- [tone | openai] Terse.\n",
        title="Scoped Only",
        frontmatter={"type": "rule"},
    )
    await index.reindex()
    served = (await recall.recall(ref="rules/scoped-only", model="google/gemini-3")).entries[0]
    assert served.observations == []
    assert "Warm." not in served.body and "Terse." not in served.body
    # ...while a matching caller does get their line.
    matched = (await recall.recall(ref="rules/scoped-only", model="openai")).entries[0]
    assert [obs.text for obs in matched.observations] == ["Terse."]


# --------------------------------------------------------------------------
# Query recall
# --------------------------------------------------------------------------

async def test_query_recall_reports_the_degraded_retrieval_mode(
    recall: RecallService,
) -> None:
    # Embeddings are off in this suite, so hybrid answers from FTS and says so
    # (SPEC-104's honesty requirement, carried through recall unchanged).
    result = await recall.recall(query="api gateway")
    assert result.degraded
    assert result.degraded_reason


async def test_query_recall_respects_the_limit(recall: RecallService) -> None:
    result = await recall.recall(query="gateway", limit=2)
    assert len(result.entries) <= 2
    assert result.matched >= len(result.entries)


async def test_query_recall_considers_more_candidates_than_it_returns(
    recall: RecallService,
) -> None:
    # Otherwise decay scoring could never promote anything into the answer.
    result = await recall.recall(query="gateway", limit=1)
    assert result.matched > 1


async def test_query_recall_with_no_matches_is_an_empty_answer(
    recall: RecallService,
) -> None:
    result = await recall.recall(query="xyzzy-nonexistent-term-42")
    assert result.entries == []
    assert result.matched == 0


async def test_bodies_can_be_left_out_for_a_cheap_ranked_listing(
    recall: RecallService,
) -> None:
    result = await recall.recall(query="api gateway", include_body=False)
    assert all(entry.body == "" for entry in result.entries)
    assert any(entry.snippet for entry in result.entries)


# --------------------------------------------------------------------------
# Access counters
# --------------------------------------------------------------------------

async def test_recall_records_access_after_ranking_not_before(
    golden_work: tuple[VaultEngine, VaultIndex],
) -> None:
    engine, index = golden_work
    service = RecallService(index, vault=engine.name, clock=frozen_clock())
    before = index.graph.access(["projects/api-gateway"])["projects/api-gateway"]
    assert before.hits == 0

    first = await service.recall(query="api gateway", limit=3, include_body=False)
    after = index.graph.access(["projects/api-gateway"])["projects/api-gateway"]
    assert after.hits == 1
    assert after.last_access

    # The first call's own ranking was computed before its bump, so its
    # scores match what a fresh index would have produced.
    fresh = RecallService(index, vault=engine.name, track_access=False, clock=frozen_clock())
    again = await fresh.recall(query="api gateway", limit=3, include_body=False)
    assert [entry.permalink for entry in again.entries] == [
        entry.permalink for entry in first.entries
    ]


async def test_repeated_access_raises_a_notes_ranking(
    tmp_path: Path,
) -> None:
    root = tmp_path / "access"
    root.mkdir()
    engine, index = await open_vault(root, "access")
    try:
        # Two notes the retriever cannot tell apart on words alone.
        for slug in ("alpha", "beta"):
            await engine.write_note(
                f"notes/{slug}.md",
                body="Shared subject matter for the ranking probe.",
                title=slug.title(),
                frontmatter={"type": "note"},
            )
        await index.reindex()
        service = RecallService(index, vault="access", clock=frozen_clock())
        baseline = await service.recall(query="ranking probe", limit=2, include_body=False)
        loser = baseline.entries[-1].permalink

        # Serve the loser directly until its access term saturates, then
        # re-run the query. Access is the *smallest* of the three weights on
        # purpose, so it takes a saturated counter to flip two otherwise
        # identical notes — which is exactly what this asserts.
        for _ in range(30):
            await service.recall(ref=loser, include_body=False)
        after = await service.recall(query="ranking probe", limit=2, include_body=False)
        assert after.entries[0].permalink == loser
        assert after.entries[0].access == pytest.approx(1.0)
    finally:
        await index.close()
        await engine.close()


async def test_access_survives_a_reindex(golden_work: tuple[VaultEngine, VaultIndex]) -> None:
    # The counters are the one thing in the index that is not derivable from
    # files, so a rebuild must not wipe them (see note_access in the schema).
    engine, index = golden_work
    service = RecallService(index, vault=engine.name, clock=frozen_clock())
    await service.recall(ref="projects/api-gateway", include_body=False)
    await index.reindex()
    assert index.graph.access(["projects/api-gateway"])["projects/api-gateway"].hits == 1


# --------------------------------------------------------------------------
# resolved_body (what `read` uses)
# --------------------------------------------------------------------------

async def test_resolved_body_resolves_references_for_the_read_tool(
    recall: RecallService,
) -> None:
    resolved = await recall.resolved_body("glossary/pricing")
    assert "100 req/min" in resolved.text
    assert resolved.inlined == 1


async def test_resolved_body_of_an_ambiguous_reference_raises(tmp_path: Path) -> None:
    root = tmp_path / "amb2"
    root.mkdir()
    engine, index = await open_vault(root, "amb2")
    try:
        await engine.write_note("a/dup.md", body="One.", title="Dup", frontmatter={"type": "note"})
        await engine.write_note("b/dup.md", body="Two.", title="Dup", frontmatter={"type": "note"})
        await index.reindex()
        service = RecallService(index, vault="amb2", track_access=False)
        with pytest.raises(AmbiguousReferenceError):
            await service.resolved_body("Dup")
    finally:
        await index.close()
        await engine.close()
