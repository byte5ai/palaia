"""SPEC-210 e2e hub process: starts with zero vaults, wizard creates one.

Unlike ``hub_server.py`` (which mounts exactly one vault, known before the
process starts, for the SPEC-113 scenarios), this script boots the hub the
same way ``palaia-hub serve`` does in production —
:func:`palaia_hub.serve.build_production_app` — against an empty
``PALAIA_HOME`` (no ``vaults.yaml`` yet). The test that drives this process
is the one that creates a vault, over ``POST /api/vaults``, and then makes
an MCP tool call against it — proving :class:`~palaia_hub.gateway.dynamic.
DynamicGateway` really does serve a vault created after the hub started,
with no restart in between.

Run directly with a Python interpreter — never through a wrapper — so
killing this process's PID kills the real server (see ``hub_server.py``'s
docstring for why that matters, even though this script's own tests never
need to kill it).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

import uvicorn

from palaia_hub.config import HubConfig
from palaia_hub.serve import build_production_app

logger = logging.getLogger("e2e.hub_server_dynamic")


async def _run(*, host: str, port: int, home: Path, auth_enabled: bool) -> None:
    os.environ["PALAIA_HOME"] = str(home)
    # auth_enabled=False (the default here): this script exercises
    # SPEC-210's dynamic mounting in isolation from SPEC-108's auth wiring
    # (covered by its own e2e/unit tests) — locked mode already allows this
    # (config.py: "optional; defaults to on anyway"). SPEC-504's first-run
    # funnel walk passes --auth-enabled instead, because its own scenario
    # is specifically "wizard endpoints -> vault -> token -> first memory
    # write", and a token means nothing to prove without a hub that
    # actually checks it.
    config = HubConfig(log_level="info", auth_enabled=auth_enabled)
    production = await build_production_app(config, home=home)

    server = uvicorn.Server(uvicorn.Config(production.app, host=host, port=port, log_level="info"))
    try:
        await server.serve()
    finally:
        for index in production.indexes.values():
            await index.close()
        if production.stash_store is not None:
            production.stash_store.close()
        if production.directory_store is not None:
            production.directory_store.close()
        if production.messenger_store is not None:
            production.messenger_store.close()
        await production.registry.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--home", required=True, help="empty PALAIA_HOME for this hub instance")
    parser.add_argument(
        "--auth-enabled",
        action="store_true",
        help="require a real plt_ token on every /mcp/* call (default: off)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    asyncio.run(
        _run(host=args.host, port=args.port, home=Path(args.home), auth_enabled=args.auth_enabled)
    )


if __name__ == "__main__":
    main()
