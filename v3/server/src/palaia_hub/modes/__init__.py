"""Operating modes & the exposure wizard (SPEC-205).

Locked -> Cloud -> Open is a guided, safe journey administered from the
dashboard: :mod:`.api` is the REST surface (`GET`/`POST /api/mode`,
`GET /api/exposure`, tunnel guidance, the public-URL self-test);
:mod:`.policy` is where a requested change is validated before anything is
written; :mod:`.patch` persists an accepted change to ``config.yaml``
without disturbing its comments; :mod:`.audit` keeps the append-only trail
of every attempt, accepted or refused; :mod:`.tunnel`/:mod:`.detect` back
the Cloud-mode tunnel guidance; :mod:`.selftest` is the "no fake green"
public-URL reachability check; :mod:`.hardening` builds the Open-mode
checklist; :mod:`.rate_limit` throttles the auth endpoints that become
publicly reachable in Cloud/Open.
"""

from __future__ import annotations

from .api import ModeChangeRequest, ModeStatusOut, build_modes_router
from .audit import AUDIT_FILE, ModeAuditEntry, ModeAuditLog
from .detect import TunnelDetection, detect_tunnels
from .errors import ModeChangeError
from .hardening import ChecklistItem, build_checklist
from .patch import patch_config_values
from .policy import build_candidate_config
from .rate_limit import (
    DEFAULT_LIMIT,
    DEFAULT_RATE_LIMITED_PATHS,
    DEFAULT_WINDOW_SECONDS,
    AuthRateLimitMiddleware,
)
from .selftest import SelfTestResult, check_public_url
from .tunnel import (
    CLOUD_PUBLIC_PATH_PREFIXES,
    TunnelGuidance,
    cloudflared_guidance,
    tailscale_guidance,
)

__all__ = [
    "AUDIT_FILE",
    "CLOUD_PUBLIC_PATH_PREFIXES",
    "DEFAULT_LIMIT",
    "DEFAULT_RATE_LIMITED_PATHS",
    "DEFAULT_WINDOW_SECONDS",
    "AuthRateLimitMiddleware",
    "ChecklistItem",
    "ModeAuditEntry",
    "ModeAuditLog",
    "ModeChangeError",
    "ModeChangeRequest",
    "ModeStatusOut",
    "SelfTestResult",
    "TunnelDetection",
    "TunnelGuidance",
    "build_candidate_config",
    "build_checklist",
    "build_modes_router",
    "check_public_url",
    "cloudflared_guidance",
    "detect_tunnels",
    "patch_config_values",
    "tailscale_guidance",
]
