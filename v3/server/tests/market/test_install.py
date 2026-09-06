"""SPEC-304 deliverables #1/#3/#4 over REST, through the real production
app — mirrors ``tests/upstream/test_api.py``'s own pattern (the exact
wiring ``palaia-hub serve`` runs), since an install lands in that same
upstream/gateway machinery.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastmcp import Client

from palaia_hub.config import load_config
from palaia_hub.market.docker_runtime import DockerError
from palaia_hub.registry.client import RegistryOfflineError
from palaia_hub.registry.models import RegistryServer
from palaia_hub.serve import ProductionApp, build_production_app
from palaia_hub.vault import VaultRegistry

from .conftest import HttpUpstream

pytestmark = pytest.mark.anyio

BASE_URL = "https://testserver"
SECRET = "sk-never-echo-this-back-9931"


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


def _manual_remote_entry(
    entry_id: str, url: str, *, config_schema: dict[str, Any] | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": entry_id,
        "name": "Fixture Remote",
        "one_liner": "A fixture MCP server for tests.",
        "kind": "remote",
        "source": {"type": "url", "value": url},
        "maintainer": "tests",
    }
    if config_schema is not None:
        body["config_schema"] = config_schema
    return body


async def _create_manual_remote(
    http: httpx.AsyncClient, entry_id: str, url: str, *, config_schema: dict[str, Any] | None = None
) -> httpx.Response:
    return await http.post(
        "/api/market/manual", json=_manual_remote_entry(entry_id, url, config_schema=config_schema)
    )


async def _consent(http: httpx.AsyncClient, entry_id: str) -> str:
    response = await http.post(f"/api/market/entry/{entry_id}/consent")
    assert response.status_code == 200, response.text
    return str(response.json()["token"])


async def _consent_refused(http: httpx.AsyncClient, entry_id: str) -> str:
    """Issue #349: what cannot be shown cannot be consented to — an entry
    that would be refused at install time is refused at the consent step,
    with the same plain reason, and no token is issued."""
    response = await http.post(f"/api/market/entry/{entry_id}/consent")
    assert response.status_code == 400, response.text
    return str(response.json()["detail"])


# --------------------------------------------------------- remote install


async def test_one_click_install_of_a_remote_entry_is_callable_without_a_restart(
    tmp_path: Path, http_upstream: HttpUpstream
) -> None:
    """SPEC-304 acceptance criterion: "from a curated-index entry,
    one-click install of a remote fixture upstream -> its tool callable
    through a profile without restart"."""
    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.fixture-remote"
        create = await _create_manual_remote(http, entry_id, http_upstream.url)
        assert create.status_code == 201

        token = await _consent(http, entry_id)
        install = await http.post(
            f"/api/market/entry/{entry_id}/install",
            json={"consent_token": token, "profiles": ["default"]},
        )
        assert install.status_code == 200, install.text
        body = install.json()
        assert body["entry_id"] == entry_id
        assert body["profiles"] == ["default"]
        assert body["up"] is True

        # No restart: the same running profile server answers immediately.
        async with Client(production.dynamic_gateway.profile_servers["default"]) as client:
            names = {tool.name for tool in await client.list_tools()}
            assert any(name.endswith("_echo") for name in names)


async def test_install_without_a_consent_post_is_impossible(
    tmp_path: Path, http_upstream: HttpUpstream
) -> None:
    """SPEC-304 acceptance criterion: install without a consent POST is
    impossible."""
    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.no-consent"
        await _create_manual_remote(http, entry_id, http_upstream.url)

        no_token = await http.post(
            f"/api/market/entry/{entry_id}/install",
            json={"consent_token": "made-up-token", "profiles": []},
        )
        assert no_token.status_code == 400
        assert "consent" in no_token.json()["detail"].lower()

        assert (await http.get("/api/market/installed")).json() == []


