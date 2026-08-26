"""SPEC-406 deliverable #3: "a test asserts the SDK's schema copy and
``palaia_hub.market.models`` cannot drift (parity test, both repos'
shapes compared field-by-field)."

The add-on SDK's manifest (``palaia_addon_sdk.models.AddonManifest``) is
deliberately the author-submitted subset of the merged marketplace entry
shape — exactly what ``palaia_hub.market.models.ManualEntryCreate``
already models server-side (id, name, one_liner, kind, source,
config_schema, permissions, maintainer). ``verified`` and ``provenance``
are assigned by the curated-index maintainer during review, never by the
add-on author, so they are correctly absent from the manifest — this test
asserts everything else lines up: field name, kind, and required-ness.

This is the one place in the repository allowed to import both
``palaia_hub`` and ``palaia_addon_sdk`` — everywhere else the dependency
is one-directional (SPEC-406 acceptance: the SDK has none on the hub).
"""

from __future__ import annotations

from typing import get_args

from palaia_addon_sdk.models import AddonManifest
from palaia_addon_sdk.models import EntryKind as SdkEntryKind
from palaia_addon_sdk.models import SourceLocator as SdkSourceLocator
from palaia_addon_sdk.models import SourceLocatorType as SdkSourceLocatorType

from palaia_hub.market.models import EntryKind as HubEntryKind
from palaia_hub.market.models import ManualEntryCreate
from palaia_hub.market.models import SourceLocator as HubSourceLocator
from palaia_hub.market.models import SourceLocatorType as HubSourceLocatorType


def _kind_label(annotation: object) -> object:
    """The annotation, or — for a nested pydantic model — just its class
    name. The SDK and the hub necessarily have their own distinct
    ``SourceLocator`` classes (this test is the only place both may be
    imported at all); comparing by name is the field-by-field "kind"
    check SPEC-406 asks for without demanding the impossible (object
    identity across two independent packages)."""
    if isinstance(annotation, type) and hasattr(annotation, "model_fields"):
        return annotation.__name__
    return annotation


def _field_shape(model: type) -> dict[str, tuple[object, bool]]:
    """``{field name: (kind, required)}`` for a pydantic model — the exact
    axes SPEC-406 names: "field names, kinds, required-ness"."""
    return {
        name: (_kind_label(field.annotation), field.is_required())
        for name, field in model.model_fields.items()
    }


def test_addon_manifest_matches_manual_entry_create_field_by_field() -> None:
    sdk_shape = _field_shape(AddonManifest)
    hub_shape = _field_shape(ManualEntryCreate)
    assert sdk_shape == hub_shape, (sdk_shape, hub_shape)


def test_source_locator_matches_field_by_field() -> None:
    assert _field_shape(SdkSourceLocator) == _field_shape(HubSourceLocator)


def test_source_locator_type_literal_matches() -> None:
    assert set(get_args(SdkSourceLocatorType)) == set(get_args(HubSourceLocatorType))


def test_entry_kind_literal_matches() -> None:
    assert set(get_args(SdkEntryKind)) == set(get_args(HubEntryKind))
