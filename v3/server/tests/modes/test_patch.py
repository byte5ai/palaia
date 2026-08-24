from __future__ import annotations

from pathlib import Path

import yaml

from palaia_hub.config import load_config
from palaia_hub.modes.patch import patch_config_values


def test_top_level_key_is_replaced_in_place(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "# a comment that must survive\nmode: locked\nport: 8420\n", encoding="utf-8"
    )

    patch_config_values(path, {"mode": "cloud"})

    text = path.read_text(encoding="utf-8")
    assert "# a comment that must survive" in text
    assert "mode: cloud" in text
    assert "port: 8420" in text
    assert text.count("mode:") == 1


def test_top_level_key_is_appended_when_absent(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("port: 8420\n", encoding="utf-8")

    patch_config_values(path, {"mode": "open"})

    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert parsed["mode"] == "open"
    assert parsed["port"] == 8420


def test_nested_key_is_replaced_without_disturbing_the_section(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "oauth:\n"
        "  enabled: false\n"
        "  # a comment inside the section\n"
        "  access_token_ttl: 900\n"
        "mode: locked\n",
        encoding="utf-8",
    )

    patch_config_values(path, {"oauth.enabled": True, "oauth.issuer": "https://hub.example.com"})

    text = path.read_text(encoding="utf-8")
    assert "# a comment inside the section" in text
    parsed = yaml.safe_load(text)
    assert parsed["oauth"]["enabled"] is True
    assert parsed["oauth"]["issuer"] == "https://hub.example.com"
    assert parsed["oauth"]["access_token_ttl"] == 900
    assert parsed["mode"] == "locked"


def test_nested_section_is_created_when_absent(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("mode: locked\n", encoding="utf-8")

    patch_config_values(path, {"exposure.public_url": "https://hub.example.com"})

    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert parsed["exposure"]["public_url"] == "https://hub.example.com"


def test_patched_file_still_loads_through_the_real_config_loader(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("mode: locked\nauth_enabled: true\n", encoding="utf-8")

    patch_config_values(
        path,
        {
            "mode": "cloud",
            "oauth.enabled": True,
            "oauth.issuer": "https://hub.example.com",
            "auth_enabled": False,
        },
    )

    config = load_config(home=tmp_path, create_if_missing=False)
    assert config.mode == "cloud"
    assert config.auth_enabled is False
    assert config.oauth.enabled is True
    assert config.oauth.issuer == "https://hub.example.com"


def test_boolean_and_null_scalars_render_as_yaml_literals(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("mode: locked\n", encoding="utf-8")

    patch_config_values(path, {"auth_enabled": False, "exposure.tunnel": None})

    text = path.read_text(encoding="utf-8")
    assert "auth_enabled: false" in text
    parsed = yaml.safe_load(text)
    assert parsed["auth_enabled"] is False
    assert parsed["exposure"]["tunnel"] is None
