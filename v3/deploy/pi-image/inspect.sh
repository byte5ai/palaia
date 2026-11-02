#!/usr/bin/env bash
# SPEC-603 acceptance: "rootfs inspection assertions green" — loop-mounts a
# built (uncompressed) .img read-only and checks the four things the SPEC
# names: Docker enabled, palaia unit enabled, mDNS on, SSH off — plus the
# port-80 redirect of issue #620 and the cloud entry kept on loopback.
# Exits non-zero with a clear reason on the first assertion that fails.
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
grep -q 'ghcr.io/byte5ai/palaia:stable' "${PALAIA_UNIT}" \
    || fail "palaia.service does not run the :stable channel image"

# --- mDNS on -----------------------------------------------------------------
# The image's own mDNS announcer (v3/deploy/mdns_announce.py) runs inside
# the palaia container and needs the host network to reach the LAN —
# see systemd/palaia.service's own comment. "mDNS on" for this appliance
# means: the unit runs the container with host networking, and nothing in
# the image disables the announcer.
grep -q -- '--network host' "${PALAIA_UNIT}" \
    || fail "palaia.service does not run the container with --network host — mDNS could not reach the LAN"
if grep -rq 'PALAIA_MDNS_ENABLED=0' "${ROOTFS}/etc/systemd/system/" 2>/dev/null; then
    fail "found PALAIA_MDNS_ENABLED=0 — the appliance image must not disable mDNS"
fi
pass "mDNS announcer is on (host networking, not disabled)"

# --- Port 80 redirect (issue #620) -----------------------------------------
# http://palaia.local/ without a port: palaia-http-redirect.service adds a
# kernel redirect of incoming port 80 to the container's 8420 (nftables,
# its own table) unless something else already listens on port 80. It lives
# outside the container, which keeps its hardening untouched.
REDIRECT_UNIT="${ROOTFS}/etc/systemd/system/palaia-http-redirect.service"
REDIRECT_SCRIPT="${ROOTFS}/usr/local/lib/palaia/http-redirect"
[ -f "${REDIRECT_UNIT}" ] || fail "palaia-http-redirect.service unit file is missing — nothing leads port 80 to the hub"
[ -x "${REDIRECT_SCRIPT}" ] || fail "/usr/local/lib/palaia/http-redirect is missing or not executable"
if [ -L "${ROOTFS}/etc/systemd/system/multi-user.target.wants/palaia-http-redirect.service" ]; then
    pass "palaia-http-redirect.service is enabled (multi-user.target.wants symlink present)"
else
    fail "palaia-http-redirect.service is not enabled — no multi-user.target.wants symlink found"
fi
grep -qF 'fib daddr type local tcp dport 80 redirect to :${HUB_PORT}' "${REDIRECT_SCRIPT}" \
    || fail "the http-redirect script no longer redirects incoming port 80"
grep -qx 'HUB_PORT=8420' "${REDIRECT_SCRIPT}" \
    || fail "the http-redirect script does not redirect to the hub's port 8420"
grep -qF "ss -Hltn 'sport = :80'" "${REDIRECT_SCRIPT}" \
    || fail "the http-redirect script no longer checks whether port 80 is taken"
[ -x "${ROOTFS}/usr/sbin/nft" ] || fail "nft is missing from the image — nftables did not install"
[ -x "${ROOTFS}/usr/bin/ss" ] || [ -x "${ROOTFS}/bin/ss" ] || fail "ss is missing from the image"
# Debian's nftables.service loads /etc/nftables.conf, which starts with
# `flush ruleset` — it would wipe Docker's rules and this redirect.
if [ -L "${ROOTFS}/etc/systemd/system/sysinit.target.wants/nftables.service" ] \
    || [ -L "${ROOTFS}/etc/systemd/system/multi-user.target.wants/nftables.service" ]; then
    fail "nftables.service is enabled — its default config flushes the whole ruleset"
fi
pass "port 80 leads to the hub (palaia-http-redirect.service → :8420, nftables.service off)"

# --- Cloud entry on loopback only ---------------------------------------------
# On the host network the container's cloud entry (8422) must not listen on
# the Pi's LAN addresses; a tunnel reaches it on loopback.
grep -q -- '-e PALAIA_CLOUD_BIND=127.0.0.1' "${PALAIA_UNIT}" \
    || fail "palaia.service does not keep the cloud entry on loopback (PALAIA_CLOUD_BIND=127.0.0.1)"
pass "the cloud entry listens on loopback only"

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
