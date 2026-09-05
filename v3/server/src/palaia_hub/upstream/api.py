"""REST for external servers and the secret store (SPEC-302 #2/#4).

Two surfaces, one rule between them.

``/api/gateway/upstreams`` — connect, edit, disconnect and health-check an
external MCP server. Every write does the same three things in the same
order as SPEC-301's profile editor: validate against the gateway actually
running, apply it live to the :class:`~palaia_hub.gateway.dynamic.
DynamicGateway` (no restart), then write the new shape back to
``config.yaml`` (so it survives one).

``/api/secrets`` — **write-only, names-only.** There is no route that returns
a secret value, and no response model in this module has a field one could be
placed in: :class:`SecretOut` carries a name and two timestamps. That is the
SPEC's fixed design, implemented structurally rather than by remembering not
to fill a field in. The value goes in through ``PUT`` and comes out only
inside the hub, when :mod:`palaia_hub.upstream.service` builds a header or a
child process's environment.

Error messages here name secrets and servers by *name*, never by value, and
never echo a request body back (a 422 from pydantic on a ``PUT`` body would
otherwise quote the value it rejected — which is why
:class:`SecretPutRequest` accepts any non-empty string and does its own
checking in the handler).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import HubConfig, config_file_path
from ..events import EventBus, publish_event
from ..gateway.build import GatewayConfigError
from ..gateway.config import CURATOR_PROFILE_PATH
from ..gateway.dynamic import DynamicGateway
from ..gateway.settings_bridge import persist_gateway_settings, snapshot_gateway_settings
from .models import UpstreamConfig, UpstreamConflictError
from .secrets import SecretStore, SecretStoreError, validate_secret_name
from .service import UpstreamNotConfiguredError, UpstreamService

logger = logging.getLogger("palaia_hub.upstream.api")


class UpstreamOut(BaseModel):
    """One external server as the dashboard sees it — credential-free.

    ``secret_names`` lists which stored secrets this server *uses*, so a UI
    can show "needs a token you have not entered yet". It never carries a
    value, and neither does anything else here.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    kind: str
    display_name: str
    namespace: str
    enabled: bool
    #: Where it points: the URL, or the command line. Credential-free by
    #: construction — a token lives in the secret store, never in either.
    target: str
    #: Profiles that mount this server (SPEC-301 profile shapes).
    profiles: list[str]
    up: bool
    #: One plain-language line: connected and how many tools, or why not.
    status: str
    checked_at: float | None
    tools: list[str]
    secret_names: list[str]
    tool_renames: dict[str, str]


class ConnectUpstreamRequest(BaseModel):
    """``POST /api/gateway/upstreams`` — the config, plus where to mount it.

    ``profiles`` is a convenience: naming them here mounts the server on
    them in the same call instead of requiring a follow-up PATCH per
    profile. The curator profile is refused (SPEC-302 deliverable #6).
    """

    model_config = ConfigDict(extra="forbid")

    upstream: UpstreamConfig
    profiles: list[str] = Field(default_factory=list)


class UpdateUpstreamRequest(BaseModel):
    """``PATCH /api/gateway/upstreams/{key}`` — every field optional.

    ``key``, ``kind`` and ``namespace`` are absent on purpose: the first two
    are identity, and changing the third renames every tool a connected
    client already approved. Disconnect and reconnect for those.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    enabled: bool | None = None
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    tool_renames: dict[str, str] | None = None
    profiles: list[str] | None = None


class SecretOut(BaseModel):
    """A stored secret's *metadata*. There is no value field, by design."""

    model_config = ConfigDict(extra="forbid")

    name: str
    created_at: float
    updated_at: float


class SecretPutRequest(BaseModel):
    """``PUT /api/secrets/{name}`` — the one place a value travels inbound."""

    model_config = ConfigDict(extra="forbid")

    value: str


def build_secret_change_hook(
    upstream_service: UpstreamService, dynamic_gateway: DynamicGateway
) -> Callable[[str], Awaitable[None]]:
    """The "a secret's value changed" reaction (SPEC-302 deliverable #3).

    An external server's credential is baked into its transport when the
    connection is built — a ``stdio`` child's environment at spawn time, an
    HTTP transport's headers at construction time — so replacing a stored
    value has no effect on a server that is already connected until that
    connection is thrown away. This hook does exactly that, for the servers
    that actually reference the changed name, and then lets the profiles
    mounting them be rebuilt around the fresh connection. A name nothing
    references costs one dictionary scan and nothing else.
    """

    async def _on_change(name: str) -> None:
        affected = [
            config.key
            for config in upstream_service.configs.values()
            if name in _secret_names(config)
        ]
        if not affected:
            return
        for key in affected:
            await upstream_service.register(upstream_service.config(key))
        await dynamic_gateway.refresh_upstreams(affected)

    return _on_change


