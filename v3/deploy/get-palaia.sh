#!/usr/bin/env bash
# palaia v3 — universal one-command installer.
#
#   curl -fsSL https://get.palaia.ai | sh
#
# Works on any existing Linux VPS you can SSH into (Ubuntu/Debian tested). It
# installs Docker and Tailscale if missing, joins your tailnet, and starts the
# hub bound to the tailnet address only — never the public internet. cloud-init
# is only a create-time shortcut; this is the path when the server already
# exists (the common case).
#
# Without a key it opens a one-time setup page (http://<server>:8420/, code
# printed below or set with PALAIA_SETUP_CODE) where you join your tailnet in
# the browser. With a key: set PALAIA_TSKEY=tskey-auth-... and pipe to `sh`.
# LAN/local without Tailscale: set PALAIA_NO_TAILSCALE=1 (binds to 0.0.0.0).
set -euo pipefail

CHANNEL="${PALAIA_CHANNEL:-stable}"
IMAGE="${PALAIA_IMAGE:-ghcr.io/byte5ai/palaia-hub:${CHANNEL}}"
CONTAINER_NAME="${PALAIA_CONTAINER_NAME:-palaia-hub}"
PORT="${PALAIA_INSTALL_PORT:-8420}"
VOLUME="${PALAIA_VOLUME:-palaia_home}"
HOSTNAME_TS="${PALAIA_TS_HOSTNAME:-palaia-hub}"

log()  { echo "palaia: $*"; }
err()  { echo "palaia: ERROR: $*" >&2; }
die()  { err "$@"; exit 1; }

[ "$(id -u)" = "0" ] || SUDO="sudo"; SUDO="${SUDO:-}"

# --- Docker -----------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
    log "installing Docker ..."
    curl -fsSL https://get.docker.com | $SUDO sh
fi
$SUDO systemctl enable --now docker >/dev/null 2>&1 || true
docker info >/dev/null 2>&1 || die "Docker is installed but not reachable (daemon down, or no permission)."

# --- Tailscale (unless explicitly disabled) ---------------------------------
BIND_ADDR="0.0.0.0"
if [ "${PALAIA_NO_TAILSCALE:-0}" = "1" ]; then
    log "PALAIA_NO_TAILSCALE=1 — skipping Tailscale; the hub will bind to ${BIND_ADDR} (LAN only if you firewall it)."
else
    if ! command -v tailscale >/dev/null 2>&1; then
        log "installing Tailscale ..."
        curl -fsSL https://tailscale.com/install.sh | $SUDO sh
    fi
    $SUDO systemctl enable --now tailscaled >/dev/null 2>&1 || true

    TSKEY="${PALAIA_TSKEY:-}"
    if [ -n "$TSKEY" ]; then
        case "$TSKEY" in
            tskey-*) : ;;
            *) die "that does not look like an auth key (expected 'tskey-...'). You may have copied an *access token* instead — use 'Generate auth key'." ;;
        esac
        log "joining the tailnet ..."
        if ! $SUDO tailscale up --auth-key="$TSKEY" --hostname="$HOSTNAME_TS"; then
            die "Tailscale rejected the key. It is likely expired, already used (non-reusable), or an access token rather than an auth key. Generate a fresh auth key and re-run."
        fi
    elif $SUDO tailscale ip -4 >/dev/null 2>&1; then
        log "already on a tailnet, skipping the setup page."
    else
        # SPEC-605: no key given — a one-time setup page in the browser joins
        # the tailnet instead (code-protected, closes itself afterwards).
        if ! command -v python3 >/dev/null 2>&1; then
            log "installing python3 for the setup page ..."
            $SUDO apt-get install -y python3 >/dev/null 2>&1 || die "python3 is needed for the setup page. Install it, or pass PALAIA_TSKEY=tskey-... instead."
        fi
        $SUDO mkdir -p /opt/palaia
        $SUDO tee /opt/palaia/setup-page.py >/dev/null <<'PALAIA_SETUP_PAGE'
