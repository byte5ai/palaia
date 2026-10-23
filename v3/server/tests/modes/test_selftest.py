"""The public-address self-test (issue #566).

Two kinds of test. Most stand in for the internet with an
``httpx.MockTransport`` so every failure the check must catch can be staged
exactly: an unrelated page that answers 200, a redirect, another hub's
sign-in address, a tunnel pointed at the dashboard, a dead backend.

One runs the *real* boundary: the hub app in Cloud mode behind a transport
that applies the cloud entry's own rule — the location regex read out of
``deploy/nginx.conf.template`` and the ``X-Palaia-Entry: cloud`` header it
sets — so the check is proven against what a tunnel actually reaches, not
against a mock of the forbidden admin route.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.modes.selftest import check_public_url
from palaia_hub.oauth import AuthorizationServer

ISSUER = "https://hub.example.test"
#: Where these tests pretend ISSUER's name leads: a public address. Nothing is
#: ever sent there — every transport below is a mock or in-process.
PUBLIC_ADDRESS = "93.184.215.14"
DASHBOARD_HTML = '<!doctype html><title>palaia</title><div id="root"></div>'
TEMPLATE = Path(__file__).resolve().parents[3] / "deploy" / "nginx.conf.template"


def _cloud_entry(path: str) -> httpx.Response | None:
    """What a correct cloud entry answers for paths it does not forward."""
    if re.match(r"^/(mcp|oauth|\.well-known|telegram/webhook)(/|$)", path):
        return None
    return httpx.Response(404, text="Not found. This address serves palaia's AI connection only.")


def _healthy(request: httpx.Request) -> httpx.Response:
    refused = _cloud_entry(request.url.path)
    if refused is not None:
        return refused
    if request.url.path == "/.well-known/oauth-authorization-server":
        return httpx.Response(
            200, json={"issuer": ISSUER, "token_endpoint": ISSUER + "/oauth/token"}
        )
    if request.url.path == "/mcp/default/":
        return httpx.Response(401, headers={"www-authenticate": 'Bearer resource_metadata="x"'})
    return httpx.Response(404)


async def _public(host: str, port: int) -> list[str]:
    return [PUBLIC_ADDRESS]


def _resolving_to(*addresses: str):  # type: ignore[no-untyped-def]
    async def resolve(host: str, port: int) -> list[str]:
        return list(addresses)

    return resolve


async def _run(handler: object, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs.setdefault("resolve", _public)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:  # type: ignore[arg-type]
        return await check_public_url(ISSUER, issuer=ISSUER, client=client, **kwargs)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_a_correct_cloud_setup_passes_every_check() -> None:
    result = await _run(_healthy)

    assert result.reachable is True, result
    assert [check.id for check in result.checks] == [
        "discovery",
        "mcp",
        "admin_private",
        "dashboard_private",
    ]
    assert all(check.passed for check in result.checks)
    assert result.error == ""
    assert result.status_code == 200
    assert result.latency_ms is not None


@pytest.mark.anyio
async def test_an_unrelated_page_that_answers_200_is_not_this_hub() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html="<html><body>Welcome to nginx!</body></html>")

    result = await _run(handler)

    assert result.reachable is False
    discovery = result.checks[0]
    assert discovery.id == "discovery" and discovery.passed is False
    assert "not with this hub's sign-in details" in discovery.detail


@pytest.mark.anyio
async def test_a_redirect_is_not_an_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://login.example.com/"})

    result = await _run(handler)

    assert result.reachable is False
    assert "redirects to https://login.example.com/" in result.error


@pytest.mark.anyio
async def test_another_hubs_sign_in_address_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json={"issuer": "https://other.example.test"})
        return _healthy(request)

    result = await _run(handler)

    assert result.reachable is False
    assert "https://other.example.test" in result.error


@pytest.mark.anyio
async def test_a_tunnel_pointed_at_the_dashboard_is_caught() -> None:
    """The tunnel forwards to port 8420 instead of the cloud entry: the AI
    connection works, and so does the admin API — which must not."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/info":
            return httpx.Response(200, json={"version": "3.0.0", "mode": "cloud"})
        if request.url.path == "/":
            return httpx.Response(200, html=DASHBOARD_HTML)
        return _healthy(request) if _cloud_entry(request.url.path) is None else httpx.Response(404)

    result = await _run(handler)

    assert result.reachable is False
    failed = {check.id for check in result.checks if not check.passed}
    assert failed == {"admin_private", "dashboard_private"}
    assert "port 8422" in result.error


