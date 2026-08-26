"""SPEC-407 Phase-4 gate evidence: "two agents on different providers hand
off work through palaia".

The scenario, literally: **session A** is the real ``claude`` CLI (OAuth,
profile ``default``) driven by a mechanical task prompt — register, save a
fact to memory, find the other session already working on the same thing
*through the directory* (never told its handle), hand it off with a
``memory://`` reference instead of pasting the fact into the message body.
**Session B** is a scripted ``fastmcp.Client`` carrying a real SPEC-108
``plt_`` token on the ``mobile`` profile — this sandbox has no ``codex``
binary, so a second-provider-shaped scripted client is the honest stand-in
here, the same substitution SPEC-209 already pinned at the wire level for
"a client that is not the real claude CLI". B checks its own inbox, follows
A's ``memory://`` ref with ``recall``, and the test asserts B's *real,
literal* recall output contains A's exact fact — proving the handoff
carried knowledge, not just an envelope.

Both agents connect to the same real hub subprocess
(``support/hub_server_messenger.py`` — real ``VaultEngine``, real
``AuthorizationServer``, real ``build_production_app`` wiring exactly as
``palaia-hub serve`` runs it, real ``uvicorn`` socket), on two different
gateway profiles that both carry the one shared vault plus
``directory: true``/``messenger: true`` — the directory and the messenger
are each exactly one hub-wide store (see the hub script's docstring), so a
registration/send on ``default`` and a check/recall on ``mobile`` are
provably talking to the same live directory and the same live mailbox, not
two independent stand-ins.

**Discovery, not a hardcoded handle** (SPEC-407 deliverable #2): every
session directory handle is a fresh, random 16-character token
(:data:`palaia_hub.directory.store.HANDLE_CHARS`), minted only at
``directory_register`` time. Session B's handle is never passed to the
``claude`` CLI anywhere — not in its prompt, not in its ``--mcp-config``,
not in its environment. The only way session A's ``messenger_send`` call
can address B correctly is to have actually called ``directory_query``
against the live directory and read the handle back out of the result
(exactly the pattern ``tests/gateway/test_messenger_tools.py``'s
``test_two_real_client_sessions_exchange_request_and_reply`` already
established for two scripted clients — this test's news is that one side
is now a real model). A passing run is therefore proof of discovery by
construction, not merely evidence consistent with it.

Needs the real ``claude`` CLI on PATH; skipped, not failed, otherwise.
"""

from __future__ import annotations

import base64
import hashlib
import json
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

import anyio
import httpx
import pytest
from fastmcp import Client
from fastmcp.client.auth import BearerAuth

_CLAUDE = shutil.which("claude")

_HUB_SCRIPT = Path(__file__).parent / "support" / "hub_server_messenger.py"

_STARTUP_TIMEOUT = 20.0
_CLAUDE_TIMEOUT = 180.0

OWNER_USERNAME = "owner"
OWNER_PASSWORD = "a-long-enough-passphrase"  # noqa: S105 - test fixture
VERIFIER = "scripted-client-code-verifier-with-enough-entropy-x"
CALLBACK = "http://127.0.0.1:9999/callback"

#: What session B registers as, *before* session A's CLI process ever
#: starts — the live peer A has to find through the directory, exactly the
#: role ``messaging_harness.py``'s ``seed_peer_scope`` plays for the
#: SPEC-404 effectiveness probes, except this peer is a real, live,
#: scripted MCP client instead of a placeholder nobody talks back to.
B_SCOPE = "the Q3 billing rate-limiter incident"

#: The fact session A must save to memory and hand off a *reference* to,
#: never its full text, in the message body. Distinctive enough that it
#: cannot appear in B's recall output by any route except having actually
#: followed the ref into the vault A wrote it into.
HANDOFF_FACT = (
    "The billing retry batch is capped at 200 items because a larger batch "
    "trips the downstream rate limiter; raising it needs the request queue "
    "split first."
)

