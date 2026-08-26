"""Resource-indicator resolution — MASTERPLAN §5.5's resolved-audience lesson.

The acceptance criterion this file owns: "resource indicator
``<issuer>/<name>/mcp`` resolves to ``<issuer>/<name>``". The rest of the file
guards the *other* half of the lesson — that nothing a client sends can end up
in an ``aud`` claim verbatim.
"""

from __future__ import annotations

import pytest

from palaia_hub.oauth import OAuthError, ResourceRegistry, normalize_issuer

ISSUER = "https://hub.test"


@pytest.fixture
def registry() -> ResourceRegistry:
    return ResourceRegistry(ISSUER, ["work", "family"])


def test_canonical_audience_is_issuer_plus_profile(registry: ResourceRegistry) -> None:
    assert registry.audience("work") == "https://hub.test/work"


@pytest.mark.parametrize(
    "indicator",
    [
        "https://hub.test/work",
        "https://hub.test/work/",
        "https://hub.test/work/mcp",
        "https://hub.test/work/mcp/",
        "https://hub.test/mcp/work",
        "https://hub.test/mcp/work/",
        "https://hub.test/mcp/work/mcp",
        "https://HUB.TEST/work",
    ],
)
def test_every_shape_clients_send_resolves_to_the_canonical_audience(
    registry: ResourceRegistry, indicator: str
) -> None:
    assert registry.resolve(indicator) == "https://hub.test/work"


@pytest.mark.parametrize(
    "indicator",
    [
        "https://evil.test/work",
        "http://hub.test/work",
        "https://hub.test/",
        "https://hub.test/unknown",
        "https://hub.test/work/extra/segments",
        "https://hub.test/work#frag",
        "https://hub.test/work?x=1",
        "not-a-url",
        "https://hub.test/WORK",
    ],
)
def test_anything_else_is_invalid_target_not_a_guess(
    registry: ResourceRegistry, indicator: str
) -> None:
    with pytest.raises(OAuthError) as excinfo:
        registry.resolve(indicator)

    assert excinfo.value.error == "invalid_target"


def test_a_single_profile_hub_may_omit_the_resource_parameter() -> None:
    single = ResourceRegistry(ISSUER, ["work"])

    assert single.resolve(None) == "https://hub.test/work"


def test_a_multi_profile_hub_refuses_to_guess_which_resource_was_meant(
    registry: ResourceRegistry,
) -> None:
    with pytest.raises(OAuthError) as excinfo:
        registry.resolve(None)

    assert excinfo.value.error == "invalid_target"
    assert "work" in excinfo.value.description and "family" in excinfo.value.description


def test_issuer_base_path_is_honored_on_both_sides() -> None:
    proxied = ResourceRegistry("https://example.com/palaia", ["work"])

    assert proxied.audience("work") == "https://example.com/palaia/work"
    assert proxied.resolve("https://example.com/palaia/work/mcp") == (
        "https://example.com/palaia/work"
    )
    # The same path without the base prefix is a different resource.
    with pytest.raises(OAuthError):
        proxied.resolve("https://example.com/work")


def test_protected_resource_metadata_url_follows_rfc_9728(registry: ResourceRegistry) -> None:
    assert registry.metadata_url("work") == (
        "https://hub.test/.well-known/oauth-protected-resource/work"
    )


def test_metadata_url_for_a_proxied_hub_keeps_the_base_path_in_the_suffix() -> None:
    proxied = ResourceRegistry("https://example.com/palaia", ["work"])

    assert proxied.metadata_url("work") == (
        "https://example.com/.well-known/oauth-protected-resource/palaia/work"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://hub.test/", "https://hub.test"),
        ("https://HUB.test", "https://hub.test"),
        ("  https://hub.test  ", "https://hub.test"),
        ("https://hub.test/palaia/", "https://hub.test/palaia"),
    ],
)
def test_issuer_normalization(raw: str, expected: str) -> None:
    assert normalize_issuer(raw) == expected


@pytest.mark.parametrize("raw", ["hub.test", "ftp://hub.test", "https://hub.test?x=1", ""])
def test_an_unusable_issuer_is_rejected_at_construction(raw: str) -> None:
    with pytest.raises(ValueError, match="issuer"):
        normalize_issuer(raw)


def test_profile_for_audience_round_trips(registry: ResourceRegistry) -> None:
    assert registry.profile_for_audience("https://hub.test/family") == "family"
    assert registry.profile_for_audience("https://hub.test/nope") is None
