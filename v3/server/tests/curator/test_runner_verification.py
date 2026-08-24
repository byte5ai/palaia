"""Verification, retries and retirement (SPEC-206 rule 3, criteria #2 and #4).

The point of every test in here: the outcome comes from the **vault**, never
from what the session said about itself.
"""

from __future__ import annotations

import pytest
from harness import build_harness
from scripted import ingest_session, lying_session, proposal_session, silent_session

from palaia_hub.curator.runner import FAILED_STATUS, FAILURE_PREFIX, count_failures
from palaia_hub.gateway.config import VaultMountConfig
from palaia_hub.vault import NoteNotFoundError, VaultEngine

CAPTURE = {
    "what_it_concerns": "API Gateway",
    "why_keep": "The limit was chosen deliberately; future work will trip over it.",
    "content": "We capped ingest at 100 req/min because the embed queue saturates.",
}


async def _capture(harness) -> str:  # noqa: ANN001 - test helper over the harness
    return await harness.capture(**CAPTURE)


@pytest.mark.anyio
async def test_a_real_note_carrying_the_capture_id_is_ingested(
    engine: VaultEngine, vault_mount: VaultMountConfig
) -> None:
    harness = build_harness(engine, vault_mount, ingest_session(vault_mount.namespace))
    await _capture(harness)
    [pending] = await harness.runner.pending_captures()

    report = await harness.run_once()

    assert report.pending == 1
    assert report.sessions == 1
    [record] = report.records
    assert record.outcome == "ingested"
    assert record.targets == ["projects/api-gateway-ingest-limit"]
    # Only a verified outcome deletes the inbox entry (rule 3).
    assert pending.path.startswith("inbox/")
    with pytest.raises(NoteNotFoundError):
        await engine.read_note(pending.path)
    assert await harness.runner.pending_captures() == []
    assert "curator.capture.ingested" in harness.event_names()


@pytest.mark.anyio
async def test_only_a_proposal_carrying_it_means_needs_review(
    engine: VaultEngine, vault_mount: VaultMountConfig
) -> None:
    harness = build_harness(engine, vault_mount, proposal_session(vault_mount.namespace))
    await _capture(harness)

    report = await harness.run_once()

    [record] = report.records
    assert record.outcome == "needs_review"
    assert record.targets == ["review/merge-the-two-rate-limit-notes"]
    # A proposal is a first-class outcome: the capture is done, not retried.
    assert await harness.runner.pending_captures() == []
    assert "curator.capture.needs_review" in harness.event_names()


@pytest.mark.anyio
async def test_a_lying_session_is_unverified_and_keeps_its_capture(
    engine: VaultEngine, vault_mount: VaultMountConfig
) -> None:
    """Criterion #2: the runner ignores the model's self-report."""
    harness = build_harness(
        engine,
        vault_mount,
        lying_session(vault_mount.namespace),
        stdout='{"action":"ingested","targets":["projects/whatever"],"summary":"done"}',
    )
    await _capture(harness)

    report = await harness.run_once()

    [record] = report.records
    assert record.self_reported == "ingested"  # what it claimed
    assert record.outcome == "unverified"  # what actually happened
    assert record.targets == []
    assert not record.retired
    # Both forbidden calls the script tried were refused at the gateway.
    assert [is_error for _, _, is_error, _ in harness.session_runner.calls] == [True, True]
    # The capture survives, with an additive failure line.
    pending = await harness.runner.pending_captures()
    assert len(pending) == 1
    assert pending[0].attempts == 1
    note = await engine.read_note(pending[0].path)
    assert FAILURE_PREFIX in note.body
    assert "curator.capture.unverified" in harness.event_names()
    assert "doctor.finding" in harness.event_names()


