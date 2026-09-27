"""Per-vault git push (issue #438): configuration, the push, and the token.

Pushes go to a local bare repository: a throwaway global git config rewrites
the ``https://`` URL the owner would enter to that path (``url.insteadOf``),
so the real ``git push`` runs end to end with no network.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palaia_hub import vault_remote
from palaia_hub.app import create_app
from palaia_hub.backup_schedule import BackupLedger, BackupScheduler
from palaia_hub.config import HubConfig
from palaia_hub.upstream.secrets import SecretStore
from palaia_hub.vault import VaultRegistry
from palaia_hub.vault_remote import (
    FAILED_EVENT,
    PUSHED_EVENT,
    REMOTES_FILENAME,
    VaultRemoteBusyError,
    VaultRemoteError,
    VaultRemotes,
    secret_name,
    validate_url,
)
from palaia_hub.vault_remote_api import (
    UNGATED_VAULT_REMOTES_DETAIL,
    VAULT_REMOTE_PATH,
    VAULT_REMOTE_PUSH_PATH,
    VAULT_REMOTES_PATH,
    build_vault_remote_router,
)

URL = "https://git.example.test/owner/notes.git"
TOKEN = "ghp_this-is-the-secret-token-1234567890"


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _commit(root: Path, name: str, text: str) -> str:
    (root / name).write_text(text, encoding="utf-8")
    _git(root, "add", name)
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", name)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def bare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A bare repository the test URL is rewritten to."""
    repo = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(repo)], check=True)  # noqa: S603, S607
    config = tmp_path / "gitconfig"
    config.write_text(f'[url "{repo}"]\n\tinsteadOf = {URL}\n', encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return repo


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    root = tmp_path / "vaults" / "work"
    root.mkdir(parents=True)
    _git(root, "init", "-q", "--initial-branch=main")
    _commit(root, "a.md", "first\n")
    return root


@pytest.fixture
def secrets(tmp_path: Path) -> Iterator[SecretStore]:
    store = SecretStore(tmp_path / "home")
    yield store
    store.close()


@pytest.fixture
def events() -> list[tuple[str, dict[str, Any]]]:
    return []


@pytest.fixture
def remotes(
    tmp_path: Path,
    vault_root: Path,
    secrets: SecretStore,
    events: list[tuple[str, dict[str, Any]]],
) -> VaultRemotes:
    return VaultRemotes(
        tmp_path / "home",
        secrets,
        lambda: {"work": vault_root},
        publish=lambda event, data: events.append((event, data)),
    )


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize(
    ("url", "fragment"),
    [
        ("http://github.com/you/notes.git", "https://"),
        ("git@github.com:you/notes.git", "https://"),
        ("ssh://git@github.com/you/notes.git", "https://"),
        ("https://user:pw@github.com/you/notes.git", "user name or password"),
        ("https://ghp_token@github.com/you/notes.git", "user name or password"),
        ("https://github.com/", "no repository"),
        ("https://github.com/you/notes.git?x=1", "query"),
    ],
)
def test_only_a_plain_https_repository_url_is_accepted(url: str, fragment: str) -> None:
    with pytest.raises(VaultRemoteError, match=fragment):
        validate_url(url)


def test_a_plain_https_url_is_accepted() -> None:
    assert validate_url(" https://github.com/you/notes.git ") == "https://github.com/you/notes.git"


# --------------------------------------------------------------- configuration


def test_configuring_needs_a_token_the_first_time(remotes: VaultRemotes) -> None:
    with pytest.raises(VaultRemoteError, match="access token is needed"):
        remotes.configure("work", url=URL)
    assert remotes.get("work") is None


def test_an_unknown_vault_cannot_be_configured(remotes: VaultRemotes) -> None:
    with pytest.raises(VaultRemoteError, match="no vault named"):
        remotes.configure("nope", url=URL, token=TOKEN)


def test_the_token_goes_to_the_secret_store_and_nowhere_else(
    tmp_path: Path, remotes: VaultRemotes, secrets: SecretStore
) -> None:
    remotes.configure("work", url=URL, branch="backup", token=TOKEN)
    assert secrets.get(secret_name("work")) == TOKEN
    stored = (tmp_path / "home" / REMOTES_FILENAME).read_text(encoding="utf-8")
    assert TOKEN not in stored
    assert json.loads(stored)["vaults"]["work"]["branch"] == "backup"
    assert (tmp_path / "home" / REMOTES_FILENAME).stat().st_mode & 0o777 == 0o600
    (listed,) = remotes.describe()
    assert listed["remote"]["has_token"] is True
    assert TOKEN not in json.dumps(listed)


def test_the_url_can_change_without_re_entering_the_token(
    remotes: VaultRemotes, secrets: SecretStore
) -> None:
    remotes.configure("work", url=URL, token=TOKEN)
    remotes.configure("work", url="https://git.example.test/owner/other.git")
    assert secrets.get(secret_name("work")) == TOKEN
    remote = remotes.get("work")
    assert remote is not None and remote.url.endswith("other.git")


def test_removing_forgets_the_destination_and_deletes_the_token(
    remotes: VaultRemotes, secrets: SecretStore
) -> None:
    remotes.configure("work", url=URL, token=TOKEN)
    assert remotes.remove("work") is True
    assert remotes.get("work") is None
    assert secrets.get(secret_name("work")) is None


def test_every_registered_vault_is_listed_configured_or_not(remotes: VaultRemotes) -> None:
    (listed,) = remotes.describe()
    assert listed == {
        "vault": "work",
        "registered": True,
        "remote": None,
        "pushing": False,
        "last_push": None,
    }


# ------------------------------------------------------------------- the push


def test_a_push_puts_the_vaults_head_on_the_branch(
    bare: Path,
    vault_root: Path,
    remotes: VaultRemotes,
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    remotes.configure("work", url=URL, branch="notes", token=TOKEN)
    record = remotes.push("work", trigger="manual")
    head = _git(vault_root, "rev-parse", "HEAD")
    assert record.ok and record.commit == head
    assert _git(bare, "rev-parse", "refs/heads/notes") == head
    assert events == [
        (
            PUSHED_EVENT,
            {"vault": "work", "url": URL, "branch": "notes", "commit": head, "trigger": "manual"},
        )
    ]
    # The vault's own repository gained no remote.
    assert _git(vault_root, "remote") == ""


def test_later_pushes_carry_new_notes(bare: Path, vault_root: Path, remotes: VaultRemotes) -> None:
    remotes.configure("work", url=URL, token=TOKEN)
    remotes.push("work", trigger="manual")
    newer = _commit(vault_root, "b.md", "second\n")
    remotes.push("work", trigger="schedule")
    assert _git(bare, "rev-parse", "refs/heads/main") == newer


def test_a_branch_with_foreign_commits_is_never_overwritten(
    tmp_path: Path,
    bare: Path,
    remotes: VaultRemotes,
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], check=True)  # noqa: S603, S607
    _git(other, "checkout", "-q", "-b", "main")
    foreign = _commit(other, "theirs.md", "not from this vault\n")
    _git(other, "push", "-q", "origin", "main")

    remotes.configure("work", url=URL, token=TOKEN)
    with pytest.raises(VaultRemoteError, match="did not overwrite"):
        remotes.push("work", trigger="manual")
    assert _git(bare, "rev-parse", "refs/heads/main") == foreign
    assert events[-1][0] == FAILED_EVENT
    (listed,) = remotes.describe()
    assert listed["last_push"]["ok"] is False


def test_the_token_never_appears_in_a_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    remotes: VaultRemotes,
    events: list[tuple[str, dict[str, Any]]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A git that echoes its whole environment into stderr: the worst case
    # for a leak, and the reason every line git prints is scrubbed.
    real_run = subprocess.run

    def echoing_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "push" in argv:
            env = kwargs["env"]
            dump = " ".join(f"{k}={v}" for k, v in env.items() if k.startswith("GIT_CONFIG"))
            return subprocess.CompletedProcess(argv, 128, stdout="", stderr=f"fatal: {dump}")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(vault_remote.subprocess, "run", echoing_run)
    remotes.configure("work", url=URL, token=TOKEN)
    with caplog.at_level(logging.DEBUG), pytest.raises(VaultRemoteError) as raised:
        remotes.push("work", trigger="manual")
    remotes.push_all(trigger="schedule")

    basic = vault_remote.base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()
    surfaces = [
        str(raised.value),
        json.dumps(events),
        json.dumps(remotes.describe()),
        (tmp_path / "home" / REMOTES_FILENAME).read_text(encoding="utf-8"),
        caplog.text,
    ]
    for text in surfaces:
        assert TOKEN not in text
        assert basic not in text
    assert "***" in str(raised.value)


def test_the_token_travels_in_the_environment_scoped_to_the_host(
    monkeypatch: pytest.MonkeyPatch, remotes: VaultRemotes
) -> None:
    seen: list[tuple[list[str], dict[str, str]]] = []
    real_run = subprocess.run

    def recording_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.append((list(argv), dict(kwargs["env"])))
        if "push" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(vault_remote.subprocess, "run", recording_run)
    remotes.configure("work", url=URL, token=TOKEN)
    remotes.push("work", trigger="manual")

    push_argv, push_env = next(item for item in seen if "push" in item[0])
    assert all(TOKEN not in part for part in push_argv)
    assert push_env["GIT_CONFIG_KEY_0"] == "http.https://git.example.test/.extraHeader"
    assert push_env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
    assert push_env["GIT_CONFIG_KEY_1"] == "credential.helper"
    assert push_env["GIT_CONFIG_VALUE_1"] == ""
    assert push_env["GIT_TERMINAL_PROMPT"] == "0"
    assert "--force" not in push_argv and "-f" not in push_argv


def test_one_vault_is_never_pushed_twice_at_once(remotes: VaultRemotes) -> None:
    remotes.configure("work", url=URL, token=TOKEN)
    remotes._pushing.add("work")  # a push already in flight
    with pytest.raises(VaultRemoteBusyError):
        remotes.push("work", trigger="manual")
    assert remotes.push_all(trigger="schedule") == {}


def test_the_last_push_survives_a_restart(
    tmp_path: Path, bare: Path, vault_root: Path, secrets: SecretStore, remotes: VaultRemotes
) -> None:
    remotes.configure("work", url=URL, token=TOKEN)
    remotes.push("work", trigger="manual")
    again = VaultRemotes(tmp_path / "home", secrets, lambda: {"work": vault_root})
    (listed,) = again.describe()
    assert listed["remote"]["url"] == URL
    assert listed["last_push"]["ok"] is True
    assert listed["last_push"]["commit"] == _git(vault_root, "rev-parse", "HEAD")


def test_a_damaged_file_means_nothing_is_configured(
    tmp_path: Path, vault_root: Path, secrets: SecretStore
) -> None:
    home = tmp_path / "home"
    (home / REMOTES_FILENAME).write_text("{not json", encoding="utf-8")
    loaded = VaultRemotes(home, secrets, lambda: {"work": vault_root})
    assert loaded.configured() == []


# ---------------------------------------------------------------- REST routes


def _client(remotes: VaultRemotes, *, gated: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(build_vault_remote_router(remotes, session_gated=gated))
    return TestClient(app)


def test_the_routes_configure_push_and_remove(
    bare: Path, vault_root: Path, remotes: VaultRemotes, secrets: SecretStore
) -> None:
    client = _client(remotes)
    listed = client.get(VAULT_REMOTES_PATH).json()["vaults"]
    assert [entry["vault"] for entry in listed] == ["work"]
    assert listed[0]["remote"] is None

    saved = client.put(VAULT_REMOTE_PATH.format(vault="work"), json={"url": URL, "token": TOKEN})
    assert saved.status_code == 200, saved.text
    assert saved.json()["remote"] == {
        "url": URL,
        "branch": "main",
        "username": "x-access-token",
        "has_token": True,
    }
    assert TOKEN not in saved.text

    pushed = client.post(VAULT_REMOTE_PUSH_PATH.format(vault="work"))
    assert pushed.status_code == 200, pushed.text
    assert pushed.json()["commit"] == _git(vault_root, "rev-parse", "HEAD")
    assert pushed.json()["trigger"] == "manual"

    removed = client.delete(VAULT_REMOTE_PATH.format(vault="work"))
    assert removed.status_code == 200
    assert secrets.get(secret_name("work")) is None
    assert client.post(VAULT_REMOTE_PUSH_PATH.format(vault="work")).status_code == 404


def test_a_bad_url_is_a_422_with_the_fix(remotes: VaultRemotes) -> None:
    response = _client(remotes).put(
        VAULT_REMOTE_PATH.format(vault="work"),
        json={"url": "http://github.com/you/notes.git", "token": TOKEN},
    )
    assert response.status_code == 422
    assert "https://" in response.json()["detail"]


def test_a_refused_push_is_a_500_with_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, remotes: VaultRemotes
) -> None:
    # No bare repository behind the URL: the host cannot be reached.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "none"))
    client = _client(remotes)
    client.put(VAULT_REMOTE_PATH.format(vault="work"), json={"url": URL, "token": TOKEN})
    response = client.post(VAULT_REMOTE_PUSH_PATH.format(vault="work"))
    assert response.status_code == 500
    assert TOKEN not in response.text
    (listed,) = client.get(VAULT_REMOTES_PATH).json()["vaults"]
    assert listed["last_push"]["ok"] is False


def test_a_vault_being_pushed_answers_409(remotes: VaultRemotes) -> None:
    remotes.configure("work", url=URL, token=TOKEN)
    remotes._pushing.add("work")
    response = _client(remotes).post(VAULT_REMOTE_PUSH_PATH.format(vault="work"))
    assert response.status_code == 409


def test_every_route_refuses_on_a_hub_with_no_sign_in(remotes: VaultRemotes) -> None:
    client = _client(remotes, gated=False)
    for method, path in (
        ("GET", VAULT_REMOTES_PATH),
        ("PUT", VAULT_REMOTE_PATH.format(vault="work")),
        ("DELETE", VAULT_REMOTE_PATH.format(vault="work")),
        ("POST", VAULT_REMOTE_PUSH_PATH.format(vault="work")),
    ):
        body = {"url": URL, "token": TOKEN} if method == "PUT" else None
        response = client.request(method, path, json=body)
        assert response.status_code == 403, (method, path)
        assert response.json()["detail"] == UNGATED_VAULT_REMOTES_DETAIL
    assert remotes.get("work") is None


# ------------------------------------------------------------ schedule, wiring


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_a_scheduled_pass_pushes_every_configured_vault(
    tmp_path: Path, bare: Path, vault_root: Path, remotes: VaultRemotes
) -> None:
    remotes.configure("work", url=URL, token=TOKEN)
    ledger = BackupLedger(tmp_path / "home", {})
    scheduler = BackupScheduler(ledger, interval_seconds=3600, vault_remotes=remotes)
    assert await scheduler.run_pass() == {"vault:work": True}
    assert _git(bare, "rev-parse", "refs/heads/main") == _git(vault_root, "rev-parse", "HEAD")
    (listed,) = remotes.describe()
    assert listed["last_push"]["trigger"] == "schedule"


def test_create_app_mounts_the_routes_only_with_a_registry_and_a_secret_store(
    tmp_path: Path,
) -> None:
    home = tmp_path / "hub"
    home.mkdir()
    bare_app = create_app(HubConfig(), home=home)
    assert TestClient(bare_app).get(VAULT_REMOTES_PATH).status_code == 404

    store = SecretStore(home)
    try:
        app = create_app(
            HubConfig(),
            home=home,
            vault_registry=VaultRegistry(home / "vaults"),
            secret_store=store,
        )
        # Mounted, and refusing: this hub has no dashboard sign-in.
        response = TestClient(app).get(VAULT_REMOTES_PATH)
        assert response.status_code == 403
        assert response.json()["detail"] == UNGATED_VAULT_REMOTES_DETAIL
    finally:
        store.close()
