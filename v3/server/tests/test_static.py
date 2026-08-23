"""Tests for the SPEC-109 static dashboard serving + SPA fallback."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.static import WEB_DIST_ENV, resolve_dist_dir


def _make_fake_build(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        "<!doctype html><title>palaia</title><div id='root'></div>", encoding="utf-8"
    )
    assets = dist / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    return dist


def test_no_build_means_no_mount_and_no_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(WEB_DIST_ENV, str(tmp_path / "does-not-exist"))
    app = create_app(HubConfig())
    client = TestClient(app)

    assert resolve_dist_dir() is None
    # /api/health still works — a missing frontend build never breaks the API.
    assert client.get("/api/health").status_code == 200
    # And a random path 404s rather than being served by anything.
    assert client.get("/some/deep/link").status_code == 404


def test_build_present_serves_index_and_assets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dist = _make_fake_build(tmp_path)
    monkeypatch.setenv(WEB_DIST_ENV, str(dist))
    app = create_app(HubConfig())
    client = TestClient(app)

    root = client.get("/")
    assert root.status_code == 200
    assert "palaia" in root.text

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "console.log" in asset.text


def test_deep_link_falls_back_to_index_html(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dist = _make_fake_build(tmp_path)
    monkeypatch.setenv(WEB_DIST_ENV, str(dist))
    app = create_app(HubConfig())
    client = TestClient(app)

    response = client.get("/explorer/some-note-id")

    assert response.status_code == 200
    assert "palaia" in response.text


def test_api_routes_are_never_shadowed_by_the_spa_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dist = _make_fake_build(tmp_path)
    monkeypatch.setenv(WEB_DIST_ENV, str(dist))
    app = create_app(HubConfig())
    client = TestClient(app)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.headers["content-type"].startswith("application/json")
    assert health.json()["status"] == "ok"
