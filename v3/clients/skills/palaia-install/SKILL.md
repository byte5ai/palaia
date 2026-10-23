---
name: palaia-install
description: Set up palaia for someone from scratch, as a guided conversation, when they ask you to install it, get it running, or help them host it — on a rented cloud server (VPS), a home NAS box, a Raspberry Pi, or their own computer. Use this the moment someone wants palaia running and does not already have it; ask them where it should live and walk them through it one step at a time, running the commands for them when you can and handing them a single command to paste when you cannot. Do not use it for connecting an AI tool to an already-running palaia, or for changing an existing install.
license: MIT
---

# Get palaia running

You are setting palaia up for someone who may not be technical. Ask a few plain
questions, then do the work: run the commands yourself if you can reach their
machine, otherwise give them exactly one line to paste. One step at a time; wait
for each to finish before the next. Never paste raw error output at them.

palaia runs on a machine they own and is used in a browser. It is almost always a
separate always-on box (a rented server, a NAS, a small Pi): a hub that only
serves the laptop it lives on gives up the point of it.

## Before you start — read the real files

The setup file and the installer change between releases, so never write them
from memory, and never from this page alone. Read them from what palaia ships:

| What | File | Address |
|---|---|---|
| The setup file pasted in when a server is created | `v3/deploy/cloud-init.yaml` | `https://get.palaia.ai/cloud-init` |
| The installer for a server that already exists | `v3/deploy/get-palaia.sh` | `https://get.palaia.ai/install` |
| Notes on reboots, updates and backups | `v3/deploy/README.md` | `https://get.palaia.ai/deploy-notes` |
| Which release this is | `v3/VERSION` | `https://get.palaia.ai/version` |

Inside a copy of the palaia repository, read the files there; otherwise open
each address. Read all four from the same place. These are the only addresses to
use or show. If you cannot open files or web pages, say so; do not make
commands up. The installer and the setup file choose the right palaia image for
their release themselves: never add or change an image name.

## Step 1 — Where should palaia live?

Ask this first, in plain words:

- **A rented cloud server (VPS)** — Hetzner, DigitalOcean, Netcup and similar.
  The most common answer. Go to Step 2.
- **A home NAS** — Synology, Umbrel, TrueNAS, CasaOS: palaia's listing in its app
  store; skip the rest of this skill.
- **A Raspberry Pi** — the ready-made palaia image attached to the latest release
  and its flashing guide; skip the rest.
- **Their own computer** — fine for a quick try. Linux: treat it like an existing
  server (Step 3). Mac or Windows: Docker Desktop and the first command under
  "Quick start" in `v3/deploy/README.md`.

## Step 2 — How will they use it? Then: does the server exist?

Explain the usual setup and recommend it: **cloud access**. ChatGPT and Claude
(the app on their Mac or phone, and claude.ai) connect from the internet, so
palaia offers them one public HTTPS address for the AI connection only, where
each app has to sign in. The dashboard — palaia's settings and their memories —
stays on their private network (Tailscale) and is never public. The other choice
is **private only**: just tools on their own devices (Claude Desktop, Claude
Code, Codex). Remember their answer and their chosen AI app for every later step;
the Claude app is not Claude Code.

Then ask whether the server exists already or is about to be created:

- **Not yet created** — the easiest path: a setup file pasted into one field when
  creating the server. No commands. Go to Step 2a.
- **Already created** — Step 3. If it is still empty and they cannot give you a
  way in, recreating it with the setup file (Step 2a) avoids the provider's
  console; offer that.

**The setup code.** The setup page (Step 4) opens only with a one-time code. Make
one up: 12 capital letters and digits without 0, O, 1 or I, in three groups like
`K7QM-R2XD-9FTP`. Tell them; it is not a password and stops working once setup
is done.

### Step 2a — Not yet created: the setup file

1. Take `v3/deploy/cloud-init.yaml` exactly as it is and change one line:
   `PALAIA_SETUP_CODE="setup-code-REPLACE_ME"` becomes
   `PALAIA_SETUP_CODE="<code>"` with your code — the text appears twice (the
   explanation at the top and where it is set); change both.
2. Check: the first line is still `#cloud-config`, nothing else changed.
3. Give them the whole file as one block. They paste it into the field their
   provider shows when creating a server (Hetzner: "Cloud config", others:
   "User data"), then create it.
4. Ask for the server's address once it shows. Go to Step 4.

## Step 3 — An existing server: set it up remotely

Ask in one go: the server's address, and how they log in — a key already on this
computer, or a password the provider showed or emailed. Never ask for a password
in the chat: what is written there stays in the conversation. A server that
already runs Docker or is already on their Tailscale network is fine; the
installer keeps both.

The installer line is the first one in `v3/deploy/get-palaia.sh`:

```
curl -fsSL https://get.palaia.ai | sh
```

Run it with your setup code, so you know it:

```
curl -fsSL https://get.palaia.ai | PALAIA_SETUP_CODE=<code> sh
```

