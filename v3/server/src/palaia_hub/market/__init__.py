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
from .manual import ManualEntryError, ManualEntryStore
from .models import EntryKind, ManualEntryCreate, MarketEntry, Provenance, SourceLocator
from .service import MarketSearchResult, MarketService

__all__ = [
    "DEFAULT_INDEX_URL",
    "DEFAULT_PUBLIC_KEY_B64",
    "CuratedIndexClient",
    "CuratedIndexResult",
    "EntryKind",
    "IndexVerificationError",
    "ManualEntryCreate",
    "ManualEntryError",
    "ManualEntryStore",
    "MarketEntry",
    "MarketSearchResult",
    "MarketService",
    "Provenance",
    "SourceLocator",
    "build_market_router",
]
