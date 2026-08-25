"""Issue #242 / SPEC-401 deliverable #5: `open` mode is accepted again — but
only on a hub the owner can actually sign in to.

The masterplan's mode table makes sign-in mandatory for a public dashboard.
Until SPEC-401 there was no dashboard sign-in at all, so both operator entry
points (`load_config` and `POST /api/mode`) refused the mode outright
(`test_open_mode_refused.py`, replaced by this file). Now the refusal is
conditional: it fires exactly when the hub has no way in.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import ConfigError, HubConfig, load_config
from palaia_hub.oauth import AuthorizationServer, OAuthStore, set_owner_password

ISSUER = "https://hub.example.test"


def _write_config(home: Path, body: str) -> None:
    (home / "config.yaml").write_text(body, encoding="utf-8")


def _open_mode_config(*, with_sign_in_server: bool) -> str:
    lines = ["mode: open", "host: 0.0.0.0", "auth_enabled: true"]
    if with_sign_in_server:
        lines += ["oauth:", "  enabled: true", f"  issuer: {ISSUER}"]
    return "\n".join(lines) + "\n"


def _create_owner(home: Path) -> None:
    store = OAuthStore(home)
    store.open()
    try:
        set_owner_password(store, "owner", "a-long-enough-passphrase", now=1_800_000_000)
    finally:
        store.close()


# ------------------------------------------------------------- load_config


def test_open_mode_is_refused_without_any_sign_in(tmp_path: Path) -> None:
    _write_config(tmp_path, _open_mode_config(with_sign_in_server=False))
    with pytest.raises(ConfigError, match="needs a way for you to sign in"):
        load_config(tmp_path)


def test_open_mode_is_refused_with_a_sign_in_server_but_no_account(tmp_path: Path) -> None:
    """The server alone is not a door: nobody can get through it yet."""
    _write_config(tmp_path, _open_mode_config(with_sign_in_server=True))
    with pytest.raises(ConfigError, match="needs a way for you to sign in"):
        load_config(tmp_path)


def test_open_mode_is_accepted_with_an_owner_account(tmp_path: Path) -> None:
    _create_owner(tmp_path)
    _write_config(tmp_path, _open_mode_config(with_sign_in_server=True))
    config = load_config(tmp_path)
    assert config.mode == "open"


def test_open_mode_is_accepted_with_a_sign_in_provider(tmp_path: Path) -> None:
    """A provider needs no local account — it *is* the account (SPEC-204)."""
    _write_config(
        tmp_path,
        "mode: open\nhost: 0.0.0.0\nauth_enabled: true\n"
        "oauth:\n"
        "  enabled: true\n"
        f"  issuer: {ISSUER}\n"
        "  idp:\n"
        "    provider: github\n"
        "    github:\n"
        "      client_id: abc\n"
        "      client_secret: shh\n"
        "      allowed_users: ['someone']\n",
    )
    config = load_config(tmp_path)
    assert config.mode == "open"


def test_open_mode_refuses_to_turn_the_gate_off(tmp_path: Path) -> None:
    _create_owner(tmp_path)
    _write_config(
        tmp_path,
        _open_mode_config(with_sign_in_server=True) + "dashboard:\n  require_sign_in: false\n",
    )
    with pytest.raises(ConfigError, match="cannot set `dashboard.require_sign_in: false`"):
        load_config(tmp_path)


def test_hub_config_itself_still_models_open_mode() -> None:
    config = HubConfig(mode="open", auth_enabled=True)
    assert config.mode == "open"


# ---------------------------------------------------------- POST /api/mode


def _oauth_server(home: Path, config: HubConfig) -> AuthorizationServer:
    return AuthorizationServer.build(config, {"default": ["vault:work:read"]}, home=home)


def test_mode_endpoint_refuses_open_without_a_sign_in(tmp_path: Path) -> None:
    app = create_app(HubConfig(), home=tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/mode", json={"mode": "open"})
    assert response.status_code == 400
    assert "needs a way for you to sign in" in response.json()["detail"]


def test_mode_endpoint_accepts_open_once_sign_in_exists(tmp_path: Path) -> None:
    """The whole change in one call: an owner account plus a sign-in server,
    and the wizard's 'fully public' option is available for the first time."""
    _create_owner(tmp_path)
    running = HubConfig(
        mode="locked",
        oauth={"enabled": True, "issuer": ISSUER},  # type: ignore[arg-type]
    )
    server = _oauth_server(tmp_path, running)
    try:
        app = create_app(running, home=tmp_path, oauth_server=server)
        with TestClient(app) as client:
            response = client.post(
                "/api/mode",
                json={
                    "mode": "open",
                    "host": "0.0.0.0",
                    "oauth_enabled": True,
                    "oauth_issuer": ISSUER,
                },
            )
        assert response.status_code == 200, response.text
        assert response.json()["configured_mode"] == "open"
        # And the config it wrote is loadable, which is the real proof: the
        # wizard never persists a file the hub would refuse to start from.
        assert load_config(tmp_path).mode == "open"
    finally:
        server.store.close()