For **private only** (Step 2), add `PALAIA_CLOUD=0` before `sh`. The installer
sets up Docker and Tailscale if missing, then opens the setup page and waits up
to 30 minutes for them. Start it so it keeps running after your command returns
(your tool's background mode, for example), keep reading its output, and go to
Step 4. It ends with a line starting `done ✓  Open` and palaia's address.

The logins below use root, which most providers set up; use their user name if
the provider gave another. "Run the installer line through it" means: put the
line, in single quotes, in place of the final word true.

**3a — With a key.** No output means you are in; then run the installer line:

```
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 root@<address> true
```

**3b — With a password, and you can run commands on their computer** (a Run
button, or a terminal next to the chat). The password goes into a private file on
their computer, never through the chat. Show this line and say: "Click Run (or
paste it into the terminal), type your server password and press Enter. You see a
star for each character." Wait until it printed "Saved".

```bash
mkdir -p ~/.palaia-setup && chmod 700 ~/.palaia-setup && bash -c 'del=$(printf "\177"); s=; printf "Server password: "; while IFS= read -rsn1 c; do if [ -z "$c" ]; then break; elif [ "$c" = "$del" ]; then [ -n "$s" ] && s=${s%?} && printf "\b \b"; else s=$s$c; printf "*"; fi; done; echo; (umask 077; printf "%s\n" "$s" > ~/.palaia-setup/pw); echo "Saved (${#s} characters)."'
```

Then create the helper that hands it to the login (it holds no secret), check you
get in, and run the installer line through the second command:

```
printf '#!/bin/sh\ncat "$HOME/.palaia-setup/pw"\n' > ~/.palaia-setup/askpass && chmod 700 ~/.palaia-setup/askpass
SSH_ASKPASS="$HOME/.palaia-setup/askpass" SSH_ASKPASS_REQUIRE=force ssh -o StrictHostKeyChecking=accept-new -o PreferredAuthentications=password,keyboard-interactive -o NumberOfPasswordPrompts=1 -o ConnectTimeout=15 root@<address> true
```

When done, or if they stop halfway, delete the saved password for good:

```
rm -rf ~/.palaia-setup
```

**3c — You cannot run commands for them** (no Run button, no terminal). For an
empty server, offer recreating it with the setup file (Step 2a). Otherwise give
them the plain installer line to paste into their provider's web console (most
have a "Console" button). The screen then shows the address to open and a setup
code. Go to Step 4.

## Step 4 — The setup page: private network and cloud access

palaia joins the person's own private network (Tailscale), reachable only from
their devices. The setup page does that in the browser, with no key to copy.

1. If they do not use Tailscale yet: a free account at tailscale.com, and the
   Tailscale app on the device they will open palaia from.
