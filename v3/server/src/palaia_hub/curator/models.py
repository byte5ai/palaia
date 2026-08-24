"""Data shapes the curator runner and the apply pass exchange (SPEC-206).

Everything here is a plain pydantic model or dataclass: the runner's report
is what the CLI prints, what the stash audit stores (``ops:curator.*``) and
what the bus event carries, so it has exactly one definition.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

#: How a capture's session ended, decided by verification and nothing else
#: (SPEC-206 rule 3):
#:
#: - ``ingested`` — a real vault note carries the capture id.
#: - ``needs_review`` — only a ``review/`` proposal carries it.
#: - ``unverified`` — nothing does; the capture stays, with an additive
#:   failure line appended.
CaptureOutcome = Literal["ingested", "needs_review", "unverified"]

#: Terminal statuses an apply run stamps on a proposal (format spec §8).
ProposalStatus = Literal["applied", "apply-failed", "manual"]


@dataclass(frozen=True, slots=True)
class PendingCapture:
    """One uncurated ``inbox/`` capture, as the runner found it."""

    vault: str
    path: str
    permalink: str
    capture_id: str
    title: str
    text: str
    attempts: int = 0
    checksum: str = ""


class SelfReport(BaseModel):
    """The model's own last-line JSON — recorded, never trusted."""

    model_config = ConfigDict(extra="allow")

    action: str = ""
    targets: list[str] = Field(default_factory=list)
    summary: str = ""
    reason: str = ""


def parse_self_report(stdout: str) -> SelfReport | None:
    """The last parseable JSON object in ``stdout``, or ``None``.

    Scanned from the end backwards because the prompt asks for the JSON as
    the *last* line, and a chatty session may have printed other braces
    earlier. A malformed or missing report is not an error: the outcome comes
    from verification either way (and a session that reports nothing at all
    but did the work still counts as ``ingested``).
    """
    for line in reversed((stdout or "").strip().splitlines()):
        candidate = line.strip().strip("`").strip()
        if not candidate.startswith("{") or not candidate.endswith("}"):
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        try:
            return SelfReport.model_validate(payload)
        except ValidationError:
            continue
    return None


@dataclass(frozen=True, slots=True)
class SessionResult:
    """What one bounded LLM session did, mechanically speaking."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_seconds: float = 0.0
    launched: bool = True

    @property
    def failed(self) -> bool:
        return self.timed_out or self.exit_code != 0


class CaptureRecord(BaseModel):
    """One capture's outcome — the audit unit (stash + event payload)."""

    model_config = ConfigDict(extra="forbid")

    vault: str
    capture_id: str
    permalink: str
    outcome: CaptureOutcome
    targets: list[str] = Field(default_factory=list)
    attempts: int = 0
    retired: bool = False
    reason: str = ""
    self_reported: str = ""
    duration_seconds: float = 0.0

    @property
    def verified(self) -> bool:
        """Did this outcome earn the inbox entry's removal (rule 3)?"""
        return self.outcome in ("ingested", "needs_review")


class CuratorRunReport(BaseModel):
    """One ``curator run`` pass over one vault."""

    model_config = ConfigDict(extra="forbid")

    vault: str
    pending: int = 0
    sessions: int = 0
    records: list[CaptureRecord] = Field(default_factory=list)

    @property
    def ingested(self) -> int:
        return sum(1 for r in self.records if r.outcome == "ingested")

    @property
    def needs_review(self) -> int:
        return sum(1 for r in self.records if r.outcome == "needs_review")

    @property
    def unverified(self) -> int:
        return sum(1 for r in self.records if r.outcome == "unverified")

    def summary(self) -> str:
        if not self.pending:
            return f"{self.vault}: inbox empty, no session started."
        return (
            f"{self.vault}: {self.pending} pending, {self.sessions} session(s) — "
            f"{self.ingested} ingested, {self.needs_review} needs-review, "
            f"{self.unverified} unverified "
            f"({sum(1 for r in self.records if r.retired)} retired)."
        )


# --- the proposal plan (format spec §8) ------------------------------------


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppendOp(_Op):
    """Append text to an existing note (the only additive maintenance op)."""

    op: Literal["append"]
    target: str
    text: str


class ReplaceBodyOp(_Op):
    """Replace a note's whole body with ``body``."""

    op: Literal["replace_body"]
    target: str
    body: str


class RetitleOp(_Op):
    """Change a note's title (its permalink stays, format spec §4.2)."""

    op: Literal["retitle"]
    target: str
    title: str


class MoveOp(_Op):
    """Move a note's file into ``folder``; the permalink does not change."""

    op: Literal["move"]
    target: str
    folder: str


class RetireOp(_Op):
    """Delete a note. Reversible through git, like every other engine write."""

    op: Literal["retire"]
    target: str


class MergeOp(_Op):
    """Append ``source``'s body onto ``target``, then retire ``source``."""

    op: Literal["merge"]
    source: str
    target: str


PlanOperation = Annotated[
    AppendOp | ReplaceBodyOp | RetitleOp | MoveOp | RetireOp | MergeOp,
    Field(discriminator="op"),
]


class Plan(BaseModel):
    """A proposal's typed plan: what the apply pass will execute, in order."""

    model_config = ConfigDict(extra="forbid")

    operations: list[PlanOperation] = Field(default_factory=list)

    def targets(self) -> list[str]:
        """Every note this plan touches, in first-mention order, deduplicated."""
        seen: list[str] = []
        for op in self.operations:
            refs = [op.source, op.target] if isinstance(op, MergeOp) else [op.target]
            for ref in refs:
                if ref not in seen:
                    seen.append(ref)
        return seen


class ProposalResult(BaseModel):
    """What one approved proposal's apply attempt did."""

    model_config = ConfigDict(extra="forbid")

    vault: str
    permalink: str
    status: ProposalStatus
    operations: int = 0
    applied: int = 0
    reason: str = ""


class ApplyReport(BaseModel):
    """One ``curator apply`` pass over one vault."""

    model_config = ConfigDict(extra="forbid")

    vault: str
    approved: int = 0
    results: list[ProposalResult] = Field(default_factory=list)

    def summary(self) -> str:
        if not self.approved:
            return f"{self.vault}: no approved proposals."
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.status] = counts.get(result.status, 0) + 1
        rendered = ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
        return f"{self.vault}: {self.approved} approved proposal(s) — {rendered}."


__all__ = [
    "AppendOp",
    "ApplyReport",
    "CaptureOutcome",
    "CaptureRecord",
    "CuratorRunReport",
    "MergeOp",
    "MoveOp",
    "PendingCapture",
    "Plan",
    "PlanOperation",
    "ProposalResult",
    "ProposalStatus",
    "ReplaceBodyOp",
    "RetireOp",
    "RetitleOp",
    "SelfReport",
    "SessionResult",
    "parse_self_report",
]
