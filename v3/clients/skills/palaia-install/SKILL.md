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

| What | File | Address |
|---|---|---|
| The setup file pasted in when a server is created | `v3/deploy/cloud-init.yaml` | `https://get.palaia.ai/cloud-init` |
| The installer for a server that already exists | `v3/deploy/get-palaia.sh` | `https://get.palaia.ai/install` |
| Notes on reboots, updates and backups | `v3/deploy/README.md` | `https://get.palaia.ai/deploy-notes` |
| Which release this is | `v3/VERSION` | `https://get.palaia.ai/version` |

If you are working inside a copy of the palaia repository, read the files
there. Otherwise open each address — those are the only addresses to use or
show; never point the person at any other place to download from.
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
  of the setup code and Step 4 can be skipped. On a Mac or Windows PC the installer
  does not apply: they need Docker Desktop and the first command under "Quick
  start" in `v3/deploy/README.md` (with the image name from "Which image this
  release uses").

## Step 2 — VPS: does the server already exist?

Only for the rented-server path. Ask whether they have already created the
server, or are about to.

- **Not yet created** — the easiest path: a small setup file they paste into
  one field when they create the server. No commands at all. Go to Step 2a.
- **Already created** — go to Step 3. If it is still empty and they cannot
  give you a way in, recreating it with the setup file (Step 2a) avoids the
  provider's console entirely; offer that as a choice.

### The setup code

Every path ends on palaia's one-time setup page (Step 4), which only opens for
a setup code. Make one up yourself: 12 characters from capital letters and
digits, without 0, O, 1 or I, written in three groups like `K7QM-R2XD-9FTP`.
Tell them the code and ask them to keep it until setup is done. It is not a
password for later: it only works while the setup page is open.

### Step 2a — Not yet created: the paste-at-creation file

1. Take `v3/deploy/cloud-init.yaml` exactly as it is and make **one** change:
   replace `PALAIA_SETUP_CODE="setup-code-REPLACE_ME"` with
   `PALAIA_SETUP_CODE="<code>"`, using your code. That text appears twice — in
   the explanation at the top and where it is really set — change both.
2. Check your copy: the first line is still `#cloud-config`, the code line
   holds the code, and nothing else changed — not the image line, not the
   indentation.
3. Give them the whole file as one block to copy. They paste it into the field
   their provider shows when creating a server — Hetzner calls it "Cloud
   config", others "User data" — then create the server.
4. Ask for the server's address once the provider shows it. Go to Step 4.

## Step 3 — An existing server: set it up remotely

Ask in one go: the server's address, and how they log in — with a key already
on this computer, with a password (the provider emailed or showed it), or they
do not know (then ask whether the provider sent a password; if so, that is the
password path). Never ask them to type a password into the chat: whatever is
written there stays in the conversation.

The installer line comes from the top of `v3/deploy/get-palaia.sh`; today:

```
curl -fsSL https://get.palaia.ai | sh
```

Put your setup code between the `|` and `sh`, so you already know it:

```
curl -fsSL https://get.palaia.ai | PALAIA_SETUP_CODE=<code> sh
```

For a test release (see "Which image this release uses"), still one line:

```
curl -fsSL https://get.palaia.ai | PALAIA_SETUP_CODE=<code> PALAIA_CHANNEL=beta sh
```

The installer sets up the container engine and the private-network software,
then opens the setup page and waits there — up to 30 minutes — until they
have finished it. So start it in a way that keeps running after your command
returns (your tool's background mode, for example), and go to Step 4 while it
waits. Afterwards it starts palaia and ends with a line starting
`done ✓  Open` followed by palaia's address.

The commands below log in as root, which most providers set up; if theirs
gave a different user name, use that. "Run the installer line through it"
means: put the line, in single quotes, in place of the final word true. If a
login prints an error, see "When the login fails" in Step 6.

**3a — With a key.** Check you get in (these options never hang on a
question); no output means you are in, then run the installer line through it:

```
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 root@<address> true
```

**3b — With a password, and you can run commands on their computer** (the
commands you show get a Run button, or there is a terminal next to the chat).
The password goes into a private file on their computer and never through the
chat. Show them this one line and say: "Click Run (or paste it into the
terminal), type your server password when it asks, press Enter. Nothing
appears while you type — that is normal." Wait until it printed "saved".

```bash
mkdir -p ~/.palaia-setup && chmod 700 ~/.palaia-setup && printf 'Server password: ' && read -rs PW && (umask 077 && printf '%s\n' "$PW" > ~/.palaia-setup/pw) && unset PW && echo ' saved'
```

Then create a helper that hands the saved password to the login (it holds no
secret itself), check you get in, and run the installer line through the
second command:

```
printf '#!/bin/sh\ncat "$HOME/.palaia-setup/pw"\n' > ~/.palaia-setup/askpass && chmod 700 ~/.palaia-setup/askpass
SSH_ASKPASS="$HOME/.palaia-setup/askpass" SSH_ASKPASS_REQUIRE=force ssh -o StrictHostKeyChecking=accept-new -o PreferredAuthentications=password,keyboard-interactive -o NumberOfPasswordPrompts=1 -o ConnectTimeout=15 root@<address> true
```

