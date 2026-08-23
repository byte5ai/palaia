"""palaia's MCP gateway: profiles, vault-scoped memory tool families.

Public surface:

- :class:`~palaia_hub.gateway.vault_protocol.VaultService` — the narrow
  protocol the memory tools are written against (search/read/write/edit/
  move/delete/list/recent_activity). SPEC-102's real vault engine and this
  SPEC's :class:`~palaia_hub.gateway.fake_vault.FakeVaultService` both
  satisfy it; nothing in this package imports ``palaia_hub.vault``.
- :func:`~palaia_hub.gateway.build.build_gateway` — turns a
  :class:`~palaia_hub.gateway.config.GatewayConfig` plus a
  ``dict[str, VaultService]`` into a
  :class:`~palaia_hub.gateway.build.GatewayASGI` ready to mount into the
  hub's FastAPI app (see ``palaia_hub.app.create_app``'s ``gateway``
  parameter).
"""

from __future__ import annotations

from .build import GatewayASGI, GatewayConfigError, build_gateway
from .config import GatewayConfig, ProfileConfig, VaultMountConfig
from .fake_vault import FakeVaultService
from .vault_protocol import (
    MEMORY_TOOL_ACTIONS,
    NoteRecord,
    NoteSummary,
    SearchHit,
    VaultService,
    VaultServiceError,
)

__all__ = [
    "MEMORY_TOOL_ACTIONS",
    "FakeVaultService",
    "GatewayASGI",
    "GatewayConfig",
    "GatewayConfigError",
    "NoteRecord",
    "NoteSummary",
    "ProfileConfig",
    "SearchHit",
    "VaultMountConfig",
    "VaultService",
    "VaultServiceError",
    "build_gateway",
]
