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

## Step 1 — Where should palaia live?

Ask this first. Offer the four choices in plain words:

- **A rented cloud server (VPS)** — Hetzner, DigitalOcean, Netcup, and similar.
  The most common answer. Go to Step 2.
- **A home NAS** — Synology, Umbrel, TrueNAS, CasaOS. These have their own app
  store; point them to palaia's listing there and skip the rest of this skill.
- **A Raspberry Pi** — they flash a ready-made palaia image onto an SD card.
  Point them at the Pi image attached to the latest release and its flashing
  guide; skip the rest.
- **Their own computer** — uncommon, but fine for a quick try. Treat it like an
  existing server (Step 3), and you may skip the private-network part if they
  only want to reach it from that same computer.

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

1. Get a private-network key first (Step 4), so you can put it into the file.
2. Hand them the ready setup file (`v3/deploy/cloud-init.yaml`), with the key
   already filled in and the release-candidate image tag set (see Step 5's note
   on tags). Tell them to paste the **whole file** into the field their provider
   shows when creating a server — Hetzner calls it "Cloud config", others call
   it "User data" — then create the server.
3. Nothing else to run. Go to Step 5 to confirm it came up.

## Step 3 — An existing server: set it up remotely

You need to reach the server. Ask for its address and whether they can give you
a way in (an SSH login), or whether they would rather paste one line themselves.

- **You can reach it** — run the one installer command on it yourself.
- **You cannot** — give them this single line to paste into their server's
  terminal, and ask them to send back the last few lines it prints:

  ```
  curl -fsSL https://get.palaia.ai | sh
  ```

Either way you first need the private-network key (Step 4). Pass it to the
installer instead of it asking, like this (still one line):

```
curl -fsSL https://get.palaia.ai | PALAIA_TSKEY=<their-key> sh
```

The installer puts everything in place — the container engine, the private
network, the firewall, and palaia itself — and prints the address to open at
the end. Go to Step 5.

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
     the access token will be rejected with a confusing error.
   - Leave **Reusable** and **Ephemeral** off.

Keep the key only long enough to use it; treat it like a password.

## Step 5 — Confirm it worked, then the next step

However it was installed, the end state is the same: palaia answers in a browser
at a private-network address, printed as `http://<address>:8420/`.

- If it answers: give them that address and tell them the next step is opening it
  and connecting their first AI tool.
- If it does not, name the likely cause in plain words rather than pasting an
  error:
  - The key was an access token, or expired, or already used — get a fresh
    **auth key** and run it again.
  - It reported no private-network address — the network had not finished
    joining; wait a moment and run it again.
  - It could not download palaia's image — while palaia is still a release
    candidate the plain image tag does not exist yet, so the release-candidate
    tag must be used (`PALAIA_CHANNEL=beta` for the installer). This will stop
    being a problem once palaia has its first full release.

## What not to do

- Do not open with Docker, compose files, or app-store jargon. Those are a
  fallback for technical people, not the path here.
- Do not invent where their palaia runs or which provider they use — ask.
- Do not paste raw error output at them; translate it.

## Per-model notes

The line for your family wins; the unlabelled line is the default.

- Ask where it should live before anything else, every time.
- [anthropic] Run the command yourself when you can reach their machine; only
  hand over a line when you cannot.
- [openai] One question at a time, and wait for the result before the next — do
  not print the whole plan up front.
- [google] Keep each step to one action and confirm it worked before moving on.