@pytest.mark.anyio
async def test_open_mode_does_not_ask_for_a_private_dashboard() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(200, html=DASHBOARD_HTML)
        return _healthy(request)

    result = await _run(handler, mode="open")

    assert result.reachable is True
    assert [check.id for check in result.checks] == ["discovery", "mcp"]


@pytest.mark.anyio
async def test_a_dead_backend_behind_a_live_proxy_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="Bad Gateway")

    result = await _run(handler)

    assert result.reachable is False
    assert "HTTP 502" in result.error


@pytest.mark.anyio
async def test_nothing_listening_is_reported_once_with_the_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    result = await _run(handler)

    assert result.reachable is False
    assert len(result.checks) == 1
    assert "could not connect" in result.error


@pytest.mark.anyio
async def test_without_an_issuer_the_ai_connection_alone_is_checked() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_healthy)) as client:
        result = await check_public_url(ISSUER + "/", issuer=None, client=client, resolve=_public)

    assert result.reachable is True
    assert result.checked_url == ISSUER
    assert result.checks[0].id == "mcp"


# ------------------------------------- "stays private" means refused, nothing else


@pytest.mark.anyio
async def test_a_sign_in_prompt_and_a_redirect_do_not_count_as_private() -> None:
    """The AI connection works; the admin API asks for a sign-in and the
    dashboard redirects elsewhere — both reachable from the internet, so
    neither may be called private."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/info":
            return httpx.Response(401, json={"detail": "Please sign in"})
        if request.url.path == "/":
            return httpx.Response(302, headers={"location": "https://dash.example.test/"})
        return _healthy(request)

    result = await _run(handler)

    assert result.reachable is False
    failed = {check.id: check.detail for check in result.checks if not check.passed}
    assert set(failed) == {"admin_private", "dashboard_private"}
    assert "a sign-in prompt" in failed["admin_private"]
    assert "a redirect to https://dash.example.test/" in failed["dashboard_private"]


@pytest.mark.parametrize("status", [200, 500, 502])
@pytest.mark.anyio
async def test_any_other_answer_on_the_admin_side_does_not_count_as_private(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/api/info", "/"):
            return httpx.Response(status, text="something")
        return _healthy(request)

    result = await _run(handler)

    assert result.reachable is False
    assert {check.id for check in result.checks if not check.passed} == {
        "admin_private",
        "dashboard_private",
    }
    assert f"HTTP {status}" in result.error


@pytest.mark.anyio
async def test_no_answer_on_the_admin_side_is_not_proof_it_is_private() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/api/info", "/"):
            raise httpx.ConnectError("connection reset", request=request)
        return _healthy(request)

    result = await _run(handler)

    assert result.reachable is False
    assert "could not confirm that the admin API stays private" in result.error


@pytest.mark.parametrize("status", [403, 404])
@pytest.mark.anyio
async def test_a_refusal_counts_as_private(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/api/info", "/"):
            return httpx.Response(status)
        return _healthy(request)

    assert (await _run(handler)).reachable is True


# ------------------------------------------------ what the hub may fetch at all


def _never_called(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"the check fetched {request.url}")


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8080", "http://hub.example.test", "ftp://hub.example.test", ""]
)
@pytest.mark.anyio
async def test_only_an_https_address_is_fetched(url: str) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_never_called)) as client:
        result = await check_public_url(url, issuer=ISSUER, client=client, resolve=_public)

    assert result.reachable is False
    assert "not an https:// address" in result.error


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.5",
        "192.168.1.10",
        "169.254.169.254",
        "0.0.0.0",  # noqa: S104 - an address the check must refuse
        "::1",
        "::ffff:127.0.0.1",
        "fe80::1",
        "fc00::1",
    ],
)
@pytest.mark.anyio
async def test_a_name_that_leads_into_a_private_network_is_not_fetched(address: str) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_never_called)) as client:
        result = await check_public_url(
            ISSUER, issuer=ISSUER, client=client, resolve=_resolving_to(PUBLIC_ADDRESS, address)
        )

    assert result.reachable is False
    assert "not a public address" in result.error


@pytest.mark.parametrize("address", ["100.101.102.103", "fd7a:115c:a1e0::1"])
@pytest.mark.anyio
async def test_a_tailnet_address_is_fetched(address: str) -> None:
    """MagicDNS answers a Funnel name with the node's own tailnet address."""
    result = await _run(_healthy, resolve=_resolving_to(address))

    assert result.reachable is True, result


