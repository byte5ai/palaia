"""Rendering one doctor pass for a terminal.

Kept apart from the checks so that what the doctor *knows* and how it is
*said* can change independently — the dashboard surface will render the
same :class:`~.framework.HubReport` very differently.

Two deliberate choices in here. Findings are capped per check, because a
vault with two thousand forward references would otherwise bury the one
error that matters — the cap says how many it hid and where to see them
all. And every finding prints its ``Fix:`` line directly beneath it, rather
than collecting fixes at the end: the fix belongs to the problem.
"""

from __future__ import annotations

from collections.abc import Sequence

from .framework import CheckReport, Finding, HubReport, RepairOutcome

#: Findings shown per check before the rest are summarized as a count.
MAX_FINDINGS_SHOWN = 10

_LABELS = {"info": "note", "warning": "warning", "error": "error"}
#: Worst first, so a count line leads with what actually needs doing.
_PLURALS = {"error": "error(s)", "warning": "warning(s)", "info": "note(s)"}


def _finding_lines(finding: Finding) -> list[str]:
    subject = f" ({finding.subject})" if finding.subject else ""
    return [
        f"  {_LABELS[finding.severity]:<8}{finding.code}{subject}",
        f"           {finding.detail}",
        f"           Fix: {finding.fix}",
    ]


def _check_lines(check: CheckReport, max_findings: int) -> list[str]:
    if check.skipped is not None:
        return [f"{check.title} — not checked: {check.skipped}"]
    if not check.findings:
        return [f"{check.title} — nothing to report."]
    counts = {severity: 0 for severity in _PLURALS}
    for finding in check.findings:
        counts[finding.severity] += 1

    headline = ", ".join(
        f"{count} {_PLURALS[severity]}" for severity, count in counts.items() if count
    )
    lines = [f"{check.title} — {headline}"]
    for finding in check.findings[:max_findings]:
        lines.extend(_finding_lines(finding))
    hidden = len(check.findings) - max_findings
    if hidden > 0:
        lines.append(f"           … and {hidden} more — see `palaia-hub doctor --json`.")
    return lines


def render_report(report: HubReport, *, max_findings: int = MAX_FINDINGS_SHOWN) -> str:
    """The whole pass as plain text, ending in what to do next."""
    lines = ["palaia-hub doctor", ""]
    for check in report.checks:
        lines.extend(_check_lines(check, max_findings))
        lines.append("")
    counts = report.counts()
    if not report.findings:
        lines.append("Everything this doctor can check looks healthy.")
    else:
        summary = ", ".join(
            f"{count} {_PLURALS[severity]}" for severity, count in counts.items() if count
        )
        lines.append(f"Found {summary}.")
    if report.skipped:
        names = ", ".join(check.title for check in report.skipped)
        lines.append(f"Not checked: {names}. Those parts are unknown, not healthy.")
    repairable = report.repairable
    if repairable:
        lines.append(
            f"{len(repairable)} of these can be fixed safely for you: "
            f"run `palaia-hub doctor --fix`."
        )
    return "\n".join(lines).rstrip() + "\n"


def render_repairs(outcomes: Sequence[RepairOutcome]) -> str:
    """What ``--fix`` actually did, or an honest "nothing to fix"."""
    if not outcomes:
        return "Nothing needed fixing.\n"
    lines = ["palaia-hub doctor --fix", ""]
    for outcome in outcomes:
        marker = "fixed" if outcome.done else "left"
        subject = f" ({outcome.subject})" if outcome.subject else ""
        lines.append(f"  {marker:<8}{outcome.code}{subject}")
        lines.append(f"           {outcome.detail}")
    done = sum(1 for outcome in outcomes if outcome.done)
    lines.append("")
    lines.append(f"Repaired {done} of {len(outcomes)} item(s). Re-run the doctor to confirm.")
    return "\n".join(lines) + "\n"


__all__ = ["MAX_FINDINGS_SHOWN", "render_report", "render_repairs"]
