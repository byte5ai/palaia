"""SPEC-407 e2e hub process: a real hub wired the exact way ``palaia-hub
serve`` wires one (:func:`palaia_hub.serve.build_production_app`, same
convention as ``hub_server_oauth.py``/``hub_server_market.py`` and
``cli.py`` itself), mounting the session directory and messenger tool
families (SPEC-402/403) *inside* two gateway profiles alongside one shared
vault — the shape the Phase-4 gate's exit criterion needs: two agents, on
two different profiles, with two different credential shapes, sharing one
vault through a handoff.

Two profiles, both carrying the same vault, both with ``directory: true``
and ``messenger: true`` (:class:`palaia_hub.config.GatewayProfileSettings`)
so a client on either one gets the vault's memory tools plus
``directory_*``/``messenger_*`` behind its own MCP mount:

- ``default`` — OAuth only, no requested ``scope`` (so the authorization
  code grant issues this profile's *full* grantable set — vault
  read/write, ``directory:*``, ``messenger:*`` — the scope-ceiling fix this
  SPEC's own task names: before it, an OAuth client could never be granted
  the directory/messenger scopes at all, only a ``plt_`` token could).
  Session A (the real ``claude`` CLI) connects here.
- ``mobile`` — accepts both OAuth and SPEC-108 ``plt_`` tokens (same
  ``build_profile_auth`` combination every other profile gets — nothing
  hub-side distinguishes the two credential shapes). Session B (a scripted
  ``fastmcp.Client`` carrying a ``plt_`` token — this sandbox has no
  ``codex`` binary, so this is the second-provider-shaped stand-in;
  SPEC-209 pinned the same wire-level equivalence for exactly this reason)
  connects here.

The directory and the messenger are each exactly one hub-wide store
(:mod:`palaia_hub.serve`'s own module docstring), shared across every
profile that mounts them — which is *why* this design proves a
cross-provider handoff at all: A registers and sends on ``default``, B
registers and checks on ``mobile``, and both land in the one directory/
messenger the hub actually runs, never two independent toy stores.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import uvicorn

from palaia_hub.config import GatewayProfileSettings, GatewaySettings, HubConfig, OAuthSettings
from palaia_hub.gateway.config import DEFAULT_GATEWAY_PROFILE
from palaia_hub.gateway.config import ProfileConfig as _ProfileConfig
from palaia_hub.gateway.settings_bridge import resolve_full_gateway_profiles
from palaia_hub.oauth import AuthorizationServer, now_seconds, set_owner_password
from palaia_hub.serve import build_production_app
from palaia_hub.vault import VaultRegistry

logger = logging.getLogger("e2e.hub_server_messenger")

VAULT_KEY = "work"


def _profile_scopes(profiles: list[_ProfileConfig]) -> dict[str, list[str]]:
    """Verbatim copy of ``palaia_hub.cli._profile_scopes`` (vault +
    directory + messenger scopes per profile) — the real function is
    private to the CLI module, and this file's house style (every other
    ``tests/e2e/support/hub_server_*.py`` script) is a standalone script,
    not a shared import from ``cli.py``. A contract test elsewhere
    (SPEC-403's own tests) pins ``cli.py``'s real version; this copy would
    only drift from it silently if that vocabulary itself changed, at
    which point every OAuth-scoped e2e test in this directory would need
    the same edit.
    """

    def scopes_for(profile: _ProfileConfig) -> list[str]:
        scopes = [
            scope
            for key in profile.vaults
            for scope in (f"vault:{key}:read", f"vault:{key}:write")
        ]
        if profile.stash:
            scopes += ["stash:read", "stash:write"]
        if profile.directory:
            scopes += ["directory:read", "directory:write"]
        if profile.messenger:
            scopes += ["messenger:read", "messenger:send"]
        return scopes

    return {profile.path: scopes_for(profile) for profile in profiles}


async def _run(
    *,
    host: str,
    port: int,
    home: Path,
    vault_dir: Path,
    username: str,
    password: str,
    profiles: list[str],
) -> None:
    registry = VaultRegistry(home)
    await registry.create(
        VAULT_KEY,
        vault_dir,
        purpose="SPEC-407 phase4-gate e2e vault: shared work knowledge.",
    )

    issuer = f"http://{host}:{port}"
    gateway = GatewaySettings(
        profiles=[
            GatewayProfileSettings(path=p, vaults=[VAULT_KEY], directory=True, messenger=True)
            for p in profiles
        ]
    )
    config = HubConfig(
        mode="cloud",
        host=host,
        port=port,
        oauth=OAuthSettings(enabled=True, issuer=issuer),
        gateway=gateway,
    )

    resolved_profiles = resolve_full_gateway_profiles(
        config, [VAULT_KEY], default_profile=DEFAULT_GATEWAY_PROFILE
    )
    oauth_server = AuthorizationServer.build(config, _profile_scopes(resolved_profiles), home=home)
    set_owner_password(oauth_server.store, username, password, now=now_seconds())

    production = await build_production_app(config, home=home, oauth_server=oauth_server)

    uv_server = uvicorn.Server(
        uvicorn.Config(production.app, host=host, port=port, log_level="info")
    )
    try:
        await uv_server.serve()
    finally:
        for index in production.indexes.values():
            await index.close()
        if production.stash_store is not None:
            production.stash_store.close()
        if production.directory_store is not None:
            production.directory_store.close()
        if production.messenger_store is not None:
            production.messenger_store.close()
        await production.dynamic_gateway.aclose()
        oauth_server.store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--home", required=True, help="empty PALAIA_HOME for this hub instance")
    parser.add_argument("--vault-dir", required=True)
    parser.add_argument("--username", default="owner")
    parser.add_argument("--password", default="a-long-enough-passphrase")
    parser.add_argument(
        "--profiles", default="default,mobile", help="comma-separated gateway profile paths"
    )
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
            profiles=[p.strip() for p in args.profiles.split(",") if p.strip()],
        )
    )


if __name__ == "__main__":
    main()
