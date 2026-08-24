"""Runtime profile CRUD: ``/api/gateway/profiles`` (SPEC-301 deliverable #2).

Every route here does the same three things, in order: validate against the
gateway actually running, apply the change live to the
:class:`~.dynamic.DynamicGateway` (so an MCP client sees it with no
restart), then write the new shape back to ``config.yaml`` (so it survives
one) — the same "live now, persisted for next time" contract
:mod:`palaia_hub.modes.api` already established for mode changes, except a
profile edit here needs no ``restart_required`` escape hatch: unlike
mode/host/auth, a profile's shape is exactly the thing
:class:`~.dynamic.DynamicGateway` was built to rebuild without one.

The curator's own profile (``/mcp/curator``) is deliberately off-limits
here — it is not a ``gateway.profiles`` entry at all, but something
synthesized from ``curator.enabled`` (see
:mod:`palaia_hub.gateway.settings_bridge`), so editing it through this
generic surface would silently fight with that synthesis on the next
restart. An operator who wants to change what the curator sees edits
``curator:`` settings or adds a vault through the wizard instead.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider
from fastmcp.server.providers.base import Provider
from fastmcp.server.transforms.visibility import is_enabled
from pydantic import BaseModel, ConfigDict, ValidationError

from ..auth.policy import AuthPolicyError
from ..auth.store import TokenStore
from ..config import (
    GatewayProfileSettings,
    GatewaySettings,
    GatewayVaultSettings,
    HubConfig,
    config_file_path,
)
from ..events import EventBus, publish_event
from ..oauth import AuthorizationServer
from ..oauth.verifier import build_profile_auth
from .build import GatewayConfigError
from .config import (
    CURATOR_PROFILE_PATH,
    DEFAULT_GATEWAY_PROFILE,
    ProfileConfig,
    VaultMountConfig,
)
from .dynamic import DynamicGateway
from .naming import sanitize_tool_name
from .settings_bridge import persist_gateway_settings

# `CURATOR_PROFILE_PATH` is imported from `.config` (not from
# `palaia_hub.curator.profile`): this module has no other reason to pull in
# the curator package, and the path itself is what matters here — protecting
# it from the generic CRUD below, see the module docstring.


class GatewayProfileOut(BaseModel):
    """One profile, as the editor sees it."""

    model_config = ConfigDict(extra="forbid")

    path: str
    label: str | None
    vaults: list[str]
    stash: bool
    #: Whether this profile also carries the session directory tool family
    #: (SPEC-402), same opt-in shape as ``stash`` above.
    directory: bool
    #: Final (post-namespace) tool names hidden from this profile's own
    #: surface (SPEC-305 deliverable #3).
    hidden_tools: list[str]
    #: ``find_tool``/``invoke_tool`` instead of the full surface (SPEC-305
    #: deliverable #4). Experimental — off by default.
    semantic_routing: bool
    #: How many tools this profile's live ``FastMCP`` instance actually
    #: answers ``tools/list`` with right now (SPEC-305 deliverable #1's
    #: "live tool count") — 0 for a profile with no vaults/stash, and
    #: exactly 2 (``find_tool``/``invoke_tool``) once ``semantic_routing``
    #: is on, whatever the hidden full surface behind it contains.
    tool_count: int
    #: External MCP servers this profile mounts (SPEC-302), by key. The
    #: profile editor (SPEC-305) assigns them through this same surface
    #: rather than a second write path.
    upstreams: list[str]
    #: The curator's own profile is listed (so the editor can show it) but
    #: every write route below refuses to touch it — see the module
    #: docstring.
    managed: bool


class GatewayToolOut(BaseModel):
    """One tool a profile's mounted surface would offer, for the editor's
    per-tool visibility checkboxes (SPEC-305 deliverable #3) — ``hidden``
    ones included, unlike ``tools/list`` itself, which never shows them."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None
    hidden: bool


class CreateGatewayProfileRequest(BaseModel):
    """``POST /api/gateway/profiles`` — ``path`` is set here, once, and
    never appears in :class:`UpdateGatewayProfileRequest` below: there is
    no "rename the URL" operation (see ``ProfileConfig``'s docstring)."""

    model_config = ConfigDict(extra="forbid")

    path: str
    label: str | None = None
    vaults: list[str] = []
    stash: bool = False
    directory: bool = False
    hidden_tools: list[str] = []
    semantic_routing: bool = False
    upstreams: list[str] = []


class UpdateGatewayProfileRequest(BaseModel):
    """``PATCH /api/gateway/profiles/{path}`` — every field optional; an
    omitted one keeps its current value. ``vaults``/``hidden_tools``, when
    given, *replace* the whole list (there is no separate add/remove verb)."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    vaults: list[str] | None = None
    stash: bool | None = None
    directory: bool | None = None
    hidden_tools: list[str] | None = None
    semantic_routing: bool | None = None
    #: Same whole-list contract as ``vaults`` (SPEC-302): given, it replaces
    #: the profile's external-server list entirely.
    upstreams: list[str] | None = None


class RenameSanitizationOut(BaseModel):
    """One ``tool_renames`` entry whose requested value fell outside the
    MCP tool-name charset and was sanitized (SPEC-305 acceptance criterion:
    "invalid names are sanitized with the warning shown")."""

    model_config = ConfigDict(extra="forbid")

    action: str
    requested: str
    applied: str


class GatewayVaultOut(BaseModel):
    """One vault's gateway identity, as the editor sees it."""

    model_config = ConfigDict(extra="forbid")

    key: str
    name: str
    purpose: str
    #: Base action name -> desired pre-namespace tool name, exactly as
    #: stored (not yet sanitized — see ``sanitized``).
    tool_renames: dict[str, str]
    #: This vault's mount namespace (``"<name>_memory"``), so the editor
    #: can show the composed tool name (``f"{namespace}_{action}"``)
    #: without re-deriving the composition rule itself.
    namespace: str
    #: Which ``tool_renames`` entries, if any, will be sanitized once the
    #: gateway actually builds this vault's tools — computed fresh on
    #: every read, so it is never stale relative to ``tool_renames``.
    sanitized: list[RenameSanitizationOut]


class UpdateGatewayVaultRequest(BaseModel):
    """``PATCH /api/gateway/vaults/{vault_key}`` — every field optional; an
    omitted one keeps its current value. ``tool_renames``, when given,
    *replaces* the whole mapping."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    purpose: str | None = None
    tool_renames: dict[str, str] | None = None


async def _introspect_tools(server: FastMCP) -> list[GatewayToolOut]:
    """Every tool ``server`` would mount, hidden ones included, with their
    live enabled state.

    Deliberately calls the base :meth:`~fastmcp.server.providers.base.
    Provider.list_tools` rather than ``server.list_tools()`` (this
    server's own override): the override already filters out anything a
    ``Visibility`` transform marked disabled — see
    ``fastmcp.server.transforms.visibility`` — which is exactly the
    information a per-tool visibility checkbox needs to *show*, not hide.
    The base method still applies the same provider-level transforms
    (namespacing, a profile's ``hidden_tools`` marks); it just skips the
    final "drop anything disabled" step.
    """
    tools = await Provider.list_tools(server)
    return [
        GatewayToolOut(name=t.name, description=t.description, hidden=not is_enabled(t))
        for t in tools
    ]


def _sanitize_renames(tool_renames: dict[str, str]) -> list[RenameSanitizationOut]:
    warnings: list[RenameSanitizationOut] = []
    for action, desired in tool_renames.items():
        result = sanitize_tool_name(desired)
        if result.changed:
            warnings.append(
                RenameSanitizationOut(action=action, requested=desired, applied=result.value)
            )
    return warnings


def _vault_out(vault: VaultMountConfig) -> GatewayVaultOut:
    return GatewayVaultOut(
        key=vault.key,
        name=vault.name,
        purpose=vault.purpose,
        tool_renames=dict(vault.tool_renames),
        namespace=vault.namespace,
        sanitized=_sanitize_renames(vault.tool_renames),
    )


async def _out(profile: ProfileConfig, dynamic_gateway: DynamicGateway) -> GatewayProfileOut:
    server = dynamic_gateway.profile_servers.get(profile.path)
    tool_count = 0
    if server is not None:
        tool_count = sum(1 for t in await _introspect_tools(server) if not t.hidden)
    return GatewayProfileOut(
        path=profile.path,
        label=profile.label,
        vaults=list(profile.vaults),
        stash=profile.stash,
        directory=profile.directory,
        hidden_tools=list(profile.hidden_tools),
        semantic_routing=profile.semantic_routing,
        tool_count=tool_count,
        upstreams=list(profile.upstreams),
        managed=profile.path == CURATOR_PROFILE_PATH,
    )


def build_gateway_profiles_router(
    dynamic_gateway: DynamicGateway,
    *,
    home: Path,
    config: HubConfig,
    event_bus: EventBus | None = None,
    oauth_server: AuthorizationServer | None = None,
    token_store: TokenStore | None = None,
) -> APIRouter:
    """Build the profile-editor router, bound to ``dynamic_gateway``.

    Args:
        dynamic_gateway: the live gateway every route reads from and
            applies to.
        home: the hub's home directory — where ``config.yaml`` lives.
        config: the live, running configuration. Only its
            ``gateway.vaults`` (per-vault identity overrides, untouched by
            any route here) and ``auth_enabled`` flag are read; ``mode`` is
            not consulted directly — :meth:`DynamicGateway.upsert_profile`
            already refuses an unauthenticated profile in cloud/open via
            :func:`palaia_hub.auth.policy.check_gateway_auth_policy`.
        event_bus: publishes ``gateway.profile.created/updated/deleted``
            when given (SPEC-301 deliverable #6). Omitted, edits still
            apply and persist, just silently.
        oauth_server: given, a brand-new profile also gets a JWT verifier
            pinned to its (freshly registered) audience — same as every
            profile built at startup gets one (see
            ``palaia_hub.serve.build_production_app``).
        token_store: given (and ``config.auth_enabled``), a brand-new
            profile also accepts SPEC-108 ``plt_`` tokens, alongside OAuth.
    """
    router = APIRouter(tags=["gateway"])
    path = config_file_path(home)

    def _new_profile_auth(profile_path: str) -> AuthProvider | None:
        """The verifier a genuinely new profile should get, mirroring
        exactly how ``build_production_app`` builds one at startup."""
        providers = build_profile_auth(
            [profile_path],
            key=oauth_server.key if oauth_server is not None else None,
            resources=oauth_server.resources if oauth_server is not None else None,
            token_store=token_store if config.auth_enabled else None,
        )
        return providers.get(profile_path)

    def _persist() -> None:
        # Reads the *live* gateway shape (`dynamic_gateway.config`), not the
        # `config.gateway` snapshot captured when this router was built —
        # that snapshot never changes, but `dynamic_gateway.config.vaults`
        # does, via `update_vault_identity` (SPEC-305 deliverable #1's vault
        # rename route below). Persisting from the live shape is what keeps
        # a vault-identity edit and a profile edit on one write path,
        # instead of one clobbering the other's config.yaml section.
        profiles = [
            p for p in dynamic_gateway.config.profiles if p.path != CURATOR_PROFILE_PATH
        ]
        settings = GatewaySettings(
            vaults=[
                GatewayVaultSettings(
                    key=v.key, name=v.name, purpose=v.purpose, tool_renames=dict(v.tool_renames)
                )
                for v in dynamic_gateway.config.vaults
            ],
            profiles=[
                GatewayProfileSettings(
                    path=p.path,
                    label=p.label,
                    vaults=list(p.vaults),
                    stash=p.stash,
                    directory=p.directory,
                    hidden_tools=list(p.hidden_tools),
                    semantic_routing=p.semantic_routing,
                    upstreams=list(p.upstreams),
                )
                for p in profiles
            ],
            # SPEC-302: carried through from the live gateway, not from
            # `config` — a profile edit must never blank out the external
            # servers someone connected since this process started.
            upstreams=list(dynamic_gateway.config.upstreams),
        )
        persist_gateway_settings(path, settings)

    def _publish(event: str, data: dict[str, object]) -> None:
        if event_bus is not None:
            publish_event(event_bus, event, origin="gateway", data=data)

    def _require_editable(profile_path: str) -> None:
        if profile_path == CURATOR_PROFILE_PATH:
            raise HTTPException(
                status_code=400,
                detail=(
                    "the curator profile is managed automatically from "
                    "`curator:` settings, not through this API. Fix: edit "
                    "config.yaml's `curator:` section, or add a vault through "
                    "the wizard (it joins the curator profile on its own)."
                ),
            )

    @router.get("/api/gateway/profiles", response_model=list[GatewayProfileOut])
    async def list_profiles() -> list[GatewayProfileOut]:
        return [await _out(p, dynamic_gateway) for p in dynamic_gateway.config.profiles]

    @router.get(
        "/api/gateway/profiles/{profile_path}/tools", response_model=list[GatewayToolOut]
    )
    async def list_profile_tools(profile_path: str) -> list[GatewayToolOut]:
        """Every tool this profile's live surface would mount, hidden ones
        included — the editor's per-tool visibility checkboxes (SPEC-305
        deliverable #3). A ``semantic_routing`` profile answers with
        exactly its two router tools: that *is* its live surface."""
        server = dynamic_gateway.profile_servers.get(profile_path)
        if server is None:
            raise HTTPException(status_code=404, detail=f"no profile at path {profile_path!r}")
        return await _introspect_tools(server)

    @router.post("/api/gateway/profiles", response_model=GatewayProfileOut)
    async def create_profile(body: CreateGatewayProfileRequest) -> GatewayProfileOut:
        _require_editable(body.path)
        existing = {p.path for p in dynamic_gateway.config.profiles}
        if body.path in existing:
            raise HTTPException(
                status_code=400,
                detail=f"a profile at path {body.path!r} already exists. Fix: "
                "PATCH it instead, or choose a different path.",
            )
        try:
            ProfileConfig(
                path=body.path,
                label=body.label,
                vaults=body.vaults,
                stash=body.stash,
                directory=body.directory,
                hidden_tools=body.hidden_tools,
                semantic_routing=body.semantic_routing,
                upstreams=body.upstreams,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            await dynamic_gateway.upsert_profile(
                body.path,
                body.vaults,
                label=body.label,
                stash=body.stash,
                directory=body.directory,
                hidden_tools=body.hidden_tools,
                semantic_routing=body.semantic_routing,
                upstreams=body.upstreams,
                auth=_new_profile_auth(body.path),  # type: ignore[arg-type]
            )
        except GatewayConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except AuthPolicyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        _persist()
        result = next(p for p in dynamic_gateway.config.profiles if p.path == body.path)
        _publish(
            "gateway.profile.created",
            {"path": result.path, "vaults": list(result.vaults), "stash": result.stash},
        )
        return await _out(result, dynamic_gateway)

    @router.patch("/api/gateway/profiles/{profile_path}", response_model=GatewayProfileOut)
    async def update_profile(
        profile_path: str, body: UpdateGatewayProfileRequest
    ) -> GatewayProfileOut:
        _require_editable(profile_path)
        current = next(
            (p for p in dynamic_gateway.config.profiles if p.path == profile_path), None
        )
        if current is None:
            raise HTTPException(
                status_code=404, detail=f"no profile at path {profile_path!r}"
            )
        label = body.label if body.label is not None else current.label
        vaults = body.vaults if body.vaults is not None else list(current.vaults)
        stash = body.stash if body.stash is not None else current.stash
        directory = body.directory if body.directory is not None else current.directory
        hidden_tools = (
            body.hidden_tools if body.hidden_tools is not None else list(current.hidden_tools)
        )
        semantic_routing = (
            body.semantic_routing
            if body.semantic_routing is not None
            else current.semantic_routing
        )
        upstreams = body.upstreams if body.upstreams is not None else list(current.upstreams)
        try:
            ProfileConfig(
                path=profile_path,
                label=label,
                vaults=vaults,
                stash=stash,
                directory=directory,
                hidden_tools=hidden_tools,
                semantic_routing=semantic_routing,
                upstreams=upstreams,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            # `auth=None`: this path already has a verifier from creation
            # (or none, in locked mode) — an edit never changes that.
            await dynamic_gateway.upsert_profile(
                profile_path,
                vaults,
                label=label,
                stash=stash,
                directory=directory,
                hidden_tools=hidden_tools,
                semantic_routing=semantic_routing,
                upstreams=upstreams,
                auth=None,
            )
        except GatewayConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except AuthPolicyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        _persist()
        result = next(p for p in dynamic_gateway.config.profiles if p.path == profile_path)
        _publish(
            "gateway.profile.updated",
            {"path": result.path, "vaults": list(result.vaults), "stash": result.stash},
        )
        return await _out(result, dynamic_gateway)

    @router.delete("/api/gateway/profiles/{profile_path}", status_code=204)
    async def delete_profile(profile_path: str) -> None:
        _require_editable(profile_path)
        # SPEC-305 deliverable #5's guardrail, server-side (the UI hides the
        # control, but an API caller must hit the same wall): the default
        # profile is what every zero-config client connects to.
        if profile_path == DEFAULT_GATEWAY_PROFILE:
            raise HTTPException(
                status_code=400,
                detail=(
                    "the default profile cannot be deleted — it is where "
                    "clients connect when nothing else is configured. Fix: "
                    "create another profile and point clients at it instead."
                ),
            )
        try:
            await dynamic_gateway.remove_profile(profile_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _persist()
        _publish("gateway.profile.deleted", {"path": profile_path})

    @router.get("/api/gateway/vaults", response_model=list[GatewayVaultOut])
    async def list_vault_identities() -> list[GatewayVaultOut]:
        """Every vault's gateway identity (name/purpose/tool_renames), for
        the profile editor's inline-rename UI (SPEC-305 deliverable #1)."""
        return [_vault_out(v) for v in dynamic_gateway.config.vaults]

    @router.patch("/api/gateway/vaults/{vault_key}", response_model=GatewayVaultOut)
    async def update_vault_identity(
        vault_key: str, body: UpdateGatewayVaultRequest
    ) -> GatewayVaultOut:
        """Rename a vault's tools / change its display name or purpose,
        live and round-tripped to ``config.yaml`` (SPEC-305 deliverable #1,
        acceptance criterion "rename via UI round-trips to config.yaml and
        the live gateway"). Every profile that mounts this vault is
        rebuilt so the new names are reachable with no restart."""
        try:
            current = dynamic_gateway.config.vault(vault_key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        name = body.name if body.name is not None else current.name
        purpose = body.purpose if body.purpose is not None else current.purpose
        tool_renames = (
            body.tool_renames if body.tool_renames is not None else dict(current.tool_renames)
        )
        try:
            new_vault = VaultMountConfig(
                key=vault_key, name=name, purpose=purpose, tool_renames=tool_renames
            )
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            await dynamic_gateway.update_vault_identity(new_vault)
        except GatewayConfigError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        _persist()
        result = dynamic_gateway.config.vault(vault_key)
        _publish(
            "gateway.vault.updated",
            {"key": result.key, "name": result.name, "tool_renames": dict(result.tool_renames)},
        )
        return _vault_out(result)

    return router


__all__ = [
    "CreateGatewayProfileRequest",
    "GatewayProfileOut",
    "GatewayToolOut",
    "GatewayVaultOut",
    "RenameSanitizationOut",
    "UpdateGatewayProfileRequest",
    "UpdateGatewayVaultRequest",
    "build_gateway_profiles_router",
]
