"""CIMD document validation (incl. the SSRF fence) and PKCE.

The SSRF tests deliberately drive the *real* :class:`CimdFetcher`, not the
static test double: the whole security value of that class is the fetch it
refuses, so a test that stubs the transport would prove nothing about it.
Every URL used here resolves to a private, loopback or otherwise
non-public address, so nothing leaves the test machine either way.
"""

from __future__ import annotations

import pytest

from palaia_hub.oauth import OAuthError
from palaia_hub.oauth.cimd import (
    CimdFetcher,
    is_cimd_client_id,
    match_redirect_uri,
    validate_metadata,
    validate_redirect_uri,
)
from palaia_hub.oauth.pkce import challenge_for, validate_challenge, verify_verifier

CLIENT_ID = "https://client.test/app.json"


# ----------------------------------------------------------- document shape


def test_a_well_formed_document_is_normalized() -> None:
    normalized = validate_metadata(
        {
            "client_id": CLIENT_ID,
            "client_name": "Connector",
            "redirect_uris": ["https://client.test/cb"],
            "grant_types": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_method": "none",
            "some_future_member": {"ignored": True},
        },
        expected_client_id=CLIENT_ID,
    )

    assert normalized == {
        "client_id": CLIENT_ID,
        "client_name": "Connector",
        "redirect_uris": ["https://client.test/cb"],
        "grant_types": ["authorization_code", "refresh_token"],
    }


def test_a_document_claiming_another_client_id_is_refused() -> None:
    with pytest.raises(OAuthError) as excinfo:
        validate_metadata(
            {"client_id": "https://evil.test/app.json", "redirect_uris": ["https://x.test/cb"]},
            expected_client_id=CLIENT_ID,
        )

    assert excinfo.value.error == "invalid_client_metadata"


@pytest.mark.parametrize(
    "document",
    [
        "a string",
        {"client_id": CLIENT_ID},
        {"client_id": CLIENT_ID, "redirect_uris": []},
        {"client_id": CLIENT_ID, "redirect_uris": ["https://c.test/cb"] * 11},
        {"client_id": CLIENT_ID, "redirect_uris": [42]},
        {
            "client_id": CLIENT_ID,
            "redirect_uris": ["https://c.test/cb"],
            "grant_types": "authorization_code",
        },
        {
            "client_id": CLIENT_ID,
            "redirect_uris": ["https://c.test/cb"],
            "grant_types": ["client_credentials"],
        },
        {
            "client_id": CLIENT_ID,
            "redirect_uris": ["https://c.test/cb"],
            "token_endpoint_auth_method": "client_secret_post",
        },
    ],
)
def test_malformed_documents_are_refused(document: object) -> None:
    with pytest.raises(OAuthError):
        validate_metadata(document, expected_client_id=CLIENT_ID)


def test_a_long_client_name_is_truncated_rather_than_rejected() -> None:
    normalized = validate_metadata(
        {"client_id": CLIENT_ID, "client_name": "x" * 5000, "redirect_uris": ["https://c.test/cb"]},
        expected_client_id=CLIENT_ID,
    )

    assert len(str(normalized["client_name"])) == 200


# ---------------------------------------------------------------- redirects


@pytest.mark.parametrize(
    "uri",
    [
        "https://client.test/cb",
        "http://127.0.0.1:1234/cb",
        "http://localhost:1234/cb",
        "http://[::1]:1234/cb",
    ],
)
def test_acceptable_redirect_uris(uri: str) -> None:
    assert validate_redirect_uri(uri) == uri


@pytest.mark.parametrize(
    "uri",
    [
        "http://client.test/cb",
        "https://client.test/cb#frag",
        "/relative/cb",
        "javascript:alert(1)",
        "ftp://client.test/cb",
    ],
)
def test_unacceptable_redirect_uris(uri: str) -> None:
    with pytest.raises(OAuthError):
        validate_redirect_uri(uri)


def test_redirect_matching_is_exact_never_prefix() -> None:
    registered = ("https://client.test/cb",)

    assert match_redirect_uri(registered, "https://client.test/cb") == "https://client.test/cb"
    for attempt in (
        "https://client.test/cb/../evil",
        "https://client.test/cb?next=https://evil.test",
        "https://client.test/cbevil",
        "https://client.test/CB",
    ):
        with pytest.raises(OAuthError):
            match_redirect_uri(registered, attempt)


# --------------------------------------------------------------- SSRF fence


@pytest.mark.parametrize(
    "client_id",
    ["http://client.test/app.json", "https://client.test/app.json#frag", "not-a-url", ""],
)
def test_only_https_fragmentless_urls_count_as_cimd_ids(client_id: str) -> None:
    assert is_cimd_client_id(client_id) is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    "client_id",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata, plain http
        "https://127.0.0.1/app.json",  # loopback
        "https://localhost/app.json",
        "https://10.0.0.1/app.json",  # RFC1918
        "https://192.168.1.1/app.json",
        "https://[::1]/app.json",
        "file:///etc/passwd",
    ],
)
async def test_the_real_fetcher_refuses_ssrf_targets(client_id: str) -> None:
    with pytest.raises(OAuthError) as excinfo:
        await CimdFetcher().fetch(client_id)

    assert excinfo.value.error == "invalid_client_metadata"
    # The message must not echo anything about the target beyond the rule.
    assert client_id not in excinfo.value.description


# --------------------------------------------------------------------- PKCE


def test_a_valid_s256_pair_verifies() -> None:
    verifier = "a" * 43
    challenge = challenge_for(verifier)

    assert validate_challenge(challenge, "S256") == challenge
    verify_verifier(verifier, challenge)  # does not raise


def test_plain_is_refused_not_downgraded() -> None:
    with pytest.raises(OAuthError) as excinfo:
        validate_challenge("x" * 43, "plain")

    assert excinfo.value.error == "invalid_request"
    assert "plain" in excinfo.value.description


def test_a_missing_or_malformed_challenge_is_refused() -> None:
    with pytest.raises(OAuthError):
        validate_challenge(None, "S256")
    with pytest.raises(OAuthError):
        validate_challenge("too-short", "S256")
    with pytest.raises(OAuthError):
        validate_challenge("!" * 43, "S256")


def test_the_challenge_method_may_be_omitted_and_defaults_to_s256() -> None:
    challenge = challenge_for("b" * 50)

    assert validate_challenge(challenge, None) == challenge


@pytest.mark.parametrize("verifier", [None, "", "short", "x" * 129, "bad chars here" * 5])
def test_a_malformed_verifier_is_invalid_grant(verifier: str | None) -> None:
    with pytest.raises(OAuthError) as excinfo:
        verify_verifier(verifier, challenge_for("a" * 43))

    assert excinfo.value.error == "invalid_grant"


def test_a_wrong_verifier_is_invalid_grant() -> None:
    with pytest.raises(OAuthError) as excinfo:
        verify_verifier("b" * 43, challenge_for("a" * 43))

    assert excinfo.value.error == "invalid_grant"
