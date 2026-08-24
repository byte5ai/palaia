"""SPEC-209 e2e hub process: a real Cloud-mode hub with OAuth 2.1 turned on.

Same shape as ``hub_server.py`` (real ``VaultEngine``/``VaultIndex``, real
``uvicorn`` over a real socket) but wires the SPEC-203 authorization server
on top, exactly the way ``palaia_hub.cli.serve``/``_maybe_oauth_server`` do
in production, so a real client driven from outside this process (the
``claude`` CLI) exercises the actual 401 -> discovery -> DCR -> PKCE code
flow -> token -> authenticated MCP call path, not a stand-in of it.

``mode: cloud`` with ``host: 127.0.0.1``: this satisfies
``HubConfig``'s own cloud-mode policy check (private bind + an auth method)
for real — the one thing this script cannot reproduce in this sandbox is an
actual public tunnel in front of it, which is a network-reachability fact
about Tailscale/cloudflared, not about the hub's OAuth code path. A local
CLI client (Claude Code, Codex, ...) never goes through a vendor cloud in
the first place, so it reaches this loopback listener exactly as it would
reach a tunnel's local termination point.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import uvicorn

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig, OAuthSettings
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.index import EmbeddingConfig, VaultIndex
from palaia_hub.oauth import (
    AuthorizationServer,
    OAuthStore,
    SigningKey,
    build_profile_auth,
    now_seconds,
    set_owner_password,
)
from palaia_hub.vault import EventBus, VaultEngine, VaultWatcher

logger = logging.getLogger("e2e.hub_server_oauth")

VAULT_KEY = "work"
PROFILE = "default"


async def _run(
    *, host: str, port: int, home: Path, vault_dir: Path, username: str, password: str
) -> None:
    engine = VaultEngine(vault_dir, VAULT_KEY, bus=EventBus())
    await engine.open(purpose="SPEC-209 client-matrix e2e vault", create=True)
    index = VaultIndex(engine, embedding=EmbeddingConfig(enabled=False))
    await index.open()
    watcher = VaultWatcher(engine)
    await watcher.start()

    issuer = f"http://{host}:{port}"
    oauth_settings = OAuthSettings(enabled=True, issuer=issuer, profiles=[PROFILE])
    config = HubConfig(mode="cloud", host=host, port=port, oauth=oauth_settings)

    store = OAuthStore(home)
    store.open()
    key = SigningKey.load_or_create(home)
    profile_scopes = {PROFILE: [f"vault:{VAULT_KEY}:read", f"vault:{VAULT_KEY}:write"]}
    server = AuthorizationServer(
        settings=oauth_settings, profile_scopes=profile_scopes, store=store, key=key
    )
    set_owner_password(store, username, password, now=now_seconds())

    gateway_config = GatewayConfig(
        vaults=[
            VaultMountConfig(key=VAULT_KEY, name=VAULT_KEY, purpose="SPEC-209 e2e vault.")
        ],
        profiles=[ProfileConfig(path=PROFILE, vaults=[VAULT_KEY])],
    )
    providers = build_profile_auth(
        [PROFILE], key=key, resources=server.resources, token_store=None
    )
    gateway = build_gateway(
        gateway_config,
        {VAULT_KEY: EngineVaultService(engine, index)},
        token_verifiers=providers,  # type: ignore[arg-type]
    )
    app = create_app(config, gateway=gateway, oauth_server=server)

    uv_server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
    try:
        await uv_server.serve()
    finally:
        await watcher.stop()
        await index.close()
        await engine.close()
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--home", required=True, help="empty PALAIA_HOME for this hub instance")
    parser.add_argument("--vault-dir", required=True)
    parser.add_argument("--username", default="owner")
    parser.add_argument("--password", default="a-long-enough-passphrase")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    asyncio.run(
        _run(
            host=args.host,
            port=args.port,
            home=Path(args.home),
            vault_dir=Path(args.vault_dir),
            username=args.username,
            password=args.password,
        )
    )


if __name__ == "__main__":
    main()