#!/usr/bin/env python3
# palaia v3 — one-time setup page (SPEC-605).
#
# Joins this server to the owner's Tailscale network without anyone handling
# a key: it starts `tailscale up` without an auth key, takes the login link
# Tailscale prints, and shows it on a small web page — but only to someone
# who enters the one-time setup code. The person opens
# http://<server-address>:8420/, types the code, clicks "Connect with
# Tailscale" and logs in. When the server has its private-network address,
# the page says where palaia will be, and this program exits 0.
#
# It exits 1 on timeout (default 30 minutes) or when Tailscale fails. Either
# way the port is closed again the moment it exits; the installer then starts
# the hub bound to the private-network address only, exactly as before.
#
# Standard library only — python3 is on every image that runs cloud-init.
# The code comes from the PALAIA_SETUP_CODE environment variable, not the
# command line, so it never shows up in a process list. Without one, a fresh
# code is made up and printed together with the address to open.
#
# This file is the single source: get-palaia.sh and cloud-init.yaml embed
# it verbatim (checked by server/tests/deploy/test_setup_page.py).

import argparse
import hmac
import html
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

LOGIN_URL_RE = re.compile(r"https://\S+")
WRONG_CODE_DELAY = 1.0
MAX_CLIENTS = 32  # concurrent connections; more are dropped, not queued
CLIENT_TIMEOUT = 10  # seconds a connection may take to send its request
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I look-alikes


def log(message):
    print(f"palaia setup page: {message}", flush=True)


def normalise(code):
    """Codes are compared without case, spaces or dashes."""
    return re.sub(r"[\s-]", "", code or "").upper()


def new_code():
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def public_address():
    """The address this server reaches the internet from — no packet is sent."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("1.1.1.1", 80))
            return sock.getsockname()[0]
    except OSError:
        return "<this server's address>"


def tailnet_ip():
    try:
        out = subprocess.run(
            ["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = out.stdout.strip().splitlines()[:1]
    return first[0] if out.returncode == 0 and first else None


class State:
    def __init__(self, code, port):
        self.code = normalise(code)
        self.port = port
        self.login_url = None
        self.ip = None
        self.failed = None
        self.proc = None
        self.lock = threading.Lock()

    def code_ok(self, given):
        return hmac.compare_digest(normalise(given).encode(), self.code.encode())


def run_tailscale(state, hostname):
    """`tailscale up` without a key prints a login link and waits for the login."""
    try:
        state.proc = proc = subprocess.Popen(
            ["tailscale", "up", f"--hostname={hostname}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:
        state.failed = f"could not start tailscale: {exc}"
        return
    for line in proc.stdout:
        match = LOGIN_URL_RE.search(line)
        if match and state.login_url is None:
            with state.lock:
                state.login_url = match.group(0)
            log("login link ready — waiting for the code on the setup page.")
    if proc.wait() != 0 and tailnet_ip() is None:
        state.failed = "tailscale up ended without joining (see the lines above)."


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>palaia setup</title>
<style>
body{{font:17px/1.5 system-ui,sans-serif;max-width:32rem;margin:3rem auto;padding:0 1rem;
color:#1d1d1f}}
h1{{font-size:1.5rem}}
input{{font:inherit;padding:.5rem;width:100%;box-sizing:border-box;letter-spacing:.1em}}
button,a.btn{{display:inline-block;font:inherit;margin-top:1rem;padding:.6rem 1.2rem;border:0;
border-radius:.5rem;background:#2457d6;color:#fff;text-decoration:none;cursor:pointer}}
.err{{color:#b3261e}} .muted{{color:#666}}
</style></head><body><h1>palaia setup</h1>{body}</body></html>"""


def code_form(error=""):
    hint = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return (
        "<p>Enter the setup code you were given.</p>"
        f"{hint}"
        '<form method="get" action="/connect"><input name="code" autocomplete="off" autofocus '
        'placeholder="XXXX-XXXX-XXXX"><button type="submit">Continue</button></form>'
    )


def connect_body(state, code):
    if state.ip:
        return done_body(state)
    if state.failed:
        return f'<p class="err">Something went wrong: {html.escape(state.failed)}</p>'
    if not state.login_url:
        return (
            "<p>Preparing the connection — this takes a few seconds.</p>"
            "<script>setTimeout(()=>location.reload(),3000)</script>"
        )
    status_url = "/status?code=" + html.escape(normalise(code))
    return (
        "<p>One last step: connect this server to your private network. "
        "Log in with the Tailscale account you use on your own devices.</p>"
        f'<a class="btn" href="{html.escape(state.login_url)}" target="_blank" '
        'rel="noopener">Connect with Tailscale</a>'
        '<p class="muted" id="wait">Waiting for you to log in…</p>'
        "<script>setInterval(async()=>{"
        f'const r=await fetch("{status_url}");const s=await r.json();'
        "if(s.joined)location.reload();},3000)</script>"
    )


