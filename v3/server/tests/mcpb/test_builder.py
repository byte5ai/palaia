"""Manifest personalization, and a real pack+sign when `mcpb` is available."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from palaia_hub.mcpb.builder import BundleRequest, _personalize_manifest, build_bundle
from palaia_hub.mcpb.template import TemplateNotFoundError, mcpb_binary, template_dir

TEMPLATE_MANIFEST = json.loads((template_dir(env={}) / "manifest.template.json").read_text())


def _mcpb_available() -> bool:
    try:
        mcpb_binary(template_dir(env={}), env={})
    except TemplateNotFoundError:
        return False
    return True


# --------------------------------------------------------------------- pure


def test_token_variant_bakes_in_the_hub_url_and_token_and_turns_oauth_off() -> None:
    request = BundleRequest(
        hub_url="https://hub.example.com/mcp/default",
        profile="default",
        variant="token",
        version="0.1.2",
        token="plt_abc.def",
    )
    manifest = _personalize_manifest(TEMPLATE_MANIFEST, request)

    assert manifest["version"] == "0.1.2"
    uc = manifest["user_config"]
    assert uc["hub_url"]["default"] == "https://hub.example.com/mcp/default"
    assert uc["token"]["default"] == "plt_abc.def"
    assert uc["oauth"]["default"] is False
    assert uc["profile"]["default"] == "default"


def test_oauth_variant_contains_no_secret_at_all() -> None:
    """The acceptance criterion, checked as a fact about the dict."""
    request = BundleRequest(
        hub_url="https://hub.example.com/mcp/default",
        profile="default",
        variant="oauth",
        version="0.1.2",
        issuer="https://hub.example.com",
    )
    manifest = _personalize_manifest(TEMPLATE_MANIFEST, request)

    uc = manifest["user_config"]
    assert uc["oauth"]["default"] is True
    assert uc["issuer"]["default"] == "https://hub.example.com"
    assert "default" not in uc["token"]
    # Belt and suspenders: no string in the whole manifest looks like the
    # one thing a token could look like (the `plt_` prefix from SPEC-108).
    assert "plt_" not in json.dumps(manifest)


def test_personalization_does_not_mutate_the_template_in_place() -> None:
    before = json.dumps(TEMPLATE_MANIFEST, sort_keys=True)
    _personalize_manifest(
        TEMPLATE_MANIFEST,
        BundleRequest(
            hub_url="https://hub.example.com/mcp/default",
            profile="default",
            variant="token",
            version="9.9.9",
            token="plt_should.notleak",
        ),
    )
    after = json.dumps(TEMPLATE_MANIFEST, sort_keys=True)
    assert before == after


# ---------------------------------------------------------------- real pack


@pytest.mark.skipif(
    not _mcpb_available(), reason="mcpb CLI not installed (run `npm ci` in the template dir)"
)
def test_build_bundle_produces_a_valid_signed_zip_with_the_personalized_manifest(
    tmp_path: Path,
) -> None:
    request = BundleRequest(
        hub_url="https://hub.example.com/mcp/default",
        profile="default",
        variant="token",
        version="0.9.9",
        token="plt_realbuild.token",
    )

    data = build_bundle(request, home=tmp_path)

    # A real, valid zip — readable without any MCPB-specific tooling.
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert "proxy/palaia-proxy.mjs" in names
        assert "icon.png" in names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["user_config"]["hub_url"]["default"] == request.hub_url
        assert manifest["user_config"]["token"]["default"] == request.token
        assert manifest["version"] == "0.9.9"

    # A real PKCS#7 signature block was appended (SPEC-306 deliverable #2 —
    # see tools/build-mcpb/SIGNING.md for exactly what this proves and does
    # not prove about trust).
    assert b"MCPB_SIG_V1" in data
    assert b"MCPB_SIG_END" in data

    # Signing persisted a reusable identity under `home`, not a fresh one
    # per call.
    assert (tmp_path / "mcpb" / "signing-cert.pem").exists()


@pytest.mark.skipif(
    not _mcpb_available(), reason="mcpb CLI not installed (run `npm ci` in the template dir)"
)
def test_build_bundle_reuses_the_same_signing_identity_across_two_downloads(
    tmp_path: Path,
) -> None:
    request = BundleRequest(
        hub_url="https://hub.example.com/mcp/default",
        profile="default",
        variant="token",
        version="0.9.9",
        token="plt_a.token",
    )
    build_bundle(request, home=tmp_path)
    cert_bytes_first = (tmp_path / "mcpb" / "signing-cert.pem").read_bytes()

    build_bundle(
        BundleRequest(
            hub_url=request.hub_url,
            profile=request.profile,
            variant="token",
            version="0.9.9",
            token="plt_b.different_token",
        ),
        home=tmp_path,
    )
    cert_bytes_second = (tmp_path / "mcpb" / "signing-cert.pem").read_bytes()

    assert cert_bytes_first == cert_bytes_second
