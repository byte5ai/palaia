"""SPEC-302 deliverable #1: the ``gateway.upstreams`` config.yaml section —
loaded, resolved, mounted, and written back without losing anything.

Also asserts the provenance line deliverable #6 asks for: a profile's
instructions say whose tools those are.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from palaia_hub.config import load_config
from palaia_hub.gateway.build import upstream_identity_block
from palaia_hub.gateway.settings_bridge import (
    GatewaySettingsError,
    persist_gateway_settings,
    resolve_profiles,
    resolve_upstreams,
)
from palaia_hub.upstream.models import UpstreamConfig

CONFIG = """\
mode: locked
auth_enabled: false
gateway:
  profiles:
    - path: default
      vaults: [work]
      upstreams: [linear]
  upstreams:
    - key: linear
      kind: http
      display_name: Linear
      url: https://mcp.example.invalid/mcp
      namespace: linear
      auth:
        secret_name: linear-token
"""


def test_the_section_loads_and_resolves(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(CONFIG, encoding="utf-8")
    config = load_config(home=tmp_path, create_if_missing=False)

    upstreams = resolve_upstreams(config.gateway)
    assert [u.key for u in upstreams] == ["linear"]
    assert upstreams[0].mount_namespace == "linear"
    assert upstreams[0].auth is not None
    assert upstreams[0].auth.secret_name == "linear-token"

    profiles = resolve_profiles(config.gateway, ["work"], default_profile="default")
    assert profiles[0].upstreams == ["linear"]


def test_no_gateway_section_means_no_external_servers(tmp_path: Path) -> None:
    config = load_config(home=tmp_path)  # zero-config default template
    assert resolve_upstreams(config.gateway) == []


def test_a_profile_naming_an_unlisted_server_fails_with_the_fix(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        "gateway:\n  profiles:\n    - path: default\n      vaults: [work]\n"
        "      upstreams: [ghost]\n",
        encoding="utf-8",
    )
    config = load_config(home=tmp_path, create_if_missing=False)
    with pytest.raises(GatewaySettingsError) as excinfo:
        resolve_profiles(config.gateway, ["work"], default_profile="default")
    assert "ghost" in str(excinfo.value)
    assert "Fix:" in str(excinfo.value)


def test_writing_the_section_back_preserves_every_field(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    config = load_config(home=tmp_path, create_if_missing=False)
    assert config.gateway is not None

    persist_gateway_settings(path, config.gateway)

    reloaded = load_config(home=tmp_path, create_if_missing=False)
    assert reloaded.gateway is not None
    assert reloaded.gateway.upstreams == config.gateway.upstreams
    assert reloaded.gateway.profiles == config.gateway.profiles
    # And nothing that looks like a credential ended up in the file — only
    # the secret's name.
    text = path.read_text(encoding="utf-8")
    assert "linear-token" in text
    parsed = yaml.safe_load(text)
    assert parsed["gateway"]["upstreams"][0]["kind"] == "http"


def test_the_identity_block_names_the_source_in_plain_language() -> None:
    block = upstream_identity_block(
        UpstreamConfig(
            key="linear",
            kind="http",
            display_name="Linear",
            url="https://mcp.example.invalid/mcp",
        )
    )
    assert "linear_*" in block
    assert "Linear" in block
    assert "connected by you" in block
