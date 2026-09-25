"""Golden-file tests for the tunnel guidance generators (SPEC-205 acceptance
criterion #3: "generated tunnel configs are syntactically valid").

Each generated config is checked two ways: it parses with the format's own
real parser (``json.loads``/``yaml.safe_load`` — syntactic validity), and it
matches a committed golden fixture byte-for-byte, so a change to the
generator's output is a deliberate, reviewed diff to
``server/tests/fixtures/exposure/*`` rather than a silent behavior change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from palaia_hub.modes.tunnel import (
    TELEGRAM_WEBHOOK_PATH_PREFIX,
    cloudflared_guidance,
    tailscale_guidance,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "exposure"


@pytest.mark.parametrize("mode", ["cloud", "open"])
def test_tailscale_config_is_valid_json_and_matches_golden(mode: str) -> None:
    guidance = tailscale_guidance(mode=mode, local_port=8420, hostname="myhub.tailnet.ts.net")

    parsed = json.loads(guidance.config)  # syntactic validity
    assert "Web" in parsed
    assert parsed["AllowFunnel"] == {"myhub.tailnet.ts.net:443": True}

    golden = (FIXTURES / f"tailscale-{mode}.json").read_text(encoding="utf-8")
    assert guidance.config == golden


@pytest.mark.parametrize("mode", ["cloud", "open"])
def test_cloudflared_config_is_valid_yaml_and_matches_golden(mode: str) -> None:
    guidance = cloudflared_guidance(mode=mode, local_port=8420, hostname="hub.example.com")

    parsed = yaml.safe_load(guidance.config)  # syntactic validity
    assert parsed["ingress"][-1] == {"service": "http_status:404"}

    golden = (FIXTURES / f"cloudflared-{mode}.yml").read_text(encoding="utf-8")
    assert guidance.config == golden


def test_cloud_mode_tailscale_config_never_forwards_the_dashboard_root() -> None:
    guidance = tailscale_guidance(mode="cloud", local_port=8420)

    handlers = json.loads(guidance.config)["Web"]["<your-tailnet-name>:443"]["Handlers"]
    assert "/" not in handlers
    assert set(handlers) == {"/mcp", "/oauth", "/.well-known"}


def test_open_mode_tailscale_config_forwards_everything() -> None:
    guidance = tailscale_guidance(mode="open", local_port=8420)

    handlers = json.loads(guidance.config)["Web"]["<your-tailnet-name>:443"]["Handlers"]
    assert set(handlers) == {"/"}


def test_cloud_mode_cloudflared_config_never_forwards_the_dashboard_root() -> None:
    guidance = cloudflared_guidance(mode="cloud", local_port=8420)

    rules = yaml.safe_load(guidance.config)["ingress"]
    paths = {rule["path"] for rule in rules if "path" in rule}
    assert paths == {"^/mcp", "^/oauth", "^/.well-known"}


def test_open_mode_cloudflared_config_has_no_path_restriction() -> None:
    guidance = cloudflared_guidance(mode="open", local_port=8420)

    rules = yaml.safe_load(guidance.config)["ingress"]
    assert all("path" not in rule for rule in rules)


def test_both_providers_note_what_they_expose_and_what_they_do_not() -> None:
    cloud_tailscale = tailscale_guidance(mode="cloud", local_port=8420)
    open_tailscale = tailscale_guidance(mode="open", local_port=8420)

    assert "only the MCP endpoint" in cloud_tailscale.note
    assert "including the dashboard" in open_tailscale.note


# ---------------------------------------- a Telegram webhook bot (issue #439)


def test_the_telegram_literal_matches_the_route_it_forwards() -> None:
    from palaia_hub.telegram.webhook import WEBHOOK_PREFIX

    assert TELEGRAM_WEBHOOK_PATH_PREFIX == WEBHOOK_PREFIX


def test_without_a_webhook_bot_the_output_is_exactly_the_golden_one() -> None:
    """The flag defaults off, and off is byte-for-byte what every hub got
    before a webhook bot existed."""
    for mode in ("cloud", "open"):
        assert tailscale_guidance(
            mode=mode, local_port=8420, hostname="myhub.tailnet.ts.net", telegram_webhook=False
        ).config == (FIXTURES / f"tailscale-{mode}.json").read_text(encoding="utf-8")
        assert cloudflared_guidance(
            mode=mode, local_port=8420, hostname="hub.example.com", telegram_webhook=False
        ).config == (FIXTURES / f"cloudflared-{mode}.yml").read_text(encoding="utf-8")


def test_cloud_mode_tailscale_forwards_the_telegram_webhook_when_asked() -> None:
    guidance = tailscale_guidance(mode="cloud", local_port=8420, telegram_webhook=True)

    handlers = json.loads(guidance.config)["Web"]["<your-tailnet-name>:443"]["Handlers"]
    assert set(handlers) == {"/mcp", "/oauth", "/.well-known", "/telegram/webhook"}
    assert "/" not in handlers  # the dashboard still stays off the internet
    assert handlers["/telegram/webhook"] == {"Proxy": "http://127.0.0.1:8420"}
    assert "Telegram webhook" in guidance.note
    assert "only the MCP endpoint" in guidance.note


def test_cloud_mode_cloudflared_forwards_the_telegram_webhook_when_asked() -> None:
    guidance = cloudflared_guidance(mode="cloud", local_port=8420, telegram_webhook=True)

    rules = yaml.safe_load(guidance.config)["ingress"]
    paths = {rule["path"] for rule in rules if "path" in rule}
    assert paths == {"^/mcp", "^/oauth", "^/.well-known", "^/telegram/webhook"}
    assert rules[-1] == {"service": "http_status:404"}
    assert "Telegram webhook" in guidance.note


def test_open_mode_ignores_the_flag_because_everything_is_forwarded_already() -> None:
    for flag in (False, True):
        tailscale = tailscale_guidance(mode="open", local_port=8420, telegram_webhook=flag)
        cloudflared = cloudflared_guidance(mode="open", local_port=8420, telegram_webhook=flag)
        handlers = json.loads(tailscale.config)["Web"]["<your-tailnet-name>:443"]["Handlers"]
        assert set(handlers) == {"/"}
        assert all("path" not in rule for rule in yaml.safe_load(cloudflared.config)["ingress"])
        assert "Telegram" not in tailscale.note
