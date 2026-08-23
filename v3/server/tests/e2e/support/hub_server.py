"""Standalone hub process for the SPEC-113 e2e scenarios.

A plain script invoked as a subprocess (``sys.executable hub_server.py
...``), run in the same interpreter/venv as pytest — the same pattern
SPEC-105's ``tests/gateway/_e2e_server.py`` uses, and for the same reason:
killing this process's PID must kill the real server, not a wrapper (the
SPEC-003/SPEC-102 kill-test finding).

Mounts exactly one vault, backed by a real :class:`~palaia_hub.vault.VaultEngine`
through :class:`~palaia_hub.gateway.wiring.EngineVaultService` (SPEC-113's
adapter — no ``FakeVaultService`` anywhere in this module), under one or
more profile paths. A :class:`~palaia_hub.vault.VaultWatcher` is always
started alongside the engine so external edits (S2) become visible to the
gateway's tools without a manual refresh.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import uvicorn

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.vault import VaultEngine, VaultWatcher

logger = logging.getLogger("e2e.hub_server")


async def _run(
    *, host: str, port: int, vault_dir: Path, vault_key: str, vault_name: str, profiles: list[str]
) -> None:
    engine = VaultEngine(vault_dir, vault_name)
    await engine.open(purpose=f"SPEC-113 e2e vault {vault_name!r}", create=True)
    watcher = VaultWatcher(engine)
    await watcher.start()

    gateway_config = GatewayConfig(
        vaults=[
            VaultMountConfig(
                key=vault_key,
                name=vault_name,
                purpose=f"SPEC-113 e2e vault {vault_name!r}.",
            )
        ],
        profiles=[ProfileConfig(path=p, vaults=[vault_key]) for p in profiles],
    )
    gateway = build_gateway(gateway_config, {vault_key: EngineVaultService(engine)})
    app = create_app(HubConfig(log_level="info"), gateway=gateway)

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
    try:
        await server.serve()
    finally:
        await watcher.stop()
        await engine.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--vault-dir", required=True)
    parser.add_argument("--vault-key", default="work")
    parser.add_argument("--vault-name", default="work")
    parser.add_argument(
        "--profile",
        action="append",
        dest="profiles",
        default=None,
        help="profile path to mount the vault under; may repeat. Default: 'default'.",
    )
    args = parser.parse_args()
    profiles = args.profiles or ["default"]

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    asyncio.run(
        _run(
            host=args.host,
            port=args.port,
            vault_dir=Path(args.vault_dir),
            vault_key=args.vault_key,
            vault_name=args.vault_name,
            profiles=profiles,
        )
    )


if __name__ == "__main__":
    main()