2. They open `http://<address>:8420/` (the server's public address). Not there
   yet? Wait a minute and reload; the server is still installing.
3. They type the setup code, click **Connect with Tailscale** and log in.
4. **Cloud access.** For the cloud setup the page continues by itself. If it says
   **Let ChatGPT and Claude reach palaia**, their Tailscale network must allow
   it once: **Allow in Tailscale**, confirm, come back. **Keep it private** skips
   it. Explain before they choose; it can be turned on later.
5. The page says "Done", shows palaia's private address and closes.

A server already on their Tailscale network shows no page. For the cloud setup
the installer prints a `login.tailscale.com` link instead when the network still
has to allow it: give them that link, same explanation, and wait.

**For technical people only — a key instead of the page.** At
`https://login.tailscale.com/admin/settings/keys` → **Generate auth key**:
description "palaia", **Reusable** and **Ephemeral** off; an **auth key** (starts
with `tskey-auth-`), not an access token (`tskey-api-`). The key never goes
through the chat or into a command line. With a terminal on their computer, have
them run this line; it shows a star per character and checks the start:

```bash
mkdir -p ~/.palaia-setup && chmod 700 ~/.palaia-setup && bash -c 'del=$(printf "\177"); s=; printf "Tailscale auth key: "; while IFS= read -rsn1 c; do if [ -z "$c" ]; then break; elif [ "$c" = "$del" ]; then [ -n "$s" ] && s=${s%?} && printf "\b \b"; else s=$s$c; printf "*"; fi; done; echo; case $s in tskey-auth-*) (umask 077; printf "%s" "$s" > ~/.palaia-setup/tskey); echo "Saved (${#s} characters).";; *) echo "That is not an auth key (it starts with tskey-auth-). Nothing was saved; run this line again.";; esac'
```

Copy it to the server through the login you checked (prefix it as in 3b for a
password), run the installer with the file — the installer deletes it there —
and delete the local copy:

```
ssh root@<address> 'umask 077; cat > /root/.palaia-tskey' < ~/.palaia-setup/tskey
curl -fsSL https://get.palaia.ai | PALAIA_TSKEY_FILE=/root/.palaia-tskey sh
rm -rf ~/.palaia-setup
```

The installer deletes that file whether it finishes or stops; to retry, copy
it again. No terminal on their computer: use the setup page instead. Never ask them to
paste a key into the chat. With the setup file, the key goes into its
`TAILSCALE_AUTH_KEY="tskey-REPLACE_ME"` line instead of the code.

## Step 5 — Finish setup in the browser

A running server is not a finished setup: say "palaia is running", never "done",
until an AI app has saved and found a note. They open palaia's address (the
installer's last line, port `8420`, Tailscale app on); its setup opens by itself
and resumes where it stands after a reload or restart. If you used 3b, delete the
saved password now. If you cannot see the page, ask what it shows; never read
palaia's code to guess. One step at a time, in this order:

1. **How you'll use palaia** — their choice from Step 2 ("With ChatGPT and
   Claude" is cloud access).
2. **Your first memory** — *Name* is required (lowercase, e.g. `work`). *What
   it's for* is optional: AI apps read it to pick the right memory, so ask them;
   never invent it, empty is fine. *More options* can stay as they are.
3. **Your account** — a username and a password of 12+ characters, typed by them
   in the page, never in the chat. Needed for cloud access; optional on a private
   hub (Skip).
4. **Cloud access** — filled in when the setup page turned on Funnel; otherwise
   run `sudo tailscale funnel --bg http://127.0.0.1:8422` on the server for them
   and use the `https://` address it shows. Before **Turn on cloud access** and
   **Restart palaia**, say that palaia restarts once and then asks them to sign
   in with the new account — expected, not a step back. All four checks must pass.
5. **Connect an AI app** — the app they chose. The Claude app, claude.ai and
   ChatGPT get the address and three clicks; Claude Desktop on a private hub the
   extension download; Claude Code and the others a command. "Connected" appears
   once palaia saw the first request.

Then have them ask the app to save one note and find it again. Only then say it
works, and say what you checked. A warning box on the page comes first: read it
in plain words and do what it says. If it does not answer at all, Step 6.

## Step 6 — When it does not come up

Name the likely cause in plain words.

**The setup page:**

- **Does not open after five minutes** — a provider firewall may block it. Ask
  them to allow port 8420 there for now (Hetzner: "Firewalls"), or use a key.
- **"That code is not right."** — a typo; dashes and case do not matter.
- **Closed before they finished** — it gives up after 30 minutes. Run the
  installer line again (setup file: `sudo sh /opt/palaia/cloud-init-setup.sh`)
  for a fresh page.

**The installer** prints its own errors, each starting `palaia: ERROR:` and
saying what to do. Translate:

- The setup page closed without joining — run the line again.
- The key was an access token, expired or already used — a fresh **auth key**,
  then the line again.
- Joined but no address yet — wait a moment, run the line again.
- `the hub did not become ready` — it shows palaia's last log lines; translate
  them. Running the line again is safe and keeps their data.
- Cloud access is off — palaia still works privately; running the line again
  retries it.

**When the login fails** (3a or 3b):

- **"REMOTE HOST IDENTIFICATION HAS CHANGED"** — another machine answers at that
  address than before; expected after they reset the server. Only if they
  confirm, run this, then try again:

```
ssh-keygen -R <address>
```

- **"Permission denied"** — wrong password or user name: rerun the 3b line.
- **"Password change required"** — the provider wants a new password first.
  They run this, type the old one, choose a new one twice, type exit, then rerun
  the 3b line:

```bash
ssh -o StrictHostKeyChecking=accept-new root@<address>
```

- **"Connection timed out" / "No route to host"** — wrong address, or the server
  is off.

**The setup file** logs to `/var/log/cloud-init-output.log` on the server, its
lines starting `palaia cloud-init:`. Read it over SSH or the provider's console
with `sudo tail -n 50 /var/log/cloud-init-output.log`:

- **`ERROR: edit this file's PALAIA_SETUP_CODE (or TAILSCALE_AUTH_KEY)`** — the
  code was never filled in; the server exists now: finish with Step 3.
- **A download error** — usually a network hiccup: rerun
  `sudo sh /opt/palaia/cloud-init-setup.sh`.
- **Ends with `done ✓  Open`, yet the page does not open** — the device must be
  on the same Tailscale network with the app on. Right after a restart a minute of
  "connection refused" is normal. Still refused after five minutes: read
  `sudo docker logs --tail 50 palaia-hub` and translate it.

## What not to do

- No Docker, compose or app-store jargon; never invent their provider or setup.
- Never write the setup file or the install line from memory.
- Use only what a Mac or Linux computer has, no helper tools of your own.

## Per-model notes

The line for your family wins; the unlabelled line is the default.

- Ask where it should live before anything else, every time.
- [anthropic] Run the command yourself when you can reach their machine; only
  hand over a line when you cannot.
- [openai] One question at a time, and wait for the result before the next — do
  not print the whole plan up front.
- [google] Keep each step to one action and confirm it worked before moving on.
