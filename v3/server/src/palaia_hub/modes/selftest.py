"""The public-address self-test (SPEC-205's "no fake green", issue #566).

The wizard never *claims* cloud access works without the hub fetching its own
public address the way a cloud AI app does. It used to fetch
``<public_url>/api/info`` — the one kind of route a correct Cloud setup keeps
private — and counted any status below 400 as success, so a correctly closed
tunnel failed while an unrelated page that answered 200 passed.

Now it checks what Cloud mode promises, each with its own result:

* **discovery** — ``/.well-known/oauth-authorization-server`` answers with
  this hub's sign-in metadata, and its ``issuer`` is the address the hub
  signs tokens for. Anything else (HTML, a redirect, another issuer) fails.
* **mcp** — the AI connection itself answers: ``/mcp/<profile>/`` without a
  token gets 401 with a ``Bearer`` challenge, as every MCP client expects.
* **admin_private** / **dashboard_private** — ``/api/info`` and ``/`` are
  refused (404 or 403, as the cloud entry answers them). A redirect, a
  sign-in prompt, an error or no answer does not prove they stay private, so
  none of these passes. In ``open`` mode the dashboard is public on purpose,
  so these two are not asked.

Redirects are never followed: a redirect does not prove the hub answered.

The address comes from the request, so the hub fetches only what a cloud AI
app could: an ``https`` URL whose host resolves to public addresses — or to
Tailscale's, where MagicDNS answers a Funnel name with the node's own. Each
request goes to an address checked that way (the host name travels in the
``Host`` header and TLS), so a name that resolves differently a moment later
cannot point the check at the hub's own network. Answers are read up to a
size cap, and the whole check has one deadline.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from fastmcp.server.auth.ssrf import format_ip_for_url, is_ip_allowed

_DEFAULT_TIMEOUT_SECONDS = 8.0
#: Every request of one check together, name lookup included.
_OVERALL_TIMEOUT_SECONDS = 20.0
#: What the checks read of one answer: a sign-in document, a short refusal,
#: the dashboard's HTML shell. The rest of a larger answer is not read.
_MAX_BODY_BYTES = 64 * 1024
_METADATA_PATH = "/.well-known/oauth-authorization-server"
#: Tailscale's addresses. Not public, but where a hub on a tailnet meets its
#: own Funnel name; only https with a valid certificate is fetched there.
_TAILNET_NETWORKS = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fd7a:115c:a1e0::/48"),
)

#: ``(host, port) -> addresses``; injectable so tests need no DNS.
Resolver = Callable[[str, int], Awaitable[list[str]]]


@dataclass(frozen=True, slots=True)
class SelfTestCheck:
    id: str
    passed: bool
    #: Plain-language result: what was seen, and the fix when it failed.
    detail: str


@dataclass(frozen=True, slots=True)
class SelfTestResult:
    checked_url: str
    #: Every check passed.
    reachable: bool
    #: HTTP status of the first request, when one was answered at all.
    status_code: int | None
    latency_ms: float | None
    #: Empty when reachable; the first failed check's detail otherwise.
    error: str
    checks: tuple[SelfTestCheck, ...] = ()


def _metadata_url(base: str, issuer: str) -> str:
    """RFC 8414 §3: the well-known segment goes between origin and path."""
    path = urlsplit(issuer).path.rstrip("/")
    return base + _METADATA_PATH + path


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def _may_fetch(address: str) -> bool:
    """A public address, or a tailnet one; never loopback, private, link-local
    (cloud metadata services among them) or reserved."""
    if is_ip_allowed(address):
        return True
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in _TAILNET_NETWORKS)


def _refused(base: str, error: str) -> SelfTestResult:
    return SelfTestResult(
        checked_url=base, reachable=False, status_code=None, latency_ms=None, error=error
    )


async def check_public_url(
    public_url: str,
    *,
    issuer: str | None = None,
    profile: str | None = "default",
    mode: str = "cloud",
    client: httpx.AsyncClient | None = None,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    overall_timeout: float = _OVERALL_TIMEOUT_SECONDS,
    resolve: Resolver = _resolve,
) -> SelfTestResult:
    """Fetch the public address like a cloud AI app would; report each check.

    Args:
        issuer: the sign-in address the running hub signs tokens for. Without
            one (per-client tokens only) the discovery check is skipped.
        profile: the profile whose MCP endpoint to probe.
        mode: in ``open`` the dashboard is public by design, so the two
            "stays private" checks are skipped.
        client: an existing :class:`httpx.AsyncClient` (tests wire one to a
            mock or in-process transport); omitted, one is opened for this call.
        resolve: how the host name is looked up (tests pass a fixed answer).
    """
    base = public_url.strip().rstrip("/")
    parts = urlsplit(base)
    if parts.scheme != "https" or not parts.hostname:
        return _refused(
            base,
            f"{base or 'the address'} is not an https:// address. Cloud AI apps connect only "
            "over https. Fix: enter the public https address of your tunnel.",
        )
    host = parts.hostname
    try:
        port = parts.port or 443
    except ValueError:
        return _refused(base, f"{base} has no valid port.")
    start = time.monotonic()
    deadline = start + overall_timeout
    try:
        addresses = await asyncio.wait_for(resolve(host, port), timeout)
    except (OSError, TimeoutError):
        addresses = []
    if not addresses:
        return _refused(
            base,
            f"{host} does not lead anywhere yet (its name does not resolve). A new public "
            "address can take a few minutes; check again shortly.",
        )
    blocked = [address for address in addresses if not _may_fetch(address)]
    if blocked:
        return _refused(
            base,
            f"{host} resolves to {', '.join(blocked)}, which is not a public address. Fix: "
            "enter the public https address your tunnel gives this hub.",
        )
    # What the address names (host and port, as written), sent as `Host`.
    authority = parts.netloc.rpartition("@")[2]
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    checks: list[SelfTestCheck] = []
    first_status: int | None = None
    latency_ms: float | None = None

    async def fetch(url: str) -> httpx.Response | str:
        """GET ``url`` from one of the checked addresses, never another."""
        nonlocal first_status, latency_ms
        path = urlsplit(url).path
        failure = f"nothing answered at {url} within {timeout:.0f}s."
        for address in addresses:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return f"checking {base} took longer than {overall_timeout:.0f}s."
            pinned = f"https://{format_ip_for_url(address)}:{port}{path}"
            try:
                async with http.stream(
                    "GET",
                    pinned,
                    headers={"host": authority},
                    extensions={"sni_hostname": host},
                    timeout=min(timeout, remaining),
                    follow_redirects=False,
                ) as streamed:
                    body = bytearray()
                    async for chunk in streamed.aiter_bytes():
                        body += chunk
                        if len(body) >= _MAX_BODY_BYTES:
                            break
            except httpx.TimeoutException:
                failure = f"nothing answered at {url} within {min(timeout, remaining):.0f}s."
                continue
            except httpx.RequestError as exc:
                failure = f"could not connect to {url}: {exc}"
                continue
            response = httpx.Response(
                streamed.status_code,
                # The body is already decoded and possibly cut short.
                headers=[
                    (name, value)
                    for name, value in streamed.headers.multi_items()
                    if name not in ("content-encoding", "content-length", "transfer-encoding")
                ],
                content=bytes(body[:_MAX_BODY_BYTES]),
            )
            if first_status is None:
                first_status = response.status_code
                latency_ms = (time.monotonic() - start) * 1000
            return response
        return failure

    try:
        if issuer:
            url = _metadata_url(base, issuer)
            got = await fetch(url)
            if isinstance(got, str):
                checks.append(SelfTestCheck("discovery", False, got))
                # Nothing answers at all — the other checks would only repeat it.
                return _result(base, checks, first_status, latency_ms)
            checks.append(_check_discovery(url, got, issuer))
        if profile:
            url = f"{base}/mcp/{profile}/"
            got = await fetch(url)
            if isinstance(got, str):
                checks.append(SelfTestCheck("mcp", False, got))
                return _result(base, checks, first_status, latency_ms)
            checks.append(_check_mcp(url, got))
        if mode != "open":
            url = f"{base}/api/info"
            got = await fetch(url)
            checks.append(_check_private("admin_private", url, got, _is_hub_info))
            url = f"{base}/"
            got = await fetch(url)
            checks.append(_check_private("dashboard_private", url, got, _is_dashboard))
    finally:
        if owns_client:
            await http.aclose()
    return _result(base, checks, first_status, latency_ms)


def _result(
    base: str, checks: list[SelfTestCheck], status: int | None, latency_ms: float | None
) -> SelfTestResult:
    failed = [check for check in checks if not check.passed]
    return SelfTestResult(
        checked_url=base,
        reachable=bool(checks) and not failed,
        status_code=status,
        latency_ms=latency_ms,
        error=failed[0].detail if failed else ("" if checks else "nothing to check."),
        checks=tuple(checks),
    )


def _check_discovery(url: str, response: httpx.Response, issuer: str) -> SelfTestCheck:
    if response.is_redirect:
        return SelfTestCheck(
            "discovery",
            False,
            f"{url} redirects to {response.headers.get('location', '?')} instead of answering "
            "— the address does not lead to this hub's cloud entry.",
        )
    if response.status_code == 403 and "cloud_access_off" in response.text:
        return SelfTestCheck(
            "discovery",
            False,
            "the tunnel reaches this hub, but cloud access is off. Fix: switch to Cloud mode "
            "and restart the hub.",
        )
    if response.status_code != 200:
        return SelfTestCheck(
            "discovery",
            False,
            f"{url} answered HTTP {response.status_code}, not this hub's sign-in details.",
        )
    try:
        data = response.json()
    except ValueError:
        return SelfTestCheck(
            "discovery", False, f"{url} answered, but not with this hub's sign-in details."
        )
    seen = str(data.get("issuer", "")) if isinstance(data, dict) else ""
    if seen.rstrip("/") != issuer.rstrip("/"):
        return SelfTestCheck(
            "discovery",
            False,
            f"{url} names the sign-in address {seen or 'nothing'!r}, but this hub signs for "
            f"{issuer!r}. Fix: use the same public address for both.",
        )
    return SelfTestCheck("discovery", True, f"sign-in details found for {issuer}.")


def _check_mcp(url: str, response: httpx.Response) -> SelfTestCheck:
    challenge = response.headers.get("www-authenticate", "")
    if response.status_code == 401 and challenge.lower().startswith("bearer"):
        return SelfTestCheck("mcp", True, "the AI connection answers and asks for sign-in.")
    if response.status_code == 403 and "cloud_access_off" in response.text:
        return SelfTestCheck(
            "mcp",
            False,
            "the tunnel reaches this hub, but cloud access is off. Fix: switch to Cloud mode "
            "and restart the hub.",
        )
    return SelfTestCheck(
        "mcp",
        False,
        f"{url} answered HTTP {response.status_code} instead of asking an AI app to sign in.",
    )


def _is_hub_info(response: httpx.Response) -> bool:
    try:
        data = response.json()
    except ValueError:
        return False
    return isinstance(data, dict) and "version" in data and "mode" in data


def _is_dashboard(response: httpx.Response) -> bool:
    return 'id="root"' in response.text and "palaia" in response.text.lower()


def _check_private(
    check_id: str, url: str, got: httpx.Response | str, exposes: object
) -> SelfTestCheck:
    """Passes only on the refusal the cloud entry gives (404, or 403)."""
    what = "admin API" if check_id == "admin_private" else "dashboard"
    if isinstance(got, str):
        return SelfTestCheck(
            check_id, False, f"could not confirm that the {what} stays private: {got}"
        )
    if got.status_code in (403, 404):
        return SelfTestCheck(check_id, True, f"the {what} stays private.")
    if got.status_code == 200 and callable(exposes) and exposes(got):
        return SelfTestCheck(
            check_id,
            False,
            f"the {what} answers at this public address. Fix: point the tunnel at palaia's "
            "cloud entry (port 8422 on the server), not at the dashboard (port 8420).",
        )
    seen = f"HTTP {got.status_code}"
    if got.is_redirect:
        seen += f", a redirect to {got.headers.get('location', '?')}"
    elif got.status_code == 401:
        seen += ", a sign-in prompt"
    return SelfTestCheck(
        check_id,
        False,
        f"{url} answered {seen} instead of refusing, so palaia cannot confirm that the "
        f"{what} stays private. Fix: point the tunnel at palaia's cloud entry (port 8422 "
        "on the server), which refuses it.",
    )


__all__ = ["SelfTestCheck", "SelfTestResult", "check_public_url"]
