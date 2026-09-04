"""Operating-mode auth policy checked against an actually-built gateway.

:mod:`palaia_hub.config` already refuses (at config-load time) a
``cloud``/``open`` mode with ``auth_enabled: false`` — before any gateway
or app object exists. This module is the second, later layer: given a real
:class:`~palaia_hub.gateway.build.GatewayASGI` about to be mounted, confirm
every one of its profiles actually has a verifier attached, catching the
case config-level validation cannot — auth *configured* on but a profile
*built* without a verifier wired in (a wiring bug, not a config mistake).
Called from :func:`palaia_hub.app.create_app`.
"""

from __future__ import annotations

from collections.abc import Mapping

from fastmcp import FastMCP


class AuthPolicyError(RuntimeError):
    """Raised when a mode's auth requirement isn't met by the built gateway."""


def check_gateway_auth_policy(mode: str, profile_servers: Mapping[str, FastMCP]) -> None:
    """Refuse to proceed if ``mode`` requires auth but a profile has none.

    A no-op in ``locked`` mode (auth is optional there) or when there are
    no profiles at all (nothing to refuse).
    """
    if mode not in ("cloud", "open"):
        return
    unauthenticated = sorted(
        path for path, server in profile_servers.items() if server.auth is None
    )
    if unauthenticated:
        raise AuthPolicyError(
            f"mode {mode!r} requires every mounted MCP profile to have a token "
            f"verifier attached, but {unauthenticated} do not. Fix: build the "
            f"gateway with `token_verifiers` covering every profile (see "
            f"palaia_hub.auth.wiring.build_profile_verifiers), or set "
            f"`mode: locked` in config.yaml if these profiles are meant to stay "
            f"VPN/tailnet-only."
        )


def check_hub_mount_auth_policy(mode: str, servers: Mapping[str, FastMCP]) -> None:
    """The same rule as :func:`check_gateway_auth_policy`, for the hub-wide
    mounts (``/mcp/stash``, ``/mcp/directory``, ``/mcp/messenger``,
    ``/mcp/hub``, ``/mcp/market``, ``/mcp/team`` — issue #313).

    ``servers`` maps each mount path to the ``FastMCP`` instance behind it.
    A no-op in ``locked`` mode or with nothing mounted.
    """
    if mode not in ("cloud", "open"):
        return
    unauthenticated = sorted(path for path, server in servers.items() if server.auth is None)
    if unauthenticated:
        raise AuthPolicyError(
            f"mode {mode!r} requires every hub-wide MCP mount to have a token "
            f"verifier attached, but {unauthenticated} do not. Fix: pass "
            f"`hub_auth` (palaia_hub.oauth.verifier.build_hub_auth) to "
            f"create_app, or set `mode: locked` in config.yaml if this hub is "
            f"meant to stay VPN/tailnet-only."
        )


__all__ = ["AuthPolicyError", "check_gateway_auth_policy", "check_hub_mount_auth_policy"]
