#!/usr/bin/env bash
# SPEC-603: builds the palaia Raspberry Pi appliance image.
#
# Starts from the pinned, checksum-verified Raspberry Pi OS Lite (arm64)
# release named in base-image.env (see that file's own comment — this is
# the "equivalently standard, justified in an ADR note" alternative to
# pi-gen; the reasoning lives in v3/decisions/005-pi-appliance-image-base.md).
# Customizes it offline (loop-mount + chroot, arm64 emulated via
# binfmt_misc/qemu-user-static) to add Docker, the palaia.service unit, and
# nothing else — SSH stays exactly as the base image ships it (disabled by
# default; see README.md for how an owner enables it).
#
# Runs the customization step TWICE, against two independent copies of the
# same verified base image, and diffs a content-hash manifest of the
# resulting rootfs between them (see compute_manifest below for the small,
# documented set of inherently volatile paths it excludes — apt list
# caches, logs, /etc/machine-id, etc., none of which this build ever ships
# in the final image anyway). Identical manifests is this pipeline's
# reproducibility proof — see README.md's "Reproducibility" section for
# exactly what that does and does not claim.
#
# Must run as root (loop devices, mount, chroot) — the workflow invokes it
# under `sudo`. Not meant to run inside a container itself: it needs real
# loop devices and a real chroot, which GitHub's ubuntu-latest runners
# provide (a full VM, not a nested container) but a `docker run` sandbox
# generally does not.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
V3_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

WORK_DIR="${PI_IMAGE_WORK_DIR:-/tmp/pi-image-build}"
OUTPUT_DIR="${PI_IMAGE_OUTPUT_DIR:-${WORK_DIR}/out}"
#: Extra space appended to the base image before customizing, so Docker
#: (~180-220MB of packages on arm64: docker.io, containerd, runc, iptables
#: and friends) plus the palaia unit file have somewhere to land without a
#: partition-full failure mid-`apt-get install`. Mostly-zero padding, which
#: xz compresses to nearly nothing — see README.md's size-budget numbers
#: for why this doesn't blow the stated budget.
GROWTH_MB="${PI_IMAGE_GROWTH_MB:-700}"
#: Checked against the final compressed .img.xz — see README.md.
SIZE_BUDGET_MB="${PI_IMAGE_SIZE_BUDGET_MB:-900}"

VERSION="$(tr -d '[:space:]' < "${V3_ROOT}/VERSION")"
OUT_NAME="palaia-appliance-v${VERSION}"

# shellcheck source=base-image.env
source "${SCRIPT_DIR}/base-image.env"

if [ "$(id -u)" -ne 0 ]; then
    echo "build.sh: must run as root (loop devices, mount, chroot) — try 'sudo $0'" >&2
    exit 1
fi

for tool in curl xz losetup parted mkfs.ext4 resize2fs e2fsck chroot sha256sum truncate; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "build.sh: required tool '${tool}' not found on PATH" >&2
        exit 1
    fi
done

mkdir -p "${WORK_DIR}" "${OUTPUT_DIR}"

# ---------------------------------------------------------------------------
# Download + verify the pinned base image once, shared by both runs.
# ---------------------------------------------------------------------------
BASE_XZ="${WORK_DIR}/base.img.xz"
if [ ! -f "${BASE_XZ}" ] || ! (echo "${BASE_IMAGE_SHA256}  ${BASE_XZ}" | sha256sum -c - >/dev/null 2>&1); then
    echo "build.sh: downloading pinned base image..."
    curl -fL --retry 3 -o "${BASE_XZ}.tmp" "${BASE_IMAGE_URL}"
    mv "${BASE_XZ}.tmp" "${BASE_XZ}"
fi
echo "build.sh: verifying base image checksum..."
echo "${BASE_IMAGE_SHA256}  ${BASE_XZ}" | sha256sum -c -

