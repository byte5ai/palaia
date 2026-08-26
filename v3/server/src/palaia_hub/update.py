"""Release-channel update check (SPEC-501 deliverable #3/#4).

Compares this hub's own version against the latest version published under
its configured channel's GHCR tag — ``GET /api/update/check``'s job. Three
states, and only three: ``up_to_date``, ``update_available``,
``cannot_check``. The last one is deliberate: any network failure, timeout,
oversized response, or unparsable answer collapses to "could not check",
never an error page (this SPEC's non-negotiable: offline-safe).

The remote version comes from the GHCR image manifest's own
``org.opencontainers.image.version`` OCI annotation (set by the release
workflow's ``docker/build-push-action`` ``annotations`` input — see
``.github/workflows/v3-release.yml``), read via the same anonymous
token-then-manifest flow ``docker pull`` uses against a public GHCR image
(`GHCR API reference
<https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry>`_,
`OCI Distribution Spec token auth
<https://github.com/opencontainers/distribution-spec/blob/main/spec.md#endpoints>`_).
No credentials are ever sent or needed — palaia's own images are public.

The ``edge`` channel is never version-compared: it moves on every ``main``
build and carries no stable ``org.opencontainers.image.version`` (its own
tag is a moving target, not a release), so checking it would either lie
about "up to date" or nag on every commit. It reports ``cannot_check`` with
an honest reason instead.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import httpx

Channel = Literal["edge", "beta", "stable"]
UpdateState = Literal["up_to_date", "update_available", "cannot_check"]
Deployment = Literal[
    "compose", "umbrel", "casaos", "runtipi", "truenas", "home_assistant", "unknown"
]

#: The published image this hub's channel tags live on. Not configurable
#: (like the curated index's pinned public key, MASTERPLAN-consistent):
#: this is palaia's own release, not a bring-your-own registry setting.
DEFAULT_OWNER = "byte5ai"
DEFAULT_IMAGE = "palaia-hub"
DEFAULT_REGISTRY = "https://ghcr.io"

DEFAULT_TIMEOUT_SECONDS = 6.0
DEFAULT_MAX_BYTES = 2 * 1024 * 1024

_MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)

_STORE_NAMES: dict[str, str] = {
    "umbrel": "Umbrel",
    "casaos": "CasaOS",
    "runtipi": "Runtipi",
    "truenas": "TrueNAS SCALE",
    "home_assistant": "Home Assistant",
}


@dataclass(frozen=True, slots=True)
class UpdateGuidance:
    """What the dashboard's banner tells the operator to do next.

    ``kind`` picks the shape: ``store`` names the app store that owns
    updates on this deployment (SPEC-501 deliverable #4 — "the dashboard
    points at it by name instead of pretending"); ``command`` is the
    compose helper's two commands; ``manual`` is the honest fallback for an
    unrecognized deployment (a plain docker/podman recreate, spelled out
    with no assumed tool).
    """

    kind: Literal["store", "command", "manual"]
    message: str
    commands: tuple[str, ...] = ()


def update_guidance(deployment: Deployment) -> UpdateGuidance:
    """SPEC-501 deliverable #4: per-environment update instructions.

    Never a silent in-place binary swap — every path here ends with the
    operator (or their app store) doing the recreate.
    """
    store_name = _STORE_NAMES.get(deployment)
    if store_name is not None:
        return UpdateGuidance(
            kind="store",
            message=f"{store_name} manages updates for this install — open it there to update.",
        )
    if deployment == "compose":
        return UpdateGuidance(
            kind="command",
            message="Run the update helper on the machine running your compose file, "
            "then restart the container:",
            commands=("palaia-hub update", "docker compose pull", "docker compose up -d"),
        )
    return UpdateGuidance(
        kind="manual",
        message="Pull the new image for your channel and recreate the container — "
        "how you started it is how you restart it.",
    )


@dataclass(frozen=True, slots=True)
class UpdateCheckResult:
    state: UpdateState
    channel: Channel
    current_version: str
    latest_version: str | None
    checked_at: float
    deployment: Deployment
    guidance: UpdateGuidance
    #: Only set when ``state == "cannot_check"`` — the honest reason, never
    #: shown as an error page (per this SPEC's offline-safe requirement).
    reason: str | None = None


def _parse_version(text: str) -> tuple[int, ...] | None:
    """Best-effort ``1.2.3`` -> ``(1, 2, 3)``. ``None`` for anything that
    doesn't look like a plain dotted-numeric version (a pre-release suffix
    like ``1.2.3-beta.1`` included) — those fall back to a straight string
    comparison in :func:`_compare_versions` instead of a false "equal"."""
    core = text.split("-", 1)[0].split("+", 1)[0]
    parts = core.split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _compare_versions(current: str, latest: str) -> UpdateState:
    if current == latest:
        return "up_to_date"
    current_parsed = _parse_version(current)
    latest_parsed = _parse_version(latest)
    if current_parsed is not None and latest_parsed is not None:
        return "update_available" if latest_parsed > current_parsed else "up_to_date"
    # Unparsable version strings on either side: any difference is reported
    # as an update rather than silently treated as "up to date" — a hub
    # that cannot tell versions apart should not tell the operator
    # everything is fine.
    return "update_available"


async def _fetch_manifest_version(
    client: httpx.AsyncClient,
    *,
    owner: str,
    image: str,
    channel: str,
    registry: str,
    timeout_seconds: float,
    max_bytes: int,
) -> str:
    """Return the remote channel tag's ``org.opencontainers.image.version``
    annotation, or raise :class:`_CheckFailed` naming exactly why not."""
    scope = f"repository:{owner}/{image}:pull"
    try:
        token_response = await client.get(
            f"{registry}/token",
            params={"service": "ghcr.io", "scope": scope},
            timeout=timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise _CheckFailed(
            f"timed out getting a registry token after {timeout_seconds:.0f}s"
        ) from exc
    except httpx.RequestError as exc:
        raise _CheckFailed(f"network error getting a registry token: {exc}") from exc
    if token_response.status_code >= 400:
        raise _CheckFailed(f"registry token endpoint answered HTTP {token_response.status_code}")
    try:
        token = token_response.json()["token"]
    except (ValueError, KeyError, TypeError) as exc:
        raise _CheckFailed("registry token response was not the expected shape") from exc

    manifest_url = f"{registry}/v2/{owner}/{image}/manifests/{channel}"
    try:
        manifest_response = await client.get(
            manifest_url,
            headers={"Authorization": f"Bearer {token}", "Accept": _MANIFEST_ACCEPT},
            timeout=timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise _CheckFailed(
            f"timed out fetching the {channel!r} manifest after {timeout_seconds:.0f}s"
        ) from exc
    except httpx.RequestError as exc:
        raise _CheckFailed(f"network error fetching the {channel!r} manifest: {exc}") from exc
    if manifest_response.status_code == 404:
        raise _CheckFailed(f"no {channel!r} tag is published for {owner}/{image} yet")
    if manifest_response.status_code >= 400:
        raise _CheckFailed(
            f"registry answered HTTP {manifest_response.status_code} for the manifest"
        )
    if len(manifest_response.content) > max_bytes:
        raise _CheckFailed(
            f"manifest response too large ({len(manifest_response.content)} > {max_bytes} bytes)"
        )
    try:
        manifest = manifest_response.json()
    except ValueError as exc:
        raise _CheckFailed("manifest response was not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise _CheckFailed("manifest response was not a JSON object")
    annotations = manifest.get("annotations")
    version = (
        annotations.get("org.opencontainers.image.version")
        if isinstance(annotations, dict)
        else None
    )
    if not isinstance(version, str) or not version:
        raise _CheckFailed(f"the {channel!r} manifest carries no published version annotation")
    return version


class _CheckFailed(RuntimeError):
    """Internal control-flow only — always caught inside :func:`check_for_update`."""


async def check_for_update(
    *,
    channel: Channel,
    current_version: str,
    deployment: Deployment = "unknown",
    owner: str = DEFAULT_OWNER,
    image: str = DEFAULT_IMAGE,
    registry: str = DEFAULT_REGISTRY,
    client: httpx.AsyncClient | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> UpdateCheckResult:
    """The whole of ``GET /api/update/check`` in one call.

    Never raises — a network failure, timeout, oversized response, or a
    manifest with no version annotation all become ``state="cannot_check"``
    with ``reason`` naming why, per this SPEC's "could not check is a
    state, never an error page" rule.
    """
    guidance = update_guidance(deployment)
    checked_at = time.time()
    if channel == "edge":
        return UpdateCheckResult(
            state="cannot_check",
            channel=channel,
            current_version=current_version,
            latest_version=None,
            checked_at=checked_at,
            deployment=deployment,
            guidance=guidance,
            reason="the edge channel tracks every change and isn't version-checked",
        )

    owns_client = client is None
    http = client or httpx.AsyncClient()
    try:
        latest_version = await _fetch_manifest_version(
            http,
            owner=owner,
            image=image,
            channel=channel,
            registry=registry,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
    except _CheckFailed as exc:
        return UpdateCheckResult(
            state="cannot_check",
            channel=channel,
            current_version=current_version,
            latest_version=None,
            checked_at=checked_at,
            deployment=deployment,
            guidance=guidance,
            reason=str(exc),
        )
    finally:
        if owns_client:
            await http.aclose()

    state = _compare_versions(current_version, latest_version)
    return UpdateCheckResult(
        state=state,
        channel=channel,
        current_version=current_version,
        latest_version=latest_version,
        checked_at=checked_at,
        deployment=deployment,
        guidance=guidance,
    )


__all__ = [
    "DEFAULT_IMAGE",
    "DEFAULT_OWNER",
    "DEFAULT_REGISTRY",
    "Channel",
    "Deployment",
    "UpdateCheckResult",
    "UpdateGuidance",
    "UpdateState",
    "check_for_update",
    "update_guidance",
]
