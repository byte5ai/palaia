---
title: Install it
description: Five minutes, one command, then your browser — installing palaia on any platform.
---

palaia runs as a single container. If you already have Docker (Docker
Desktop on macOS/Windows, or Docker Engine on Linux), this is the whole
install.

<!-- screenshot: the first-run wizard's welcome screen -->

## The one command

```bash
docker run -d --name palaia-hub \
  -p 8420:8420 \
  -v palaia_home:/data \
  --restart unless-stopped \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --read-only --tmpfs /tmp --tmpfs /run \
  ghcr.io/byte5ai/palaia-hub:stable
```

<!-- rc-channel-note -->
> **Release candidate:** until `3.0.0` is final there is no `stable` image yet. Where a
> command or file on this page says `ghcr.io/byte5ai/palaia-hub:stable`, use
> `ghcr.io/byte5ai/palaia-hub:beta` for now.

The five extra flags close off what a non-root container process could
otherwise still reach — nothing about the install changes if you leave
them off, they simply make the container harder to escape from if
something inside it were ever compromised.

That pulls the image, starts it, and keeps it running (and restarting after
a reboot). Everything palaia saves lives in the `palaia_home` volume, so the
container itself is disposable — you can remove and recreate it without
losing anything.

Open `http://localhost:8420/` in your browser (or the machine's address, if
you're installing on a home server and browsing from a laptop). A short
first-run setup walks you through:

1. **An administrator sign-in** for the dashboard.
2. **How far your memory reaches** — just this device and network, or the
   internet too (with sign-in required the moment it is). You can change
   this later; starting local is the safe default.
3. **Your first memory** — give it a name and a one-line purpose ("work" or
   "personal" is plenty to start).

From there you land on a page whose whole job is getting your first AI tool
connected — see [Connect your AI](/connect/).

## Prefer a config file, or already run other containers?

A ready-to-use file is at `v3/deploy/docker-compose.yml` in the palaia
repository:

```bash
git clone https://github.com/byte5ai/palaia.git
cd palaia/v3/deploy && docker compose up -d
```

Or, a script that does the same one-liner with a couple of sanity checks
(Docker present, Docker actually running) and prints the address to open at
the end:

```bash
curl -fsSL https://raw.githubusercontent.com/byte5ai/palaia/main/v3/deploy/install.sh | bash
```

None of these three paths is more "correct" than another — pick whichever
fits how you already manage containers.

## Finding it on your network: `palaia.local`

The container tries to advertise itself as `http://palaia.local` on your
local network, so you don't have to remember an IP address. Whether that
actually reaches your other devices depends on how your container engine
handles network traffic:

- **Docker on Linux**, with `--network host` (a commented-out line in the
  compose file turns this on) — `palaia.local` resolves for other devices
  on the same network that support it (most desktops and phones do).
- **Docker Desktop (macOS/Windows)** runs containers inside a hidden VM, so
  the advertisement never reaches your actual network. `palaia.local` will
  not resolve here — use the machine's regular address instead.

Either way, nothing about setup depends on this working: every startup
prints the address that does work to the container's log
(`docker logs palaia-hub`), and the wizard is reachable at that address
regardless.

## Later: updating

Phase one keeps this manual and honest about it — there is no silent
in-place update:

```bash
docker pull ghcr.io/byte5ai/palaia-hub:stable
docker compose up -d   # or the equivalent docker run, after docker rm
```

Your data lives in the named volume, not the container, so this is safe —
pulling a newer image and recreating the container keeps everything. The
dashboard footer shows the version you're running and tells you when a
newer one is published.

If you install through a self-hosting app store (Umbrel, CasaOS, Runtipi,
TrueNAS SCALE, and similar), check there first — those platforms often
handle updates and networking for you, and a listing may not be live for
every platform yet.
