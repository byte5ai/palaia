"""``GET /api/backup`` (SPEC-604): mounted unconditionally, gated by the
admin session middleware.

The 401/403 matrix itself is already exercised for every gated route,
`/api/backup` included, by ``test_admin_session.py``'s route walk — see
that file's module docstring for why the walk (not a hand-maintained path
list) is the load-bearing test. What is worth its own file here is the
route's *own* behavior: headers, content, and that a signed-in caller
really does get back a working archive of the home it was pointed at.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from palaia_hub.admin_session import CSRF_HEADER
from palaia_hub.app import create_app
from palaia_hub.backup_api import (
    BACKUP_PATH,
    BACKUP_TARGETS_PATH,
    UNGATED_DETAIL,
    UNGATED_TARGETS_DETAIL,
    build_backup_router,
)
from palaia_hub.backup_targets import SUCCEEDED_EVENT, build_targets
from palaia_hub.config import (
    BackupSettings,
    HubConfig,
    LocalDirectoryBackupTarget,
    OAuthSettings,
)
from palaia_hub.oauth import AuthorizationServer, set_owner_password
from palaia_hub.oauth.login import CSRF_COOKIE, SESSION_COOKIE

ISSUER = "https://hub.example.test"
OWNER = "owner"
PASSWORD = "a-long-enough-passphrase"  # noqa: S105 - test fixture
NOW = 1_800_000_000


def test_backup_is_mounted_with_no_opt_in_parameter_but_refuses_without_a_gate(
    tmp_path: Path,
) -> None:
    """Same mounting posture as `/api/health` — a bare `create_app()` serves the
    route — but issue #317: with no admin session gate in front of it (the
    locked-mode default) it refuses, naming both ways out, rather than handing
    the hub's keys to anyone on the network."""
    app = create_app(HubConfig(), home=tmp_path)
    client = TestClient(app)

    response = client.get(BACKUP_PATH)

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail == UNGATED_DETAIL
    assert "palaia-hub backup" in detail
    assert "Fix:" in detail


