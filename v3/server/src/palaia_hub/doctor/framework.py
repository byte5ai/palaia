"""The check framework the hub-wide doctor is built from (issue #296).

:mod:`palaia_hub.vault.doctor` is the *vault-level* doctor: it knows about
one vault's files, git repository and index projection. This package is the
layer above it — the one that walks the whole hub (vaults, search, connected
clients, configuration, storage), reports every problem with the fix named,
and offers the provably-safe repairs as one action.

Three rules shape everything here, and they are the reason this is a
framework rather than one long function:

1. **A finding is data, never an exception.** The doctor reports; the caller
   (CLI, dashboard) decides. Same contract as the vault doctor's own
   :class:`~palaia_hub.vault.doctor.Finding`.
2. **No fake green.** A check that cannot honestly answer raises
   :class:`CheckSkipped` and is rendered as *skipped*, never as passing —
   the same rule :mod:`palaia_hub.modes.hardening` follows for its
   checklist. A check that crashes takes only itself down: every other
   check still runs, and the broken one reports an error saying what is
   now unchecked.
3. **Repairs are opt-in and safe.** Only a check that implements
   :class:`Repairable` can change anything, only when the caller asks
   (``palaia-hub doctor --fix``), and only for repairs that cannot lose
   data — clearing a stale lock, sweeping crash residue, rebuilding the
   disposable index, narrowing file permissions. Nothing destructive is
   ever offered as a one-click fix, however tempting.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from .context import DoctorContext

logger = logging.getLogger("palaia_hub.doctor")

#: How bad one finding is. Deliberately the same three words the vault
#: doctor uses, so a vault finding can be re-homed here without translation.
Severity = Literal["info", "warning", "error"]

#: What one check ended up saying. ``ok`` means "checked, nothing found";
#: ``skipped`` means "could not check" and is never green.
CheckStatus = Literal["ok", "info", "warning", "error", "skipped"]

_SEVERITY_RANK: dict[Severity, int] = {"info": 0, "warning": 1, "error": 2}


def worst_severity(severities: Iterable[Severity]) -> Severity | None:
    """The most severe of ``severities``, or ``None`` when there are none."""
    ranked = sorted(severities, key=lambda severity: _SEVERITY_RANK[severity])
    return ranked[-1] if ranked else None


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing the doctor noticed about this hub.

    ``fix`` is not optional and not decorative: every finding names what to
    do about it, in the caller's own terms (MASTERPLAN §5.2's "name the
    fix"). ``repairable`` says that the owning check can perform that fix
    itself, safely, when asked.
    """

    code: str
    severity: Severity
    detail: str
    fix: str
    #: What this is about — a vault key, a token id, a file path. ``None``
    #: for a finding about the hub as a whole.
    subject: str | None = None
    #: True when the owning check's :meth:`Repairable.repair` fixes this.
    repairable: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "detail": self.detail,
            "fix": self.fix,
            "subject": self.subject,
            "repairable": self.repairable,
        }


@dataclass(frozen=True, slots=True)
class CheckReport:
    """What one check found — or why it could not look."""

    id: str
    title: str
    findings: tuple[Finding, ...] = ()
    #: Why this check could not run. Set means :attr:`status` is
    #: ``"skipped"``; a skipped check is never reported as passing.
    skipped: str | None = None

    @property
    def status(self) -> CheckStatus:
        if self.skipped is not None:
            return "skipped"
        return worst_severity(finding.severity for finding in self.findings) or "ok"

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "skipped": self.skipped,
            "findings": [finding.as_dict() for finding in self.findings],
        }


@dataclass(frozen=True, slots=True)
class HubReport:
    """Every check's report from one doctor pass."""

    checks: tuple[CheckReport, ...] = ()

    @property
    def findings(self) -> tuple[Finding, ...]:
        return tuple(finding for check in self.checks for finding in check.findings)

    @property
    def status(self) -> CheckStatus:
        """The worst severity found anywhere, or ``ok`` when nothing was.

        A skipped check does not make the hub unhealthy — it makes part of
        it unknown, which :attr:`skipped` reports separately rather than
        hiding inside this one word.
        """
        return worst_severity(finding.severity for finding in self.findings) or "ok"

    @property
    def skipped(self) -> tuple[CheckReport, ...]:
        return tuple(check for check in self.checks if check.skipped is not None)

    @property
    def repairable(self) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if finding.repairable)

    def counts(self) -> dict[str, int]:
        """Findings per severity — for logs, the dashboard and tests."""
        counts = {"info": 0, "warning": 0, "error": 0}
        for finding in self.findings:
            counts[finding.severity] += 1
        return counts

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "counts": self.counts(),
            "checks": [check.as_dict() for check in self.checks],
        }


