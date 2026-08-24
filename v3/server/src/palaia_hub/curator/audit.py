"""The curator's audit trail (SPEC-206 deliverable #4).

Every outcome lands in two places, both optional and both write-only from
here:

- **the stash** (``ops:curator.*``, SPEC-202) — the durable record: what
  happened to a capture, and when. Keyed per capture / per proposal / per
  run, so the last outcome for anything is one ``stash_get`` away.
- **the event bus** (SPEC-201) — ``curator.*`` envelopes for whoever is
  listening (the dashboard, a webhook, the future review-queue app).

Plus one rule that is not bookkeeping but the point: a capture the runner
could **not** verify also raises a ``doctor.finding`` — the hub's existing
"something needs a human" channel — so an inbox quietly filling up with
captures no session can land becomes visible without anyone reading logs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

from .models import ApplyReport, CaptureRecord, CuratorRunReport, ProposalResult

logger = logging.getLogger("palaia_hub.curator.audit")

#: ``publish(event_name, data)`` — the same narrow hook shape the rest of the
#: hub reports events through (:data:`palaia_hub.events.schema.HubEventHook`).
Publisher = Callable[[str, dict[str, Any]], None]

#: The stash namespace and key prefix the SPEC fixes: ``ops:curator.*``.
STASH_NAMESPACE = "ops"
STASH_PREFIX = "curator"


class StashLike(Protocol):
    """Just the one stash call the audit needs (:class:`palaia_hub.stash.StashService`)."""

    async def set(  # noqa: A003 - mirrors StashService.set exactly
        self,
        namespace: str,
        key: str,
        value: Any,
        *,
        ttl_seconds: float | None = ...,
        stale_after_seconds: float | None = ...,
    ) -> Any: ...


class CuratorAudit:
    """Records curator outcomes to the stash and the event bus.

    Both sinks are optional: a runner built with neither still runs, still
    curates and still reports to its caller — it just leaves no trail. That
    is what keeps the runner testable without a SQLite file or a bus.
    """

    def __init__(
        self, *, publish: Publisher | None = None, stash: StashLike | None = None
    ) -> None:
        self._publish = publish
        self._stash = stash

    # ------------------------------------------------------------------ sinks

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        if self._publish is None:
            return
        try:
            self._publish(event, data)
        except Exception:  # noqa: BLE001 - audit must never break a run
            logger.exception("curator event publish failed", extra={"event": event})

    async def _store(self, key: str, value: dict[str, Any]) -> None:
        if self._stash is None:
            return
        try:
            await self._stash.set(STASH_NAMESPACE, f"{STASH_PREFIX}.{key}", value)
        except Exception:  # noqa: BLE001 - audit must never break a run
            logger.exception("curator stash write failed", extra={"key": key})

    # ---------------------------------------------------------------- records

    async def capture(self, record: CaptureRecord) -> None:
        """Record one capture's outcome; unverified also raises a finding."""
        data = record.model_dump()
        self._emit(f"curator.capture.{record.outcome}", data)
        await self._store(f"capture.{record.capture_id}", data)
        if record.retired:
            self._emit("curator.capture.retired", data)
        if record.outcome == "unverified":
            self._emit(
                "doctor.finding",
                {
                    "vault": record.vault,
                    "permalink": record.permalink,
                    "code": "curation-unverified",
                    "severity": "error" if record.retired else "warning",
                    "detail": (
                        f"capture {record.capture_id} was not verified in the vault "
                        f"after attempt {record.attempts}: {record.reason}"
                    ),
                    "fix": (
                        "curate it by hand, or fix what stopped the curator and let "
                        "the next run retry it"
                        if not record.retired
                        else "this capture is retired (status: curation-failed) and "
                        "will not be retried — curate it by hand"
                    ),
                },
            )

    async def run(self, report: CuratorRunReport) -> None:
        data = report.model_dump()
        data["summary"] = report.summary()
        self._emit("curator.run.finished", {"vault": report.vault, **data})
        await self._store(f"run.{report.vault}", data)

    async def proposal(self, result: ProposalResult) -> None:
        data = result.model_dump()
        event = {
            "applied": "curator.proposal.applied",
            "apply-failed": "curator.proposal.apply_failed",
            "manual": "curator.proposal.manual",
        }[result.status]
        self._emit(event, data)
        await self._store(f"proposal.{result.permalink}", data)
        if result.status == "apply-failed":
            self._emit(
                "doctor.finding",
                {
                    "vault": result.vault,
                    "permalink": result.permalink,
                    "code": "proposal-apply-failed",
                    "severity": "error",
                    "detail": f"applying the approved proposal failed: {result.reason}",
                    "fix": (
                        "read the proposal's pre-images, finish or revert the change "
                        "by hand, then set its status to applied or rejected"
                    ),
                },
            )

    async def apply_pass(self, report: ApplyReport) -> None:
        data = report.model_dump()
        data["summary"] = report.summary()
        await self._store(f"apply.{report.vault}", data)


__all__ = ["STASH_NAMESPACE", "STASH_PREFIX", "CuratorAudit", "Publisher", "StashLike"]
