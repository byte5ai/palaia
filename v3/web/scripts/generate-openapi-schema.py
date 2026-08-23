#!/usr/bin/env python3
"""Dump the hub's OpenAPI schema for `npm run gen:api` (SPEC-109).

Run via ``uv run --project ../server python scripts/generate-openapi-schema.py``
from ``v3/web``. Writes ``openapi.json`` next to this script's caller (the
current working directory), which ``openapi-typescript`` then turns into
``src/lib/api/schema.gen.ts`` — see the ``gen:api`` script in package.json.
Not part of the build itself: the generated TypeScript file is committed,
so a normal `npm install && npm run build` never needs a Python
interpreter or a running hub.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server" / "src"))

from palaia_hub.app import create_app  # noqa: E402
from palaia_hub.config import HubConfig  # noqa: E402


def main() -> None:
    app = create_app(HubConfig())
    out_path = Path("openapi.json")
    out_path.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path.resolve()}")


if __name__ == "__main__":
    main()
