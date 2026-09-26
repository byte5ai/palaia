"""Tests for the MCP SDK version check (palaia v2 supports only mcp>=1.2.0,<2)."""

from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path

import pytest

from palaia.doctor.checks import _check_mcp_server
from palaia.mcp import MCP_SDK_REQUIREMENT, check_mcp_sdk, main


def _installed(monkeypatch, version: str | None):
    """Make importlib.metadata report the given mcp version (None = not installed)."""

    def fake_version(name):
        if name != "mcp" or version is None:
            raise importlib.metadata.PackageNotFoundError(name)
        return version

    monkeypatch.setattr(importlib.metadata, "version", fake_version)


class TestCheckMcpSdk:
    def test_missing(self, monkeypatch):
        _installed(monkeypatch, None)
        sdk = check_mcp_sdk()
        assert sdk.state == "missing"
        assert sdk.fix == "pip install 'palaia[mcp]'"

    @pytest.mark.parametrize("version", ["1.2.0", "1.2.1", "1.30.0", "1.99.9"])
    def test_supported(self, monkeypatch, version):
        _installed(monkeypatch, version)
        sdk = check_mcp_sdk()
        assert sdk.ok
        assert sdk.installed_version == version

    @pytest.mark.parametrize("version", ["1.0.0", "1.1.3", "2.0.0", "2.0.0rc1", "2.2.0", "3.0", "unknown"])
    def test_unsupported(self, monkeypatch, version):
        _installed(monkeypatch, version)
        sdk = check_mcp_sdk()
        assert sdk.state == "unsupported"
        assert sdk.problem == f"mcp {version} is not supported (palaia needs {MCP_SDK_REQUIREMENT})"
        assert sdk.fix == f"pip install '{MCP_SDK_REQUIREMENT}'"


class TestMain:
    def test_unsupported_version_exits_with_install_hint(self, monkeypatch, capsys):
        _installed(monkeypatch, "2.2.0")
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "mcp 2.2.0 is not supported" in err
        assert f"pip install '{MCP_SDK_REQUIREMENT}'" in err

    def test_missing_sdk_exits_with_install_hint(self, monkeypatch, capsys):
        _installed(monkeypatch, None)
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 1
        assert "pip install 'palaia[mcp]'" in capsys.readouterr().err

    def test_broken_supported_install_shows_real_import_error(self, monkeypatch, capsys, tmp_path):
        """An in-range version that fails to import is reported with its real cause."""
        _installed(monkeypatch, "1.30.0")
        # A None entry makes the import raise ImportError, like a missing dependency would.
        monkeypatch.setitem(sys.modules, "palaia.mcp.server", None)
        (tmp_path / ".palaia").mkdir()
        with pytest.raises(SystemExit) as exc:
            main(["--root", str(tmp_path / ".palaia")])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "mcp 1.30.0 failed to import" in err
        assert "not supported" not in err


class TestDoctorMcpCheck:
    def test_unsupported_version_is_reported_with_fix(self, monkeypatch):
        _installed(monkeypatch, "2.2.0")
        result = _check_mcp_server(None)
        assert result["status"] == "info"
        assert "mcp 2.2.0 is not supported" in result["message"]
        assert f"pip install '{MCP_SDK_REQUIREMENT}'" in result["fix"]

    def test_missing_is_info(self, monkeypatch):
        _installed(monkeypatch, None)
        result = _check_mcp_server(None)
        assert result["status"] == "info"
        assert "not installed" in result["message"]

    def test_supported_is_ok(self, monkeypatch):
        _installed(monkeypatch, "1.30.0")
        result = _check_mcp_server(None)
        assert result["status"] == "ok"
        assert "1.30.0" in result["message"]


def test_requirement_matches_pyproject_extra():
    tomllib = pytest.importorskip("tomllib")  # Python 3.11+; the CI matrix covers it
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    extras = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    assert extras["mcp"] == [MCP_SDK_REQUIREMENT]
