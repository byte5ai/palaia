"""``/api/setup`` and ``/api/hub/restart`` (issues #559, #561).

The wizard's progress comes from the hub's real state, so these tests set
that state up for real — a vault on disk, an owner in the sign-in store, a
sign-in server built without a later vault — and read the answer back.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.oauth import AuthorizationServer, OAuthStore, set_owner_password
from palaia_hub.startup import PROBLEMS, report_problem
from palaia_hub.vault import VaultRegistry

ISSUER = "https://hub.example.test"


def _client(home: Path, config: HubConfig | None = None, **kwargs: object) -> TestClient:
    return TestClient(
        create_app(config or HubConfig(), home=home, vault_registry=VaultRegistry(home), **kwargs)  # type: ignore[arg-type]
    )


def _vault(home: Path, key: str = "work") -> None:
    asyncio.run(VaultRegistry(home).create(key, path=home / "vaults" / key))


def test_a_fresh_hub_has_setup_ahead_of_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALAIA_SELF_RESTART", raising=False)
    monkeypatch.delenv("PALAIA_CLOUD_URL_HINT", raising=False)
    body = _client(tmp_path).get("/api/setup").json()
    assert body["completed"] is False
    assert body["goal"] is None
    assert body["owner_configured"] is False
    assert body["vaults"] == []
    assert body["profiles"] == []
    assert body["sign_in_active"] is False
    assert body["restart_required"] is False
    assert body["restart_supported"] is False
    assert body["cloud_ready"] is False
    assert body["cloud_url_hint"] is None


def test_a_hub_installed_before_setup_json_existed_counts_as_set_up(tmp_path: Path) -> None:
    """Updating must never send an existing owner back into the wizard."""
    _vault(tmp_path)
    body = _client(tmp_path).get("/api/setup").json()
    assert body["completed"] is True
    assert body["vaults"] == ["work"]
    assert body["profiles"] == ["default"]


def test_goal_and_completion_survive_a_new_app(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert client.put("/api/setup", json={"goal": "cloud"}).json()["goal"] == "cloud"
    _vault(tmp_path)
    # A new process, as after a restart: the choice is read back, and an
    # unfinished setup stays unfinished although a vault now exists.
    body = _client(tmp_path).get("/api/setup").json()
    assert body["goal"] == "cloud"
    assert body["completed"] is False
    assert _client(tmp_path).put("/api/setup", json={"completed": True}).json()["completed"]
    assert json.loads((tmp_path / "setup.json").read_text()) == {"goal": "cloud", "completed": True}
    assert (tmp_path / "setup.json").stat().st_mode & 0o077 == 0


def test_an_unknown_goal_is_refused(tmp_path: Path) -> None:
    assert _client(tmp_path).put("/api/setup", json={"goal": "everything"}).status_code == 422


def test_the_owner_account_counts_without_a_running_sign_in_server(tmp_path: Path) -> None:
    store = OAuthStore(tmp_path)
    store.open()
    try:
        set_owner_password(store, "owner", "a-long-enough-passphrase", now=1_800_000_000)
    finally:
        store.close()
    assert _client(tmp_path).get("/api/setup").json()["owner_configured"] is True


def test_a_vault_created_after_sign_in_started_needs_a_restart(tmp_path: Path) -> None:
    """The sign-in server's grantable scopes are fixed when it starts."""
    config = HubConfig(oauth={"enabled": True, "issuer": ISSUER})  # type: ignore[arg-type]
    (tmp_path / "config.yaml").write_text(
        f"oauth:\n  enabled: true\n  issuer: {ISSUER}\n", encoding="utf-8"
    )
    server = AuthorizationServer.build(config, {}, home=tmp_path)
    try:
        _vault(tmp_path)
        body = _client(tmp_path, config, oauth_server=server).get("/api/setup").json()
    finally:
        server.store.close()
    assert body["sign_in_active"] is True
    assert body["issuer"] == ISSUER
    assert body["restart_required"] is True