@dataclass(frozen=True, slots=True)
class RepairOutcome:
    """What one attempted repair actually did."""

    check: str
    code: str
    detail: str
    subject: str | None = None
    #: False when the repair was attempted and failed. A repair that was
    #: never needed is simply not reported.
    done: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "check": self.check,
            "code": self.code,
            "detail": self.detail,
            "subject": self.subject,
            "done": self.done,
        }


class CheckSkipped(Exception):
    """Raised by a check that cannot honestly answer.

    The message is shown to the operator as the reason, so it reads as one:
    "no OAuth database exists yet", not "store is None".
    """


class Check(Protocol):
    """One diagnosis. Stateless: everything it needs arrives in the context."""

    @property
    def id(self) -> str:
        """Stable machine name, e.g. ``"vaults"``."""

    @property
    def title(self) -> str:
        """One-line human name, e.g. ``"Vaults"``."""

    async def run(self, context: DoctorContext) -> Sequence[Finding]:
        """Diagnose, or raise :class:`CheckSkipped` if that is impossible."""
        ...


@runtime_checkable
class Repairable(Protocol):
    """A check that can also perform its own provably-safe repairs."""

    async def repair(self, context: DoctorContext) -> Sequence[RepairOutcome]:
        """Fix what is safely fixable; report only what was actually done."""
        ...


class HubDoctor:
    """Runs a set of checks over one hub, and their safe repairs on request."""

    def __init__(self, checks: Sequence[Check]) -> None:
        self.checks: tuple[Check, ...] = tuple(checks)

    async def run(self, context: DoctorContext) -> HubReport:
        """Run every check. One broken check never stops the others."""
        reports = [await self._run_one(check, context) for check in self.checks]
        report = HubReport(checks=tuple(reports))
        logger.debug("hub doctor: %s (%s)", report.status, report.counts())
        return report

    async def _run_one(self, check: Check, context: DoctorContext) -> CheckReport:
        try:
            findings = tuple(await check.run(context))
        except CheckSkipped as exc:
            return CheckReport(id=check.id, title=check.title, skipped=str(exc))
        except Exception as exc:  # noqa: BLE001 - one check must not sink the pass
            logger.exception("doctor check %r failed", check.id)
            return CheckReport(
                id=check.id,
                title=check.title,
                findings=(
                    Finding(
                        code="check-failed",
                        severity="error",
                        detail=(
                            f"the {check.id!r} check itself failed ({exc!r}), so everything "
                            f"it looks at is unchecked — not healthy, unknown."
                        ),
                        fix=(
                            "Re-run the doctor. If it keeps failing, this is a bug in palaia: "
                            "report it with the hub log around this run."
                        ),
                    ),
                ),
            )
        return CheckReport(id=check.id, title=check.title, findings=findings)

    async def repair(self, context: DoctorContext) -> list[RepairOutcome]:
        """Perform every repairable check's safe repairs.

        Nothing here is destructive, and nothing runs unless a caller asked
        for it explicitly — the doctor's default pass only ever reads.
        """
        outcomes: list[RepairOutcome] = []
        for check in self.checks:
            if not isinstance(check, Repairable):
                continue
            try:
                outcomes.extend(await check.repair(context))
            except Exception as exc:  # noqa: BLE001 - same containment as run()
                logger.exception("doctor repair %r failed", check.id)
                outcomes.append(
                    RepairOutcome(
                        check=check.id,
                        code="repair-failed",
                        detail=f"the {check.id!r} repair failed ({exc!r}); nothing was changed.",
                        done=False,
                    )
                )
        return outcomes


__all__ = [
    "Check",
    "CheckReport",
    "CheckSkipped",
    "CheckStatus",
    "Finding",
    "HubDoctor",
    "HubReport",
    "RepairOutcome",
    "Repairable",
    "Severity",
    "worst_severity",
]
