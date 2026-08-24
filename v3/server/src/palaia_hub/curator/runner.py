"""The curator runner: one capture, one session, one verified outcome.

The loop, per SPEC-206 rules 3 and 5:

1. **List the pending captures.** ``inbox/`` notes with ``type: capture`` and
   ``status: uncurated``, oldest first. An empty inbox ends the run here —
   one catalog query, no session, no cost (deliverable #5).
2. **Run one bounded session per capture** through the configured
   :class:`~palaia_hub.curator.session.SessionRunner`, with the capture id
   registered in :class:`~palaia_hub.curator.policy.ActiveCaptures` for
   exactly that session's duration, so the gateway guard knows which
   provenance the session is allowed to claim.
3. **Verify against the vault** (:mod:`palaia_hub.curator.verify`) — never
   against the session's self-report, which is recorded and ignored.
4. **Act on the verdict.** ``ingested``/``needs_review`` delete the inbox
   entry; ``unverified`` appends ``- [curation-failed] <ts>: <reason>`` to
   the capture — additive, never destructive (format spec §7) — and, on the
   third failure, stamps ``status: curation-failed`` so it stops being
   retried.
5. **Audit it** (:mod:`palaia_hub.curator.audit`): stash + bus, and a
   ``doctor.finding`` for anything that did not land.

Nothing in here is allowed to raise on a single bad capture: one unparseable
note or one failing session must not stop the rest of the run.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from ..vault import ChecksumConflictError, VaultEngine, VaultError
from .audit import CuratorAudit
from .models import (
    CaptureRecord,
    CuratorRunReport,
    PendingCapture,
    SessionResult,
    parse_self_report,
)
from .policy import ActiveCaptures
from .prompt import CURATION_NOTE_PERMALINK, build_prompt
from .session import SessionRequest, SessionRunner
from .verify import verify_capture

logger = logging.getLogger("palaia_hub.curator.runner")

#: Format spec §7's failure line: additive, never destructive.
FAILURE_PREFIX = "- [curation-failed] "

#: Format spec §7's terminal capture status after the retry cap.
FAILED_STATUS = "curation-failed"

#: SPEC-206 rule 3: "retries capped (3)".
DEFAULT_MAX_ATTEMPTS = 3

#: Format spec §8: a new proposal opens the review lifecycle.
PROPOSED_STATUS = "proposed"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def count_failures(body: str) -> int:
    """How many curation attempts this capture already survived, per its body."""
    return sum(1 for line in body.splitlines() if line.startswith(FAILURE_PREFIX))


class CuratorRunner:
    """Turns one vault's pending captures into verified vault knowledge.

    Args:
        engine: the vault's own (already opened) engine. The runner reads
            captures, deletes verified ones and appends failure lines
            through it — plain code, no model in this path.
        session_runner: how a session is launched (subprocess in production,
            a scripted stand-in in tests).
        endpoint: the curator profile's MCP URL, handed to each session.
        token: the curator token, handed to each session.
        allowed_tools: the tool names a session may call, handed to each
            session (:func:`palaia_hub.curator.profile.allowed_tool_specs`).
        audit: where outcomes are recorded. Omitted, the run is silent
            beyond its return value.
        active_captures: the binding the gateway guard reads. Pass the *same*
            instance the curator profile's middleware was built with, or the
            guard falls back to shape-only provenance checks.
        max_attempts: retries before a capture is retired (SPEC-206: 3).
        purpose: the vault's one-line purpose, for the prompt.
    """

    def __init__(
        self,
        engine: VaultEngine,
        *,
        session_runner: SessionRunner,
        endpoint: str = "",
        token: str | None = None,
        allowed_tools: Sequence[str] = (),
        audit: CuratorAudit | None = None,
        active_captures: ActiveCaptures | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        purpose: str = "",
    ) -> None:
        self._engine = engine
        self._session_runner = session_runner
        self._endpoint = endpoint
        self._token = token
        self._allowed_tools = tuple(allowed_tools)
        self._audit = audit or CuratorAudit()
        self._active_captures = active_captures or ActiveCaptures()
        self._max_attempts = max(1, max_attempts)
        self._purpose = purpose

    # ------------------------------------------------------------- discovery

    async def pending_captures(self) -> list[PendingCapture]:
        """The uncurated captures waiting in ``inbox/``, oldest first."""
        await self._engine.refresh()
        pending: list[tuple[str, PendingCapture]] = []
        for entry in list(self._engine.catalog.values()):
            if not entry.path.startswith("inbox/"):
                continue
            try:
                note = await self._engine.read_note(entry.path)
            except VaultError:  # pragma: no cover - unreadable note, skip it
                logger.warning("curator: could not read %s", entry.path)
                continue
            frontmatter = note.frontmatter
            if str(frontmatter.get("type", "note")) != "capture":
                continue
            if str(frontmatter.get("status") or "") != "uncurated":
                continue
            capture_id = str(frontmatter.get("capture_id") or "")
            if not capture_id:
                logger.warning(
                    "curator: capture %s has no capture_id; skipping (nothing to "
                    "verify against)",
                    entry.path,
                )
                continue
            created = str(frontmatter.get("created") or "")
            pending.append(
                (
                    created,
                    PendingCapture(
                        vault=self._engine.name,
                        path=entry.path,
                        permalink=note.permalink or entry.path,
                        capture_id=capture_id,
                        title=note.title,
                        text=note.text,
                        attempts=count_failures(note.body),
                        checksum=note.checksum,
                    ),
                )
            )
        pending.sort(key=lambda item: (item[0], item[1].path))
        return [capture for _, capture in pending]

    async def _curation_note(self) -> str | None:
        """The vault's own ``meta/curation.md`` rules, read live (or ``None``)."""
        try:
            note = await self._engine.read_note(CURATION_NOTE_PERMALINK)
        except VaultError:
            return None
        return note.body

    # ------------------------------------------------------------------- run

    async def run_once(self) -> CuratorRunReport:
        """Curate everything currently pending; return what happened."""
        captures = await self.pending_captures()
        report = CuratorRunReport(vault=self._engine.name, pending=len(captures))
        if not captures:
            # Deliverable #5: an empty inbox costs one catalog query.
            await self._audit.run(report)
            return report
        curation_note = await self._curation_note()
        for capture in captures:
            record = await self._curate(capture, curation_note)
            report.records.append(record)
            report.sessions += 1
        await self._audit.run(report)
        return report

    async def _curate(self, capture: PendingCapture, curation_note: str | None) -> CaptureRecord:
        prompt = build_prompt(
            vault_name=self._engine.name,
            purpose=self._purpose or (self._engine.info().purpose or "a palaia memory vault"),
            capture_id=capture.capture_id,
            capture_permalink=capture.permalink,
            capture_text=capture.text,
            curation_note=curation_note,
        )
        request = SessionRequest(
            vault=self._engine.name,
            capture_id=capture.capture_id,
            prompt=prompt,
            endpoint=self._endpoint,
            allowed_tools=self._allowed_tools,
            token=self._token,
        )
        self._active_captures.acquire(capture.capture_id)
        try:
            session = await self._session_runner.run(request)
        except Exception as exc:  # noqa: BLE001 - a broken session is an outcome
            logger.exception("curator: session for %s raised", capture.capture_id)
            session = SessionResult(exit_code=-1, stderr=f"session raised: {exc}")
        finally:
            self._active_captures.release(capture.capture_id)

        verification = await verify_capture(self._engine, capture)
        self_report = parse_self_report(session.stdout)
        record = CaptureRecord(
            vault=self._engine.name,
            capture_id=capture.capture_id,
            permalink=capture.permalink,
            outcome=verification.outcome,
            targets=verification.targets,
            attempts=capture.attempts + 1,
            self_reported=(self_report.action if self_report else ""),
            duration_seconds=round(session.duration_seconds, 3),
        )
        if record.verified:
            await self._stamp_new_proposals(verification.proposals)
            await self._retire_capture(capture)
        else:
            record = record.model_copy(
                update={
                    "reason": self._failure_reason(session),
                    "retired": capture.attempts + 1 >= self._max_attempts,
                }
            )
            await self._record_failure(capture, record.reason, retire=record.retired)
        await self._audit.capture(record)
        return record

    @staticmethod
    def _failure_reason(session: SessionResult) -> str:
        if not session.launched:
            return "the runner command could not be started"
        if session.timed_out:
            return "the session timed out"
        if session.exit_code != 0:
            detail = (session.stderr or "").strip().splitlines()
            tail = detail[-1] if detail else "no stderr"
            return f"the session exited {session.exit_code} ({tail[:200]})"
        return (
            "the session finished without leaving a note or proposal carrying "
            "this capture's provenance line"
        )

    # ---------------------------------------------------------------- effects

    async def _stamp_new_proposals(self, permalinks: Sequence[str]) -> None:
        """Give a freshly written proposal its ``status: proposed`` (format §8).

        The ``write`` tool takes a ``type`` but no ``status``, so a proposal a
        session creates arrives without one — and format spec §8 fixes the
        review lifecycle as ``proposed → approved → applied``. The runner
        stamps the opening status itself, in plain code after verification:
        the curator cannot approve anything (the guard refuses every edit of a
        ``review/`` note), and a proposal with no status at all would be
        invisible to a review queue that filters on it.
        """
        for permalink in permalinks:
            try:
                note = await self._engine.read_note(permalink)
            except VaultError:  # pragma: no cover - it was just verified
                continue
            if str(note.frontmatter.get("status") or ""):
                continue
            try:
                await self._engine.edit_note(
                    permalink,
                    frontmatter={"status": PROPOSED_STATUS},
                    expected_checksum=note.checksum,
                )
            except VaultError:  # pragma: no cover - best effort, never fatal
                logger.warning("curator: could not stamp status on %s", permalink)

    async def _retire_capture(self, capture: PendingCapture) -> None:
        """Delete a verified capture's inbox entry (rule 3: only verified ones)."""
        try:
            await self._engine.delete_note(capture.path)
        except VaultError:
            logger.exception("curator: could not delete curated capture %s", capture.path)

    async def _record_failure(self, capture: PendingCapture, reason: str, *, retire: bool) -> None:
        """Append a failure line (and, at the cap, stamp ``curation-failed``)."""
        line = f"{FAILURE_PREFIX}{_now_iso()}: {reason}"
        frontmatter = {"status": FAILED_STATUS} if retire else None
        for attempt in range(2):
            try:
                note = await self._engine.read_note(capture.path)
            except VaultError:
                logger.warning(
                    "curator: capture %s vanished before its failure could be "
                    "recorded",
                    capture.path,
                )
                return
            body = f"{note.body.rstrip(chr(10))}\n{line}\n"
            try:
                await self._engine.edit_note(
                    capture.path,
                    body=body,
                    frontmatter=frontmatter,
                    expected_checksum=note.checksum,
                )
                return
            except ChecksumConflictError:
                if attempt == 0:
                    continue  # someone wrote the capture in between; re-read once
                logger.warning(
                    "curator: could not append the failure line to %s (the note "
                    "kept changing under us)",
                    capture.path,
                )
                return
            except VaultError:
                logger.exception("curator: could not append failure line to %s", capture.path)
                return


__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "FAILED_STATUS",
    "FAILURE_PREFIX",
    "CuratorRunner",
    "count_failures",
]
