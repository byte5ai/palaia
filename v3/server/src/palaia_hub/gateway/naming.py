"""Tool-name composition, sanitization, and the mount() rename foot-gun.

Binding finding (SPEC-002, ``v3/spikes/gateway/FINDINGS.md`` Q4): FastMCP's
``FastMCP.mount(server, namespace=ns, tool_names={old: new})`` applies the
``tool_names`` rename **before** adding the namespace prefix — ``old -> new``
with ``namespace="baz"`` yields ``baz_new``, not ``new``. A rename UI that
hands the *already-namespaced* display name straight to ``tool_names``
double-prefixes it (``baz_baz_new``) and the tool silently stops resolving
under its expected name.

This module is the single place that owns the composition rule, so nothing
else in the gateway package re-derives it:

- :func:`compose_tool_name` — namespace + pre-namespace name -> the name a
  client will actually see (what ``mount()`` produces).
- :data:`resolve_tool_names` — given a vault's configured renames (values are
  pre-namespace, by construction — see module docstring below), returns the
  dict to hand to ``mount(..., tool_names=...)`` directly, with sanitization
  and warnings applied.
- :func:`sanitize_tool_name` — the MCP tool-name charset filter.

Renames are stored in config as **pre-namespace values** (`resolve_tool_names`
docstring below), not full display names. This is a deliberate design choice
made *because of* the Q4 foot-gun: storing the pre-namespace value directly
means composing the display name is a pure, error-free concatenation
(:func:`compose_tool_name`), and there is nothing to "decompose" or get
wrong later. :func:`decompose_final_name` is provided anyway (and tested
against the exact double-prefix scenario from FINDINGS Q4) for a caller that
only has the display name in hand — e.g. a future dashboard field that lets
a user type/see the full name and needs the pre-namespace value back out.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("palaia_hub.gateway.naming")

# MCP tool names are conventionally restricted to this charset across
# clients (Claude Code, the MCP Python SDK's own validator, etc.): ASCII
# letters, digits, and underscore. Anything else is replaced.
_INVALID_CHARS_RE = re.compile(r"[^a-zA-Z0-9_]+")
_LEADING_DIGIT_RE = re.compile(r"^[0-9]")

MAX_TOOL_NAME_LENGTH = 128


class SanitizedName:
    """Result of :func:`sanitize_tool_name`: the safe value, and whether it changed."""

    __slots__ = ("value", "changed", "original")

    def __init__(self, value: str, changed: bool, original: str) -> None:
        self.value = value
        self.changed = changed
        self.original = original

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"SanitizedName(value={self.value!r}, changed={self.changed}, "
            f"original={self.original!r})"
        )


def sanitize_tool_name(raw: str) -> SanitizedName:
    """Coerce ``raw`` into the MCP tool-name charset (``[a-zA-Z0-9_]``).

    Invalid characters (including whitespace, ``-``, ``.``, ``/``) collapse
    to a single ``_``; leading/trailing underscores from that collapsing are
    stripped; a name that would start with a digit gets a ``t_`` prefix
    (tool names must not look like numbers); an empty result falls back to
    ``"tool"``; anything longer than :data:`MAX_TOOL_NAME_LENGTH` is
    truncated. ``changed`` is True if any of that altered the input.
    """
    value = _INVALID_CHARS_RE.sub("_", raw).strip("_")
    if _LEADING_DIGIT_RE.match(value):
        value = f"t_{value}"
    if not value:
        value = "tool"
    if len(value) > MAX_TOOL_NAME_LENGTH:
        value = value[:MAX_TOOL_NAME_LENGTH]
    return SanitizedName(value=value, changed=value != raw, original=raw)


def compose_tool_name(namespace: str, pre_namespace_name: str) -> str:
    """The name a client sees for ``pre_namespace_name`` mounted under ``namespace``.

    Mirrors exactly what ``FastMCP.mount(..., namespace=namespace,
    tool_names={...: pre_namespace_name})`` produces (FINDINGS Q4): the
    namespace, an underscore, then the pre-namespace name. An empty
    namespace produces the pre-namespace name unchanged (matches
    ``mount()``'s own ``namespace or ""`` handling).
    """
    if not namespace:
        return pre_namespace_name
    return f"{namespace}_{pre_namespace_name}"


def decompose_final_name(namespace: str, final_name: str) -> str:
    """Invert :func:`compose_tool_name`: strip ``namespace`` back off ``final_name``.

    For a caller that only holds the display name (e.g. a dashboard rename
    field showing the composed name) and needs the pre-namespace value to
    pass into ``mount(tool_names=...)``. If ``final_name`` does not carry
    the expected ``"<namespace>_"`` prefix, it is returned unchanged and a
    warning is logged — passing that value straight to ``tool_names`` would
    double-mount it under the namespace again (the exact FINDINGS Q4
    foot-gun), so callers on this path should prefer storing pre-namespace
    values directly (as :data:`resolve_tool_names` does) rather than
    round-tripping through display names.
    """
    prefix = f"{namespace}_"
    if namespace and final_name.startswith(prefix) and len(final_name) > len(prefix):
        return final_name[len(prefix) :]
    logger.warning(
        "decompose_final_name: %r does not start with the expected '%s' namespace "
        "prefix; returning it unchanged. Passing this straight to "
        "mount(tool_names=...) would double-prefix the result "
        "('%s_%s') rather than producing the literal name typed — "
        "see FINDINGS.md Q4.",
        final_name,
        namespace,
        namespace,
        final_name,
    )
    return final_name


def resolve_tool_names(
    namespace: str, renames: dict[str, str] | None
) -> dict[str, str]:
    """Sanitize a vault's configured renames into a ``mount(tool_names=...)`` dict.

    ``renames`` maps a base action name (``"search"``, ``"write"``, ...) to
    the desired **pre-namespace** value — i.e. what should appear after the
    vault's ``"<namespace>_"`` prefix once mounted. This is a deliberate
    storage choice (see module docstring): it sidesteps the Q4 foot-gun
    entirely, since composing the eventual display name is then a pure
    concatenation with no ambiguity.

    Each value is run through :func:`sanitize_tool_name`; a changed value is
    logged as a warning naming the vault namespace, the action, the
    original value, and the sanitized replacement (SPEC-105 acceptance
    criterion: "invalid rename chars are sanitized with a warning").
    Entries mapping an action to itself are dropped (no-op rename).
    """
    if not renames:
        return {}
    resolved: dict[str, str] = {}
    for action, desired in renames.items():
        sanitized = sanitize_tool_name(desired)
        if sanitized.changed:
            logger.warning(
                "vault %r: rename for tool %r ('%s') contains characters outside "
                "the MCP tool-name charset; sanitized to '%s'.",
                namespace,
                action,
                desired,
                sanitized.value,
            )
        if sanitized.value != action:
            resolved[action] = sanitized.value
    return resolved
