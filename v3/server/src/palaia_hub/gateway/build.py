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
- Vault tool servers are mounted in-process (no network hop). **External**
  MCP servers (SPEC-302) arrive here as already-built client-backed proxies
  in :class:`UpstreamMount` — created by
  :meth:`palaia_hub.upstream.service.UpstreamService.proxy_for` with
  ``fastmcp.server.create_proxy()``, never the deprecated
  ``FastMCP.as_proxy()`` (Q1). Building them is the async caller's job so
  that this function stays synchronous and, more importantly, so that no
  network round-trip can ever happen inside a profile build.
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

from ..directory.service import DirectoryService
from ..messenger.service import MessengerService
from ..stash.service import StashService
from ..upstream.models import UpstreamConfig
from .apps.recall_app import RESOURCE_URI as RECALL_EXPLORER_URI
from .apps.recall_app import render_recall_explorer_html
from .apps.review_app import RESOURCE_URI as REVIEW_QUEUE_URI
from .apps.review_app import render_review_queue_html
from .config import CURATOR_PROFILE_PATH, GatewayConfig, ProfileConfig
from .directory_tools import build_directory_server
from .memory_tools import build_vault_server, vault_identity_block
from .messenger_tools import build_messenger_server
from .naming import resolve_tool_names
from .semantic_routing import build_semantic_routing_server
from .stash_tools import build_stash_server
from .vault_protocol import VaultService

# `combine_lifespans`'s return type is generic over the ASGI app it will be
# called with (FastAPI here, a bare FastMCP app in the spike); typed as
# `Any` at this dataclass boundary rather than re-declaring the precise
# `AbstractAsyncContextManager[...]` shape FastAPI's own overloads expect —
# that shape is exactly what `combine_lifespans` already produces (verified
# against `FastAPI(lifespan=...)` directly; see the module docstring).
Lifespan = Any


@dataclass(frozen=True)
class UpstreamMount:
    """One external MCP server, ready to mount (SPEC-302 deliverable #1).

    ``server`` is the client-backed proxy
    (:func:`fastmcp.server.create_proxy`) whose every tool call is forwarded
    over its own MCP connection to the real upstream. Constructing it costs
    no I/O, and a proxy whose upstream is unreachable mounts perfectly well
    — fastmcp 3.4.7's tool aggregator logs and skips a provider whose
    ``list_tools`` fails, so the profile serves everything else. That is
    exactly the degradation SPEC-302 deliverable #4 asks for.
    """

    config: UpstreamConfig
    server: FastMCP


def upstream_identity_block(config: UpstreamConfig) -> str:
    """The IDENTITY line marking an upstream's tools as somebody else's.

    SPEC-302 deliverable #6: an upstream's own tool descriptions pass
    through untouched, so the profile's instructions are where provenance
    gets stated — in plain language, naming who connected it, so a model
    reading the surface can tell palaia's own memory tools apart from a
    third party's.
    """
    return (
        f"IDENTITY: tools named {config.mount_namespace}_* come from "
        f"{config.display_name} — an outside service, connected by you. palaia "
        "passes their descriptions through unchanged and does not vouch for them."
    )


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
    stash_service: StashService | None = None,
    upstream_mounts: Mapping[str, UpstreamMount] | None = None,
    directory_service: DirectoryService | None = None,
    messenger_service: MessengerService | None = None,
) -> FastMCP:
    # SPEC-302 deliverable #6, second half of the fence: `ProfileConfig`
    # already refuses to *hold* upstreams on the curator path, so reaching
    # this line means a caller built the profile some other way. Fail
    # closed and loudly rather than mount anything.
    if profile.path == CURATOR_PROFILE_PATH and profile.upstreams:
        raise GatewayConfigError(
            "refusing to mount an external server on the curator profile: the "
            "curator runs a model over your own notes, and an outside tool in "
            f"that session could exfiltrate them (asked for: {sorted(profile.upstreams)})"
        )
    # SPEC-403 deliverable #4, the same fence for the messenger: no message
    # channel — in or out — inside the curator's unattended session. Also
    # refused by `ProfileConfig` itself; this is the half that holds even if
    # a future caller constructs the profile some other way.
    if profile.path == CURATOR_PROFILE_PATH and profile.messenger:
        raise GatewayConfigError(
            "refusing to mount messenger tools on the curator profile: the curator "
            "runs a model over your own notes unattended, and a message channel "
            "there is both a way out for their content and a way in for somebody "
            "else's instructions."
        )
    # `mount()` does not propagate a mounted server's `instructions` to its
    # parent, so a real client connecting to this profile would otherwise
    # see none at all (SPEC-105 deliverable #4: "server instructions with
    # an IDENTITY line per vault"). Compose one IDENTITY block per mounted
    # vault into *this* server's own instructions instead.
    vault_configs = [config.vault(key) for key in profile.vaults]
    # Only upstreams the caller actually built a proxy for are mounted: a
    # disabled or unreachable one is simply absent from `upstream_mounts`,
    # which is how a down external server degrades to absent tools instead
    # of a broken profile (SPEC-302 deliverable #4).
    mounted_upstreams = [
        (upstream_mounts or {})[key] for key in profile.upstreams if key in (upstream_mounts or {})
    ]
    identity_blocks = [vault_identity_block(v) for v in vault_configs]
    identity_blocks += [upstream_identity_block(m.config) for m in mounted_upstreams]
    instructions = "\n\n".join(identity_blocks) if identity_blocks else None
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
    # `profile.stash` (SPEC-301): mount the stash tool family's five tools
    # (unnamespaced — see gateway/stash_tools.py's module docstring) into
    # *this* profile too, alongside its vaults, so one MCP connection
    # carries both. `stash_service is None` (no hub-wide stash configured
    # at all) silently mounts nothing, same as a profile with `stash: false`
    # — a profile never fails to build just because the flag is set ahead
    # of the service existing.
    if profile.stash and stash_service is not None:
        server.mount(build_stash_server(stash_service))
    # `profile.directory` (SPEC-402): same opt-in shape as stash above —
    # `directory_service is None` (no hub-wide directory configured at
    # all) silently mounts nothing, so a profile with `directory: true`
    # ahead of the service existing never fails to build.
    if profile.directory and directory_service is not None:
        server.mount(build_directory_server(directory_service))
    # `profile.messenger` (SPEC-403): same opt-in shape again. The curator
    # path is already fenced off above, so reaching here means this is an
    # ordinary profile a client connects to.
    if profile.messenger and messenger_service is not None:
        server.mount(build_messenger_server(messenger_service))
    # SPEC-302: external servers, namespaced and renamable exactly like a
    # vault's tool family. `tool_names` values are pre-namespace (FINDINGS
    # Q4) — the one composition rule `gateway.naming` owns, applied here
    # through the same helper the vault mounts use.
    for mount in mounted_upstreams:
        renames = resolve_tool_names(mount.config.mount_namespace, mount.config.tool_renames)
        server.mount(
            mount.server,
            namespace=mount.config.mount_namespace,
            tool_names=renames or None,
        )

    # `profile.hidden_tools` (SPEC-305 deliverable #3): a global (not
    # session-scoped) `Provider.disable()` transform on *this profile's own*
    # `FastMCP` instance — every profile already gets its own instance (the
    # SPEC-002 finding this module's docstring opens with), so this hides a
    # tool from exactly this profile's `tools/list` and refuses it on call,
    # without touching the shared vault tool server another profile might
    # also mount. `disable()` only ever marks a `model_copy` of the
    # component (see fastmcp.server.transforms.visibility) — the mounted
    # vault/stash servers' own tool objects are never mutated. Applied
    # after every mount (vaults, stash, upstreams), since the names it
    # hides are final post-namespace names.
    if profile.hidden_tools:
        server.disable(names=set(profile.hidden_tools))
    _attach_app_resources(server)
    # `profile.semantic_routing` (SPEC-305 deliverable #4): swap the profile
    # actually served for a slim `find_tool`/`invoke_tool` router backed by
    # this full server. Built last, so the router always reflects every
    # vault/stash/hidden-tool decision already applied above.
    if profile.semantic_routing:
        return build_semantic_routing_server(profile, server)
    return server


