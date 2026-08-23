"""Scope strings: the vocabulary token permissions and tool checks share.

A scope is a plain string, ``vault:<key>:read`` or ``vault:<key>:write`` —
stored verbatim in a token's :class:`~palaia_hub.auth.models.TokenRecord`
and, unchanged, on the ``AccessToken.scopes`` a verifier hands back to
FastMCP (see :mod:`palaia_hub.auth.verifier`). Nothing here is fastmcp- or
gateway-specific: this module is the single source of truth for which of
the gateway's eight memory-tool actions need ``read`` vs. ``write``, kept
independent of :mod:`palaia_hub.gateway.vault_protocol` so the auth package
never has to import the gateway package to know that.

MASTERPLAN §5.5: "a tool counts as read-only only if it explicitly says so
*and* isn't on a known-writes list" — fail-closed. :data:`READ_ACTIONS` is
that explicit allow-list; anything not on it (including a name this module
has never heard of) is treated as a write.
"""

from __future__ import annotations

from typing import Literal

Permission = Literal["read", "write"]

# The gateway's memory tool family (palaia_hub.gateway.vault_protocol.
# MEMORY_TOOL_ACTIONS) split by whether they mutate the vault. Kept as an
# explicit allow-list rather than an "everything except these" denylist —
# per the fail-closed rule above, an action this set has never seen (a
# future ninth tool, a typo) requires the stronger scope, not the weaker
# one.
READ_ACTIONS: frozenset[str] = frozenset({"search", "read", "list", "recent_activity"})
WRITE_ACTIONS: frozenset[str] = frozenset({"write", "edit", "move", "delete"})


def vault_scope(vault_key: str, permission: Permission) -> str:
    """The scope string for ``permission`` on vault ``vault_key``."""
    return f"vault:{vault_key}:{permission}"


def required_scope_for_action(vault_key: str, action: str) -> str:
    """The scope a token needs to call memory-tool ``action`` on ``vault_key``.

    Fail-closed (see module docstring): only actions in :data:`READ_ACTIONS`
    get the weaker ``read`` scope; every other action name — including one
    this module does not recognize — requires ``write``.
    """
    permission: Permission = "read" if action in READ_ACTIONS else "write"
    return vault_scope(vault_key, permission)


__all__ = [
    "READ_ACTIONS",
    "WRITE_ACTIONS",
    "Permission",
    "required_scope_for_action",
    "vault_scope",
]
