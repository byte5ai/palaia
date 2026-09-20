"""Smart Nudges: deterministic guidance injected into agent-facing output.

Issue #301. A nudge is a live micro-skill — one contextual, actionable line
that rides along on the next result an agent reads, emitted the moment
deterministic code sees the need. Skills are how an agent *learns* a
behavior; a nudge is the runtime heads-up at the point of action, for the
signals a model is weakest at noticing on its own.

Three modules, in dependency order:

- :mod:`~palaia_hub.nudges.models` — :class:`~palaia_hub.nudges.models.Nudge`
  and :class:`~palaia_hub.nudges.models.VaultSignals`, the flat record of
  already-computed facts a detector reads.
- :mod:`~palaia_hub.nudges.detectors` — the seeded detectors, pure functions
  over that record.
- :mod:`~palaia_hub.nudges.service` — :class:`~palaia_hub.nudges.service.NudgeEngine`,
  which runs them and enforces the rate policy (per-session cooldown,
  per-result cap) that keeps guidance from eating the context window.

The package imports nothing from MCP, the gateway or the vault on purpose, so
a second surface can reuse the same detectors by filling the same record.
Today's one caller is the MCP tool family, through
:mod:`palaia_hub.gateway.guidance`.
"""

from __future__ import annotations

from .detectors import DETECTORS, Detector, detect
from .models import (
    DEFAULT_COOLDOWN_SECONDS,
    INBOX_BACKLOG_THRESHOLD,
    MAX_NUDGE_CHARS,
    MAX_NUDGES_PER_RESULT,
    Nudge,
    VaultSignals,
)
from .service import ANONYMOUS_SESSION, NudgeEngine

__all__ = [
    "ANONYMOUS_SESSION",
    "DEFAULT_COOLDOWN_SECONDS",
    "DETECTORS",
    "INBOX_BACKLOG_THRESHOLD",
    "MAX_NUDGES_PER_RESULT",
    "MAX_NUDGE_CHARS",
    "Detector",
    "Nudge",
    "NudgeEngine",
    "VaultSignals",
    "detect",
]
