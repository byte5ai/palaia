"""palaia's MCP gateway: profiles, vault-scoped memory tool families.

Public surface:

- :class:`~palaia_hub.gateway.vault_protocol.VaultService` — the narrow
  protocol the memory tools are written against (search/read/write/edit/
  move/delete/list/recent_activity). :class:`~palaia_hub.gateway.fake_vault.FakeVaultService`
  (in-memory, tests) and :class:`~palaia_hub.gateway.wiring.EngineVaultService`
  (SPEC-113's real adapter over SPEC-102's vault engine) both satisfy it.
  Everything else in this package (``build``, ``config``, ``memory_tools``,
  ``naming``, ``vault_protocol``) is still independent of ``palaia_hub.vault``
  by design — only ``wiring`` imports it, so the memory tool family stays
  written against the protocol, not the engine.
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
from .stash_tools import (
    STASH_TOOL_ACTIONS,
    StashGatewayASGI,
    build_stash_gateway,
    build_stash_server,
)
from .vault_protocol import (
    INBOX_TOOL_ACTIONS,
    MEMORY_TOOL_ACTIONS,
    CaptureResult,
    InboxStatusResult,
    NoteRecord,
    NoteSummary,
    SearchHit,
    VaultService,
    VaultServiceError,
)
from .wiring import EngineVaultService

__all__ = [
    "INBOX_TOOL_ACTIONS",
    "MEMORY_TOOL_ACTIONS",
    "STASH_TOOL_ACTIONS",
    "CaptureResult",
    "EngineVaultService",
    "FakeVaultService",
    "GatewayASGI",
    "GatewayConfig",
    "GatewayConfigError",
    "InboxStatusResult",
    "NoteRecord",
    "NoteSummary",
    "ProfileConfig",
    "SearchHit",
    "StashGatewayASGI",
    "VaultMountConfig",
    "VaultService",
    "VaultServiceError",
    "build_gateway",
    "build_stash_gateway",
    "build_stash_server",
]
