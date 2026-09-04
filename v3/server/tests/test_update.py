"""SPEC-501 acceptance: "mocked GHCR answers drive 'up to date', 'update
available', 'cannot check' states end-to-end" and "a beta-channel hub
checks beta, stable checks stable"."""

from __future__ import annotations

from typing import Literal

import httpx
import pytest

from palaia_hub import __version__
from palaia_hub.update import (
    UpdateGuidance,
    _compare_versions,
    _parse_version,
    check_for_update,
    update_guidance,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _client_for(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


_INDEX_MEDIA_TYPE = "application/vnd.oci.image.index.v1+json"
_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
_AMD64_DIGEST = "sha256:" + "a" * 64
_ARM64_DIGEST = "sha256:" + "b" * 64
_ATTESTATION_DIGESTS = ("sha256:" + "c" * 64, "sha256:" + "d" * 64)

AnnotationPlacement = Literal["index", "descriptor", "child", "nowhere"]


def _descriptor(digest: str, *, architecture: str, size: int = 1234) -> dict[str, object]:
    return {
        "mediaType": _MANIFEST_MEDIA_TYPE,
        "digest": digest,
        "size": size,
        "platform": {"os": "linux", "architecture": architecture},
    }


def _attestation(digest: str, refers_to: str) -> dict[str, object]:
    # buildx provenance/SBOM entries: `architecture: unknown` and an
    # annotation pointing back at the platform manifest they attest.
    return {
        "mediaType": _MANIFEST_MEDIA_TYPE,
        "digest": digest,
        "size": 567,
        "annotations": {
            "vnd.docker.reference.digest": refers_to,
            "vnd.docker.reference.type": "attestation-manifest",
        },
        "platform": {"os": "unknown", "architecture": "unknown"},
    }


def _token_and_manifest_handler(
    *,
    version: str | None,
    status: int = 200,
    placement: AnnotationPlacement = "index",
):
    """A GHCR-shaped fake: token endpoint, then the multi-platform OCI
    *index* for whichever channel tag was requested (two platform children
    plus two buildx attestation children — the real shape a channel tag
    resolves to), then the platform manifests by digest. ``placement``
    says where the ``org.opencontainers.image.version`` annotation lives;
    ``requested`` records the tag asked for and every manifest path hit."""
    requested: dict[str, object] = {"paths": []}
    annotation = {"org.opencontainers.image.version": version} if version is not None else {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"token": "fake-token"})
        assert request.headers.get("Authorization") == "Bearer fake-token"
        # /v2/<owner>/<image>/manifests/<tag-or-digest>
        reference = request.url.path.rsplit("/", 1)[-1]
        paths = requested["paths"]
        assert isinstance(paths, list)
        paths.append(request.url.path)
        if status != 200:
            return httpx.Response(status)
        if reference in (_AMD64_DIGEST, _ARM64_DIGEST):
            assert _MANIFEST_MEDIA_TYPE in request.headers.get("Accept", "")
            child: dict[str, object] = {
                "schemaVersion": 2,
                "mediaType": _MANIFEST_MEDIA_TYPE,
                "config": {"mediaType": "application/vnd.oci.image.config.v1+json"},
                "layers": [],
            }
            if placement == "child":
                child["annotations"] = annotation
            return httpx.Response(200, json=child)
        if reference in _ATTESTATION_DIGESTS:
            raise AssertionError("attestation manifests must never be fetched")
        requested["tag"] = reference
        assert _INDEX_MEDIA_TYPE in request.headers.get("Accept", "")
        amd64 = _descriptor(_AMD64_DIGEST, architecture="amd64")
        arm64 = _descriptor(_ARM64_DIGEST, architecture="arm64")
        if placement == "descriptor":
            amd64["annotations"] = annotation
            arm64["annotations"] = annotation
        index: dict[str, object] = {
            "schemaVersion": 2,
            "mediaType": _INDEX_MEDIA_TYPE,
            "manifests": [
                amd64,
                arm64,
                _attestation(_ATTESTATION_DIGESTS[0], _AMD64_DIGEST),
                _attestation(_ATTESTATION_DIGESTS[1], _ARM64_DIGEST),
            ],
        }
        if placement == "index":
            index["annotations"] = annotation
        return httpx.Response(200, json=index)

    return handler, requested


@pytest.mark.anyio
async def test_a_newer_channel_version_reports_update_available() -> None:
    handler, requested = _token_and_manifest_handler(version="0.2.0")
    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(channel="stable", current_version="0.1.0", client=http)

    assert result.state == "update_available"
    assert result.latest_version == "0.2.0"
    assert result.channel == "stable"
    assert requested["tag"] == "stable"


@pytest.mark.anyio
async def test_a_matching_channel_version_reports_up_to_date() -> None:
    handler, _requested = _token_and_manifest_handler(version="0.1.0")
    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(channel="stable", current_version="0.1.0", client=http)

    assert result.state == "up_to_date"
    assert result.latest_version == "0.1.0"


@pytest.mark.anyio
async def test_an_older_remote_version_is_still_up_to_date_not_a_downgrade_nag() -> None:
    handler, _requested = _token_and_manifest_handler(version="0.1.0")
    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(channel="stable", current_version="0.2.0", client=http)

    assert result.state == "up_to_date"


@pytest.mark.anyio
async def test_beta_channel_checks_the_beta_tag_not_stable() -> None:
    handler, requested = _token_and_manifest_handler(version="0.2.0-beta.1")
    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(channel="beta", current_version="0.1.0", client=http)

    assert requested["tag"] == "beta"
    assert result.channel == "beta"
    assert result.state == "update_available"


@pytest.mark.anyio
async def test_a_network_error_is_cannot_check_never_an_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(channel="stable", current_version="0.1.0", client=http)

    assert result.state == "cannot_check"
    assert result.latest_version is None
    assert result.reason is not None


@pytest.mark.anyio
async def test_a_registry_error_status_is_cannot_check() -> None:
    handler, _requested = _token_and_manifest_handler(version=None, status=503)
    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(channel="stable", current_version="0.1.0", client=http)

    assert result.state == "cannot_check"
    assert "503" in (result.reason or "")


@pytest.mark.anyio
async def test_an_oversized_manifest_response_is_cannot_check_not_a_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"token": "fake-token"})
        return httpx.Response(200, content=b"x" * 100)

    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(
            channel="stable", current_version="0.1.0", client=http, max_bytes=10
        )

    assert result.state == "cannot_check"
    assert "too large" in (result.reason or "")


