#!/usr/bin/env bash
# palaia v3 — universal one-command installer.
#
#   curl -fsSL https://get.palaia.ai | sh
#
# Works on any existing Linux VPS you can SSH into (Ubuntu/Debian tested). It
# installs Docker and Tailscale if missing, joins your tailnet, and starts the
# hub bound to the tailnet address only — never the public internet. cloud-init
# is only a create-time shortcut; this is the path when the server already
# exists (the common case).
#
# Non-interactive use (e.g. from a skill): set PALAIA_TSKEY and pipe to `sh`.
# LAN/local without Tailscale: set PALAIA_NO_TAILSCALE=1 (binds to 0.0.0.0).
set -euo pipefail

CHANNEL="${PALAIA_CHANNEL:-stable}"
IMAGE="${PALAIA_IMAGE:-ghcr.io/byte5ai/palaia-hub:${CHANNEL}}"
CONTAINER_NAME="${PALAIA_CONTAINER_NAME:-palaia-hub}"
PORT="${PALAIA_INSTALL_PORT:-8420}"
VOLUME="${PALAIA_VOLUME:-palaia_home}"
HOSTNAME_TS="${PALAIA_TS_HOSTNAME:-palaia-hub}"

log()  { echo "palaia: $*"; }
err()  { echo "palaia: ERROR: $*" >&2; }
die()  { err "$@"; exit 1; }

[ "$(id -u)" = "0" ] || SUDO="sudo"; SUDO="${SUDO:-}"

# --- Docker -----------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
    log "installing Docker ..."
    curl -fsSL https://get.docker.com | $SUDO sh
fi
$SUDO systemctl enable --now docker >/dev/null 2>&1 || true
docker info >/dev/null 2>&1 || die "Docker is installed but not reachable (daemon down, or no permission)."

# --- Tailscale (unless explicitly disabled) ---------------------------------
BIND_ADDR="0.0.0.0"
if [ "${PALAIA_NO_TAILSCALE:-0}" = "1" ]; then
    log "PALAIA_NO_TAILSCALE=1 — skipping Tailscale; the hub will bind to ${BIND_ADDR} (LAN only if you firewall it)."
else
    if ! command -v tailscale >/dev/null 2>&1; then
        log "installing Tailscale ..."
        curl -fsSL https://tailscale.com/install.sh | $SUDO sh
    fi
    $SUDO systemctl enable --now tailscaled >/dev/null 2>&1 || true

    TSKEY="${PALAIA_TSKEY:-}"
    if [ -z "$TSKEY" ]; then
        if [ -t 0 ]; then
            echo "palaia: paste a Tailscale AUTH KEY (NOT an access token) —"
            echo "        create one at https://login.tailscale.com/admin/settings/keys"
            echo "        ('Generate auth key'; Reusable + Ephemeral off is fine):"
            read -r TSKEY < /dev/tty || true
        fi
    fi
    [ -n "$TSKEY" ] || die "no Tailscale auth key given. Set PALAIA_TSKEY=tskey-... or run interactively."
    case "$TSKEY" in
        tskey-*) : ;;
        *) die "that does not look like an auth key (expected 'tskey-...'). You may have copied an *access token* instead — use 'Generate auth key'." ;;
    esac

    log "joining the tailnet ..."
    if ! $SUDO tailscale up --auth-key="$TSKEY" --hostname="$HOSTNAME_TS"; then
        die "Tailscale rejected the key. It is likely expired, already used (non-reusable), or an access token rather than an auth key. Generate a fresh auth key and re-run."
    fi
    BIND_ADDR="$($SUDO tailscale ip -4 2>/dev/null | head -n1)"
    [ -n "$BIND_ADDR" ] || die "joined Tailscale but no IPv4 tailnet address yet — not starting the hub on an empty address. Re-run in a moment."
    log "tailnet address: ${BIND_ADDR}"

    # Firewall: hub port reachable on the tailnet only.
    if command -v ufw >/dev/null 2>&1; then
        $SUDO ufw allow OpenSSH >/dev/null 2>&1 || true
        $SUDO ufw allow in on tailscale0 to any port "${PORT}" proto tcp comment 'palaia hub, tailnet only' >/dev/null 2>&1 || true
        $SUDO ufw --force enable >/dev/null 2>&1 || true
        log "ufw: ${PORT}/tcp on tailscale0 only."
    fi
fi

# --- Image ------------------------------------------------------------------
log "pulling ${IMAGE} ..."
if ! docker pull "${IMAGE}"; then
    if [ "${CHANNEL}" = "stable" ]; then
        die "could not pull ${IMAGE}. During the release-candidate phase there is no ':stable' image yet — re-run with PALAIA_CHANNEL=beta."
    fi
    die "could not pull ${IMAGE}. Check the tag/registry and your network."
fi

# --- Container --------------------------------------------------------------
if docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    log "a container named '${CONTAINER_NAME}' exists — replacing it (your data in the '${VOLUME}' volume is untouched)."
    docker rm -f "${CONTAINER_NAME}" >/dev/null
fi

log "starting ${CONTAINER_NAME} on ${BIND_ADDR}:${PORT} ..."
docker run -d \
    --name "${CONTAINER_NAME}" \
    -p "${BIND_ADDR}:${PORT}:8420" \
    -v "${VOLUME}:/data" \
    --restart unless-stopped \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --read-only \
    --tmpfs /tmp \
    --tmpfs /run \
    "${IMAGE}" >/dev/null

# --- Healthcheck ------------------------------------------------------------
log "waiting for the hub to answer ..."
URL="http://${BIND_ADDR}:${PORT}/"
ok=0
for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null --max-time 2 "$URL" 2>/dev/null; then ok=1; break; fi
    sleep 1
done
echo ""
if [ "$ok" = "1" ]; then
    log "done ✓  Open ${URL} from any device on your tailnet."
else
    err "hub started but did not answer at ${URL} within 30s."
    err "Check logs: docker logs -f ${CONTAINER_NAME}"
    exit 1
fi
