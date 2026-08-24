"""The curator gateway profile: a second door onto the same vaults.

SPEC-206 rule 2: "the curator session authenticates with a dedicated curator
token whose profile exposes ONLY search, read, list, recent_activity,
build_context, write and edit". A profile is already the gateway's unit of
exposure (one :class:`~fastmcp.FastMCP` instance per profile path, SPEC-002
finding Q2), and a token is already bound to exactly one profile
(:class:`palaia_hub.auth.verifier.PalaiaTokenVerifier`) — so the curator
profile is an ordinary profile over the same vault tool servers, with
:class:`~palaia_hub.curator.middleware.CuratorScopeMiddleware` attached.

**Known limitation, deliberately fail-closed:** the tool-name → action map
(:func:`curator_tool_actions`) is built from the vaults known when the hub
wires the curator up. A vault created at runtime through the wizard is added
to the *default* profile only (see :mod:`palaia_hub.dashboard_api`), so its
tools are absent from the curator's map — and an unmapped tool name is
refused, not waved through. The curator starts curating that vault's inbox
after the next hub restart.

That middleware is passed into the gateway *builder*, not bolted onto the
built server: a profile can be rebuilt at runtime (a vault created through
the wizard, :class:`palaia_hub.gateway.dynamic.DynamicGateway`), and a policy
that had to be re-attached after every rebuild would eventually be forgotten
exactly once — which is all it takes.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from fastmcp.server.middleware import Middleware

from ..gateway.config import ProfileConfig, VaultMountConfig
from ..gateway.naming import compose_tool_name, resolve_tool_names
from ..gateway.vault_protocol import (
    INBOX_TOOL_ACTIONS,
    MEMORY_TOOL_ACTIONS,
    RECALL_TOOL_ACTIONS,
)
from .middleware import CuratorScopeMiddleware
from .policy import CURATOR_TOOL_ACTIONS, ActiveCaptures
from .session import MCP_SERVER_NAME

#: The profile path the curator connects to: ``/mcp/curator``.
CURATOR_PROFILE_PATH = "curator"

#: Every action the memory tool family exposes, curator-relevant or not. The
#: middleware needs all of them: mapping a *forbidden* tool name to its
#: action is what lets it refuse the call with a message naming what was
#: refused, instead of the generic "unknown tool".
_ALL_ACTIONS: tuple[str, ...] = (
    *MEMORY_TOOL_ACTIONS,
    *INBOX_TOOL_ACTIONS,
    *RECALL_TOOL_ACTIONS,
)


def curator_profile(vault_keys: Sequence[str]) -> ProfileConfig:
    """The curator profile over ``vault_keys`` (all of a hub's vaults, normally)."""
    return ProfileConfig(path=CURATOR_PROFILE_PATH, vaults=list(vault_keys))


def curator_tool_actions(vaults: Iterable[VaultMountConfig]) -> dict[str, str]:
    """``{tool name as a client sees it: base action}`` for these vaults.

    Renames are honored the same way the mount does it — the configured
    pre-namespace value, composed with the vault's namespace
    (:func:`palaia_hub.gateway.naming.compose_tool_name`) — so a vault whose
    ``write`` is exposed as ``work_memory_remember`` is still recognized as
    a write by the guard.
    """
    mapping: dict[str, str] = {}
    for vault in vaults:
        renames = resolve_tool_names(vault.namespace, vault.tool_renames)
        for action in _ALL_ACTIONS:
            final = compose_tool_name(vault.namespace, renames.get(action, action))
            mapping[final] = action
    return mapping


def allowed_tool_specs(
    vaults: Iterable[VaultMountConfig], *, server_name: str = MCP_SERVER_NAME
) -> tuple[str, ...]:
    """The ``--allowed-tools`` values for a curator session, sorted.

    A client namespaces an MCP server's tools as
    ``mcp__<server>__<tool>``; the session is launched with the generated
    config's server name (:data:`palaia_hub.curator.session.MCP_SERVER_NAME`),
    so the two must agree. Belt to the middleware's braces: the client is
    *told* which tools it may call, and the gateway refuses the rest anyway.
    """
    mapping = curator_tool_actions(vaults)
    return tuple(
        sorted(
            f"mcp__{server_name}__{name}"
            for name, action in mapping.items()
            if action in CURATOR_TOOL_ACTIONS
        )
    )


def curator_profile_middleware(
    vaults: Iterable[VaultMountConfig],
    *,
    active_captures: ActiveCaptures | None = None,
) -> dict[str, list[Middleware]]:
    """The ``profile_middleware`` mapping to hand to the gateway builder."""
    return {
        CURATOR_PROFILE_PATH: [
            CuratorScopeMiddleware(
                curator_tool_actions(vaults), active_captures=active_captures
            )
        ]
    }


__all__ = [
    "CURATOR_PROFILE_PATH",
    "allowed_tool_specs",
    "curator_profile",
    "curator_profile_middleware",
    "curator_tool_actions",
]
