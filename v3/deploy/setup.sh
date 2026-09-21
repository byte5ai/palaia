#!/usr/bin/env bash
# palaia v3 — set up the hub on a server you ALREADY have (SPEC-601 companion
# to cloud-init.yaml). cloud-init.yaml only ever runs on a server's FIRST boot
# — pasting it into a box that is already running does nothing. For an
# existing server, SSH in and run this script instead: it does the same thing
# cloud-init.yaml does — installs Docker and Tailscale, joins your tailnet, and
# starts the hub bound to the tailnet address only, with the same hardening
# flags — so both paths end at the identical container.
#
# Usage, over SSH on the target server (it needs root, hence sudo):
#
#   curl -fsSLO https://raw.githubusercontent.com/byte5ai/palaia/main/v3/deploy/setup.sh
#   sudo TAILSCALE_AUTH_KEY="tskey-..." bash setup.sh
#
# Get a Tailscale auth key at https://login.tailscale.com/admin/settings/keys
# (a reusable, ephemeral key works well — this script re-runs safely).
#
# Everything it does is printed as it goes; every step is guarded, so running
# it a second time changes nothing already in place.
set -euo pipefail

log() { echo "palaia setup: $*"; }

# rc-channel-note — defaults to `:beta` (the pre-release channel) during the
# 3.0.0 release candidate, matching cloud-init.yaml, because until the final
# tag the `stable` image does not exist yet. RELEASING.md §3 flips both back to
# `:stable` on that tag; server/tests/test_version_drift.py enforces which tag
# is correct for the current v3/VERSION. Override PALAIA_IMAGE to pin another.
IMAGE="${PALAIA_IMAGE:-ghcr.io/byte5ai/palaia-hub:beta}"
CONTAINER_NAME="${PALAIA_CONTAINER_NAME:-palaia-hub}"
VOLUME="${PALAIA_VOLUME:-palaia_home}"
PORT="${PALAIA_INSTALL_PORT:-8420}"

if [ "${TAILSCALE_AUTH_KEY:-}" = "" ]; then
    log "ERROR: set TAILSCALE_AUTH_KEY before running this — for example:"
    log "  sudo TAILSCALE_AUTH_KEY=\"tskey-...\" bash setup.sh"
    log "  get a key at https://login.tailscale.com/admin/settings/keys"
    exit 1
fi

# --- Docker ----------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
    log "installing Docker ..."
    curl -fsSL https://get.docker.com | sh
else
    log "Docker already installed, skipping."
fi
systemctl enable --now docker

# --- Tailscale -------------------------------------------------------------
# A different private network entirely? Swap this install step and the
# `tailscale up`/`tailscale0` lines below for your VPN's own join step and
# interface name — the firewall rule further down is the only other line that
# names it.
if ! command -v tailscale >/dev/null 2>&1; then
    log "installing Tailscale ..."
    curl -fsSL https://tailscale.com/install.sh | sh
else
    log "Tailscale already installed, skipping."
fi
systemctl enable --now tailscaled

log "joining the tailnet ..."
tailscale up --auth-key="${TAILSCALE_AUTH_KEY}" --hostname="palaia-hub"
TAILSCALE_IP="$(tailscale ip -4)"
log "tailnet address: ${TAILSCALE_IP}"

# --- Firewall: the hub port, reachable via the tailnet only ----------------
# Two independent layers, so one weak spot does not undo the other: binding
# docker's published port to the tailnet address itself (below, in the
# `docker run` line) means nothing is even listening on the public interface;
# this ufw rule denies the port there too, for anything that ever changes that
# bind.
if command -v ufw >/dev/null 2>&1; then
    ufw allow OpenSSH >/dev/null 2>&1 || true
    ufw allow in on tailscale0 to any port "${PORT}" proto tcp \
        comment 'palaia hub, tailnet only'
    ufw --force enable
    log "ufw enabled: ${PORT}/tcp reachable on the tailscale0 interface only."
else
    log "ufw not found — skipping the firewall rule; the docker publish below"
    log "  already binds to the tailnet address only, regardless."
fi

# --- The hub ---------------------------------------------------------------
if docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    log "container '${CONTAINER_NAME}' already exists, leaving it as-is."
else
    log "pulling ${IMAGE} ..."
    docker pull "${IMAGE}"
    log "starting ${CONTAINER_NAME} on ${TAILSCALE_IP}:${PORT} (tailnet only) ..."
    # Hardening flags mirror install.sh / docker-compose.yml (SPEC-502)
    # verbatim — checked by server/tests/deploy/test_cloud_init.py's drift
    # test, which asserts this script and cloud-init.yaml share install.sh's
    # own flag list. Only the `-p` bind address differs from install.sh's own,
    # on purpose: binding to the tailnet address (not 0.0.0.0) is what keeps
    # the hub off the public internet — the same choice cloud-init.yaml makes.
    docker run -d \
        --name "${CONTAINER_NAME}" \
        -p "${TAILSCALE_IP}:${PORT}:8420" \
        -v "${VOLUME}:/data" \
        --restart unless-stopped \
        --security-opt no-new-privileges:true \
        --cap-drop ALL \
        --read-only \
        --tmpfs /tmp \
        --tmpfs /run \
        "${IMAGE}"
fi

log "done. Open http://${TAILSCALE_IP}:${PORT}/ from any device on your tailnet."
