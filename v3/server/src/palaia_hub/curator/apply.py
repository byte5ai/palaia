"""Deterministic apply: approved proposals, executed by plain code (rule 4).

**No model is in this path.** A human flips a ``review/`` proposal's
``status`` to ``approved`` (in Obsidian, in the dashboard, or in the future
review-queue app — all three edit the same frontmatter field, format spec
§8), and this module executes the typed plan the proposal carries:

- the plan is a fenced ```json block (info string ``json plan``; a lone
  ```json block in the proposal is accepted too) parsed into
  :class:`~palaia_hub.curator.models.Plan`;
- every note the plan touches gets its **pre-image appended to the
  proposal** before anything is written, so the state before the change is
  recorded in the vault itself, not only in git;
- operations run in order through the vault engine — every one of them an
  attributed git commit, like any other engine write;
- **every exit path stamps a terminal status**: ``applied`` when the whole
  plan ran, ``apply-failed`` when an operation failed (with the reason
  appended to the proposal), ``manual`` when there is no machine-executable
  plan to run at all.

A proposal is never left in ``approved`` by a run that touched it: that is
what would make an apply pass silently repeat itself forever.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from ..vault import Note, VaultEngine, VaultError
from .audit import CuratorAudit
from .models import (
    AppendOp,
    ApplyReport,
    MergeOp,
    MoveOp,
    Plan,
    PlanOperation,
    ProposalResult,
    ProposalStatus,
    ReplaceBodyOp,
    RetireOp,
    RetitleOp,
)

logger = logging.getLogger("palaia_hub.curator.apply")

#: The status a human sets to queue a proposal for this pass (format spec §8).
APPROVED_STATUS = "approved"

#: Appended to a proposal when its apply run fails — additive, like every
#: other failure record in the vault.
APPLY_FAILED_PREFIX = "- [apply-failed] "

_PLAN_FENCE_RE = re.compile(
    r"^```[ \t]*json[ \t]*(?P<label>[A-Za-z0-9_-]*)[ \t]*\n(?P<body>.*?)^```",
    re.DOTALL | re.MULTILINE,
)


class PlanError(ValueError):
    """The proposal carries a plan block, but not one that can be executed."""


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_plan(body: str) -> Plan | None:
    """The proposal's typed plan, or ``None`` when it carries none.

    Raises:
        PlanError: a plan block is present but is not valid JSON, or names an
            operation this apply pass does not implement. That is a
            ``manual`` outcome, never a silent skip — the human who wrote
            the plan needs to hear about it.
    """
    blocks = [
        (match.group("label"), match.group("body")) for match in _PLAN_FENCE_RE.finditer(body or "")
    ]
    labelled = [text for label, text in blocks if label == "plan"]
    candidates = labelled or [text for label, text in blocks if not label]
    if not candidates:
        return None
    if len(candidates) > 1:
        raise PlanError(
            f"the proposal carries {len(candidates)} plan blocks; exactly one is "
            "executable. Fix: keep one ```json plan block."
        )
    try:
        payload = json.loads(candidates[0])
    except json.JSONDecodeError as exc:
        raise PlanError(f"the plan block is not valid JSON ({exc})") from exc
    if not isinstance(payload, dict):
        raise PlanError("the plan block must be a JSON object with an 'operations' list")
    try:
        return Plan.model_validate(payload)
    except ValidationError as exc:
        raise PlanError(
            f"the plan's operations are not valid ({exc.error_count()} problem(s))"
        ) from exc


def render_pre_images(notes: Mapping[str, Note]) -> str:
    """The pre-image section appended to a proposal before it is applied."""
    lines = [f"## Pre-images ({_now_iso()})", ""]
    for reference, note in notes.items():
        lines.append(f"### `{reference}` — {note.path}")
        lines.append("")
        lines.append("````markdown")
        lines.append(note.text.rstrip("\n"))
        lines.append("````")
        lines.append("")
    return "\n".join(lines)


class ProposalApplier:
    """Applies a vault's approved proposals, one deterministic pass."""

    def __init__(self, engine: VaultEngine, *, audit: CuratorAudit | None = None) -> None:
        self._engine = engine
        self._audit = audit or CuratorAudit()

    async def approved_proposals(self) -> list[Note]:
        """``review/`` notes with ``type: proposal`` and ``status: approved``."""
        await self._engine.refresh()
        found: list[Note] = []
        for entry in sorted(self._engine.catalog.values(), key=lambda e: e.path):
            if not entry.path.startswith("review/"):
                continue
            try:
                note = await self._engine.read_note(entry.path)
            except VaultError:  # pragma: no cover - unreadable note, skip it
                logger.warning("curator apply: could not read %s", entry.path)
                continue
            frontmatter = note.frontmatter
            if str(frontmatter.get("type", "note")) != "proposal":
                continue
            if str(frontmatter.get("status") or "") != APPROVED_STATUS:
                continue
            found.append(note)
        return found

    async def run_once(self) -> ApplyReport:
        proposals = await self.approved_proposals()
        report = ApplyReport(vault=self._engine.name, approved=len(proposals))
        for proposal in proposals:
            result = await self.apply(proposal)
            report.results.append(result)
            await self._audit.proposal(result)
        await self._audit.apply_pass(report)
        return report

    async def apply(self, proposal: Note) -> ProposalResult:
        """Apply one proposal; always leaves it in a terminal status."""
        permalink = proposal.permalink or proposal.path
        try:
            plan = parse_plan(proposal.body)
        except PlanError as exc:
            return await self._finish(proposal, "manual", reason=str(exc))
        if plan is None or not plan.operations:
            return await self._finish(
                proposal,
                "manual",
                reason=(
                    "no executable plan block — this proposal has to be applied by "
                    "hand, then marked applied"
                ),
            )

        try:
            await self._append_pre_images(proposal, plan)
        except VaultError as exc:
            return await self._finish(
                proposal,
                "apply-failed",
                reason=f"could not record pre-images, so nothing was applied ({exc})",
                operations=len(plan.operations),
            )

        applied = 0
        for operation in plan.operations:
            try:
                await self._execute(operation)
            except (VaultError, ValueError) as exc:
                logger.warning(
                    "curator apply: %s failed on %s: %s", permalink, operation.op, exc
                )
                return await self._finish(
                    proposal,
                    "apply-failed",
                    reason=(
                        f"operation {applied + 1} of {len(plan.operations)} "
                        f"({operation.op}) failed: {exc}"
                    ),
                    operations=len(plan.operations),
                    applied=applied,
                )
            applied += 1
        return await self._finish(
            proposal, "applied", operations=len(plan.operations), applied=applied
        )

    # ------------------------------------------------------------- internals

    async def _append_pre_images(self, proposal: Note, plan: Plan) -> None:
        pre_images: dict[str, Note] = {}
        for reference in plan.targets():
            try:
                pre_images[reference] = await self._engine.read_note(reference)
            except VaultError:
                # A plan may legitimately name a note that does not exist yet
                # (an op that creates one); there is no pre-image to record.
                continue
        if not pre_images:
            return
        current = await self._engine.read_note(proposal.path)
        body = f"{current.body.rstrip(chr(10))}\n\n{render_pre_images(pre_images)}"
        await self._engine.edit_note(
            proposal.path, body=body, expected_checksum=current.checksum
        )

    async def _execute(self, operation: PlanOperation) -> None:
        if isinstance(operation, AppendOp):
            await self._append(operation.target, operation.text)
        elif isinstance(operation, ReplaceBodyOp):
            note = await self._engine.read_note(operation.target)
            await self._engine.edit_note(
                operation.target, body=operation.body, expected_checksum=note.checksum
            )
        elif isinstance(operation, RetitleOp):
            note = await self._engine.read_note(operation.target)
            await self._engine.edit_note(
                operation.target, title=operation.title, expected_checksum=note.checksum
            )
        elif isinstance(operation, MoveOp):
            note = await self._engine.read_note(operation.target)
            filename = note.path.rsplit("/", 1)[-1]
            folder = operation.folder.strip("/")
            await self._engine.move_note(
                operation.target, f"{folder}/{filename}" if folder else filename
            )
        elif isinstance(operation, RetireOp):
            await self._engine.delete_note(operation.target)
        elif isinstance(operation, MergeOp):
            source = await self._engine.read_note(operation.source)
            await self._append(
                operation.target,
                f"\n## Merged from {source.title}\n\n{source.body.strip()}",
            )
            await self._engine.delete_note(operation.source)

    async def _append(self, reference: str, text: str) -> None:
        note = await self._engine.read_note(reference)
        body = f"{note.body.rstrip(chr(10))}\n{text}\n"
        await self._engine.edit_note(reference, body=body, expected_checksum=note.checksum)

    async def _finish(
        self,
        proposal: Note,
        status: ProposalStatus,
        *,
        reason: str = "",
        operations: int = 0,
        applied: int = 0,
    ) -> ProposalResult:
        """Stamp the terminal status on ``proposal`` and build the result.

        Runs even when the vault refuses the stamp: the caller still learns
        what happened, and a failed stamp is logged rather than swallowed —
        but it never turns a successful apply into a reported failure.
        """
        permalink = proposal.permalink or proposal.path
        frontmatter: dict[str, Any] = {"status": status}
        try:
            current = await self._engine.read_note(proposal.path)
            body = current.body
            if status == "apply-failed" and reason:
                body = f"{body.rstrip(chr(10))}\n{APPLY_FAILED_PREFIX}{_now_iso()}: {reason}\n"
            await self._engine.edit_note(
                proposal.path,
                body=body,
                frontmatter=frontmatter,
                expected_checksum=current.checksum,
            )
        except VaultError:
            logger.exception(
                "curator apply: could not stamp status %r on %s", status, permalink
            )
        return ProposalResult(
            vault=self._engine.name,
            permalink=permalink,
            status=status,
            operations=operations,
            applied=applied,
            reason=reason,
        )


__all__ = [
    "APPLY_FAILED_PREFIX",
    "APPROVED_STATUS",
    "PlanError",
    "ProposalApplier",
    "parse_plan",
    "render_pre_images",
]
