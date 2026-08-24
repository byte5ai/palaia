"""Tests for the SPEC-109 static dashboard serving + SPA fallback."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.static import WEB_DIST_ENV, _default_dist_dir, resolve_dist_dir


def test_default_dist_dir_points_at_v3_web_dist_not_v3_server_web_dist() -> None:
    """Regression test for a real bug (SPEC-110): every other test here
    sets ``PALAIA_WEB_DIST``, so the *unoverridden* default path was never
    checked and silently pointed one directory short (``v3/server/web/dist``
    instead of ``v3/web/dist``) — a zero-config ``palaia-hub serve`` would
    never find or serve the dashboard build at all.
    """
    default = _default_dist_dir()
    assert default.name == "dist"
    assert default.parent.name == "web"
    assert default.parent.parent.name == "v3"


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


def test_unregistered_api_path_404s_even_with_a_build_mounted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression test (SPEC-110): an opt-in endpoint whose backing store
    was never given to ``create_app()`` (no ``vault_registry``, no
    ``token_store``) has no route at all — before this fix, such a path
    still matched the SPA mount at "/" and silently got ``index.html``
    back with a 200, masking a disabled feature as if it were a page.
    """
    dist = _make_fake_build(tmp_path)
    monkeypatch.setenv(WEB_DIST_ENV, str(dist))
    app = create_app(HubConfig())
    client = TestClient(app)

    response = client.get("/api/vaults")

    assert response.status_code == 404
    assert "palaia" not in response.text


def test_unregistered_mcp_path_404s_even_with_a_build_mounted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Same regression, for the gateway's ``/mcp/*`` mount namespace when
    no gateway is given to ``create_app()`` at all."""
    dist = _make_fake_build(tmp_path)
    monkeypatch.setenv(WEB_DIST_ENV, str(dist))
    app = create_app(HubConfig())
    client = TestClient(app)

    response = client.get("/mcp/default/")

    assert response.status_code == 404
    assert "palaia" not in response.text


def test_unregistered_oauth_path_404s_even_with_a_build_mounted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Same regression, for the SPEC-203/204 authorization server's
    surface: no ``oauth_server`` given to ``create_app()`` means no
    ``/oauth/*`` route exists at all, so an unregistered one (or, with an
    IdP configured, the deliberately-absent ``/oauth/login``) must 404 —
    not silently come back as the dashboard shell with a 200, which would
    mask SPEC-204's "one door only" rule from ever actually taking effect
    on a hub that has run ``npm run build``.
    """
    dist = _make_fake_build(tmp_path)
    monkeypatch.setenv(WEB_DIST_ENV, str(dist))
    app = create_app(HubConfig())
    client = TestClient(app)

    response = client.get("/oauth/login")

    assert response.status_code == 404
    assert "palaia" not in response.text


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
