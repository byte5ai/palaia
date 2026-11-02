"""SPEC-605: the one-time setup page that joins a server to the tailnet.

``v3/deploy/setup-page.py`` is run for real here, against a fake
``tailscale`` on ``PATH`` — no network, no real tailnet. The fake prints a
login link like ``tailscale up`` does without a key, and only reports an
address once the test "logs in" (creates a marker file). That proves the
promises the SPEC makes:

- without the right code, the login link is never served — not on the
  page, not in the status answer;
- with it, the page offers "Connect with Tailscale" with that link;
- once the server has its tailnet address the page says done and the
  program exits 0, so the installer can continue;
- on timeout it exits 1 and the port is closed;
- the copy embedded in ``get-palaia.sh`` is the same file, byte for byte
  (one source of truth; cloud-init.yaml runs that installer).
"""

from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

# Runs the real setup-page helper process: deselected on pull requests, run in v3-ci-batch.yml
# (the `integration` marker, v3/pyproject.toml).
pytestmark = pytest.mark.integration

DEPLOY_ROOT = Path(__file__).resolve().parents[3] / "deploy"
SETUP_PAGE = DEPLOY_ROOT / "setup-page.py"
LOGIN_URL = "https://login.tailscale.com/a/test0123456789"
CODE = "ABCD-EFGH-JKLM"

FAKE_TAILSCALE = textwrap.dedent(
    """\
    #!/bin/sh
    # Fake tailscale: `up` prints a login link and waits for the marker;
    # `ip -4` answers only once the marker exists. `status` reports MagicDNS
    # on only when the `magicdns` file exists (it holds the machine's name);
    # `serve` keeps its configuration in serve.json and logs every change.
    marker="$FAKE_TS_DIR/logged-in"
    name="$(cat "$FAKE_TS_DIR/magicdns" 2>/dev/null || echo palaia-hub.tail1234.ts.net)"
    case "$1" in
      up)
        printf '\\nTo authenticate, visit:\\n\\n\\t@LOGIN_URL@\\n\\n' >&2
        while [ ! -f "$marker" ]; do sleep 0.2; done
        echo Success. >&2
        exit 0 ;;
      ip)
        [ -f "$marker" ] && echo 100.64.0.7 && exit 0
        exit 1 ;;
      status)
        enabled=false
        [ -f "$FAKE_TS_DIR/magicdns" ] && enabled=true
        tailnet='{"Name": "t", "MagicDNSSuffix": "tail1234.ts.net", "MagicDNSEnabled": %s}'
        printf '{"Self": {"DNSName": "%s."}, "CurrentTailnet": '"$tailnet"'}\\n' \\
          "$name" "$enabled"
        exit 0 ;;
      serve)
        config="$FAKE_TS_DIR/serve.json"
        if [ "$2" = status ]; then
          if [ -f "$config" ]; then cat "$config"; else echo '{}'; fi
          exit 0
        fi
        echo "$*" >> "$FAKE_TS_DIR/serve-calls"
        if [ -f "$FAKE_TS_DIR/serve-fails" ]; then echo "error: serve config denied" >&2; exit 1; fi
        for arg in "$@"; do target="$arg"; done
        web='{"%s:80": {"Handlers": {"/": {"Proxy": "%s"}}}}'
        printf '{"TCP": {"80": {"HTTP": true}}, "Web": '"$web"'}\\n' "$name" "$target" > "$config"
        exit 0 ;;
      logout)
        touch "$FAKE_TS_DIR/logged-out"
        exit 0 ;;
    esac
    exit 0
    """
).replace("@LOGIN_URL@", LOGIN_URL)
MAGIC_NAME = "palaia-hub.tail1234.ts.net"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 - local test server
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


def _wait_for_port(port: int, proc: subprocess.Popen[str]) -> None:
    for _ in range(100):
        if proc.poll() is not None:
            raise AssertionError(
                f"setup page exited early: {proc.stdout.read() if proc.stdout else ''}"
            )
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise AssertionError("setup page never started listening")


