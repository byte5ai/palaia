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
- the copies embedded in ``get-palaia.sh`` and ``cloud-init.yaml`` are the
  same file, byte for byte (one source of truth).
"""

from __future__ import annotations

import os
import re
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
import yaml

DEPLOY_ROOT = Path(__file__).resolve().parents[3] / "deploy"
SETUP_PAGE = DEPLOY_ROOT / "setup-page.py"
LOGIN_URL = "https://login.tailscale.com/a/test0123456789"
CODE = "ABCD-EFGH-JKLM"

FAKE_TAILSCALE = textwrap.dedent(
    f"""\
    #!/bin/sh
    # Fake tailscale: `up` prints a login link and waits for the marker;
    # `ip -4` answers only once the marker exists.
    marker="$FAKE_TS_DIR/logged-in"
    case "$1" in
      up)
        printf '\\nTo authenticate, visit:\\n\\n\\t{LOGIN_URL}\\n\\n' >&2
        while [ ! -f "$marker" ]; do sleep 0.2; done
        echo Success. >&2
        exit 0 ;;
      ip)
        [ -f "$marker" ] && echo 100.64.0.7 && exit 0
        exit 1 ;;
    esac
    exit 0
    """
)


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


def test_timeout_exits_one_and_closes_the_port(fake_ts: Path) -> None:
    port = _free_port()
    proc = _start(fake_ts, port, timeout=2)
    _wait_for_port(port, proc)
    assert proc.wait(timeout=30) == 1
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0


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


def test_cloud_init_embeds_the_setup_page_verbatim() -> None:
    document = yaml.safe_load((DEPLOY_ROOT / "cloud-init.yaml").read_text(encoding="utf-8"))
    files = {entry["path"]: entry["content"] for entry in document["write_files"]}
    assert files.get("/opt/palaia/setup-page.py") == _source()
