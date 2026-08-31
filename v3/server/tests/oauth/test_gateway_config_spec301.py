"""SPEC-301 acceptance criterion: "OAuth resources follow gateway profiles:
token minted for a new profile's audience verifies on it e2e; `oauth.profiles`
in an old config still works but warns."

Unlike ``test_flow_e2e.py`` (which builds its harness by hand, wiring the
gateway and the OAuth server together itself), this goes through the real
production path — ``palaia_hub.cli._maybe_oauth_server`` +
``palaia_hub.serve.build_production_app`` — with a ``config.yaml`` that sets
**no** ``oauth.profiles`` at all: the whole point is that the AS learns
which resources exist from the gateway's own ``gateway:`` section.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from auth._asgi_mcp_client import mcp_client_transport
from fastmcp import Client

from palaia_hub.cli import _maybe_oauth_server
from palaia_hub.config import load_config
from palaia_hub.oauth import provision_machine_client
from palaia_hub.serve import build_production_app
from palaia_hub.vault import VaultRegistry

BASE_URL = "https://testserver"
SCOPES = ("vault:alpha:read", "vault:alpha:write")


async def _registered_vault(home: Path, key: str) -> None:
    registry = VaultRegistry(home)
    await registry.create(key, home / "vaults" / key, purpose=f"{key} vault.")


def _write_config(home: Path) -> None:
    (home / "config.yaml").write_text(
        "mode: locked\n"
        "oauth:\n"
        "  enabled: true\n"
        "  issuer: https://testserver\n"
        "gateway:\n"
        "  profiles:\n"
        "    - path: alpha\n"
        "      vaults: [alpha]\n"
        "    - path: beta\n"
        "      vaults: [beta]\n",
        encoding="utf-8",
    )


@pytest.mark.anyio
async def test_oauth_resources_follow_gateway_profiles_with_no_oauth_profiles_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `_maybe_oauth_server` reads the registry via `VaultRegistry()` (no
    # explicit home, same as `palaia_hub.cli.serve()` itself) — point it at
    # this test's isolated home the same way the real CLI is pointed at a
    # real one.
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))
    await _registered_vault(tmp_path, "alpha")
    await _registered_vault(tmp_path, "beta")
    _write_config(tmp_path)
    config = load_config(home=tmp_path, create_if_missing=False)
    assert config.oauth.profiles == []  # the deprecated field is not set at all

    oauth_server = _maybe_oauth_server(config)
    assert oauth_server is not None
    # The AS learned about both profiles from `gateway:`, with no
    # `oauth.profiles` in sight — deliverable #3's "one source of truth".
    assert set(oauth_server.resources.profiles) == {"alpha", "beta"}

    production = await build_production_app(config, home=tmp_path, oauth_server=oauth_server)
    app = production.app
    try:
        async with app.router.lifespan_context(app):
            provisioned = provision_machine_client(
                oauth_server.store,
                client_name="ci job",
                audience=oauth_server.resources.audience("alpha"),
                scopes=list(SCOPES),
                now=oauth_server.now(),
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE_URL
            ) as http:
                token_response = await http.post(
                    "/oauth/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": provisioned.client.client_id,
                        "client_secret": provisioned.client_secret,
                    },
                )
                assert token_response.status_code == 200, token_response.text
                access_token = str(token_response.json()["access_token"])

                # Verifies on the profile it was minted for.
                transport = mcp_client_transport(
                    app, f"{BASE_URL}/mcp/alpha/", token=access_token
                )
                async with Client(transport) as client:
                    result = await client.call_tool_mcp(
                        "alpha_memory_search", {"query": "anything"}
                    )
                assert result.isError is not True

                # And is rejected by the other profile (aud isolation) —
                # both profiles came from the same `gateway:` section, with
                # no OAuth-specific config naming them individually.
                rejected = await http.get(
                    "/mcp/beta/", headers={"Authorization": f"Bearer {access_token}"}
                )
                assert rejected.status_code == 401
    finally:
        await production.dynamic_gateway.aclose()
        if production.stash_store is not None:
            production.stash_store.close()
        for index in production.indexes.values():
            await index.close()


@pytest.mark.anyio
async def test_old_oauth_profiles_config_still_works_with_no_gateway_section(
    tmp_path: Path,
) -> None:
    """An old ``config.yaml`` (``oauth.profiles`` set, no vault registered
    yet, no ``gateway:`` section) still starts the AS — "still works" — but
    warns that the field is deprecated."""
    (tmp_path / "config.yaml").write_text(
        "mode: locked\noauth:\n  enabled: true\n  issuer: https://testserver\n"
        "  profiles: [legacy]\n",
        encoding="utf-8",
    )

    with pytest.warns(DeprecationWarning, match="oauth.profiles"):
        config = load_config(home=tmp_path, create_if_missing=False)

    oauth_server = _maybe_oauth_server(config)
    assert oauth_server is not None
    assert set(oauth_server.resources.profiles) == {"legacy"}


def _write_precreated_config(home: Path) -> None:
    """#273: `default` is declared up front, pre-naming a vault ("work")
    that does not exist on this hub yet — the config an operator writes to
    get Cloud mode + OAuth working *before* ever running the wizard."""
    (home / "config.yaml").write_text(
        "mode: cloud\n"
        "host: 127.0.0.1\n"
        "oauth:\n"
        "  enabled: true\n"
        "  issuer: https://testserver\n"
        # Sidesteps the dashboard's own admin sign-in gate (SPEC-401, on by
        # default in cloud mode) — this test drives `POST /api/vaults`
        # directly, the way the wizard's already-signed-in browser session
        # does; asserting *that* gate is a different SPEC's test.
        "dashboard:\n"
        "  require_sign_in: false\n"
        "gateway:\n"
        "  profiles:\n"
        "    - path: default\n"
        "      vaults: [work]\n",
        encoding="utf-8",
    )


@pytest.mark.anyio
async def test_precreated_vault_scopes_boot_before_the_wizard_creates_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#273: a `gateway.profiles` entry naming a vault the wizard has not
    created yet must (1) not crash the hub at boot, (2) already reserve
    that vault's OAuth scopes for its profile, and (3) mount the real vault
    with no restart, and no scope mismatch, the moment it is created —
    exactly the "Cloud mode + OAuth from the very first boot" scenario the
    issue describes."""
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))
    _write_precreated_config(tmp_path)
    config = load_config(home=tmp_path, create_if_missing=False)
    assert config.gateway is not None
    assert list(VaultRegistry().names()) == []  # zero vaults registered — the whole point

    # 1. Boots at all: the old behavior raised GatewaySettingsError here.
    oauth_server = _maybe_oauth_server(config)
    assert oauth_server is not None

    # 2. The pending vault's scopes are already reserved for "default" —
    # computed from the *declared* shape, not the (currently empty) real one.
    assert oauth_server.resources.profiles == ("default",)
    audience = oauth_server.resources.audience("default")
    assert oauth_server.scopes_for(audience) == ("vault:work:read", "vault:work:write")

    production = await build_production_app(config, home=tmp_path, oauth_server=oauth_server)
    try:
        async with production.app.router.lifespan_context(production.app):
            # The real gateway mounted "default" with zero vaults (nothing
            # to mount yet) — not zero *profiles*, and cloud mode's own
            # auth-policy check (every mounted profile needs a verifier)
            # still passed, or build_production_app would have raised.
            assert "default" in production.dynamic_gateway.profile_servers
            async with Client(production.dynamic_gateway.profile_servers["default"]) as client:
                names = {t.name for t in await client.list_tools()}
            assert not any(name.startswith("work_") for name in names)

            provisioned = provision_machine_client(
                oauth_server.store,
                client_name="pre-provisioned job",
                audience=audience,
                scopes=["vault:work:read", "vault:work:write"],
                now=oauth_server.now(),
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=production.app), base_url=BASE_URL
            ) as http:
                # 3. The wizard's own REST endpoint creates the vault —
                # DynamicGateway.add_vault reconciles it onto "default" live.
                create_response = await http.post(
                    "/api/vaults", json={"key": "work", "purpose": "Work notes."}
                )
                assert create_response.status_code == 200, create_response.text

                token_response = await http.post(
                    "/oauth/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": provisioned.client.client_id,
                        "client_secret": provisioned.client_secret,
                    },
                )
                assert token_response.status_code == 200, token_response.text
                access_token = str(token_response.json()["access_token"])

            # A token minted against the pre-declared scopes — no restart,
            # no re-wiring — now works against the just-created real vault.
            transport = mcp_client_transport(
                production.app, f"{BASE_URL}/mcp/default/", token=access_token
            )
            async with Client(transport) as client:
                result = await client.call_tool_mcp(
                    "work_memory_search", {"query": "anything"}
                )
            assert result.isError is not True
    finally:
        await production.dynamic_gateway.aclose()
        if production.stash_store is not None:
            production.stash_store.close()
        for index in production.indexes.values():
            await index.close()


def test_profile_scopes_include_mounted_builtin_families() -> None:
    """An OAuth client can be granted the stash/directory/messenger scopes
    of the profiles that actually mount those families (SPEC-403 follow-up:
    before this, only plt_ tokens could carry them)."""
    from palaia_hub.cli import _profile_scopes
    from palaia_hub.gateway.config import ProfileConfig

    scopes = _profile_scopes(
        [
            ProfileConfig(
                path="team",
                vaults=["work"],
                stash=True,
                directory=True,
                messenger=True,
            ),
            ProfileConfig(path="plain", vaults=["work"]),
        ]
    )

    assert scopes["team"] == [
        "vault:work:read",
        "vault:work:write",
        "stash:read",
        "stash:write",
        "directory:read",
        "directory:write",
        "messenger:read",
        "messenger:send",
    ]
    assert scopes["plain"] == ["vault:work:read", "vault:work:write"]
