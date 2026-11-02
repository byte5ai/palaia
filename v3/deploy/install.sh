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

# The network (README.md, "Quick start" and "mDNS"). On Linux the container
# runs on the host network, so its palaia.local announcement reaches the
# other devices on this network; the cloud entry then stays on loopback
# (PALAIA_CLOUD_BIND), where only a tunnel on this machine reaches it.
# Docker Desktop (macOS, Windows, and Docker Desktop on Linux) runs
# containers inside a virtual machine, whose host network is not yours:
# there the port is published instead, and the name cannot work.
if docker info --format '{{.OperatingSystem}}' 2>/dev/null | grep -qi 'docker desktop'; then
    DESKTOP=1
    NETWORK_ARGS=(-p "${PORT}:8420")
else
    DESKTOP=0
    NETWORK_ARGS=(--network host -e PALAIA_CLOUD_BIND=127.0.0.1)
    # On the host network nothing is mapped: the hub itself listens on PORT.
    [ "${PORT}" = "8420" ] || NETWORK_ARGS+=(-e "PUBLIC_PORT=${PORT}")
fi

echo "palaia install: starting ${CONTAINER_NAME} on port ${PORT} ..."
# The hardening flags mirror docker-compose.yml's `security_opt`/`cap_drop`/
# `read_only`/`tmpfs` block (SPEC-502) — the one-liner and the compose file
# must not give different containers different postures. See that file for
# why each one is safe here.
docker run -d \
    --name "${CONTAINER_NAME}" \
    "${NETWORK_ARGS[@]}" \
    -v "${VOLUME}:/data" \
    --restart unless-stopped \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --read-only \
    --tmpfs /tmp \
    --tmpfs /run \
    "${IMAGE}"

echo ""
if [ "${DESKTOP}" = "1" ]; then
    echo "palaia is starting. Open http://localhost:${PORT}/ in your browser."
    echo "  (Docker Desktop keeps containers off your network, so the palaia.local"
    echo "   name cannot reach your other devices — see v3/deploy/README.md, \"mDNS\".)"
else
    LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") { print $(i + 1); exit }}' || true)"
    [ -n "${LAN_IP}" ] || LAN_IP="<this machine's address>"
    echo "palaia is starting. Open it in your browser:"
    echo "  http://palaia.local:${PORT}/     (from any device on this network)"
    echo "  http://localhost:${PORT}/        (on this machine)"
    echo "  http://${LAN_IP}:${PORT}/  (if the name does not resolve —"
    echo "                                     some networks block it; see v3/deploy/README.md)"
fi
echo ""
echo "Follow startup logs with: docker logs -f ${CONTAINER_NAME}"
