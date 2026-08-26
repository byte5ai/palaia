from __future__ import annotations

from pathlib import Path

import pytest

from palaia_addon_sdk.scaffold import scaffold_addon
from palaia_addon_sdk.validate import validate_manifest


def test_scaffold_writes_three_files(tmp_path: Path) -> None:
    addon_dir = tmp_path / "my-fetch-addon"
    written = scaffold_addon(addon_dir, maintainer="alice")
    names = {path.name for path in written}
    assert names == {"manifest.json", "server.py", "README.md"}
    for path in written:
        assert path.is_file()


def test_scaffold_output_passes_validate(tmp_path: Path) -> None:
    addon_dir = tmp_path / "my-fetch-addon"
    scaffold_addon(addon_dir, maintainer="alice")
    assert validate_manifest(addon_dir) == []


def test_scaffold_refuses_to_overwrite(tmp_path: Path) -> None:
    addon_dir = tmp_path / "my-fetch-addon"
    scaffold_addon(addon_dir, maintainer="alice")
    with pytest.raises(FileExistsError):
        scaffold_addon(addon_dir, maintainer="alice")


def test_scaffold_derives_id_from_name(tmp_path: Path) -> None:
    addon_dir = tmp_path / "ignored-dir-name"
    scaffold_addon(addon_dir, name="My Cool Add-on", maintainer="alice")
    import json

    manifest = json.loads((addon_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "my-cool-add-on"
    assert manifest["name"] == "My Cool Add-on"