def build_secrets_router(
    secret_store: SecretStore,
    *,
    on_secret_changed: Callable[[str], Awaitable[None]] | None = None,
) -> APIRouter:
    """The write-only secret surface (SPEC-302 deliverable #2).

    Args:
        secret_store: the encrypted store.
        on_secret_changed: awaited with a secret's name after its value is
            replaced or removed — normally
            :func:`build_secret_change_hook`, so a connected server picks up
            a rotated credential without a restart. Omitted, writes still
            work; a server already connected keeps using the old value until
            it is edited or the hub restarts.
    """
    router = APIRouter(tags=["secrets"])

    @router.get("/api/secrets", response_model=list[SecretOut])
    async def list_secrets() -> list[SecretOut]:
        """Names and timestamps only — never values."""
        return [
            SecretOut(name=info.name, created_at=info.created_at, updated_at=info.updated_at)
            for info in secret_store.names()
        ]

    @router.put("/api/secrets/{name}", response_model=SecretOut)
    async def put_secret(name: str, body: SecretPutRequest) -> SecretOut:
        """Store a value under ``name``, replacing any previous one.

        The response confirms *that* it was stored, never *what* was
        stored — there is nowhere in :class:`SecretOut` to put it.
        """
        try:
            validate_secret_name(name)
            info = secret_store.put(name, body.value)
        except SecretStoreError as exc:
            # `str(exc)` is safe: every SecretStoreError message names the
            # secret and the fix, and none of them interpolates a value.
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if on_secret_changed is not None:
            await on_secret_changed(name)
        return SecretOut(name=info.name, created_at=info.created_at, updated_at=info.updated_at)

    @router.delete("/api/secrets/{name}", status_code=204)
    async def delete_secret(name: str) -> None:
        if not secret_store.delete(name):
            raise HTTPException(status_code=404, detail=f"no secret stored under {name!r}")
        if on_secret_changed is not None:
            await on_secret_changed(name)

    return router


def _secret_names(config: UpstreamConfig) -> list[str]:
    names = sorted(config.env_secrets.values())
    if config.auth is not None:
        names = sorted({*names, config.auth.secret_name})
    return names


