"""palaia's marketplace data layer (SPEC-303): the official MCP registry,
the curated palaia add-on index, and manual entries, merged into one read
model (:class:`~palaia_hub.market.service.MarketService`) and one REST
surface (:mod:`palaia_hub.market.api`). See MASTERPLAN §5.3. SPEC-304
builds the dashboard UI and install/lifecycle flows on top of this.
"""

from __future__ import annotations

from .api import build_market_router
from .curated import (
    DEFAULT_INDEX_URL,
    DEFAULT_PUBLIC_KEY_B64,
    CuratedIndexClient,
    CuratedIndexResult,
    IndexVerificationError,
)
from .install import (
    CONSENT_TTL_SECONDS,
    ConsentStore,
    InstalledAddonOut,
    InstallService,
    MarketInstallError,
    build_market_install_router,
    wire_market_index_updates,
)
from .installed_store import InstalledAddonRecord, InstalledAddonStore
from .manual import ManualEntryError, ManualEntryStore
from .models import EntryKind, ManualEntryCreate, MarketEntry, Provenance, SourceLocator
from .service import MarketSearchResult, MarketService

__all__ = [
    "CONSENT_TTL_SECONDS",
    "DEFAULT_INDEX_URL",
    "DEFAULT_PUBLIC_KEY_B64",
    "ConsentStore",
    "CuratedIndexClient",
    "CuratedIndexResult",
    "EntryKind",
    "IndexVerificationError",
    "InstallService",
    "InstalledAddonOut",
    "InstalledAddonRecord",
    "InstalledAddonStore",
    "ManualEntryCreate",
    "ManualEntryError",
    "ManualEntryStore",
    "MarketEntry",
    "MarketInstallError",
    "MarketSearchResult",
    "MarketService",
    "Provenance",
    "SourceLocator",
    "build_market_install_router",
    "build_market_router",
    "wire_market_index_updates",
]
