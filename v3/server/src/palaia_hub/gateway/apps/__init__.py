"""SPEC-208: palaia's three Phase-2 MCP Apps.

- :mod:`palaia_hub.gateway.apps.shell` — the shared, self-contained
  HTML/CSS/JS page builder every app below renders through.
- :mod:`palaia_hub.gateway.apps.hub_status_app` — the hub-level
  ``hub_status`` tool + its app page.
- :mod:`palaia_hub.gateway.apps.recall_app` — the recall-explorer app page
  attached to the memory tool family's ``search``/``recall`` tools
  (:mod:`palaia_hub.gateway.memory_tools`).
- :mod:`palaia_hub.gateway.apps.review_app` — the review-queue app page
  attached to the memory tool family's ``review_queue`` tool.

``vendor/`` holds the two third-party assets these pages embed inline (the
MCP Apps view SDK bundle and two self-hosted font files) — see
``vendor/mcp_app_bridge.js``'s own header and ``shell.py``'s docstring for
provenance and licensing.
"""

from __future__ import annotations

__all__: list[str] = []
