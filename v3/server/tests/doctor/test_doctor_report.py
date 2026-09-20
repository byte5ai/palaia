"""How a doctor pass reads in a terminal (issue #296)."""

from __future__ import annotations

from palaia_hub.doctor import CheckReport, Finding, HubReport, RepairOutcome
from palaia_hub.doctor.report import render_repairs, render_report


def finding(code: str, severity: str = "warning", **kwargs: object) -> Finding:
    return Finding(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        detail=f"{code} happened",
        fix=f"do something about {code}",
        **kwargs,  # type: ignore[arg-type]
    )


def test_every_finding_prints_its_fix_beneath_it() -> None:
    report = HubReport(
        checks=(CheckReport(id="config", title="Configuration", findings=(finding("broken"),)),)
    )

    text = render_report(report)

    lines = text.splitlines()
    problem = next(index for index, line in enumerate(lines) if "broken" in line)
    assert "broken happened" in lines[problem + 1]
    assert lines[problem + 2].strip().startswith("Fix: do something about broken")


def test_a_clean_check_says_so_without_ceremony() -> None:
    report = HubReport(checks=(CheckReport(id="storage", title="Storage"),))

    text = render_report(report)

    assert "Storage — nothing to report." in text
    assert "Everything this doctor can check looks healthy." in text


def test_a_skipped_check_is_called_unknown_not_healthy() -> None:
    report = HubReport(
        checks=(CheckReport(id="search", title="Search", skipped="there is no index yet."),)
    )

    text = render_report(report)

    assert "Search — not checked: there is no index yet." in text
    assert "Those parts are unknown, not healthy." in text


def test_a_flood_of_findings_is_capped_and_says_how_many_it_hid() -> None:
    findings = tuple(finding(f"issue-{n}", "info") for n in range(12))
    report = HubReport(checks=(CheckReport(id="vaults", title="Vaults", findings=findings),))

    text = render_report(report, max_findings=3)

    assert "issue-2" in text
    assert "issue-3" not in text
    assert "… and 9 more — see `palaia-hub doctor --json`." in text


def test_repairable_findings_point_at_the_command_that_fixes_them() -> None:
    report = HubReport(
        checks=(
            CheckReport(
                id="vaults",
                title="Vaults",
                findings=(finding("orphan-temp-file", "info", repairable=True),),
            ),
        )
    )

    text = render_report(report)

    assert "1 of these can be fixed safely for you: run `palaia-hub doctor --fix`." in text


def test_repairs_report_what_was_done_and_what_was_left() -> None:
    outcomes = [
        RepairOutcome(check="vaults", code="orphan-temp-file", detail="swept it", subject="work"),
        RepairOutcome(
            check="vaults", code="git-lock-held", detail="left in place", done=False, subject="work"
        ),
    ]

    text = render_repairs(outcomes)

    assert "fixed   orphan-temp-file (work)" in text
    assert "left    git-lock-held (work)" in text
    assert "Repaired 1 of 2 item(s)." in text


def test_nothing_to_repair_says_exactly_that() -> None:
    assert render_repairs([]) == "Nothing needed fixing.\n"
