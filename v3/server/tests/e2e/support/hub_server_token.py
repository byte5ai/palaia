"""Standalone hub process for the SPEC-306 palaia-proxy e2e test.

Same pattern as ``hub_server.py`` (a plain subprocess, so killing this
process's PID kills the real server — needed for the "proxy survives a
hub restart" acceptance criterion), plus a real
:class:`~palaia_hub.auth.store.TokenStore`-backed :class:`TokenVerifier`
on the one mounted profile: this is what lets the test mint a real SPEC-108
token and hand it to the real ``palaia-proxy.mjs`` via ``PALAIA_TOKEN``,
exercising the exact same bearer-token enforcement path a Claude Desktop
install (via ``/api/connect/mcpb``'s token variant) would hit.

``--token-store-dir`` is a directory the test creates its own
:class:`TokenStore` against beforehand (to mint the token) and this
process re-opens against the same directory — the two processes share one
``tokens.yaml`` on disk, never the same in-memory store.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import uvicorn

from palaia_hub.app import create_app
from palaia_hub.auth import TokenStore, build_profile_verifiers
from palaia_hub.config import HubConfig
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.index import EmbeddingConfig, VaultIndex
from palaia_hub.vault import EventBus, VaultEngine, VaultWatcher

logger = logging.getLogger("e2e.hub_server_token")


async def _run(
    *,
    host: str,
    port: int,
    vault_dir: Path,
    vault_key: str,
    vault_name: str,
    profile: str,
    token_store_dir: Path,
) -> None:
    engine = VaultEngine(vault_dir, vault_name, bus=EventBus())
    await engine.open(purpose=f"SPEC-306 e2e vault {vault_name!r}", create=True)
    index = VaultIndex(engine, embedding=EmbeddingConfig(enabled=False))
    await index.open()
    watcher = VaultWatcher(engine)
    await watcher.start()

    token_store = TokenStore(home=token_store_dir)
    gateway_config = GatewayConfig(
        vaults=[VaultMountConfig(key=vault_key, name=vault_name, purpose="SPEC-306 e2e vault.")],
        profiles=[ProfileConfig(path=profile, vaults=[vault_key])],
    )
    verifiers = build_profile_verifiers([profile], token_store)
    gateway = build_gateway(
        gateway_config, {vault_key: EngineVaultService(engine, index)}, token_verifiers=verifiers
    )
    app = create_app(
        HubConfig(mode="cloud", host=host, port=port, log_level="info"),
        gateway=gateway,
        token_store=token_store,
    )

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
    try:
        await server.serve()
    finally:
        await watcher.stop()
        await index.close()
        await engine.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--vault-dir", required=True)
    parser.add_argument("--vault-key", default="work")
    parser.add_argument("--vault-name", default="work")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--token-store-dir", required=True)
    args = parser.parse_args()

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
            profile=args.profile,
            token_store_dir=Path(args.token_store_dir),
        )
    )


if __name__ == "__main__":
    main()
