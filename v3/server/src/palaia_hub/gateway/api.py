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
from fastmcp.server.auth import AuthProvider
from pydantic import BaseModel, ConfigDict, ValidationError

from ..auth.policy import AuthPolicyError
from ..auth.store import TokenStore
from ..config import GatewayProfileSettings, GatewaySettings, HubConfig, config_file_path
from ..events import EventBus, publish_event
from ..oauth import AuthorizationServer
from ..oauth.verifier import build_profile_auth
from .build import GatewayConfigError
from .config import CURATOR_PROFILE_PATH, ProfileConfig
from .dynamic import DynamicGateway
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
    #: External MCP servers this profile mounts (SPEC-302), by key. The
    #: profile editor (SPEC-305) assigns them through this same surface
    #: rather than a second write path.
    upstreams: list[str]
    #: The curator's own profile is listed (so the editor can show it) but
    #: every write route below refuses to touch it — see the module
    #: docstring.
    managed: bool


class CreateGatewayProfileRequest(BaseModel):
    """``POST /api/gateway/profiles`` — ``path`` is set here, once, and
    never appears in :class:`UpdateGatewayProfileRequest` below: there is
    no "rename the URL" operation (see ``ProfileConfig``'s docstring)."""

    model_config = ConfigDict(extra="forbid")

    path: str
    label: str | None = None
    vaults: list[str] = []
    stash: bool = False
    upstreams: list[str] = []


class UpdateGatewayProfileRequest(BaseModel):
    """``PATCH /api/gateway/profiles/{path}`` — every field optional; an
    omitted one keeps its current value. ``vaults``, when given, *replaces*
    the whole mounted-vault list (there is no separate add/remove verb)."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    vaults: list[str] | None = None
    stash: bool | None = None
    #: Same whole-list contract as ``vaults`` (SPEC-302): given, it replaces
    #: the profile's external-server list entirely.
    upstreams: list[str] | None = None


def _out(profile: ProfileConfig) -> GatewayProfileOut:
    return GatewayProfileOut(
        path=profile.path,
        label=profile.label,
        vaults=list(profile.vaults),
        stash=profile.stash,
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
        existing_vaults = config.gateway.vaults if config.gateway is not None else []
        profiles = [
            p for p in dynamic_gateway.config.profiles if p.path != CURATOR_PROFILE_PATH
        ]
        settings = GatewaySettings(
            vaults=existing_vaults,
            profiles=[
                GatewayProfileSettings(
                    path=p.path,
                    label=p.label,
                    vaults=list(p.vaults),
                    stash=p.stash,
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
        return [_out(p) for p in dynamic_gateway.config.profiles]

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
        return _out(result)

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
        upstreams = body.upstreams if body.upstreams is not None else list(current.upstreams)
        try:
            ProfileConfig(
                path=profile_path,
                label=label,
                vaults=vaults,
                stash=stash,
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
        return _out(result)

    @router.delete("/api/gateway/profiles/{profile_path}", status_code=204)
    async def delete_profile(profile_path: str) -> None:
        _require_editable(profile_path)
        try:
            await dynamic_gateway.remove_profile(profile_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _persist()
        _publish("gateway.profile.deleted", {"path": profile_path})

    return router


__all__ = [
    "CreateGatewayProfileRequest",
    "GatewayProfileOut",
    "UpdateGatewayProfileRequest",
    "build_gateway_profiles_router",
]
