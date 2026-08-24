"""The curator's binding policy, as pure functions (SPEC-206 rule 2).

**The tool surface IS the policy.** This module owns the two halves of that
sentence that can be decided without touching a vault:

- :data:`CURATOR_TOOL_ACTIONS` — the only actions a curator session may see
  at all. Everything else the memory tool family offers (``move``,
  ``delete``, ``capture``, ``inbox_status``, ``recall``) is neither listed
  nor callable on a curator profile.
- :func:`rejection_for` — the per-call guard: given an action and the raw
  tool arguments, either ``None`` (this call may proceed) or the
  explanatory error the caller gets back instead of the call happening.

Nothing here reaches for a vault, a token or a server object, so the guard
matrix can be tested as a table of arguments (SPEC-206 acceptance criterion
#1) and enforced from a fastmcp middleware
(:mod:`palaia_hub.curator.middleware`) in the same breath.

Why server-side at all, when the prompt already says it? Because a prompt is
advice. MASTERPLAN §5.1: "the curator's limits are enforced in code (its tool
surface *is* the policy), not in prompt text" — the model literally cannot
hold a capability the policy forbids, so a jailbreak, a confused session or a
future prompt regression cannot turn INGEST into MAINTENANCE.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from typing import Any

#: The seven actions a curator session may use, verbatim from SPEC-206 rule
#: 2. Read-only reconnaissance plus the two INGEST verbs — and nothing that
#: could rewrite, move or retire what already exists.
CURATOR_TOOL_ACTIONS: tuple[str, ...] = (
    "search",
    "read",
    "list",
    "recent_activity",
    "build_context",
    "write",
    "edit",
)

#: Every note the curator writes carries this line (SPEC-206 rule 2 / the
#: prompt's "Every note you write carries ..."), so verification can find it
#: again by content alone (:mod:`palaia_hub.curator.verify`).
PROVENANCE_PREFIX = "- [source] inbox capture "

#: The provenance line's shape, anchored to a line of its own. ``capture_id``
#: is format spec §7's ``"cap-" + sha256(permalink)[:10]``, but the pattern
#: stays deliberately looser than that (any non-space token) so a vault whose
#: captures were imported with a differently-shaped id is not locked out.
_PROVENANCE_RE = re.compile(
    rf"^{re.escape(PROVENANCE_PREFIX)}(?P<capture_id>\S+)\s*$", re.MULTILINE
)

#: Reserved directories the curator may never write into or edit, and why.
#: ``inbox/`` is the capture's own home (format spec §7: "the curator may not
#: edit ``inbox/`` content"); ``review/`` may receive *new* proposals but
#: never edits of existing ones — that is what self-approval would look like.
INBOX_PREFIX = "inbox/"
REVIEW_PREFIX = "review/"

#: Argument names that mean "folder" on a write (the memory tool family
#: absorbs ``dir``/``path`` as aliases for it — see
#: :mod:`palaia_hub.gateway.memory_tools`), checked together so the guard
#: cannot be walked around by picking the alias.
_FOLDER_ARGUMENT_NAMES: tuple[str, ...] = ("folder", "dir", "path")

#: Argument names that would give ``write`` overwrite semantics. The v3
#: ``write`` tool has none of them (it is create-only: the engine adapter
#: passes ``must_create=True``, so writing over an existing note fails with
#: the engine's own explanatory error). They are rejected here anyway, by
#: name: if a future SPEC ever grows the tool surface such a parameter, the
#: curator profile must refuse it on the day it appears rather than on the
#: day someone notices.
_OVERWRITE_ARGUMENT_NAMES: tuple[str, ...] = (
    "overwrite",
    "replace",
    "force",
    "must_create",
    "mode",
)
_OVERWRITE_MODE_VALUES: frozenset[str] = frozenset({"overwrite", "replace", "force"})


def provenance_line(capture_id: str) -> str:
    """The exact provenance line a curator write must carry for ``capture_id``."""
    return f"{PROVENANCE_PREFIX}{capture_id}"


def provenance_ids(text: str) -> set[str]:
    """Every capture id ``text`` claims provenance from (possibly empty)."""
    return {match.group("capture_id") for match in _PROVENANCE_RE.finditer(text or "")}


def _folder_argument(arguments: Mapping[str, Any]) -> str:
    for name in _FOLDER_ARGUMENT_NAMES:
        value = arguments.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _in_reserved_folder(value: str, prefix: str) -> bool:
    """Is ``value`` inside the reserved directory ``prefix``?

    Accepts the folder forms a tool call can carry — ``"inbox"``,
    ``"inbox/"``, ``"/inbox"``, ``"inbox/2026"`` — and permalink forms
    (``"inbox/rate-limit-decision"``), because ``edit`` addresses a note by
    permalink and a permalink's first segment is its folder.
    """
    normalized = value.strip().strip("/").lower()
    if not normalized:
        return False
    reserved = prefix.rstrip("/")
    return normalized == reserved or normalized.startswith(f"{reserved}/")


def _overwrite_rejection(arguments: Mapping[str, Any]) -> str | None:
    for name in _OVERWRITE_ARGUMENT_NAMES:
        if name not in arguments:
            continue
        value = arguments[name]
        if name == "must_create":
            if value is False:
                return name
            continue
        if name == "mode":
            if isinstance(value, str) and value.strip().lower() in _OVERWRITE_MODE_VALUES:
                return name
            continue
        if value:
            return name
    return None


def _write_rejection(
    arguments: Mapping[str, Any], expected_captures: Collection[str]
) -> str | None:
    folder = _folder_argument(arguments)
    if _in_reserved_folder(folder, INBOX_PREFIX):
        return (
            "rejected: the curator never writes into inbox/. That folder is the "
            "capture's own home (vault-format §7) — file the knowledge where it "
            "belongs in the vault, or raise a proposal in review/, and leave the "
            "capture alone; the runner removes it once your write is verified."
        )
    if (offender := _overwrite_rejection(arguments)) is not None:
        return (
            f"rejected: write is create-only for the curator, so {offender!r} is "
            "refused. Overwriting an existing note is MAINTENANCE, never INGEST: "
            "append observations with edit(append=...), or write a proposal into "
            "review/ describing the rewrite you want a human to approve."
        )
    body = arguments.get("body")
    body_text = body if isinstance(body, str) else ""
    return _provenance_rejection(body_text, expected_captures, what="every note you write")


def _edit_rejection(
    arguments: Mapping[str, Any], expected_captures: Collection[str]
) -> str | None:
    target = arguments.get("permalink")
    target_text = target if isinstance(target, str) else ""
    if _in_reserved_folder(target_text, INBOX_PREFIX):
        return (
            "rejected: the curator never edits inbox/ content (vault-format §7). "
            "The capture is the input, not the workspace — write the knowledge "
            "into the vault instead; the runner retires the capture itself."
        )
    if _in_reserved_folder(target_text, REVIEW_PREFIX):
        return (
            "rejected: the curator may create new proposals in review/ but never "
            "edit existing ones — approving your own proposal is exactly what "
            "this guard exists to prevent. Write a new proposal if the old one "
            "is wrong, and let a human decide."
        )
    if arguments.get("body") is not None:
        return (
            "rejected: edit(body=...) replaces a note's content, which is "
            "MAINTENANCE and never autonomous. Use edit(append=...) to add "
            "observations, or write a proposal into review/ for the rewrite."
        )
    append = arguments.get("append")
    if append is None:
        return (
            "rejected: an edit needs append=... — additive observations are the "
            "only edit the curator may make. Nothing else on an existing note is "
            "INGEST."
        )
    append_text = append if isinstance(append, str) else ""
    return _provenance_rejection(
        append_text, expected_captures, what="everything you append to an existing note"
    )


def _provenance_rejection(
    text: str, expected_captures: Collection[str], *, what: str
) -> str | None:
    found = provenance_ids(text)
    expected = {capture_id for capture_id in expected_captures if capture_id}
    if not found:
        wanted = (
            provenance_line(sorted(expected)[0])
            if len(expected) == 1
            else f"{PROVENANCE_PREFIX}<capture_id>"
        )
        return (
            f"rejected: {what} must carry its provenance line, and this one has "
            f"none. Add a line exactly like `{wanted}` — verification finds your "
            "work by that id, and a write it cannot find never counts as done."
        )
    if expected and not (found & expected):
        return (
            f"rejected: this write claims provenance from {sorted(found)!r}, but "
            f"this session is curating {sorted(expected)!r}. Cite the capture you "
            "were given — a write attributed to another capture is unverifiable."
        )
    return None


def rejection_for(
    action: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    expected_captures: Collection[str] = (),
) -> str | None:
    """``None`` if a curator session may make this call; else why it may not.

    Args:
        action: the base memory-tool action (``"write"``, ``"edit"``, ...) —
            already stripped of the vault's tool-name namespace by the
            caller (:mod:`palaia_hub.curator.middleware`).
        arguments: the raw tool arguments, exactly as they arrived over MCP
            (alias names included — the guard checks the alias group, not
            just the canonical name).
        expected_captures: the capture id(s) the session currently running is
            allowed to claim provenance from. Empty means "any well-formed
            provenance line is accepted" — the honest fallback for a curator
            session this process did not launch itself (see
            :class:`ActiveCaptures`).

    The returned string is the message the model sees. It always says what
    was refused *and* what to do instead: per the SPEC's prompt, "a rejected
    call is information, not an obstacle".
    """
    arguments = arguments or {}
    if action not in CURATOR_TOOL_ACTIONS:
        return (
            f"rejected: {action!r} is not part of the curator's tool surface. "
            f"The curator may only use {', '.join(CURATOR_TOOL_ACTIONS)} — "
            "rewriting, moving, renaming, retiring or capturing are MAINTENANCE "
            "and belong in a review/ proposal a human approves."
        )
    if action == "write":
        return _write_rejection(arguments, expected_captures)
    if action == "edit":
        return _edit_rejection(arguments, expected_captures)
    return None


class ActiveCaptures:
    """Which capture id(s) curator sessions may cite right now.

    The provenance guard is strongest when it knows *which* capture the
    running session was handed: a write citing some other capture is then
    refused rather than merely well-formed. The runner
    (:class:`palaia_hub.curator.runner.CuratorRunner`) holds one of these and
    registers a capture for exactly the duration of that capture's session,
    so the binding is in-process state, not something a prompt can claim.

    When no session is registered — a curator session launched out of process,
    or a hub where the runner is not the one driving — :meth:`current` is
    empty and the guard falls back to shape-only provenance checking. That is
    a deliberate, documented weakening rather than a refusal: the guard still
    rejects a write with *no* provenance at all, which is what makes
    verification possible.
    """

    def __init__(self) -> None:
        self._active: dict[str, int] = {}

    def current(self) -> frozenset[str]:
        return frozenset(self._active)

    def acquire(self, capture_id: str) -> None:
        self._active[capture_id] = self._active.get(capture_id, 0) + 1

    def release(self, capture_id: str) -> None:
        remaining = self._active.get(capture_id, 0) - 1
        if remaining > 0:
            self._active[capture_id] = remaining
        else:
            self._active.pop(capture_id, None)


__all__ = [
    "CURATOR_TOOL_ACTIONS",
    "INBOX_PREFIX",
    "PROVENANCE_PREFIX",
    "REVIEW_PREFIX",
    "ActiveCaptures",
    "provenance_ids",
    "provenance_line",
    "rejection_for",
]
