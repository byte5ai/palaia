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
token-then-manifest flow ``docker pull`` uses against a public GHCR image.
A multi-platform channel tag resolves to an OCI *index*; the annotation is
read from the index itself when present and otherwise from the first
linux/amd64|arm64 platform manifest the index points at (#319: buildx
writes ``--annotation`` to the platform manifests only unless told to
annotate the index too, and older releases were built that way)
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

import re
import time
from dataclasses import dataclass
from typing import Literal

import httpx

from .security.bounded_fetch import ResponseTooLargeError, get_bounded

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

_INDEX_MEDIA_TYPES = frozenset(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    )
)
_IMAGE_MANIFEST_MEDIA_TYPES = (
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
)
_MANIFEST_ACCEPT = ", ".join((*sorted(_INDEX_MEDIA_TYPES), *_IMAGE_MANIFEST_MEDIA_TYPES))
_IMAGE_MANIFEST_ACCEPT = ", ".join(_IMAGE_MANIFEST_MEDIA_TYPES)
_VERSION_ANNOTATION = "org.opencontainers.image.version"
#: Platform children of an index worth descending into for the annotation
#: — the two the release workflow builds. Attestation manifests (buildx
#: provenance/SBOM) advertise ``architecture: unknown`` and are skipped.
_PLATFORM_ARCHITECTURES = frozenset(("amd64", "arm64"))

