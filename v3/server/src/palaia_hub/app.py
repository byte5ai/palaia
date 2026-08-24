"""ASGI app factory for the hub daemon.

One FastAPI app hosting the REST/dashboard API, the MCP gateway mount
point (SPEC-105, opt-in via the ``gateway`` parameter), the
``/api/auth/tokens`` token-management surface (SPEC-108, opt-in via the
``token_store`` parameter), and the ``/api/hooks`` webhook surface
(SPEC-201, opt-in via the ``hook_store`` parameter).
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from . import __version__
from .auth import TokenRecord, TokenStore, build_auth_router, check_gateway_auth_policy
from .automations import (
    AutomationDispatcher,
    AutomationOutbox,
    AutomationStore,
    build_automations_router,
)
from .automations.outbox import OUTBOX_RELATIVE_PATH as AUTOMATIONS_OUTBOX_RELATIVE_PATH
from .config import HubConfig, load_config, palaia_home
from .curator import CuratorScheduler
from .curator.wiring import CuratorWiring
from .dashboard_api import build_dashboard_router
from .directory.service import DirectoryService
from .directory_api import build_directory_router
from .events import (
    EventBus,
    bridge_vault_events,
    build_events_router,
    publish_event,
    start_background_tasks,
    stop_background_tasks,
)
from .gateway import DynamicGateway, GatewayASGI, VaultService
from .gateway.api import build_gateway_profiles_router
from .gateway.apps.hub_status_app import HubStatusDeps, build_hub_status_server
from .gateway.apps.market_app import MarketAppDeps, build_market_server
from .gateway.directory_tools import build_directory_gateway
from .gateway.stash_tools import build_stash_gateway
from .gateway.wiring import EngineVaultService
from .hooks import OUTBOX_RELATIVE_PATH, HookDispatcher, HookOutbox, HookStore, build_hooks_router
from .index import VaultIndex
from .logging import setup_logging
from .market import (
    InstallService,
    MarketService,
    build_market_install_router,
    build_market_router,
    wire_market_index_updates,
)
from .mcpb import build_mcpb_router
from .modes import AuthRateLimitMiddleware, ModeAuditLog, build_modes_router
from .notifications import NotificationStore, build_notifications_router
from .oauth import AuthorizationServer, build_oauth_router
from .stash.service import StashService
from .stash_api import build_stash_router
from .static import mount_dashboard
from .upstream.api import (
    build_secret_change_hook,
    build_secrets_router,
    build_upstreams_router,
)
from .upstream.monitor import UpstreamHealthMonitor
from .upstream.secrets import SecretStore
from .upstream.service import UpstreamService
from .vault import VaultNotFoundError, VaultRegistry

# Name of the env var that, when set to a positive number of seconds, adds a
# `/api/_test/slow` route that sleeps that long before responding. This
# exists solely so tests can exercise graceful-shutdown behavior (a slow
# request in flight when SIGTERM arrives) against a real server process; it
# never activates unless a test explicitly sets the env var.
_TEST_SLOW_ENDPOINT_ENV = "PALAIA_TEST_SLOW_ENDPOINT_SECONDS"


def create_app(
    config: HubConfig | None = None,
    *,
    gateway: GatewayASGI | None = None,
    dynamic_gateway: DynamicGateway | None = None,
    token_store: TokenStore | None = None,
    vault_services: Mapping[str, VaultService] | None = None,
    vault_registry: VaultRegistry | None = None,
    indexes: dict[str, VaultIndex] | None = None,
    event_bus: EventBus | None = None,
    oauth_server: AuthorizationServer | None = None,
    stash_service: StashService | None = None,
    directory_service: DirectoryService | None = None,
    market_service: MarketService | None = None,
    install_service: InstallService | None = None,
    hook_store: HookStore | None = None,
    hook_outbox: HookOutbox | None = None,
    curator: CuratorScheduler | None = None,
    automation_store: AutomationStore | None = None,
    automation_outbox: AutomationOutbox | None = None,
    notification_store: NotificationStore | None = None,
    curator_wiring: CuratorWiring | None = None,
    upstream_service: UpstreamService | None = None,
    upstream_monitor: UpstreamHealthMonitor | None = None,
    secret_store: SecretStore | None = None,
    home: Path | None = None,
) -> FastAPI:
    """Build the hub's ASGI app.

    Args:
        config: hub configuration; loaded via :func:`load_config` if omitted.
        home: the hub's home directory (``PALAIA_HOME``/platform data dir if
            omitted) — where ``config.yaml`` and the SPEC-205 mode-change
            audit log live. Passed through to
            :func:`palaia_hub.modes.build_modes_router`, which is always
            mounted (see below) since every hub has an operating mode.
        gateway: the MCP gateway (SPEC-105, ``palaia_hub.gateway.build_gateway``),
            mounted at its configured profile paths when given. Real wiring
            of vault services into a gateway happens in a later SPEC
            (SPEC-113); omitted, the hub runs with no MCP endpoint, same as
            before this parameter existed. Its lifespan MUST be attached to
            this app's lifespan (done below) or its mounted profile(s) hang
            on their first request — see ``gateway/build.py``'s docstring.
        token_store: the client-token store (SPEC-108); given, mounts the
            ``/api/auth/tokens`` REST surface (:func:`palaia_hub.auth.
            build_auth_router`). Omitted (the default), the hub runs with
            no token-management API at all, same as before this parameter
            existed — a caller that only needs the gateway's *enforcement*
            of tokens already-issued via the CLI does not need to pass one.

    Raises:
        palaia_hub.auth.AuthPolicyError: ``gateway`` is given, ``config.mode``
            is ``cloud``/``open``, and one or more of the gateway's mounted
            profiles has no auth attached (see ``auth/policy.py`` — this is
            the "hub refuses to start MCP endpoints without auth enabled"
            enforcement, checked against the gateway actually built rather
            than against config alone; :mod:`palaia_hub.config` already
            refuses the config-level version of this mistake earlier, at
            ``load_config()`` time).
        vault_services: the same ``{vault_key: VaultService}`` mapping passed
            to ``build_gateway`` (SPEC-107), used to back the
            ``/api/vaults/{vault_key}/inbox_status`` REST endpoint below.
            Independent of ``gateway`` on purpose: a caller can expose the
            REST endpoint without an MCP gateway mounted, and vice versa.
        vault_registry: the hub's vault registry (SPEC-102/SPEC-110). Given,
            mounts the wizard's "create a vault" endpoint and the memory
            explorer's list/read/search/history/graph endpoints
            (:mod:`palaia_hub.dashboard_api`), and backs ``inbox_status``
            above for any vault key known to the registry but absent from
            ``vault_services`` — so a vault created through the wizard at
            runtime is inbox-visible without also needing an entry in the
            (gateway-mounted-at-startup) ``vault_services`` mapping. Omitted
            (the default), the hub runs with no wizard/explorer REST surface
            at all, same as before this parameter existed. Also mounts
            ``/api/connect/mcpb`` (SPEC-306, :mod:`palaia_hub.mcpb`) — the
            Claude Desktop connect-page download, which needs it to know
            what scopes a minted token may carry.
        dynamic_gateway: the SPEC-210 dynamic gateway
            (:class:`palaia_hub.gateway.dynamic.DynamicGateway`), mounted
            once at ``/mcp`` when given — the production alternative to
            ``gateway`` for a caller (the CLI's ``serve`` command) that
            needs profiles rebuildable after startup, e.g. a vault the
            wizard creates at runtime. Its own ``start()``/``aclose()`` are
            driven from this app's lifespan below. Independent of
            ``gateway`` — a caller passes one or the other; nothing here
            stops both, but no production caller does.
        indexes: the SPEC-104 :class:`~palaia_hub.index.VaultIndex` open for
            each vault this hub serves, keyed the same as
            ``vault_services``. Backs ``GET
            /api/vaults/{vault_key}/index_status`` (mounted alongside the
            wizard/explorer router, so it also needs ``vault_registry``)
            and is closed, alongside ``dynamic_gateway``, from this app's
            lifespan. Omitted, the hub runs with no index-status endpoint,
            same as before this parameter existed.
        event_bus: the dashboard's live-state bus (SPEC-109). A caller that
            also wires SPEC-210's index-status live updates (a
            :class:`~palaia_hub.index.VaultIndex` built with
            ``on_backlog_drained=...`` publishing onto this same bus) must
            build the bus first and pass it in here, since a
            ``VaultIndex`` has to exist before ``create_app`` is called.
            Omitted (the default), this app builds its own — identical to
            this parameter never having existed.
        oauth_server: the OAuth 2.1 authorization server (SPEC-203). Given,
            mounts its discovery, ``/oauth/*`` and sign-in routes at the app
            root (:func:`palaia_hub.oauth.build_oauth_router`). Omitted (the
            default), the hub serves no OAuth endpoints at all, same as
            before this parameter existed — the resource *side* is
            independent of it (a profile's JWT verifier is wired into the
            gateway, not here), so a split deployment can verify tokens
            without hosting the endpoints that issue them.
        stash_service: the hub's stash cache (SPEC-202). Given, mounts the
            stash tool family at ``/mcp/stash`` and the ``/api/stash`` REST
            mirror, and wires its ``stash.*`` events onto ``event_bus``.
            Omitted (the default), the hub runs with no stash surface at
            all, same as before this parameter existed.
        directory_service: the hub's session directory (SPEC-402). Given,
            mounts the ``directory_*`` tool family at ``/mcp/directory``
            and the ``/api/directory`` read-only REST mirror, and wires its
            ``session.*`` events onto ``event_bus``. Omitted (the
            default), the hub runs with no session directory surface at
            all, same as before this parameter existed.
        market_service: the marketplace read model (SPEC-303 — official
            registry + curated index + manual entries, merged). Given,
            mounts ``/api/market/*`` and wires its
            ``market.index.updated`` event onto ``event_bus``. Omitted
            (the default), the hub runs with no marketplace surface at
            all, same as before this parameter existed. Also mounts the
            marketplace MCP App at ``/mcp/market`` (SPEC-304 deliverable
            #5) — independent of ``install_service``: browsing needs only
            this.
        install_service: marketplace install/lifecycle flows (SPEC-304
            deliverables #1/#3/#4 —
            :class:`~palaia_hub.market.install.InstallService`). Given
            together with ``market_service`` and ``event_bus``, mounts the
            consent/install/installed-add-on REST surface under
            ``/api/market/*`` (alongside ``market_service``'s own read-only
            routes) and subscribes its update check onto
            ``market.index.updated``. Omitted (the default), the hub
            serves marketplace *browsing* (when ``market_service`` is
            given) but no install flow at all — the dashboard's install
            button then has nothing to call.
        hook_store: outbound-webhook configuration (SPEC-201). Given, mounts
            the ``/api/hooks`` REST surface and starts the delivery worker
            that turns every published event into a signed webhook POST for
            every matching, enabled hook. Omitted (the default), the hub
            publishes events on its bus same as always, just with no
            webhook consumer attached.
        curator: the SPEC-206 curator scheduler. Given, it is started with
            this app and stopped with it — the curator is a hook-driven
            automation living inside the hub, not a second daemon (MASTERPLAN
            §5.1). Omitted (the default), no curation ever runs from this
            process; ``palaia-hub curator run`` still works on demand.
        curator_wiring: the same curator, as its whole
            :class:`~palaia_hub.curator.wiring.CuratorWiring` rather than
            just its scheduler (SPEC-301). Given, a vault created through
            the wizard also joins this curator's vault set live (see
            :meth:`~palaia_hub.curator.wiring.CuratorWiring.add_vault`,
            wired into :mod:`palaia_hub.dashboard_api`'s ``create_vault``).
            Omitted, a wizard-created vault stays off the curator until a
            restart, exactly as before this parameter existed.
        upstream_service: the external-server registry (SPEC-302). Given
            together with ``dynamic_gateway``, mounts
            ``/api/gateway/upstreams`` and every connection it holds
            (including a ``stdio`` upstream's child process) is closed by
            this app's own lifespan. Omitted, the hub serves no external
            servers at all, same as before this parameter existed.
        upstream_monitor: the periodic reachability probe for those servers
            (:class:`~palaia_hub.upstream.monitor.UpstreamHealthMonitor`).
            Started at the *end* of startup — deliberately after the gateway
            has mounted its profiles, so a hub whose external server is
            unreachable still starts instantly (SPEC-302 deliverable #4) —
            and stopped before the connections are reaped.
        secret_store: the encrypted credential store (SPEC-302). Given,
            mounts the write-only ``/api/secrets`` surface — independent of
            ``dynamic_gateway`` on purpose, so a credential can be entered
            before anything is connected — and is closed at shutdown.
        hook_outbox: the durable delivery queue backing ``hook_store``.
            Defaults to :class:`~palaia_hub.hooks.HookOutbox` at its
            standard path under the hub's data directory when ``hook_store``
            is given and this is omitted; pass one explicitly in tests that
            need an isolated path.
        automation_store: the trigger -> condition -> action editor's
            configuration (SPEC-307). Given, mounts the ``/api/automations``
            REST surface and starts the delivery worker that turns every
            matching, enabled automation into a ``memory_write``/
            ``stash_set``/``notification`` action. The ``memory_write``
            action kind needs ``vault_registry`` and the ``stash_set`` kind
            needs ``stash_service`` — a delivery whose action kind has no
            backing service configured fails with a plain-language error
            rather than crashing the worker. Omitted (the default), the hub
            runs with no automations surface at all.
        automation_outbox: the durable delivery queue backing
            ``automation_store``. Defaults to
            :class:`~palaia_hub.automations.AutomationOutbox` at its
            standard path when ``automation_store`` is given and this is
            omitted.
        notification_store: the dashboard notification center (SPEC-307).
            Given, mounts ``/api/notifications`` and is what the
            ``notification`` automation action kind writes to. Independent
            of ``automation_store`` on purpose, same as ``stash_service``
            vs. ``hook_store`` — a caller can expose the bell without
            automations, though nothing else writes to it today.
    """
    config = config or load_config()
    vault_services = vault_services or {}
    setup_logging(config)
    if gateway is not None:
        check_gateway_auth_policy(config.mode, gateway.profile_servers)

    start_time = time.monotonic()
    event_bus = event_bus or EventBus()

    def health_snapshot() -> dict[str, Any]:
        return {"status": "ok", "components": {"config": "ok"}}

    stash_gateway = None
    if stash_service is not None:
        def _publish_stash(action: str, data: dict[str, Any]) -> None:
            publish_event(event_bus, action, origin="stash", data=data)

        stash_service.publish = _publish_stash
        stash_gateway = build_stash_gateway(stash_service)

    directory_gateway = None
    if directory_service is not None:
        def _publish_directory(action: str, data: dict[str, Any]) -> None:
            publish_event(event_bus, action, origin="directory", data=data)

        directory_service.publish = _publish_directory
        directory_gateway = build_directory_gateway(directory_service)

    if market_service is not None:
        def _publish_market(action: str, data: dict[str, Any]) -> None:
            publish_event(event_bus, action, origin="market", data=data)

        market_service.publish = _publish_market

    # SPEC-208 deliverable #2: the hub_status MCP App, mounted at
    # `/mcp/hub` — hub-level (not per-vault, unlike the memory tool
    # family), same opt-in-on-vault_registry gating as the dashboard router
    # below, since there is nothing to report without one. Independent of
    # `gateway`/`dynamic_gateway`: this is its own standalone FastMCP
    # instance, not a profile of either.
    hub_status_asgi_app = None
    if vault_registry is not None:
        hub_status_deps = HubStatusDeps(
            vault_registry=vault_registry,
            indexes=indexes,
            token_store=token_store,
            mode=config.mode,
            start_time=start_time,
        )
        hub_status_server = build_hub_status_server(hub_status_deps)
        hub_status_asgi_app = hub_status_server.http_app(path="/")

    # SPEC-304 deliverable #5: the marketplace MCP App, mounted at
    # `/mcp/market` — hub-level, same standalone-FastMCP-instance shape as
    # hub_status above. Gated on `market_service` alone (not
    # `install_service`): browsing needs no install machinery at all.
    market_asgi_app = None
    if market_service is not None:
        market_app_deps = MarketAppDeps(
            market_service=market_service,
            dashboard_url=(
                config.exposure.public_url.rstrip("/")
                if config.exposure.public_url
                else None
            ),
        )
        market_asgi_app = build_market_server(market_app_deps).http_app(path="/")

    # One lifespan runs BOTH concerns: the events background tasks (SPEC-109)
    # and, when a gateway is mounted, its session-manager lifespan (SPEC-105 —
    # skipping it hangs the mounted profiles on their first request). The
    # stash server's own lifespan (SPEC-202) is combined in the same way.
    # SPEC-201: unify the vault registry's internal change events onto the
    # public bus — one bus, three consumers (in-process, SSE, webhooks; see
    # palaia_hub.events.bridge's module docstring). Only possible when the
    # registry was itself built with a vault.events.EventBus (cli.serve()
    # does this; a caller that omits it — most tests — gets no bridge,
    # same as before this SPEC existed).
    unbridge_vault: Callable[[], None] | None = None
    if vault_registry is not None and vault_registry.bus is not None:
        unbridge_vault = bridge_vault_events(vault_registry.bus, event_bus)

    # SPEC-201: "client.connected" fires on a token's first successful
    # verify() this process. Wired regardless of whether a real MCP gateway
    # is mounted here (see PalaiaTokenVerifier — it calls store.verify()
    # from inside fastmcp's auth path), so it is ready the moment one is.
    if token_store is not None:

        def _on_verified(record: TokenRecord, is_first_use: bool) -> None:
            if not is_first_use:
                return
            publish_event(
                event_bus,
                "client.connected",
                origin="auth",
                data={
                    "token_id": record.id,
                    "client_name": record.name,
                    "profile": record.profile,
                },
            )

        token_store.on_verified = _on_verified

    # SPEC-201: outbound webhooks. The dispatcher subscribes to the bus as
    # an ordinary in-process consumer (deliverable #4's own API) — nothing
    # about the bus knows webhooks exist.
    dispatcher: HookDispatcher | None = None
    outbox: HookOutbox | None = None
    if hook_store is not None:
        outbox = hook_outbox or HookOutbox(_default_outbox_path())
        dispatcher = HookDispatcher(hook_store, outbox)
        event_bus.on(dispatcher.on_event)

    # SPEC-307: the automations dispatcher, same "in-process bus consumer"
    # posture as the hooks dispatcher above — nothing about the bus knows
    # automations exist either.
    automation_dispatcher: AutomationDispatcher | None = None
    automation_outbox_: AutomationOutbox | None = None
    if automation_store is not None:
        automation_outbox_ = automation_outbox or AutomationOutbox(
            _default_automations_outbox_path()
        )

        def _emit_automation_event(event_name: str, data: dict[str, Any]) -> None:
            publish_event(event_bus, event_name, origin="automations", data=data)

        automation_dispatcher = AutomationDispatcher(
            automation_store,
            automation_outbox_,
            vault_registry=vault_registry,
            stash_service=stash_service,
            notification_store=notification_store,
            emit=_emit_automation_event,
        )
        event_bus.on(automation_dispatcher.on_event)

    # One lifespan runs every background concern: the events ticker
    # (SPEC-109), the webhook delivery worker (SPEC-201), and, when a
    # gateway is mounted, its session-manager lifespan (SPEC-105 —
    # skipping it hangs the mounted profiles on their first request).
    @asynccontextmanager
    async def lifespan(app_: FastAPI) -> AsyncIterator[None]:
        tasks = start_background_tasks(event_bus, health_snapshot=health_snapshot)
        if dynamic_gateway is not None:
            await dynamic_gateway.start()
        if dispatcher is not None:
            tasks.append(asyncio.create_task(dispatcher.run_forever()))
        if automation_dispatcher is not None:
            tasks.append(asyncio.create_task(automation_dispatcher.run_forever()))
        if curator is not None:
            await curator.start()
        # SPEC-302: the first external-server probe pass runs here, in the
        # background — after the gateway has already mounted every profile,
        # so a hub whose upstream is unreachable still starts instantly and
        # the profile picks the server up on the pass that finds it.
        if upstream_monitor is not None:
            await upstream_monitor.start()
        publish_event(
            event_bus,
            "hub.started",
            origin="hub",
            data={"version": __version__, "mode": config.mode},
        )
        try:
            async with AsyncExitStack() as stack:
                if gateway is not None:
                    await stack.enter_async_context(gateway.lifespan(app_))
                if stash_gateway is not None:
                    await stack.enter_async_context(stash_gateway.lifespan(app_))
                if directory_gateway is not None:
                    await stack.enter_async_context(directory_gateway.lifespan(app_))
                if hub_status_asgi_app is not None:
                    await stack.enter_async_context(hub_status_asgi_app.lifespan(app_))
                if market_asgi_app is not None:
                    await stack.enter_async_context(market_asgi_app.lifespan(app_))
                yield
        finally:
            await stop_background_tasks(tasks)
            if curator is not None:
                await curator.aclose()
            # Stop probing before the gateway goes away, then reap every
            # upstream connection — for a `stdio` upstream that is what
            # kills its child process (SPEC-302 acceptance: "process reaped
            # on hub shutdown").
            if upstream_monitor is not None:
                await upstream_monitor.aclose()
            if upstream_service is not None:
                await upstream_service.aclose()
            if secret_store is not None:
                secret_store.close()
            if dynamic_gateway is not None:
                await dynamic_gateway.aclose()
            if indexes is not None:
                for index in indexes.values():
                    await index.close()
            if dispatcher is not None:
                await dispatcher.aclose()
            if unbridge_vault is not None:
                unbridge_vault()

    app = FastAPI(title="palaia-hub", version=__version__, lifespan=lifespan)
    app.state.config = config
    app.state.start_time = start_time
    app.state.event_bus = event_bus
    if config.mode in ("cloud", "open"):
        # SPEC-205 deliverable #4: these endpoints become reachable off the
        # operator's own network in these two modes — 'locked' has no such
        # surface to throttle, so this middleware never exists there.
        app.add_middleware(AuthRateLimitMiddleware)
    if gateway is not None:
        for path, mounted_app in gateway.mounts.items():
            app.mount(path, mounted_app)
    # The stash and hub_status mounts are registered before the
    # DynamicGateway's "/mcp" catch-all: Starlette matches mounts in
    # registration order, so the more specific paths must come first or the
    # gateway would shadow them.
    if stash_gateway is not None:
        app.mount("/mcp/stash", stash_gateway.app)
    if directory_gateway is not None:
        app.mount("/mcp/directory", directory_gateway.app)
    if hub_status_asgi_app is not None:
        app.mount("/mcp/hub", hub_status_asgi_app)
    if market_asgi_app is not None:
        app.mount("/mcp/market", market_asgi_app)
    if dynamic_gateway is not None:
        # One mount, forever: DynamicGateway owns everything below "/mcp"
        # and rebuilds its own internal routing as profiles come and go
        # (see that class's docstring) — Starlette's own route list here
        # never changes after this line.
        app.mount("/mcp", dynamic_gateway.asgi_app)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        """Liveness + component readiness. No dependencies in this SPEC."""
        return health_snapshot()

    @app.get("/api/info")
    async def info() -> dict[str, Any]:
        """Version, operating mode, uptime, and how the owner signs in.

        ``sign_in`` is non-secret (no client id, no allow-list) and is what
        the dashboard's settings section (SPEC-204 deliverable #4) reads to
        show "Sign in with GitHub" / a configured provider's name / the
        local password, in plain language.
        """
        sign_in: dict[str, str | None]
        if oauth_server is not None and oauth_server.idp_configured:
            sign_in = {"method": "idp", "provider_name": oauth_server.idp_display_name}
        elif oauth_server is not None:
            sign_in = {"method": "password", "provider_name": None}
        else:
            sign_in = {"method": "none", "provider_name": None}
        return {
            "version": __version__,
            "mode": config.mode,
            "uptime_seconds": round(time.monotonic() - start_time, 3),
            "sign_in": sign_in,
        }

    # SPEC-107: inbox visibility outside the MCP surface (deliverable #3).
    @app.get("/api/vaults/{vault_key}/inbox_status")
    async def inbox_status(vault_key: str) -> dict[str, Any]:
        service = vault_services.get(vault_key)
        if service is None and vault_registry is not None:
            try:
                service = EngineVaultService(await vault_registry.get(vault_key))
            except VaultNotFoundError:
                service = None
        if service is None:
            raise HTTPException(
                status_code=404,
                detail=f"no vault {vault_key!r} configured with a backing service",
            )
        status = await service.inbox_status()
        return status.model_dump()

    # SPEC-109: the dashboard's live-state layer (health + vault-change
    # events) and, once `npm run build` has produced one, the static
    # dashboard build itself. The dashboard mount goes last so it never
    # shadows an /api/* route (see static.mount_dashboard).
    app.include_router(build_events_router(event_bus, health_snapshot=health_snapshot))

    # SPEC-205: always mounted, like /api/health and /api/info — every hub
    # has an operating mode, so this needs no opt-in parameter. `hub_home`
    # is only ever used lazily, inside request handlers (config.yaml is
    # read/patched per-request, never at app-build time) — mounting this
    # router has no filesystem side effect by itself.
    hub_home = home or palaia_home()
    app.include_router(
        build_modes_router(
            config,
            home=hub_home,
            event_bus=event_bus,
            audit_log=ModeAuditLog(hub_home),
            oauth_store=oauth_server.store if oauth_server is not None else None,
        )
    )

    if token_store is not None:
        app.include_router(build_auth_router(token_store))

    # SPEC-203: the OAuth surface goes at the app root (RFC 8414/9728 fix the
    # `.well-known` paths there) and before the dashboard mount, which claims
    # "/" last.
    if oauth_server is not None:
        app.include_router(build_oauth_router(oauth_server))

    if vault_registry is not None:
        app.include_router(
            build_dashboard_router(
                vault_registry,
                indexes=indexes,
                dynamic_gateway=dynamic_gateway,
                curator=curator_wiring,
            )
        )

    # SPEC-301 deliverable #2: the runtime profile-editor REST surface.
    # Needs a live gateway to apply an edit to and `home` to persist it to
    # `config.yaml` — the same opt-in-on-`dynamic_gateway` gate the
    # dashboard router above uses, since there is nothing to edit without
    # one.
    if dynamic_gateway is not None:
        app.include_router(
            build_gateway_profiles_router(
                dynamic_gateway,
                home=hub_home,
                config=config,
                event_bus=event_bus,
                oauth_server=oauth_server,
                token_store=token_store,
            )
        )
    # SPEC-302: external MCP servers, and the write-only secret store their
    # credentials live in. The upstream surface needs a live gateway to
    # mount onto (same gate as the profile editor above); the secret surface
    # only needs the store, so a credential can be entered before anything
    # is connected.
    if secret_store is not None:
        app.include_router(
            build_secrets_router(
                secret_store,
                on_secret_changed=(
                    build_secret_change_hook(upstream_service, dynamic_gateway)
                    if upstream_service is not None and dynamic_gateway is not None
                    else None
                ),
            )
        )
    if dynamic_gateway is not None and upstream_service is not None:
        app.include_router(
            build_upstreams_router(
                dynamic_gateway,
                upstream_service,
                home=hub_home,
                config=config,
                event_bus=event_bus,
            )
        )
    # SPEC-306: the Claude Desktop connect-page "Download bundle" button.
    # Mounted whenever there is a vault registry to compute scopes from,
    # same gating as the dashboard router above — the route itself answers
    # 501 if neither auth path (token_store, oauth_server) is configured,
    # rather than 404ing as if the feature did not exist.
    if vault_registry is not None:
        app.include_router(
            build_mcpb_router(
                vault_registry=vault_registry,
                token_store=token_store,
                oauth_server=oauth_server,
                home=hub_home,
            )
        )

    if stash_service is not None:
        app.include_router(build_stash_router(stash_service))
    if directory_service is not None:
        app.include_router(build_directory_router(directory_service))
    if market_service is not None:
        app.include_router(build_market_router(market_service))
    if install_service is not None:
        app.include_router(build_market_install_router(install_service))
        # SPEC-304 deliverable #4: recompute every installed container's
        # update status whenever the curated index refreshes, and publish
        # `addon.update_available` for whichever just turned stale.
        wire_market_index_updates(event_bus, install_service)
    if hook_store is not None:
        assert outbox is not None  # built above, together with hook_store's dispatcher
        app.include_router(build_hooks_router(hook_store, outbox))
    if notification_store is not None:
        app.include_router(build_notifications_router(notification_store))
    if automation_store is not None:
        assert automation_outbox_ is not None  # built above, with automation_store's dispatcher
        assert automation_dispatcher is not None
        app.include_router(
            build_automations_router(automation_store, automation_outbox_, automation_dispatcher)
        )

    _maybe_add_test_slow_route(app)

    mount_dashboard(app)

    return app


def _default_outbox_path() -> Path:
    """Where the hooks outbox lives when ``create_app`` is not given one explicitly."""
    return palaia_home() / OUTBOX_RELATIVE_PATH


def _default_automations_outbox_path() -> Path:
    """Where the automations outbox lives when ``create_app`` is not given one explicitly."""
    return palaia_home() / AUTOMATIONS_OUTBOX_RELATIVE_PATH


def _maybe_add_test_slow_route(app: FastAPI) -> None:
    raw_seconds = os.environ.get(_TEST_SLOW_ENDPOINT_ENV)
    if not raw_seconds:
        return
    seconds = float(raw_seconds)

    @app.get("/api/_test/slow")
    async def _slow() -> dict[str, Any]:
        await asyncio.sleep(seconds)
        return {"status": "done"}
