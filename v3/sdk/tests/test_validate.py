from __future__ import annotations

import json
from pathlib import Path

import pytest

from palaia_addon_sdk.validate import validate_manifest

GOOD_MANIFEST = {
    "id": "example.fetch",
    "name": "Fetch",
    "one_liner": "Fetch and convert web pages to text for an agent to read.",
    "kind": "container",
    "source": {"type": "image", "value": "ghcr.io/example/fetch:1.0.0"},
    "config_schema": {
        "type": "object",
        "properties": {
            "user_agent": {"title": "User agent string", "type": "string"},
        },
    },
    "permissions": ["network"],
    "maintainer": "example",
}


def _write(tmp_path: Path, manifest: dict) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_good_manifest_validates_clean(tmp_path: Path) -> None:
    _write(tmp_path, GOOD_MANIFEST)
    assert validate_manifest(tmp_path) == []


def test_missing_manifest_is_reported(tmp_path: Path) -> None:
    issues = validate_manifest(tmp_path)
    assert any("no manifest.json found" in issue.message for issue in issues), issues


def test_bad_json_is_reported(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{not json", encoding="utf-8")
    issues = validate_manifest(tmp_path)
    assert any("not valid JSON" in issue.message for issue in issues), issues


def test_bad_kind_is_rejected(tmp_path: Path) -> None:
    manifest = {**GOOD_MANIFEST, "kind": "docker-compose"}
    _write(tmp_path, manifest)
    issues = validate_manifest(tmp_path)
    assert any(
        "kind 'docker-compose' is not one of the supported kinds" in issue.message
        for issue in issues
    ), issues


def test_unknown_permission_is_rejected(tmp_path: Path) -> None:
    manifest = {**GOOD_MANIFEST, "permissions": ["root-access"]}
    _write(tmp_path, manifest)
    issues = validate_manifest(tmp_path)
    assert any("unknown permission 'root-access'" in issue.message for issue in issues), issues


def test_config_field_type_outside_subset_is_rejected(tmp_path: Path) -> None:
    manifest = {
        **GOOD_MANIFEST,
        "config_schema": {
            "type": "object",
            "properties": {"mode": {"title": "Mode", "type": "enum", "enum": ["a", "b"]}},
        },
    }
    _write(tmp_path, manifest)
    issues = validate_manifest(tmp_path)
    assert any(
        "config_schema field 'mode' has type 'enum'" in issue.message for issue in issues
    ), issues


def test_jargon_in_one_liner_is_rejected(tmp_path: Path) -> None:
    manifest = {**GOOD_MANIFEST, "one_liner": "Adds an entry to the vault via the mcp curator."}
    _write(tmp_path, manifest)
    issues = validate_manifest(tmp_path)
    words = {issue.message for issue in issues}
    assert any("'vault'" in word for word in words), issues
    assert any("'curator'" in word for word in words), issues


def test_jargon_in_config_schema_title_is_rejected(tmp_path: Path) -> None:
    manifest = {
        **GOOD_MANIFEST,
        "config_schema": {
            "type": "object",
            "properties": {"path": {"title": "Vault path", "type": "string"}},
        },
    }
    _write(tmp_path, manifest)
    issues = validate_manifest(tmp_path)
    assert any("uses in-house word 'vault'" in issue.message for issue in issues), issues


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    manifest = {k: v for k, v in GOOD_MANIFEST.items() if k != "maintainer"}
    _write(tmp_path, manifest)
    issues = validate_manifest(tmp_path)
    assert any("maintainer" in issue.message for issue in issues), issues


def test_validate_accepts_manifest_file_path_directly(tmp_path: Path) -> None:
    path = _write(tmp_path, GOOD_MANIFEST)
    assert validate_manifest(path) == []


@pytest.mark.parametrize("field_type", ["string", "number", "boolean", "secret"])
def test_every_supported_config_field_kind_is_accepted(tmp_path: Path, field_type: str) -> None:
    manifest = {
        **GOOD_MANIFEST,
        "config_schema": {
            "type": "object",
            "properties": {"field": {"title": "Field", "type": field_type}},
        },
    }
    _write(tmp_path, manifest)
    assert validate_manifest(tmp_path) == []
