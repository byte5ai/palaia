"""SPEC-204's config surface: :class:`palaia_hub.config.IdpSettings` and friends."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from palaia_hub.config import GitHubIdpSettings, IdpSettings, OidcIdpSettings

GITHUB = GitHubIdpSettings(
    client_id="id",
    client_secret="secret",  # noqa: S106 - test fixture
    allowed_users=["octocat"],
)
OIDC = OidcIdpSettings(
    discovery_url="https://idp.example.com/.well-known/openid-configuration",
    client_id="id",
    client_secret="secret",  # noqa: S106 - test fixture
    allowed_users=["ana@example.com"],
    display_name="Example Workspace",
)


def test_github_provider_needs_its_block() -> None:
    with pytest.raises(ValidationError, match="oauth.idp.github"):
        IdpSettings(provider="github")


def test_oidc_provider_needs_its_block() -> None:
    with pytest.raises(ValidationError, match="oauth.idp.oidc"):
        IdpSettings(provider="oidc")


def test_only_one_provider_block_may_be_set() -> None:
    with pytest.raises(ValidationError, match="oauth.idp.oidc"):
        IdpSettings(provider="github", github=GITHUB, oidc=OIDC)


def test_a_valid_github_config_round_trips() -> None:
    settings = IdpSettings(provider="github", github=GITHUB)
    assert settings.github is not None
    assert settings.github.allowed_users == ["octocat"]


def test_a_valid_oidc_config_round_trips() -> None:
    settings = IdpSettings(provider="oidc", oidc=OIDC)
    assert settings.oidc is not None
    assert settings.oidc.display_name == "Example Workspace"


def test_oidc_discovery_url_must_be_https() -> None:
    with pytest.raises(ValidationError, match="https"):
        OidcIdpSettings(
            discovery_url="http://idp.example.com/.well-known/openid-configuration",
            client_id="id",
            client_secret="secret",  # noqa: S106 - test fixture
            allowed_users=["ana@example.com"],
            display_name="Example Workspace",
        )


def test_github_allow_list_must_not_be_empty() -> None:
    with pytest.raises(ValidationError):
        GitHubIdpSettings(
            client_id="id", client_secret="secret", allowed_users=[]  # noqa: S106
        )


def test_oidc_display_name_must_not_be_empty() -> None:
    with pytest.raises(ValidationError):
        OidcIdpSettings(
            discovery_url="https://idp.example.com/.well-known/openid-configuration",
            client_id="id",
            client_secret="secret",  # noqa: S106
            allowed_users=["ana@example.com"],
            display_name="",
        )
