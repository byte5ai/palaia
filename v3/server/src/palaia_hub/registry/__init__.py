"""Client for the official MCP registry (SPEC-303 deliverable #1).

See :mod:`palaia_hub.registry.client` for the module docstring covering
timeouts, size caps and disk caching, and :mod:`palaia_hub.market` for how
this is merged with palaia's own curated index and manual entries into one
read model.
"""

from __future__ import annotations

from .client import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TTL_SECONDS,
    RegistryClient,
    RegistryOfflineError,
)
from .models import RegistrySearchResult, RegistryServer

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_TTL_SECONDS",
    "RegistryClient",
    "RegistryOfflineError",
    "RegistrySearchResult",
    "RegistryServer",
]
