"""Issue #396: the `oauth.profiles` deprecation reaches the operator's log."""

from __future__ import annotations

import logging

import pytest

from palaia_hub.config import OAuthSettings


def test_deprecated_oauth_profiles_is_logged_not_only_warned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="palaia_hub.config"):
        with pytest.warns(DeprecationWarning, match="oauth.profiles"):
            OAuthSettings(profiles=["default"])
    assert any("oauth.profiles" in record.getMessage() for record in caplog.records)
