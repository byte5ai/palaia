from __future__ import annotations

import pytest

from palaia_hub.config import HubConfig
from palaia_hub.modes.policy import ModeChangeError, build_candidate_config


def test_a_bare_mode_change_within_the_same_auth_posture_is_accepted() -> None:
    current = HubConfig(mode="locked")

    candidate = build_candidate_config(current, {"mode": "locked"})

    assert candidate.mode == "locked"


def test_cloud_without_any_auth_method_is_refused_with_a_fix() -> None:
    current = HubConfig(mode="locked", auth_enabled=True)

    with pytest.raises(ModeChangeError) as excinfo:
        build_candidate_config(current, {"mode": "cloud", "auth_enabled": False})

    message = str(excinfo.value)
    assert "auth_enabled: true" in message
    assert "oauth.enabled" in message


def test_cloud_with_per_client_tokens_is_accepted() -> None:
    current = HubConfig(mode="locked", auth_enabled=True)

    candidate = build_candidate_config(current, {"mode": "cloud"})

    assert candidate.mode == "cloud"
    assert candidate.auth_enabled is True


def test_cloud_with_oauth_but_no_issuer_is_refused_with_a_fix() -> None:
    current = HubConfig(mode="locked")

    with pytest.raises(ModeChangeError) as excinfo:
        build_candidate_config(
            current, {"mode": "cloud", "auth_enabled": False, "oauth": {"enabled": True}}
        )

    assert "oauth.issuer" in str(excinfo.value)


def test_cloud_with_oauth_and_issuer_is_accepted() -> None:
    current = HubConfig(mode="locked")

    candidate = build_candidate_config(
        current,
        {
            "mode": "cloud",
            "auth_enabled": False,
            "oauth": {"enabled": True, "issuer": "https://hub.example.com"},
        },
    )

    assert candidate.mode == "cloud"
    assert candidate.oauth.issuer == "https://hub.example.com"


def test_cloud_with_a_public_bind_address_is_refused() -> None:
    current = HubConfig(mode="locked")

    with pytest.raises(ModeChangeError) as excinfo:
        build_candidate_config(current, {"mode": "cloud", "host": "0.0.0.0"})

    assert "private/VPN bind address" in str(excinfo.value)


def test_open_mode_accepts_a_public_bind_address() -> None:
    current = HubConfig(mode="locked")

    candidate = build_candidate_config(current, {"mode": "open", "host": "0.0.0.0"})

    assert candidate.mode == "open"
    assert candidate.host == "0.0.0.0"


def test_a_non_https_public_url_is_refused() -> None:
    current = HubConfig(mode="cloud")

    with pytest.raises(ModeChangeError) as excinfo:
        build_candidate_config(current, {"exposure": {"public_url": "http://hub.example.com"}})

    assert "https://" in str(excinfo.value)


def test_an_https_public_url_is_accepted() -> None:
    current = HubConfig(mode="cloud")

    candidate = build_candidate_config(
        current, {"exposure": {"public_url": "https://hub.example.com"}}
    )

    assert candidate.exposure.public_url == "https://hub.example.com"


def test_untouched_settings_carry_over_from_current() -> None:
    current = HubConfig(mode="locked", port=9999, log_level="debug")

    candidate = build_candidate_config(current, {"mode": "cloud"})

    assert candidate.port == 9999
    assert candidate.log_level == "debug"
