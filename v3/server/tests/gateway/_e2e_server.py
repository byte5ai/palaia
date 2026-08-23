"""Standalone HTTP server for the SPEC-105 Claude Code e2e connectivity test.

Not part of the ``palaia_hub`` package — a plain script invoked as a
subprocess (``sys.executable _e2e_server.py --port PORT``) by
``test_e2e_claude_code.py``, run in the SAME interpreter/venv as pytest
(inherits ``sys.executable``) so ``palaia_hub`` and its dependencies are
already importable.

Builds one fake-backed vault ("work") behind the hub's ``/mcp/default``
endpoint, and wraps the ASGI app in a small diagnostic middleware that logs
the method, path, headers, and request/response body of any request that
gets a ``400`` response — this is how SPEC-105 identified exactly which
request Claude Code sends that FastMCP 3.4.7 rejects before its handshake
succeeds (SPEC-002 FINDINGS Q5 flags the 400 but does not identify the
request; this SPEC's e2e test does).

**Finding** (captured verbatim in a run's ``server.log``, e.g.
``test_e2e_claude_code.py``'s tmp dir): the request is neither a malformed
``Accept`` header nor an early ``initialize`` (FINDINGS Q5's guess) — it is
a ``server/discover`` JSON-RPC probe Claude Code sends *before*
``initialize``, asking whether the server supports the newer stateless
protocol revision (``"_meta": {"io.modelcontextprotocol/protocolVersion":
"2026-07-28", ...}``), with no ``Mcp-Session-Id`` header (none exists yet).
FastMCP 3.4.7's streamable-HTTP transport (2025-11-25, session-based, per
MASTERPLAN §5.2's gate decision) rejects any non-``initialize`` request
without a session ID: ``{"jsonrpc":"2.0","id":"server-error","error":
{"code":-32600,"message":"Bad Request: Missing session ID"}}``. Claude Code
then immediately retries with a normal ``initialize`` on a fresh POST,
which succeeds and gets a session ID — matching FINDINGS Q5's "not fatal,
client retries, everything after succeeds". Nothing to fix in this SPEC:
it is Claude Code politely checking whether it can skip session
bookkeeping against a 2026-07-28-capable server, harmlessly declined by a
3.x/2025-11-25 one — resolved automatically once the hub moves to a
stable FastMCP 4.x (MASTERPLAN §5.2's documented upgrade path).
"""

from __future__ import annotations

import argparse
import logging

import uvicorn
from starlette.types import ASGIApp, Receive, Scope, Send

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService

logger = logging.getLogger("e2e_server.diagnostic")


class Log400RequestsMiddleware:
    """Logs method/path/Accept for any response with status 400.

    Exists purely to let the e2e test capture *which* request Claude Code
    sends that trips FastMCP 3.4.7's pre-handshake rejection (FINDINGS Q5),
    without guessing from uvicorn's plain access log line alone.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_body = bytearray()

        async def receive_wrapper() -> dict[str, object]:
            message = await receive()
            if message["type"] == "http.request":
                request_body.extend(message.get("body") or b"")  # type: ignore[arg-type]
            return message

        status_holder: dict[str, int] = {}
        response_body = bytearray()

        async def send_wrapper(message: dict[str, object]) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = int(message["status"])  # type: ignore[arg-type]
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body") or b"")  # type: ignore[arg-type]
            await send(message)

        await self.app(scope, receive_wrapper, send_wrapper)

        if status_holder.get("status") == 400:
            headers = {
                k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])
            }
            logger.warning(
                "DIAGNOSTIC 400: method=%s path=%s accept=%r content-type=%r "
                "mcp-session-id=%r user-agent=%r request-body=%r response-body=%r",
                scope["method"],
                scope["path"],
                headers.get("accept"),
                headers.get("content-type"),
                headers.get("mcp-session-id"),
                headers.get("user-agent"),
                bytes(request_body)[:2000].decode("utf-8", errors="replace"),
                bytes(response_body)[:2000].decode("utf-8", errors="replace"),
            )


def build_app() -> ASGIApp:
    gateway_config = GatewayConfig(
        vaults=[
            VaultMountConfig(
                key="work",
                name="work",
                purpose="SPEC-105 e2e connectivity check vault.",
            )
        ],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    gateway = build_gateway(gateway_config, {"work": FakeVaultService()})
    app = create_app(HubConfig(log_level="debug"), gateway=gateway)
    return Log400RequestsMiddleware(app)  # type: ignore[return-value]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    app = build_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", access_log=True)


if __name__ == "__main__":
    main()
