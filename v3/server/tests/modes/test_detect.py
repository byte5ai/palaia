from __future__ import annotations

import pytest

from palaia_hub.modes.detect import detect_tunnels


def test_detects_a_binary_that_is_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "palaia_hub.modes.detect.shutil.which",
        lambda name: "/usr/bin/tailscale" if name == "tailscale" else None,
    )

    detection = detect_tunnels()

    assert detection.tailscale is True
    assert detection.cloudflared is False


def test_neither_binary_present_is_reported_honestly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("palaia_hub.modes.detect.shutil.which", lambda name: None)

    detection = detect_tunnels()

    assert detection.tailscale is False
    assert detection.cloudflared is False
