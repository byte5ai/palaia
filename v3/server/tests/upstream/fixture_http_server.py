"""A real second FastMCP server, served over streamable HTTP, as an
``http`` upstream fixture (SPEC-302 acceptance criterion #1: "a real second
FastMCP server (test fixture) connected as an upstream").

Started as a subprocess by ``conftest.py``'s ``http_upstream`` fixture — a
separate OS process, so a call that comes back through it has demonstrably
left the hub. When ``--require-token`` is passed it rejects any request whose
``Authorization`` header does not carry that exact bearer token, which is how
``test_http_upstream.py`` proves the secret store's value reached the wire.
"""

from __future__ import annotations

import argparse

import uvicorn
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier


def build_server(required_token: str | None) -> FastMCP:
    auth = (
        StaticTokenVerifier(tokens={required_token: {"client_id": "fixture", "scopes": []}})
        if required_token
        else None
    )
    server: FastMCP = FastMCP(name="fixture-http-upstream", auth=auth)

    @server.tool
    def echo(text: str) -> str:
        """Echo text back, prefixed so the caller can prove where it came from."""
        return f"fixture-http-upstream echo: {text}"

    @server.tool
    def ping() -> str:
        """Liveness check."""
        return "pong"

    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--require-token", default=None)
    args = parser.parse_args()
    server = build_server(args.require_token)
    uvicorn.run(server.http_app(path="/"), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
