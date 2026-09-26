"""palaia MCP Server — expose palaia memory via Model Context Protocol.

Works with Claude Desktop, Cursor, and any MCP-compatible host.
Independent of OpenClaw — palaia as a standalone memory layer.

Usage:
    palaia-mcp                          # stdio transport (default)
    palaia-mcp --root /path/to/.palaia  # explicit store root
    palaia-mcp --read-only              # no writes allowed
    palaia mcp-server                   # via CLI subcommand
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass

# Supported MCP SDK range. Keep MCP_SDK_REQUIREMENT in sync with the `mcp` extra in
# pyproject.toml, and the bounds below with MCP_SDK_REQUIREMENT.
# 1.2.0 introduced `mcp.server.fastmcp`; 2.x renamed FastMCP and dropped that module.
MCP_SDK_REQUIREMENT = "mcp>=1.2.0,<2"
_MCP_SDK_MIN = (1, 2)  # inclusive
_MCP_SDK_MAX = (2,)  # exclusive


@dataclass(frozen=True)
class McpSdkStatus:
    """Result of check_mcp_sdk().

    state is "ok", "missing" or "unsupported"; problem and fix are user-facing
    strings, set unless state is "ok".
    """

    state: str
    installed_version: str | None = None
    problem: str | None = None
    fix: str | None = None

    @property
    def ok(self) -> bool:
        return self.state == "ok"


def _release(version: str) -> tuple[int, ...] | None:
    """Leading numeric release segment of a version string ("1.30.0rc1" -> (1, 30, 0))."""
    match = re.match(r"\d+(?:\.\d+)*", version)
    return tuple(int(part) for part in match.group().split(".")) if match else None


def check_mcp_sdk() -> McpSdkStatus:
    """Check the installed MCP SDK version against the supported range.

    Reads package metadata only; it does not import the SDK.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        installed = version("mcp")
    except PackageNotFoundError:
        return McpSdkStatus("missing", problem="MCP SDK not installed", fix="pip install 'palaia[mcp]'")

    release = _release(installed)
    if release is None or not (_MCP_SDK_MIN <= release < _MCP_SDK_MAX):
        return McpSdkStatus(
            "unsupported",
            installed_version=installed,
            problem=f"mcp {installed} is not supported (palaia needs {MCP_SDK_REQUIREMENT})",
            fix=f"pip install '{MCP_SDK_REQUIREMENT}'",
        )
    return McpSdkStatus("ok", installed_version=installed)


def main(argv: list[str] | None = None) -> None:
    """Entry point for `palaia-mcp` and `palaia mcp-server`."""
    parser = argparse.ArgumentParser(
        prog="palaia-mcp",
        description="palaia MCP Server — local memory for AI agents via MCP",
    )
    parser.add_argument(
        "--root",
        help="Path to .palaia directory (default: auto-detect via PALAIA_HOME or cwd)",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Disable write operations (store, edit, gc)",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )

    args = parser.parse_args(argv)

    sdk = check_mcp_sdk()
    if not sdk.ok:
        print(f"Error: {sdk.problem}. Install with: {sdk.fix}", file=sys.stderr)
        sys.exit(1)

    from pathlib import Path

    from palaia.config import find_palaia_root

    # Resolve store root
    if args.root:
        root = Path(args.root)
        if not root.exists():
            print(f"Error: {root} does not exist", file=sys.stderr)
            sys.exit(1)
        if root.name != ".palaia" and (root / ".palaia").exists():
            root = root / ".palaia"
    else:
        found = find_palaia_root()
        if found is None:
            print(
                "Error: No .palaia store found. Run 'palaia init' first, "
                "or use --root to specify the path.",
                file=sys.stderr,
            )
            sys.exit(1)
        root = found

    try:
        from palaia.mcp.server import create_server
    except ImportError as e:
        # A supported version that still fails to import is a broken install
        # (e.g. a missing dependency) — show the real cause.
        print(f"Error: mcp {sdk.installed_version} failed to import: {e}", file=sys.stderr)
        sys.exit(1)

    server = create_server(root, read_only=args.read_only)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