A_PROMPT = f"""You have a four-step task using the palaia MCP tools. Follow the steps \
in order, using each tool's real output as the input to the next step — never invent \
or guess a value.

Step 1: Call directory_register with scope="investigating {B_SCOPE}" and \
platform="claude-code". Keep the handle and session_secret it returns — you will \
need both for every later step.

Step 2: Call the memory write tool (the tool whose name ends in "_write") with \
title="billing retry batch cap" and body set to exactly this text, unchanged: \
"{HANDOFF_FACT}". Keep the permalink it returns.

Step 3: Call directory_query with scope_contains="{B_SCOPE}". This returns exactly \
one other session. Use its handle for step 4 — do not use any handle typed in this \
prompt, because none is; the only correct handle is the one that tool call returns.

Step 4: Call messenger_send with handle=<your own handle from step 1>, \
session_secret=<your own session_secret from step 1>, to=<the handle from step 3>, \
subject="billing retry cap handoff", message_type="handoff", \
body="see the reference for the capped-batch decision and why", \
refs=["memory://<the permalink from step 2>"].

When all four steps succeed, reply with exactly one line: \
DONE <your handle> <the handle from step 3> <the permalink from step 2>
"""


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
    raise RuntimeError(f"hub did not become healthy within {timeout}s: {last_error}")


@dataclass
class MessengerHub:
    """A live SPEC-407 hub subprocess: real OAuth + plt_, two profiles
    (``default``, ``mobile``), both carrying the same vault plus the
    directory and messenger tool families."""

    port: int
    base_url: str
    _process: subprocess.Popen[bytes]

    def stop(self) -> None:
        self._process.terminate()
        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            self._process.kill()
            self._process.wait(timeout=5)


@pytest.fixture
def messenger_hub(tmp_path: Path) -> Iterator[MessengerHub]:
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
        "--profiles",
        "default,mobile",
    ]
    with log_path.open("w") as log_file:
        process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            args, stdout=log_file, stderr=subprocess.STDOUT
        )
    try:
        _wait_for_health(port)
    except Exception:
        process.terminate()
        process.wait(timeout=5)
        raise

    hub = MessengerHub(port=port, base_url=f"http://127.0.0.1:{port}", _process=process)
    try:
        yield hub
    finally:
        hub.stop()


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


def _admin_client(base_url: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, timeout=15.0)
    _csrf_and_sign_in(client, base_url)
    client.headers["X-Palaia-CSRF"] = client.cookies["palaia_oauth_csrf"]
    return client


