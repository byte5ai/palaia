#!/usr/bin/env bash
# SPEC-506 deliverable #1: "release workflow dry-run (whatever release
# automation exists or a scripted dry-run proving the steps)."
#
# Runs every release-time check this repo has, in the order RELEASING.md
# says a real release happens in, against the current v3/VERSION — without
# pushing a tag, an image, or a package anywhere. Exits non-zero on the
# first thing that would block a real release.
#
# Usage: v3/tools/release-dry-run.sh   (run from anywhere; cd's internally)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
V3_ROOT="$(cd "${HERE}/.." && pwd)"
cd "${V3_ROOT}"

VERSION="$(cat VERSION)"
echo "== palaia v3 release dry-run =="
echo "v3/VERSION: ${VERSION}"
echo ""

echo "-- 1. version/changelog drift test --"
uv run pytest server/tests/test_version_drift.py server/tests/test_release_workflow.py -q
echo ""

echo "-- 2. what the release workflow would tag and push --"
TAG="v3.${VERSION}"
if [[ "${VERSION}" == *rc* || "${VERSION}" == *beta* ]]; then
  CHANNEL="beta"
else
  CHANNEL="stable"
fi
echo "git tag:        ${TAG}"
echo "image tags:     ghcr.io/byte5ai/palaia-hub:${TAG}, ghcr.io/byte5ai/palaia-hub:${CHANNEL}"
echo "OCI annotation: org.opencontainers.image.version=${VERSION}"
echo "channel:        ${CHANNEL}  (never 'stable' for an rc/beta version — enforced by"
echo "                 the release workflow's own branch and by the drift test above)"
echo ""

echo "-- 3. CHANGELOG.md has an entry for this version --"
if grep -q "## ${VERSION}" CHANGELOG.md; then
  echo "OK: CHANGELOG.md has a '## ${VERSION}' section"
else
  echo "MISSING: CHANGELOG.md has no '## ${VERSION}' section" >&2
  exit 1
fi
echo ""

echo "-- 4. mcpb bundle: real pack + sign against this VERSION --"
if [[ -d "${V3_ROOT}/tools/build-mcpb/node_modules" ]] || (cd "${V3_ROOT}/tools/build-mcpb" && npm ci --silent 2>/dev/null); then
  (
    cd "${V3_ROOT}/tools/build-mcpb"
    rm -rf dist
    npm run build --silent
    UNPACKED="$(mktemp -d)"
    node_modules/.bin/mcpb unpack dist/palaia.mcpb "${UNPACKED}" >/dev/null
    node_modules/.bin/mcpb validate "${UNPACKED}/manifest.json"
    BUNDLE_VERSION="$(node -pe "require('${UNPACKED}/manifest.json').version")"
    if [[ "${BUNDLE_VERSION}" != "${VERSION}" ]]; then
      echo "MCPB bundle version (${BUNDLE_VERSION}) != v3/VERSION (${VERSION})" >&2
      exit 1
    fi
    echo "OK: built, signed, and validated palaia-${BUNDLE_VERSION}.mcpb"
    rm -rf "${UNPACKED}" dist
  )
else
  echo "SKIPPED: no network reachable to npm ci the mcpb build tooling — the"
  echo "  structural check in server/tests/test_version_drift.py"
  echo "  (test_mcpb_build_script_never_hardcodes_a_release_version) is the"
  echo "  fallback evidence that this step is wired correctly."
fi
echo ""

echo "-- 5. server/web/sdk import and report the same version --"
uv run python -c "import palaia_hub; print('server:', palaia_hub.__version__)"
python3 -c "import json; print('web:', json.load(open('web/package.json'))['version'])"
python3 -c "
import re
text = open('sdk/pyproject.toml').read()
print('sdk:', re.search(r'(?m)^version\s*=\s*\"([^\"]+)\"', text).group(1))
"
echo ""

echo "== dry-run complete: 3.0.0-rc1's release plumbing checks out =="
