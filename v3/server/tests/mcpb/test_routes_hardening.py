"""Issue #397: the download endpoint validates its `profile`, points the
bundle at the configured public address, and never leaves a token behind
for a bundle that failed to build. None of this needs the mcpb CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palaia_hub.auth.store import TokenStore
from palaia_hub.mcpb import routes as mcpb_routes
from palaia_hub.mcpb.builder import BundleBuildError, BundleRequest
from palaia_hub.vault import VaultRegistry

pytestmark = pytest.mark.anyio


async def _app(tmp_path: Path, **router_kwargs: object) -> tuple[TestClient, TokenStore]:
    registry = VaultRegistry(tmp_path / "registry-home")
    await registry.create("work", tmp_path / "work-vault", purpose="test")
    token_store = TokenStore(home=tmp_path / "tokens-home")
    app = FastAPI()
    app.include_router(
        mcpb_routes.build_mcpb_router(
            vault_registry=registry,
            token_store=token_store,
            oauth_server=None,
            home=tmp_path,
            **router_kwargs,  # type: ignore[arg-type]
        )
    )
    return TestClient(app), token_store


async def test_a_profile_that_is_not_a_path_is_refused_before_a_token_is_minted(
    tmp_path: Path,
) -> None:
    client, token_store = await _app(tmp_path)
    response = client.get("/api/connect/mcpb", params={"profile": "../etc"})
    assert response.status_code == 400
    assert "profile" in response.json()["detail"]
    assert token_store.list_tokens() == []


async def test_an_unknown_profile_is_a_404_when_the_gateway_is_known(tmp_path: Path) -> None:
    client, token_store = await _app(tmp_path, known_profiles=lambda: ["default", "phone"])
    response = client.get("/api/connect/mcpb", params={"profile": "laptop"})
    assert response.status_code == 404
    assert token_store.list_tokens() == []


async def test_a_failed_build_revokes_the_token_it_minted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(request: BundleRequest, *, home: Path) -> bytes:
        raise BundleBuildError("mcpb pack exploded")

    monkeypatch.setattr(mcpb_routes, "build_bundle", failing)
    client, token_store = await _app(tmp_path)

    response = client.get("/api/connect/mcpb", params={"profile": "default"})

    assert response.status_code == 500
    [info] = token_store.list_tokens()
    assert info.revoked_at is not None, (
        "a token for a bundle that never shipped must not stay valid"
    )


async def test_the_bundle_points_at_the_configured_public_address(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[BundleRequest] = []

    def capturing(request: BundleRequest, *, home: Path) -> bytes:
        seen.append(request)
        return b"not-really-a-bundle"

    monkeypatch.setattr(mcpb_routes, "build_bundle", capturing)
    client, _ = await _app(tmp_path, public_url="https://hub.example.com/")

    response = client.get("/api/connect/mcpb", params={"profile": "default"})

    assert response.status_code == 200
    assert seen[0].hub_url == "https://hub.example.com/mcp/default"