def _mint_plt_token(base_url: str, *, name: str, profile: str) -> str:
    """A real SPEC-108 per-client token for session B, over the real
    ``POST /api/auth/tokens`` REST surface — the credential shape any
    non-OAuth client (a phone app, a scripted integration, a different
    provider's agent runtime) carries instead of an OAuth token."""
    client = _admin_client(base_url)
    response = client.post(
        "/api/auth/tokens",
        json={
            "name": name,
            "profile": profile,
            "scopes": [
                "vault:work:read",
                "vault:work:write",
                "directory:read",
                "directory:write",
                "messenger:read",
                "messenger:send",
            ],
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["token"])


# --------------------------------------------------- OAuth PKCE (SPEC-209)


def _challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _get_real_access_token(base_url: str, profile: str) -> str:
    """A scripted OAuth 2.1 + PKCE code-flow client, over a real socket —
    identical protocol steps to ``test_spec209_client_matrix.py``'s and
    ``test_spec308_phase3_gate.py``'s own ``_get_real_access_token``, kept
    as its own copy here per this directory's house style: each
    ``tests/e2e/`` file is a standalone script. No ``scope`` is requested,
    so the authorization server issues this profile's full grantable set —
    including ``directory:*``/``messenger:*`` now that they are part of
    ``_profile_scopes`` (the scope-ceiling fix this SPEC's task named:
    before it, an OAuth client could never be granted those scopes at all,
    only a ``plt_`` token could)."""
    client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=10.0)

    response = client.get(f"/mcp/{profile}/")
    assert response.status_code == 401, response.text
    challenge = response.headers["www-authenticate"]
    metadata_url = challenge.split('resource_metadata="', 1)[1].split('"', 1)[0]

    resource_metadata = client.get(urlsplit(metadata_url).path).json()
    as_metadata = client.get("/.well-known/oauth-authorization-server").json()

    registered = client.post(
        urlsplit(as_metadata["registration_endpoint"]).path,
        json={"client_name": "spec-407-scripted", "redirect_uris": [CALLBACK]},
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


# ------------------------------------------------------------------ the test


@pytest.mark.skipif(_CLAUDE is None, reason="claude CLI not on PATH")
def test_two_agents_on_different_providers_hand_off_work_through_palaia(
    messenger_hub: MessengerHub, tmp_path: Path
) -> None:
    """SPEC-407's exit criterion, literally: session A (the real ``claude``
    CLI, OAuth, profile ``default``) registers, saves a fact to memory,
    discovers session B through the directory (never told its handle), and
    hands it off with a ``memory://`` reference. Session B (a scripted
    ``fastmcp.Client``, a real SPEC-108 ``plt_`` token, profile ``mobile``)
    checks its inbox and follows the reference — the assertion is on B's
    real recall output, not on A's transcript."""

    # --- B registers first: the live peer A has to find through the
    # directory, never told to A by name.
    plt_token = _mint_plt_token(messenger_hub.base_url, name="second-provider-b", profile="mobile")

    async def _register_b() -> tuple[str, str]:
        transport = f"{messenger_hub.base_url}/mcp/mobile/"
        async with Client(transport, auth=BearerAuth(plt_token)) as client:
            result = await client.call_tool(
                "directory_register",
                {
                    "scope": B_SCOPE,
                    "platform": "second-provider-shaped-client (scripted fastmcp.Client; "
                    "this sandbox has no codex binary — SPEC-209's own wire-level "
                    "equivalence pin applies here too)",
                    "agent_kind": "reviewer",
                },
            )
            assert not result.is_error, result.content
            session = result.structured_content["session"]
            return str(session["handle"]), str(result.structured_content["session_secret"])

    b_handle, b_secret = anyio.run(_register_b)

    # --- A: the real claude CLI, over a real OAuth 2.1 + PKCE code flow,
    # against the "default" profile. Never told b_handle anywhere.
    access_token = _get_real_access_token(messenger_hub.base_url, "default")
    work_dir = tmp_path / "claude-project"
    work_dir.mkdir()
    mcp_config = json.dumps(
        {
            "mcpServers": {
                "palaia": {
                    "type": "http",
                    "url": f"{messenger_hub.base_url}/mcp/default/",
                    "headers": {"Authorization": f"Bearer {access_token}"},
                }
            }
        }
    )

    completed = _run_claude(
        [
            "-p",
            A_PROMPT,
            "--mcp-config",
            mcp_config,
            "--strict-mcp-config",
            "--allowedTools",
            "mcp__palaia",
            "--output-format",
            "json",
        ],
        cwd=work_dir,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload.get("is_error") is False, payload

    # --- B checks its own inbox (its own handle/secret — never A's) and
    # should find exactly the handoff A just sent.
    async def _check_and_recall() -> tuple[list[dict[str, object]], str]:
        transport = f"{messenger_hub.base_url}/mcp/mobile/"
        async with Client(transport, auth=BearerAuth(plt_token)) as client:
            inbox = await client.call_tool(
                "messenger_check", {"handle": b_handle, "session_secret": b_secret}
            )
            assert not inbox.is_error, inbox.content
            envelopes = inbox.structured_content["envelopes"]
            assert envelopes, (
                "B's inbox was empty — A never sent (or never discovered B). "
                f"claude's reply was: {payload.get('result')!r}"
            )
            handoffs = [e for e in envelopes if e["type"] == "handoff"]
            assert handoffs, f"no handoff envelope arrived: {envelopes}"
            envelope = handoffs[0]
            assert envelope["to"] == b_handle
            refs = envelope["refs"]
            assert refs, f"handoff carried no memory:// ref: {envelope}"

            recalled = await client.call_tool("work_memory_recall", {"ref": refs[0]})
            assert not recalled.is_error, recalled.content
            return envelopes, str(recalled.structured_content)

    envelopes, recalled_repr = anyio.run(_check_and_recall)

    # The assertion that matters: B's real, literal recall output contains
    # A's exact fact — the handoff carried knowledge, not just an envelope.
    assert HANDOFF_FACT in recalled_repr, (
        f"B's recall output did not contain A's fact.\n"
        f"envelopes B received: {envelopes}\n"
        f"recall result: {recalled_repr}\n"
        f"claude's own reply: {payload.get('result')!r}"
    )
