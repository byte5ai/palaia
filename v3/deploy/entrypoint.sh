#!/usr/bin/env bash
# Container entrypoint: renders the nginx config, starts the hub (internal,
# loopback-only) and the mDNS announcer, then runs nginx (the container's
# only public listener) in the foreground.
#
# Signal handling: this script stays PID 1 (nginx and the hub run as its
# background jobs, never exec'd over it) so SIGTERM/SIGINT from `docker
# stop` / compose can be forwarded to both children, giving the hub its
# `graceful_shutdown_timeout` to drain in-flight requests.
set -euo pipefail

: "${PUBLIC_PORT:=8420}"
: "${PALAIA_HOST:=127.0.0.1}"
: "${PALAIA_PORT:=8421}"
export PUBLIC_PORT PALAIA_HOST PALAIA_PORT

mkdir -p /tmp/nginx/body /tmp/nginx/proxy /tmp/nginx/fastcgi /tmp/nginx/uwsgi /tmp/nginx/scgi
envsubst '${PUBLIC_PORT} ${PALAIA_HOST} ${PALAIA_PORT}' \
    < /opt/palaia/nginx.conf.template > /tmp/nginx/nginx.conf

pids=()

palaia-hub serve --host "$PALAIA_HOST" --port "$PALAIA_PORT" &
hub_pid=$!
pids+=("$hub_pid")

if [ "${PALAIA_MDNS_ENABLED:-1}" = "1" ]; then
    python /opt/palaia/mdns_announce.py --port "$PUBLIC_PORT" &
    pids+=("$!")
else
    echo "palaia-hub: mDNS announcing disabled (PALAIA_MDNS_ENABLED=0)" >&2
fi

nginx -c /tmp/nginx/nginx.conf -g "daemon off;" &
nginx_pid=$!
pids+=("$nginx_pid")

echo "palaia-hub: ready — open http://<this-host's-ip>:${PUBLIC_PORT}/ " \
     "(http://palaia.local:${PUBLIC_PORT}/ if mDNS reaches your LAN; see v3/deploy/README.md)" >&2
echo "palaia-hub: channel=${PALAIA_CHANNEL:-edge} deployment=${PALAIA_DEPLOYMENT:-unknown}" >&2

_term() {
    trap - TERM INT
    for pid in "${pids[@]}"; do
        kill -TERM "$pid" 2>/dev/null || true
    done
}
trap _term TERM INT

# Exit as soon as either the hub or nginx dies, so `restart: unless-stopped`
# actually restarts a half-dead container rather than leaving it limping
# along on whichever process survived.
set +e
wait -n "$hub_pid" "$nginx_pid"
exit_code=$?
set -e
_term
wait 2>/dev/null || true
exit "$exit_code"
