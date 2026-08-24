"""SPEC-209 acceptance criterion: "Claude Code CLI: end-to-end against
Cloud-mode hub with OAuth (real)".

Everything here runs against a real ``mode: cloud`` + ``oauth.enabled: true``
hub (``support/hub_server_oauth.py`` — real ``VaultEngine``, real
``AuthorizationServer``, real ``uvicorn`` socket; the only thing this
sandbox cannot add is an actual public tunnel in front of it, which is a
network-reachability fact, not part of the OAuth code path a *local* CLI
client exercises) and the real ``claude`` CLI (2.1.241 at the time this was
written).

Three things, building on each other:

1. :func:`test_a_real_oauth_token_lets_claude_code_round_trip_write_search_read`
   — a scripted OAuth 2.1 code flow (real HTTP over a real socket, same
   shape as ``tests/oauth/test_flow_e2e.py``'s ``ScriptedClient`` but
   without the ASGI shortcut) obtains a real access token from the real
   authorization server; the real ``claude`` CLI is handed that token via
   ``--header`` and round-trips write → search → read against the
   OAuth-protected profile. Purely local — no outbound network beyond the
   loopback hub.

2. :func:`test_claude_mcp_get_reports_failed_to_connect_before_any_token_exists`
   documents byte5ai/palaia#232: ``claude mcp get``/``list`` runs a
   connectivity probe that fails a strict RFC 9728 ``resource``-field check
   palaia's canonical audience shape never satisfies, reporting a scary
   "Failed to connect" on a hub that is otherwise working fine. Also local.

3. :func:`test_claude_code_cli_native_oauth_login_needs_a_preregistered_redirect_uri`
   documents byte5ai/palaia#233, the actual blocker on the CLI's default,
   zero-flag login path: Claude Code's real, published Client ID Metadata
   Document registers a *portless* loopback ``redirect_uri``
   (``http://localhost/callback``); the CLI's real authorize request always
   carries an ephemeral port; palaia's redirect_uri matching is byte-exact
   with no RFC 8252 §7.3 loopback-port exemption, so the match can never
   succeed. It then proves the fix's absence is the *only* thing missing by
   completing a real login anyway, using the CLI's own documented escape
   hatch for authorization servers like this one (``--client-id`` pointing
   at a DCR client this test pre-registers with a literal, fixed-port
   redirect_uri, plus ``--callback-port`` naming that same port) — and
   round-tripping a real tool call on the resulting stored credential.
   Needs real outbound HTTPS to ``claude.ai`` (to fetch the real CIMD
   document) and ``FASTMCP_SSRF_TRUST_PROXY=1`` in an egress-proxied
   environment (see the hub fixture); skipped, not failed, when that
   network path is not available.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import select
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

_CLAUDE = shutil.which("claude")
pytestmark = pytest.mark.skipif(_CLAUDE is None, reason="claude CLI not on PATH")

_SCRIPT = Path(__file__).parent / "support" / "hub_server_oauth.py"
_STARTUP_TIMEOUT = 20.0
_CLAUDE_TIMEOUT = 60.0
_LOGIN_TIMEOUT = 20.0

OWNER_USERNAME = "owner"
OWNER_PASSWORD = "a-long-enough-passphrase"  # noqa: S105 - test fixture
VERIFIER = "scripted-client-code-verifier-with-enough-entropy-x"
CALLBACK = "http://127.0.0.1:9999/callback"
#: Claude Code's own real, published CIMD document (byte5ai/palaia#233).
CLAUDE_CODE_CIMD_URL = "https://claude.ai/oauth/claude-code-client-metadata"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(port: int, timeout: float = _STARTUP_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=0.5
            ) as resp:
                if resp.status == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"oauth hub did not become healthy within {timeout}s: {last_error}")


def _run_claude(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    assert _CLAUDE is not None
    return subprocess.run(
        [_CLAUDE, *args], cwd=cwd, capture_output=True, text=True, timeout=_CLAUDE_TIMEOUT
    )


def _claude_call_tool_text(server_name: str, tool: str, prompt: str, cwd: Path) -> str:
    full_tool = f"mcp__{server_name}__{tool}"
    result = _run_claude(
        ["-p", prompt, "--allowedTools", full_tool, "--output-format", "json"], cwd=cwd
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload.get("is_error") is False, payload
    return str(payload["result"])


def _challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _csrf_and_sign_in(client: httpx.Client, base_url: str) -> None:
    login_form = client.get(f"{base_url}/oauth/login")
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_form.text)
    assert match is not None, login_form.text
    signed_in = client.post(
        f"{base_url}/oauth/login",
        data={
            "username": OWNER_USERNAME,
            "password": OWNER_PASSWORD,
            "csrf_token": match.group(1),
            "next": "",
        },
    )
    assert signed_in.status_code == 303, signed_in.text
    assert "palaia_oauth_session" in client.cookies


def _get_real_access_token(base_url: str) -> str:
    """A scripted OAuth 2.1 + PKCE code-flow client, over a real socket.

    Same protocol steps as ``tests/oauth/test_flow_e2e.py``'s
    ``ScriptedClient``, but driven with a plain ``httpx.Client`` against a
    live TCP listener instead of ``httpx.ASGITransport`` — proof this is
    the real wire protocol, not the in-process shortcut.
    """
    client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=10.0)

    response = client.get("/mcp/default/")
    assert response.status_code == 401, response.text
    challenge = response.headers["www-authenticate"]
    metadata_url = challenge.split('resource_metadata="', 1)[1].split('"', 1)[0]

    resource_metadata = client.get(urlsplit(metadata_url).path).json()
    as_metadata = client.get("/.well-known/oauth-authorization-server").json()

    registered = client.post(
        urlsplit(as_metadata["registration_endpoint"]).path,
        json={"client_name": "spec-209-scripted", "redirect_uris": [CALLBACK]},
    )
    assert registered.status_code == 201, registered.text
    client_id = registered.json()["client_id"]

    _csrf_and_sign_in(client, "")

    authorized = client.get(
        urlsplit(as_metadata["authorization_endpoint"]).path,
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": CALLBACK,
            "code_challenge": _challenge_for(VERIFIER),
            "code_challenge_method": "S256",
            "state": "opaque-state",
            "resource": resource_metadata["resource"],
        },
    )
    assert authorized.status_code == 303, authorized.text
    code = parse_qs(urlsplit(authorized.headers["location"]).query)["code"][0]

    tokens = client.post(
        urlsplit(as_metadata["token_endpoint"]).path,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": CALLBACK,
            "code_verifier": VERIFIER,
        },
    )
    assert tokens.status_code == 200, tokens.text
    return str(tokens.json()["access_token"])


class _PtySession:
    """A subprocess with a real pty on stdio, readable/writable line by line.

    Needed because ``claude mcp login`` refuses to even attempt the flow
    ("stdin isn't a terminal") unless it believes it is talking to one.
    """

    def __init__(self, argv: list[str], *, cwd: Path) -> None:
        import pty

        self._master, slave = pty.openpty()
        self.process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            argv, stdin=slave, stdout=slave, stderr=slave, cwd=cwd, close_fds=True
        )
        os.close(slave)

    def read_until(self, pattern: re.Pattern[str], timeout: float) -> str:
        buf = b""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self._master], [], [], 1.0)
            if self._master in ready:
                try:
                    chunk = os.read(self._master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                if pattern.search(buf.decode(errors="replace")):
                    break
            if self.process.poll() is not None:
                break
        return buf.decode(errors="replace")

    def write_line(self, text: str) -> None:
        os.write(self._master, (text + "\n").encode())

    def close(self) -> None:
        try:
            os.close(self._master)
        except OSError:
            pass
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            self.process.kill()
            self.process.wait(timeout=5)


def _claude_ai_cimd_reachable() -> bool:
    """Can this environment fetch Claude Code's real CIMD document?

    Gates the network-dependent native-login test so an offline runner
    (has ``claude`` on PATH but no route to claude.ai) skips it instead of
    failing on a network condition unrelated to palaia's own code.
    """
    try:
        response = httpx.get(CLAUDE_CODE_CIMD_URL, timeout=10.0)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


@pytest.fixture
def oauth_hub(tmp_path: Path):  # noqa: ANN201 - yields a bare port int
    port = _free_port()
    home = tmp_path / "home"
    vault_dir = tmp_path / "vault"
    home.mkdir()
    log_path = tmp_path / "hub.log"
    args = [
        sys.executable,
        str(_SCRIPT),
        "--port",
        str(port),
        "--home",
        str(home),
        "--vault-dir",
        str(vault_dir),
        "--username",
        OWNER_USERNAME,
        "--password",
        OWNER_PASSWORD,
    ]
    env = dict(os.environ)
    # byte5ai/palaia#233's note: needed for the CIMD document fetch to
    # succeed at all in an environment where outbound HTTPS must go through
    # a configured proxy (this sandbox; plausibly some real deployments).
    # Harmless when unset/irrelevant — the local-only tests never fetch
    # anything external.
    env.setdefault("FASTMCP_SSRF_TRUST_PROXY", "1")
    with log_path.open("w") as log_file:
        process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            args, stdout=log_file, stderr=subprocess.STDOUT, env=env
        )
    try:
        _wait_for_health(port)
        yield port
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            process.kill()
            process.wait(timeout=5)


def test_a_real_oauth_token_lets_claude_code_round_trip_write_search_read(
    oauth_hub: int, tmp_path: Path
) -> None:
    port = oauth_hub
    base_url = f"http://127.0.0.1:{port}"
    access_token = _get_real_access_token(base_url)

    server_name = "palaia-spec209-e2e"
    work_dir = tmp_path / "claude-project"
    work_dir.mkdir()
    mcp_url = f"{base_url}/mcp/default/"

    add_result = _run_claude(
        [
            "mcp",
            "add",
            "--transport",
            "http",
            server_name,
            mcp_url,
            "--header",
            f"Authorization: Bearer {access_token}",
            "--scope",
            "local",
        ],
        cwd=work_dir,
    )
    assert add_result.returncode == 0, add_result.stderr

    try:
        get_result = _run_claude(["mcp", "get", server_name], cwd=work_dir)
        assert "Connected" in get_result.stdout, get_result.stdout

        write_reply = _claude_call_tool_text(
            server_name,
            "work_memory_write",
            "Call the mcp__palaia-spec209-e2e__work_memory_write tool with "
            "title='OAuth E2E' and body='real oauth token round trip' and then "
            "reply with ONLY the exact raw text the tool returned, nothing else.",
            work_dir,
        )
        assert "OAuth E2E" in write_reply

        search_reply = _claude_call_tool_text(
            server_name,
            "work_memory_search",
            "Call the mcp__palaia-spec209-e2e__work_memory_search tool with "
            "query='round trip' and then reply with ONLY the exact raw text the "
            "tool returned, nothing else.",
            work_dir,
        )
        assert "OAuth E2E" in search_reply

        read_reply = _claude_call_tool_text(
            server_name,
            "work_memory_read",
            "Call the mcp__palaia-spec209-e2e__work_memory_read tool with "
            "permalink='oauth-e2e' and then reply with ONLY the exact raw text "
            "the tool returned, nothing else.",
            work_dir,
        )
        assert "real oauth token round trip" in read_reply
    finally:
        _run_claude(["mcp", "remove", server_name, "-s", "local"], cwd=work_dir)


def test_claude_mcp_get_reports_failed_to_connect_before_any_token_exists(
    oauth_hub: int, tmp_path: Path
) -> None:
    """byte5ai/palaia#232: a real, but non-blocking, status-display bug."""
    port = oauth_hub
    server_name = "palaia-spec209-status"
    work_dir = tmp_path / "claude-project-status"
    work_dir.mkdir()
    mcp_url = f"http://127.0.0.1:{port}/mcp/default/"

    add_result = _run_claude(
        ["mcp", "add", "--transport", "http", server_name, mcp_url, "--scope", "local"],
        cwd=work_dir,
    )
    assert add_result.returncode == 0, add_result.stderr

    try:
        get_result = _run_claude(["mcp", "get", server_name], cwd=work_dir)
        assert "Failed to connect" in get_result.stdout, get_result.stdout
        assert "does not match expected" in get_result.stdout, get_result.stdout
        assert f"http://127.0.0.1:{port}/mcp/default/" in get_result.stdout, get_result.stdout
    finally:
        _run_claude(["mcp", "remove", server_name, "-s", "local"], cwd=work_dir)


