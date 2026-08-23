"""ASGI app factory for the hub daemon.

One FastAPI app hosting the REST/dashboard API (this SPEC: ``/api/health``
and ``/api/info`` only) and, from SPEC-105 onward, the MCP gateway mount
point. No MCP serving, auth, or persistence here — see SPEC-101's
non-goals.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from fastapi import FastAPI

from . import __version__
from .config import HubConfig, load_config
from .gateway import GatewayASGI
from .logging import setup_logging

# Name of the env var that, when set to a positive number of seconds, adds a
# `/api/_test/slow` route that sleeps that long before responding. This
# exists solely so tests can exercise graceful-shutdown behavior (a slow
# request in flight when SIGTERM arrives) against a real server process; it
# never activates unless a test explicitly sets the env var.
_TEST_SLOW_ENDPOINT_ENV = "PALAIA_TEST_SLOW_ENDPOINT_SECONDS"


def create_app(config: HubConfig | None = None, *, gateway: GatewayASGI | None = None) -> FastAPI:
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
    """
    config = config or load_config()
    setup_logging(config)

    start_time = time.monotonic()

    app = FastAPI(
        title="palaia-hub",
        version=__version__,
        lifespan=gateway.lifespan if gateway is not None else None,
    )
    app.state.config = config
    app.state.start_time = start_time
    if gateway is not None:
        for path, mounted_app in gateway.mounts.items():
            app.mount(path, mounted_app)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        """Liveness + component readiness. No dependencies in this SPEC."""
        return {
            "status": "ok",
            "components": {"config": "ok"},
        }

    @app.get("/api/info")
    async def info() -> dict[str, Any]:
        """Version, operating mode, uptime."""
        return {
            "version": __version__,
            "mode": config.mode,
            "uptime_seconds": round(time.monotonic() - start_time, 3),
        }

    _maybe_add_test_slow_route(app)

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
