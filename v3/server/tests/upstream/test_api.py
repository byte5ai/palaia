"""SPEC-302 deliverables #2/#4 over REST, through the real production app.

``build_production_app`` is used rather than a hand-assembled router, so
these exercise the same wiring ``palaia-hub serve`` runs: connect a server,
see its health, have its tools appear on a profile without a restart, and —
the security half — never get a stored value back out of any endpoint.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastmcp import Client

from palaia_hub.config import load_config
from palaia_hub.serve import ProductionApp, build_production_app
from palaia_hub.vault import VaultRegistry

from .conftest import FIXTURE_BEARER_TOKEN, HttpUpstream

pytestmark = pytest.mark.anyio

BASE_URL = "https://testserver"
SECRET = "sk-never-echo-this-back-8123"


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


def _connect_body(url: str, *, secret_name: str | None = None) -> dict[str, object]:
    upstream: dict[str, object] = {
        "key": "fixture",
        "kind": "http",
        "display_name": "Fixture server",
        "url": url,
    }
    if secret_name is not None:
        upstream["auth"] = {"secret_name": secret_name}
    return {"upstream": upstream, "profiles": ["default"]}


async def test_connect_probe_and_call_without_a_restart(
    tmp_path: Path, http_upstream: HttpUpstream
) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        response = await http.post(
            "/api/gateway/upstreams", json=_connect_body(http_upstream.url)
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["key"] == "fixture"
        assert body["namespace"] == "fixture"
        assert body["profiles"] == ["default"]
        assert body["up"] is True
        assert "fixture_echo" not in body["tools"]  # upstream-side names
        assert "echo" in body["tools"]

        listing = (await http.get("/api/gateway/upstreams")).json()
        assert [item["key"] for item in listing] == ["fixture"]
        assert listing[0]["status"]

        # Live on the profile, no restart.
        async with Client(production.dynamic_gateway.profile_servers["default"]) as client:
            names = {tool.name for tool in await client.list_tools()}
            assert "fixture_echo" in names
            result = await client.call_tool("fixture_echo", {"text": "over rest"})
        assert "fixture-http-upstream echo: over rest" in str(result.content)


async def test_a_connected_server_survives_a_restart(
    tmp_path: Path, http_upstream: HttpUpstream
) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        assert (
            await http.post("/api/gateway/upstreams", json=_connect_body(http_upstream.url))
        ).status_code == 200

    restarted_config = load_config(home=tmp_path, create_if_missing=False)
    assert restarted_config.gateway is not None
    assert [u.key for u in restarted_config.gateway.upstreams] == ["fixture"]
    assert restarted_config.gateway.profiles[0].upstreams == ["fixture"]

    restarted = await build_production_app(restarted_config, home=tmp_path)
    async with _running(restarted) as http:
        # The monitor's own first pass is asynchronous; probing explicitly is
        # the deterministic equivalent.
        probed = (await http.post("/api/gateway/upstreams/fixture/probe")).json()
        assert probed["up"] is True
        async with Client(restarted.dynamic_gateway.profile_servers["default"]) as client:
            assert "fixture_echo" in {tool.name for tool in await client.list_tools()}


async def test_switching_a_server_off_removes_its_tools_and_persists(
    tmp_path: Path, http_upstream: HttpUpstream
) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        await http.post("/api/gateway/upstreams", json=_connect_body(http_upstream.url))
        patched = await http.patch(
            "/api/gateway/upstreams/fixture", json={"enabled": False}
        )
        assert patched.status_code == 200
        assert patched.json()["enabled"] is False
        assert patched.json()["up"] is False

        async with Client(production.dynamic_gateway.profile_servers["default"]) as client:
            names = {tool.name for tool in await client.list_tools()}
        assert not any(name.startswith("fixture_") for name in names)
        assert "work_memory_search" in names

    reloaded = load_config(home=tmp_path, create_if_missing=False)
    assert reloaded.gateway is not None
    assert reloaded.gateway.upstreams[0].enabled is False


async def test_renaming_an_upstream_tool_over_rest(
    tmp_path: Path, http_upstream: HttpUpstream
) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        await http.post("/api/gateway/upstreams", json=_connect_body(http_upstream.url))
        patched = await http.patch(
            "/api/gateway/upstreams/fixture", json={"tool_renames": {"echo": "say"}}
        )
        assert patched.status_code == 200
        assert patched.json()["tool_renames"] == {"echo": "say"}

        async with Client(production.dynamic_gateway.profile_servers["default"]) as client:
            names = {tool.name for tool in await client.list_tools()}
        assert "fixture_say" in names
        assert "fixture_echo" not in names


async def test_disconnecting_removes_it_from_every_profile(
    tmp_path: Path, http_upstream: HttpUpstream
) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        await http.post("/api/gateway/upstreams", json=_connect_body(http_upstream.url))
        assert (
            await http.delete("/api/gateway/upstreams/fixture")
        ).status_code == 204
        assert (await http.get("/api/gateway/upstreams")).json() == []
        profiles = (await http.get("/api/gateway/profiles")).json()
        assert all(profile["upstreams"] == [] for profile in profiles)

        async with Client(production.dynamic_gateway.profile_servers["default"]) as client:
            names = {tool.name for tool in await client.list_tools()}
        assert not any(name.startswith("fixture_") for name in names)

    reloaded = load_config(home=tmp_path, create_if_missing=False)
    assert reloaded.gateway is not None
    assert reloaded.gateway.upstreams == []


async def test_connecting_the_same_key_twice_is_refused(
    tmp_path: Path, http_upstream: HttpUpstream
) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        await http.post("/api/gateway/upstreams", json=_connect_body(http_upstream.url))
        second = await http.post(
            "/api/gateway/upstreams", json=_connect_body(http_upstream.url)
        )
        assert second.status_code == 400
        assert "already connected" in second.json()["detail"]


async def test_a_namespace_clash_with_a_vault_is_refused_loudly(tmp_path: Path) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        response = await http.post(
            "/api/gateway/upstreams",
            json={
                "upstream": {
                    "key": "clash",
                    "kind": "http",
                    "display_name": "Clashing server",
                    "url": "https://example.invalid/mcp",
                    "namespace": "work_memory",
                },
                "profiles": [],
            },
        )
        assert response.status_code == 400
        assert "work_memory" in response.json()["detail"]


async def test_mounting_on_the_curator_profile_is_refused_over_rest(
    tmp_path: Path, http_upstream: HttpUpstream
) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        body = _connect_body(http_upstream.url)
        body["profiles"] = ["curator"]
        response = await http.post("/api/gateway/upstreams", json=body)
        assert response.status_code == 400
        assert "curator" in response.json()["detail"]


# ------------------------------------------------------------------ secrets


async def test_a_stored_secret_value_never_comes_back_out(tmp_path: Path) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        stored = await http.put("/api/secrets/fixture-token", json={"value": SECRET})
        assert stored.status_code == 200
        assert stored.json() == {
            "name": "fixture-token",
            "created_at": stored.json()["created_at"],
            "updated_at": stored.json()["updated_at"],
        }
        assert SECRET not in stored.text

        listing = await http.get("/api/secrets")
        assert [item["name"] for item in listing.json()] == ["fixture-token"]
        assert SECRET not in listing.text

        # There is no endpoint that returns a value — the obvious guesses
        # are not routes at all.
        for path in (
            "/api/secrets/fixture-token",
            "/api/secrets/fixture-token/value",
        ):
            assert (await http.get(path)).status_code == 405 or (
                await http.get(path)
            ).status_code == 404

        # Nor does the upstream surface leak it: it names the secret only.
        await http.post(
            "/api/gateway/upstreams",
            json=_connect_body("https://example.invalid/mcp", secret_name="fixture-token"),
        )
        upstreams = await http.get("/api/gateway/upstreams")
        assert upstreams.json()[0]["secret_names"] == ["fixture-token"]
        assert SECRET not in upstreams.text

        # …and neither does the config file it persisted to.
        assert SECRET not in (tmp_path / "config.yaml").read_text(encoding="utf-8")

        assert (await http.delete("/api/secrets/fixture-token")).status_code == 204
        assert (await http.get("/api/secrets")).json() == []


async def test_a_secret_written_over_rest_is_the_one_the_upstream_uses(
    tmp_path: Path, http_upstream_with_token: HttpUpstream
) -> None:
    """The full loop: the dashboard writes the token, the hub connects with
    it, and the (token-demanding) fixture answers."""
    production = await _hub(tmp_path)
    async with _running(production) as http:
        await http.put("/api/secrets/fixture-token", json={"value": FIXTURE_BEARER_TOKEN})
        response = await http.post(
            "/api/gateway/upstreams",
            json=_connect_body(http_upstream_with_token.url, secret_name="fixture-token"),
        )
        assert response.status_code == 200, response.text
        assert response.json()["up"] is True

        async with Client(production.dynamic_gateway.profile_servers["default"]) as client:
            result = await client.call_tool("fixture_echo", {"text": "with a real token"})
        assert "fixture-http-upstream echo: with a real token" in str(result.content)


async def test_replacing_a_secret_reconnects_the_servers_using_it(
    tmp_path: Path, http_upstream_with_token: HttpUpstream
) -> None:
    """A rotated credential reaches an already-connected server without a
    restart: the wrong value leaves it down, and writing the right one over
    the same name brings it up and its tools back."""
    production = await _hub(tmp_path)
    async with _running(production) as http:
        await http.put("/api/secrets/fixture-token", json={"value": "the-wrong-token"})
        connected = await http.post(
            "/api/gateway/upstreams",
            json=_connect_body(http_upstream_with_token.url, secret_name="fixture-token"),
        )
        assert connected.status_code == 200
        assert connected.json()["up"] is False

        await http.put("/api/secrets/fixture-token", json={"value": FIXTURE_BEARER_TOKEN})

        assert (await http.get("/api/gateway/upstreams")).json()[0]["up"] is True
        async with Client(production.dynamic_gateway.profile_servers["default"]) as client:
            assert "fixture_echo" in {tool.name for tool in await client.list_tools()}


async def test_a_bad_secret_name_is_refused_without_echoing_the_value(
    tmp_path: Path,
) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        response = await http.put("/api/secrets/has%20space", json={"value": SECRET})
        assert response.status_code == 400
        assert SECRET not in response.text

        empty = await http.put("/api/secrets/token", json={"value": ""})
        assert empty.status_code == 400

        missing = await http.delete("/api/secrets/never-stored")
        assert missing.status_code == 404