def test_claude_code_cli_native_oauth_login_needs_a_preregistered_redirect_uri(
    oauth_hub: int, tmp_path: Path
) -> None:
    """byte5ai/palaia#233, in full: the default path fails, the documented
    CLI escape hatch for this class of authorization server completes it.
    """
    if not _claude_ai_cimd_reachable():
        pytest.skip("no outbound network path to claude.ai's real CIMD document")

    port = oauth_hub
    base_url = f"http://127.0.0.1:{port}"
    work_dir = tmp_path / "claude-project-login"
    work_dir.mkdir()
    mcp_url = f"{base_url}/mcp/default/"

    # --- part 1: the plain, zero-flag path Claude Code's default CIMD
    # client hits the missing loopback-port exemption on every attempt.
    server_name = "palaia-spec209-cimd"
    add_result = _run_claude(
        ["mcp", "add", "--transport", "http", server_name, mcp_url, "--scope", "local"],
        cwd=work_dir,
    )
    assert add_result.returncode == 0, add_result.stderr

    session = _PtySession([_CLAUDE, "mcp", "login", server_name, "--no-browser"], cwd=work_dir)  # type: ignore[list-item]
    try:
        url_re = re.compile(r"(http://127\.0\.0\.1:\d+/oauth/authorize\?[^\s\x1b\x07]+)")
        output = session.read_until(url_re, _LOGIN_TIMEOUT)
        match = url_re.search(output)
        assert match is not None, output
        authorize_url = match.group(1)

        client = httpx.Client(follow_redirects=False, timeout=15.0)
        _csrf_and_sign_in(client, base_url)
        authorize_response = client.get(authorize_url)
        assert authorize_response.status_code == 400, authorize_response.text
        assert "invalid_redirect_uri" in authorize_response.text
    finally:
        session.close()
        _run_claude(["mcp", "remove", server_name, "-s", "local"], cwd=work_dir)

    # --- part 2: the documented CLI escape hatch (--client-id +
    # --callback-port) for an authorization server whose exact-match has
    # no loopback exemption yet. A real DCR client, registered with a
    # literal, fixed-port redirect_uri the CLI can byte-match.
    callback_port = _free_port()
    dcr_client = httpx.Client(base_url=base_url, timeout=15.0)
    registered = dcr_client.post(
        "/oauth/register",
        json={
            "client_name": "spec-209-fixed-port",
            "redirect_uris": [f"http://localhost:{callback_port}/callback"],
        },
    )
    assert registered.status_code == 201, registered.text
    client_id = registered.json()["client_id"]

    workaround_name = "palaia-spec209-workaround"
    add_result = _run_claude(
        [
            "mcp",
            "add",
            "--transport",
            "http",
            workaround_name,
            mcp_url,
            "--client-id",
            client_id,
            "--callback-port",
            str(callback_port),
            "--scope",
            "local",
        ],
        cwd=work_dir,
    )
    assert add_result.returncode == 0, add_result.stderr

    session = _PtySession(
        [_CLAUDE, "mcp", "login", workaround_name, "--no-browser"],  # type: ignore[list-item]
        cwd=work_dir,
    )
    try:
        url_re = re.compile(r"(http://127\.0\.0\.1:\d+/oauth/authorize\?[^\s\x1b\x07]+)")
        output = session.read_until(url_re, _LOGIN_TIMEOUT)
        match = url_re.search(output)
        assert match is not None, output
        authorize_url = match.group(1)
        assert f"redirect_uri=http%3A%2F%2Flocalhost%3A{callback_port}" in authorize_url

        client = httpx.Client(follow_redirects=False, timeout=15.0)
        _csrf_and_sign_in(client, base_url)
        authorize_response = client.get(authorize_url)
        assert authorize_response.status_code == 303, authorize_response.text
        redirect_url = authorize_response.headers["location"]

        session.write_line(redirect_url)
        final_output = session.read_until(re.compile(r"Authenticated with|error"), _LOGIN_TIMEOUT)
        assert "Authenticated with" in final_output, final_output
        assert session.process.wait(timeout=10) == 0
    finally:
        session.close()

    try:
        get_result = _run_claude(["mcp", "get", workaround_name], cwd=work_dir)
        assert "Connected" in get_result.stdout, get_result.stdout

        write_reply = _claude_call_tool_text(
            workaround_name,
            "work_memory_write",
            "Call the mcp__palaia-spec209-workaround__work_memory_write tool with "
            "title='Native Login E2E' and body='completed via claude mcp login "
            "--no-browser' and then reply with ONLY the exact raw text the tool "
            "returned, nothing else.",
            work_dir,
        )
        assert "Native Login E2E" in write_reply
    finally:
        _run_claude(["mcp", "remove", workaround_name, "-s", "local"], cwd=work_dir)