async def test_a_consent_token_is_single_use(tmp_path: Path, http_upstream: HttpUpstream) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.reuse-token"
        await _create_manual_remote(http, entry_id, http_upstream.url)
        token = await _consent(http, entry_id)

        first = await http.post(
            f"/api/market/entry/{entry_id}/install", json={"consent_token": token, "profiles": []}
        )
        assert first.status_code == 200

        second_entry_id = "acme.reuse-token-2"
        await http.post(
            "/api/market/manual", json=_manual_remote_entry(second_entry_id, http_upstream.url)
        )
        reused = await http.post(
            f"/api/market/entry/{second_entry_id}/install",
            json={"consent_token": token, "profiles": []},
        )
        assert reused.status_code == 400


async def test_a_consent_token_does_not_transfer_to_another_entry(
    tmp_path: Path, http_upstream: HttpUpstream
) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_a = "acme.entry-a"
        entry_b = "acme.entry-b"
        await _create_manual_remote(http, entry_a, http_upstream.url)
        await _create_manual_remote(http, entry_b, http_upstream.url)
        token = await _consent(http, entry_a)

        wrong_entry = await http.post(
            f"/api/market/entry/{entry_b}/install", json={"consent_token": token, "profiles": []}
        )
        assert wrong_entry.status_code == 400


async def test_installing_twice_is_refused(tmp_path: Path, http_upstream: HttpUpstream) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.twice"
        await _create_manual_remote(http, entry_id, http_upstream.url)
        token = await _consent(http, entry_id)
        first = await http.post(
            f"/api/market/entry/{entry_id}/install", json={"consent_token": token, "profiles": []}
        )
        assert first.status_code == 200

        token2 = await _consent(http, entry_id)
        second = await http.post(
            f"/api/market/entry/{entry_id}/install", json={"consent_token": token2, "profiles": []}
        )
        assert second.status_code == 400
        assert "already installed" in second.json()["detail"]


async def test_skill_entries_are_refused_with_a_connect_page_hint(tmp_path: Path) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.a-skill"
        await http.post(
            "/api/market/manual",
            json={
                "id": entry_id,
                "name": "A Skill",
                "one_liner": "A skill, not installable here.",
                "kind": "skill",
                "source": {"type": "url", "value": "https://example.com/SKILL.md"},
                "maintainer": "tests",
            },
        )
        assert "connect page" in await _consent_refused(http, entry_id)


async def test_uninstall_disconnects_and_persists(
    tmp_path: Path, http_upstream: HttpUpstream
) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.uninstall-me"
        await _create_manual_remote(http, entry_id, http_upstream.url)
        token = await _consent(http, entry_id)
        install = await http.post(
            f"/api/market/entry/{entry_id}/install",
            json={"consent_token": token, "profiles": ["default"]},
        )
        upstream_key = install.json()["upstream_key"]

        deleted = await http.delete(f"/api/market/installed/{upstream_key}")
        assert deleted.status_code == 204
        assert (await http.get("/api/market/installed")).json() == []

        listing = await http.get("/api/gateway/upstreams")
        assert listing.json() == []

    reloaded = load_config(home=tmp_path, create_if_missing=False)
    assert reloaded.gateway is not None
    assert reloaded.gateway.upstreams == []


# --------------------------------------------------------- secret round-trip


async def test_a_secret_config_field_round_trips_and_never_comes_back(
    tmp_path: Path, http_upstream: HttpUpstream
) -> None:
    """SPEC-304 acceptance criterion: a ``secret`` config field round-trips
    into the secret store and is never present in any subsequent GET
    (contract test)."""
    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.needs-secret"
        schema = {
            "type": "object",
            "properties": {"api_key": {"type": "secret", "title": "API key"}},
        }
        await _create_manual_remote(http, entry_id, http_upstream.url, config_schema=schema)
        token = await _consent(http, entry_id)
        install = await http.post(
            f"/api/market/entry/{entry_id}/install",
            json={"consent_token": token, "config": {"api_key": SECRET}, "profiles": []},
        )
        assert install.status_code == 200, install.text
        assert SECRET not in install.text

        for path in (
            "/api/market/installed",
            "/api/gateway/upstreams",
            "/api/secrets",
        ):
            response = await http.get(path)
            assert SECRET not in response.text, f"leaked at {path}"

        secret_names = [s["name"] for s in (await http.get("/api/secrets")).json()]
        assert any(name.endswith(".api_key") for name in secret_names)

    assert SECRET not in (tmp_path / "config.yaml").read_text(encoding="utf-8")


