"""The curator (SPEC-206): inbox captures become vault knowledge.

The asynchronous half of palaia's two write paths (MASTERPLAN §5.1). An
agent drops a capture mid-work; later, unattended, the curator turns that
capture into a well-placed note — or, when placing it would mean rewriting
what already exists, into a ``review/`` proposal a human approves.

The package's shape follows the policy, which is fixed in the SPEC:

- :mod:`~palaia_hub.curator.policy` — the binding rules as pure functions
  (the tool surface, the write guards, the provenance requirement).
- :mod:`~palaia_hub.curator.middleware` / :mod:`~palaia_hub.curator.profile`
  — where those rules are enforced: the curator's own gateway profile.
- :mod:`~palaia_hub.curator.prompt` — the SPEC's role block, plus the
  vault's own ``meta/curation.md`` rules and the capture itself.
- :mod:`~palaia_hub.curator.session` — how one bounded session is launched
  (a config-driven, provider-neutral command).
- :mod:`~palaia_hub.curator.verify` / :mod:`~palaia_hub.curator.runner` —
  verification instead of trust, retries, and retirement.
- :mod:`~palaia_hub.curator.apply` — approved proposals, applied by plain
  code with no model in the path.
- :mod:`~palaia_hub.curator.service` — when it all runs (events, debounced,
  plus an interval fallback).
"""

from __future__ import annotations

from .apply import PlanError, ProposalApplier, parse_plan
from .audit import CuratorAudit
from .middleware import CuratorScopeMiddleware
from .models import (
    ApplyReport,
    CaptureRecord,
    CuratorRunReport,
    PendingCapture,
    Plan,
    ProposalResult,
    SelfReport,
    SessionResult,
    parse_self_report,
)
from .policy import (
    CURATOR_TOOL_ACTIONS,
    PROVENANCE_PREFIX,
    ActiveCaptures,
    provenance_line,
    rejection_for,
)
from .profile import (
    CURATOR_PROFILE_PATH,
    allowed_tool_specs,
    curator_profile,
    curator_profile_middleware,
    curator_tool_actions,
)
from .prompt import ROLE_BLOCK, build_prompt
from .runner import CuratorRunner
from .service import CuratorScheduler
from .session import (
    DEFAULT_RUNNER_COMMAND,
    SessionRequest,
    SessionRunner,
    SubprocessSessionRunner,
)
from .verify import Verification, verify_capture

__all__ = [
    "CURATOR_PROFILE_PATH",
    "CURATOR_TOOL_ACTIONS",
    "DEFAULT_RUNNER_COMMAND",
    "PROVENANCE_PREFIX",
    "ROLE_BLOCK",
    "ActiveCaptures",
    "ApplyReport",
    "CaptureRecord",
    "CuratorAudit",
    "CuratorRunReport",
    "CuratorRunner",
    "CuratorScheduler",
    "CuratorScopeMiddleware",
    "PendingCapture",
    "Plan",
    "PlanError",
    "ProposalApplier",
    "ProposalResult",
    "SelfReport",
    "SessionRequest",
    "SessionResult",
    "SessionRunner",
    "SubprocessSessionRunner",
    "Verification",
    "allowed_tool_specs",
    "build_prompt",
    "curator_profile",
    "curator_profile_middleware",
    "curator_tool_actions",
    "parse_plan",
    "parse_self_report",
    "provenance_line",
    "rejection_for",
    "verify_capture",
]
