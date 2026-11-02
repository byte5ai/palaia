#!/bin/sh
# palaia Pi image, issue #620: let port 80 lead to the hub's own port 8420,
# so http://palaia.local/ works without a port.
#
# Installed as /usr/local/lib/palaia/http-redirect and run by
# palaia-http-redirect.service after the rest of the boot.
#
# A kernel NAT redirect, not a userspace proxy: nginx in the container then
# still sees each device's own address, which the hub's failed-sign-in
# limit is keyed on (palaia_hub.security.client_ip, SPEC-502). Through a
# proxy every caller would arrive from 127.0.0.1 and share one bucket.
#
# The rule lives in its own nftables table, so it never touches Docker's
# rules and is removed as a whole. `inet` covers IPv4 and IPv6 in one rule;
# `fib daddr type local` limits it to traffic addressed to this box, so a
# container's outgoing HTTP is never caught.
#
# Port 80 already taken (a web server the owner installed on this box):
# the redirect is removed instead of added, the other service keeps
# port 80, and the hub stays on 8420. Idempotent: every start replaces the
# table in one nft transaction.
set -eu

TABLE="inet palaia_http"
#: The container's PUBLIC_PORT (v3/deploy/Dockerfile); palaia.service runs
#: it on the host network, so nginx listens on this port on the box itself.
HUB_PORT=8420

log() { echo "palaia-http-redirect: $*"; }

case "${1:-}" in
start)
    if ss -Hltn 'sport = :80' | grep -q .; then
        nft delete table ${TABLE} 2>/dev/null || true
        log "port 80 is already in use on this box, so it is left alone; the hub answers on :${HUB_PORT}"
        exit 0
    fi
    if ! nft -f - <<EOF
table ${TABLE}
delete table ${TABLE}
table ${TABLE} {
    chain prerouting {
        type nat hook prerouting priority dstnat; policy accept;
        fib daddr type local tcp dport 80 redirect to :${HUB_PORT}
    }
}
EOF
    then
        log "could not set up port 80 (nft's error is above); the hub answers on :${HUB_PORT}"
        exit 1
    fi
    log "port 80 now leads to the hub on :${HUB_PORT}"
    ;;
stop)
    nft delete table ${TABLE} 2>/dev/null || true
    log "port 80 no longer leads to the hub"
    ;;
*)
    echo "usage: $0 start|stop" >&2
    exit 2
    ;;
esac
