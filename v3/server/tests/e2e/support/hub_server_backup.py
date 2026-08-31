"""SPEC-604 e2e hub process: a real Cloud-mode hub with a vault under its
own home directory, one upstream secret, and both auth doors a real client
needs to touch — everything the backup/restore round trip has to prove.

Same "real subprocess, real socket" shape as ``hub_server.py``/
``hub_server_oauth.py``, with the pieces this scenario specifically needs:

* **The vault lives under the hub's own home**
  (``<home>/vaults/<key>``, the wizard's own default layout —
  ``dashboard_api.py::create_vault``). ``GET /api/backup`` archives the
  home directory, so the vault has to be inside it for a whole-hub restore
  to mean anything here.
* **MCP auth is a plain SPEC-108 bearer token**
  (:class:`~palaia_hub.auth.store.TokenStore`, same as
  ``hub_server_token.py``) rather than OAuth — this scenario is about the
  archive, not about re-running the PKCE flow, and a bearer token is a
  single line for :class:`simulator.SimulatedClient` to use either side of
  the restore.
* **The dashboard's admin session still needs a real sign-in**
  (:class:`~palaia_hub.oauth.AuthorizationServer`) — ``GET /api/backup``
  itself is behind that gate, and this scenario proves the *download* is
  gated, not just that the archive is correct.
* **A secret is pre-populated** (``--secret-name``/``--secret-value``) so
  the test has a known plaintext to compare against after the restore —
  the only honest way to prove a secret "round-trips" is to know what it
  was supposed to come back as.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import uvicorn

from palaia_hub.app import create_app
from palaia_hub.auth import TokenStore, build_profile_verifiers
from palaia_hub.config import HubConfig, OAuthSettings
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.index import EmbeddingConfig, VaultIndex
from palaia_hub.oauth import (
    AuthorizationServer,
    OAuthStore,
    SigningKey,
    now_seconds,
    set_owner_password,
)
from palaia_hub.upstream.secrets import SecretStore
from palaia_hub.vault import EventBus, VaultEngine, VaultWatcher

logger = logging.getLogger("e2e.hub_server_backup")

VAULT_KEY = "work"
PROFILE = "default"


async def _run(
    *,
    host: str,
    port: int,
    home: Path,
    username: str,
    password: str,
    secret_name: str | None,
    secret_value: str | None,
) -> None:
    vault_dir = home / "vaults" / VAULT_KEY
    engine = VaultEngine(vault_dir, VAULT_KEY, bus=EventBus())
    await engine.open(purpose="SPEC-604 backup/restore e2e vault", create=True)
    index = VaultIndex(engine, embedding=EmbeddingConfig(enabled=False))
    await index.open()
    watcher = VaultWatcher(engine)
    await watcher.start()

    issuer = f"http://{host}:{port}"
    config = HubConfig(
        mode="cloud", host=host, port=port, oauth=OAuthSettings(enabled=True, issuer=issuer)
    )

    oauth_store = OAuthStore(home)
    oauth_store.open()
    signing_key = SigningKey.load_or_create(home)
    oauth_server = AuthorizationServer(
        settings=config.oauth,
        profile_scopes={PROFILE: [f"vault:{VAULT_KEY}:read", f"vault:{VAULT_KEY}:write"]},
        store=oauth_store,
        key=signing_key,
    )
    set_owner_password(oauth_store, username, password, now=now_seconds())

    secret_store = SecretStore(home)
    if secret_name and secret_value:
        secret_store.put(secret_name, secret_value)

    token_store = TokenStore(home=home)
    gateway_config = GatewayConfig(
        vaults=[VaultMountConfig(key=VAULT_KEY, name=VAULT_KEY, purpose="SPEC-604 e2e vault.")],
        profiles=[ProfileConfig(path=PROFILE, vaults=[VAULT_KEY])],
    )
    verifiers = build_profile_verifiers([PROFILE], token_store)
    gateway = build_gateway(
        gateway_config, {VAULT_KEY: EngineVaultService(engine, index)}, token_verifiers=verifiers
    )
    app = create_app(
        config,
        gateway=gateway,
        oauth_server=oauth_server,
        token_store=token_store,
        secret_store=secret_store,
        home=home,
    )

    uv_server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
    try:
        await uv_server.serve()
    finally:
        await watcher.stop()
        await index.close()
        await engine.close()
        secret_store.close()
        oauth_store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--home", required=True, help="the hub home this process persists under")
    parser.add_argument("--username", default="owner")
    parser.add_argument("--password", default="a-long-enough-passphrase")
    parser.add_argument("--secret-name", default=None)
    parser.add_argument("--secret-value", default=None)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    asyncio.run(
        _run(
            host=args.host,
            port=args.port,
            home=Path(args.home),
            username=args.username,
            password=args.password,
            secret_name=args.secret_name,
            secret_value=args.secret_value,
        )
    )


if __name__ == "__main__":
    main()