def test_cloud_ready_needs_cloud_mode_https_sign_in_an_owner_and_a_profile(
    tmp_path: Path,
) -> None:
    _vault(tmp_path)
    store = OAuthStore(tmp_path)
    store.open()
    set_owner_password(store, "owner", "a-long-enough-passphrase", now=1_800_000_000)
    store.close()
    # The dashboard's sign-in gate is off here only so this test can read the
    # status without a browser session; with it on, /api/setup needs one.
    config = HubConfig(
        mode="cloud",
        host="127.0.0.1",
        oauth={"enabled": True, "issuer": ISSUER},  # type: ignore[arg-type]
        dashboard={"require_sign_in": False},  # type: ignore[arg-type]
    )
    (tmp_path / "config.yaml").write_text(
        f"mode: cloud\nhost: 127.0.0.1\noauth:\n  enabled: true\n  issuer: {ISSUER}\n"
        "dashboard:\n  require_sign_in: false\n",
        encoding="utf-8",
    )
    server = AuthorizationServer.build(
        config, {"default": ["vault:work:read", "vault:work:write"]}, home=tmp_path
    )
    try:
        body = _client(tmp_path, config, oauth_server=server).get("/api/setup").json()
    finally:
        server.store.close()
    assert body["cloud_ready"] is True
    assert body["restart_required"] is False


def test_hints_and_start_up_problems_are_passed_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PALAIA_CLOUD_URL_HINT", "https://palaia-hub.tail1234.ts.net")
    report_problem("Sign-in did not start. Fix: create your first memory, then restart the hub.")
    try:
        body = _client(tmp_path).get("/api/setup").json()
    finally:
        PROBLEMS.clear()
    assert body["cloud_url_hint"] == "https://palaia-hub.tail1234.ts.net"
    assert body["problems"] == [
        "Sign-in did not start. Fix: create your first memory, then restart the hub."
    ]


def test_restart_is_refused_where_nothing_would_start_the_hub_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PALAIA_SELF_RESTART", raising=False)
    response = _client(tmp_path).post("/api/hub/restart", json={})
    assert response.status_code == 409
    assert "docker restart" in response.json()["detail"]


def test_restart_ends_the_process_gracefully_when_a_supervisor_restarts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PALAIA_SELF_RESTART", "1")
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append((pid, sig)))
    with _client(tmp_path) as client:
        # As the dashboard sends it (`restartHub` in web/src/lib/api/client.ts).
        response = client.post(
            "/api/hub/restart", json={}, headers={"sec-fetch-site": "same-origin"}
        )
        assert response.status_code == 202
        assert response.json() == {"restarting": True}
        assert client.get("/api/setup").json()["restart_supported"] is True
        # The signal is sent a moment later, after the answer went out.
        deadline = asyncio.run(asyncio.sleep(0.8, result=True))
        assert deadline
    assert sent == [(os.getpid(), signal.SIGTERM)]


@pytest.mark.parametrize(
    ("kwargs", "headers", "status"),
    [
        # What a plain form or a no-cors fetch on another site can send.
        ({"data": {"x": "1"}}, {"origin": "https://evil.example"}, 415),
        ({"content": b"{}"}, {"content-type": "text/plain"}, 415),
        ({}, {}, 415),
        # A browser that says the request came from another site.
        ({"json": {}}, {"sec-fetch-site": "cross-site"}, 403),
        ({"json": {}}, {"sec-fetch-site": "same-site"}, 403),
    ],
)
def test_restart_refuses_what_another_sites_page_can_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, object],
    headers: dict[str, str],
    status: int,
) -> None:
    """A locked-mode hub has no admin session gate, so the hub must refuse a
    cross-site request that a browser sends without asking — since issue
    #587 by the rule every change under `/api/*` passes (the walk in
    `tests/security/test_cross_site_requests.py`)."""
    monkeypatch.setenv("PALAIA_SELF_RESTART", "1")
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append((pid, sig)))
    with _client(tmp_path) as client:
        response = client.post("/api/hub/restart", headers=headers, **kwargs)  # type: ignore[arg-type]
        assert response.status_code == status
        asyncio.run(asyncio.sleep(0.8))
    assert sent == []


