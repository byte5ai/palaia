"""The add-on manifest shape — literally the SPEC-303 entry shape.

SPEC-406's goal statement is explicit: "the manifest IS the SPEC-303 entry
shape; the SDK's job is scaffolding, validation and an honest local test
loop." Concretely, an author's manifest carries everything
``palaia_hub.market.models.ManualEntryCreate`` does (id, name, one_liner,
kind, source, config_schema, permissions, maintainer) — the fields a
submission supplies. ``verified`` and ``provenance`` are not manifest
fields: those are assigned by the curated-index maintainer during review
(SPEC-303 deliverable #4), never by the add-on author.

Field names, kinds and required-ness here are guarded against drifting
from the server's copy by
``server/tests/market/test_sdk_schema_parity.py`` — that test lives in the
server suite (only it may import both ``palaia_hub`` and this package);
this module has no dependency on ``palaia_hub`` itself.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Kept identical to ``palaia_hub.market.models.EntryKind``.
EntryKind = Literal["remote", "container", "mcpb", "skill", "plugin"]

#: Kept identical to ``palaia_hub.market.models.SourceLocatorType``.
SourceLocatorType = Literal["registry_ref", "image", "url"]

#: SPEC-304 deliverable #2's fixed ``config_schema`` field-kind subset
#: (mirrors the web dashboard's ``MarketConfigProperty["type"]`` union in
#: ``v3/web/src/lib/api/client.ts``). "enum" is not a kind of its own — a
#: ``string`` field with an ``enum`` list is how the fixed subset expresses
#: a picklist, exactly as the dashboard's form renderer reads it.
CONFIG_FIELD_KINDS: frozenset[str] = frozenset({"string", "number", "boolean", "secret"})

#: The permission vocabulary MASTERPLAN §5.3's security model names
#: ("network, filesystem mounts, memory-scope access") plus the read/write
#: split the starter curated index and the dashboard already use. A
#: manifest declaring anything outside this set fails validation with a
#: plain-language error naming the fix (SPEC-406 acceptance criterion).
KNOWN_PERMISSIONS: frozenset[str] = frozenset(
    {"network", "filesystem", "memory-scope:read", "memory-scope:write"}
)


class SourceLocator(BaseModel):
    """Where to install this entry from — identical shape to
    ``palaia_hub.market.models.SourceLocator``."""

    model_config = ConfigDict(extra="forbid")

    type: SourceLocatorType
    value: str


class AddonManifest(BaseModel):
    """An add-on author's ``manifest.json`` — field-for-field the same
    shape as ``palaia_hub.market.models.ManualEntryCreate``."""

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
    "CONFIG_FIELD_KINDS",
    "KNOWN_PERMISSIONS",
    "AddonManifest",
    "EntryKind",
    "SourceLocator",
    "SourceLocatorType",
]
