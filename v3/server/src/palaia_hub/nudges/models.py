"""The value types the Smart Nudge layer is built from (issue #301).

A **nudge** is a live micro-skill: a single, contextual, actionable line
injected into the output an agent actually reads, at the moment palaia
deterministically *sees* the need. Skills teach behavior up front; a nudge is
the heads-up at the point of action, for the situations an LLM is weakest at
noticing on its own (a degraded index, a backlog, an unresolved reference).

Two rules shape everything in this package:

- **Deterministic origin.** A nudge is derived from facts the hub already
  computed — never from a model call. That is the whole point: the trigger is
  exactly the kind of signal an LLM does not notice unprompted.
- **Context is the budget.** Guidance that rides along on every result costs
  tokens on every result. Hence :data:`MAX_NUDGES_PER_RESULT`,
  :data:`MAX_NUDGE_CHARS` and the per-session cooldown in
  :mod:`palaia_hub.nudges.service`.

:class:`VaultSignals` is deliberately a flat record of already-computed facts
rather than the tool result objects themselves. That keeps this whole package
free of any MCP, FastMCP, gateway or vault import — detectors are pure
functions over plain data, which is what lets a second surface (the dashboard,
the CLI; v2 precedent: nudges in CLI output) reuse the same detector layer by
filling the same record from its own state. The MCP-side adapter that builds
one of these from a tool result lives in
:mod:`palaia_hub.gateway.guidance`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: How many nudges may ride along on a single result. A result carrying a
#: wall of guidance is a result whose actual payload got harder to read, so
#: the cap is deliberately low: two, and in practice almost always one.
MAX_NUDGES_PER_RESULT = 2

#: The length ceiling one nudge's text is held to. Not enforced at runtime
#: (a truncated sentence helps nobody) — enforced on the seeded detectors by
#: ``tests/nudges/test_detectors.py``, so a new detector cannot quietly grow
#: into a paragraph.
MAX_NUDGE_CHARS = 220

#: How long the same nudge stays quiet after firing, per session. Long enough
#: that a working agent is not told the same thing twice in a row; short
#: enough that a long session is reminded when it still matters.
DEFAULT_COOLDOWN_SECONDS = 900.0

#: Unfiled captures at or above this count are worth mentioning. Below it the
#: inbox is simply doing its job and saying so would be filler.
INBOX_BACKLOG_THRESHOLD = 10


@dataclass(frozen=True)
class Nudge:
    """One piece of guidance, ready to inject.

    ``key`` is the nudge's stable identity (``"recall.degraded"``), used for
    rate limiting and for anything downstream that wants to count or suppress
    a specific nudge — never shown to the agent.

    ``text`` is the whole user-visible payload: one sentence of *what*
    followed by a ``Fix:`` naming the concrete next action, per the
    name-the-fix house rule this repository applies to every message an agent
    reads (see :func:`palaia_hub.auth.enforcement.missing_scope_error` for
    the same rule on the error path).

    ``state`` is the coarse fingerprint of the condition that produced this
    nudge. Empty (the default) means "this nudge fires once per cooldown,
    however the details change". A detector sets it only when a *changed*
    condition genuinely deserves to speak up again before the cooldown
    expires — and then sets it to something coarse (a bucket, not a raw
    count), because a fingerprint that changes on every call is the same as
    having no rate limit at all.
    """

    key: str
    text: str
    state: str = ""

    @property
    def identity(self) -> tuple[str, str]:
        """What the rate limiter deduplicates on: the key plus its state."""
        return (self.key, self.state)


@dataclass(frozen=True)
class VaultSignals:
    """The deterministic facts about one completed vault operation.

    Every field is something the hub already knows by the time a result is
    returned — no field here costs an extra read, an extra query or an extra
    model call. A caller fills in what its operation actually produced and
    leaves the rest at its default; ``None`` on the optional counters means
    "not measured by this operation", which is distinct from ``0``.
    """

    #: The vault action that just completed (``"search"``, ``"recall"``, ...).
    #: Detectors match on this first, so the same record can carry fields that
    #: only some actions populate.
    action: str

    #: Which vault this was, for nudges that name it. Not part of rate
    #: limiting — see :class:`~palaia_hub.nudges.service.NudgeEngine`.
    vault_key: str = ""

    #: How many results the operation returned, when it returns results.
    hits: int | None = None

    #: The operation answered, but not at full strength — e.g. vectors are
    #: pending or unavailable, so a hybrid query ran text-only
    #: (``palaia_hub.recall.models.RecallResult.degraded``), or a context
    #: package did not fit its token budget.
    degraded: bool = False
    degraded_reason: str = ""

    #: Notes a context walk found but the token budget could not fit at any
    #: tier (``ContextResult.dropped``).
    dropped_notes: int = 0

    #: Uncurated captures waiting in ``inbox/`` (format spec §7).
    inbox_count: int | None = None

    #: A capture that was acknowledged without writing anything, because an
    #: identical one already exists, and where that existing one lives.
    duplicate_capture: bool = False
    duplicate_permalink: str = ""

    #: Value references that could not be resolved while reading a note
    #: (``NoteRecord.resolution_warnings``, format spec §5.3).
    unresolved_values: tuple[str, ...] = field(default_factory=tuple)


__all__ = [
    "DEFAULT_COOLDOWN_SECONDS",
    "INBOX_BACKLOG_THRESHOLD",
    "MAX_NUDGES_PER_RESULT",
    "MAX_NUDGE_CHARS",
    "Nudge",
    "VaultSignals",
]
