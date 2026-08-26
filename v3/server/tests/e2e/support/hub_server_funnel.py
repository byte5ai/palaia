"""SPEC-506 Phase-5 gate e2e hub process: the exit criterion's mechanical
twin, "a non-developer completes install -> first shared memory unaided" —
fresh home, wizard-driven vault creation (SPEC-210's DynamicGateway, no
restart), then two real client connections with two different credential
shapes reaching that same vault the moment it mounts: a real OAuth 2.1
code flow for session A (the real ``claude`` CLI's own default,
zero-flag behavior), and a SPEC-108 ``plt_`` token for session B.

**Why this script pre-declares vault key "work" in the OAuth scopes it
hands ``AuthorizationServer.build``, even though no vault exists on disk
yet**: :class:`~palaia_hub.oauth.service.AuthorizationServer` freezes its
grantable-scopes-per-profile dict at construction
(``self._profile_scopes`` in ``__init__`` — never mutated afterward,
confirmed by grep: no ``add_``/``register_``/``update_`` method on that
class touches it). Production's own CLI path
(``palaia_hub.cli._maybe_oauth_server``) keeps this coupled to reality by
refusing to even start the OAuth server until at least one vault already
exists ("this hub serves no MCP profiles yet ... Fix: create a vault
first"). This script deliberately takes the case that guard exists to
protect against as its own scenario instead: an operator who chooses Cloud
mode from the very first boot, before running the wizard, already knowing
the vault key the wizard is about to create — exactly what a scripted,
deterministic funnel walk is. `resolve_full_gateway_profiles`/
`resolve_profiles` (the function ``cli.py`` and ``palaia_hub.serve`` both
call) is *not* used for this dict on purpose: that helper raises
``GatewaySettingsError`` for a profile naming a vault key that is not yet
registered, by design (that error is what protects a real operator from a
typo) — a good rule for its own callers, but a mismatch for what this
script needs to model. This is a real product gap, honestly: an operator
cannot do the equivalent through `config.yaml` today (`gateway.profiles`
goes through that same validated helper). Filed as
https://github.com/byte5ai/palaia/issues/273 rather than fixed here per
this SPEC's own "no behavior changes outside release plumbing" rule.

The *runtime* half of the story needs no such workaround and involves no
guesswork: ``palaia_hub.serve.build_production_app``'s ``_auth_provider_for``
closure (see that function's own SPEC-504 docstring) builds a real
verifier — OAuth JWT check plus ``plt_`` token check together, the same
recipe every other profile gets — for a dynamically-mounted profile the
moment ``DynamicGateway.add_vault`` first reaches it, using the very same
``oauth_server`` instance this script builds. So an OAuth access token
minted against the scopes below verifies correctly against the "default"
profile from the instant the wizard mounts "work" into it, no restart, no
second wiring step — this half is exactly what production already does.

Two credential shapes on the *same* "default" profile, mirroring
``hub_server_messenger.py``'s own note that nothing hub-side distinguishes
them: session A (OAuth, no ``scope`` requested — the resource's full
grantable set per RFC 6749 §3.3's default, `AuthorizationServer._resolve_
scopes`'s own documented choice) and session B (a ``plt_`` token minted
through the real ``POST /api/auth/tokens`` REST surface, SPEC-108).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import uvicorn

from palaia_hub.config import HubConfig, OAuthSettings
from palaia_hub.oauth import AuthorizationServer, now_seconds, set_owner_password
from palaia_hub.serve import build_production_app

logger = logging.getLogger("e2e.hub_server_funnel")

#: The vault key the wizard step of the driving test will create over
#: ``POST /api/vaults`` — chosen here, ahead of time, deterministically,
#: because the OAuth scopes below have to name it before it exists (see
#: this module's own docstring).
VAULT_KEY = "work"

OWNER_USERNAME = "owner"
OWNER_PASSWORD = "a-long-enough-passphrase"  # noqa: S105 - test fixture


async def _run(*, host: str, port: int, home: Path, username: str, password: str) -> None:
    issuer = f"http://{host}:{port}"
    config = HubConfig(
        mode="cloud",
        host=host,
        port=port,
        oauth=OAuthSettings(enabled=True, issuer=issuer),
    )

    # See this module's docstring: a hand-built scope dict, not
    # `resolve_full_gateway_profiles`/`_profile_scopes` — this hub has zero
    # registered vaults at this exact line, on purpose.
    profile_scopes = {
        "default": [
            f"vault:{VAULT_KEY}:read",
            f"vault:{VAULT_KEY}:write",
        ]
    }
    oauth_server = AuthorizationServer.build(config, profile_scopes, home=home)
    set_owner_password(oauth_server.store, username, password, now=now_seconds())

    production = await build_production_app(config, home=home, oauth_server=oauth_server)

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
        await production.dynamic_gateway.aclose()
        oauth_server.store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--home", required=True, help="empty PALAIA_HOME for this hub instance")
    parser.add_argument("--username", default=OWNER_USERNAME)
    parser.add_argument("--password", default=OWNER_PASSWORD)
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
        )
    )


if __name__ == "__main__":
    main()
