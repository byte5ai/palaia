"""Tests for the MCP SDK version check (palaia v2 supports only the 1.x SDK)."""

from __future__ import annotations

import importlib.metadata
import sys
import types
from pathlib import Path

import pytest

from palaia.doctor.checks import _check_mcp_server
from palaia.mcp import MCP_SDK_REQUIREMENT, check_mcp_sdk, main


@pytest.fixture
def sdk_missing(monkeypatch):
    """Simulate an environment without the MCP SDK."""
    monkeypatch.setitem(sys.modules, "mcp", None)


@pytest.fixture
def sdk_unsupported(monkeypatch):
    """Simulate mcp 2.x: the package imports, but mcp.server.fastmcp does not."""
    monkeypatch.setitem(sys.modules, "mcp", types.ModuleType("mcp"))
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", None)
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "2.2.0")


class TestCheckMcpSdk:
    def test_missing(self, sdk_missing):
        assert check_mcp_sdk() == ("MCP SDK not installed", "pip install 'palaia[mcp]'")

    def test_unsupported_version(self, sdk_unsupported):
        problem, fix = check_mcp_sdk()
        assert problem == f"mcp 2.2.0 is not supported (palaia needs {MCP_SDK_REQUIREMENT})"
        assert fix == f"pip install '{MCP_SDK_REQUIREMENT}'"

    def test_supported(self):
        pytest.importorskip("mcp.server.fastmcp")
        assert check_mcp_sdk() is None


class TestMainRefusesUnsupportedSdk:
    def test_unsupported_version_exits_with_install_hint(self, sdk_unsupported, capsys):
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "mcp 2.2.0 is not supported" in err
        assert f"pip install '{MCP_SDK_REQUIREMENT}'" in err

    def test_missing_sdk_exits_with_install_hint(self, sdk_missing, capsys):
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 1
        assert "pip install 'palaia[mcp]'" in capsys.readouterr().err


class TestDoctorMcpCheck:
    def test_unsupported_version_warns(self, sdk_unsupported):
        result = _check_mcp_server(None)
        assert result["status"] == "warn"
        assert "mcp 2.2.0 is not supported" in result["message"]
        assert result["fix"] == f"pip install '{MCP_SDK_REQUIREMENT}'"

    def test_missing_is_info(self, sdk_missing):
        assert _check_mcp_server(None)["status"] == "info"

    def test_supported_is_ok(self):
        pytest.importorskip("mcp.server.fastmcp")
        assert _check_mcp_server(None)["status"] == "ok"


def test_requirement_matches_pyproject_extra():
    tomllib = pytest.importorskip("tomllib")
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    extras = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    assert extras["mcp"] == [MCP_SDK_REQUIREMENT]
