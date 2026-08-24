"""Issue #242: `open` mode is refused at both operator entry points until
the dashboard's own sign-in exists (the masterplan mode table makes that
sign-in mandatory for a public dashboard). HubConfig itself still accepts
mode="open" so the mode's internal semantics stay implemented and tested."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import ConfigError, HubConfig, load_config


def test_load_config_refuses_open_mode(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        "mode: open\nhost: 0.0.0.0\nauth_enabled: true\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="not available yet"):
        load_config(tmp_path)


def test_mode_endpoint_refuses_open_mode(tmp_path: Path) -> None:
    app = create_app(HubConfig(), home=tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/mode", json={"mode": "open"})
    assert response.status_code == 400
    assert "isn't available yet" in response.json()["detail"]


def test_hub_config_itself_still_models_open_mode() -> None:
    config = HubConfig(mode="open", auth_enabled=True)
    assert config.mode == "open"
