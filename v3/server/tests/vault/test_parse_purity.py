"""Purity guard for the parser (SPEC-103 acceptance criterion).

``palaia_hub.vault.parse`` must do no I/O: no filesystem, network, process,
or database access, directly or through its own imports. This is enforced
statically (an AST scan of the source, not a runtime import) so the check
holds even for I/O reachable only through a code path this test suite
doesn't happen to exercise.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

PARSE_MODULE = "palaia_hub.vault.parse"

#: Sibling vault modules considered pure (no I/O) — verified by this same
#: check and by inspection: frontmatter/permalink/links only ever touch
#: strings, re, yaml, unicodedata, dataclasses, datetime, typing.
ALLOWED_LOCAL_IMPORTS = {
    "palaia_hub.vault.frontmatter",
    "palaia_hub.vault.permalink",
    "palaia_hub.vault.links",
    "palaia_hub.vault.models",
}

#: Stdlib/third-party modules that mean "this does I/O" if imported.
FORBIDDEN_MODULES = {
    "os",
    "sys",
    "io",
    "pathlib",
    "shutil",
    "subprocess",
    "socket",
    "sqlite3",
    "tempfile",
    "asyncio",
    "requests",
    "httpx",
    "aiohttp",
    "watchfiles",
    "git",
    "fastapi",
    "uvicorn",
    "fastmcp",
    "platformdirs",
}


def _module_path(module_name: str) -> Path:
    spec = importlib.util.find_spec(module_name)
    assert spec is not None and spec.origin is not None, f"can't locate {module_name}"
    return Path(spec.origin)


def _imported_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                if node.level:
                    # relative import, e.g. "from . import frontmatter"
                    for alias in node.names:
                        names.add(f"palaia_hub.vault.{alias.name}")
                else:
                    names.add(node.module)
            elif node.level:
                for alias in node.names:
                    names.add(f"palaia_hub.vault.{alias.name}")
    return names


def test_parse_module_imports_no_io_capable_module() -> None:
    source = _module_path(PARSE_MODULE).read_text(encoding="utf-8")
    imported = _imported_names(source)

    forbidden_hits = {
        name
        for name in imported
        if name.split(".")[0] in FORBIDDEN_MODULES
        or any(name.startswith(f) for f in FORBIDDEN_MODULES)
    }
    assert not forbidden_hits, f"{PARSE_MODULE} imports I/O-capable module(s): {forbidden_hits}"

    local_hits = {
        name
        for name in imported
        if name.startswith("palaia_hub.vault.") and name not in ALLOWED_LOCAL_IMPORTS
    }
    assert not local_hits, (
        f"{PARSE_MODULE} imports non-allowlisted sibling module(s): {local_hits} "
        "— siblings must be added to ALLOWED_LOCAL_IMPORTS only after confirming "
        "they too do no I/O"
    )


def test_allowed_sibling_modules_do_no_io_either() -> None:
    for module_name in ALLOWED_LOCAL_IMPORTS:
        source = _module_path(module_name).read_text(encoding="utf-8")
        imported = _imported_names(source)
        forbidden_hits = {
            name
            for name in imported
            if name.split(".")[0] in FORBIDDEN_MODULES
        }
        assert not forbidden_hits, f"{module_name} imports I/O-capable module(s): {forbidden_hits}"
