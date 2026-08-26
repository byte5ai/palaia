#!/usr/bin/env bash
# palaia v3 — optional convenience installer.
#
# This script is never required: `docker run` (see README.md) is the actual
# one-liner. This just wraps it with a couple of sanity checks (Docker
# present and running) and prints the URL to open at the end, for anyone who
# would rather paste one command than read the README.
set -euo pipefail

IMAGE="${PALAIA_IMAGE:-ghcr.io/byte5ai/palaia-hub:stable}"
CONTAINER_NAME="${PALAIA_CONTAINER_NAME:-palaia-hub}"
PORT="${PALAIA_INSTALL_PORT:-8420}"
VOLUME="${PALAIA_VOLUME:-palaia_home}"

if ! command -v docker >/dev/null 2>&1; then
    echo "palaia install: Docker is required but was not found on PATH." >&2
    echo "  Install it from https://docs.docker.com/get-docker/ and re-run this script." >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "palaia install: Docker is installed but not reachable (daemon not running," >&2
    echo "  or this user lacks permission to talk to it — try 'sudo' or add yourself" >&2
    echo "  to the 'docker' group)." >&2
    exit 1
fi

echo "palaia install: pulling ${IMAGE} ..."
docker pull "${IMAGE}"

if docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    echo "palaia install: a container named '${CONTAINER_NAME}' already exists."
    echo "  Remove it first (docker rm -f ${CONTAINER_NAME}) or set PALAIA_CONTAINER_NAME" >&2
    echo "  to a different name, then re-run this script." >&2
    exit 1
fi

echo "palaia install: starting ${CONTAINER_NAME} on port ${PORT} ..."
# The hardening flags mirror docker-compose.yml's `security_opt`/`cap_drop`/
# `read_only`/`tmpfs` block (SPEC-502) — the one-liner and the compose file
# must not give different containers different postures. See that file for
# why each one is safe here.
docker run -d \
    --name "${CONTAINER_NAME}" \
    -p "${PORT}:8420" \
    -v "${VOLUME}:/data" \
    --restart unless-stopped \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --read-only \
    --tmpfs /tmp \
    --tmpfs /run \
    "${IMAGE}"

echo ""
echo "palaia is starting. Open one of these in your browser:"
echo "  http://localhost:${PORT}/        (from this machine)"
echo "  http://palaia.local:${PORT}/     (from other devices, if mDNS reaches your LAN —"
echo "                                     see v3/deploy/README.md; not guaranteed)"
echo ""
echo "Follow startup logs with: docker logs -f ${CONTAINER_NAME}"
