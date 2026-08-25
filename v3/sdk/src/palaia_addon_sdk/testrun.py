"""``palaia-addon test``: spin the add-on up locally and drive
initialize/tools-list through a real MCP client, printing what a
marketplace user would see (name, one-liner, config form fields,
permissions) alongside proof the running server actually answered.

Convention: an add-on directory holds ``manifest.json`` next to a
``server.py`` entry point, run with ``uv run server.py`` (a PEP 723
"inline script metadata" file — the standard way to run a small Python
script with its own pinned dependencies with nothing to install by hand).
``palaia-addon init`` scaffolds exactly this pair.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .mcp_client import McpClientError, StdioMcpClient, ToolsListResult
from .models import AddonManifest
from .validate import MANIFEST_FILENAME, load_manifest_raw

SERVER_FILENAME = "server.py"


class TestRunError(RuntimeError):
    """The add-on could not be exercised locally — message is printable
    as-is."""


@dataclass(frozen=True, slots=True)
class TestRunResult:
    manifest: AddonManifest
    tools: ToolsListResult


def run_local_test(addon_dir: Path, *, timeout: float = 20.0) -> TestRunResult:
    raw, issues = load_manifest_raw(addon_dir)
    if raw is None:
        raise TestRunError("; ".join(str(issue) for issue in issues))
    try:
        manifest = AddonManifest.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - re-raised as a plain test-run failure
        raise TestRunError(
            f"{MANIFEST_FILENAME} does not validate — run `palaia-addon validate` first: {exc}"
        ) from exc

    server_path = addon_dir / SERVER_FILENAME
    if not server_path.is_file():
        raise TestRunError(
            f"no {SERVER_FILENAME} next to {MANIFEST_FILENAME} in {addon_dir} — "
            f"`palaia-addon init` scaffolds one; a hand-built add-on needs its own "
            f"MCP stdio server to test against"
        )

    command = ["uv", "run", "--quiet", str(server_path)]
    try:
        with StdioMcpClient(command, cwd=str(addon_dir), timeout=timeout) as client:
            tools = client.initialize_and_list_tools()
    except McpClientError as exc:
        raise TestRunError(str(exc)) from exc

    return TestRunResult(manifest=manifest, tools=tools)


def format_preview(result: TestRunResult) -> str:
    """Render exactly what a marketplace user would see, plus the live
    proof the server answered — the acceptance criterion's own wording."""
    manifest = result.manifest
    lines = [
        f"{manifest.name} — {manifest.one_liner}",
        f"maintainer: {manifest.maintainer}",
        f"kind: {manifest.kind}",
        f"permissions: {', '.join(manifest.permissions) if manifest.permissions else 'none'}",
    ]

    properties: dict[str, Any] = (manifest.config_schema or {}).get("properties", {})
    if properties:
        required = set((manifest.config_schema or {}).get("required", []))
        lines.append("config form fields:")
        for field_name, prop in properties.items():
            label = prop.get("title", field_name) if isinstance(prop, dict) else field_name
            kind = prop.get("type", "?") if isinstance(prop, dict) else "?"
            mark = " (required)" if field_name in required else ""
            lines.append(f"  - {label} [{kind}]{mark}")
    else:
        lines.append("config form fields: none — this add-on needs no setup")

    tool_names = ", ".join(str(tool.get("name", "?")) for tool in result.tools.tools) or "(none)"
    reported_name = result.tools.server_name or manifest.name
    lines.append(
        f"live check: {reported_name} answered tools/list with "
        f"{len(result.tools.tools)} tool(s): {tool_names}"
    )
    return "\n".join(lines)


__all__ = ["SERVER_FILENAME", "TestRunError", "TestRunResult", "format_preview", "run_local_test"]
