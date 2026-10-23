#!/usr/bin/env python3
# palaia v3 — one-time setup page (SPEC-605).
#
# Joins this server to the owner's Tailscale network without anyone handling
# a key: it starts `tailscale up` without an auth key, takes the login link
# Tailscale prints, and shows it on a small web page — but only to someone
# who enters the one-time setup code. The person opens
# http://<server-address>:8420/, types the code, clicks "Connect with
# Tailscale" and logs in.
#
# Once the server is on the tailnet, the same page offers cloud access
# (--cloud-target): Tailscale Funnel then forwards palaia's cloud entry — the
# AI-connection endpoints only, never the dashboard — so ChatGPT and Claude
# can reach it over HTTPS. If the tailnet has not allowed Funnel yet, the page
# shows Tailscale's own "allow" link; "Keep it private" skips the step.
#
# Exit status: 0 once the server is on the tailnet (cloud access on or not),
# 1 on timeout (default 30 minutes) or when Tailscale fails. Either way the
# port is closed again the moment it exits; the installer then starts the hub
# bound to the private-network address only.
#
# `setup-page.py cloud --target URL` runs only the cloud step, without a page:
# it prints Tailscale's link if one is needed, waits, and ends with a line
# `cloud_url=https://...` (exit 0) or `cloud_url=` (exit 3: not set up);
# `--check-only` just reports.
#
# Standard library only — python3 is on every image that runs cloud-init.
# The code comes from the PALAIA_SETUP_CODE environment variable, not the
# command line, so it never shows up in a process list. Without one, a fresh
# code is made up and printed together with the address to open.
#
# This file is the single source: get-palaia.sh embeds it verbatim (checked
# by server/tests/deploy/test_setup_page.py).

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

LINK_RE = re.compile(r"https?://\S+")
WRONG_CODE_DELAY = 1.0
MAX_CLIENTS = 32  # concurrent connections; more are dropped, not queued
CLIENT_TIMEOUT = 10  # seconds a connection may take to send its request
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I look-alikes
FUNNEL_PORTS = (443, 8443, 10000)  # the only HTTPS ports Funnel offers


def log(message):
    # stderr: in `cloud` mode stdout carries only the result line.
    print(f"palaia setup page: {message}", file=sys.stderr, flush=True)


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


def tailscale_json(*args):
    try:
        out = subprocess.run(
            ["tailscale", *args, "--json"], capture_output=True, text=True, timeout=15, check=False
        )
        return json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else {}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {}