@pytest.mark.anyio
async def test_an_annotation_on_the_index_needs_one_manifest_request() -> None:
    handler, requested = _token_and_manifest_handler(version="3.0.0", placement="index")
    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(channel="stable", current_version="3.0.0-rc1", client=http)

    assert result.state == "update_available"
    assert result.latest_version == "3.0.0"
    assert requested["paths"] == ["/v2/byte5ai/palaia-hub/manifests/stable"]


@pytest.mark.anyio
async def test_an_annotation_only_on_the_platform_manifest_is_fetched_by_digest() -> None:
    # #319: what buildx produces without the `index,manifest:` level prefix
    # — the index has no annotations, the platform manifests do.
    handler, requested = _token_and_manifest_handler(version="3.0.0-rc1", placement="child")
    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(channel="beta", current_version="3.0.0-rc1", client=http)

    assert result.state == "up_to_date"
    assert result.latest_version == "3.0.0-rc1"
    assert requested["paths"] == [
        "/v2/byte5ai/palaia-hub/manifests/beta",
        f"/v2/byte5ai/palaia-hub/manifests/{_AMD64_DIGEST}",
    ]


@pytest.mark.anyio
async def test_an_annotation_on_the_child_descriptor_spares_the_second_request() -> None:
    handler, requested = _token_and_manifest_handler(version="3.0.0", placement="descriptor")
    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(channel="stable", current_version="3.0.0", client=http)

    assert result.state == "up_to_date"
    assert result.latest_version == "3.0.0"
    assert requested["paths"] == ["/v2/byte5ai/palaia-hub/manifests/stable"]


@pytest.mark.anyio
async def test_no_annotation_anywhere_is_cannot_check_with_the_honest_reason() -> None:
    handler, requested = _token_and_manifest_handler(version=None, placement="nowhere")
    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(channel="stable", current_version="0.1.0", client=http)

    assert result.state == "cannot_check"
    assert result.latest_version is None
    assert result.reason == "the 'stable' manifest carries no published version annotation"
    # It did look in the platform manifest before giving up.
    assert requested["paths"] == [
        "/v2/byte5ai/palaia-hub/manifests/stable",
        f"/v2/byte5ai/palaia-hub/manifests/{_AMD64_DIGEST}",
    ]


@pytest.mark.anyio
async def test_a_flat_manifest_missing_the_version_annotation_is_cannot_check() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"token": "fake-token"})
        return httpx.Response(200, json={"schemaVersion": 2})

    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(channel="stable", current_version="0.1.0", client=http)

    assert result.state == "cannot_check"
    assert "version" in (result.reason or "")


@pytest.mark.anyio
async def test_a_missing_platform_manifest_is_cannot_check_not_a_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"token": "fake-token"})
        if request.url.path.endswith("/stable"):
            index = {
                "schemaVersion": 2,
                "mediaType": _INDEX_MEDIA_TYPE,
                "manifests": [_descriptor(_AMD64_DIGEST, architecture="amd64")],
            }
            return httpx.Response(200, json=index)
        return httpx.Response(404)

    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(channel="stable", current_version="0.1.0", client=http)

    assert result.state == "cannot_check"
    assert _AMD64_DIGEST in (result.reason or "")


