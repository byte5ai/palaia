#!/usr/bin/env bash
# Re-pins base-image.env to the *current* Raspberry Pi OS Lite (arm64)
# build. Run this by hand when a refresh is wanted; it is never invoked by
# CI — the build always uses whatever is already committed in
# base-image.env, which is what makes a CI run reproducible against
# itself (see README.md's "Reproducibility" section).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

latest_url="$(curl -fsSI "https://downloads.raspberrypi.org/raspios_lite_arm64_latest" \
    | grep -i '^location:' | tr -d '\r' | awk '{print $2}')"
if [ -z "${latest_url}" ]; then
    echo "pin-base-image: could not resolve the 'latest' redirect" >&2
    exit 1
fi

sha256="$(curl -fsS "${latest_url}.sha256" | awk '{print $1}')"
if [ -z "${sha256}" ]; then
    echo "pin-base-image: could not fetch a checksum for ${latest_url}" >&2
    exit 1
fi

cat > base-image.env <<EOF
# Pinned Raspberry Pi OS Lite (arm64) base image — SPEC-603.
#
# build.sh sources this file and refuses to proceed if the downloaded
# file's sha256 doesn't match BASE_IMAGE_SHA256. This is the whole
# reproducibility story for the *base OS*: the same committed URL+checksum
# is what every build (CI or an owner's own machine) starts from, today or
# a year from now, for as long as Raspberry Pi Foundation keeps this dated
# build online.
#
# Re-pin with `./pin-base-image.sh` when a refresh is wanted (e.g. a
# security-relevant base OS update) — it fetches the *current* "latest"
# build, rewrites this file, and prints what changed. Never hand-edit
# BASE_IMAGE_URL without also updating BASE_IMAGE_SHA256 to match.
BASE_IMAGE_URL="${latest_url}"
BASE_IMAGE_SHA256="${sha256}"
EOF

echo "pin-base-image: base-image.env now pinned to:"
echo "  ${latest_url}"
echo "  sha256:${sha256}"
