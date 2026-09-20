"""The `config.yaml` example in ``v3/docs/telegram.md`` must actually load.

A documented example that stopped parsing three refactors ago is worse than
no example: an operator pastes it, the hub refuses to start, and the fault
looks like theirs. This test reads the two YAML blocks out of §3 of the doc
and runs them through the real :class:`palaia_hub.config.HubConfig` — the
same validation a hub does at startup, including the cross-reference check
that would catch a route pointing at a bot the example forgot to declare.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from palaia_hub.config import HubConfig

DOC = Path(__file__).resolve().parents[3] / "docs" / "telegram.md"

_YAML_BLOCK = re.compile(r"```yaml\n(.*?)```", re.DOTALL)


@pytest.fixture(scope="module")
def blocks() -> list[dict]:
    assert DOC.is_file(), f"{DOC} is missing — the connector's documentation"
    found = [yaml.safe_load(block) for block in _YAML_BLOCK.findall(DOC.read_text())]
    assert found, "docs/telegram.md has no yaml example to check"
    return [block for block in found if isinstance(block, dict)]


def test_every_yaml_example_in_the_doc_loads_as_hub_config(blocks: list[dict]) -> None:
    for block in blocks:
        HubConfig.model_validate(block)


def test_the_documented_telegram_section_is_the_one_the_code_reads(
    blocks: list[dict],
) -> None:
    telegram = next(block["telegram"] for block in blocks if "telegram" in block)
    config = HubConfig.model_validate({"telegram": telegram})
    assert config.telegram is not None
    # The doc promises two bots, both transports' default, and a grant.
    assert {bot.key for bot in config.telegram.bots} == {"support", "personal"}
    assert config.telegram.grant("default") is not None
    # And one route per destination kind, which is what makes it an example.
    assert {route.destination.kind for route in config.telegram.routes} == {
        "messenger",
        "inbox",
        "event",
    }


def test_the_documented_profile_flag_is_the_one_the_gateway_reads(
    blocks: list[dict],
) -> None:
    gateway = next(block["gateway"] for block in blocks if "gateway" in block)
    config = HubConfig.model_validate({"gateway": gateway})
    assert config.gateway is not None
    assert any(profile.telegram for profile in config.gateway.profiles)
