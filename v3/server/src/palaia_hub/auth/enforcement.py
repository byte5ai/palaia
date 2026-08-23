"""Per-tool scope enforcement — the gateway's fine-grained half of auth.

fastmcp's ``RequireAuthMiddleware`` (wired in via ``FastMCP(auth=...)``,
see :mod:`palaia_hub.auth.verifier`) is coarse: it gates an entire mounted
profile on "is there any valid token at all", because a profile can host
several vaults with different read/write grants on the *same* token. This
module is the other half: called from inside a memory tool
(:mod:`palaia_hub.gateway.memory_tools`), after the transport layer has
already authenticated the call, to check whether *this* token's scopes
cover *this* specific action on *this* specific vault.

The result is deliberately a plain string, not an exception:
:mod:`palaia_hub.gateway.memory_tools` turns it into
``ToolResult(is_error=True, ...)`` — an MCP-level tool error the calling
model sees and can react to, not an HTTP failure or a crash (SPEC-108
acceptance criterion: "read-scoped token calling a write tool -> MCP error
naming the missing scope").
"""

from __future__ import annotations

from fastmcp.server.dependencies import get_access_token

from .scopes import required_scope_for_action


def missing_scope_error(vault_key: str, action: str) -> str | None:
    """``None`` if the current call may proceed; else the error to return.

    ``get_access_token()`` returns ``None`` when no ``TokenVerifier`` is
    attached to the profile currently serving this request — i.e. auth was
    never required for this mount (locked mode's default-optional
    posture). That is a transport-layer decision already made before any
    tool code runs (see :mod:`palaia_hub.auth.policy` /
    :mod:`palaia_hub.gateway.build`): a profile *with* a verifier attached
    already refused an unauthenticated call with a 401 via
    ``RequireAuthMiddleware`` before reaching here, so a token-less call
    that does reach a tool body can only mean this mount never required
    one — every action is allowed in that case, same as before this SPEC.
    """
    access_token = get_access_token()
    if access_token is None:
        return None
    needed = required_scope_for_action(vault_key, action)
    if needed in access_token.scopes:
        return None
    return (
        f"this token is missing scope {needed!r} "
        f"(it has: {sorted(access_token.scopes)!r}). Fix: create or use a token "
        f"that includes {needed!r} for this vault."
    )


__all__ = ["missing_scope_error"]
