"""SPEC-504 first-run funnel audit fix: an empty ``scopes`` list on
``POST /api/auth/tokens`` — what every dashboard caller has ever sent, there
being no scope picker in the UI — now defaults to read+write on every vault
the named profile mounts, when a ``dynamic_gateway`` is wired in. See
``palaia_hub.auth.routes``'s module docstring for the bug this closes: an
empty list used to mean a token that authenticates but can call nothing,
which made the wizard's own "connect a client, write the first memory"
target shape fail on any hub actually enforcing scopes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.auth.store import TokenStore
from palaia_hub.config import HubConfig
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.dynamic import DynamicGateway
from palaia_hub.gateway.fake_vault import FakeVaultService

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _client_with_mounted_profile(tmp_path: Path) -> TestClient:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work", purpose="Work vault.")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    dynamic_gateway = DynamicGateway(config, {"work": FakeVaultService()})
    await dynamic_gateway.start()
    app = create_app(
        HubConfig(),
        token_store=TokenStore(home=tmp_path),
        dynamic_gateway=dynamic_gateway,
        home=tmp_path,
    )
    return TestClient(app)


async def test_empty_scopes_default_to_every_mounted_vault_read_and_write(
    tmp_path: Path,
) -> None:
    client = await _client_with_mounted_profile(tmp_path)

    response = client.post(
        "/api/auth/tokens", json={"name": "first-client", "profile": "default", "scopes": []}
    )

    assert response.status_code == 200
    scopes = response.json()["info"]["scopes"]
    assert sorted(scopes) == ["vault:work:read", "vault:work:write"]


async def test_scopes_omitted_entirely_defaults_the_same_way(tmp_path: Path) -> None:
    client = await _client_with_mounted_profile(tmp_path)

    response = client.post("/api/auth/tokens", json={"name": "first-client", "profile": "default"})

    assert response.status_code == 200
    scopes = response.json()["info"]["scopes"]
    assert sorted(scopes) == ["vault:work:read", "vault:work:write"]


async def test_explicit_scopes_are_never_overridden(tmp_path: Path) -> None:
    client = await _client_with_mounted_profile(tmp_path)

    response = client.post(
        "/api/auth/tokens",
        json={"name": "read-only-client", "profile": "default", "scopes": ["vault:work:read"]},
    )

    assert response.status_code == 200
    assert response.json()["info"]["scopes"] == ["vault:work:read"]


async def test_a_profile_that_does_not_exist_yet_still_gets_no_scopes(tmp_path: Path) -> None:
    """Pre-provisioning a token for a profile the wizard has not created
    yet must keep working exactly as before this fix — there is nothing to
    default *to*."""
    client = await _client_with_mounted_profile(tmp_path)

    response = client.post(
        "/api/auth/tokens", json={"name": "future-client", "profile": "not-mounted-yet"}
    )

    assert response.status_code == 200
    assert response.json()["info"]["scopes"] == []


def test_without_a_dynamic_gateway_empty_scopes_stay_empty(tmp_path: Path) -> None:
    """Every call site that omits ``dynamic_gateway`` (every test and
    embedding that predates this SPEC) must see the exact pre-SPEC-504
    behavior — an empty list stays empty."""
    app = create_app(HubConfig(), token_store=TokenStore(home=tmp_path), home=tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/auth/tokens", json={"name": "a", "profile": "default", "scopes": []}
    )

    assert response.status_code == 200
    assert response.json()["info"]["scopes"] == []


async def test_a_profile_mounting_two_vaults_gets_scopes_for_both(tmp_path: Path) -> None:
    config = GatewayConfig(
        vaults=[
            VaultMountConfig(key="work", name="work"),
            VaultMountConfig(key="personal", name="personal"),
        ],
        profiles=[ProfileConfig(path="default", vaults=["work", "personal"])],
    )
    dynamic_gateway = DynamicGateway(
        config, {"work": FakeVaultService(), "personal": FakeVaultService()}
    )
    await dynamic_gateway.start()
    app = create_app(
        HubConfig(),
        token_store=TokenStore(home=tmp_path),
        dynamic_gateway=dynamic_gateway,
        home=tmp_path,
    )
    client = TestClient(app)

    response = client.post("/api/auth/tokens", json={"name": "a", "profile": "default"})

    assert response.status_code == 200
    assert sorted(response.json()["info"]["scopes"]) == [
        "vault:personal:read",
        "vault:personal:write",
        "vault:work:read",
        "vault:work:write",
    ]


async def test_a_profile_carrying_built_in_families_gets_their_scope_pairs(
    tmp_path: Path,
) -> None:
    """Issue #313's rule, applied to every built-in family a profile can
    carry — Telegram included (issue #439), with the same ``read``/``send``
    vocabulary the messenger uses and the same ceiling the OAuth server
    grants (``palaia_hub.cli._profile_scopes``)."""
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[
            ProfileConfig(path="default", vaults=["work"], messenger=True, telegram=True),
            ProfileConfig(path="plain", vaults=["work"]),
        ],
    )
    dynamic_gateway = DynamicGateway(config, {"work": FakeVaultService()})
    await dynamic_gateway.start()
    app = create_app(
        HubConfig(),
        token_store=TokenStore(home=tmp_path),
        dynamic_gateway=dynamic_gateway,
        home=tmp_path,
    )
    client = TestClient(app)

    flagged = client.post("/api/auth/tokens", json={"name": "a", "profile": "default"})
    plain = client.post("/api/auth/tokens", json={"name": "b", "profile": "plain"})

    assert flagged.status_code == 200
    assert sorted(flagged.json()["info"]["scopes"]) == [
        "messenger:read",
        "messenger:send",
        "telegram:read",
        "telegram:send",
        "vault:work:read",
        "vault:work:write",
    ]
    assert not any(s.startswith("telegram:") for s in plain.json()["info"]["scopes"])
    await dynamic_gateway.aclose()


def test_the_dashboard_default_matches_the_oauth_ceiling() -> None:
    """The two places that decide a profile's scopes must agree, family for
    family — the token route's default is the OAuth ceiling, not a subset."""
    from palaia_hub.auth.routes import _default_scopes_for_profile
    from palaia_hub.cli import _profile_scopes

    profile = ProfileConfig(
        path="default",
        vaults=["work"],
        stash=True,
        directory=True,
        messenger=True,
        telegram=True,
    )

    class _Gateway:
        config = GatewayConfig(
            vaults=[VaultMountConfig(key="work", name="work")], profiles=[profile]
        )

    default = _default_scopes_for_profile(_Gateway(), "default")  # type: ignore[arg-type]
    assert sorted(default) == sorted(_profile_scopes([profile])["default"])
