"""Where Smart Nudges meet the MCP tool surface (issue #301).

:mod:`palaia_hub.nudges` is transport-agnostic on purpose. This module is the
one adapter between it and the memory tool family:

- :func:`signals_for` reads the facts out of a tool's own result object —
  never by doing extra work, only by looking at what the call already
  produced.
- :func:`nudged_result` builds the :class:`~fastmcp.tools.base.ToolResult`,
  attaching whatever guidance the engine allowed.
- :func:`current_session_key` identifies the MCP session, so the rate policy
  is per connected client rather than hub-wide.

**Where the guidance lands.** Both halves of the dual text/json result, since
clients read different halves: the human-readable ``content`` gets a trailing
``Guidance:`` block, and ``structured_content`` gets a ``guidance`` list of
the same strings. The field appears only when there is something to say — an
always-present empty list on every payload would be exactly the per-call cost
the nudge design is trying to avoid, and these tools publish no fixed output
schema that a stable shape would serve.

Guidance is attached to successful results only. An error result already
names its own fix (see :func:`palaia_hub.auth.enforcement.missing_scope_error`)
and is the wrong moment to add a second, unrelated instruction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from fastmcp.server.dependencies import get_context
from fastmcp.tools.base import ToolResult
from pydantic import BaseModel

from ..nudges import ANONYMOUS_SESSION, NudgeEngine, SimilarNote, VaultSignals
from ..recall.models import ContextResult, RecallResult
from .vault_protocol import CaptureResult, InboxStatusResult, NoteRecord, SimilarNoteHit

#: Heading for the guidance block appended to the human-readable half. Short
#: and literal: a model scanning tool output should be able to tell in one
#: token where the result stops and the heads-up starts.
GUIDANCE_HEADING = "Guidance:"


def current_session_key() -> str:
    """The MCP session id for the call in flight, or :data:`ANONYMOUS_SESSION`.

    Both lookups are guarded because both legitimately fail outside a served
    request: ``get_context()`` raises when no FastMCP context is active (a
    direct in-process call, e.g. from a test or the dashboard adapter), and
    ``session_id`` raises when a context exists but no session has been
    established yet. Neither is a reason to fail a tool call — guidance is an
    extra, so the fallback is simply a coarser rate-limiting bucket.
    """
    try:
        context = get_context()
    except RuntimeError:
        return ANONYMOUS_SESSION
    try:
        return context.session_id
    except (RuntimeError, AttributeError):
        return ANONYMOUS_SESSION


def signals_for(
    action: str,
    result: object,
    *,
    vault_key: str = "",
    similar_notes: Sequence[SimilarNoteHit] = (),
) -> VaultSignals:
    """Read one completed call's deterministic facts off its result object.

    Unrecognized results (and actions that carry no signal today) produce a
    bare record naming the action: detectors match on ``action`` first, so a
    record with nothing else in it simply fires nothing. That is what lets
    every tool route through the same helper without each needing its own
    branch here.

    ``similar_notes`` is the one fact that does not live on the result
    (issue #187): ``write``/``capture`` ask the vault for it separately and
    hand it in, because putting it on :class:`NoteRecord` would add an empty
    field to every ``read``/``edit``/``move`` payload for a signal only a
    write produces.
    """
    signals = VaultSignals(
        action=action,
        vault_key=vault_key,
        similar_notes=tuple(
            SimilarNote(permalink=n.permalink, title=n.title) for n in similar_notes
        ),
    )
    if isinstance(result, RecallResult):
        return replace(
            signals,
            hits=len(result.entries),
            degraded=result.degraded,
            degraded_reason=result.degraded_reason,
        )
    if isinstance(result, ContextResult):
        return replace(
            signals,
            hits=len(result.nodes),
            degraded=result.degraded,
            dropped_notes=len(result.dropped),
        )
    if isinstance(result, CaptureResult):
        return replace(
            signals,
            duplicate_capture=result.duplicate,
            duplicate_permalink=result.permalink,
        )
    if isinstance(result, InboxStatusResult):
        return replace(signals, inbox_count=result.count)
    if isinstance(result, NoteRecord):
        return replace(signals, unresolved_values=tuple(result.resolution_warnings))
    # `SearchResult` is defined in `memory_tools`, which imports this module,
    # so it cannot be imported here without a cycle. It is matched
    # structurally instead — which also covers any future result reporting a
    # hit list the same way.
    hits = getattr(result, "hits", None)
    if isinstance(hits, list):
        return replace(signals, hits=len(hits))
    return signals


def nudged_result(
    engine: NudgeEngine,
    *,
    action: str,
    text: str,
    payload: BaseModel,
    vault_key: str = "",
    similar_notes: Sequence[SimilarNoteHit] = (),
) -> ToolResult:
    """A successful tool result, carrying whatever guidance applies.

    With nothing to say (the overwhelmingly common case) this is exactly the
    ``ToolResult(content=..., structured_content=...)`` the tool would have
    returned on its own.
    """
    nudges = engine.emit(
        signals_for(action, payload, vault_key=vault_key, similar_notes=similar_notes)
    )
    if not nudges:
        return ToolResult(content=text, structured_content=payload)
    lines = "\n".join(f"- {nudge.text}" for nudge in nudges)
    structured: dict[str, Any] = payload.model_dump(mode="json")
    structured["guidance"] = [nudge.text for nudge in nudges]
    return ToolResult(
        content=f"{text}\n\n{GUIDANCE_HEADING}\n{lines}",
        structured_content=structured,
    )


__all__ = ["GUIDANCE_HEADING", "current_session_key", "nudged_result", "signals_for"]
