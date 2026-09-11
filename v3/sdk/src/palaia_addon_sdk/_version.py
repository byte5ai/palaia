"""The SDK's version, read from the installed distribution.

One source of truth — ``sdk/pyproject.toml``'s ``version`` (which
``server/tests/test_version_drift.py`` pins to ``v3/VERSION``). The two
literal ``"0.1.0"`` strings this replaces had drifted from it (issue #397).
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("palaia-addon-sdk")
except PackageNotFoundError:  # pragma: no cover - a source tree that was never installed
    __version__ = "0.0.0+uninstalled"

__all__ = ["__version__"]
