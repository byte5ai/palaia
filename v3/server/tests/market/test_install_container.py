"""Container add-on lifecycle, against a real docker daemon (SPEC-304
acceptance criterion: "install -> running -> health visible -> update ->
uninstall leaves no container behind (env-gated on docker availability,
skipped honestly otherwise)").

Building the fixture image needs both a reachable docker daemon *and*
network access (a base image pull, then a ``pip install`` of ``fastmcp``
inside it) — either being unavailable is reported as an honest skip, never
a failure: this module tests palaia's own lifecycle code, not whether the
sandbox running it happens to have a daemon or network reachable right
now.
"""

from __future__ import annotations

import asyncio
import subprocess
import textwrap
from pathlib import Path

import pytest

from palaia_hub.config import load_config
from palaia_hub.market.docker_runtime import docker_available
from palaia_hub.serve import ProductionApp, build_production_app
from palaia_hub.vault import VaultRegistry

from .test_install import _consent, _running

pytestmark = pytest.mark.anyio

IMAGE_TAG = "palaia-test-fixture-addon:latest"


def _docker_ready() -> bool:
    return asyncio.run(docker_available())


async def _hub(tmp_path: Path) -> ProductionApp:
    registry = VaultRegistry(tmp_path)
    await registry.create("work", tmp_path / "vaults" / "work", purpose="Work vault.")
    config = load_config(home=tmp_path)
    return await build_production_app(config, home=tmp_path)


@pytest.fixture(scope="module")
def fixture_image(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Build a tiny local image wrapping the same fixture MCP server the
    ``stdio``-upstream tests already use — skips honestly (never fails)
    when the daemon or the network needed to build it is unavailable."""
    if not _docker_ready():
        pytest.skip("no reachable docker daemon in this environment")

    build_dir = tmp_path_factory.mktemp("addon-image-build")
    script_src = (
        Path(__file__).resolve().parent.parent / "upstream" / "fixture_stdio_server.py"
    ).read_text(encoding="utf-8")
    (build_dir / "server.py").write_text(script_src, encoding="utf-8")
    (build_dir / "Dockerfile").write_text(
        textwrap.dedent(
            """\
            FROM python:3.12-slim
            RUN pip install --no-cache-dir fastmcp==3.4.7
            COPY server.py /server.py
            ENV FIXTURE_TOKEN=container-fixture-token
            CMD ["python", "/server.py"]
            """
        ),
        encoding="utf-8",
    )
    try:
        subprocess.run(
            ["docker", "build", "-t", IMAGE_TAG, str(build_dir)],
            check=True,
            capture_output=True,
            timeout=300,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"could not build the fixture image (no network?): {exc}")
    yield IMAGE_TAG
    subprocess.run(["docker", "rmi", "-f", IMAGE_TAG], capture_output=True)


async def test_container_install_run_update_uninstall_lifecycle(
    tmp_path: Path, fixture_image: str
) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.fixture-container"
        await http.post(
            "/api/market/manual",
            json={
                "id": entry_id,
                "name": "Fixture Container",
                "one_liner": "A fixture MCP server, containerized.",
                "kind": "container",
                "source": {"type": "image", "value": fixture_image},
                "maintainer": "tests",
            },
        )
        token = await _consent(http, entry_id)
        install = await http.post(
            f"/api/market/entry/{entry_id}/install",
            json={"consent_token": token, "profiles": ["default"]},
        )
        assert install.status_code == 200, install.text
        installed = install.json()
        upstream_key = installed["upstream_key"]
        assert installed["kind"] == "container"

        # Health visible.
        probed = await http.post(f"/api/gateway/upstreams/{upstream_key}/probe")
        assert probed.json()["up"] is True
        assert "whoami" in probed.json()["tools"] or "add" in probed.json()["tools"]

        # Update — same tag, but exercises the one-click update path end to
        # end (re-pull, rebuild the connection).
        updated = await http.post(f"/api/market/installed/{upstream_key}/update")
        assert updated.status_code == 200, updated.text

        # Uninstall leaves no container behind.
        container_name = f"palaia-addon-{upstream_key}"
        uninstalled = await http.delete(f"/api/market/installed/{upstream_key}")
        assert uninstalled.status_code == 204

    remaining = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name=^{container_name}$", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert remaining.stdout.strip() == ""


async def test_updating_a_non_container_add_on_is_refused(tmp_path: Path) -> None:
    production = await _hub(tmp_path)
    async with _running(production) as http:
        entry_id = "acme.fixture-remote-for-update"
        # A `remote` entry, never actually connected — this test only
        # proves the "only a container can be updated" rule, which needs
        # no docker at all.
        await http.post(
            "/api/market/manual",
            json={
                "id": entry_id,
                "name": "Remote",
                "one_liner": "x",
                "kind": "remote",
                "source": {"type": "url", "value": "https://example.invalid/mcp"},
                "maintainer": "tests",
            },
        )
        token = await _consent(http, entry_id)
        install = await http.post(
            f"/api/market/entry/{entry_id}/install",
            json={"consent_token": token, "profiles": []},
        )
        upstream_key = install.json()["upstream_key"]

        response = await http.post(f"/api/market/installed/{upstream_key}/update")
        assert response.status_code == 400
        assert "container" in response.json()["detail"]
