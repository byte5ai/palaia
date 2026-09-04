"""The one merged marketplace read model (SPEC-303 deliverable #4).

:class:`MarketService` is the single place that knows about all three
sources — the official registry, the curated index, and manual entries —
and the only thing SPEC-304's UI/install flows talk to. Every result is a
:class:`~palaia_hub.market.models.MarketEntry`, whichever source it came
from.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..registry.client import RegistryClient, RegistryOfflineError
from ..registry.models import RegistryServer
from .curated import CuratedIndexClient, CuratedIndexResult
from .manual import ManualEntryStore
from .models import ManualEntryCreate, MarketEntry, Provenance, SourceLocator

logger = logging.getLogger("palaia_hub.market.service")

#: A hub subsystem that cannot depend on the event bus directly reports
#: through this narrow hook instead, same pattern as
#: ``palaia_hub.stash.service.StashService.publish`` — ``app.py`` wires it
#: onto the real :class:`~palaia_hub.events.bus.EventBus` when both a
#: ``market_service`` and an ``event_bus`` are given.
PublishHook = Callable[[str, dict[str, Any]], None]


def _market_entry_from_registry(server: RegistryServer) -> MarketEntry:
    """Map a raw registry ``server.json`` payload onto the shared shape.

    The registry declares no permissions and is not palaia-verified by
    definition (deliverable #4's ``verified`` is always ``False`` here) —
    curation, per MASTERPLAN §5.3, is what the palaia index adds on top.
    """
    raw = server.raw.get("server", server.raw)
    remotes = raw.get("remotes") or []
    packages = raw.get("packages") or []
    if remotes:
        kind: str = "remote"
        source = SourceLocator(type="url", value=str(remotes[0].get("url", "")))
    elif packages:
        first_package = packages[0]
        registry_type = str(first_package.get("registry_type", ""))
        if registry_type in ("oci", "docker"):
            kind = "container"
            source = SourceLocator(type="image", value=str(first_package.get("identifier", "")))
        else:
            kind = "remote"
            source = SourceLocator(type="registry_ref", value=server.id)
    else:
        kind = "remote"
        source = SourceLocator(type="registry_ref", value=server.id)

    maintainer = str(raw.get("repository", {}).get("url", "") or "unknown")
    return MarketEntry(
        id=server.id,
        name=server.name,
        one_liner=server.description[:200],
        kind=kind,  # type: ignore[arg-type]
        source=source,
        config_schema=None,
        permissions=[],
        maintainer=maintainer,
        verified=False,
        provenance="registry",
    )


@dataclass(frozen=True, slots=True)
class MarketSearchResult:
    entries: tuple[MarketEntry, ...]
    stale: bool
    #: Per-source honest notes (empty string when that source had none),
    #: e.g. {"registry": "cached 3h ago (offline)"}.
    notes: dict[str, str]


class MarketService:
    """Merges registry + curated index + manual entries into one API."""

    def __init__(
        self,
        *,
        registry_client: RegistryClient,
        curated_client: CuratedIndexClient,
        manual_store: ManualEntryStore,
    ) -> None:
        self.registry_client = registry_client
        self.curated_client = curated_client
        self.manual_store = manual_store
        #: Set by ``app.py`` to bridge ``market.index.updated`` onto the
        #: hub's real event bus; a no-op default keeps this service usable
        #: standalone (tests, scripts) with no bus at all.
        self.publish: PublishHook = lambda event, data: None

    async def search(
        self, query: str = "", *, source: Provenance | None = None
    ) -> MarketSearchResult:
        """Search across whichever sources ``source`` selects (all three
        when omitted), merged into one list, one shape."""
        entries: list[MarketEntry] = []
        stale = False
        notes: dict[str, str] = {}

        if source in (None, "registry"):
            try:
                result = await self.registry_client.search(query)
            except RegistryOfflineError as exc:
                notes["registry"] = f"registry unavailable: {exc}"
            else:
                entries.extend(_market_entry_from_registry(s) for s in result.servers)
                if result.stale:
                    stale = True
                    notes["registry"] = result.note or "serving cached results"

        if source in (None, "curated"):
            curated = await self.curated_client.fetch()
            entries.extend(curated.entries)
            if curated.stale:
                stale = True
                notes["curated"] = curated.warning or "serving last verified copy"

        if source in (None, "manual"):
            entries.extend(self.manual_store.list())

        if query:
            needle = query.lower()
            entries = [
                e for e in entries if needle in e.name.lower() or needle in e.one_liner.lower()
            ]

        return MarketSearchResult(entries=tuple(entries), stale=stale, notes=notes)

    async def get_entry(
        self, entry_id: str, *, curated: CuratedIndexResult | None = None
    ) -> MarketEntry | None:
        """Look up one entry by id, checking manual, then curated, then
        the registry (a REST-created override could in principle shadow a
        registry id; checking manual first makes that deterministic).

        ``curated`` lets a caller resolving *many* ids in one request
        (``GET /api/market/installed``) hand over one already-fetched
        index instead of asking the client once per id (issue #321).
        """
        manual = self.manual_store.get(entry_id)
        if manual is not None:
            return manual

        if curated is None:
            curated = await self.curated_client.fetch()
        for entry in curated.entries:
            if entry.id == entry_id:
                return entry

        try:
            server = await self.registry_client.detail(entry_id)
        except RegistryOfflineError:
            return None
        if server is None:
            return None
        return _market_entry_from_registry(server)

    async def refresh_curated_index(self) -> None:
        """Force a curated-index fetch and emit ``market.index.updated``
        (SPEC-303 deliverable #5) with the outcome, whether fresh or a
        refused/offline fallback — the event names both cases honestly."""
        result = await self.curated_client.fetch(force=True)
        self.publish(
            "market.index.updated",
            {
                "generated_at": result.generated_at,
                "entry_count": len(result.entries),
                "stale": result.stale,
                "warning": result.warning,
            },
        )

    def add_manual_entry(self, payload: ManualEntryCreate) -> MarketEntry:
        return self.manual_store.add(payload)


__all__ = ["MarketSearchResult", "MarketService", "PublishHook"]