# ---------------------------------------------------- registry_ref -> stdio


class _FakeRegistryDetail:
    """Stands in for :class:`RegistryClient` for exactly one ``detail``
    lookup — deliverable #1's "stdio command entries" resolution needs a
    registry ``server.json`` shaped payload, which the merged
    :class:`~palaia_hub.market.models.MarketEntry` a manual/curated entry
    carries never has (see :mod:`palaia_hub.market.install`'s docstring)."""

    def __init__(self, server: RegistryServer | None) -> None:
        self._server = server

    async def detail(self, server_id: str) -> RegistryServer | None:
        return self._server


async def test_registry_ref_resolves_a_stdio_command_from_an_npm_package(
    tmp_path: Path,
) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.npm-tool"
        await http.post(
            "/api/market/manual",
            json={
                "id": entry_id,
                "name": "NPM Tool",
                "one_liner": "An npm-packaged MCP server.",
                "kind": "remote",
                "source": {"type": "registry_ref", "value": "io.example/npm-tool"},
                "maintainer": "tests",
            },
        )
        assert production.install_service is not None
        production.install_service.market_service.registry_client = _FakeRegistryDetail(  # type: ignore[assignment]
            RegistryServer(
                id="io.example/npm-tool",
                name="npm-tool",
                description="An npm tool.",
                version="1.2.0",
                raw={
                    "server": {
                        "packages": [
                            {
                                "registry_type": "npm",
                                "identifier": "@acme/npm-tool",
                                "version": "1.2.0",
                                "package_arguments": [{"value": "--quiet"}],
                            }
                        ]
                    }
                },
            )
        )

        token = await _consent(http, entry_id)
        install = await http.post(
            f"/api/market/entry/{entry_id}/install", json={"consent_token": token, "profiles": []}
        )
        assert install.status_code == 200, install.text

    upstream = production.dynamic_gateway.config.upstreams[0]
    assert upstream.kind == "stdio"
    assert upstream.command == "npx"
    assert upstream.args == ["-y", "@acme/npm-tool@1.2.0", "--quiet"]


async def test_an_unsupported_package_kind_is_refused_plainly(tmp_path: Path) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.mystery-package"
        await http.post(
            "/api/market/manual",
            json={
                "id": entry_id,
                "name": "Mystery",
                "one_liner": "A package palaia cannot run.",
                "kind": "remote",
                "source": {"type": "registry_ref", "value": "io.example/mystery"},
                "maintainer": "tests",
            },
        )
        assert production.install_service is not None
        production.install_service.market_service.registry_client = _FakeRegistryDetail(  # type: ignore[assignment]
            RegistryServer(
                id="io.example/mystery",
                name="mystery",
                description="",
                version=None,
                raw={"server": {"packages": [{"registry_type": "cargo", "identifier": "mystery"}]}},
            )
        )

        assert "does not know how to run" in await _consent_refused(http, entry_id)


async def test_registry_offline_during_resolution_is_a_plain_400(tmp_path: Path) -> None:
    class _OfflineRegistry:
        async def detail(self, server_id: str) -> RegistryServer | None:
            raise RegistryOfflineError("no network in this test")

    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.offline-registry"
        await http.post(
            "/api/market/manual",
            json={
                "id": entry_id,
                "name": "Offline",
                "one_liner": "x",
                "kind": "remote",
                "source": {"type": "registry_ref", "value": "io.example/offline"},
                "maintainer": "tests",
            },
        )
        assert production.install_service is not None
        production.install_service.market_service.registry_client = _OfflineRegistry()  # type: ignore[assignment]

        assert "registry" in (await _consent_refused(http, entry_id)).lower()


# ---------------------------------------------------------- container path


