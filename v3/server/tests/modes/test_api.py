"""Integration tests for the exposure-wizard REST surface (SPEC-205)."""

from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.auth import TokenStore
from palaia_hub.config import HubConfig, config_file_path, load_config
from palaia_hub.events import Envelope, EventBus
from palaia_hub.modes.audit import ModeAuditLog


def _client(config: HubConfig, home: Path, **kwargs: object) -> TestClient:
    """Build a real app whose live config matches what is actually on disk.

    Writing ``config.yaml`` first and loading ``config`` back through
    :func:`load_config` (rather than handing ``create_app`` a config object
    that was never persisted) mirrors how the real hub always starts —
    every existing test above whose intent is to check *drift* between the
    live process and a change made after startup patches the file only
    after the client already exists.
    """
    path = config_file_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"mode: {config.mode}\n"
        f"host: {config.host}\n"
        f"auth_enabled: {'true' if config.auth_enabled else 'false'}\n",
        encoding="utf-8",
    )
    loaded = load_config(home=home, create_if_missing=False)
    app = create_app(loaded, home=home, **kwargs)  # type: ignore[arg-type]
    return TestClient(app)


# --------------------------------------------------------------- GET /api/mode


def test_get_mode_reports_the_live_and_on_disk_state(tmp_path: Path) -> None:
    client = _client(HubConfig(mode="locked"), tmp_path)

    response = client.get("/api/mode")

    assert response.status_code == 200
    body = response.json()
    assert body["active_mode"] == "locked"
    assert body["configured_mode"] == "locked"
    assert body["restart_required"] is False


# -------------------------------------------------------------- POST /api/mode


def test_post_mode_accepts_a_valid_change_and_persists_it(tmp_path: Path) -> None:
    client = _client(HubConfig(mode="locked", auth_enabled=True), tmp_path)

    response = client.post("/api/mode", json={"mode": "cloud"})

    assert response.status_code == 200
    body = response.json()
    assert body["active_mode"] == "locked"  # the running process did not change
    assert body["configured_mode"] == "cloud"
    assert body["restart_required"] is True

    on_disk = yaml.safe_load(config_file_path(tmp_path).read_text(encoding="utf-8"))
    assert on_disk["mode"] == "cloud"


def test_post_mode_refuses_cloud_with_no_auth_method_and_explains_the_fix(
    tmp_path: Path,
) -> None:
    client = _client(HubConfig(mode="locked", auth_enabled=True), tmp_path)

    response = client.post("/api/mode", json={"mode": "cloud", "auth_enabled": False})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "auth_enabled: true" in detail
    assert "oauth.enabled" in detail
    # A refusal must not have touched the file.
    on_disk = yaml.safe_load(config_file_path(tmp_path).read_text(encoding="utf-8"))
    assert on_disk["mode"] == "locked"


def test_a_refused_change_and_an_accepted_one_both_reach_the_audit_log(
    tmp_path: Path,
) -> None:
    client = _client(HubConfig(mode="locked", auth_enabled=True), tmp_path)

    client.post("/api/mode", json={"mode": "cloud", "auth_enabled": False})
    client.post("/api/mode", json={"mode": "cloud"})

    entries = ModeAuditLog(tmp_path).recent()
    assert len(entries) == 2
    accepted = [e for e in entries if e["accepted"]]
    refused = [e for e in entries if not e["accepted"]]
    assert len(accepted) == 1
    assert len(refused) == 1
    assert accepted[0]["to_mode"] == "cloud"
    assert "auth_enabled: true" in refused[0]["reason"]


def test_an_accepted_change_publishes_hub_mode_changed(tmp_path: Path) -> None:
    bus = EventBus()
    seen: list[Envelope] = []
    bus.on(seen.append)
    client = _client(HubConfig(mode="locked", auth_enabled=True), tmp_path, event_bus=bus)

    client.post("/api/mode", json={"mode": "cloud"})

    events = [e for e in seen if e.event == "hub.mode_changed"]
    assert len(events) == 1
    assert events[0].data["from_mode"] == "locked"
    assert events[0].data["to_mode"] == "cloud"
    assert events[0].data["restart_required"] is True


def test_a_refused_change_does_not_publish_an_event(tmp_path: Path) -> None:
    bus = EventBus()
    seen: list[Envelope] = []
    bus.on(seen.append)
    client = _client(HubConfig(mode="locked", auth_enabled=True), tmp_path, event_bus=bus)

    client.post("/api/mode", json={"mode": "cloud", "auth_enabled": False})

    assert not [e for e in seen if e.event == "hub.mode_changed"]


def test_changing_only_the_public_url_does_not_require_a_restart(tmp_path: Path) -> None:
    client = _client(HubConfig(mode="cloud", auth_enabled=True), tmp_path)

    response = client.post(
        "/api/mode", json={"public_url": "https://hub.example.com", "tunnel": "tailscale"}
    )

    assert response.status_code == 200
    assert response.json()["restart_required"] is False
    assert response.json()["public_url"] == "https://hub.example.com"


