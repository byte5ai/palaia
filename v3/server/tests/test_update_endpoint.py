"""SPEC-501 acceptance, end to end through the real REST surface:
"mocked GHCR answers drive 'up to date'/'update available'/'cannot check'
states end-to-end into the dashboard banner" and "a beta-channel hub
checks beta, stable checks stable" — this is the "into the dashboard
banner" half; ``test_update.py`` covers the check function's own states.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import palaia_hub.app as app_module
from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.update import UpdateCheckResult, UpdateGuidance


def _fake_check_for_update(seen_channels: list[str], result: UpdateCheckResult):
    async def _check(*, channel, current_version, deployment):  # noqa: ANN001
        seen_channels.append(channel)
        return result

    return _check


def test_update_available_reaches_the_rest_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    result = UpdateCheckResult(
        state="update_available",
        channel="stable",
        current_version="0.1.0",
        latest_version="0.2.0",
        checked_at=123.0,
        deployment="compose",
        guidance=UpdateGuidance(
            kind="command",
            message="Run the update helper, then restart:",
            commands=("palaia-hub update", "docker compose pull", "docker compose up -d"),
        ),
    )
    monkeypatch.setattr(app_module, "check_for_update", _fake_check_for_update(seen, result))

    app = create_app(HubConfig(channel="stable"))
    response = TestClient(app).get("/api/update/check")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "update_available"
    assert body["latest_version"] == "0.2.0"
    assert body["guidance"]["commands"] == [
        "palaia-hub update",
        "docker compose pull",
        "docker compose up -d",
    ]
    assert seen == ["stable"]


def test_a_beta_channel_hub_checks_beta_a_stable_hub_checks_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for channel in ("stable", "beta"):
        seen: list[str] = []
        result = UpdateCheckResult(
            state="up_to_date",
            channel=channel,  # type: ignore[arg-type]
            current_version="0.1.0",
            latest_version="0.1.0",
            checked_at=1.0,
            deployment="unknown",
            guidance=UpdateGuidance(kind="manual", message="pull it yourself"),
        )
        monkeypatch.setattr(
            app_module, "check_for_update", _fake_check_for_update(seen, result)
        )

        app = create_app(HubConfig(channel=channel))  # type: ignore[arg-type]
        response = TestClient(app).get("/api/update/check")

        assert response.status_code == 200
        assert response.json()["channel"] == channel
        assert seen == [channel]


def test_cannot_check_is_a_200_state_not_an_error_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    result = UpdateCheckResult(
        state="cannot_check",
        channel="stable",
        current_version="0.1.0",
        latest_version=None,
        checked_at=1.0,
        deployment="unknown",
        guidance=UpdateGuidance(kind="manual", message="pull it yourself"),
        reason="network error: no route to host",
    )
    monkeypatch.setattr(app_module, "check_for_update", _fake_check_for_update(seen, result))

    app = create_app(HubConfig(channel="stable"))
    response = TestClient(app).get("/api/update/check")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "cannot_check"
    assert body["latest_version"] is None
    assert "network error" in body["reason"]
