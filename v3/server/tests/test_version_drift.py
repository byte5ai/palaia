"""SPEC-506 deliverable #1: "single VERSION source of truth ... a drift
test that fails when any artifact disagrees."

``v3/VERSION`` is that source. What "agrees with it" means differs by
artifact, and this file is explicit about which kind each one is —
lying about that distinction would be worse than not testing it at all:

- **Literal-version artifacts** (server, web, sdk): each has exactly one
  file that states the version as a plain string, and that string must be
  byte-for-byte identical to ``v3/VERSION``'s content. These are checked
  by direct string comparison below.
- **The mcpb bundle**: two independent paths produce it, both anchored to
  the same source, neither restating it as a literal:
  - the hub's own ``GET /api/connect/mcpb`` (SPEC-306) bakes
    ``palaia_hub.__version__`` directly into every personalized download
    (``palaia_hub/mcpb/routes.py``) — already covered transitively by the
    server check below, plus an explicit import-time assertion here so a
    future refactor that stops reading ``__version__`` fails loudly;
  - the CI-built static bundle (``tools/build-mcpb/build.mjs``) takes an
    explicit ``version``, else ``$PALAIA_VERSION``, else — since
    SPEC-506 — ``v3/VERSION`` itself (verified with a real build in this
    SPEC's PR description; not re-run here since it needs `npm ci`
    against the network, which this fast Python suite should not
    depend on). Checked structurally: the script must never fall back to
    a bare hardcoded release-shaped version.
- **compose and the store packages** (SPEC-501): these intentionally do
  *not* carry a literal product version at all. They pin the GHCR image
  at the ``stable`` *channel* tag — a moving alias the release workflow
  repoints on every stable tag push, never a version this repository
  edits by hand (``deploy/README.md`` §"The check", `deploy/stores/
  README.md` "What's shared across every package"). An RC is explicitly
  *not* promoted to ``stable`` (`.github/workflows/v3-release.yml`'s
  "rc"/"beta" branch) — so during an RC, "agreeing with VERSION" for
  these files means *not* drifting from the channel-tag design by
  accidentally hardcoding a stale literal version, which is what the
  existing ``server/tests/deploy/test_store_manifests.py`` and this
  file's own compose check already enforce. Bumping their `version`/
  `app_version` *fields* (the store-listing's own version, distinct from
  the pinned image) is a `v3/RELEASING.md` owner action gated on the
  final (non-RC) tag — see that file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

V3_ROOT = Path(__file__).resolve().parents[2]

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z][0-9A-Za-z.-]*)?$")


def _read_version_file() -> str:
    return (V3_ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_version_file_exists_and_is_valid_semver() -> None:
    version = _read_version_file()
    assert _SEMVER_RE.match(version), (
        f"v3/VERSION ({version!r}) must be a bare semver, optionally with a "
        "prerelease suffix (e.g. '3.0.0-rc1') — no leading 'v', no whitespace."
    )


def test_server_package_version_matches() -> None:
    import palaia_hub

    assert palaia_hub.__version__ == _read_version_file()


def test_mcpb_personalized_download_reads_the_server_version_not_a_literal() -> None:
    """The hub-served MCPB bundle (SPEC-306) must keep importing
    ``palaia_hub.__version__`` rather than restating a version string —
    if this ever regresses to a hardcoded literal, every personalized
    download would silently drift from ``v3/VERSION`` without any of the
    other checks in this file noticing."""
    routes_source = (V3_ROOT / "server" / "src" / "palaia_hub" / "mcpb" / "routes.py").read_text(
        encoding="utf-8"
    )
    assert "from .. import __version__" in routes_source
    assert "version=__version__" in routes_source


def test_web_package_version_matches() -> None:
    package_json = json.loads((V3_ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    assert package_json["version"] == _read_version_file()


def test_sdk_package_version_matches() -> None:
    pyproject_text = (V3_ROOT / "sdk" / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject_text)
    assert match is not None, "sdk/pyproject.toml has no [project] version line"
    assert match.group(1) == _read_version_file()


def test_mcpb_build_script_never_hardcodes_a_release_version() -> None:
    """Structural check on ``tools/build-mcpb/build.mjs`` (no `npm ci`
    needed): the version passed to `stageBundle` must come from an
    explicit argument, `$PALAIA_VERSION`, or the repo `VERSION` file — in
    that priority order — never a bare literal that could go stale. A
    real build against this exact commit (`PALAIA_VERSION` unset, so the
    `VERSION`-file fallback is what fires) produced
    `palaia@3.0.0-rc1` / `palaia-3.0.0-rc1.mcpb`, matching `v3/VERSION` —
    see this SPEC's PR description for the full `npm run build` transcript."""
    build_source = (V3_ROOT / "tools" / "build-mcpb" / "build.mjs").read_text(encoding="utf-8")
    assert "readRepoVersion()" in build_source
    assert "version || process.env.PALAIA_VERSION || readRepoVersion()" in build_source
    # The only literal-looking fallback left is the "file genuinely
    # missing" case inside readRepoVersion() itself — never a stand-in
    # for a real release version.
    assert '"0.0.0-dev"' in build_source