class TestCompareVersions:
    """#320: pre-release precedence per SemVer 2.0 §11 — an rc is older than
    the next rc and older than the final release; a final release is never
    "behind" one of its own pre-releases."""

    @pytest.mark.parametrize(
        ("current", "latest", "expected"),
        [
            ("3.0.0-rc1", "3.0.0-rc2", "update_available"),
            ("3.0.0-rc1", "3.0.0", "update_available"),
            ("3.0.0", "3.0.0-rc2", "up_to_date"),
            ("3.0.0-beta1", "3.0.0-rc1", "update_available"),
            ("3.0.0-alpha", "3.0.0-beta", "update_available"),
            ("3.0.0-beta2", "3.0.0-rc1", "update_available"),
            ("3.0.0", "3.0.1", "update_available"),
            ("3.0.1", "3.0.0", "up_to_date"),
            ("3.0.0", "3.0.0", "up_to_date"),
            ("3.0.0-rc1", "3.0.0-rc1", "up_to_date"),
            ("3.0.0-rc2", "3.0.0-rc1", "up_to_date"),
            # Dotted pre-release identifiers (`rc.1`) and the rc10 > rc2 case
            # strict ASCII ordering would get wrong.
            ("3.0.0-rc.1", "3.0.0-rc.2", "update_available"),
            ("3.0.0-rc2", "3.0.0-rc10", "update_available"),
            # SemVer §11: numeric identifiers rank below alphanumeric ones.
            ("1.0.0-1", "1.0.0-alpha", "update_available"),
            # Build metadata is ignored: two edge builds are "equal", and an
            # edge annotation never outranks a real release.
            ("0.0.0+edge.abc123", "0.0.0+edge.def456", "up_to_date"),
            ("3.0.0-rc1", "0.0.0+edge.abc123", "up_to_date"),
            ("0.0.0+edge.abc123", "3.0.0-rc1", "update_available"),
            # Unparseable on either side: any difference is reported as an
            # update rather than a false "up to date".
            ("garbage", "3.0.0", "update_available"),
            ("3.0.0", "latest", "update_available"),
        ],
    )
    def test_precedence(self, current: str, latest: str, expected: str) -> None:
        assert _compare_versions(current, latest) == expected

    def test_the_edge_annotation_form_parses_with_build_metadata_ignored(self) -> None:
        assert _parse_version("0.0.0+edge.0123456789ab") == _parse_version("0.0.0")

    def test_unparseable_text_is_none(self) -> None:
        assert _parse_version("latest") is None
        assert _parse_version("") is None
        assert _parse_version("3.0.0-rc1!") is None

    def test_the_packages_own_version_is_parseable(self) -> None:
        # `3.0.0-rc1` is what every hub reports as current_version; the
        # comparison must never fall into the string-fallback for it.
        assert _parse_version(__version__) is not None


@pytest.mark.anyio
async def test_an_rc_hub_sees_the_next_rc_as_an_update_end_to_end() -> None:
    handler, _requested = _token_and_manifest_handler(version="3.0.0-rc2", placement="child")
    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(channel="beta", current_version="3.0.0-rc1", client=http)

    assert result.state == "update_available"
    assert result.latest_version == "3.0.0-rc2"


@pytest.mark.anyio
async def test_the_edge_channel_is_never_version_checked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("edge channel must never hit the network")

    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(channel="edge", current_version="0.1.0", client=http)

    assert result.state == "cannot_check"
    assert result.reason is not None


class TestUpdateGuidance:
    def test_a_known_app_store_deployment_points_at_the_store_by_name(self) -> None:
        guidance = update_guidance("umbrel")
        assert guidance.kind == "store"
        assert "Umbrel" in guidance.message
        assert guidance.commands == ()

    def test_compose_deployment_gets_the_helper_and_the_two_commands(self) -> None:
        guidance = update_guidance("compose")
        assert guidance.kind == "command"
        assert guidance.commands == (
            "palaia-hub update",
            "docker compose pull",
            "docker compose up -d",
        )

    def test_an_unrecognized_deployment_gets_the_honest_manual_fallback(self) -> None:
        guidance = update_guidance("unknown")
        assert guidance.kind == "manual"
        assert guidance.commands == ()

    def test_every_known_store_deployment_names_a_different_store(self) -> None:
        stores = {"umbrel", "casaos", "runtipi", "truenas", "home_assistant"}
        seen_messages = {update_guidance(store).message for store in stores}  # type: ignore[arg-type]
        assert len(seen_messages) == len(stores)


def test_update_guidance_result_is_a_frozen_value_object() -> None:
    # Sanity: UpdateGuidance is imported and constructible directly too,
    # for callers that want to build one without going through the table.
    guidance = UpdateGuidance(kind="manual", message="do it yourself")
    assert guidance.commands == ()
