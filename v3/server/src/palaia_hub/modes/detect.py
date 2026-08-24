"""Detect whether Tailscale/cloudflared are installed on this host (SPEC-205).

Deliberately narrow: a ``shutil.which`` lookup, nothing that shells out or
reads either tool's own state. It only ever changes which of the exposure
wizard's two tunnel tabs is offered first — a host with neither installed
still gets both configs (and the "bring your own reverse proxy" path),
since the tabs are exactly as useful as copy-paste text even when nothing
is detected.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TunnelDetection:
    tailscale: bool
    cloudflared: bool


def detect_tunnels() -> TunnelDetection:
    """Return which of the two supported tunnel binaries are on ``PATH``."""
    return TunnelDetection(
        tailscale=shutil.which("tailscale") is not None,
        cloudflared=shutil.which("cloudflared") is not None,
    )


__all__ = ["TunnelDetection", "detect_tunnels"]
