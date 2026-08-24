"""Deterministic apply (SPEC-206 rule 4, acceptance criterion #3).

State machine under test: an ``approved`` proposal leaves this pass in
exactly one terminal status — ``applied``, ``apply-failed`` or ``manual`` —
never in ``approved``, and never without its pre-images recorded first.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from palaia_hub.curator.apply import (
    APPLY_FAILED_PREFIX,
    PlanError,
    ProposalApplier,
    parse_plan,
)
from palaia_hub.curator.audit import CuratorAudit
from palaia_hub.vault import NoteNotFoundError, VaultEngine

PLAN_APPEND: dict[str, Any] = {
    "operations": [
        {"op": "append", "target": "projects/api-gateway", "text": "- [limit] 100 req/min"}
    ]
}


async def _seed_note(engine: VaultEngine, path: str, title: str, body: str) -> None:
    await engine.write_note(path, title=title, body=body)


async def _proposal(
    engine: VaultEngine,
    *,
    path: str = "review/merge-rate-limits.md",
    status: str = "approved",
    plan: dict[str, Any] | None = None,
    plan_text: str | None = None,
    label: str = "plan",
) -> str:
    body = "Two notes disagree about the ingest limit; merge them.\n"
    if plan_text is not None:
        body += f"\n```json {label}\n{plan_text}\n```\n"
    elif plan is not None:
        body += f"\n```json {label}\n{json.dumps(plan)}\n```\n"
    result = await engine.write_note(
        path,
        title="Merge rate limits",
        body=body,
        frontmatter={"type": "proposal", "status": status},
    )
    assert result.note is not None
    return result.note.path


@pytest.mark.anyio
async def test_an_approved_proposal_applies_and_preserves_pre_images(
    engine: VaultEngine,
) -> None:
    await _seed_note(engine, "projects/api-gateway.md", "API Gateway", "The gateway.\n")
    path = await _proposal(engine, plan=PLAN_APPEND)
    events: list[tuple[str, dict[str, Any]]] = []
    applier = ProposalApplier(
        engine, audit=CuratorAudit(publish=lambda e, d: events.append((e, d)))
    )

    report = await applier.run_once()

    assert report.approved == 1
    [result] = report.results
    assert result.status == "applied"
    assert (result.operations, result.applied) == (1, 1)
    target = await engine.read_note("projects/api-gateway")
    assert "- [limit] 100 req/min" in target.body
    proposal = await engine.read_note(path)
    assert str(proposal.frontmatter["status"]) == "applied"
    # The pre-image of the touched note is in the proposal, before the change.
    assert "## Pre-images" in proposal.body
    assert "The gateway." in proposal.body
    assert "- [limit] 100 req/min" not in proposal.body.split("## Pre-images")[1].split(
        "````"
    )[1]
    assert "curator.proposal.applied" in [name for name, _ in events]
    # A second pass finds nothing: the terminal status ends the loop.
    assert (await applier.run_once()).approved == 0


@pytest.mark.anyio
async def test_a_failing_operation_stamps_apply_failed(engine: VaultEngine) -> None:
    path = await _proposal(
        engine,
        plan={
            "operations": [
                {"op": "append", "target": "projects/does-not-exist", "text": "- [x] y"}
            ]
        },
    )
    events: list[tuple[str, dict[str, Any]]] = []
    applier = ProposalApplier(
        engine, audit=CuratorAudit(publish=lambda e, d: events.append((e, d)))
    )

    [result] = (await applier.run_once()).results

    assert result.status == "apply-failed"
    assert result.applied == 0
    proposal = await engine.read_note(path)
    assert str(proposal.frontmatter["status"]) == "apply-failed"
    assert APPLY_FAILED_PREFIX in proposal.body
    assert "curator.proposal.apply_failed" in [name for name, _ in events]
    assert "doctor.finding" in [name for name, _ in events]


@pytest.mark.anyio
async def test_a_proposal_without_a_plan_is_manual(engine: VaultEngine) -> None:
    path = await _proposal(engine, plan=None)

    [result] = (await ProposalApplier(engine).run_once()).results

    assert result.status == "manual"
    assert "by hand" in result.reason
    assert str((await engine.read_note(path)).frontmatter["status"]) == "manual"


@pytest.mark.anyio
async def test_a_malformed_plan_is_manual_not_a_crash(engine: VaultEngine) -> None:
    path = await _proposal(engine, plan_text="{not json at all")

    [result] = (await ProposalApplier(engine).run_once()).results

    assert result.status == "manual"
    assert "not valid JSON" in result.reason
    assert str((await engine.read_note(path)).frontmatter["status"]) == "manual"


@pytest.mark.anyio
async def test_an_unknown_operation_is_manual(engine: VaultEngine) -> None:
    await _proposal(
        engine, plan={"operations": [{"op": "rm -rf", "target": "projects/x"}]}
    )

    [result] = (await ProposalApplier(engine).run_once()).results

    assert result.status == "manual"
    assert "not valid" in result.reason


@pytest.mark.anyio
async def test_only_approved_proposals_are_touched(engine: VaultEngine) -> None:
    await _seed_note(engine, "projects/api-gateway.md", "API Gateway", "The gateway.\n")
    proposed = await _proposal(
        engine, path="review/waiting.md", status="proposed", plan=PLAN_APPEND
    )
    rejected = await _proposal(
        engine, path="review/rejected.md", status="rejected", plan=PLAN_APPEND
    )

    report = await ProposalApplier(engine).run_once()

    assert report.approved == 0
    assert str((await engine.read_note(proposed)).frontmatter["status"]) == "proposed"
    assert str((await engine.read_note(rejected)).frontmatter["status"]) == "rejected"
    assert "- [limit]" not in (await engine.read_note("projects/api-gateway")).body


@pytest.mark.anyio
async def test_every_operation_kind_runs_deterministically(engine: VaultEngine) -> None:
    await _seed_note(engine, "projects/one.md", "One", "First note.\n")
    await _seed_note(engine, "projects/two.md", "Two", "Second note.\n")
    await _seed_note(engine, "projects/three.md", "Three", "Third note.\n")
    await _seed_note(engine, "projects/four.md", "Four", "Fourth note.\n")
    await _proposal(
        engine,
        plan={
            "operations": [
                {"op": "append", "target": "projects/one", "text": "- [a] appended"},
                {"op": "replace_body", "target": "projects/two", "body": "Rewritten.\n"},
                {"op": "retitle", "target": "projects/three", "title": "Three Renamed"},
                {"op": "move", "target": "projects/four", "folder": "archive"},
                {"op": "merge", "source": "projects/three", "target": "projects/one"},
            ]
        },
    )

    [result] = (await ProposalApplier(engine).run_once()).results

    assert (result.status, result.applied) == ("applied", 5)
    one = await engine.read_note("projects/one")
    assert "- [a] appended" in one.body
    assert "Merged from Three Renamed" in one.body
    assert (await engine.read_note("projects/two")).body.strip() == "Rewritten."
    with pytest.raises(NoteNotFoundError):
        await engine.read_note("projects/three")
    assert (await engine.read_note("projects/four")).path == "archive/four.md"


@pytest.mark.anyio
async def test_retire_deletes_the_named_note(engine: VaultEngine) -> None:
    await _seed_note(engine, "projects/stale.md", "Stale", "Old.\n")
    await _proposal(engine, plan={"operations": [{"op": "retire", "target": "projects/stale"}]})

    [result] = (await ProposalApplier(engine).run_once()).results

    assert result.status == "applied"
    with pytest.raises(NoteNotFoundError):
        await engine.read_note("projects/stale")


def test_parse_plan_accepts_a_lone_json_block_and_rejects_two() -> None:
    single = "text\n\n```json\n{\"operations\": []}\n```\n"
    plan = parse_plan(single)
    assert plan is not None
    assert plan.operations == []
    two = single + "\n```json\n{\"operations\": []}\n```\n"
    with pytest.raises(PlanError):
        parse_plan(two)
    assert parse_plan("no code block here") is None


def test_parse_plan_prefers_the_labelled_block() -> None:
    body = (
        "```json\n{\"operations\": [{\"op\": \"retire\", \"target\": \"a\"}]}\n```\n"
        "```json plan\n{\"operations\": [{\"op\": \"retire\", \"target\": \"b\"}]}\n```\n"
    )
    plan = parse_plan(body)
    assert plan is not None
    assert plan.targets() == ["b"]
