"""``GET /api/connect/mcpb`` — variant selection, and the acceptance
criteria the download endpoint itself owns: profile baked in, token
minted for the token variant, no secret at all for the OAuth variant."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.auth.store import TokenStore
from palaia_hub.config import HubConfig, OAuthSettings
from palaia_hub.mcpb.template import TemplateNotFoundError, mcpb_binary, template_dir
from palaia_hub.vault import VaultRegistry


def _mcpb_available() -> bool:
    try:
        mcpb_binary(template_dir(env={}), env={})
    except TemplateNotFoundError:
        return False
    return True


requires_mcpb = pytest.mark.skipif(
    not _mcpb_available(), reason="mcpb CLI not installed (run `npm ci` in the template dir)"
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _registry_with_a_vault(tmp_path: Path) -> VaultRegistry:
    registry = VaultRegistry(tmp_path / "registry-home")
    await registry.create("work", tmp_path / "work-vault", purpose="test")
    return registry


def test_501_when_neither_token_store_nor_oauth_server_is_configured(tmp_path: Path) -> None:
    app = create_app(HubConfig(), vault_registry=VaultRegistry(tmp_path))
    client = TestClient(app)

    response = client.get("/api/connect/mcpb")

    assert response.status_code == 501
    assert "no client-authentication method is configured" in response.json()["detail"]


@pytest.mark.anyio
@requires_mcpb
async def test_token_variant_bakes_the_profile_url_and_a_freshly_minted_token(
    tmp_path: Path,
) -> None:
    registry = await _registry_with_a_vault(tmp_path)
    token_store = TokenStore(home=tmp_path / "tokens-home")
    app = create_app(HubConfig(), vault_registry=registry, token_store=token_store, home=tmp_path)
    client = TestClient(app)

    response = client.get("/api/connect/mcpb", params={"profile": "default"})

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="palaia.mcpb"'
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    uc = manifest["user_config"]
    assert uc["hub_url"]["default"] == f"{client.base_url}/mcp/default"
    assert uc["profile"]["default"] == "default"
    assert uc["oauth"]["default"] is False
    minted = uc["token"]["default"]
    assert minted.startswith("plt_")

    # The minted token is real: it shows up in the token store, scoped to
    # this profile with read+write on the registered vault.
    infos = token_store.list_tokens()
    assert len(infos) == 1
    assert infos[0].profile == "default"
    assert set(infos[0].scopes) == {"vault:work:read", "vault:work:write"}


@pytest.mark.anyio
@requires_mcpb
async def test_oauth_variant_contains_no_secret_at_all(tmp_path: Path) -> None:
    from palaia_hub.oauth import AuthorizationServer

    registry = await _registry_with_a_vault(tmp_path)
    config = HubConfig(
        mode="cloud",
        host="127.0.0.1",
        oauth=OAuthSettings(enabled=True, issuer="https://hub.example.com", profiles=["default"]),
    )
    oauth_server = AuthorizationServer.build(
        config, {"default": ["vault:work:read", "vault:work:write"]}, home=tmp_path / "oauth-home"
    )
    app = create_app(config, vault_registry=registry, oauth_server=oauth_server, home=tmp_path)
    client = TestClient(app)

    response = client.get("/api/connect/mcpb", params={"profile": "default"})

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    uc = manifest["user_config"]
    assert uc["oauth"]["default"] is True
    assert uc["issuer"]["default"] == "https://hub.example.com"
    assert "default" not in uc["token"]
    assert "plt_" not in json.dumps(manifest)
    assert response.headers["content-disposition"] == 'attachment; filename="palaia.mcpb"'
