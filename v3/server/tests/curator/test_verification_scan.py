"""Issue #402: verification reads each note once per pass, not once per
capture — and afterwards only what a session actually changed."""

from __future__ import annotations

import pytest

from palaia_hub.curator.models import PendingCapture
from palaia_hub.curator.policy import provenance_line
from palaia_hub.curator.verify import VerificationScan, verify_capture
from palaia_hub.vault import VaultEngine

pytestmark = pytest.mark.anyio


def _capture(capture_id: str) -> PendingCapture:
    return PendingCapture(
        vault="work",
        path=f"inbox/{capture_id}.md",
        permalink=f"inbox/{capture_id}",
        capture_id=capture_id,
        title="a capture",
        text="",
        attempts=0,
        checksum="",
    )


async def _seed(engine: VaultEngine, count: int) -> None:
    for n in range(count):
        await engine.write_note(
            f"notes/plain-{n}.md", body=f"Plain note {n}.\n", title=f"Plain {n}"
        )


async def test_a_scan_reads_each_note_once_and_then_only_what_changed(
    engine: VaultEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(engine, 5)
    reads: list[str] = []
    original = engine.read_note

    async def counting(reference: str, *args: object, **kwargs: object):  # noqa: ANN202
        reads.append(reference)
        return await original(reference, *args, **kwargs)

    monkeypatch.setattr(engine, "read_note", counting)

    non_inbox = [p for p in engine.catalog if not p.startswith("inbox/")]
    scan = await VerificationScan.build(engine)
    assert sorted(reads) == sorted(non_inbox), "the first scan reads every non-inbox note once"
    baseline = len(reads)

    # Nothing changed: verifying three captures costs zero reads.
    for capture_id in ("cap-a", "cap-b", "cap-c"):
        assert await scan.update() == 0
        assert scan.verify(_capture(capture_id)).outcome == "unverified"
    assert len(reads) == baseline

    # A session wrote one real note carrying the provenance line: one read.
    await engine.write_note(
        "projects/landed.md",
        body=f"The knowledge.\n\n{provenance_line('cap-a')}\n",
        title="Landed",
    )
    assert await scan.update() == 1
    assert len(reads) == baseline + 1
    verdict = scan.verify(_capture("cap-a"))
    assert verdict.outcome == "ingested"
    assert verdict.notes == ["projects/landed"]
    assert scan.verify(_capture("cap-b")).outcome == "unverified"


async def test_a_scan_forgets_notes_that_were_deleted_or_rewritten(engine: VaultEngine) -> None:
    await engine.write_note(
        "review/proposal.md",
        body=f"Maybe.\n\n{provenance_line('cap-x')}\n",
        title="Proposal",
    )
    scan = await VerificationScan.build(engine)
    assert scan.verify(_capture("cap-x")).outcome == "needs_review"

    # Rewritten without the provenance line: no longer evidence.
    current = await engine.read_note("review/proposal")
    await engine.edit_note(
        "review/proposal", body="Nothing to see.\n", expected_checksum=current.checksum
    )
    await scan.update()
    assert scan.verify(_capture("cap-x")).outcome == "unverified"

    await engine.write_note(
        "projects/real.md", body=f"Real.\n\n{provenance_line('cap-x')}\n", title="Real"
    )
    await scan.update()
    assert scan.verify(_capture("cap-x")).outcome == "ingested"
    await engine.delete_note("projects/real")
    await scan.update()
    assert scan.verify(_capture("cap-x")).outcome == "unverified"


async def test_the_one_off_helper_agrees_with_the_scan(engine: VaultEngine) -> None:
    await engine.write_note(
        "projects/one.md", body=f"One.\n\n{provenance_line('cap-1')}\n", title="One"
    )
    direct = await verify_capture(engine, _capture("cap-1"))
    scan = await VerificationScan.build(engine)
    assert direct == scan.verify(_capture("cap-1"))
    assert direct.outcome == "ingested"
