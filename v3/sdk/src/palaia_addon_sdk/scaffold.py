"""``palaia-addon init``: scaffold a new add-on directory — a manifest, a
README, and a minimal working stdio MCP server example that answers
``tools/list`` out of the box (so the scaffold passes ``validate`` and
``test`` immediately, per SPEC-406's acceptance criterion).
"""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path

#: fastmcp stays pinned to the one version the rest of palaia uses (repo
#: rule) — the scaffold's example server follows the same pin so an
#: author's first "it works" is on the version the hub itself runs.
FASTMCP_PIN = "3.4.7"

SERVER_TEMPLATE = '''#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["fastmcp=={fastmcp_pin}"]
# ///
"""{name} — an example MCP server, scaffolded by `palaia-addon init`.

Replace the tool below with your add-on's real one(s). Run it directly
with `uv run server.py` (uv reads the dependency block above and installs
it on first run) — that is exactly what `palaia-addon test` does.
"""

from fastmcp import FastMCP

mcp = FastMCP("{name}")


@mcp.tool
def greet(name: str = "world") -> str:
    """Say hello — replace with your add-on's real tool(s)."""
    return f"Hello, {{name}}!"


if __name__ == "__main__":
    mcp.run()
'''

README_TEMPLATE = """# {name}

{one_liner}

## Develop

    uv run server.py

## Check it locally

    palaia-addon validate .
    palaia-addon test .

## Submit

See `v3/docs/addon-submission.md` in the palaia repository for the
submission flow once this add-on works.
"""


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "my-addon"


def scaffold_addon(
    target_dir: Path,
    *,
    addon_id: str | None = None,
    name: str | None = None,
    one_liner: str = "Describe in one plain sentence what this add-on does.",
    maintainer: str,
) -> list[Path]:
    """Write ``manifest.json``, ``server.py`` and ``README.md`` into
    ``target_dir`` (created if needed). Refuses to overwrite an existing
    manifest — ``init`` is for a fresh directory."""
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = target_dir / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError(f"{manifest_path} already exists — init is for a fresh directory")

    display_name = name or target_dir.name.replace("-", " ").replace("_", " ").title()
    slug = addon_id or _slugify(display_name)

    manifest = {
        "id": slug,
        "name": display_name,
        "one_liner": one_liner,
        # "container" is how a finished add-on ships (SPEC-303/304: a
        # containerized local MCP server) — the placeholder image name is
        # meant to be replaced once the author builds and pushes one.
        # `palaia-addon test` runs the stdio server directly for a fast
        # local loop and never needs this image.
        "kind": "container",
        "source": {"type": "image", "value": f"ghcr.io/{maintainer}/{slug}:0.1.0"},
        "config_schema": {
            "type": "object",
            "properties": {
                "greeting_style": {
                    "title": "Greeting style",
                    "type": "string",
                }
            },
        },
        "permissions": [],
        "maintainer": maintainer,
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    manifest_path.write_text(manifest_text, encoding="utf-8")

    server_path = target_dir / "server.py"
    server_path.write_text(
        SERVER_TEMPLATE.format(name=display_name, fastmcp_pin=FASTMCP_PIN), encoding="utf-8"
    )
    server_path.chmod(server_path.stat().st_mode | stat.S_IEXEC)

    readme_path = target_dir / "README.md"
    readme_path.write_text(
        README_TEMPLATE.format(name=display_name, one_liner=one_liner), encoding="utf-8"
    )

    return [manifest_path, server_path, readme_path]


__all__ = ["scaffold_addon"]
