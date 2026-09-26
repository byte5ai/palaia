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
import sys

# Supported MCP SDK range. Keep in sync with the `mcp` extra in pyproject.toml.
# 1.2.0 introduced `mcp.server.fastmcp`; 2.x renamed FastMCP and dropped that module.
MCP_SDK_REQUIREMENT = "mcp>=1.2.0,<2"


def check_mcp_sdk() -> tuple[str, str] | None:
    """Check that a supported MCP SDK is installed.

    Returns None if palaia-mcp can run, otherwise a ``(problem, fix)`` pair of
    user-facing strings.
    """
    try:
        import mcp  # noqa: F401
    except ImportError:
        return "MCP SDK not installed", "pip install 'palaia[mcp]'"

    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F401
    except ImportError:
        from importlib.metadata import PackageNotFoundError, version

        try:
            installed = f"mcp {version('mcp')}"
        except PackageNotFoundError:
            installed = "The installed MCP SDK"
        return (
            f"{installed} is not supported (palaia needs {MCP_SDK_REQUIREMENT})",
            f"pip install '{MCP_SDK_REQUIREMENT}'",
        )
    return None


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

    sdk_problem = check_mcp_sdk()
    if sdk_problem:
        problem, fix = sdk_problem
        print(f"Error: {problem}. Install with: {fix}", file=sys.stderr)
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

    from palaia.mcp.server import create_server

    server = create_server(root, read_only=args.read_only)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
