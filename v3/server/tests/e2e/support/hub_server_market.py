"""SPEC-308 e2e hub process: a real hub wired the exact way ``palaia-hub
serve`` wires one (:func:`palaia_hub.serve.build_production_app`, same as
``hub_server_oauth.py`` and ``cli.py`` itself), plus a curated-index entry
that is real for real: a signed document, fetched and Ed25519-verified by
the genuine :mod:`palaia_hub.market.curated` code path.

The point this script exists to prove is the Phase-3 gate's exit criterion
literally: *install a tool once, and it is available to every connected
AI* — so it mounts **two** gateway profiles (``default`` and ``mobile``)
over the same vault, with **both** SPEC-203 OAuth and SPEC-108 ``plt_``
tokens accepted on either one (``build_production_app``'s own
``build_profile_auth`` combination, unchanged). A marketplace install made
once, through the real ``/api/market/*`` REST surface, is mounted on both
profiles at once — the test file connects to ``default`` with a real OAuth
access token (the real ``claude`` CLI) and to ``mobile`` with a real
``plt_`` token (a scripted ``fastmcp.Client``), and both must see the same
newly-installed tool.

**Why the curated index is signed with a throwaway key generated in this
process**: :mod:`palaia_hub.market.curated`'s pinned
``DEFAULT_PUBLIC_KEY_B64`` is deliberately not configurable — a real key
only palaia's own real curated index holds the private half of. Proving
"a curated-index entry installs" for real does not require *that* specific
key; it requires the real verify-then-trust code path to run against a
document that really is signed and really does verify, which a
freshly-generated keypair (used once, by this process only, then
discarded) exercises identically. The transport carrying that document is
an in-process ``httpx.MockTransport`` — the same technique
``tests/market/test_api.py``'s own fixtures already use to stand in for a
real curated-index host — so no outbound network is needed for this half
of the SPEC-308 evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from palaia_hub.config import GatewayProfileSettings, GatewaySettings, HubConfig, OAuthSettings
from palaia_hub.gateway.config import DEFAULT_GATEWAY_PROFILE
from palaia_hub.gateway.settings_bridge import resolve_full_gateway_profiles
from palaia_hub.market.curated import CuratedIndexClient, canonical_bytes
from palaia_hub.oauth import AuthorizationServer, now_seconds, set_owner_password
from palaia_hub.serve import build_production_app
from palaia_hub.vault import VaultRegistry

logger = logging.getLogger("e2e.hub_server_market")

VAULT_KEY = "work"


def _profile_scopes(profiles: list[Any]) -> dict[str, list[str]]:
    """Same shape as ``palaia_hub.cli._profile_scopes`` — a read+write
    scope per vault each profile mounts."""
    return {
        profile.path: [
            scope for key in profile.vaults for scope in (f"vault:{key}:read", f"vault:{key}:write")
        ]
        for profile in profiles
    }


def _signed_curated_document(entry_id: str, fixture_url: str) -> tuple[dict[str, Any], str]:
    """A genuinely Ed25519-signed one-entry curated index document, plus the
    (throwaway) public key it verifies against — see the module docstring."""
    private_key = Ed25519PrivateKey.generate()
    public_key_b64 = base64.b64encode(private_key.public_key().public_bytes_raw()).decode()
    document: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": [
            {
                "id": entry_id,
                "name": "SPEC-308 Fixture Remote",
                "one_liner": "Fixture MCP server proving one install reaches every profile.",
                "kind": "remote",
                "source": {"type": "url", "value": fixture_url},
                "permissions": [],
                "maintainer": "spec-308-e2e",
                "verified": True,
            }
        ],
    }
    signature = private_key.sign(canonical_bytes(document))
    document["signature"] = base64.b64encode(signature).decode()
    return document, public_key_b64


async def _run(
    *,
    host: str,
    port: int,
    home: Path,
    vault_dir: Path,
    username: str,
    password: str,
    fixture_url: str,
    entry_id: str,
    profiles: list[str],
) -> None:
    registry = VaultRegistry(home)
    await registry.create(VAULT_KEY, vault_dir, purpose="SPEC-308 phase3-gate e2e vault.")

    issuer = f"http://{host}:{port}"
    gateway = GatewaySettings(
        profiles=[GatewayProfileSettings(path=p, vaults=[VAULT_KEY]) for p in profiles]
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

    # Swap in a curated index that really does carry a signed entry for the
    # real fixture upstream this test spawned — see the module docstring.
    document, public_key_b64 = _signed_curated_document(entry_id, fixture_url)

    def _serve_signed_index(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=document)

    assert production.install_service is not None
    old_curated_client = production.install_service.market_service.curated_client
    await old_curated_client.aclose()
    production.install_service.market_service.curated_client = CuratedIndexClient(
        index_url="https://spec308-curated-index.invalid/index.json",
        public_key_b64=public_key_b64,
        client=httpx.AsyncClient(transport=httpx.MockTransport(_serve_signed_index)),
        last_good_path=home / "market_curated_index.json",
    )

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
    parser.add_argument("--fixture-url", required=True, help="the fixture http upstream's URL")
    parser.add_argument("--entry-id", default="acme.spec308-fixture")
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
            fixture_url=args.fixture_url,
            entry_id=args.entry_id,
            profiles=[p.strip() for p in args.profiles.split(",") if p.strip()],
        )
    )


if __name__ == "__main__":
    main()