_VERSION_RE = re.compile(
    r"^(?P<core>\d+(?:\.\d+)*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_IDENTIFIER_RUNS_RE = re.compile(r"\d+|[^\d]+")

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


#: Sortable form of a version: ``(core, 1, ())`` for a final release and
#: ``(core, 0, <pre-release key>)`` for a pre-release, so that a final
#: release outranks every pre-release of the same core (SemVer 2.0 §11).
_VersionKey = tuple[tuple[int, ...], int, tuple[tuple[tuple[int, int, str], ...], ...]]


def _identifier_key(identifier: str) -> tuple[tuple[int, int, str], ...]:
    """SemVer §11 ordering for one pre-release identifier: numeric
    identifiers compare numerically and rank below alphanumeric ones, which
    compare lexically. One pragmatic extension: an alphanumeric identifier
    is split into its text and digit runs (``rc10`` -> ``rc``, ``10``) so
    the house style ``rc1 < rc2 < rc10`` holds, where strict ASCII order
    would put ``rc10`` before ``rc2``."""
    runs = _IDENTIFIER_RUNS_RE.findall(identifier)
    return tuple((0, int(run), "") if run.isdigit() else (1, 0, run) for run in runs)


def _parse_version(text: str) -> _VersionKey | None:
    """Best-effort SemVer parse into a sortable key, ``None`` for anything
    that isn't ``<digits>(.<digits>)*`` with an optional ``-<pre-release>``
    and optional ``+<build>`` — those make :func:`_compare_versions` fall
    back to "any difference is an update". Build metadata (``+edge.<sha>``
    on the edge channel's annotation) is ignored per SemVer §10; the
    pre-release part orders per §11 with ``1.2.3-rc1 < 1.2.3``."""
    match = _VERSION_RE.match(text.strip())
    if match is None:
        return None
    core = tuple(int(part) for part in match.group("core").split("."))
    prerelease = match.group("prerelease")
    if prerelease is None:
        return (core, 1, ())
    return (core, 0, tuple(_identifier_key(part) for part in prerelease.split(".")))


def _compare_versions(current: str, latest: str) -> UpdateState:
    """``update_available`` only when ``latest`` outranks ``current`` —
    never for an equal version and never for a downgrade (a hub on
    ``3.0.0`` is not nagged about ``3.0.0-rc2``)."""
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


def _version_annotation(document: object) -> str | None:
    """The ``org.opencontainers.image.version`` annotation of a manifest,
    index, or index child descriptor — ``None`` when absent or malformed."""
    if not isinstance(document, dict):
        return None
    annotations = document.get("annotations")
    if not isinstance(annotations, dict):
        return None
    version = annotations.get(_VERSION_ANNOTATION)
    return version if isinstance(version, str) and version else None


def _is_index(manifest: dict[str, object]) -> bool:
    return manifest.get("mediaType") in _INDEX_MEDIA_TYPES or isinstance(
        manifest.get("manifests"), list
    )


def _first_platform_child(index: dict[str, object]) -> dict[str, object] | None:
    """The first linux/amd64|arm64 child descriptor of an OCI index, skipping
    buildx attestation entries (``architecture: unknown``)."""
    children = index.get("manifests")
    if not isinstance(children, list):
        return None
    for child in children:
        if not isinstance(child, dict):
            continue
        platform = child.get("platform")
        if not isinstance(platform, dict):
            continue
        if (
            platform.get("os") == "linux"
            and platform.get("architecture") in _PLATFORM_ARCHITECTURES
        ):
            return child
    return None


async def _get_registry_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    what: str,
    not_found: str,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    timeout_seconds: float,
    max_bytes: int,
) -> dict[str, object]:
    """One registry GET, decoded as a JSON object — every failure mode
    becomes a :class:`_CheckFailed` naming ``what`` was being fetched."""
    try:
        response = await get_bounded(
            client,
            url,
            headers=headers,
            params=params,
            timeout=timeout_seconds,
            max_bytes=max_bytes,
        )
    except ResponseTooLargeError as exc:
        raise _CheckFailed(f"{what} {exc}") from exc
    except httpx.TimeoutException as exc:
        raise _CheckFailed(f"timed out fetching {what} after {timeout_seconds:.0f}s") from exc
    except httpx.RequestError as exc:
        raise _CheckFailed(f"network error fetching {what}: {exc}") from exc
    if response.status_code == 404:
        raise _CheckFailed(not_found)
    if response.status_code >= 400:
        raise _CheckFailed(f"registry answered HTTP {response.status_code} for {what}")
    try:
        document = response.json()
    except ValueError as exc:
        raise _CheckFailed(f"{what} response was not valid JSON") from exc
    if not isinstance(document, dict):
        raise _CheckFailed(f"{what} response was not a JSON object")
    return document


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
    annotation, or raise :class:`_CheckFailed` naming exactly why not.

    Reads the annotation from the tag's manifest itself; when that is an
    OCI index without one (#319), from the first linux platform child's
    descriptor, and failing that from the child manifest fetched by digest
    (one extra request, same anonymous token)."""
    scope = f"repository:{owner}/{image}:pull"
    token_document = await _get_registry_json(
        client,
        f"{registry}/token",
        what="a registry token",
        not_found="registry token endpoint answered HTTP 404",
        params={"service": "ghcr.io", "scope": scope},
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
    )
    token = token_document.get("token")
    if not isinstance(token, str) or not token:
        raise _CheckFailed("registry token response was not the expected shape")

    manifests_url = f"{registry}/v2/{owner}/{image}/manifests"
    manifest = await _get_registry_json(
        client,
        f"{manifests_url}/{channel}",
        what=f"the {channel!r} manifest",
        not_found=f"no {channel!r} tag is published for {owner}/{image} yet",
        headers={"Authorization": f"Bearer {token}", "Accept": _MANIFEST_ACCEPT},
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
    )
    version = _version_annotation(manifest)
    if version is None and _is_index(manifest):
        child = _first_platform_child(manifest)
        if child is not None:
            version = _version_annotation(child)
        digest = child.get("digest") if child is not None else None
        if version is None and isinstance(digest, str) and digest:
            child_manifest = await _get_registry_json(
                client,
                f"{manifests_url}/{digest}",
                what=f"the {channel!r} platform manifest",
                not_found=f"the {channel!r} index points at a platform manifest "
                f"the registry does not have ({digest})",
                headers={"Authorization": f"Bearer {token}", "Accept": _IMAGE_MANIFEST_ACCEPT},
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            )
            version = _version_annotation(child_manifest)
    if version is None:
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
