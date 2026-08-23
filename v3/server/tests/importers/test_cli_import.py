"""CLI smoke tests: ``palaia-hub import v2|basic-memory``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from palaia_hub.cli import main


def test_import_v2_dry_run_json(
    tmp_path: Path, v2_store_fixture: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault_root = tmp_path / "vault"
    main(
        [
            "import",
            "v2",
            str(v2_store_fixture),
            "--vault",
            str(vault_root),
            "--dry-run",
            "--json",
        ]
    )
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["source"] == "v2"
    assert report["dry_run"] is True
    assert report["created"] == 4
    assert report["unmappable"] == 2
    assert not vault_root.exists() or not (vault_root / "imported").exists()


def test_import_basic_memory_apply_creates_vault(
    tmp_path: Path, bm_vault_fixture: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault_root = tmp_path / "vault"
    main(
        [
            "import",
            "basic-memory",
            str(bm_vault_fixture),
            "--vault",
            str(vault_root),
            "--vault-name",
            "personal",
        ]
    )
    captured = capsys.readouterr()
    assert "created: 3" in captured.out
    assert (vault_root / "imported" / "basic-memory").is_dir()