def test_comments_in_config_yaml_survive_a_mode_change(tmp_path: Path) -> None:
    client = _client(HubConfig(mode="locked", auth_enabled=True), tmp_path)
    # Simulate an operator's own hand-edited comment already in the file —
    # written after the client exists, same as the drift tests above, since
    # `_client` itself owns the file's initial content.
    path = tmp_path / "config.yaml"
    path.write_text("# my own note to self\nmode: locked\nauth_enabled: true\n", encoding="utf-8")

    client.post("/api/mode", json={"mode": "cloud"})

    assert "# my own note to self" in path.read_text(encoding="utf-8")


# ------------------------------------------------------------- GET /api/exposure


def test_get_exposure_includes_status_detection_and_checklist(tmp_path: Path) -> None:
    # Built directly (not via the persisted-config _client): `open` mode is
    # refused at load_config until the dashboard sign-in exists (issue
    # #242), but the exposure semantics stay implemented for the SPEC that
    # lifts that.
    from palaia_hub.app import create_app

    app = create_app(HubConfig(mode="open", auth_enabled=True), home=tmp_path)
    client = TestClient(app)

    response = client.get("/api/exposure")

    assert response.status_code == 200
    body = response.json()
    assert body["status"]["active_mode"] == "open"
    assert set(body["detected"]) == {"tailscale", "cloudflared"}
    ids = {item["id"] for item in body["checklist"]}
    assert "dashboard_exposure_acknowledged" in ids
    assert "rate_limited" in ids


def test_exposure_checklist_reflects_rate_limiting_being_active_in_open_mode(
    tmp_path: Path,
) -> None:
    # Direct construction — see the previous test's comment (issue #242).
    from palaia_hub.app import create_app

    client = TestClient(create_app(HubConfig(mode="open", auth_enabled=True), home=tmp_path))

    body = client.get("/api/exposure").json()

    rate_item = next(i for i in body["checklist"] if i["id"] == "rate_limited")
    assert rate_item["passed"] is True


def test_exposure_checklist_reflects_rate_limiting_being_inactive_in_locked_mode(
    tmp_path: Path,
) -> None:
    client = _client(HubConfig(mode="locked", auth_enabled=True), tmp_path)

    body = client.get("/api/exposure").json()

    rate_item = next(i for i in body["checklist"] if i["id"] == "rate_limited")
    assert rate_item["passed"] is False


# --------------------------------------------------------- POST /api/exposure/tunnel


def test_tunnel_guidance_scopes_to_mcp_and_oauth_paths_in_cloud_mode(tmp_path: Path) -> None:
    client = _client(HubConfig(mode="cloud", auth_enabled=True), tmp_path)

    response = client.post(
        "/api/exposure/tunnel",
        json={"kind": "cloudflared", "hostname": "hub.example.com"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "/mcp" in body["config"]
    assert "/oauth" in body["config"]
    assert "only the MCP endpoint" in body["note"]


def test_tunnel_guidance_forwards_everything_in_open_mode() -> None:
    # Unit-level rather than through a persisted hub: `open` mode is refused
    # at the operator entry points until the dashboard sign-in exists
    # (issue #242, test_open_mode_refused.py), but the guidance semantics
    # stay implemented for the SPEC that lifts that.
    from palaia_hub.modes.tunnel import tailscale_guidance

    guidance = tailscale_guidance(mode="open", local_port=8420)

    assert "including the dashboard" in guidance.note


# ------------------------------------------------------- POST /api/exposure/selftest


def test_selftest_against_an_unreachable_url_reports_unreachable_honestly(
    tmp_path: Path,
) -> None:
    client = _client(HubConfig(mode="cloud", auth_enabled=True), tmp_path)

    # Port 0 is never a live listener; this stays entirely on loopback, no
    # real network or DNS dependency, and fails fast and deterministically.
    response = client.post(
        "/api/exposure/selftest", json={"public_url": "http://127.0.0.1:1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is False
    assert body["error"] != ""


# -------------------------------------------------------------- rate limiting


def test_auth_endpoints_are_rate_limited_in_cloud_mode(tmp_path: Path) -> None:
    token_store = TokenStore(tmp_path)
    client = _client(
        HubConfig(mode="cloud", auth_enabled=True), tmp_path, token_store=token_store
    )

    statuses = [client.post("/api/auth/tokens", json={}).status_code for _ in range(15)]

    assert 422 in statuses  # missing required fields -> a validation failure
    assert 429 in statuses  # and repeated failures eventually get throttled


def test_auth_endpoints_are_not_rate_limited_in_locked_mode(tmp_path: Path) -> None:
    token_store = TokenStore(tmp_path)
    client = _client(
        HubConfig(mode="locked", auth_enabled=True), tmp_path, token_store=token_store
    )

    statuses = [client.post("/api/auth/tokens", json={}).status_code for _ in range(15)]

    assert statuses == [422] * 15
