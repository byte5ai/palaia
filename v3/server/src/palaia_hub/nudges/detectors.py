"""The seeded deterministic detectors (issue #301).

Every detector is a pure function :data:`Detector`: given one
:class:`~palaia_hub.nudges.models.VaultSignals` record it returns a
:class:`~palaia_hub.nudges.models.Nudge` or ``None``. No I/O, no clock, no
model call, no MCP types — which is what makes the whole set testable as a
table and reusable from a non-MCP surface.

Each one fires only on a condition the hub has actually measured. That is the
line between a nudge and filler: "results are text-only because the vector
table is unavailable" is a fact an agent cannot see and can act on; "remember
to search first" is a skill, and belongs in a skill.

Every text follows the same two-part shape — what happened, then ``Fix:``
plus the concrete next action — and is held under
:data:`~palaia_hub.nudges.models.MAX_NUDGE_CHARS`.

The set is deliberately small and covers six actions. Three detectors named
in issue #301 are *not* here yet, because the signal they need does not reach
a tool result today: "a write landed in a vault whose index rebuild is
pending", "token near expiry / profile changed since the token was minted",
and vault doctor findings (``verify()`` is an engine-side call behind the
dashboard and the repair path, not something a memory tool returns). Each is
a detector on top of an existing signal, not a change to this mechanism —
adding one means adding a field to ``VaultSignals`` and a function below,
nothing else.
"""

from __future__ import annotations

from collections.abc import Callable

from .models import INBOX_BACKLOG_THRESHOLD, Nudge, VaultSignals

#: What every detector is. Returning ``None`` is the normal case by far.
Detector = Callable[[VaultSignals], Nudge | None]


def recall_degraded(signals: VaultSignals) -> Nudge | None:
    """Recall answered without vectors — say so, since the answer looks normal.

    A degraded recall returns ranked results like any other; nothing in the
    payload tells the reading model that the semantic half was missing and
    that a paraphrase it would have matched was never considered.
    """
    if signals.action != "recall" or not signals.degraded:
        return None
    reason = signals.degraded_reason or "vector search is unavailable"
    return Nudge(
        key="recall.degraded",
        text=(
            f"These results are text-only right now: {reason}. Fix: rerun once "
            "embedding catches up, or rephrase using the exact words the note "
            "itself would use."
        ),
        # The reason is already coarse (a backlog state or a load failure),
        # and a change from "pending" to "unavailable" is worth re-stating.
        state=reason,
    )


def search_found_nothing(signals: VaultSignals) -> Nudge | None:
    """An empty ``search`` is the moment to point at ``recall``.

    ``search`` matches words; ``recall`` ranks by meaning, resolves aliases
    and looks at observations too. An agent that gets zero hits usually
    concludes the vault knows nothing, which is exactly the wrong conclusion
    to let stand.
    """
    if signals.action != "search" or signals.hits != 0:
        return None
    return Nudge(
        key="search.no_hits",
        text=(
            "No note matched those words. Fix: try recall for the same topic — "
            "it ranks by meaning, resolves aliases, and searches observations, "
            "not just note text."
        ),
    )


def context_budget_pressure(signals: VaultSignals) -> Nudge | None:
    """A context package that did not fit is a silently incomplete answer."""
    if signals.action != "build_context":
        return None
    if signals.dropped_notes > 0:
        return Nudge(
            key="context.dropped",
            text=(
                f"The token budget left out {signals.dropped_notes} note(s) this "
                "walk found. Fix: raise max_tokens, or narrow the walk with a "
                "smaller depth or a timeframe."
            ),
        )
    if signals.degraded:
        return Nudge(
            key="context.shortened",
            text=(
                "Some notes in this package were shortened to fit the token "
                "budget. Fix: raise max_tokens, or narrow depth/timeframe, to "
                "get the ones you need in full."
            ),
        )
    return None


def inbox_backlog(signals: VaultSignals) -> Nudge | None:
    """Unfiled captures pile up quietly — name the thing that clears them.

    ``inbox_status`` already reports the number. What it does not report is
    what to do about it, which is the half an agent needs.
    """
    if signals.action != "inbox_status":
        return None
    count = signals.inbox_count
    if count is None or count < INBOX_BACKLOG_THRESHOLD:
        return None
    return Nudge(
        key="inbox.backlog",
        text=(
            f"{count} captures are still unfiled. Fix: let the curator propose "
            "filings for them (dashboard, Inbox), rather than filing by hand as "
            "you go."
        ),
        # Bucketed by ten, so a backlog that keeps growing is allowed to speak
        # up again while a backlog that merely wobbles is not.
        state=f"{count // 10 * 10}+",
    )


def capture_was_duplicate(signals: VaultSignals) -> Nudge | None:
    """A deduplicated capture wrote nothing — the agent should know where the
    original is, or it will simply recapture again next time."""
    if signals.action != "capture" or not signals.duplicate_capture:
        return None
    where = signals.duplicate_permalink or "the existing capture"
    return Nudge(
        key="capture.duplicate",
        text=(
            "Nothing new was written — this capture already existed. Fix: if the "
            f"detail actually changed, edit {where} instead of capturing it "
            "again."
        ),
        state=signals.duplicate_permalink,
    )


def unresolved_values_on_read(signals: VaultSignals) -> Nudge | None:
    """A note whose value references did not resolve reads as if current.

    The resolved body is what the tool hands back (see
    :mod:`palaia_hub.gateway.memory_tools`), so an unresolved embed is
    invisible in the text — it just looks like the note never mentioned that
    value.
    """
    if signals.action != "read" or not signals.unresolved_values:
        return None
    first = signals.unresolved_values[0]
    return Nudge(
        key="read.unresolved_values",
        text=(
            f"{len(signals.unresolved_values)} value reference(s) in this note "
            f"did not resolve ({first}), so what you read is missing current "
            "values. Fix: check the source note named in the warning first."
        ),
        state=first,
    )


#: The seeded detector set, in the order they are offered to the rate limiter
#: — a result that trips two of them keeps the earlier one.
DETECTORS: tuple[Detector, ...] = (
    recall_degraded,
    context_budget_pressure,
    unresolved_values_on_read,
    capture_was_duplicate,
    inbox_backlog,
    search_found_nothing,
)


def detect(signals: VaultSignals, detectors: tuple[Detector, ...] = DETECTORS) -> list[Nudge]:
    """Run every detector over ``signals`` and return what fired, in order.

    Applies no budget and no rate limiting — that is
    :class:`~palaia_hub.nudges.service.NudgeEngine`'s job, kept separate so
    detection stays a pure, order-independent table.
    """
    fired = (detector(signals) for detector in detectors)
    return [nudge for nudge in fired if nudge is not None]


__all__ = [
    "DETECTORS",
    "Detector",
    "capture_was_duplicate",
    "context_budget_pressure",
    "detect",
    "inbox_backlog",
    "recall_degraded",
    "search_found_nothing",
    "unresolved_values_on_read",
]
