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
#
# SPEC-106's `recall`/`build_context` are on the read list: they answer from
# the vault and never write to it. They *do* bump an access counter in the
# disposable index (palaia_hub.index.schema's `note_access`), which is not
# vault content and cannot change what any note says — the same reason both
# tools also carry `readOnlyHint`.
#
# SPEC-208's `review_queue` (lists review/ proposals) and `recall_pick`
# (re-reads notes the recall-explorer app's user already selected) are read
# actions by the same reasoning; `review_decide` (flips a proposal's
# status) is deliberately NOT on this list, so it falls through to the
# fail-closed `write` default below.
READ_ACTIONS: frozenset[str] = frozenset(
    {
        "search",
        "read",
        "list",
        "recent_activity",
        "recall",
        "build_context",
        "review_queue",
        "recall_pick",
    }
)
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


# SPEC-202 (stash): the stash tool family is hub-level, not per-vault, so its
# scopes are plain ``stash:read``/``stash:write`` rather than
# ``vault:<key>:<permission>``. Same fail-closed rule as above: only actions
# on :data:`STASH_READ_ACTIONS` get the weaker scope.
STASH_READ_ACTIONS: frozenset[str] = frozenset({"stash_get", "stash_list", "stash_status"})
STASH_WRITE_ACTIONS: frozenset[str] = frozenset({"stash_set", "stash_del"})


def stash_scope(permission: Permission) -> str:
    """The scope string for ``permission`` on the stash tool family."""
    return f"stash:{permission}"


def required_scope_for_stash_action(action: str) -> str:
    """The scope a token needs to call stash-tool ``action``.

    Fail-closed, same as :func:`required_scope_for_action`: an action name
    this module does not recognize requires the stronger ``write`` scope.
    """
    permission: Permission = "read" if action in STASH_READ_ACTIONS else "write"
    return stash_scope(permission)


# SPEC-402 (session directory): also hub-level, not per-vault, same
# ``directory:read``/``directory:write`` shape as stash above. Registering,
# heartbeating, updating and deregistering a session are all writes (they
# mutate the directory); listing and querying are reads.
DIRECTORY_READ_ACTIONS: frozenset[str] = frozenset({"directory_list", "directory_query"})
DIRECTORY_WRITE_ACTIONS: frozenset[str] = frozenset(
    {
        "directory_register",
        "directory_heartbeat",
        "directory_update",
        "directory_deregister",
    }
)


def directory_scope(permission: Permission) -> str:
    """The scope string for ``permission`` on the session directory."""
    return f"directory:{permission}"


def required_scope_for_directory_action(action: str) -> str:
    """The scope a token needs to call directory-tool ``action``.

    Fail-closed, same as :func:`required_scope_for_action`: an action name
    this module does not recognize requires the stronger ``write`` scope.
    """
    permission: Permission = "read" if action in DIRECTORY_READ_ACTIONS else "write"
    return directory_scope(permission)


__all__ = [
    "DIRECTORY_READ_ACTIONS",
    "DIRECTORY_WRITE_ACTIONS",
    "READ_ACTIONS",
    "STASH_READ_ACTIONS",
    "STASH_WRITE_ACTIONS",
    "WRITE_ACTIONS",
    "Permission",
    "directory_scope",
    "required_scope_for_action",
    "required_scope_for_directory_action",
    "required_scope_for_stash_action",
    "stash_scope",
    "vault_scope",
]
