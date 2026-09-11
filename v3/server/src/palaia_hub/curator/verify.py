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


class VerificationScan:
    """One pass's view of which notes carry which capture ids.

    Issue #402: verifying a capture used to re-walk the vault and re-read
    every non-inbox note — per capture, per pass. The scan reads each note
    once and afterwards re-reads only what the catalog says changed
    (checksum), so a pass over twenty captures costs one read per note
    plus one per note a session actually wrote. Files stay the only truth:
    nothing here consults the search index.
    """

    def __init__(self, engine: VaultEngine) -> None:
        self._engine = engine
        self._seen: dict[str, str] = {}  # path -> checksum at last read
        self._paths: dict[str, set[str]] = {}  # path -> capture ids it carries
        self._carriers: dict[
            str, dict[str, tuple[str, bool]]
        ] = {}  # id -> path -> (permalink, is_proposal)

    @classmethod
    async def build(cls, engine: VaultEngine, *, refresh: bool = True) -> VerificationScan:
        """Scan the vault once. ``refresh=False`` trusts the engine's catalog
        (the runner refreshed it while listing the pending captures)."""
        scan = cls(engine)
        await scan.update(refresh=refresh)
        return scan

    async def update(self, *, refresh: bool = False) -> int:
        """Re-read the notes that changed since the last scan; return how many."""
        if refresh:
            await self._engine.refresh()
        catalog = dict(self._engine.catalog)
        for path in [p for p in self._seen if p not in catalog]:
            self._forget(path)
        reread = 0
        for path, entry in catalog.items():
            if path.startswith(INBOX_PREFIX):
                continue
            if self._seen.get(path) == entry.checksum:
                continue
            self._forget(path)
            note = await self._engine.read_note(path)
            self._seen[path] = note.checksum
            ids = provenance_ids(note.body)
            if ids:
                permalink = note.permalink or note.path
                proposal = path.startswith(REVIEW_PREFIX)
                self._paths[path] = ids
                for capture_id in ids:
                    self._carriers.setdefault(capture_id, {})[path] = (permalink, proposal)
            reread += 1
        return reread

    def _forget(self, path: str) -> None:
        self._seen.pop(path, None)
        for capture_id in self._paths.pop(path, ()):
            carriers = self._carriers.get(capture_id)
            if carriers is not None:
                carriers.pop(path, None)
                if not carriers:
                    del self._carriers[capture_id]

    def verify(self, capture: PendingCapture) -> Verification:
        """Classify ``capture`` from the scan (see the module docstring)."""
        notes: list[str] = []
        proposals: list[str] = []
        for permalink, proposal in self._carriers.get(capture.capture_id, {}).values():
            (proposals if proposal else notes).append(permalink)
        notes.sort()
        proposals.sort()
        if notes:
            return Verification(outcome="ingested", notes=notes, proposals=proposals)
        if proposals:
            return Verification(outcome="needs_review", proposals=proposals)
        return Verification(outcome="unverified")


async def verify_capture(engine: VaultEngine, capture: PendingCapture) -> Verification:
    """Classify ``capture``'s outcome by searching the vault for its id.

    ``inbox/`` is skipped wholesale: the capture note itself carries its own
    ``capture_id`` in frontmatter, and no other inbox entry can be evidence
    that this one was curated. One-off form of :class:`VerificationScan`;
    the runner keeps a scan for the whole pass instead.
    """
    scan = await VerificationScan.build(engine)
    return scan.verify(capture)


__all__ = ["Verification", "VerificationScan", "verify_capture"]
