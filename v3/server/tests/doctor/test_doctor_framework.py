"""The check framework's three promises (issue #296).

A check that cannot answer is never green; a check that crashes takes only
itself down; and nothing repairs anything unless it was asked to.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from palaia_hub.doctor import (
    CheckSkipped,
    DoctorContext,
    Finding,
    HubDoctor,
    Repairable,
    RepairOutcome,
    worst_severity,
)

pytestmark = pytest.mark.anyio


class _Fine:
    id = "fine"
    title = "Fine"

    async def run(self, context: DoctorContext) -> Sequence[Finding]:
        return [Finding(code="hello", severity="info", detail="all good", fix="nothing to do")]


class _Loud:
    id = "loud"
    title = "Loud"

    async def run(self, context: DoctorContext) -> Sequence[Finding]:
        return [
            Finding(code="bad", severity="error", detail="broken", fix="fix it"),
            Finding(code="meh", severity="warning", detail="odd", fix="look at it"),
        ]


class _Skips:
    id = "skips"
    title = "Skips"

    async def run(self, context: DoctorContext) -> Sequence[Finding]:
        raise CheckSkipped("there is no database to look at yet.")


class _Boom:
    id = "boom"
    title = "Boom"

    async def run(self, context: DoctorContext) -> Sequence[Finding]:
        raise RuntimeError("kaboom")


class _Repairs:
    id = "repairs"
    title = "Repairs"

    def __init__(self) -> None:
        self.repaired = 0

    async def run(self, context: DoctorContext) -> Sequence[Finding]:
        return [Finding(code="fixable", severity="warning", detail="d", fix="f", repairable=True)]

    async def repair(self, context: DoctorContext) -> Sequence[RepairOutcome]:
        self.repaired += 1
        return [RepairOutcome(check=self.id, code="fixable", detail="did the thing")]


class _BadRepair:
    id = "bad-repair"
    title = "Bad repair"

    async def run(self, context: DoctorContext) -> Sequence[Finding]:
        return []

    async def repair(self, context: DoctorContext) -> Sequence[RepairOutcome]:
        raise RuntimeError("the repair itself broke")


async def test_a_skipped_check_is_never_reported_as_passing(context: DoctorContext) -> None:
    report = await HubDoctor([_Skips()]).run(context)

    (check,) = report.checks
    assert check.status == "skipped"
    assert check.skipped == "there is no database to look at yet."
    assert report.skipped == (check,)
    # No findings, but that must not read as a healthy hub either: the
    # overall status is "ok" only because nothing was *found*, and the
    # skipped list is what stops that being mistaken for "all checked".
    assert not report.findings


async def test_a_crashing_check_takes_only_itself_down(context: DoctorContext) -> None:
    report = await HubDoctor([_Boom(), _Fine()]).run(context)

    boom, fine = report.checks
    assert [finding.code for finding in fine.findings] == ["hello"]
    (failure,) = boom.findings
    assert failure.code == "check-failed"
    assert failure.severity == "error"
    assert "unchecked" in failure.detail
    assert "kaboom" in failure.detail


async def test_status_and_counts_follow_the_worst_finding(context: DoctorContext) -> None:
    report = await HubDoctor([_Fine(), _Loud()]).run(context)

    assert report.status == "error"
    assert report.counts() == {"info": 1, "warning": 1, "error": 1}


async def test_a_clean_pass_is_ok(context: DoctorContext) -> None:
    report = await HubDoctor([_BadRepair()]).run(context)

    assert report.status == "ok"
    assert report.counts() == {"info": 0, "warning": 0, "error": 0}


async def test_repairs_run_only_when_asked_and_only_for_repairable_checks(
    context: DoctorContext,
) -> None:
    repairs = _Repairs()
    doctor = HubDoctor([_Fine(), repairs])

    report = await doctor.run(context)
    assert repairs.repaired == 0, "a plain doctor pass must never change anything"
    assert [finding.code for finding in report.repairable] == ["fixable"]

    outcomes = await doctor.repair(context)
    assert repairs.repaired == 1
    assert [outcome.code for outcome in outcomes] == ["fixable"]
    assert all(outcome.done for outcome in outcomes)


async def test_a_failing_repair_is_reported_not_raised(context: DoctorContext) -> None:
    outcomes = await HubDoctor([_BadRepair()]).repair(context)

    (outcome,) = outcomes
    assert outcome.code == "repair-failed"
    assert outcome.done is False
    assert "nothing was changed" in outcome.detail


def test_a_check_without_a_repair_is_not_repairable() -> None:
    assert not isinstance(_Fine(), Repairable)
    assert isinstance(_Repairs(), Repairable)


async def test_the_whole_report_serializes_to_json(context: DoctorContext) -> None:
    report = await HubDoctor([_Loud(), _Skips()]).run(context)

    payload = json.loads(json.dumps(report.as_dict()))

    assert payload["status"] == "error"
    assert payload["counts"]["error"] == 1
    assert [check["id"] for check in payload["checks"]] == ["loud", "skips"]
    assert payload["checks"][1]["status"] == "skipped"
    assert payload["checks"][0]["findings"][0]["fix"] == "fix it"


def test_worst_severity_of_nothing_is_none() -> None:
    assert worst_severity([]) is None
    assert worst_severity(["info", "error", "warning"]) == "error"
