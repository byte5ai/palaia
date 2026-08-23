"""ASGI app factory for the hub daemon.

One FastAPI app hosting the REST/dashboard API, the MCP gateway mount
point (SPEC-105, opt-in via the ``gateway`` parameter), and the
``/api/auth/tokens`` token-management surface (SPEC-108, opt-in via the
``token_store`` parameter).
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException

from . import __version__
from .auth import TokenStore, build_auth_router, check_gateway_auth_policy
from .config import HubConfig, load_config
from .dashboard_api import build_dashboard_router
from .events import EventBus, build_events_router, start_background_tasks, stop_background_tasks
from .gateway import DynamicGateway, GatewayASGI, VaultService
from .gateway.wiring import EngineVaultService
from .index import VaultIndex
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
    dynamic_gateway: DynamicGateway | None = None,
    token_store: TokenStore | None = None,
    vault_services: Mapping[str, VaultService] | None = None,
    vault_registry: VaultRegistry | None = None,
    indexes: dict[str, VaultIndex] | None = None,
    event_bus: EventBus | None = None,
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

    # One lifespan runs BOTH concerns: the events background tasks (SPEC-109)
    # and, when a gateway is mounted, its session-manager lifespan (SPEC-105 —
    # skipping it hangs the mounted profiles on their first request).
    @asynccontextmanager
    async def lifespan(app_: FastAPI) -> AsyncIterator[None]:
        tasks = start_background_tasks(event_bus, health_snapshot=health_snapshot)
        if dynamic_gateway is not None:
            await dynamic_gateway.start()
        try:
            if gateway is not None:
                async with gateway.lifespan(app_):
                    yield
            else:
                yield
        finally:
            await stop_background_tasks(tasks)
            if dynamic_gateway is not None:
                await dynamic_gateway.aclose()
            if indexes is not None:
                for index in indexes.values():
                    await index.close()

    app = FastAPI(title="palaia-hub", version=__version__, lifespan=lifespan)
    app.state.config = config
    app.state.start_time = start_time
    app.state.event_bus = event_bus
    if gateway is not None:
        for path, mounted_app in gateway.mounts.items():
            app.mount(path, mounted_app)
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
        app.include_router(
            build_dashboard_router(
                vault_registry,
                indexes=indexes,
                dynamic_gateway=dynamic_gateway,
            )
        )

    _maybe_add_test_slow_route(app)

    mount_dashboard(app)

    return app


def _maybe_add_test_slow_route(app: FastAPI) -> None:
    raw_seconds = os.environ.get(_TEST_SLOW_ENDPOINT_ENV)
    if not raw_seconds:
        return
    seconds = float(raw_seconds)

    @app.get("/api/_test/slow")
    async def _slow() -> dict[str, Any]:
        await asyncio.sleep(seconds)
        return {"status": "done"}