@pytest.mark.anyio
async def test_a_name_that_does_not_resolve_yet_is_reported_plainly() -> None:
    async def nowhere(host: str, port: int) -> list[str]:
        raise OSError("Name or service not known")

    async with httpx.AsyncClient(transport=httpx.MockTransport(_never_called)) as client:
        result = await check_public_url(ISSUER, issuer=ISSUER, client=client, resolve=nowhere)

    assert result.reachable is False
    assert "does not lead anywhere yet" in result.error


@pytest.mark.anyio
async def test_every_request_goes_to_the_checked_address_under_the_public_name() -> None:
    """The connection is made to the address that was checked, so a name that
    resolves elsewhere a moment later cannot redirect the check."""
    seen: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers["host"], request.url.path))
        return _healthy(request)

    result = await _run(handler)

    assert result.reachable is True
    assert {(host, header) for host, header, _path in seen} == {
        (PUBLIC_ADDRESS, "hub.example.test")
    }
    assert [path for _host, _header, path in seen] == [
        "/.well-known/oauth-authorization-server",
        "/mcp/default/",
        "/api/info",
        "/",
    ]


@pytest.mark.anyio
async def test_a_huge_answer_is_not_read_to_the_end() -> None:
    """Each answer is a 10 MB stream; only its first 64 KiB are read."""
    pulled: list[int] = []

    async def huge() -> AsyncIterator[bytes]:
        pulled.append(0)
        for _ in range(10_000):
            pulled[-1] += 1
            yield b"x" * 1024

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=huge())

    result = await _run(handler)

    assert result.reachable is False
    assert pulled and max(pulled) <= 64


@pytest.mark.anyio
async def test_the_whole_check_has_one_deadline() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.3)
        return _healthy(request)

    result = await _run(slow, overall_timeout=0.5)

    assert result.reachable is False
    assert "took longer than" in result.error


# --------------------------------------------- the real hub behind the real rule


def _cloud_entry_regex() -> re.Pattern[str]:
    """The cloud server block's location regex, as written in the template."""
    text = TEMPLATE.read_text(encoding="utf-8")
    block = text[text.index("listen ${CLOUD_PORT};") :]
    match = re.search(r"location ~ (\S+) \{", block)
    assert match, "the cloud entry's location regex is gone from nginx.conf.template"
    return re.compile(match.group(1).replace("\\\\", "\\"))


def _behind_the_cloud_entry(app: object) -> httpx.AsyncBaseTransport:
    inner = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    allowed = _cloud_entry_regex()

    class CloudEntry(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if not allowed.match(request.url.path):
                return httpx.Response(404, text="Not found.")
            request.headers["x-palaia-entry"] = "cloud"
            request.headers["x-forwarded-proto"] = "https"
            return await inner.handle_async_request(request)

    return CloudEntry()


def _hub(tmp_path: Path, mode: str) -> tuple[object, AuthorizationServer]:
    config = HubConfig(
        mode=mode,  # type: ignore[arg-type]
        host="127.0.0.1",
        oauth={"enabled": True, "issuer": ISSUER},  # type: ignore[arg-type]
    )
    server = AuthorizationServer.build(
        config, {"default": ["vault:work:read", "vault:work:write"]}, home=tmp_path
    )
    return create_app(config, home=tmp_path, oauth_server=server), server


@pytest.mark.anyio
async def test_the_real_cloud_entry_passes_and_keeps_the_admin_side_private(
    tmp_path: Path,
) -> None:
    app, server = _hub(tmp_path, "cloud")
    try:
        async with httpx.AsyncClient(
            transport=_behind_the_cloud_entry(app), base_url=ISSUER
        ) as client:
            result = await check_public_url(
                ISSUER, issuer=ISSUER, profile=None, client=client, resolve=_public
            )
            # The hub's own lock, separately from nginx's: a header-marked
            # request for an admin route is refused even if a proxy let it by.
            direct = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ISSUER)  # type: ignore[arg-type]
            async with direct:
                leaked = await direct.get("/api/info", headers={"x-palaia-entry": "cloud"})
    finally:
        server.store.close()

    assert result.reachable is True, result
    assert {check.id for check in result.checks} == {
        "discovery",
        "admin_private",
        "dashboard_private",
    }
    assert leaked.status_code == 404


@pytest.mark.anyio
async def test_the_real_cloud_entry_is_closed_until_cloud_access_is_on(tmp_path: Path) -> None:
    app, server = _hub(tmp_path, "locked")
    try:
        async with httpx.AsyncClient(
            transport=_behind_the_cloud_entry(app), base_url=ISSUER
        ) as client:
            result = await check_public_url(
                ISSUER, issuer=ISSUER, profile=None, client=client, resolve=_public
            )
    finally:
        server.store.close()

    assert result.reachable is False
    assert "cloud access is off" in result.error
