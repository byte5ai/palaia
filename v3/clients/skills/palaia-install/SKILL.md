---
name: palaia-install
description: Set up palaia for someone from scratch, as a guided conversation, when they ask you to install it, get it running, or help them host it — on a rented cloud server (VPS), a home NAS box, a Raspberry Pi, or their own computer. Use this the moment someone wants palaia running and does not already have it; ask them where it should live and walk them through it one step at a time, running the commands for them when you can and handing them a single command to paste when you cannot. Do not use it for connecting an AI tool to an already-running palaia, or for changing an existing install.
license: MIT
---

# Get palaia running

You are setting palaia up for someone who may not be technical. Your job is to
ask a few plain questions, then do the work — run the commands yourself if you
can reach their machine, otherwise give them exactly one line to paste. Never
show them a wall of Docker commands and never assume they know what any of this
means. One step at a time; wait for each to finish before the next.

palaia runs on a machine they own and is reached in a browser. It is almost
always a separate always-on box (a rented server, a NAS, a small Pi), because a
hub that only serves the laptop it lives on gives up the point of it. Keep that
in mind when they are unsure where to put it.

## Before you start — read the real files

The setup file and the install command change between releases, so never
write them from memory, and never from this page alone. Read them from the
files palaia actually ships, every time:

| What | File |
|---|---|
| The setup file pasted in when a server is created | `v3/deploy/cloud-init.yaml` |
| The installer for a server that already exists | `v3/deploy/get-palaia.sh` |
| Notes on reboots, updates and backups | `v3/deploy/README.md` |
| Which release this is | `v3/VERSION` |

If you are working inside a copy of the palaia repository, read them there.
Otherwise open each one under
`https://raw.githubusercontent.com/byte5ai/palaia/main/` — for example
`https://raw.githubusercontent.com/byte5ai/palaia/main/v3/deploy/cloud-init.yaml`.
Read all four from the same place, so they belong to the same release. If you
cannot open files or web pages at all, say so plainly and do not make the
commands up.

### Which image this release uses

Read `v3/VERSION`. If it contains a hyphen (like 3.0.0-rc2), this is a test
release: palaia's image is published only under the `beta` name, and the
everyday `stable` name does not exist yet. With no hyphen (like 3.0.0), it is
a full release and `stable` is right.

- **The setup file already handles this.** It names the image that matches
  its release. Never change its image line.
- **The installer needs to be told.** For a test release, add
  `PALAIA_CHANNEL=beta` to its command (Step 3 shows where). For a full
  release, leave it out.

## Step 1 — Where should palaia live?

Ask this first. Offer the four choices in plain words:

- **A rented cloud server (VPS)** — Hetzner, DigitalOcean, Netcup, and similar.
  The most common answer. Go to Step 2.
- **A home NAS** — Synology, Umbrel, TrueNAS, CasaOS. These have their own app
  store; point them to palaia's listing there and skip the rest of this skill.
- **A Raspberry Pi** — they flash a ready-made palaia image onto an SD card.
  Point them at the Pi image attached to the latest release and its flashing
  guide; skip the rest.
- **Their own computer** — uncommon, but fine for a quick try. If it runs
  Linux, treat it like an existing server (Step 3); when they only want to
  reach palaia from that same computer, `PALAIA_NO_TAILSCALE=1` takes the place
  of the key and Step 4 can be skipped. On a Mac or Windows PC the installer
  does not apply: they need Docker Desktop and the first command under "Quick
  start" in `v3/deploy/README.md` (with the image name from "Which image this
  release uses").

## Step 2 — VPS: does the server already exist?

Only for the rented-server path. Ask whether they have already created the
server, or are about to.

- **Not yet created** — the easiest path. You will prepare a small setup file
  they paste into one field when they create the server, so no commands are
  needed at all. Go to Step 2a.
- **Already created (it exists and is empty)** — that paste-at-creation field is
  no longer available to them, so you set it up over a remote connection
  instead. Go to Step 3.

### Step 2a — Not yet created: the paste-at-creation file

1. Get the private-network key first (Step 4).
2. Take `v3/deploy/cloud-init.yaml` exactly as it is and make **one** change:
   replace the text `TAILSCALE_AUTH_KEY="tskey-REPLACE_ME"` with
   `TAILSCALE_AUTH_KEY="<their-key>"`. That text appears twice — once in the
   explanation at the top and once where the key is really set — and changing
   both is fine.
3. Do **not** replace every `tskey-REPLACE_ME` in the file. One of them sits in
   the line that checks whether the key was forgotten; change that one too and
   the server stops right away with an error nobody is watching.
4. Check your copy before handing it over: the first line is still
   `#cloud-config`, the key line holds their key, the checking line still says
   `tskey-REPLACE_ME`, and nothing else changed — not the image line, not the
   indentation.
5. Give them the whole file as one block to copy. Tell them to paste it into
   the field their provider shows when creating a server — Hetzner calls it
   "Cloud config", others call it "User data" — then create the server. The
   file now contains their key: they should not share it or keep it lying
   around.
6. Nothing else to run. Setting itself up takes a few minutes after the server
   starts. Go to Step 5.

## Step 3 — An existing server: set it up remotely

You need to reach the server. Ask for its address and whether they can give you
a way in (an SSH login), or whether they would rather paste one line themselves.