def _attach_app_resources(server: FastMCP) -> None:
    """Register the recall-explorer/review-queue MCP App pages once per
    profile (SPEC-208 deliverable #1).

    Every vault mounted into this profile shares the exact same two ``ui://``
    resources (their ``search``/``recall``/``review_queue`` tools all point
    at the same literal URI, set in :mod:`palaia_hub.gateway.memory_tools` —
    the per-call data, not the static page, is what varies per vault; see
    ``gateway/apps/recall_app.py``'s docstring). Registering them here,
    once per profile, rather than inside :func:`~.memory_tools.
    build_vault_server` (called once per *vault*), is what avoids mounting
    the identical resource URI twice when a profile includes more than one
    vault — ``server.mount()`` would otherwise aggregate two providers each
    claiming the same URI.
    """

    @server.resource(RECALL_EXPLORER_URI, name="recall_explorer_app")
    def _recall_explorer_resource() -> str:
        return render_recall_explorer_html()

    @server.resource(REVIEW_QUEUE_URI, name="review_queue_app")
    def _review_queue_resource() -> str:
        return render_review_queue_html()


def build_gateway(
    config: GatewayConfig,
    vault_services: Mapping[str, VaultService],
    *,
    token_verifiers: Mapping[str, TokenVerifier] | None = None,
    profile_middleware: Mapping[str, Sequence[Middleware]] | None = None,
    stash_service: StashService | None = None,
    upstream_mounts: Mapping[str, UpstreamMount] | None = None,
    directory_service: DirectoryService | None = None,
    messenger_service: MessengerService | None = None,
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
        stash_service: the hub-wide stash (SPEC-202), mounted into any
            profile whose ``stash`` flag is set (SPEC-301). ``None`` (the
            default) leaves every profile exactly as before this parameter
            existed, even one with ``stash: true`` — the flag only takes
            effect once a service exists to back it.
        directory_service: the hub-wide session directory (SPEC-402),
            mounted into any profile whose ``directory`` flag is set — same
            "flag ahead of the service" contract as ``stash_service``.
        messenger_service: the hub-wide messenger (SPEC-403), mounted into
            any profile whose ``messenger`` flag is set — same contract
            again. Never onto the curator profile: that combination is
            refused, both here and by ``ProfileConfig`` itself.
        upstream_mounts: external MCP servers ready to mount (SPEC-302),
            keyed by upstream key — built by the async caller via
            :meth:`palaia_hub.upstream.service.UpstreamService.proxy_for`.
            A profile's ``upstreams`` entry with no key here contributes no
            tools, which is how a switched-off or unreachable server
            degrades. ``None`` (the default) leaves every profile exactly as
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
        server = _build_profile_server(
            profile,
            config,
            vault_servers,
            auth,
            middleware,
            stash_service,
            upstream_mounts,
            directory_service,
            messenger_service,
        )
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


__all__ = [
    "GatewayASGI",
    "GatewayConfigError",
    "UpstreamMount",
    "build_gateway",
    "upstream_identity_block",
]
