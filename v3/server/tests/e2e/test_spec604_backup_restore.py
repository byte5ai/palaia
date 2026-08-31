"""SPEC-604 acceptance criterion #1, the whole point of this feature, end
to end against real subprocesses:

    fresh hub -> write memory -> download backup -> NEW fresh home ->
    restore per the documented steps -> the memory is back and a client
    can read it

Plus the two criteria that go with it:

* **secrets round-trip** — a known plaintext, put into the secret store
  before the backup, is still decryptable after the restore.
* **if indexes are excluded, restore provably rebuilds them** — the
  restored home has no ``.palaia/index.sqlite3`` right after unpacking
  (proving the exclusion), and a real search against the restored hub
  finds the note (proving the rebuild the exclusion depends on actually
  happens, not just that a file reappears).

Restore itself is driven exactly the way ``docs/backup-restore.md`` and the
docs-site page describe it: stop the hub, unpack the archive into the data
directory, start it again — no special "restore mode," just a second
``hub_server_backup.py`` process pointed at the unpacked directory.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from conftest import RunningHub, free_port, wait_for_health
from simulator import SimulatedClient

from palaia_hub.upstream.secrets import SecretStore

pytestmark = pytest.mark.anyio

_SCRIPT = Path(__file__).parent / "support" / "hub_server_backup.py"

OWNER_USERNAME = "owner"
OWNER_PASSWORD = "a-long-enough-passphrase"  # noqa: S105 - test fixture
SECRET_NAME = "spec604-upstream-token"
SECRET_VALUE = "s3cr3t-upstream-value-do-not-log-me"  # noqa: S105 - test fixture


def _spawn(
    *, home: Path, log_path: Path, secret_name: str | None = None, secret_value: str | None = None
) -> RunningHub:
    """Launch a real ``hub_server_backup.py`` subprocess over ``home``.

    A local factory rather than ``conftest.py``'s ``hub_factory``: that one
    drives ``hub_server.py``, whose ``--vault-dir``/``--vault-key`` shape
    does not fit this scenario (the vault has to live *inside* ``home`` for
    a whole-home backup to mean anything — see ``hub_server_backup.py``'s
    module docstring). Same subprocess discipline throughout: ``sys.
    executable`` directly, never a ``uv run`` wrapper, so ``.kill()``/
    ``.stop()`` really terminates the server process (SPEC-102/103's
    kill-test finding, restated in every other e2e support script here).
    """
    port = free_port()
    args = [
        sys.executable,
        str(_SCRIPT),
        "--port",
        str(port),
        "--home",
        str(home),
        "--username",
        OWNER_USERNAME,
        "--password",
        OWNER_PASSWORD,
    ]
    if secret_name and secret_value:
        args += ["--secret-name", secret_name, "--secret-value", secret_value]

    log_file = log_path.open("w")
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        args, stdout=log_file, stderr=subprocess.STDOUT
    )
    try:
        wait_for_health(port)
    except Exception:
        process.kill()
        process.wait(timeout=5)
        raise
    return RunningHub(process=process, port=port, profiles=["default"], log_path=log_path)


HubBackupFactory = Callable[..., RunningHub]


@pytest.fixture
def hub_factory(tmp_path: Path) -> Iterator[HubBackupFactory]:
    """Shadows ``conftest.py``'s module-level ``hub_factory`` fixture for
    every test in this file — pytest resolves a fixture defined in the test
    module itself before the one in ``conftest.py``. Tears down every hub
    it started, same as the one it shadows."""
    started: list[RunningHub] = []

    def factory(
        *,
        home: Path,
        log_name: str = "hub.log",
        secret_name: str | None = None,
        secret_value: str | None = None,
    ) -> RunningHub:
        hub = _spawn(
            home=home,
            log_path=tmp_path / log_name,
            secret_name=secret_name,
            secret_value=secret_value,
        )
        started.append(hub)
        return hub

    yield factory

    for hub in started:
        hub.stop()


def _sign_in(base_url: str) -> httpx.Client:
    """A real password sign-in over a real socket — the same double-submit
    dance ``test_spec209_client_matrix.py::_csrf_and_sign_in`` uses, kept
    local here since this is the only test in this file that needs it."""
    client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=10.0)
    login_form = client.get("/oauth/login")
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_form.text)
    assert match is not None, login_form.text
    signed_in = client.post(
        "/oauth/login",
        data={
            "username": OWNER_USERNAME,
            "password": OWNER_PASSWORD,
            "csrf_token": match.group(1),
            "next": "",
        },
    )
    assert signed_in.status_code == 303, signed_in.text
    assert "palaia_oauth_session" in client.cookies
    return client


def _mint_token(client: httpx.Client, *, name: str) -> str:
    """Mint a real SPEC-108 bearer token through the same admin-gated
    ``POST /api/auth/tokens`` route the dashboard's "Connect a client"
    panel calls — the plaintext this returns is what a real MCP client
    would be handed once, never logged or stored anywhere else."""
    csrf = client.cookies.get("palaia_oauth_csrf", "")
    response = client.post(
        "/api/auth/tokens",
        json={
            "name": name,
            "profile": "default",
            "scopes": ["vault:work:read", "vault:work:write"],
        },
        headers={"X-Palaia-CSRF": csrf},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["token"])


async def test_fresh_hub_to_backup_to_new_home_to_restore_to_readable_memory(
    tmp_path: Path, hub_factory: HubBackupFactory
) -> None:
    home1 = tmp_path / "home1"
    hub1 = hub_factory(
        home=home1,
        log_name="hub1.log",
        secret_name=SECRET_NAME,
        secret_value=SECRET_VALUE,
    )

    # --- downloading the backup with no session at all is refused (SPEC-604
    # acceptance: "the endpoint 401s without an admin session in every mode
    # that gates" — the route-walk matrix in test_admin_session.py covers
    # every OTHER gated route; this is the one specific to this endpoint,
    # against a real socket rather than the ASGI test transport). ---
    anonymous = httpx.get(f"http://127.0.0.1:{hub1.port}/api/backup", timeout=5.0)
    assert anonymous.status_code == 401, anonymous.text

    # --- sign in as the owner, mint a real client token the same way the
    # dashboard's "Connect a client" panel does, and download the backup —
    # all through the one admin session. ---
    signed_in = _sign_in(f"http://127.0.0.1:{hub1.port}")
    try:
        token = _mint_token(signed_in, name="spec604-e2e-client")

        # --- write a memory through a real MCP client, using that token. ---
        async with SimulatedClient(
            hub1.profile_url(), client_name="spec604-writer", token=token
        ) as client:
            write_result = await client.call_tool_ok(
                "work_memory_write",
                {
                    "title": "SPEC-604 Round Trip",
                    "body": "This note has to survive a backup and a restore onto a new home.",
                },
            )
            assert "SPEC-604 Round Trip" in write_result.text

        response = signed_in.get("/api/backup")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/gzip"
        archive_bytes = response.content
    finally:
        signed_in.close()

    archive_path = tmp_path / "palaia-backup.tar.gz"
    archive_path.write_bytes(archive_bytes)

    hub1.stop()

    # --- "NEW fresh home": a directory that never existed before, unpacked
    # exactly the way docs/backup-restore.md's restore steps say. ---
    home2 = tmp_path / "home2"
    home2.mkdir()
    with tarfile.open(archive_path, mode="r:gz") as tar:
        tar.extractall(home2, filter="data")

    # --- the excluded index is provably absent right after unpacking — the
    # acceptance criterion's other half (the rebuild) is checked once hub2
    # is up, below. ---
    restored_index = home2 / "vaults" / "work" / ".palaia" / "index.sqlite3"
    assert not restored_index.exists(), (
        "the archive should not have shipped the rebuildable search index"
    )

    # --- secrets round-trip: the plaintext put into hub1's secret store
    # before the backup is still decryptable from the restored home, using
    # only what the archive shipped (secrets.sqlite3 AND secrets.key). ---
    restored_secrets = SecretStore(home2)
    try:
        assert restored_secrets.get(SECRET_NAME) == SECRET_VALUE
    finally:
        restored_secrets.close()

    # --- start a hub against the restored home: no special "restore mode,"
    # the same process this whole scenario has used throughout. ---
    hub2 = hub_factory(home=home2, log_name="hub2.log")

    # --- the rebuild half of the index-exclusion acceptance criterion: the
    # index file exists again, rebuilt on this very start. ---
    assert restored_index.exists(), (
        "the search index should have rebuilt itself on the restored hub's first start"
    )

    # --- the headline moment: a client reads the memory back, through the
    # restored hub, having never touched hub1 at all. The SAME token minted
    # against hub1 still works here too — `tokens.yaml` is part of the whole
    # -home archive like everything else, so a restore brings back not just
    # the data but the access a client already had to it. ---
    async with SimulatedClient(
        hub2.profile_url(), client_name="spec604-reader", token=token
    ) as client:
        read_result = await client.call_tool_ok(
            "work_memory_read", {"permalink": "spec-604-round-trip"}
        )
        assert "survive a backup and a restore" in read_result.text

        search_result = await client.call_tool_ok(
            "work_memory_search", {"query": "SPEC-604 Round Trip"}
        )
        assert "SPEC-604 Round Trip" in search_result.text


async def test_restore_does_not_require_the_index_directory_to_pre_exist(
    tmp_path: Path, hub_factory: HubBackupFactory
) -> None:
    """A vault whose `.palaia/` directory the archive never created at all
    (rather than an empty one) still starts cleanly — covers a restore from
    an archive built before any index had ever been opened once."""
    home1 = tmp_path / "home1"
    hub1 = hub_factory(home=home1, log_name="hub1.log")

    signed_in = _sign_in(f"http://127.0.0.1:{hub1.port}")
    try:
        token = _mint_token(signed_in, name="spec604-e2e-client-2")

        async with SimulatedClient(
            hub1.profile_url(), client_name="spec604-writer-2", token=token
        ) as client:
            await client.call_tool_ok(
                "work_memory_write",
                {"title": "No Index Yet", "body": "Backed up before any search ever ran."},
            )

        response = signed_in.get("/api/backup")
        assert response.status_code == 200
        archive_bytes = response.content
    finally:
        signed_in.close()
    hub1.stop()

    home2 = tmp_path / "home2"
    home2.mkdir()
    archive_path = tmp_path / "backup2.tar.gz"
    archive_path.write_bytes(archive_bytes)
    with tarfile.open(archive_path, mode="r:gz") as tar:
        tar.extractall(home2, filter="data")
    shutil.rmtree(home2 / "vaults" / "work" / ".palaia", ignore_errors=True)

    hub2 = hub_factory(home=home2, log_name="hub2.log")
    assert hub2.is_alive()

    async with SimulatedClient(
        hub2.profile_url(), client_name="spec604-reader-2", token=token
    ) as client:
        result = await client.call_tool_ok("work_memory_read", {"permalink": "no-index-yet"})
        assert "Backed up before any search ever ran" in result.text
