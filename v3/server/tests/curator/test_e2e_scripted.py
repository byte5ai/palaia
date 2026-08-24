"""End-to-end, with a scripted fake runner (acceptance criterion #5).

Two journeys, both through the real pieces — the curator profile with its
middleware, the memory tool family, the vault engine, the runner's
verification, and the deterministic apply pass. Only the model is scripted.

1. capture → curated note → inbox entry gone
2. capture → proposal → a human approves it → applied
"""

from __future__ import annotations

import pytest
from harness import build_harness
from scripted import ingest_session, proposal_session

from palaia_hub.curator.apply import ProposalApplier
from palaia_hub.gateway.config import VaultMountConfig
from palaia_hub.vault import NoteNotFoundError, VaultEngine


@pytest.mark.anyio
async def test_capture_becomes_a_curated_note_and_the_inbox_empties(
    engine: VaultEngine, vault_mount: VaultMountConfig
) -> None:
    harness = build_harness(engine, vault_mount, ingest_session(vault_mount.namespace))
    capture_id = await harness.capture(
        what_it_concerns="API Gateway",
        why_keep="The limit was chosen deliberately.",
        content="We capped ingest at 100 req/min.",
    )
    [pending] = await harness.runner.pending_captures()

    report = await harness.run_once()

    assert report.ingested == 1
    note = await engine.read_note("projects/api-gateway-ingest-limit")
    assert f"- [source] inbox capture {capture_id}" in note.body
    assert "100 req/min" in note.body
    with pytest.raises(NoteNotFoundError):
        await engine.read_note(pending.path)
    # Every curator action is a git commit (MASTERPLAN §5.1).
    history = await engine.history("projects/api-gateway-ingest-limit")
    assert history


@pytest.mark.anyio
async def test_capture_becomes_a_proposal_a_human_approves_and_applies(
    engine: VaultEngine, vault_mount: VaultMountConfig
) -> None:
    # An existing note the curator must not rewrite on its own.
    await engine.write_note(
        "projects/api-gateway.md", title="API Gateway", body="The gateway.\n"
    )
    harness = build_harness(engine, vault_mount, proposal_session(vault_mount.namespace))
    await harness.capture(
        what_it_concerns="API Gateway",
        why_keep="Two notes disagree about the limit.",
        content="The ingest limit is 100 req/min, not 50.",
    )

    report = await harness.run_once()

    assert report.needs_review == 1
    proposal_path = "review/merge-the-two-rate-limit-notes.md"
    proposal = await engine.read_note(proposal_path)
    assert str(proposal.frontmatter["type"]) == "proposal"
    assert str(proposal.frontmatter["status"]) == "proposed"
    # Nothing was applied while it waited for a human.
    assert "- [limit] 100 req/min" not in (await engine.read_note("projects/api-gateway")).body

    # The human approves it — the same frontmatter field Obsidian, the
    # dashboard and the review-queue app all edit (format spec §8).
    await engine.edit_note(
        proposal_path,
        frontmatter={"status": "approved"},
        expected_checksum=proposal.checksum,
    )

    [result] = (await ProposalApplier(engine).run_once()).results

    assert result.status == "applied"
    assert "- [limit] 100 req/min" in (await engine.read_note("projects/api-gateway")).body
    applied = await engine.read_note(proposal_path)
    assert str(applied.frontmatter["status"]) == "applied"
    assert "## Pre-images" in applied.body
