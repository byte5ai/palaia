"""palaia v3 hub daemon package.

This module's ``__version__`` is a literal copy of ``v3/VERSION``
(SPEC-506) — the *repository's* single source of truth, checked byte-for-
byte at build time by ``server/tests/test_version_drift.py``. It stays a
plain literal rather than reading the file at import time because
``[tool.hatch.version]`` below parses this line with a regex to derive
``pyproject.toml``'s own dynamic version, and a wheel built from an
sdist would not carry a sibling ``../../VERSION`` file to read at
runtime. No other Python file restates the version number;
``pyproject.toml`` reads it back out dynamically via
``[tool.hatch.version]``. This is deliberate: v2's multi-file version
sync (six places to update on every release) must not return in v3 — one
extra place (``VERSION``) to update, one drift test, is the only cost of
letting the web/sdk/mcpb-bundle side of the release also anchor to it.
"""

from __future__ import annotations

__version__ = "3.0.0-rc1"

__all__ = ["__version__"]