When done — or if they stop halfway — delete the saved password:

```
rm -rf ~/.palaia-setup
```

**3c — You cannot run commands for them** (a chat with no Run button and no
terminal). First offer the no-console way if the server is still empty:
recreate it with the setup file (Step 2a). If they would rather keep it, give
them the plain installer line (with `PALAIA_CHANNEL=beta` for a test release,
without a code) to paste into their provider's web console — most providers
have a "Console" button for the server. The screen then shows the address to
open and the setup code. Go to Step 4.

## Step 4 — The setup page: joining their private network

A rented server sits on the open internet, so palaia is placed on the person's
own private network (Tailscale) and is reachable only from their own devices.
The setup page does this in the browser, with no key to copy.

1. If they do not use Tailscale yet: create a free account at tailscale.com
   and install the Tailscale app on the device they will open palaia from.
2. Have them open `http://<address>:8420/` — the server's public address. If
   it does not load yet, wait a minute and reload: the server is still
   installing.
3. They type the setup code, click **Connect with Tailscale**, and log in with
   their Tailscale account.
4. The page says "Done", shows palaia's private address, then closes itself.

**For technical people only — a key instead of the page.** At
`https://login.tailscale.com/admin/settings/keys` → **Generate auth key**:
type "palaia" as the description, leave **Reusable** and **Ephemeral** off,
and pick an **auth key** (it starts with `tskey-auth-`), not an **access
token** (`tskey-api-`). Then use it instead of the code — in the setup file,
`TAILSCALE_AUTH_KEY="tskey-REPLACE_ME"`; for the installer:

```
curl -fsSL https://get.palaia.ai | PALAIA_TSKEY=<their-key> sh
```

## Step 5 — Confirm it worked, then the next step

palaia answers in a browser on the private network, on port `8420`, at the
address the setup page showed (also in the installer's last line). It is also
listed as a machine named `palaia-hub` in their Tailscale admin page. The
device they open it from needs the Tailscale app switched on.

If it answers: give them that address and tell them the next step is opening it
and connecting their first AI tool. If you used the password path (Step 3b),
delete the saved password now, as that step says. If it does not, go to Step 6.

## Step 6 — When it does not come up

Name the likely cause in plain words; never paste raw error output at them.

**The setup page:**

- **It does not open at all after five minutes** — the provider may have a
  firewall in front of the server. Ask them to allow port 8420 there for now
  (Hetzner: "Firewalls" in the project), or use the key path instead.
- **"That code is not right."** — a typo; letters and digits only, dashes and
  case do not matter.
- **It closed before they finished** — it gives up after 30 minutes. Run the
  installer line again (setup file: `sudo bash /opt/palaia/cloud-init-setup.sh`
  on the server) for a fresh page.

**The installer** prints its own errors, each starting `palaia: ERROR:`
and saying what to do. Translate it:

- The setup page closed without joining — run the line again.
- The key was an access token, expired, or already used — get a fresh
  **auth key** and run the line again.
- It joined the private network but got no address yet — wait a moment and run
  the line again.
- It could not download palaia's image — check "Which image this release
  uses"; for a test release the line needs `PALAIA_CHANNEL=beta`.

**When the login fails** (Step 3a or 3b), translate its error line:

- **"REMOTE HOST IDENTIFICATION HAS CHANGED"** — a different machine answers
  at that address than this computer met before; expected after they reset or
  reinstalled the server. Only if they confirm they did, run the line below
  and try again; otherwise stop and tell them plainly.

```
ssh-keygen -R <address>
```

- **"Permission denied"** — wrong password or user name: rerun the 3b line.
- **"Password change required" / "Your password has expired"** — the provider
  wants a new password at first login (Hetzner does this without a key). Have
  them run the line below, type the password they were sent, choose a new one
  twice, type exit — then rerun the 3b line with the new password.

```bash
ssh -o StrictHostKeyChecking=accept-new root@<address>
```

- **"Connection timed out" / "No route to host"** — wrong address or the
  server is off; have them check both on the provider's website.

**The setup file** writes everything it did to
`/var/log/cloud-init-output.log` on the server; its own lines start with
`palaia cloud-init:`. To read it they (or you) log in over SSH or the
provider's console and run `sudo tail -n 50 /var/log/cloud-init-output.log`:

- **`ERROR: edit this file's PALAIA_SETUP_CODE (or TAILSCALE_AUTH_KEY)`** —
  the code was never filled in. The server exists now: finish with Step 3.
- **It stops after `pulling`, with a download error** — almost always a passing
  network hiccup. Re-run `sudo bash /opt/palaia/cloud-init-setup.sh`, which is
  safe to repeat. If someone edited the image line, put the original back.
- **The last line starts `done. Open`, yet the page does not open** — the
  device must be on the same Tailscale network with the app on. Right after a
  restart, a minute or two of "connection refused" is normal (the "Reboots"
  note in `v3/deploy/README.md`). If it still refuses after five minutes,
  read `sudo docker logs --tail 50 palaia-hub` and translate it.

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