def done_body(state):
    url = f"http://{state.ip}:{state.port}/"
    return (
        "<p><strong>Done.</strong> This server is now on your private network.</p>"
        f'<p>In a minute or two, palaia opens at <a href="{html.escape(url)}">'
        f"{html.escape(url)}</a> — from any device where the Tailscale app is on.</p>"
        '<p class="muted">This setup page closes itself now.</p>'
    )


class BoundedServer(ThreadingHTTPServer):
    """One thread per connection, but never more than MAX_CLIENTS at once."""

    daemon_threads = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.slots = threading.BoundedSemaphore(MAX_CLIENTS)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        timeout = CLIENT_TIMEOUT

        def log_message(self, *args):
            pass

        def send(self, status, body, ctype="text/html; charset=utf-8"):
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = urlparse(self.path)
            code = parse_qs(parsed.query).get("code", [""])[0]
            if parsed.path == "/":
                return self.send(200, PAGE.format(body=code_form()))
            if parsed.path not in ("/connect", "/status"):
                return self.send(404, PAGE.format(body="<p>Not found.</p>"))
            if not state.code_ok(code):
                time.sleep(WRONG_CODE_DELAY)
                if parsed.path == "/status":
                    return self.send(403, json.dumps({"joined": False}), "application/json")
                return self.send(403, PAGE.format(body=code_form("That code is not right.")))
            if parsed.path == "/status":
                return self.send(200, json.dumps({"joined": bool(state.ip)}), "application/json")
            return self.send(200, PAGE.format(body=connect_body(state, code)))

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8420, help="where this page listens")
    parser.add_argument("--hub-port", type=int, default=8420, help="where palaia will answer")
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--hostname", default="palaia-hub")
    parser.add_argument("--timeout", type=int, default=1800, help="seconds")
    parser.add_argument("--linger", type=int, default=30, help="seconds to show 'done'")
    args = parser.parse_args(argv)

    code = os.environ.get("PALAIA_SETUP_CODE", "").strip() or new_code()
    if len(normalise(code)) < 8:
        log("ERROR: PALAIA_SETUP_CODE is shorter than 8 characters.")
        return 2

    state = State(code, args.hub_port)
    if tailnet_ip():
        log("this server is already on a tailnet — nothing to set up.")
        return 0

    # A plain `kill` (SIGTERM) or a closed terminal (SIGHUP) must still run the
    # clean-up below, not leave the page or a pending login behind.
    def stop(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)

    server = BoundedServer((args.bind, args.port), make_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=run_tailscale, args=(state, args.hostname), daemon=True).start()
    print(
        "\n"
        "  ============================================================\n"
        f"   Open   http://{public_address()}:{args.port}/\n"
        f"   Code   {code}\n"
        "   Then click 'Connect with Tailscale' and log in.\n"
        "  ============================================================\n",
        flush=True,
    )

    deadline = time.monotonic() + args.timeout
    try:
        while time.monotonic() < deadline and not state.failed:
            ip = tailnet_ip()
            if ip:
                state.ip = ip
                log(f"joined the tailnet as {ip}.")
                time.sleep(args.linger)
                return 0
            time.sleep(2)
    finally:
        server.shutdown()
        server.server_close()
        if state.proc and state.proc.poll() is None:
            state.proc.terminate()
            try:
                state.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                state.proc.kill()
        if not state.ip:
            # Drop the pending login, so the link can no longer be used by
            # anyone to pull this server into their network.
            try:
                subprocess.run(
                    ["tailscale", "logout"], capture_output=True, timeout=30, check=False
                )
            except (OSError, subprocess.TimeoutExpired):
                log("could not reset the pending Tailscale login — run 'tailscale logout'.")
    log(f"ERROR: {state.failed or 'nobody completed the setup page in time'} — the page is closed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
PALAIA_SETUP_PAGE
        # Open the port for the page only if ufw is on and does not allow it
        # already — and remove only the rule this run added, also when the
        # run is interrupted.
        UFW_OPENED=0
        if command -v ufw >/dev/null 2>&1 && $SUDO ufw status 2>/dev/null | grep -q "Status: active" \
            && ! $SUDO ufw status 2>/dev/null | grep -q "^${PORT}/tcp .*ALLOW"; then
            $SUDO ufw allow "${PORT}/tcp" comment 'palaia setup page, temporary' >/dev/null && UFW_OPENED=1
        fi
        close_setup_port() {
            if [ "$UFW_OPENED" = "1" ]; then
                $SUDO ufw delete allow "${PORT}/tcp" >/dev/null 2>&1 || true
                UFW_OPENED=0
            fi
        }
        trap 'close_setup_port' EXIT
        trap 'close_setup_port; exit 130' INT TERM HUP
        log "starting the setup page (closes itself after 30 minutes) ..."
        # The code travels in the environment, never as a command argument.
        export PALAIA_SETUP_CODE="${PALAIA_SETUP_CODE:-}"
        SETUP_OK=1
        if [ -n "$SUDO" ]; then
            $SUDO --preserve-env=PALAIA_SETUP_CODE python3 /opt/palaia/setup-page.py \
                --port "$PORT" --hub-port "$PORT" --hostname "$HOSTNAME_TS" </dev/null || SETUP_OK=0
        else
            python3 /opt/palaia/setup-page.py \
                --port "$PORT" --hub-port "$PORT" --hostname "$HOSTNAME_TS" </dev/null || SETUP_OK=0
        fi
        close_setup_port
        trap - EXIT INT TERM HUP
        [ "$SETUP_OK" = "1" ] || die "the setup page closed without joining the tailnet. Re-run this command to get a new page and code."
    fi
    BIND_ADDR="$($SUDO tailscale ip -4 2>/dev/null | head -n1)"
    [ -n "$BIND_ADDR" ] || die "joined Tailscale but no IPv4 tailnet address yet — not starting the hub on an empty address. Re-run in a moment."
    log "tailnet address: ${BIND_ADDR}"

    # Firewall: hub port reachable on the tailnet only.
    if command -v ufw >/dev/null 2>&1; then
        $SUDO ufw allow OpenSSH >/dev/null 2>&1 || true
        $SUDO ufw allow in on tailscale0 to any port "${PORT}" proto tcp comment 'palaia hub, tailnet only' >/dev/null 2>&1 || true
        $SUDO ufw --force enable >/dev/null 2>&1 || true
        log "ufw: ${PORT}/tcp on tailscale0 only."
    fi
fi

# --- Image ------------------------------------------------------------------
log "pulling ${IMAGE} ..."
if ! docker pull "${IMAGE}"; then
    if [ "${CHANNEL}" = "stable" ]; then
        die "could not pull ${IMAGE}. During the release-candidate phase there is no ':stable' image yet — re-run with PALAIA_CHANNEL=beta."
    fi
    die "could not pull ${IMAGE}. Check the tag/registry and your network."
fi

# --- Container --------------------------------------------------------------
if docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    log "a container named '${CONTAINER_NAME}' exists — replacing it (your data in the '${VOLUME}' volume is untouched)."
    docker rm -f "${CONTAINER_NAME}" >/dev/null
fi

log "starting ${CONTAINER_NAME} on ${BIND_ADDR}:${PORT} ..."
docker run -d \
    --name "${CONTAINER_NAME}" \
    -p "${BIND_ADDR}:${PORT}:8420" \
    -v "${VOLUME}:/data" \
    --restart unless-stopped \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --read-only \
    --tmpfs /tmp \
    --tmpfs /run \
    "${IMAGE}" >/dev/null

# --- Healthcheck ------------------------------------------------------------
log "waiting for the hub to answer ..."
URL="http://${BIND_ADDR}:${PORT}/"
ok=0
for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null --max-time 2 "$URL" 2>/dev/null; then ok=1; break; fi
    sleep 1
done
echo ""
if [ "$ok" = "1" ]; then
    log "done ✓  Open ${URL} from any device on your tailnet."
else
    err "hub started but did not answer at ${URL} within 30s."
    err "Check logs: docker logs -f ${CONTAINER_NAME}"
    exit 1
fi
