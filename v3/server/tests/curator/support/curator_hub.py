"""A standalone hub serving only the curator profile, for the smoke test.

Invoked as ``sys.executable curator_hub.py <vault_root> <port>`` by
``tests/curator/test_real_runner_smoke.py`` (env-gated, never in CI). No
token verifier is attached: the point of the smoke test is the *policy*
surface — that a real session can reach exactly the seven allowed tools and
nothing else — and adding auth would only add a second thing to debug when
the CLI cannot connect.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import uvicorn

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.curator.profile import curator_profile, curator_profile_middleware
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, VaultMountConfig
from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.vault import VaultEngine


async def _run(vault_root: Path, port: int) -> None:
    engine = VaultEngine(vault_root, name="work")
    await engine.open(purpose="Smoke-test vault for the curator.", create=True)
    mount = VaultMountConfig(key="work", name="work", purpose="Smoke-test vault.")
    gateway = build_gateway(
        GatewayConfig(vaults=[mount], profiles=[curator_profile([mount.key])]),
        {mount.key: EngineVaultService(engine)},
        profile_middleware=curator_profile_middleware([mount]),
    )
    app = create_app(HubConfig(auth_enabled=False), gateway=gateway)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None)
    )
    try:
        await server.serve()
    finally:
        await engine.close()


if __name__ == "__main__":
    asyncio.run(_run(Path(sys.argv[1]), int(sys.argv[2])))