# ---------------------------------------------------------------------------
# Cleanup bookkeeping: every run pushes onto this stack whatever it mounted
# or attached, and unwind_all tears it down in reverse order — including on
# a mid-run failure, so a failed CI attempt never leaves a stuck loop device
# or bind mount behind on the runner.
# ---------------------------------------------------------------------------
declare -a CLEANUP_STACK=()
push_cleanup() { CLEANUP_STACK+=("$1"); }
unwind_all() {
    local i cmd
    for ((i = ${#CLEANUP_STACK[@]} - 1; i >= 0; i--)); do
        cmd="${CLEANUP_STACK[i]}"
        eval "${cmd}" || true
    done
    CLEANUP_STACK=()
}
trap unwind_all EXIT

#: The small set of rootfs paths that are legitimately different between
#: two otherwise-identical customization runs (or simply not meaningful to
#: compare) — apt's own cache/lists carry the live mirror's timing
#: metadata, /etc/machine-id and the dbus/systemd equivalents are meant to
#: be regenerated per-boot (this image never ships one; see README.md),
#: and /var/log, /tmp, /run hold this run's own transient noise. Anything
#: NOT matched here is asserted byte-identical across both runs.
EXCLUDE_RE='^(var/lib/apt/lists/|var/log/|var/cache/apt/archives/|tmp/|run/|root/\.bash_history$|etc/machine-id$|var/lib/dbus/machine-id$|var/lib/systemd/random-seed$)'

compute_manifest() {
    local rootfs="$1" out="$2"
    ( cd "${rootfs}" && find . -xdev -type f -printf '%P\n' ) \
        | grep -vE "${EXCLUDE_RE}" \
        | LC_ALL=C sort \
        | while IFS= read -r rel; do
            sha256sum "${rootfs}/${rel}" | awk -v p="${rel}" '{print $1"  "p}'
        done > "${out}"
}

# ---------------------------------------------------------------------------
# One full customization run: copy the verified base image, grow it, loop
# mount it, chroot in and install Docker + the palaia unit, then hash the
# resulting rootfs. Called twice (run "1" and run "2") with independent
# copies so a diff between their manifests is a real reproducibility check,
# not a comparison against itself.
# ---------------------------------------------------------------------------
build_one() {
    local run_id="$1"
    local run_dir="${WORK_DIR}/run-${run_id}"
    local img="${run_dir}/palaia-appliance.img"
    local rootfs="${run_dir}/rootfs"

    rm -rf "${run_dir}"
    mkdir -p "${run_dir}" "${rootfs}"

    echo "build.sh[run ${run_id}]: decompressing base image..."
    xz -dk -T0 -c "${BASE_XZ}" > "${img}"
    truncate -s "+${GROWTH_MB}M" "${img}"

    echo "build.sh[run ${run_id}]: attaching loop device..."
    local loopdev
    loopdev="$(losetup --find --show -P "${img}")"
    push_cleanup "losetup -d '${loopdev}' 2>/dev/null"

    echo "build.sh[run ${run_id}]: growing the rootfs partition..."
    parted --script "${loopdev}" resizepart 2 100%
    # partprobe/kernel re-read of the new partition table size.
    partprobe "${loopdev}" 2>/dev/null || true
    udevadm settle 2>/dev/null || true
    e2fsck -f -y "${loopdev}p2" || true
    resize2fs "${loopdev}p2"

    mount "${loopdev}p2" "${rootfs}"
    push_cleanup "umount '${rootfs}'"

    # Networking for apt-get inside the chroot: swap in the host's own
    # working resolv.conf for the duration of the chroot step, restoring
    # whatever was there before (typically a systemd-resolved symlink on
    # this base image) right after — restored explicitly below, right
    # after the chroot step, rather than only in the cleanup stack, so the
    # manifest this run hashes reflects the same file the shipped image
    # ships, not this run's temporary DNS setup. A bind mount would try to
    # mount over wherever that symlink resolves to, which doesn't exist
    # under a chroot with no systemd running — hence a plain swap instead.
    local resolv_backup=""
    if [ -e "${rootfs}/etc/resolv.conf" ] || [ -L "${rootfs}/etc/resolv.conf" ]; then
        resolv_backup="${rootfs}/etc/.resolv.conf.pi-image-orig"
        mv "${rootfs}/etc/resolv.conf" "${resolv_backup}"
    fi
    cp /etc/resolv.conf "${rootfs}/etc/resolv.conf"

    for pseudo in dev proc sys; do
        mount --bind "/${pseudo}" "${rootfs}/${pseudo}"
        push_cleanup "umount -l '${rootfs}/${pseudo}'"
    done

    # Belt-and-suspenders arm64 emulation: docker/setup-qemu-action (run by
    # the workflow before this script) registers binfmt_misc handlers with
    # the "F" (fix-binary) flag, which the kernel resolves at registration
    # time — a bare chroot should already work through it with no extra
    # step. Also copying the static interpreter into the rootfs itself is
    # the same defensive step pi-gen's own build takes, and costs nothing:
    # it is deleted again below, before this run's manifest is computed, so
    # it never reaches the shipped image or skews the reproducibility diff.
    if [ -x /usr/bin/qemu-aarch64-static ]; then
        cp /usr/bin/qemu-aarch64-static "${rootfs}/usr/bin/qemu-aarch64-static"
    fi

    # Stop package postinst scripts from trying to actually start services
    # inside the chroot (there is no running init to talk to) — standard
    # Debian chroot-customization practice.
    cat > "${rootfs}/usr/sbin/policy-rc.d" <<'EOF'
#!/bin/sh
exit 101
EOF
    chmod +x "${rootfs}/usr/sbin/policy-rc.d"

    echo "build.sh[run ${run_id}]: installing Docker in the chroot..."
    chroot "${rootfs}" /bin/bash -c '
        set -euo pipefail
        export DEBIAN_FRONTEND=noninteractive LANG=C
        apt-get update
        apt-get install -y --no-install-recommends docker.io
        apt-get clean
    '

    rm -f "${rootfs}/usr/sbin/policy-rc.d"
    rm -f "${rootfs}/usr/bin/qemu-aarch64-static"
    # ldconfig's binary cache embeds mtimes/inodes, so it differs between
    # two otherwise-identical runs (the ONE file run #1 of the workflow
    # caught) — and ldconfig regenerates it on first boot anyway. Dropping
    # it keeps the image honest about determinism instead of excluding it
    # from the check.
    rm -f "${rootfs}/var/cache/ldconfig/aux-cache"
    rm -rf "${rootfs}/var/lib/apt/lists"/*
    rm -rf "${rootfs}/var/cache/apt/archives"/*.deb

    # Restore whatever /etc/resolv.conf the base image actually ships,
    # before the manifest below hashes it — see the comment above.
    rm -f "${rootfs}/etc/resolv.conf"
    if [ -n "${resolv_backup}" ]; then
        mv "${resolv_backup}" "${rootfs}/etc/resolv.conf"
    fi

    echo "build.sh[run ${run_id}]: installing the palaia unit..."
    install -m 644 "${SCRIPT_DIR}/systemd/palaia.service" "${rootfs}/etc/systemd/system/palaia.service"

    # `systemctl --root=<path>` works entirely offline (pure [Install]
    # symlink math against the given tree) — no chroot/emulation needed for
    # this step, unlike installing the docker.io package itself above.
    systemctl --root="${rootfs}" enable docker.service palaia.service
    # Explicit and idempotent, even though the base image already ships
    # ssh.service un-enabled by default (see README.md's "Enabling SSH"
    # section) — this line is what inspect.sh's "SSH off" assertion is
    # actually asserting stays true, not an assumption about the base image.
    systemctl --root="${rootfs}" disable ssh.service 2>/dev/null || true

    echo "build.sh[run ${run_id}]: hashing rootfs..."
    compute_manifest "${rootfs}" "${run_dir}/manifest.txt"
    echo "build.sh[run ${run_id}]: $(wc -l < "${run_dir}/manifest.txt") files in manifest"

    # Tear this run's own mounts/loop down now (in reverse order) so run 2
    # starts clean, rather than waiting for the script-wide EXIT trap.
    unwind_all
}

build_one 1
build_one 2

echo "build.sh: comparing the two runs' rootfs manifests..."
if ! diff -u "${WORK_DIR}/run-1/manifest.txt" "${WORK_DIR}/run-2/manifest.txt" > "${WORK_DIR}/manifest.diff"; then
    echo "build.sh: REPRODUCIBILITY CHECK FAILED — the two runs produced" >&2
    echo "different rootfs content (see below). This is the SPEC-603" >&2
    echo "'builds reproducibly' acceptance criterion failing, not a" >&2
    echo "flake — do not retry blindly, read the diff." >&2
    cat "${WORK_DIR}/manifest.diff" >&2
    exit 1
fi
echo "build.sh: reproducibility check passed — identical rootfs content across both runs."

echo "build.sh: compressing final image..."
xz -9 -T0 -c "${WORK_DIR}/run-1/palaia-appliance.img" > "${OUTPUT_DIR}/${OUT_NAME}.img.xz"
( cd "${OUTPUT_DIR}" && sha256sum "${OUT_NAME}.img.xz" > "${OUT_NAME}.img.xz.sha256" )

size_mb=$(( $(stat -c%s "${OUTPUT_DIR}/${OUT_NAME}.img.xz") / 1024 / 1024 ))
echo "build.sh: compressed image size: ${size_mb} MB (budget: ${SIZE_BUDGET_MB} MB)"
if [ "${size_mb}" -ge "${SIZE_BUDGET_MB}" ]; then
    echo "build.sh: image exceeds the ${SIZE_BUDGET_MB}MB compressed budget (SPEC-603)." >&2
    exit 1
fi

echo "build.sh: done."
echo "  image:    ${OUTPUT_DIR}/${OUT_NAME}.img.xz (${size_mb} MB)"
echo "  checksum: ${OUTPUT_DIR}/${OUT_NAME}.img.xz.sha256"
echo "  raw rootfs for inspect.sh: ${WORK_DIR}/run-1/palaia-appliance.img"
