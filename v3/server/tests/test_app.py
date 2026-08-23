from fastapi.testclient import TestClient

from palaia_hub import __version__
from palaia_hub.app import create_app
from palaia_hub.config import HubConfig


def test_health_is_ok_with_zero_config() -> None:
    app = create_app(HubConfig())
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "components" in body


def test_info_reports_single_source_version_and_mode() -> None:
    app = create_app(HubConfig(mode="cloud"))
    client = TestClient(app)

    response = client.get("/api/info")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == __version__
    assert body["mode"] == "cloud"
    assert body["uptime_seconds"] >= 0


def test_test_slow_route_is_absent_by_default() -> None:
    app = create_app(HubConfig())
    client = TestClient(app)

    response = client.get("/api/_test/slow")

    assert response.status_code == 404
