"""palaia v3 hub daemon package.

This module is the single source of truth for the package version
(``palaia_hub.__version__``). No other file — not ``pyproject.toml``, not a
docs page, not a CLI flag — restates the version number; ``pyproject.toml``
reads it back out dynamically via ``[tool.hatch.version]``. This is
deliberate: v2's multi-file version sync (six places to update on every
release) must not return in v3.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