def test_skipped_steps_are_remembered(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        body = client.put("/api/setup", json={"skipped": ["account", "account"]}).json()
        assert body["skipped"] == ["account"]
    assert _client(tmp_path).get("/api/setup").json()["skipped"] == ["account"]
    assert _client(tmp_path).put("/api/setup", json={"skipped": ["nope"]}).status_code == 422


def test_cloud_access_counts_as_verified_only_after_a_passing_self_test(tmp_path: Path) -> None:
    from palaia_hub.setup_api import record_cloud_check

    (tmp_path / "config.yaml").write_text(f"exposure:\n  public_url: {ISSUER}\n", encoding="utf-8")
    assert _client(tmp_path).get("/api/setup").json()["cloud_verified"] is False
    record_cloud_check(tmp_path, ISSUER + "/", False)
    assert _client(tmp_path).get("/api/setup").json()["cloud_verified"] is False
    record_cloud_check(tmp_path, ISSUER, True)
    assert _client(tmp_path).get("/api/setup").json()["cloud_verified"] is True
    # A check of another address says nothing about this one.
    record_cloud_check(tmp_path, "https://elsewhere.example", True)
    assert _client(tmp_path).get("/api/setup").json()["cloud_verified"] is False


def test_the_self_test_endpoint_records_its_result(tmp_path: Path) -> None:
    client = _client(tmp_path)
    body = client.post("/api/exposure/selftest", json={"public_url": "http://127.0.0.1:1"}).json()
    assert body["reachable"] is False
    stored = json.loads((tmp_path / "setup.json").read_text())
    assert stored["cloud_check"] == {"url": "http://127.0.0.1:1", "passed": False}


def test_a_self_test_keeps_an_installed_hub_set_up(tmp_path: Path) -> None:
    """A hub from before setup.json existed counts as set up; the self-test
    that first creates the file must not turn that into "not set up" and
    send the owner back into the wizard — whatever the test found."""
    _vault(tmp_path)
    client = _client(tmp_path)
    assert client.get("/api/setup").json()["completed"] is True
    client.post("/api/exposure/selftest", json={"public_url": "http://127.0.0.1:1"})
    assert (tmp_path / "setup.json").exists()
    assert client.get("/api/setup").json()["completed"] is True


def test_a_fresh_hub_stays_ahead_of_setup_after_a_self_test(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/exposure/selftest", json={"public_url": "http://127.0.0.1:1"})
    assert client.get("/api/setup").json()["completed"] is False


def test_a_choice_and_a_self_test_at_the_same_time_both_stay_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two tabs: one stores the goal while the other's self-test result comes
    in. The goal's write is held up between reading and writing the file;
    the self-test result must not be lost when it goes through."""
    from palaia_hub import setup_api

    write = setup_api._write_choices
    calls = 0
    goal_read = threading.Event()
    check_stored = threading.Event()

    def slow_first_write(home: Path, choices: dict[str, object]) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            goal_read.set()
            # Without one lock the self-test writes in this gap; with it, it
            # waits for this write and the wait here simply runs out.
            check_stored.wait(timeout=1.0)
        write(home, choices)

    monkeypatch.setattr(setup_api, "_write_choices", slow_first_write)

    def self_test_result() -> None:
        goal_read.wait(timeout=5.0)
        setup_api.record_cloud_check(tmp_path, ISSUER, True)
        check_stored.set()

    other_tab = threading.Thread(target=self_test_result)
    other_tab.start()
    assert _client(tmp_path).put("/api/setup", json={"goal": "cloud"}).status_code == 200
    other_tab.join(timeout=5.0)

    stored = json.loads((tmp_path / "setup.json").read_text())
    assert stored["goal"] == "cloud"
    assert stored["cloud_check"] == {"url": ISSUER, "passed": True}