async def test_container_install_surfaces_a_pull_failure_plainly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The install path for ``container`` entries (docker daemon interaction
    itself is exercised, docker-gated, in ``test_install_container.py``) —
    here only the "pull fails" branch, which needs no real daemon."""
    from palaia_hub.market import install as install_module

    async def _fail_pull(image: str, *, timeout: float = 300.0) -> None:
        raise DockerError(f"docker pull {image!r} failed: no such image")

    monkeypatch.setattr(install_module.docker_runtime, "pull_image", _fail_pull)

    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.container-tool"
        await http.post(
            "/api/market/manual",
            json={
                "id": entry_id,
                "name": "Container Tool",
                "one_liner": "x",
                "kind": "container",
                "source": {"type": "image", "value": "ghcr.io/acme/does-not-exist:1.0.0"},
                "maintainer": "tests",
            },
        )
        token = await _consent(http, entry_id)
        response = await http.post(
            f"/api/market/entry/{entry_id}/install", json={"consent_token": token, "profiles": []}
        )
        assert response.status_code == 400
        assert "no such image" in response.json()["detail"]


# ------------------------------------------ the consent screen shows the plan


def _registry_entry(entry_id: str, registry_id: str) -> dict[str, Any]:
    return {
        "id": entry_id,
        "name": "Registry Tool",
        "one_liner": "A community-listed MCP server.",
        "kind": "remote",
        "source": {"type": "registry_ref", "value": registry_id},
        "maintainer": "tests",
    }


def _npm_listing(registry_id: str, identifier: str, version: str) -> RegistryServer:
    return RegistryServer(
        id=registry_id,
        name="tool",
        description="",
        version=version,
        raw={
            "server": {
                "packages": [{"registry_type": "npm", "identifier": identifier, "version": version}]
            }
        },
    )


async def test_the_consent_screen_can_show_the_exact_command_a_listing_would_run(
    tmp_path: Path,
) -> None:
    """Issue #349: consenting to a community listing used to mean consenting
    to a name — the command it resolves to was derived only after the click.
    The plan endpoint derives it first, with the very code the install uses,
    and the consent answer carries it too."""
    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.registry-tool"
        created = await http.post("/api/market/manual", json=_registry_entry(entry_id, "io.x/tool"))
        assert created.status_code == 201, created.text
        assert production.install_service is not None
        production.install_service.market_service.registry_client = _FakeRegistryDetail(  # type: ignore[assignment]
            _npm_listing("io.x/tool", "@acme/tool", "1.2.0")
        )

        plan = await http.get(f"/api/market/entry/{entry_id}/plan")
        assert plan.status_code == 200, plan.text
        shown = plan.json()
        assert shown["kind"] == "stdio"
        assert shown["command"] == "npx"
        assert shown["args"] == ["-y", "@acme/tool@1.2.0"]
        assert shown["url"] is None and shown["image"] is None
        assert len(shown["plan_hash"]) == 32

        consent = await http.post(f"/api/market/entry/{entry_id}/consent")
        assert consent.status_code == 200, consent.text
        assert consent.json()["preview"] == shown

        # A plain address is shown as the address it is.
        await _create_manual_remote(http, "acme.plain", "https://tools.example.com/mcp")
        plain = await http.get("/api/market/entry/acme.plain/plan")
        assert plain.status_code == 200, plain.text
        assert (plain.json()["kind"], plain.json()["url"]) == (
            "http",
            "https://tools.example.com/mcp",
        )

        # Nothing was installed, pulled or registered by looking.
        assert (await http.get("/api/market/installed")).json() == []
        assert production.dynamic_gateway.config.upstreams == []


async def test_an_install_is_refused_when_the_listing_changed_after_consent(
    tmp_path: Path,
) -> None:
    """Issue #349: the consent token is bound to what the owner was shown."""
    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.moving-target"
        await http.post("/api/market/manual", json=_registry_entry(entry_id, "io.x/moving"))
        service = production.install_service
        assert service is not None
        service.market_service.registry_client = _FakeRegistryDetail(  # type: ignore[assignment]
            _npm_listing("io.x/moving", "@acme/tool", "1.2.0")
        )
        token = await _consent(http, entry_id)

        # Between the consent screen and the click, the registry now lists
        # something else under the same id.
        service.market_service.registry_client = _FakeRegistryDetail(  # type: ignore[assignment]
            _npm_listing("io.x/moving", "@somebody-else/tool", "1.2.0")
        )

        install = await http.post(
            f"/api/market/entry/{entry_id}/install", json={"consent_token": token, "profiles": []}
        )
        assert install.status_code == 409, install.text
        assert "changed since you reviewed" in install.json()["detail"]
        assert (await http.get("/api/market/installed")).json() == []
        assert production.dynamic_gateway.config.upstreams == []

        # Reviewing again — and consenting to what is listed *now* — works.
        token = await _consent(http, entry_id)
        again = await http.post(
            f"/api/market/entry/{entry_id}/install", json={"consent_token": token, "profiles": []}
        )
        assert again.status_code == 200, again.text

    assert production.dynamic_gateway.config.upstreams[0].args == [
        "-y",
        "@somebody-else/tool@1.2.0",
    ]


