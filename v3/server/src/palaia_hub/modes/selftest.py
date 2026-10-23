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
  *not* this hub's admin API and dashboard. In ``open`` mode the dashboard is
  public on purpose, so these two are not asked.

Redirects are never followed: a redirect does not prove the hub answered.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

_DEFAULT_TIMEOUT_SECONDS = 8.0
_METADATA_PATH = "/.well-known/oauth-authorization-server"


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


async def check_public_url(
    public_url: str,
    *,
    issuer: str | None = None,
    profile: str | None = "default",
    mode: str = "cloud",
    client: httpx.AsyncClient | None = None,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
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
    """
    base = public_url.rstrip("/")
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    checks: list[SelfTestCheck] = []
    first_status: int | None = None
    start = time.monotonic()
    latency_ms: float | None = None

    async def fetch(url: str) -> httpx.Response | str:
        nonlocal first_status, latency_ms
        try:
            response = await http.get(url, timeout=timeout, follow_redirects=False)
        except httpx.TimeoutException:
            return f"nothing answered at {url} within {timeout:.0f}s."
        except httpx.RequestError as exc:
            return f"could not connect to {url}: {exc}"
        if first_status is None:
            first_status = response.status_code
            latency_ms = (time.monotonic() - start) * 1000
        return response

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
            got = await fetch(f"{base}/api/info")
            checks.append(_check_private("admin_private", got, _is_hub_info))
            got = await fetch(f"{base}/")
            checks.append(_check_private("dashboard_private", got, _is_dashboard))
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


def _check_private(check_id: str, got: httpx.Response | str, exposes: object) -> SelfTestCheck:
    what = "admin API" if check_id == "admin_private" else "dashboard"
    if isinstance(got, str):
        return SelfTestCheck(check_id, True, f"the {what} does not answer here.")
    if got.status_code == 200 and callable(exposes) and exposes(got):
        return SelfTestCheck(
            check_id,
            False,
            f"the {what} answers at this public address. Fix: point the tunnel at palaia's "
            "cloud entry (port 8422 on the server), not at the dashboard (port 8420).",
        )
    return SelfTestCheck(check_id, True, f"the {what} stays private.")


__all__ = ["SelfTestCheck", "SelfTestResult", "check_public_url"]
