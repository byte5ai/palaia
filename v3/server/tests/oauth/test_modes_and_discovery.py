"""Deliverable #6 (mode integration + startup summary) and the discovery docs.

Two acceptance-adjacent claims live here:

* ``cloud``/``open`` accept OAuth as satisfying the auth mandate — checked
  both at config-validation time and against a really-built gateway.
* the startup summary states which auth methods each profile serves.

Plus the two metadata documents, because a discovery document that says the
wrong thing breaks every client at once and is otherwise never noticed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest

from palaia_hub.auth.policy import check_gateway_auth_policy
from palaia_hub.config import ConfigError, HubConfig, OAuthSettings, load_config
from palaia_hub.oauth import (
    SigningKey,
    build_profile_auth,
    log_profile_auth,
    summarize_profile_auth,
)
from palaia_hub.oauth.resources import ResourceRegistry
from palaia_hub.oauth.service import AUTHORIZE_PATH, TOKEN_PATH

from .harness import Harness, build_harness

BASE_URL = "https://testserver"


# ------------------------------------------------------------ mode integration


def test_cloud_mode_accepts_oauth_instead_of_per_client_tokens(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        "mode: cloud\nauth_enabled: false\noauth:\n  enabled: true\n"
        "  issuer: https://hub.example.com\n",
        encoding="utf-8",
    )

    config = load_config(home=tmp_path)

    assert config.mode == "cloud"
    assert config.auth_enabled is False
    assert config.oauth.enabled is True


def test_cloud_mode_with_neither_auth_method_still_fails_with_both_fixes(
    tmp_path: Path,
) -> None:
    (tmp_path / "config.yaml").write_text(
        "mode: cloud\nauth_enabled: false\n", encoding="utf-8"
    )

    with pytest.raises(ConfigError) as excinfo:
        load_config(home=tmp_path)

    message = str(excinfo.value)
    assert "auth_enabled: true" in message
    assert "oauth.enabled" in message


def test_a_gateway_authenticated_only_by_oauth_satisfies_the_mode_policy(
    tmp_path: Path,
) -> None:
    """The built-gateway check (auth/policy.py), not just the config check.

    Building the harness in ``cloud`` mode *is* half the assertion:
    :func:`palaia_hub.app.create_app` runs the policy check itself, so an
    OAuth-only gateway that failed it could not be constructed at all.
    """
    harness = build_harness(tmp_path, mode="cloud", with_plt_tokens=False)
    try:
        servers = harness.gateway.profile_servers
        assert set(servers) == set(harness.profiles)
        assert all(server.auth is not None for server in servers.values())
        check_gateway_auth_policy("cloud", servers)  # does not raise
    finally:
        harness.store.close()


# ------------------------------------------------------------ startup summary


def test_the_summary_names_both_credential_types_per_profile(tmp_path: Path) -> None:
    key = SigningKey.load_or_create(tmp_path)
    resources = ResourceRegistry("https://hub.test", ["alpha", "beta"])
    from palaia_hub.auth.store import TokenStore

    providers = build_profile_auth(
        ["alpha", "beta"], key=key, resources=resources, token_store=TokenStore(home=tmp_path)
    )

    lines = summarize_profile_auth(providers)

    assert lines == [
        "profile 'alpha' accepts: oauth2 (access JWT), per-client token (plt_)",
        "profile 'beta' accepts: oauth2 (access JWT), per-client token (plt_)",
    ]


def test_the_summary_names_oauth_only_when_that_is_all_there_is(tmp_path: Path) -> None:
    key = SigningKey.load_or_create(tmp_path)
    resources = ResourceRegistry("https://hub.test", ["alpha"])

    lines = summarize_profile_auth(
        build_profile_auth(["alpha"], key=key, resources=resources)
    )

    assert lines == ["profile 'alpha' accepts: oauth2 (access JWT)"]


def test_a_profile_with_no_credential_is_left_unauthenticated_not_half_wired() -> None:
    assert build_profile_auth(["alpha"]) == {}


def test_key_and_resources_must_be_passed_together(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="together"):
        build_profile_auth(["alpha"], key=SigningKey.load_or_create(tmp_path))


def test_the_summary_is_logged_at_startup(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="palaia_hub.oauth.verifier")
    key = SigningKey.load_or_create(tmp_path)
    resources = ResourceRegistry("https://hub.test", ["alpha"])

    log_profile_auth(build_profile_auth(["alpha"], key=key, resources=resources))

    assert "profile 'alpha' accepts: oauth2 (access JWT)" in caplog.text


# ---------------------------------------------------------- discovery documents


@pytest.mark.anyio
async def test_the_authorization_server_metadata_says_what_this_server_does(
    harness: Harness,
) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=harness.app), base_url=BASE_URL
        ) as http:
            response = await http.get("/.well-known/oauth-authorization-server")

    assert response.status_code == 200
    metadata = response.json()
    assert metadata["issuer"] == harness.server.issuer
    assert metadata["authorization_endpoint"] == f"{harness.server.issuer}{AUTHORIZE_PATH}"
    assert metadata["token_endpoint"] == f"{harness.server.issuer}{TOKEN_PATH}"
    assert metadata["response_types_supported"] == ["code"]
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert set(metadata["grant_types_supported"]) == {
        "authorization_code",
        "refresh_token",
        "client_credentials",
    }
    assert metadata["client_id_metadata_document_supported"] is True
    assert metadata["resource_indicators_supported"] is True
    assert metadata["authorization_response_iss_parameter_supported"] is True
    assert metadata["scopes_supported"] == ["vault:work:read", "vault:work:write"]


@pytest.mark.anyio
async def test_the_oidc_discovery_path_serves_the_same_document(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=harness.app), base_url=BASE_URL
        ) as http:
            oauth = await http.get("/.well-known/oauth-authorization-server")
            oidc = await http.get("/.well-known/openid-configuration")

    assert oidc.status_code == 200
    assert oidc.json() == oauth.json()


@pytest.mark.anyio
async def test_each_profile_has_its_own_protected_resource_document(
    harness: Harness,
) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=harness.app), base_url=BASE_URL
        ) as http:
            alpha = await http.get("/.well-known/oauth-protected-resource/alpha")
            beta = await http.get("/.well-known/oauth-protected-resource/beta")
            missing = await http.get("/.well-known/oauth-protected-resource/nope")

    assert alpha.json()["resource"] == harness.audience("alpha")
    assert beta.json()["resource"] == harness.audience("beta")
    assert alpha.json()["resource"] != beta.json()["resource"]
    assert alpha.json()["authorization_servers"] == [harness.server.issuer]
    assert alpha.json()["bearer_methods_supported"] == ["header"]
    assert missing.status_code == 404


@pytest.mark.anyio
async def test_the_jwks_endpoint_publishes_only_the_public_key(harness: Harness) -> None:
    async with harness.app.router.lifespan_context(harness.app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=harness.app), base_url=BASE_URL
        ) as http:
            response = await http.get("/.well-known/jwks.json")

    assert response.status_code == 200
    entry = response.json()["keys"][0]
    assert entry["kty"] == "EC"
    assert entry["crv"] == "P-256"
    assert entry["alg"] == "ES256"
    assert entry["kid"] == harness.key.kid
    assert "d" not in entry, "the private scalar must never be published"


def test_an_oauth_server_without_an_issuer_refuses_to_be_built(tmp_path: Path) -> None:
    from palaia_hub.oauth import AuthorizationServer, OAuthStore

    store = OAuthStore(tmp_path)
    store.open()
    try:
        with pytest.raises(ValueError, match="issuer"):
            AuthorizationServer(
                settings=OAuthSettings(enabled=True),
                profile_scopes={"alpha": []},
                store=store,
                key=SigningKey.load_or_create(tmp_path),
            )
    finally:
        store.close()


def test_the_default_config_template_parses_into_the_documented_defaults(
    tmp_path: Path,
) -> None:
    """The commented `oauth:` block in config.yaml must round-trip."""
    config = load_config(home=tmp_path)

    assert config.oauth == OAuthSettings()
    assert config.oauth.enabled is False
    assert config.oauth.refresh_grace_window == 120
    assert HubConfig().oauth.access_token_ttl == 900
