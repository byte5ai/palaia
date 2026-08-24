"""Assembles the gateway: per-vault tool servers, mounted into per-profile
FastMCP instances, served under one Starlette-mountable ASGI surface.

Binding findings this module follows exactly (SPEC-002,
``v3/spikes/gateway/FINDINGS.md``):

- **Profiles are one ``FastMCP()`` instance per profile**, each vault's tool
  server mounted into every profile that includes it (Q2) — FastMCP's own
  ``Visibility`` transform is session-scoped, not path-scoped, so it cannot
  implement per-path tool subsets; only separate instances can.
- **Lifespans are combined explicitly** with
  ``fastmcp.utilities.lifespan.combine_lifespans`` (Q2's "surprise, with a
  fix"): a bare Starlette/FastAPI parent does not propagate its lifespan
  into a mounted sub-app's ``.http_app()``, and a mounted FastMCP app whose
  lifespan never starts hangs on its first request rather than erroring
  loudly.
- **``tool_names`` renames are pre-namespace** (Q4) — handled once, in
  :mod:`palaia_hub.gateway.naming`, not re-derived here.
- No ``FastMCP.as_proxy()`` / ``create_proxy()`` appears here because vault
  tool servers are mounted in-process (no remote upstream in this SPEC's
  scope — external upstreams are Phase 3, MASTERPLAN §5.2/§5.3). If a
  future SPEC proxies a remote MCP server into a profile, it MUST use
  ``fastmcp.server.create_proxy()`` — ``FastMCP.as_proxy()`` is deprecated
  (Q1).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth import TokenVerifier
from fastmcp.server.middleware import Middleware
from fastmcp.utilities.lifespan import combine_lifespans
from starlette.types import ASGIApp

from .config import GatewayConfig, ProfileConfig
from .memory_tools import build_vault_server, vault_identity_block
from .naming import resolve_tool_names
from .vault_protocol import VaultService

# `combine_lifespans`'s return type is generic over the ASGI app it will be
# called with (FastAPI here, a bare FastMCP app in the spike); typed as
# `Any` at this dataclass boundary rather than re-declaring the precise
# `AbstractAsyncContextManager[...]` shape FastAPI's own overloads expect —
# that shape is exactly what `combine_lifespans` already produces (verified
# against `FastAPI(lifespan=...)` directly; see the module docstring).
Lifespan = Any


class GatewayConfigError(ValueError):
    """Raised when ``build_gateway`` is given a config it cannot satisfy.

    Distinct from :class:`pydantic.ValidationError` (which
    :class:`~palaia_hub.gateway.config.GatewayConfig` itself already raises
    for structurally invalid config): this is raised for a config that is
    structurally valid but references a vault key with no corresponding
    entry in the ``vault_services`` mapping passed to ``build_gateway``.
    """


@dataclass
class GatewayASGI:
    """The gateway's mountable surface: one ASGI app per profile path, plus
    their combined lifespan.

    ``mounts`` keys are full paths (``/mcp/<profile.path>``) ready to hand
    to ``Starlette``'s or FastAPI's ``Mount``/``app.mount()``. ``lifespan``
    MUST be passed into whatever ASGI application these are mounted under —
    see the module docstring's second bullet — or the mounted apps hang on
    their first request rather than erroring.
    """

    mounts: dict[str, ASGIApp]
    lifespan: Lifespan
    profile_servers: dict[str, FastMCP]
    vault_servers: dict[str, FastMCP]


def _build_vault_servers(
    config: GatewayConfig, vault_services: Mapping[str, VaultService]
) -> dict[str, FastMCP]:
    missing = [v.key for v in config.vaults if v.key not in vault_services]
    if missing:
        raise GatewayConfigError(
            f"gateway config references vault key(s) {missing} with no matching "
            "entry in vault_services; every configured vault needs a backing "
            "VaultService (a FakeVaultService for tests, a real adapter once "
            "SPEC-102/113 land)"
        )
    return {
        vault.key: build_vault_server(vault, vault_services[vault.key]) for vault in config.vaults
    }


def _build_profile_server(
    profile: ProfileConfig,
    config: GatewayConfig,
    vault_servers: Mapping[str, FastMCP],
    auth: TokenVerifier | None,
    middleware: Sequence[Middleware] = (),
) -> FastMCP:
    # `mount()` does not propagate a mounted server's `instructions` to its
    # parent, so a real client connecting to this profile would otherwise
    # see none at all (SPEC-105 deliverable #4: "server instructions with
    # an IDENTITY line per vault"). Compose one IDENTITY block per mounted
    # vault into *this* server's own instructions instead.
    vault_configs = [config.vault(key) for key in profile.vaults]
    instructions = (
        "\n\n".join(vault_identity_block(v) for v in vault_configs)
        if vault_configs
        else None
    )
    # `auth` (SPEC-108): a TokenVerifier here makes FastMCP wrap this
    # profile's HTTP endpoint in its own RequireAuthMiddleware/
    # BearerAuthBackend — every request needs a bearer token this verifier
    # accepts, with a missing/invalid one getting FastMCP's own RFC
    # 6750-compliant 401 + WWW-Authenticate. `None` (the default) preserves
    # this SPEC's exact prior behavior: no auth at all, same as before this
    # parameter existed.
    server = FastMCP(
        name=f"palaia-gateway-{profile.path}", instructions=instructions, auth=auth
    )
    # `middleware` (SPEC-206): per-profile request middleware, applied here
    # rather than after the fact, so a profile *rebuilt* at runtime
    # (DynamicGateway) never comes back without the policy it was mounted
    # with. Empty (the default) leaves the server exactly as before.
    for item in middleware:
        server.add_middleware(item)
    for vault_config in vault_configs:
        tool_names = resolve_tool_names(vault_config.namespace, vault_config.tool_renames)
        server.mount(
            vault_servers[vault_config.key],
            namespace=vault_config.namespace,
            tool_names=tool_names or None,
        )
    return server


def build_gateway(
    config: GatewayConfig,
    vault_services: Mapping[str, VaultService],
    *,
    token_verifiers: Mapping[str, TokenVerifier] | None = None,
    profile_middleware: Mapping[str, Sequence[Middleware]] | None = None,
) -> GatewayASGI:
    """Build the full gateway from a validated config and its backing services.

    Args:
        config: the validated gateway shape.
        vault_services: backing service per configured vault key.
        token_verifiers: optional per-profile-path :class:`TokenVerifier`
            (SPEC-108 — see :func:`palaia_hub.auth.wiring.
            build_profile_verifiers`). A profile whose path has no entry
            here is mounted with no auth at all, exactly as before this
            parameter existed; a profile with an entry requires every
            request to present a bearer token that verifier accepts.
        profile_middleware: optional per-profile-path fastmcp middleware
            (SPEC-206 — see :func:`palaia_hub.curator.profile.
            curator_profile_middleware`). Attached while the profile's
            server is built, so a later rebuild of that profile carries the
            same middleware. A profile with no entry is built exactly as
            before this parameter existed.

    Raises :class:`GatewayConfigError` if a configured vault has no entry in
    ``vault_services``. Structural config problems (duplicate keys, unknown
    references between profiles and vaults) are already rejected by
    :class:`GatewayConfig`'s own validators before this function is reached.
    """
    vault_servers = _build_vault_servers(config, vault_services)

    mounts: dict[str, ASGIApp] = {}
    profile_servers: dict[str, FastMCP] = {}
    lifespans: list[Lifespan] = []
    for profile in config.profiles:
        auth = (token_verifiers or {}).get(profile.path)
        middleware = (profile_middleware or {}).get(profile.path, ())
        server = _build_profile_server(profile, config, vault_servers, auth, middleware)
        profile_servers[profile.path] = server
        asgi_app = server.http_app(path="/")
        mounts[f"/mcp/{profile.path}"] = asgi_app
        lifespans.append(asgi_app.lifespan)

    # combine_lifespans() with zero lifespans (an empty profiles list) is a
    # valid no-op combined lifespan — no special-casing needed.
    combined_lifespan: Lifespan = combine_lifespans(*lifespans)

    return GatewayASGI(
        mounts=mounts,
        lifespan=combined_lifespan,
        profile_servers=profile_servers,
        vault_servers=vault_servers,
    )


__all__ = ["GatewayASGI", "GatewayConfigError", "build_gateway"]
