"""SPEC-308 Phase-3 gate evidence: "install a tool once, every AI has it".

One curated-index entry, installed exactly once through the real
``/api/market/*`` REST flow (consent token included, deliverable #3's
"install without a consent POST is impossible" rule still enforced —
see :mod:`palaia_hub.market.install`) onto **two** gateway profiles at
once, then read back by **two differently-authenticated real clients**:

1. :func:`test_one_install_answers_on_two_differently_authenticated_clients`
   — the real ``claude`` CLI, over a real scripted OAuth 2.1 + PKCE code
   flow against the ``default`` profile (SPEC-209's own machinery,
   ``support/hub_server_oauth.py``'s pattern, reused here), *and* a
   scripted ``fastmcp.Client`` carrying a real SPEC-108 ``plt_`` token
   against the ``mobile`` profile — zero client-side tool configuration
   either way; the tool the marketplace install added is simply *there*.
   Needs the real ``claude`` CLI on PATH; skipped, not failed, otherwise.

2. :func:`test_the_install_is_visible_through_the_mcpb_stdio_proxy_without_bundle_changes`
   — the exact same install, read a third way: the real
   ``palaia-proxy.mjs`` (SPEC-306) over real stdio, with no proxy/bundle
   rebuild between the install and this read. Needs ``node`` on PATH;
   skipped, not failed, otherwise.

Both spawn a real hub subprocess (``support/hub_server_market.py`` — real
``VaultEngine``, real ``AuthorizationServer``, real ``build_production_app``
wiring exactly as ``palaia-hub serve`` runs it, real ``uvicorn`` socket) and
a real second FastMCP server as the marketplace's fixture upstream
(``tests/upstream/fixture_http_server.py``, SPEC-302's own fixture, reused
by path — the same cross-package-by-path convention
``tests/market/conftest.py`` already uses for the same file). The
curated-index entry the hub serves is a genuinely Ed25519-signed document
verified by the real :mod:`palaia_hub.market.curated` code path; see
``support/hub_server_market.py``'s module docstring for why a
freshly-generated, throwaway signing key is honest evidence for "a
curated-index entry installs" without needing palaia's real, non-public
index key.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

_CLAUDE = shutil.which("claude")
_NODE = shutil.which("node")

_HUB_SCRIPT = Path(__file__).parent / "support" / "hub_server_market.py"
_FIXTURE_UPSTREAM_SCRIPT = (
    Path(__file__).resolve().parent.parent / "upstream" / "fixture_http_server.py"
)
_PROXY_SCRIPT = (
    Path(__file__).resolve().parents[3] / "tools" / "build-mcpb" / "proxy" / "palaia-proxy.mjs"
)

_STARTUP_TIMEOUT = 20.0
_CLAUDE_TIMEOUT = 60.0

OWNER_USERNAME = "owner"
OWNER_PASSWORD = "a-long-enough-passphrase"  # noqa: S105 - test fixture
VERIFIER = "scripted-client-code-verifier-with-enough-entropy-x"
CALLBACK = "http://127.0.0.1:9999/callback"
ENTRY_ID = "acme.spec308-fixture"


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
    raise RuntimeError(f"process did not become healthy within {timeout}s: {last_error}")


def _wait_for_fixture_upstream(url: str, timeout: float = _STARTUP_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            httpx.post(url, timeout=1.0)
            return
        except httpx.HTTPError:
            time.sleep(0.1)
    raise RuntimeError(f"fixture upstream at {url} never became reachable within {timeout}s")


@dataclass
class MarketHub:
    """A live SPEC-308 hub subprocess (real OAuth + plt_ + marketplace)
    plus its real fixture-upstream subprocess — both torn down together."""

    port: int
    base_url: str
    entry_id: str
    profiles: tuple[str, ...]
    _hub_process: subprocess.Popen[bytes]
    _fixture_process: subprocess.Popen[bytes]

    def stop(self) -> None:
        for process in (self._hub_process, self._fixture_process):
            process.terminate()
        for process in (self._hub_process, self._fixture_process):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                process.kill()
                process.wait(timeout=5)


@pytest.fixture
def market_hub(tmp_path: Path) -> Iterator[MarketHub]:
    """Spawn the real fixture upstream, then the real SPEC-308 hub pointed
    at it — two gateway profiles (``default``, ``mobile``), both accepting
    OAuth *and* ``plt_`` tokens, over the one vault the curated entry's
    fixture upstream will be mounted into once a test installs it."""
    fixture_port = _free_port()
    fixture_process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(_FIXTURE_UPSTREAM_SCRIPT), "--port", str(fixture_port)]
    )
    fixture_url = f"http://127.0.0.1:{fixture_port}/"
    try:
        _wait_for_fixture_upstream(fixture_url)
    except Exception:
        fixture_process.terminate()
        fixture_process.wait(timeout=5)
        raise

    port = _free_port()
    home = tmp_path / "home"
    home.mkdir()
    log_path = tmp_path / "hub.log"
    args = [
        sys.executable,
        str(_HUB_SCRIPT),
        "--port",
        str(port),
        "--home",
        str(home),
        "--vault-dir",
        str(tmp_path / "vault"),
        "--username",
        OWNER_USERNAME,
        "--password",
        OWNER_PASSWORD,
        "--fixture-url",
        fixture_url,
        "--entry-id",
        ENTRY_ID,
        "--profiles",
        "default,mobile",
    ]
    with log_path.open("w") as log_file:
        hub_process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            args, stdout=log_file, stderr=subprocess.STDOUT
        )
    try:
        _wait_for_health(port)
    except Exception:
        hub_process.terminate()
        hub_process.wait(timeout=5)
        fixture_process.terminate()
        fixture_process.wait(timeout=5)
        raise

    hub = MarketHub(
        port=port,
        base_url=f"http://127.0.0.1:{port}",
        entry_id=ENTRY_ID,
        profiles=("default", "mobile"),
        _hub_process=hub_process,
        _fixture_process=fixture_process,
    )
    try:
        yield hub
    finally:
        hub.stop()


def _install_once(base_url: str, entry_id: str, profiles: list[str]) -> dict[str, object]:
    """The real, full REST install flow (deliverable #3): consent, then
    install onto every profile named — refused without a fresh, matching
    consent token (see :mod:`palaia_hub.market.install`'s ``ConsentStore``).
    """
    client = httpx.Client(base_url=base_url, timeout=15.0)

    # SPEC-303 deliverable #4's merged surface: the curated entry is
    # visible over the exact same `/api/market/search` a dashboard would
    # call — real fetch, real Ed25519 verification (see the hub script).
    search = client.get("/api/market/search", params={"source": "curated"})
    assert search.status_code == 200, search.text
    assert search.json()["stale"] is False, search.json()
    assert any(e["id"] == entry_id for e in search.json()["entries"]), search.json()

    consent = client.post(f"/api/market/entry/{entry_id}/consent")
    assert consent.status_code == 200, consent.text
    token = consent.json()["token"]

    install = client.post(
        f"/api/market/entry/{entry_id}/install",
        json={"consent_token": token, "profiles": profiles},
    )
    assert install.status_code == 200, install.text
    body = install.json()
    assert body["up"] is True, body
    assert sorted(body["profiles"]) == sorted(profiles), body
    return body  # type: ignore[return-value]


def _mint_plt_token(base_url: str, *, name: str, profile: str) -> str:
    """A real SPEC-108 per-client token, minted through the real
    ``POST /api/auth/tokens`` REST surface — no client-side tool config,
    the same credential shape any non-OAuth client (a phone app, a
    scripted integration) would carry."""
    client = httpx.Client(base_url=base_url, timeout=15.0)
    response = client.post(
        "/api/auth/tokens",
        json={
            "name": name,
            "profile": profile,
            "scopes": ["vault:work:read", "vault:work:write"],
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["token"])


def _tool_namespace(install_body: dict[str, object]) -> str:
    """The mount namespace an installed upstream's tools appear under
    (``palaia_hub.upstream.models.UpstreamConfig.mount_namespace``:
    ``namespace`` if set, else ``key`` with ``-`` turned into ``_``) —
    derived from the install response rather than hard-coded, so this
    test does not silently stop meaning anything if the key-derivation
    rule in :func:`palaia_hub.market.install._derive_upstream_key` ever
    changes shape."""
    return str(install_body["upstream_key"]).replace("-", "_")


# --------------------------------------------------- OAuth PKCE (SPEC-209)


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


def _get_real_access_token(base_url: str, profile: str) -> str:
    """A scripted OAuth 2.1 + PKCE code-flow client, over a real socket —
    identical protocol steps to
    ``test_spec209_client_matrix.py``'s ``_get_real_access_token``, kept as
    its own copy here (this repo's ``tests/e2e/`` house style: each e2e
    file is a standalone script, not a shared library — see this
    directory's other ``test_spec*`` files, none of which import from one
    another either)."""
    client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=10.0)

    response = client.get(f"/mcp/{profile}/")
    assert response.status_code == 401, response.text
    challenge = response.headers["www-authenticate"]
    metadata_url = challenge.split('resource_metadata="', 1)[1].split('"', 1)[0]

    resource_metadata = client.get(urlsplit(metadata_url).path).json()
    as_metadata = client.get("/.well-known/oauth-authorization-server").json()

    registered = client.post(
        urlsplit(as_metadata["registration_endpoint"]).path,
        json={"client_name": "spec-308-scripted", "redirect_uris": [CALLBACK]},
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


def _run_claude(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    assert _CLAUDE is not None
    return subprocess.run(
        [_CLAUDE, *args], cwd=cwd, capture_output=True, text=True, timeout=_CLAUDE_TIMEOUT
    )


def _claude_call_tool_text(server_name: str, full_tool: str, prompt: str, cwd: Path) -> str:
    result = _run_claude(
        ["-p", prompt, "--allowedTools", full_tool, "--output-format", "json"], cwd=cwd
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload.get("is_error") is False, payload
    return str(payload["result"])


# ------------------------------------------------------------------ tests


@pytest.mark.skipif(_CLAUDE is None, reason="claude CLI not on PATH")
def test_one_install_answers_on_two_differently_authenticated_clients(
    market_hub: MarketHub, tmp_path: Path
) -> None:
    """SPEC-308's exit criterion, literally: one marketplace install,
    reachable by two differently-authenticated real clients on two
    different profiles, with zero client-side tool configuration on
    either one."""
    install_body = _install_once(
        market_hub.base_url, market_hub.entry_id, ["default", "mobile"]
    )
    tool_name = f"{_tool_namespace(install_body)}_echo"

    # --- client 1: a scripted fastmcp.Client with a real plt_ token,
    # against the "mobile" profile. No tool config beyond the bearer
    # token — the tool is simply part of whatever this profile serves.
    from fastmcp import Client
    from fastmcp.client.auth import BearerAuth

    plt_token = _mint_plt_token(market_hub.base_url, name="mobile-app", profile="mobile")

    async def _call_via_plt_client() -> str:
        transport = f"{market_hub.base_url}/mcp/mobile/"
        async with Client(transport, auth=BearerAuth(plt_token)) as client:
            names = {tool.name for tool in await client.list_tools()}
            assert tool_name in names, names
            result = await client.call_tool(tool_name, {"text": "hello from the plt_ client"})
            return str(result.data)

    import anyio

    plt_reply = anyio.run(_call_via_plt_client)
    assert "hello from the plt_ client" in plt_reply

    # --- client 2: the real `claude` CLI, over a real OAuth 2.1 + PKCE
    # code flow, against the "default" profile (SPEC-209's own default,
    # zero-flag-shaped path: `claude mcp add --header ...`).
    access_token = _get_real_access_token(market_hub.base_url, "default")
    server_name = "palaia-spec308-e2e"
    work_dir = tmp_path / "claude-project"
    work_dir.mkdir()
    mcp_url = f"{market_hub.base_url}/mcp/default/"

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

        full_tool = f"mcp__{server_name}__{tool_name}"
        cli_reply = _claude_call_tool_text(
            server_name,
            full_tool,
            f"Call the {full_tool} tool with text='hello from claude CLI' and reply with "
            "ONLY the exact raw text the tool returned, nothing else.",
            work_dir,
        )
        assert "hello from claude CLI" in cli_reply
    finally:
        _run_claude(["mcp", "remove", server_name, "-s", "local"], cwd=work_dir)


@pytest.mark.skipif(_NODE is None, reason="node is not on PATH")
def test_the_install_is_visible_through_the_mcpb_stdio_proxy_without_bundle_changes(
    market_hub: MarketHub,
) -> None:
    """SPEC-308 deliverable #2: the same install, seen a third way — the
    real SPEC-306 ``palaia-proxy.mjs`` over real stdio, with no proxy or
    bundle rebuild in between. Proves the stdio path is not a separate,
    manually-curated tool list: it mirrors whatever the profile serves,
    live."""
    install_body = _install_once(
        market_hub.base_url, market_hub.entry_id, ["default", "mobile"]
    )
    tool_name = f"{_tool_namespace(install_body)}_echo"
    plt_token = _mint_plt_token(market_hub.base_url, name="proxy-client", profile="mobile")

    async def _call_via_proxy() -> str:
        from fastmcp import Client
        from fastmcp.client.transports import StdioTransport

        env = dict(os.environ)
        env["PALAIA_HUB_URL"] = f"{market_hub.base_url}/mcp/mobile/"
        env["PALAIA_TOKEN"] = plt_token
        env["PALAIA_LOG_LEVEL"] = "debug"
        transport = StdioTransport(command="node", args=[str(_PROXY_SCRIPT)], env=env)
        async with Client(transport) as client:
            names = {tool.name for tool in await client.list_tools()}
            assert tool_name in names, names
            result = await client.call_tool(tool_name, {"text": "hello through the stdio proxy"})
            return str(result.data)

    import anyio

    proxy_reply = anyio.run(_call_via_proxy)
    assert "hello through the stdio proxy" in proxy_reply