Build the one line from the installer itself: the top of
`v3/deploy/get-palaia.sh` names the command to run, which today is

```
curl -fsSL https://get.palaia.ai | sh
```

Put their key (Step 4) between the `|` and `sh`, so the installer does not
stop to ask for it:

```
curl -fsSL https://get.palaia.ai | PALAIA_TSKEY=<their-key> sh
```

For a test release (see "Which image this release uses"), add the image name
the same way, still one line:

```
curl -fsSL https://get.palaia.ai | PALAIA_TSKEY=<their-key> PALAIA_CHANNEL=beta sh
```

- **You can reach it** — run that line on the server yourself.
- **You cannot** — give them the line to paste into their server's terminal,
  and ask them to send back the last few lines it prints.

The installer puts everything in place — the container engine, the private
network, the firewall, and palaia itself — and ends with a line starting
`done ✓  Open` followed by the address to open. Go to Step 5.

## Step 4 — The private-network key (Tailscale)

A rented server sits on the open internet, so palaia is placed on the person's
own private network (Tailscale) and is reachable only from their own devices,
never publicly. You need one key for this.

Walk them through it:

1. If they do not use Tailscale yet: create a free account and install the
   Tailscale app on the computer they will open palaia from.
2. Generate a key at `https://login.tailscale.com/admin/settings/keys` →
   **Generate auth key**.
3. Two warnings that save the most common failures:
   - Pick **auth key**, not **access token** — they sit next to each other and
     the access token will be rejected with a confusing error. An auth key
     starts with `tskey-auth-`; one starting with `tskey-api-` is the access
     token.
   - Leave **Reusable** and **Ephemeral** off. (The setup file's own comment
     says a reusable, ephemeral key also works; keep it simple and leave both
     off — a server on an ephemeral key can drop off the private network after
     it has been offline for a while.)

Keep the key only long enough to use it; treat it like a password.

## Step 5 — Confirm it worked, then the next step

However it was installed, the end state is the same: palaia answers in a
browser on the private network, on port `8420`.

- **Installer path** — the address is in the installer's last line.
- **Setup-file path** — nothing is printed anywhere they can see. After a few
  minutes, ask them to open the machine list in their Tailscale admin page and
  look for a machine named `palaia-hub`; its address, with `:8420` added, is
  the one to open in a browser (`http://<address>:8420/`).

If it answers: give them that address and tell them the next step is opening it
and connecting their first AI tool. If it does not, go to Step 6.

## Step 6 — When it does not come up

Name the likely cause in plain words; never paste raw error output at them.

**The installer path** prints its own errors, each starting `palaia: ERROR:`
and saying what to do. Translate it:

- The key was an access token, expired, or already used — get a fresh
  **auth key** (Step 4) and run the line again.
- It joined the private network but got no address yet — wait a moment and run
  the line again.
- It could not download palaia's image — check "Which image this release
  uses"; for a test release the line needs `PALAIA_CHANNEL=beta`.

**The setup-file path** writes everything it did to one log on the server:
`/var/log/cloud-init-output.log`. Only the hub itself is kept off the public
internet; SSH still works, so they (or you) can log in to the server's public
address, or use the provider's web console, and run
`sudo tail -n 50 /var/log/cloud-init-output.log`. Every line palaia's own setup
writes starts with `palaia cloud-init:`, so the last of those shows how far it
got:

- **It stops with `ERROR: edit this file's TAILSCALE_AUTH_KEY`** — the key was
  never filled in, or the checking line was changed too. The server exists
  now, so do not recreate it: finish with Step 3's installer on it.
- **It stops after `joining the tailnet ...`** with a Tailscale error below it —
  the key was rejected (an access token, expired, or a one-time key already
  used). Get a fresh auth key, then finish with Step 3's installer.
- **It stops after `pulling`, with a download error** — the setup file names the
  right image for its release, so this is almost always a passing network or
  download hiccup. Re-run the setup on the server, which is safe to repeat:
  `sudo bash /opt/palaia/cloud-init-setup.sh`. If someone edited the image line,
  put the original file's line back first.
- **The last line starts `done. Open`, yet the page does not open** — the
  device they are browsing from must be on the same Tailscale network with the
  app switched on. Right after the server restarts, a minute or two of
  "connection refused" is normal: palaia waits for its private-network address
  and retries by itself (the "Reboots" note in `v3/deploy/README.md`). Only if
  it still refuses after five minutes, look at palaia's own log with
  `sudo docker logs --tail 50 palaia-hub` and translate what it says.

## What not to do

- Do not open with Docker, compose files, or app-store jargon. Those are a
  fallback for technical people, not the path here.
- Do not invent where their palaia runs or which provider they use — ask.
- Do not write the setup file or the install line from memory — read them
  (see "Before you start").
- Do not pick the image name yourself; it follows `v3/VERSION`.

## Per-model notes

The line for your family wins; the unlabelled line is the default.

- Ask where it should live before anything else, every time.
- [anthropic] Run the command yourself when you can reach their machine; only
  hand over a line when you cannot.
- [openai] One question at a time, and wait for the result before the next — do
  not print the whole plan up front.
- [google] Keep each step to one action and confirm it worked before moving on.
