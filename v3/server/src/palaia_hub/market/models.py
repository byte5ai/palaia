"""The one merged entry shape (SPEC-303 deliverable #4).

Every add-on the marketplace lists — whatever it came from — round-trips
through :class:`MarketEntry`. The dashboard (SPEC-304) never special-cases
a source: it reads ``provenance`` and ``verified`` off the same shape
every time.

**Naming note** (documented here rather than left implicit, since the SPEC
overloads the word "source"): the SPEC's entry shape names a field
``source`` meaning *where to install this from* — a registry ref, a
container image, or a URL. The SPEC's REST endpoint
(``/api/market/search?q=&source=``) filters by a *different* axis: which
of the three palaia data sources (official registry / curated index /
manual) produced the listing. Implementing both under one field name would
make either the entry shape or the query semantics silently wrong, so this
module keeps them as two distinct fields — ``source`` (the install
locator, exactly as deliverable #2 specifies) and ``provenance`` (registry
| curated | manual, always present per deliverable #4, and exactly the
value deliverable #3 assigns manual entries: ``provenance: manual``). The
REST layer's ``?source=`` query parameter filters on ``provenance`` — see
:mod:`palaia_hub.market.api` — which is the literal least-deviation
reading of "the same entry shape regardless of source" while keeping the
per-entry install locator unambiguous.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EntryKind = Literal["remote", "container", "mcpb", "skill", "plugin"]
Provenance = Literal["registry", "curated", "manual"]
SourceLocatorType = Literal["registry_ref", "image", "url"]


class SourceLocator(BaseModel):
    """Where to actually install this entry from."""

    model_config = ConfigDict(extra="forbid")

    type: SourceLocatorType
    value: str


class MarketEntry(BaseModel):
    """The merged shape every ``/api/market/*`` response uses."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    one_liner: str
    kind: EntryKind
    source: SourceLocator
    config_schema: dict[str, Any] | None = None
    permissions: list[str] = Field(default_factory=list)
    maintainer: str
    verified: bool
    #: Which of the three data sources produced this listing. Always
    #: present (SPEC-303 deliverable #4) — see the module docstring.
    provenance: Provenance


class ManualEntryCreate(BaseModel):
    """Body of a ``POST /api/market/manual`` request (deliverable #3)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    one_liner: str
    kind: EntryKind
    source: SourceLocator
    config_schema: dict[str, Any] | None = None
    permissions: list[str] = Field(default_factory=list)
    maintainer: str


__all__ = [
    "EntryKind",
    "ManualEntryCreate",
    "MarketEntry",
    "Provenance",
    "SourceLocator",
    "SourceLocatorType",
]