def tailnet_ip():
    try:
        out = subprocess.run(
            ["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = out.stdout.strip().splitlines()[:1]
    return first[0] if out.returncode == 0 and first else None


# --- cloud access (Tailscale Funnel) -------------------------------------------


def dns_name():
    """This machine's tailnet name, e.g. palaia-hub.tail1234.ts.net."""
    return str((tailscale_json("status").get("Self") or {}).get("DNSName") or "").rstrip(".")


def _proxies(web_entry):
    handlers = (web_entry or {}).get("Handlers") or {}
    return {str(h.get("Proxy") or "") for h in handlers.values() if isinstance(h, dict)}


def funnel_url(target):
    """The public https URL Funnel already serves `target` at, or None."""
    name = dns_name()
    config = tailscale_json("serve", "status")
    for port in FUNNEL_PORTS:
        key = f"{name}:{port}"
        on = (config.get("AllowFunnel") or {}).get(key)
        if name and on and _proxies((config.get("Web") or {}).get(key)) == {target}:
            return f"https://{name}" + ("" if port == 443 else f":{port}")
    return None


def free_funnel_port(target):
    """A Funnel port that is unused, or already serves `target`; None if all are taken.

    A port another service of this machine already uses is never touched.
    """
    name = dns_name()
    if not name:
        return None
    config = tailscale_json("serve", "status")
    for port in FUNNEL_PORTS:
        web = (config.get("Web") or {}).get(f"{name}:{port}")
        tcp = (config.get("TCP") or {}).get(str(port))
        if web is None and tcp is None:
            return port
        if web is not None and _proxies(web) == {target}:
            return port
    return None


class Cloud:
    """Turns on Funnel for `target` and remembers what happened."""

    def __init__(self, target):
        self.target = target
        self.link = None
        self.text = []
        self.url = None
        self.result = None  # "on", "skipped" or a reason it is off
        self.proc = None

    def run(self, wait):
        self.url = funnel_url(self.target)
        if self.url:
            self.result = "on"
            return
        port = free_funnel_port(self.target)
        if port is None:
            self.result = "this machine's Tailscale HTTPS ports are already in use"
            return
        cmd = ["tailscale", "funnel", "--bg", "--yes", f"--https={port}", self.target]
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
        except OSError as exc:
            self.result = f"could not start tailscale: {exc}"
            return
        timer = threading.Timer(wait, self.stop)
        timer.daemon = True
        timer.start()
        for line in self.proc.stdout:
            line = line.strip()
            match = LINK_RE.search(line)
            # Tailscale asks the owner to allow HTTPS or Funnel for the tailnet
            # with a login.tailscale.com/f/... link and waits; other links in
            # its output point at documentation.
            if match and "/f/" in match.group(0):
                self.link = match.group(0)
                log(f"Tailscale asks to allow cloud access: {self.link}")
            elif line:
                self.text.append(line)
        self.proc.wait()
        timer.cancel()
        if self.result == "skipped":
            return
        self.url = funnel_url(self.target)
        if self.url:
            self.result = "on"
        elif self.result is None:
            self.result = " ".join(self.text[-3:]) or "Tailscale did not turn on Funnel"

    def stop(self):
        if self.result is None:
            self.result = "nobody allowed cloud access in time"
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def skip(self):
        self.result = "skipped"
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


def cloud_main(args):
    cloud = Cloud(args.target)
    if args.check_only:
        cloud.url = funnel_url(args.target)
        cloud.result = "on" if cloud.url else "not set up"
    else:
        cloud.run(args.wait)
    if cloud.url:
        print(f"cloud_url={cloud.url}", flush=True)
        return 0
    log(f"cloud access is not set up: {cloud.result}.")
    print("cloud_url=", flush=True)
    return 3


# --- the page ------------------------------------------------------------------


class State:
    def __init__(self, code, port):
        self.code = normalise(code)
        self.port = port
        self.login_url = None
        self.ip = None
        self.failed = None
        self.proc = None
        self.cloud = None  # a Cloud while the cloud step runs
        self.finished = threading.Event()
        self.lock = threading.Lock()

    def code_ok(self, given):
        return hmac.compare_digest(normalise(given).encode(), self.code.encode())


def run_tailscale(state, hostname, login_server):
    """`tailscale up` without a key prints a login link and waits for the login."""
    cmd = ["tailscale", "up", f"--hostname={hostname}"]
    if login_server:
        cmd.append(f"--login-server={login_server}")
    try:
        state.proc = proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:
        state.failed = f"could not start tailscale: {exc}"
        return
    for line in proc.stdout:
        match = LINK_RE.search(line)
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
:root{{color-scheme:light dark;--bg:#f6f7f9;--card:#fff;--text:#16181d;--muted:#5d6470;
--line:#dfe2e7;--accent:#2457d6;--ok:#167a3e;--err:#b3261e}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111317;--card:#1a1d23;--text:#eceef2;
--muted:#a3a9b4;--line:#2c313a;--accent:#7aa2ff;--ok:#5fcf8b;--err:#ff8a80}}}}
body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 system-ui,sans-serif}}
main{{max-width:30rem;margin:8vh auto;padding:0 16px}}
.brand{{font-weight:650;letter-spacing:-.01em;margin-bottom:12px;color:var(--muted)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:24px}}
h1{{font-size:1.35rem;line-height:1.3;margin:0 0 8px}}
p{{margin:8px 0}}
.steps{{display:flex;gap:6px;margin:0 0 16px;font-size:.8rem;color:var(--muted)}}
.steps span{{padding:2px 8px;border:1px solid var(--line);border-radius:999px}}
.steps .on{{border-color:var(--accent);color:var(--accent)}}
input{{font:inherit;font-size:1.1rem;padding:10px 12px;width:100%;box-sizing:border-box;
letter-spacing:.12em;text-transform:uppercase;border:1px solid var(--line);border-radius:8px;
background:var(--bg);color:var(--text)}}
.row{{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:16px}}
button,a.btn{{display:inline-block;font:inherit;font-weight:600;padding:10px 16px;border:0;
border-radius:8px;background:var(--accent);color:#fff;text-decoration:none;cursor:pointer}}
button.ghost{{background:transparent;color:var(--muted);border:1px solid var(--line)}}
.err{{color:var(--err)}} .ok{{color:var(--ok)}} .muted{{color:var(--muted);font-size:.92rem}}
code{{font:.92rem ui-monospace,monospace}}
</style></head><body><main><div class="brand">palaia</div>
<div class="card">{body}</div></main></body></html>"""


def steps(active):
    names = ("Code", "Private network", "Cloud access", "Done")
    marks = (f'<span class="{"on" if i == active else ""}">{n}</span>' for i, n in enumerate(names))
    return '<div class="steps">' + "".join(marks) + "</div>"


def code_form(error=""):
    hint = f'<p class="err" role="alert">{html.escape(error)}</p>' if error else ""
    return (
        steps(0) + "<h1>Set up palaia</h1>"
        "<p>Enter the setup code you were given.</p>"
        f"{hint}"
        '<form method="get" action="/connect"><label class="muted" for="code">Setup code</label>'
        '<input id="code" name="code" autocomplete="off" autofocus required '
        'placeholder="XXXX-XXXX-XXXX"><div class="row"><button type="submit">Continue</button>'
        "</div></form>"
    )


def poll_script(code):
    status_url = "/status?code=" + html.escape(normalise(code))
    return (
        "<script>let p=null;setInterval(async()=>{try{"
        f'const r=await fetch("{status_url}");const s=await r.json();'
        "if(p!==null&&s.phase!==p)location.reload();p=s.phase;}catch(e){}},2500)</script>"
    )


def phase(state):
    if state.failed:
        return "failed"
    if not state.ip:
        return "join" if state.login_url else "preparing"
    if state.cloud is not None and state.cloud.result is None:
        return "cloud-link" if state.cloud.link else "cloud-check"
    return "done"


def connect_body(state, code):
    current = phase(state)
    safe_code = html.escape(normalise(code))
    if current == "failed":
        return steps(1) + f'<p class="err">Something went wrong: {html.escape(state.failed)}</p>'
    if current == "preparing":
        return (
            steps(1)
            + "<h1>Preparing the connection</h1><p>This takes a few seconds.</p>"
            + poll_script(code)
        )
    if current == "join":
        return (
            steps(1) + "<h1>Connect this server to your private network</h1>"
            "<p>Log in with the Tailscale account you use on your own devices. "
            "Your devices and this server then reach each other privately.</p>"
            f'<div class="row"><a class="btn" href="{html.escape(state.login_url)}" '
            'target="_blank" rel="noopener">Connect with Tailscale</a></div>'
            '<p class="muted">This page moves on by itself once you have logged in.</p>'
            + poll_script(code)
        )
    if current == "cloud-check":
        return (
            steps(2)
            + "<h1>Setting up cloud access</h1><p>This takes a few seconds.</p>"
            + poll_script(code)
        )
    if current == "cloud-link":
        return (
            steps(2) + "<h1>Let ChatGPT and Claude reach palaia</h1>"
            "<p>Cloud AI apps connect from the internet. Tailscale can forward "
            "<strong>only palaia's AI connection</strong> to this server over HTTPS; "
            "the dashboard stays on your private network. Each app still has to sign in.</p>"
            "<p>Your Tailscale network has not allowed this yet. Open the link, "
            "allow it, then come back.</p>"
            f'<div class="row"><a class="btn" href="{html.escape(state.cloud.link)}" '
            'target="_blank" rel="noopener">Allow in Tailscale</a>'
            f'<form method="post" action="/skip?code={safe_code}">'
            '<button class="ghost" type="submit">Keep it private</button></form></div>'
            '<p class="muted">You can turn cloud access on later.</p>' + poll_script(code)
        )
    return done_body(state)


def done_body(state):
    url = f"http://{state.ip}:{state.port}/"
    cloud = state.cloud
    if cloud is None:
        cloud_line = ""
    elif cloud.url:
        cloud_line = (
            '<p class="ok">Cloud access is ready at '
            f"<code>{html.escape(cloud.url)}</code> — you finish it in palaia.</p>"
        )
    elif cloud.result == "skipped":
        cloud_line = '<p class="muted">Cloud access is off. You can turn it on later.</p>'
    else:
        cloud_line = (
            f'<p class="muted">Cloud access is off ({html.escape(cloud.result or "")}). '
            "You can turn it on later.</p>"
        )
    return (
        steps(3) + "<h1>Done</h1><p>This server is now on your private network.</p>"
        f"{cloud_line}"
        f'<p>In a minute or two, palaia opens at <a href="{html.escape(url)}">'
        f"{html.escape(url)}</a> on any device with the Tailscale app turned on.</p>"
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

        def send(self, status, body, ctype="text/html; charset=utf-8", location=None):
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(data)

        def checked(self):
            parsed = urlparse(self.path)
            code = parse_qs(parsed.query).get("code", [""])[0]
            if state.code_ok(code):
                return parsed.path, code
            time.sleep(WRONG_CODE_DELAY)
            if parsed.path == "/status":
                self.send(403, json.dumps({"joined": False}), "application/json")
            else:
                self.send(403, PAGE.format(body=code_form("That code is not right.")))
            return None, None

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                return self.send(200, PAGE.format(body=code_form()))
            if path not in ("/connect", "/status"):
                return self.send(404, PAGE.format(body="<p>Not found.</p>"))
            path, code = self.checked()
            if path == "/status":
                answer = {"joined": bool(state.ip), "phase": phase(state)}
                return self.send(200, json.dumps(answer), "application/json")
            if path == "/connect":
                return self.send(200, PAGE.format(body=connect_body(state, code)))
            return None

        def do_POST(self):
            if urlparse(self.path).path != "/skip":
                return self.send(404, PAGE.format(body="<p>Not found.</p>"))
            path, code = self.checked()
            if path is None:
                return None
            if state.cloud is not None:
                state.cloud.skip()
            return self.send(303, "", location=f"/connect?code={normalise(code)}")

    return Handler


def page_main(args):
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
    threading.Thread(
        target=run_tailscale, args=(state, args.hostname, args.login_server), daemon=True
    ).start()
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
                if args.cloud_target:
                    state.cloud = Cloud(args.cloud_target)
                    state.cloud.run(max(1, int(deadline - time.monotonic())))
                    log(f"cloud access: {state.cloud.url or state.cloud.result}.")
                time.sleep(args.linger)
                return 0
            time.sleep(2)
    finally:
        server.shutdown()
        server.server_close()
        if state.cloud is not None and state.cloud.proc and state.cloud.proc.poll() is None:
            state.cloud.proc.terminate()
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


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["cloud"]:
        parser = argparse.ArgumentParser(description="Turn on cloud access (Tailscale Funnel).")
        parser.add_argument("--target", required=True, help="e.g. http://127.0.0.1:8422")
        parser.add_argument("--wait", type=int, default=600, help="seconds to wait for approval")
        parser.add_argument("--check-only", action="store_true", help="only report, change nothing")
        return cloud_main(parser.parse_args(argv[1:]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8420, help="where this page listens")
    parser.add_argument("--hub-port", type=int, default=8420, help="where palaia will answer")
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--hostname", default="palaia-hub")
    parser.add_argument("--login-server", default="", help="a self-hosted control server")
    parser.add_argument("--cloud-target", default="", help="offer cloud access for this URL")
    parser.add_argument("--timeout", type=int, default=1800, help="seconds")
    parser.add_argument("--linger", type=int, default=30, help="seconds to show 'done'")
    return page_main(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
