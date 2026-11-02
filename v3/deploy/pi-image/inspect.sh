#!/usr/bin/env bash
# SPEC-603 acceptance: "rootfs inspection assertions green" — loop-mounts a
# built (uncompressed) .img read-only and checks the four things the SPEC
# names: Docker enabled, palaia unit enabled, mDNS on, SSH off — plus the
# port-80 forwarder of issue #620. Exits non-zero with a clear reason on the
# first assertion that fails.
#
# Usage: sudo ./inspect.sh /path/to/palaia-appliance.img
set -euo pipefail

IMG="${1:?usage: inspect.sh <path-to-.img>}"

if [ "$(id -u)" -ne 0 ]; then
    echo "inspect.sh: must run as root (loop devices, mount) — try 'sudo $0 $*'" >&2
    exit 1
fi

WORK="$(mktemp -d)"
ROOTFS="${WORK}/rootfs"
BOOT="${WORK}/boot"
mkdir -p "${ROOTFS}" "${BOOT}"

declare -a CLEANUP_STACK=()
push_cleanup() { CLEANUP_STACK+=("$1"); }
unwind_all() {
    local i cmd
    for ((i = ${#CLEANUP_STACK[@]} - 1; i >= 0; i--)); do
        cmd="${CLEANUP_STACK[i]}"
        eval "${cmd}" || true
    done
    rm -rf "${WORK}"
}
trap unwind_all EXIT

loopdev="$(losetup --find --show -P -r "${IMG}")"
push_cleanup "losetup -d '${loopdev}' 2>/dev/null"

mount -o ro "${loopdev}p2" "${ROOTFS}"
push_cleanup "umount '${ROOTFS}'"
mount -o ro "${loopdev}p1" "${BOOT}"
push_cleanup "umount '${BOOT}'"

fail() {
    echo "inspect.sh: FAIL — $1" >&2
    exit 1
}
pass() {
    echo "inspect.sh: ok — $1"
}

# --- Docker enabled --------------------------------------------------------
if [ -L "${ROOTFS}/etc/systemd/system/multi-user.target.wants/docker.service" ] \
    || [ -L "${ROOTFS}/lib/systemd/system/multi-user.target.wants/docker.service" ]; then
    pass "docker.service is enabled (multi-user.target.wants symlink present)"
else
    fail "docker.service is not enabled — no multi-user.target.wants symlink found"
fi
[ -e "${ROOTFS}/lib/systemd/system/docker.service" ] \
    || fail "docker.service unit file is missing — docker.io did not install correctly"
[ -x "${ROOTFS}/usr/bin/dockerd" ] || [ -x "${ROOTFS}/usr/sbin/dockerd" ] \
    || fail "dockerd binary missing from the image"

# --- palaia unit enabled ----------------------------------------------------
PALAIA_UNIT="${ROOTFS}/etc/systemd/system/palaia.service"
[ -f "${PALAIA_UNIT}" ] || fail "palaia.service unit file is missing"
if [ -L "${ROOTFS}/etc/systemd/system/multi-user.target.wants/palaia.service" ]; then
    pass "palaia.service is enabled (multi-user.target.wants symlink present)"
else
    fail "palaia.service is not enabled — no multi-user.target.wants symlink found"
fi
grep -q 'ghcr.io/byte5ai/palaia-hub:stable' "${PALAIA_UNIT}" \
    || fail "palaia.service does not run the :stable channel image"

# --- mDNS on -----------------------------------------------------------------
# The image's own mDNS announcer (v3/deploy/mdns_announce.py) runs inside
# the palaia-hub container and needs the host network to reach the LAN —
# see systemd/palaia.service's own comment. "mDNS on" for this appliance
# means: the unit runs the container with host networking, and nothing in
# the image disables the announcer.
grep -q -- '--network host' "${PALAIA_UNIT}" \
    || fail "palaia.service does not run the container with --network host — mDNS could not reach the LAN"
if grep -rq 'PALAIA_MDNS_ENABLED=0' "${ROOTFS}/etc/systemd/system/" 2>/dev/null; then
    fail "found PALAIA_MDNS_ENABLED=0 — the appliance image must not disable mDNS"
fi
pass "mDNS announcer is on (host networking, not disabled)"

# --- Port 80 forwarder (issue #620) -----------------------------------------
# http://palaia.local/ without a port: palaia-http.socket binds port 80 on
# the box and palaia-http.service forwards to the container's 8420. Both
# live outside the container, which keeps its hardening untouched.
HTTP_SOCKET="${ROOTFS}/etc/systemd/system/palaia-http.socket"
HTTP_SERVICE="${ROOTFS}/etc/systemd/system/palaia-http.service"
[ -f "${HTTP_SOCKET}" ] || fail "palaia-http.socket unit file is missing — nothing answers on port 80"
[ -f "${HTTP_SERVICE}" ] || fail "palaia-http.service unit file is missing — port 80 would accept and never forward"
if [ -L "${ROOTFS}/etc/systemd/system/multi-user.target.wants/palaia-http.socket" ]; then
    pass "palaia-http.socket is enabled (multi-user.target.wants symlink present)"
else
    fail "palaia-http.socket is not enabled — no multi-user.target.wants symlink found"
fi
grep -qx 'ListenStream=80' "${HTTP_SOCKET}" \
    || fail "palaia-http.socket does not listen on port 80"
grep -qx 'ExecStart=/usr/lib/systemd/systemd-socket-proxyd 127.0.0.1:8420' "${HTTP_SERVICE}" \
    || fail "palaia-http.service does not forward to the hub on 127.0.0.1:8420"
[ -x "${ROOTFS}/usr/lib/systemd/systemd-socket-proxyd" ] \
    || fail "systemd-socket-proxyd is missing from the image — palaia-http.service cannot start"
pass "port 80 forwards to the hub (palaia-http.socket → 127.0.0.1:8420)"

# --- SSH off -----------------------------------------------------------------
if [ -L "${ROOTFS}/etc/systemd/system/multi-user.target.wants/ssh.service" ] \
    || [ -L "${ROOTFS}/lib/systemd/system/multi-user.target.wants/ssh.service" ]; then
    fail "ssh.service is enabled — the appliance image must ship with SSH off by default"
fi
if [ -e "${BOOT}/ssh" ] || [ -e "${BOOT}/firmware/ssh" ]; then
    fail "found a /boot ssh marker file baked into the image — SSH must not be pre-enabled"
fi
pass "SSH is off (no enabled unit, no /boot ssh marker file)"

echo "inspect.sh: all rootfs assertions passed."
