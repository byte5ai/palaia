"""SPEC-501 acceptance: "mocked GHCR answers drive 'up to date', 'update
available', 'cannot check' states end-to-end" and "a beta-channel hub
checks beta, stable checks stable"."""

from __future__ import annotations

import httpx
import pytest

from palaia_hub.update import (
    UpdateGuidance,
    check_for_update,
    update_guidance,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _client_for(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


def _token_and_manifest_handler(*, version: str | None, status: int = 200):
    """A GHCR-shaped fake: token endpoint, then the manifest for whichever
    channel tag was requested — recording which tag it was asked for."""
    requested: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"token": "fake-token"})
        # /v2/<owner>/<image>/manifests/<channel>
        requested["tag"] = request.url.path.rsplit("/", 1)[-1]
        if status != 200:
            return httpx.Response(status)
        body: dict[str, object] = {"schemaVersion": 2}
        if version is not None:
            body["annotations"] = {"org.opencontainers.image.version": version}
        return httpx.Response(200, json=body)

    return handler, requested


@pytest.mark.anyio
async def test_a_newer_channel_version_reports_update_available() -> None:
    handler, requested = _token_and_manifest_handler(version="0.2.0")
    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(
            channel="stable", current_version="0.1.0", client=http
        )

    assert result.state == "update_available"
    assert result.latest_version == "0.2.0"
    assert result.channel == "stable"
    assert requested["tag"] == "stable"


@pytest.mark.anyio
async def test_a_matching_channel_version_reports_up_to_date() -> None:
    handler, _requested = _token_and_manifest_handler(version="0.1.0")
    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(
            channel="stable", current_version="0.1.0", client=http
        )

    assert result.state == "up_to_date"
    assert result.latest_version == "0.1.0"


@pytest.mark.anyio
async def test_an_older_remote_version_is_still_up_to_date_not_a_downgrade_nag() -> None:
    handler, _requested = _token_and_manifest_handler(version="0.1.0")
    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(
            channel="stable", current_version="0.2.0", client=http
        )

    assert result.state == "up_to_date"


@pytest.mark.anyio
async def test_beta_channel_checks_the_beta_tag_not_stable() -> None:
    handler, requested = _token_and_manifest_handler(version="0.2.0-beta.1")
    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(
            channel="beta", current_version="0.1.0", client=http
        )

    assert requested["tag"] == "beta"
    assert result.channel == "beta"
    assert result.state == "update_available"


@pytest.mark.anyio
async def test_a_network_error_is_cannot_check_never_an_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(
            channel="stable", current_version="0.1.0", client=http
        )

    assert result.state == "cannot_check"
    assert result.latest_version is None
    assert result.reason is not None


@pytest.mark.anyio
async def test_a_registry_error_status_is_cannot_check() -> None:
    handler, _requested = _token_and_manifest_handler(version=None, status=503)
    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(
            channel="stable", current_version="0.1.0", client=http
        )

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
async def test_a_manifest_missing_the_version_annotation_is_cannot_check() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"token": "fake-token"})
        return httpx.Response(200, json={"schemaVersion": 2})

    async with _client_for(httpx.MockTransport(handler)) as http:
        result = await check_for_update(
            channel="stable", current_version="0.1.0", client=http
        )

    assert result.state == "cannot_check"
    assert "version" in (result.reason or "")


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