def build_upstreams_router(
    dynamic_gateway: DynamicGateway,
    upstream_service: UpstreamService,
    *,
    home: Path,
    config: HubConfig,
    event_bus: EventBus | None = None,
    refresh: Callable[[list[str]], Awaitable[object]] | None = None,
) -> APIRouter:
    """Build the external-server router (SPEC-302 deliverables #1/#3/#4).

    Args:
        dynamic_gateway: the live gateway every write applies to.
        upstream_service: the registry that owns connections and health.
        home: where ``config.yaml`` lives, for the write-back.
        config: the running config — only its ``gateway.vaults``/
            ``gateway.profiles`` identity overrides are read (never
            mutated); the authoritative profile/upstream shape is the
            gateway's own.
        event_bus: publishes ``gateway.upstream.up``/``down`` transitions
            triggered by a probe from here. Omitted, probes still work.
        refresh: how a mountability change is applied — normally
            :meth:`DynamicGateway.refresh_upstreams`. Injected rather than
            called directly so a test can observe it.
    """
    router = APIRouter(tags=["gateway"])
    config_path = config_file_path(home)
    apply_refresh = refresh or dynamic_gateway.refresh_upstreams

    def _profiles_mounting(key: str) -> list[str]:
        return sorted(
            profile.path for profile in dynamic_gateway.config.profiles if key in profile.upstreams
        )

    def _out(key: str) -> UpstreamOut:
        upstream = upstream_service.config(key)
        status = upstream_service.status(key)
        return UpstreamOut(
            key=upstream.key,
            kind=upstream.kind,
            display_name=upstream.display_name,
            namespace=upstream.mount_namespace,
            enabled=upstream.enabled,
            target=upstream.target,
            profiles=_profiles_mounting(key),
            up=status.up,
            status=status.detail,
            checked_at=status.checked_at,
            tools=list(status.tools),
            secret_names=_secret_names(upstream),
            tool_renames=dict(upstream.tool_renames),
        )

    def _persist() -> None:
        """Write the gateway's current shape back to ``config.yaml``.

        Same contract as SPEC-301's profile editor: the curator profile is
        excluded (it is synthesized from ``curator:``, not stored here), and
        the per-vault identity overrides already in the file are carried
        through untouched.
        """
        # The shared live-then-persisted snapshot (settings_bridge): a
        # hand-built copy here once dropped hidden_tools/semantic_routing
        # from every profile on any upstream edit or secret rotation.
        persist_gateway_settings(config_path, snapshot_gateway_settings(dynamic_gateway, config))

    def _publish(event: str, data: dict[str, object]) -> None:
        if event_bus is not None:
            publish_event(event_bus, event, origin="gateway", data=data)

    async def _mount_on(key: str, profile_paths: list[str]) -> None:
        """Add ``key`` to each named profile's ``upstreams`` list, live."""
        for path in profile_paths:
            if path == CURATOR_PROFILE_PATH:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "the curator profile never mounts an external server: it "
                        "runs a model over your own notes, and an outside tool in "
                        "that session could exfiltrate them."
                    ),
                )
            current = next((p for p in dynamic_gateway.config.profiles if p.path == path), None)
            if current is None:
                raise HTTPException(status_code=404, detail=f"no profile at path {path!r}")
            if key in current.upstreams:
                continue
            # Issue #324: only the upstream list changes; hidden_tools,
            # messenger, directory and semantic_routing stay as they are.
            await dynamic_gateway.set_profile_upstreams(path, [*current.upstreams, key])

    async def _unmount_from(key: str, keep: list[str]) -> None:
        """Make exactly ``keep`` mount ``key`` — remove it everywhere else."""
        for profile in list(dynamic_gateway.config.profiles):
            if key in profile.upstreams and profile.path not in keep:
                await dynamic_gateway.set_profile_upstreams(
                    profile.path, [k for k in profile.upstreams if k != key]
                )

    @router.get("/api/gateway/upstreams", response_model=list[UpstreamOut])
    async def list_upstreams() -> list[UpstreamOut]:
        """Every connected server with its last known health (deliverable #4)."""
        return [_out(status.key) for status in upstream_service.statuses()]

    @router.post("/api/gateway/upstreams", response_model=UpstreamOut)
    async def connect_upstream(body: ConnectUpstreamRequest) -> UpstreamOut:
        upstream = body.upstream
        if upstream.key in upstream_service.configs:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"an external server is already connected under {upstream.key!r}. "
                    "Fix: PATCH it, or pick a different key."
                ),
            )
        try:
            await dynamic_gateway.register_upstream(upstream)
        except (UpstreamConflictError, ValidationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await upstream_service.register(upstream)
        try:
            await _mount_on(upstream.key, body.profiles)
        except GatewayConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await apply_refresh([upstream.key])
        _persist()
        _publish(
            "gateway.upstream.connected",
            {
                "upstream": upstream.key,
                "display_name": upstream.display_name,
                "kind": upstream.kind,
                "namespace": upstream.mount_namespace,
                "profiles": _profiles_mounting(upstream.key),
            },
        )
        return _out(upstream.key)

    @router.patch("/api/gateway/upstreams/{key}", response_model=UpstreamOut)
    async def update_upstream(key: str, body: UpdateUpstreamRequest) -> UpstreamOut:
        try:
            current = upstream_service.config(key)
        except UpstreamNotConfiguredError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        updates = body.model_dump(exclude_unset=True, exclude_none=True)
        updates.pop("profiles", None)
        try:
            updated = current.model_copy(update=updates)
            # `model_copy` skips validators; re-construct so a now-invalid
            # combination (an http upstream with its url blanked, say) is
            # refused rather than mounted.
            updated = UpstreamConfig.model_validate(updated.model_dump())
        except (ValidationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            await dynamic_gateway.register_upstream(updated)
        except (UpstreamConflictError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await upstream_service.register(updated)
        if body.profiles is not None:
            try:
                await _mount_on(key, body.profiles)
                await _unmount_from(key, body.profiles)
            except GatewayConfigError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        await apply_refresh([key])
        _persist()
        _publish(
            "gateway.upstream.updated",
            {
                "upstream": key,
                "display_name": updated.display_name,
                "enabled": updated.enabled,
                "profiles": _profiles_mounting(key),
            },
        )
        return _out(key)

    @router.post("/api/gateway/upstreams/{key}/probe", response_model=UpstreamOut)
    async def probe_upstream(key: str) -> UpstreamOut:
        """Check reachability now (deliverable #4's on-demand half)."""
        try:
            before = upstream_service.status(key).up
            await upstream_service.probe(key)
        except UpstreamNotConfiguredError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if upstream_service.status(key).up != before:
            await apply_refresh([key])
        return _out(key)

    @router.delete("/api/gateway/upstreams/{key}", status_code=204)
    async def disconnect_upstream(key: str) -> None:
        try:
            upstream_service.config(key)
        except UpstreamNotConfiguredError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        await dynamic_gateway.remove_upstream(key)
        await upstream_service.unregister(key)
        _persist()
        _publish("gateway.upstream.disconnected", {"upstream": key})

    return router


__all__ = [
    "ConnectUpstreamRequest",
    "SecretOut",
    "SecretPutRequest",
    "UpdateUpstreamRequest",
    "UpstreamOut",
    "build_secret_change_hook",
    "build_secrets_router",
    "build_upstreams_router",
]
