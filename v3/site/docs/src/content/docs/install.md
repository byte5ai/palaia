---
title: Install it
description: Five minutes, one command, then your browser — installing palaia on any platform.
---

palaia runs as a single container. If you already have Docker (Docker
Engine on Linux, or Docker Desktop on macOS/Windows), this is the whole
install.

<!-- screenshot: the first-run wizard's welcome screen -->

## The one command

On a Linux machine — a home server, a NAS, a Raspberry Pi:

```bash
docker run -d --name palaia-hub \
  --network host -e PALAIA_CLOUD_BIND=127.0.0.1 \
  -v palaia_home:/data \
  --restart unless-stopped \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --read-only --tmpfs /tmp --tmpfs /run \
  ghcr.io/byte5ai/palaia-hub:stable
```

With Docker Desktop on macOS or Windows:

```bash
docker run -d --name palaia-hub \
  -p 8420:8420 \
  -v palaia_home:/data \
  --restart unless-stopped \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --read-only --tmpfs /tmp --tmpfs /run \
  ghcr.io/byte5ai/palaia-hub:stable
```

The two differ in one line only. On Linux the container shares the
machine's own network, so its name, `palaia.local`, reaches your other
devices (see [below](#finding-it-on-your-network-palaialocal)), and
`PALAIA_CLOUD_BIND` keeps the entrance for cloud AI apps on the machine
itself. Docker Desktop runs containers inside a hidden virtual machine, so
there the port is handed out instead.

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

Open `http://palaia.local:8420/` in your browser from any device on the
same network — a laptop, a phone — or `http://localhost:8420/` on the
machine itself (with Docker Desktop, always `http://localhost:8420/`).
palaia's setup opens by itself and walks you through, one step at a time:

1. **How you'll use palaia** — with ChatGPT and Claude (they reach palaia
   over a secure web address and sign in; the dashboard stays on your
   private network), or only on your own devices.
2. **Your first memory** — a name such as `work`. What it's for is
   optional; AI apps read it to pick the right memory.
3. **Your account** — a username and a password of at least 12 characters.
   Needed for ChatGPT and Claude; optional when palaia stays private.
4. **Cloud access** — only for ChatGPT and Claude: palaia's public `https://`
   address. palaia restarts once, asks you to sign in, then checks that
   address the way ChatGPT and Claude reach it.
5. **Connect an AI app** — the steps for the app you use, ending when
   palaia receives its first request.

Setup remembers where you are: after a reload or a restart it continues at
the first step that is still open. See [Connect your AI](/connect/) for
every app.

Installing on a Linux server instead? [Get palaia running](/onboarding/)
has the one command that also sets up Docker and Tailscale.

## Prefer a config file, or already run other containers?

A ready-to-use file is at `v3/deploy/docker-compose.yml` in the palaia
repository. It is set up like the Linux command above; its first lines say
the three edits for Docker Desktop.

```bash
git clone https://github.com/byte5ai/palaia.git
cd palaia/v3/deploy && docker compose up -d
```

Or, a script that runs the right one of the two commands with a couple of
sanity checks (Docker present, Docker actually running) and prints the
address to open at the end:

```bash
curl -fsSL https://get.palaia.ai/docker | bash
```

None of these three paths is more "correct" than another — pick whichever
fits how you already manage containers.

## Finding it on your network: `palaia.local`

The container announces itself as `palaia.local` on your local network, so
you don't have to remember an IP address: `http://palaia.local:8420/`
opens it from your other devices, the way a Home Assistant box opens at its
name and `:8123`. The `:8420` stays part of the address — the container
runs without any special rights, and the plain web port (80) needs them.
Whether the name reaches your devices depends on how your container engine
handles network traffic:

- **Docker on Linux** — the Linux command and the compose file run the
  container on the machine's own network, so `palaia.local` resolves for
  other devices on the same network that support it (most desktops and
  phones do). Some routers keep the name from crossing between separate
  networks, such as a guest Wi-Fi.
- **Docker Desktop (macOS/Windows)** runs containers inside a hidden VM, so
  the announcement never reaches your actual network. `palaia.local` will
  not resolve here — use `http://localhost:8420/` on that computer.

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
dashboard footer shows the version you're running; when a newer one is
published, a notice appears at the top of the dashboard with the steps for
your kind of install.

If you install through a self-hosting app store (Umbrel, CasaOS, Runtipi,
TrueNAS SCALE, and similar), check there first — those platforms often
handle updates and networking for you, and a listing may not be live for
every platform yet.
