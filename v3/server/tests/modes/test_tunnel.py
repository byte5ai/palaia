"""Golden-file tests for the tunnel guidance (SPEC-205 criterion #3, issue #567).

The guidance points a tunnel at a port the shipped deployment really
publishes on the server: the cloud entry (``127.0.0.1:8422``) in Cloud mode,
the whole hub in Open mode. The boundary between the AI connection and the
dashboard lives in the cloud entry itself (``deploy/nginx.conf.template`` and
:mod:`palaia_hub.modes.cloud_entry`), so the tunnel configuration carries no
path list that could leave a route out or let one too many through.

The cloudflared config parses with the real YAML parser and matches a
committed golden fixture byte for byte, so a change to it is a reviewed diff
to ``server/tests/fixtures/exposure/*``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from palaia_hub.modes.tunnel import (
    DEFAULT_CLOUD_HOST_PORT,
    cloudflared_guidance,
    default_local_port,
    tailscale_guidance,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "exposure"


@pytest.mark.parametrize("mode", ["cloud", "open"])
def test_cloudflared_config_is_valid_yaml_and_matches_golden(mode: str) -> None:
    port = 8422 if mode == "cloud" else 8420
    guidance = cloudflared_guidance(mode=mode, local_port=port, hostname="hub.example.com")

    parsed = yaml.safe_load(guidance.config)  # syntactic validity
    assert parsed["ingress"][0] == {
        "hostname": "hub.example.com",
        "service": f"http://127.0.0.1:{port}",
    }
    assert parsed["ingress"][-1] == {"service": "http_status:404"}

    golden = (FIXTURES / f"cloudflared-{mode}.yml").read_text(encoding="utf-8")
    assert guidance.config == golden


@pytest.mark.parametrize("mode", ["cloud", "open"])
def test_tailscale_guidance_is_one_funnel_command_to_loopback(mode: str) -> None:
    """Funnel proxies only to localhost; the installer publishes both doors there."""
    port = 8422 if mode == "cloud" else 8420
    guidance = tailscale_guidance(mode=mode, local_port=port, hostname="hub.tail1234.ts.net")

    assert guidance.config == ""
    assert guidance.commands == (f"sudo tailscale funnel --bg http://127.0.0.1:{port}",)
    assert "https://hub.tail1234.ts.net/" in guidance.note


def test_cloud_guidance_says_the_dashboard_stays_private() -> None:
    for guidance in (
        tailscale_guidance(mode="cloud", local_port=8422),
        cloudflared_guidance(mode="cloud", local_port=8422),
    ):
        assert "only palaia's AI connection" in guidance.note
        assert "including the dashboard" not in guidance.note


def test_open_guidance_says_the_dashboard_is_public() -> None:
    assert "including the dashboard" in tailscale_guidance(mode="open", local_port=8420).note


def test_the_default_ports_follow_what_the_installer_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PALAIA_CLOUD_HOST_PORT", raising=False)
    monkeypatch.delenv("PALAIA_HUB_HOST_PORT", raising=False)
    assert default_local_port("cloud") == DEFAULT_CLOUD_HOST_PORT == 8422
    assert default_local_port("open") == 8420
    monkeypatch.setenv("PALAIA_CLOUD_HOST_PORT", "9422")
    monkeypatch.setenv("PALAIA_HUB_HOST_PORT", "9420")
    assert default_local_port("cloud") == 9422
    assert default_local_port("open") == 9420
