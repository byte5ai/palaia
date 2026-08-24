"""Wire shapes for the official MCP registry client (SPEC-303).

``registry.modelcontextprotocol.io``'s v0.1 API returns a ``server.json``
shaped payload per entry (schema ``2025-12-11`` — see
``v3/research/mcp-landscape-2026.md`` §4). :class:`RegistryServer` keeps
only the fields palaia's marketplace needs, plus the full ``raw`` payload
for anything else a later SPEC wants without a schema round-trip.
"""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True, slots=True)
class RegistryServer:
    """One entry from the official registry, as palaia consumes it."""

    id: str
    name: str
    description: str
    version: str | None
    raw: dict[str, Any]


@dataclasses.dataclass(frozen=True, slots=True)
class RegistrySearchResult:
    """The result of a registry search/list call, honest about staleness.

    ``stale`` is true whenever the data did not come from a fresh network
    round-trip this call (either an on-disk cache hit within TTL that we
    chose not to refresh, or — see ``offline``— a fallback to the last
    successful fetch after the network attempt itself failed).
    """

    servers: tuple[RegistryServer, ...]
    stale: bool
    offline: bool
    #: Unix timestamp the returned data was fetched at, or ``None`` when
    #: there is no cached data at all (a cold cache plus an offline network
    #: yields an empty, non-stale-labeled result with this ``None``).
    fetched_at: float | None
    #: Empty when the call reflects a live fetch; otherwise the honest
    #: reason a cache/fallback was used instead (never a generic "failed").
    note: str = ""


__all__ = ["RegistryServer", "RegistrySearchResult"]