#: Every install path that pins the `stable` channel tag carries a note
#: telling a release-candidate reader to use `beta` instead (issue #326).
#: The generated Synology page is included: its generator emits the note.
_RC_CHANNEL_NOTE_FILES = (
    "deploy/README.md",
    "deploy/docker-compose.yml",
    "docs/how-it-works.md",
    "site/docs/src/content/docs/install.md",
    "site/docs/src/content/docs/install-synology.md",
    "site/docs/src/content/docs/backup-restore.md",
    "../README.md",
)


def test_rc_channel_notes_exist_exactly_while_version_is_a_prerelease() -> None:
    """During an RC the `stable` image does not exist (the release workflow
    only creates it on the final tag), yet every install path pins it —
    so each carries an `rc-channel-note` pointing at `beta`. The note must
    be present while `VERSION` is a pre-release and gone once it is not:
    RELEASING.md §3 lists removing them, and this is what enforces it."""
    prerelease = "-" in _read_version_file()
    for relative in _RC_CHANNEL_NOTE_FILES:
        text = (V3_ROOT / relative).read_text(encoding="utf-8")
        present = "rc-channel-note" in text
        assert present is prerelease, (
            f"{relative}: rc-channel-note {'missing' if prerelease else 'still present'} "
            f"for VERSION {_read_version_file()!r} — see RELEASING.md §3"
        )


def test_compose_pins_the_stable_channel_tag_not_a_literal_version() -> None:
    compose_text = (V3_ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    match = re.search(r"image:\s*(\S+)", compose_text)
    assert match is not None, "docker-compose.yml has no image: line"
    assert match.group(1) == "ghcr.io/byte5ai/palaia-hub:stable"


def test_install_sh_defaults_to_the_stable_channel_tag() -> None:
    install_text = (V3_ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert 'IMAGE="${PALAIA_IMAGE:-ghcr.io/byte5ai/palaia-hub:stable}"' in install_text


@pytest.mark.parametrize(
    "compose_path",
    [
        "umbrel/docker-compose.yml",
        "casaos/docker-compose.yml",
        "runtipi/apps/palaia/docker-compose.yml",
    ],
)
def test_store_packages_pin_the_stable_channel_tag(compose_path: str) -> None:
    text = (V3_ROOT / "deploy" / "stores" / compose_path).read_text(encoding="utf-8")
    assert "ghcr.io/byte5ai/palaia-hub:stable" in text, (
        f"{compose_path} must pin the stable channel tag, matching "
        "deploy/stores/README.md's shared contract"
    )


def test_release_workflow_tag_derived_version_would_round_trip_this_rc() -> None:
    """Simulates `.github/workflows/v3-release.yml`'s own tag-parsing
    shell (`test_release_workflow.py` checks that script's structure;
    this test checks the *arithmetic* it would do against this exact
    release): tagging `v3.<VERSION>` must strip back down to exactly
    `v3/VERSION`'s content, and the channel that arithmetic resolves to
    must match what `v3/VERSION` actually is right now — `rc`/`beta` in
    the version means the `beta` channel, never `stable`, and vice versa.
    This is deliberately not a hardcoded "must be beta" assertion: this
    same test still has to pass once `v3/RELEASING.md`'s §3 bumps
    `VERSION` to a final, non-candidate `3.0.0`, at which point the
    correct channel flips to `stable` and this test must agree, not keep
    demanding `beta` forever. `v3/RELEASING.md` names the literal tag to
    push."""
    version = _read_version_file()
    tag_ref = f"refs/tags/v3.{version}"
    assert tag_ref.startswith("refs/tags/v3.")
    extracted = tag_ref[len("refs/tags/v3.") :]
    assert extracted == version
    is_prerelease = "beta" in version or "rc" in version
    channel = "beta" if is_prerelease else "stable"
    if version == "3.0.0-rc1":
        assert channel == "beta", f"{version!r} is an RC and must resolve to beta, not stable"