@pytest.mark.parametrize(
    ("identifier", "version"),
    [
        ("--registry=https://evil.example", "1.0.0"),
        ("@acme/tool", "1.0.0 --ignore-scripts=false"),
    ],
)
async def test_a_package_name_that_is_really_a_runner_flag_is_refused(
    tmp_path: Path, identifier: str, version: str
) -> None:
    """Issue #349: registry content is unverified; a "package name" that
    ``npx`` would read as an option is not a package name."""
    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.flag-tool"
        await http.post("/api/market/manual", json=_registry_entry(entry_id, "io.x/flag"))
        assert production.install_service is not None
        production.install_service.market_service.registry_client = _FakeRegistryDetail(  # type: ignore[assignment]
            _npm_listing("io.x/flag", identifier, version)
        )

        plan = await http.get(f"/api/market/entry/{entry_id}/plan")
        assert plan.status_code == 400, plan.text
        assert "not a package name" in plan.json()["detail"]
        consent = await http.post(f"/api/market/entry/{entry_id}/consent")
        assert consent.status_code == 400
        assert production.dynamic_gateway.config.upstreams == []


# ---------------------------------------- a failed install leaves nothing behind


async def test_a_refused_profile_leaves_no_half_installed_upstream_behind(
    tmp_path: Path, http_upstream: HttpUpstream
) -> None:
    """Issue #351: a profile the install cannot mount on used to surface
    only after the upstream was registered — the installed list stayed
    empty while a retry answered "already installed"."""
    from palaia_hub.gateway.config import CURATOR_PROFILE_PATH

    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.wrong-profile"
        await _create_manual_remote(http, entry_id, http_upstream.url)

        for profiles, status in ((["does-not-exist"], 404), ([CURATOR_PROFILE_PATH], 400)):
            token = await _consent(http, entry_id)
            refused = await http.post(
                f"/api/market/entry/{entry_id}/install",
                json={"consent_token": token, "profiles": profiles},
            )
            assert refused.status_code == status, refused.text
            assert (await http.get("/api/market/installed")).json() == []
            assert production.dynamic_gateway.config.upstreams == []
            assert dict(production.upstream_service.configs) == {}

        # Corrected, the very next attempt succeeds.
        token = await _consent(http, entry_id)
        ok = await http.post(
            f"/api/market/entry/{entry_id}/install",
            json={"consent_token": token, "profiles": ["default"]},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["profiles"] == ["default"]


async def test_a_failure_after_registration_rolls_the_registration_back(
    tmp_path: Path, http_upstream: HttpUpstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #351: nothing about an install is persisted until its record is
    written, so nothing about it may survive in memory when that fails."""
    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.disk-full"
        await _create_manual_remote(http, entry_id, http_upstream.url)
        service = production.install_service
        assert service is not None

        def _no_disk() -> None:
            raise OSError("no space left on device")

        monkeypatch.setattr(service, "_persist", _no_disk)
        token = await _consent(http, entry_id)
        with pytest.raises(OSError):
            await http.post(
                f"/api/market/entry/{entry_id}/install",
                json={"consent_token": token, "profiles": ["default"]},
            )

        assert production.dynamic_gateway.config.upstreams == []
        assert dict(production.upstream_service.configs) == {}
        default = next(p for p in production.dynamic_gateway.config.profiles if p.path == "default")
        assert default.upstreams == []
        assert (await http.get("/api/market/installed")).json() == []

        monkeypatch.undo()
        token = await _consent(http, entry_id)
        ok = await http.post(
            f"/api/market/entry/{entry_id}/install",
            json={"consent_token": token, "profiles": ["default"]},
        )
        assert ok.status_code == 200, ok.text
