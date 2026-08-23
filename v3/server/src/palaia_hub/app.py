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
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from . import __version__
from .auth import TokenRecord, TokenStore, build_auth_router, check_gateway_auth_policy
from .config import HubConfig, load_config, palaia_home
from .dashboard_api import build_dashboard_router
from .events import (
    EventBus,
    bridge_vault_events,
    build_events_router,
    publish_event,
    start_background_tasks,
    stop_background_tasks,
)
from .gateway import GatewayASGI, VaultService
from .gateway.wiring import EngineVaultService
from .hooks import OUTBOX_RELATIVE_PATH, HookDispatcher, HookOutbox, HookStore, build_hooks_router
from .logging import setup_logging
from .static import mount_dashboard
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
    token_store: TokenStore | None = None,
    vault_services: Mapping[str, VaultService] | None = None,
    vault_registry: VaultRegistry | None = None,
    hook_store: HookStore | None = None,
    hook_outbox: HookOutbox | None = None,
) -> FastAPI:
    """Build the hub's ASGI app.

    Args:
        config: hub configuration; loaded via :func:`load_config` if omitted.
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
            at all, same as before this parameter existed.
        hook_store: outbound-webhook configuration (SPEC-201). Given, mounts
            the ``/api/hooks`` REST surface and starts the delivery worker
            that turns every published event into a signed webhook POST for
            every matching, enabled hook. Omitted (the default), the hub
            publishes events on its bus same as always, just with no
            webhook consumer attached.
        hook_outbox: the durable delivery queue backing ``hook_store``.
            Defaults to :class:`~palaia_hub.hooks.HookOutbox` at its
            standard path under the hub's data directory when ``hook_store``
            is given and this is omitted; pass one explicitly in tests that
            need an isolated path.
    """
    config = config or load_config()
    vault_services = vault_services or {}
    setup_logging(config)
    if gateway is not None:
        check_gateway_auth_policy(config.mode, gateway.profile_servers)

    start_time = time.monotonic()
    event_bus = EventBus()

    def health_snapshot() -> dict[str, Any]:
        return {"status": "ok", "components": {"config": "ok"}}

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

    # One lifespan runs every background concern: the events ticker
    # (SPEC-109), the webhook delivery worker (SPEC-201), and, when a
    # gateway is mounted, its session-manager lifespan (SPEC-105 —
    # skipping it hangs the mounted profiles on their first request).
    @asynccontextmanager
    async def lifespan(app_: FastAPI) -> AsyncIterator[None]:
        tasks = start_background_tasks(event_bus, health_snapshot=health_snapshot)
        if dispatcher is not None:
            tasks.append(asyncio.create_task(dispatcher.run_forever()))
        publish_event(
            event_bus,
            "hub.started",
            origin="hub",
            data={"version": __version__, "mode": config.mode},
        )
        try:
            if gateway is not None:
                async with gateway.lifespan(app_):
                    yield
            else:
                yield
        finally:
            await stop_background_tasks(tasks)
            if dispatcher is not None:
                await dispatcher.aclose()
            if unbridge_vault is not None:
                unbridge_vault()

    app = FastAPI(title="palaia-hub", version=__version__, lifespan=lifespan)
    app.state.config = config
    app.state.start_time = start_time
    app.state.event_bus = event_bus
    if gateway is not None:
        for path, mounted_app in gateway.mounts.items():
            app.mount(path, mounted_app)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        """Liveness + component readiness. No dependencies in this SPEC."""
        return health_snapshot()

    @app.get("/api/info")
    async def info() -> dict[str, Any]:
        """Version, operating mode, uptime."""
        return {
            "version": __version__,
            "mode": config.mode,
            "uptime_seconds": round(time.monotonic() - start_time, 3),
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

    if token_store is not None:
        app.include_router(build_auth_router(token_store))

    if vault_registry is not None:
        app.include_router(build_dashboard_router(vault_registry))

    if hook_store is not None:
        assert outbox is not None  # built above, together with hook_store's dispatcher
        app.include_router(build_hooks_router(hook_store, outbox))

    _maybe_add_test_slow_route(app)

    mount_dashboard(app)

    return app


def _default_outbox_path() -> Path:
    """Where the hooks outbox lives when ``create_app`` is not given one explicitly."""
    return palaia_home() / OUTBOX_RELATIVE_PATH


def _maybe_add_test_slow_route(app: FastAPI) -> None:
    raw_seconds = os.environ.get(_TEST_SLOW_ENDPOINT_ENV)
    if not raw_seconds:
        return
    seconds = float(raw_seconds)

    @app.get("/api/_test/slow")
    async def _slow() -> dict[str, Any]:
        await asyncio.sleep(seconds)
        return {"status": "done"}
