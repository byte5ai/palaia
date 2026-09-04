"""Issue #321, the wiring half: ``GET /api/market/installed`` (and
``check_updates``) resolve every installed add-on against **one**
curated-index fetch, and ``config.yaml``'s ``market.index_url`` /
``market.public_key`` reach the client the production app builds.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from palaia_hub.config import ConfigError, load_config
from palaia_hub.market.curated import (
    DEFAULT_INDEX_URL,
    DEFAULT_PUBLIC_KEY_B64,
    CuratedIndexClient,
)
from palaia_hub.market.installed_store import InstalledAddonRecord
from palaia_hub.serve import ProductionApp, build_production_app
from palaia_hub.vault import VaultRegistry

from .conftest import dump, make_document, make_entry

pytestmark = pytest.mark.anyio

BASE_URL = "https://testserver"


async def _hub(tmp_path: Path) -> ProductionApp:
    registry = VaultRegistry(tmp_path)
    await registry.create("work", tmp_path / "vaults" / "work", purpose="Work vault.")
    config = load_config(home=tmp_path)
    return await build_production_app(config, home=tmp_path)


@asynccontextmanager
async def _running(production: ProductionApp) -> AsyncIterator[httpx.AsyncClient]:
    try:
        async with production.app.router.lifespan_context(production.app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=production.app), base_url=BASE_URL
            ) as http:
                yield http
    finally:
        await production.dynamic_gateway.aclose()
        if production.stash_store is not None:
            production.stash_store.close()
        for index in production.indexes.values():
            await index.close()


def _record(n: int) -> InstalledAddonRecord:
    return InstalledAddonRecord(
        upstream_key=f"tool{n}",
        entry_id=f"acme.tool{n}",
        name=f"Acme Tool {n}",
        kind="container",
        provenance="curated",
        installed_ref="ghcr.io/acme/tool:0.9.0",  # older than the index's 1.0.0
        image="ghcr.io/acme/tool:0.9.0",
        container_name=f"palaia-addon-tool{n}",
        installed_at=0.0,
    )


async def _swap_in_curated_client(
    production: ProductionApp,
    home: Path,
    keypair: tuple[Ed25519PrivateKey, str],
    sign_document: Callable[[dict], dict],
) -> dict[str, int]:
    """Replace the production curated client with one whose every
    ``fetch()`` really hits the (counting) network — TTLs of zero — so a
    per-record fetch would show up as a count above one."""
    _, public_key_b64 = keypair
    document = sign_document(
        make_document(
            entries=[make_entry("acme.tool1"), make_entry("acme.tool2"), make_entry("acme.tool3")]
        )
    )
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, content=dump(document))

    assert production.install_service is not None
    await production.install_service.market_service.curated_client.aclose()
    production.install_service.market_service.curated_client = CuratedIndexClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        public_key_b64=public_key_b64,
        last_good_path=home / "market_curated_index.json",
        ttl_seconds=0,
        failure_ttl_seconds=0,
    )
    return calls


async def test_listing_installed_addons_fetches_the_curated_index_once(
    tmp_path: Path, keypair: tuple[Ed25519PrivateKey, str], sign_document: Callable[[dict], dict]
) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        calls = await _swap_in_curated_client(production, tmp_path, keypair, sign_document)
        assert production.install_service is not None
        for n in (1, 2, 3):
            production.install_service.installed_store.put(_record(n))

        response = await http.get("/api/market/installed")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["entry_id"] for item in body] == ["acme.tool1", "acme.tool2", "acme.tool3"]
    # Every record was resolved against the index (each sees the 1.0.0 ref)...
    assert all(item["current_ref"] == "ghcr.io/acme/tool:1.0.0" for item in body)
    assert all(item["update_available"] is True for item in body)
    # ...from exactly one fetch, not one per installed add-on.
    assert calls["count"] == 1


async def test_check_updates_fetches_the_curated_index_once(
    tmp_path: Path, keypair: tuple[Ed25519PrivateKey, str], sign_document: Callable[[dict], dict]
) -> None:
    production = await _hub(tmp_path)
    async with _running(production):
        calls = await _swap_in_curated_client(production, tmp_path, keypair, sign_document)
        assert production.install_service is not None
        for n in (1, 2, 3):
            production.install_service.installed_store.put(_record(n))

        changed = await production.install_service.check_updates()

    assert {out.entry_id for out in changed} == {"acme.tool1", "acme.tool2", "acme.tool3"}
    assert calls["count"] == 1


async def test_an_empty_installed_list_fetches_nothing(
    tmp_path: Path, keypair: tuple[Ed25519PrivateKey, str], sign_document: Callable[[dict], dict]
) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        calls = await _swap_in_curated_client(production, tmp_path, keypair, sign_document)
        response = await http.get("/api/market/installed")

    assert response.status_code == 200
    assert response.json() == []
    assert calls["count"] == 0


# ------------------------------------------------------------ config plumbing


def _fresh_public_key_b64() -> str:
    return base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes_raw()).decode()


async def test_market_index_url_and_public_key_reach_the_curated_client(tmp_path: Path) -> None:
    public_key = _fresh_public_key_b64()
    (tmp_path / "config.yaml").write_text(
        "market:\n"
        "  index_url: https://index.example.test/market-index.json\n"
        f"  public_key: {public_key}\n",
        encoding="utf-8",
    )
    registry = VaultRegistry(tmp_path)
    await registry.create("work", tmp_path / "vaults" / "work", purpose="Work vault.")
    config = load_config(home=tmp_path)
    assert config.market.index_url == "https://index.example.test/market-index.json"
    assert config.market.public_key == public_key

    production = await build_production_app(config, home=tmp_path)
    async with _running(production):
        assert production.install_service is not None
        curated = production.install_service.market_service.curated_client
        assert curated.index_url == "https://index.example.test/market-index.json"
        assert curated.public_key_b64 == public_key
        assert curated.last_good_path == tmp_path / "market_curated_index.json"
        assert curated._cache.cache_dir == tmp_path / "market_curated_cache"


async def test_market_defaults_apply_when_the_section_is_absent(tmp_path: Path) -> None:
    production = await _hub(tmp_path)
    async with _running(production):
        assert production.install_service is not None
        curated = production.install_service.market_service.curated_client
        assert curated.index_url == DEFAULT_INDEX_URL
        assert curated.public_key_b64 == DEFAULT_PUBLIC_KEY_B64


def test_a_malformed_public_key_is_refused_with_the_key_named(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        "market:\n  public_key: not-base64-at-all!\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(home=tmp_path)
    message = str(excinfo.value)
    assert "market.public_key" in message
    assert "Fix:" in message


def test_a_public_key_of_the_wrong_length_is_refused(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        f"market:\n  public_key: {base64.b64encode(b'short').decode()}\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(home=tmp_path)
    assert "32" in str(excinfo.value)
    assert "market.public_key" in str(excinfo.value)


def test_the_generated_template_round_trips_the_market_defaults(tmp_path: Path) -> None:
    load_config(home=tmp_path)  # writes the commented template
    from_file = load_config(home=tmp_path)
    assert from_file.market.index_url is None
    assert from_file.market.public_key is None
    text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "public_key: null" in text