@pytest.mark.anyio
async def test_prose_mentioning_the_capture_id_is_not_evidence(
    engine: VaultEngine, vault_mount: VaultMountConfig
) -> None:
    harness = build_harness(engine, vault_mount, silent_session())
    capture_id = await _capture(harness)
    # A note that names the capture id without the provenance line.
    await engine.write_note(
        "projects/hearsay.md",
        title="Hearsay",
        body=f"Someone mentioned {capture_id} in passing.\n",
    )

    report = await harness.run_once()

    assert report.records[0].outcome == "unverified"


@pytest.mark.anyio
async def test_three_strikes_retires_the_capture_additively(
    engine: VaultEngine, vault_mount: VaultMountConfig
) -> None:
    """Criterion #4: 3-strikes retirement, failure notes appended additively."""
    harness = build_harness(engine, vault_mount, silent_session(), max_attempts=3)
    capture_id = await _capture(harness)
    [pending] = await harness.runner.pending_captures()
    path = pending.path

    outcomes = []
    for _ in range(3):
        report = await harness.run_once()
        outcomes.append((report.records[0].attempts, report.records[0].retired))

    assert outcomes == [(1, False), (2, False), (3, True)]
    note = await engine.read_note(path)
    # Every attempt left its own line, and none overwrote an earlier one.
    assert count_failures(note.body) == 3
    assert str(note.frontmatter["status"]) == FAILED_STATUS
    # The capture's original content is untouched.
    assert capture_id in note.text
    assert CAPTURE["content"] in note.body
    # A retired capture is no longer pending, so a fourth run starts no session.
    assert await harness.runner.pending_captures() == []
    fourth = await harness.run_once()
    assert fourth.pending == 0
    assert len(harness.session_runner.requests) == 3
    assert "curator.capture.retired" in harness.event_names()


@pytest.mark.anyio
async def test_an_empty_inbox_starts_no_session(
    engine: VaultEngine, vault_mount: VaultMountConfig
) -> None:
    """Deliverable #5: an empty inbox costs (almost) nothing."""
    harness = build_harness(engine, vault_mount, ingest_session(vault_mount.namespace))

    report = await harness.run_once()

    assert report.pending == 0
    assert report.sessions == 0
    assert report.records == []
    assert harness.session_runner.requests == []
    assert report.summary().endswith("inbox empty, no session started.")


@pytest.mark.anyio
async def test_the_session_is_bound_to_its_own_capture(
    engine: VaultEngine, vault_mount: VaultMountConfig
) -> None:
    """The provenance guard knows which capture the session was handed."""
    namespace = vault_mount.namespace

    async def script(client, request) -> None:  # noqa: ANN001 - test script
        # Citing a different capture is refused...
        await client.call_tool(
            f"{namespace}_write",
            {"title": "Wrong provenance", "body": "- [source] inbox capture cap-0000000000"},
        )
        # ...citing its own is not.
        await client.call_tool(
            f"{namespace}_write",
            {
                "title": "Right provenance",
                "body": f"- [source] inbox capture {request.capture_id}",
                "folder": "projects",
            },
        )

    harness = build_harness(engine, vault_mount, script)
    await _capture(harness)

    report = await harness.run_once()

    refused, allowed = harness.session_runner.calls
    assert refused[2] is True
    assert "this session is curating" in refused[3]
    assert allowed[2] is False
    assert report.records[0].outcome == "ingested"
    # The binding is released once the session is over.
    assert harness.active_captures.current() == frozenset()


@pytest.mark.anyio
async def test_stash_audit_records_every_outcome(
    engine: VaultEngine, vault_mount: VaultMountConfig
) -> None:
    """Deliverable #4: outcomes reach ``ops:curator.*``."""
    harness = build_harness(engine, vault_mount, ingest_session(vault_mount.namespace))
    capture_id = await _capture(harness)

    await harness.run_once()

    keys = set(harness.stash.entries)
    assert ("ops", f"curator.capture.{capture_id}") in keys
    assert ("ops", "curator.run.work") in keys
    assert harness.stash.entries[("ops", f"curator.capture.{capture_id}")]["outcome"] == (
        "ingested"
    )