def test_backup_headers_and_body(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("mode: locked\n", encoding="utf-8")
    vault = tmp_path / "vaults" / "work"
    vault.mkdir(parents=True)
    (vault / "note.md").write_text("# Hello\n\nBody.\n", encoding="utf-8")

    # The archive itself, exercised through the router with the gate on —
    # `session_gated=True` is what `create_app` passes once the admin
    # session middleware wraps `/api/*`; here the router is mounted alone.
    app = FastAPI()
    app.include_router(build_backup_router(home=tmp_path, session_gated=True))
    client = TestClient(app)

    response = client.get(BACKUP_PATH)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/gzip"
    assert response.headers["cache-control"] == "no-store"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="palaia-backup-')
    assert disposition.endswith('.tar.gz"')

    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as tar:
        names = tar.getnames()
        assert "config.yaml" in names
        assert "vaults/work/note.md" in names


def test_backup_requires_an_admin_session_when_the_gate_is_on(tmp_path: Path) -> None:
    """A focused, single-route confirmation alongside the route-walk
    coverage in `test_admin_session.py` — this endpoint carries secrets, so
    it gets its own explicit "no session, no archive" assertion too."""
    config = HubConfig(
        mode="cloud",
        host="127.0.0.1",
        oauth=OAuthSettings(enabled=True, issuer=ISSUER),
    )
    server = AuthorizationServer.build(config, {"default": ["vault:work:read"]}, home=tmp_path)
    set_owner_password(server.store, OWNER, PASSWORD, now=NOW)
    app = create_app(config, home=tmp_path, oauth_server=server)

    try:
        with TestClient(app) as client:
            anonymous = client.get(BACKUP_PATH)
            assert anonymous.status_code == 401
            assert "sign_in_url" in anonymous.json()

            session, _expires = server.store.create_login_session(
                OWNER, now=NOW, ttl=server.settings.session_ttl
            )
            client.cookies.set(SESSION_COOKIE, session)
            client.cookies.set(CSRF_COOKIE, "csrf-value")
            signed_in = client.get(BACKUP_PATH, headers={CSRF_HEADER: "csrf-value"})
            assert signed_in.status_code == 200
    finally:
        server.store.close()


# ----------------------------------------- the target routes (issue #297)


def _hub_home(root: Path) -> Path:
    home = root / "home"
    (home / "vaults" / "work").mkdir(parents=True)
    (home / "vaults" / "work" / "note.md").write_text("# Hi\n", encoding="utf-8")
    (home / "config.yaml").write_text("mode: locked\n", encoding="utf-8")
    return home


def _target_client(
    home: Path, destination: Path, published: list[tuple[str, dict[str, Any]]] | None = None
) -> TestClient:
    settings = BackupSettings(
        targets=[LocalDirectoryBackupTarget(name="nas", path=str(destination), keep_last=2)]
    )
    app = FastAPI()
    app.include_router(
        build_backup_router(
            home=home,
            session_gated=True,
            targets=build_targets(settings),
            publish=None
            if published is None
            else lambda event, data: published.append((event, data)),
        )
    )
    return TestClient(app)


def test_the_configured_targets_are_listed(tmp_path: Path) -> None:
    home = _hub_home(tmp_path)

    response = _target_client(home, tmp_path / "backups").get(BACKUP_TARGETS_PATH)

    assert response.status_code == 200
    assert response.json() == {
        "targets": [
            {
                "name": "nas",
                "kind": "local_directory",
                "destination": str(tmp_path / "backups"),
                "carries_full_archive": True,
                "secret_safe": True,
                "keep_last": 2,
            }
        ]
    }


def test_running_a_target_writes_the_archive_on_the_hub_not_through_the_browser(
    tmp_path: Path,
) -> None:
    """Issue #297 #1: the bytes go from the hub straight into the
    operator's directory — the response carries only the report."""
    home = _hub_home(tmp_path)
    destination = tmp_path / "backups"
    published: list[tuple[str, dict[str, Any]]] = []

    response = _target_client(home, destination, published).post(
        f"{BACKUP_TARGETS_PATH}/nas/run"
    )

    assert response.status_code == 200
    body = response.json()
    written = destination / body["artifact"]
    assert written.is_file()
    assert body["bytes_written"] == written.stat().st_size
    assert body["target"] == "nas"
    with tarfile.open(written, mode="r:gz") as tar:
        assert "vaults/work/note.md" in tar.getnames()
    assert [event for event, _ in published] == [SUCCEEDED_EVENT]


def test_running_an_unknown_target_names_the_configured_ones(tmp_path: Path) -> None:
    home = _hub_home(tmp_path)

    response = _target_client(home, tmp_path / "backups").post(f"{BACKUP_TARGETS_PATH}/nope/run")

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "nope" in detail
    assert "configured targets: nas" in detail


def test_a_failing_target_answers_500_with_the_reason(tmp_path: Path) -> None:
    """An unmounted share, a full disk — the request was fine, the hub
    could not carry it out, and the operator is told which."""
    home = _hub_home(tmp_path)

    response = _target_client(home, home / "inside").post(f"{BACKUP_TARGETS_PATH}/nas/run")

    assert response.status_code == 500
    assert "inside the hub's own data directory" in response.json()["detail"]


def test_a_hub_with_no_backup_section_lists_nothing_and_runs_nothing(tmp_path: Path) -> None:
    home = _hub_home(tmp_path)
    app = FastAPI()
    app.include_router(build_backup_router(home=home, session_gated=True))
    client = TestClient(app)

    assert client.get(BACKUP_TARGETS_PATH).json() == {"targets": []}
    missing = client.post(f"{BACKUP_TARGETS_PATH}/nas/run")
    assert missing.status_code == 404
    assert "none are configured" in missing.json()["detail"]


def test_the_target_routes_refuse_on_a_hub_with_no_sign_in(tmp_path: Path) -> None:
    """Same posture as the download itself (issue #317): without the admin
    session gate in front of them these refuse, naming the way out."""
    app = create_app(HubConfig(), home=tmp_path)
    client = TestClient(app)

    listed = client.get(BACKUP_TARGETS_PATH)
    ran = client.post(f"{BACKUP_TARGETS_PATH}/nas/run")

    assert listed.status_code == 403
    assert listed.json()["detail"] == UNGATED_TARGETS_DETAIL
    assert ran.status_code == 403
    assert "palaia-hub backup --target" in ran.json()["detail"]
