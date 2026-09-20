"""The guided doctor: diagnose the whole hub, and fix what is safe to fix.

Issue #296. ``palaia doctor`` existed in v1 and v2 and is the feature the
migration guide's gap table called out as missing; this package is its v3
core — the check framework, the checks themselves, and the rendering the
``palaia-hub doctor`` command prints. The dashboard surface consumes the
same :class:`~.framework.HubReport`.

Layering, deliberately: :mod:`palaia_hub.vault.doctor` stays the *vault*
doctor (one vault's files, git and index projection, plus the two repairs
SPEC-003 proved safe). This package is the layer above it and calls into
it — it never re-implements a vault-level check.

    from palaia_hub.doctor import HubDoctor, default_checks, open_doctor_context

    async with open_doctor_context() as context:
        report = await HubDoctor(default_checks()).run(context)
"""

from __future__ import annotations

from .checks import (
    ClientsCheck,
    ConfigCheck,
    SearchCheck,
    StorageCheck,
    VaultsCheck,
    default_checks,
)
from .context import DoctorContext, open_doctor_context
from .framework import (
    Check,
    CheckReport,
    CheckSkipped,
    CheckStatus,
    Finding,
    HubDoctor,
    HubReport,
    Repairable,
    RepairOutcome,
    Severity,
    worst_severity,
)
from .report import MAX_FINDINGS_SHOWN, render_repairs, render_report

__all__ = [
    "MAX_FINDINGS_SHOWN",
    "Check",
    "CheckReport",
    "CheckSkipped",
    "CheckStatus",
    "ClientsCheck",
    "ConfigCheck",
    "DoctorContext",
    "Finding",
    "HubDoctor",
    "HubReport",
    "RepairOutcome",
    "Repairable",
    "SearchCheck",
    "Severity",
    "StorageCheck",
    "VaultsCheck",
    "default_checks",
    "open_doctor_context",
    "render_report",
    "render_repairs",
    "worst_severity",
]