@pytest.fixture
def fake_ts(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tailscale = bin_dir / "tailscale"
    tailscale.write_text(FAKE_TAILSCALE, encoding="utf-8")
    tailscale.chmod(0o755)
    return tmp_path


def _start(fake_ts: Path, port: int, timeout: int = 60, code: str = CODE) -> subprocess.Popen[str]:
    env = {
        **os.environ,
        "PATH": f"{fake_ts / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "FAKE_TS_DIR": str(fake_ts),
        "PALAIA_SETUP_CODE": code,
    }
    return subprocess.Popen(
        [
            sys.executable,
            str(SETUP_PAGE),
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            "--timeout",
            str(timeout),
            "--linger",
            "1",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


@pytest.fixture
def running(fake_ts: Path) -> Iterator[tuple[subprocess.Popen[str], int]]:
    port = _free_port()
    proc = _start(fake_ts, port)
    _wait_for_port(port, proc)
    yield proc, port
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=10)


def _connect_page(port: int, code: str) -> tuple[int, str]:
    # The login link appears a moment after start; the page says "preparing" until then.
    for _ in range(50):
        status, body = _get(f"http://127.0.0.1:{port}/connect?code={code}")
        if status != 200 or "Preparing" not in body:
            return status, body
        time.sleep(0.1)
    return status, body


def test_the_start_page_asks_for_the_code_and_never_shows_the_link(running) -> None:
    _, port = running
    status, body = _get(f"http://127.0.0.1:{port}/")
    assert status == 200
    assert "setup code" in body
    assert "tailscale.com/a/" not in body


def test_a_wrong_code_never_gets_the_link(running) -> None:
    _, port = running
    status, body = _connect_page(port, "WRONG-CODE-0000")
    assert status == 403
    assert "not right" in body
    assert "tailscale.com/a/" not in body
    status, body = _get(f"http://127.0.0.1:{port}/status?code=WRONG-CODE-0000")
    assert status == 403
    assert "tailscale.com/a/" not in body


def test_the_right_code_shows_connect_and_the_login_link(running) -> None:
    _, port = running
    # Case, spaces and dashes do not matter when typing the code.
    status, body = _connect_page(port, "abcdefghjklm")
    assert status == 200
    assert "Connect with Tailscale" in body
    assert LOGIN_URL in body


def test_after_login_it_reports_done_and_exits_zero(running, fake_ts: Path) -> None:
    proc, port = running
    _connect_page(port, CODE)
    (fake_ts / "logged-in").touch()
    for _ in range(50):
        status, body = _get(f"http://127.0.0.1:{port}/status?code={CODE}")
        if '"joined": true' in body:
            break
        time.sleep(0.2)
    assert status == 200 and '"joined": true' in body
    _, page = _get(f"http://127.0.0.1:{port}/connect?code={CODE}")
    assert "http://100.64.0.7:8420/" in page
    assert proc.wait(timeout=60) == 0


def _done_page(proc: subprocess.Popen[str], port: int, fake_ts: Path) -> str:
    _connect_page(port, CODE)
    (fake_ts / "logged-in").touch()
    for _ in range(50):
        _, body = _get(f"http://127.0.0.1:{port}/status?code={CODE}")
        if '"joined": true' in body:
            break
        time.sleep(0.2)
    _, page = _get(f"http://127.0.0.1:{port}/connect?code={CODE}")
    assert proc.wait(timeout=60) == 0
    return page


def _serve_calls(fake_ts: Path) -> list[str]:
    calls = fake_ts / "serve-calls"
    return calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []


def test_with_magicdns_done_names_palaia_without_a_port(running, fake_ts: Path) -> None:
    """#619/#620: the "Done" screen gives a name, and Tailscale forwards port 80
    of that name to the hub's loopback port — the first sign-in happens at the
    address shown here, so it must be the name, not the number."""
    proc, port = running
    (fake_ts / "magicdns").write_text(MAGIC_NAME, encoding="utf-8")
    page = _done_page(proc, port, fake_ts)
    assert 'href="http://palaia-hub/"' in page
    assert f"http://{MAGIC_NAME}/" in page
    assert "100.64.0.7" not in page
    assert _serve_calls(fake_ts) == ["serve --bg --yes --http=80 http://127.0.0.1:8420"]


def test_port_80_used_by_another_service_is_left_alone(running, fake_ts: Path) -> None:
    proc, port = running
    (fake_ts / "magicdns").write_text(MAGIC_NAME, encoding="utf-8")
    other = (
        '{"TCP": {"80": {"HTTP": true}}, "Web": {"'
        + MAGIC_NAME
        + ':80": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3000"}}}}}\n'
    )
    (fake_ts / "serve.json").write_text(other, encoding="utf-8")
    page = _done_page(proc, port, fake_ts)
    assert 'href="http://palaia-hub:8420/"' in page
    assert "already used by another service" in page
    assert _serve_calls(fake_ts) == []
    assert (fake_ts / "serve.json").read_text(encoding="utf-8") == other


def test_without_magicdns_done_gives_the_number_and_says_why(running, fake_ts: Path) -> None:
    proc, port = running
    page = _done_page(proc, port, fake_ts)
    assert 'href="http://100.64.0.7:8420/"' in page
    assert "MagicDNS turned off" in page
    assert _serve_calls(fake_ts) == []


def _address(fake_ts: Path) -> dict[str, str]:
    env = {
        **os.environ,
        "PATH": f"{fake_ts / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "FAKE_TS_DIR": str(fake_ts),
    }
    out = subprocess.run(
        [sys.executable, str(SETUP_PAGE), "address", "--target", "http://127.0.0.1:8420"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def test_the_address_command_sets_up_port_80_once(fake_ts: Path) -> None:
    """The installer asks again after the hub is up: same answer, no second change."""
    (fake_ts / "logged-in").touch()
    (fake_ts / "magicdns").write_text(MAGIC_NAME, encoding="utf-8")
    first = _address(fake_ts)
    assert first == {
        "address": "http://palaia-hub/",
        "full_address": f"http://{MAGIC_NAME}/",
        "address_note": "",
    }
    assert _address(fake_ts) == first
    assert len(_serve_calls(fake_ts)) == 1


def test_a_taken_name_gives_the_name_tailscale_chose(fake_ts: Path) -> None:
    (fake_ts / "logged-in").touch()
    (fake_ts / "magicdns").write_text("palaia-hub-1.tail1234.ts.net", encoding="utf-8")
    assert _address(fake_ts)["address"] == "http://palaia-hub-1/"


def test_a_refused_port_80_forward_keeps_the_port_and_says_so(fake_ts: Path) -> None:
    (fake_ts / "logged-in").touch()
    (fake_ts / "magicdns").write_text(MAGIC_NAME, encoding="utf-8")
    (fake_ts / "serve-fails").touch()
    answer = _address(fake_ts)
    assert answer["address"] == "http://palaia-hub:8420/"
    assert answer["full_address"] == f"http://{MAGIC_NAME}:8420/"
    assert "did not forward port 80" in answer["address_note"]
    assert "serve config denied" in answer["address_note"]


def test_timeout_exits_one_closes_the_port_and_drops_the_pending_login(fake_ts: Path) -> None:
    port = _free_port()
    proc = _start(fake_ts, port, timeout=2)
    _wait_for_port(port, proc)
    assert proc.wait(timeout=30) == 1
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0
    # The login link must not stay usable after the page is gone.
    assert (fake_ts / "logged-out").exists()


def test_a_plain_kill_still_cleans_up(fake_ts: Path) -> None:
    port = _free_port()
    proc = _start(fake_ts, port)
    _wait_for_port(port, proc)
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=30) != 0
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0
    assert (fake_ts / "logged-out").exists()
    # The fake `tailscale up` (waiting for a login) was stopped, not orphaned.
    leftover = subprocess.run(
        ["pgrep", "-f", f"{fake_ts}/bin/tailscale up"], capture_output=True, text=True, check=False
    )
    assert leftover.stdout.strip() == ""


def test_a_joined_server_is_not_logged_out(running, fake_ts: Path) -> None:
    proc, _ = running
    (fake_ts / "logged-in").touch()
    assert proc.wait(timeout=60) == 0
    assert not (fake_ts / "logged-out").exists()


def test_idle_connections_cannot_pile_up(running) -> None:
    """Connections that never send a request are capped and time out, so a
    flood of them cannot lock the owner out of the page."""
    _, port = running
    idle = [socket.create_connection(("127.0.0.1", port)) for _ in range(40)]
    try:
        time.sleep(0.5)
        # Over the cap: some of those were closed by the server right away.
        closed = 0
        for sock in idle:
            sock.settimeout(0.2)
            try:
                if sock.recv(1) == b"":
                    closed += 1
            except (TimeoutError, OSError):
                pass
        assert closed >= 1
    finally:
        for sock in idle:
            sock.close()
    # Once the idle ones are gone, the page answers again.
    status, _ = _get(f"http://127.0.0.1:{port}/")
    assert status == 200


def test_refuses_a_code_that_is_too_short(fake_ts: Path) -> None:
    proc = _start(fake_ts, _free_port(), code="short")
    assert proc.wait(timeout=10) == 2


def test_without_a_code_it_makes_one_up_and_prints_it(fake_ts: Path) -> None:
    port = _free_port()
    proc = _start(fake_ts, port, timeout=2, code="")
    out, _ = proc.communicate(timeout=30)
    match = re.search(r"Code\s+([A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4})", out)
    assert match, out
    assert not set(match.group(1).replace("-", "")) & set("01IO")
    assert f":{port}/" in out


def test_already_joined_server_skips_the_page(fake_ts: Path) -> None:
    (fake_ts / "logged-in").touch()
    proc = _start(fake_ts, _free_port())
    assert proc.wait(timeout=10) == 0


# --- one source of truth ------------------------------------------------------


def _source() -> str:
    return SETUP_PAGE.read_text(encoding="utf-8")


def test_get_palaia_embeds_the_setup_page_verbatim() -> None:
    script = (DEPLOY_ROOT / "get-palaia.sh").read_text(encoding="utf-8")
    match = re.search(r"<<'PALAIA_SETUP_PAGE'\n(.*?)^PALAIA_SETUP_PAGE$", script, re.S | re.M)
    assert match, "get-palaia.sh no longer embeds setup-page.py in a 'PALAIA_SETUP_PAGE' heredoc"
    assert match.group(1) == _source()


def _page_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("palaia_setup_page", SETUP_PAGE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_page_colours_are_the_design_tokens_of_the_same_name() -> None:
    """The page cannot load the dashboard's stylesheet (it runs before palaia
    exists), so it carries the token values; they must stay equal to
    ``v3/design/tokens.json`` (issue 570)."""
    import json

    tokens_file = DEPLOY_ROOT.parent / "design" / "tokens.json"
    tokens = {
        token["name"]: (token["value"]["light"], token["value"]["dark"])
        for token in json.loads(tokens_file.read_text(encoding="utf-8"))["color"]["tokens"]
    }
    module = _page_module()
    page = module.PAGE.format(body="")
    for name, (light, dark) in module.COLORS.items():
        assert tokens.get(name) == (light, dark), name
        assert f"--{name}: {light};" in page
        assert f"--{name}: {dark};" in page
    assert "prefers-color-scheme: dark" in page
    # Inline styles and an inline mark only: the page fetches nothing.
    assert re.search(r'(src|href)="https?://', page) is None
    assert "@import" not in page and "url(" not in page


def test_a_waiting_page_reloads_when_the_phase_differs_from_the_one_it_shows() -> None:
    """The phase can change between rendering and the first poll (the login
    link arrives a moment later): the page must compare with what it shows,
    not with the first answer, or it keeps the old view until the timeout."""
    module = _page_module()
    script = module.poll_script("abcd-efgh-jkmn", "preparing")
    assert 'const p="preparing"' in script
    assert "if(s.phase!==p)location.reload()" in script
