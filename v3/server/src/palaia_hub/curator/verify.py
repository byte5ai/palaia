"""Verification, not trust (SPEC-206 rule 3).

A session's own report is a claim. This module is the check: after the
session ends, look for the capture's provenance line
(:func:`palaia_hub.curator.policy.provenance_line`) in the vault itself and
classify from what is actually on disk —

- a **real note** carries it → ``ingested``
- only a ``review/`` **proposal** carries it → ``needs_review``
- **nothing** carries it → ``unverified``

The scan reads files through the engine rather than querying the search
index: the index is a derived, eventually-consistent view (its embed backlog
drains in the background), and a capture must never be deleted because a
stale index happened to say the work landed. Files are the only truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..vault import VaultEngine
from .models import CaptureOutcome, PendingCapture
from .policy import INBOX_PREFIX, REVIEW_PREFIX, provenance_ids


@dataclass(frozen=True, slots=True)
class Verification:
    """What the vault says happened, independent of what the session said."""

    outcome: CaptureOutcome
    notes: list[str] = field(default_factory=list)
    proposals: list[str] = field(default_factory=list)

    @property
    def targets(self) -> list[str]:
        return [*self.notes, *self.proposals]


async def verify_capture(engine: VaultEngine, capture: PendingCapture) -> Verification:
    """Classify ``capture``'s outcome by searching the vault for its id.

    ``inbox/`` is skipped wholesale: the capture note itself carries its own
    ``capture_id`` in frontmatter, and no other inbox entry can be evidence
    that this one was curated.
    """
    await engine.refresh()
    notes: list[str] = []
    proposals: list[str] = []
    for entry in list(engine.catalog.values()):
        if entry.path.startswith(INBOX_PREFIX):
            continue
        note = await engine.read_note(entry.path)
        if capture.capture_id not in note.text:
            continue
        if capture.capture_id not in provenance_ids(note.body):
            # The id appears, but not as a provenance line — prose mentioning
            # a capture id is not evidence that the knowledge landed.
            continue
        permalink = note.permalink or note.path
        if entry.path.startswith(REVIEW_PREFIX):
            proposals.append(permalink)
        else:
            notes.append(permalink)
    notes.sort()
    proposals.sort()
    if notes:
        return Verification(outcome="ingested", notes=notes, proposals=proposals)
    if proposals:
        return Verification(outcome="needs_review", proposals=proposals)
    return Verification(outcome="unverified")


__all__ = ["Verification", "verify_capture"]
