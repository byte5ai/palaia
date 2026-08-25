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

from collections.abc import Iterable
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


# SPEC-403 (messenger): hub-level again, but with its own two-word
# vocabulary rather than read/write — the SPEC names ``messenger:send`` as
# *the* scope sending requires, so the write side is called ``send`` and not
# ``write``. ``messenger:read`` covers looking at your own mail.
#
# Note what a scope here does *not* buy: reading an inbox additionally needs
# the SPEC-402 session secret (SPEC-403 deliverable #4 — "a scope alone must
# not read another session's inbox"), enforced in
# :mod:`palaia_hub.messenger.service`, not here. A scope says what a client
# may do; only the secret says which session it is.
MessengerPermission = Literal["read", "send"]

#: ``messenger_ack`` is deliberately **not** here: it mutates delivery
#: state, so the fail-closed rule gives it the stronger scope. The SPEC
#: names only ``messenger:send`` on the write side, so ack shares it rather
#: than inventing a third scope string for one tool.
MESSENGER_READ_ACTIONS: frozenset[str] = frozenset({"messenger_check", "messenger_thread"})
MESSENGER_SEND_ACTIONS: frozenset[str] = frozenset({"messenger_send", "messenger_ack"})


def messenger_scope(permission: MessengerPermission) -> str:
    """The scope string for ``permission`` on the messenger tool family."""
    return f"messenger:{permission}"


def required_scope_for_messenger_action(action: str) -> str:
    """The scope a token needs to call messenger-tool ``action``.

    Fail-closed, same as every other family above: an action name this
    module does not recognize requires ``messenger:send``, the stronger of
    the two.
    """
    permission: MessengerPermission = "read" if action in MESSENGER_READ_ACTIONS else "send"
    return messenger_scope(permission)


def readable_vault_keys(scopes: Iterable[str]) -> frozenset[str]:
    """Which vaults these scopes grant *read* access to.

    Used by the messenger to decide which vaults an envelope's
    ``memory://`` refs may resolve in (SPEC-403 deliverable #1: "validated
    to resolve in a vault the sender can read"). Only an explicit
    ``vault:<key>:read`` counts — a write scope is not silently treated as
    implying read, because nothing else in this module does that either and
    a ref check is not the place to invent a scope hierarchy.
    """
    keys: set[str] = set()
    for scope in scopes:
        parts = scope.split(":")
        if len(parts) == 3 and parts[0] == "vault" and parts[2] == "read" and parts[1]:
            keys.add(parts[1])
    return frozenset(keys)


__all__ = [
    "DIRECTORY_READ_ACTIONS",
    "DIRECTORY_WRITE_ACTIONS",
    "MESSENGER_READ_ACTIONS",
    "MESSENGER_SEND_ACTIONS",
    "READ_ACTIONS",
    "STASH_READ_ACTIONS",
    "STASH_WRITE_ACTIONS",
    "WRITE_ACTIONS",
    "MessengerPermission",
    "Permission",
    "directory_scope",
    "messenger_scope",
    "readable_vault_keys",
    "required_scope_for_action",
    "required_scope_for_directory_action",
    "required_scope_for_messenger_action",
    "required_scope_for_stash_action",
    "stash_scope",
    "vault_scope",
]
