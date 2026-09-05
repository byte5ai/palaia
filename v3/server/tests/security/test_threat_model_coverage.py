"""The threat model covers every surface this hub actually mounts (SPEC-502 #1).

Acceptance criterion #1, stated in the SPEC as bluntly as it deserves: *a
doc that can rot is a doc that will*. So the threat model is not checked by
reading it — it is checked against the running app.

Four inventories are taken from the code, never from a list in this file:

* every REST **route group** the package declares (``/api/<group>``);
* every **authorization-server path** (``/oauth/*`` and the ``.well-known``
  discovery documents);
* every **MCP mount** — ``/mcp``, ``/mcp/stash``, ``/mcp/hub`` …;
* every **tool-family module** under ``palaia_hub/gateway/`` (``*_tools.py``),
  which is what a mount actually exposes.

The first three are read out of the package's **source** with the AST rather
than off an assembled app's route table. That is deliberate: almost every
router in :func:`palaia_hub.app.create_app` is opt-in on a store the caller
passes, so *no single test hub mounts them all* — an inventory taken from a
live app would quietly shrink to whatever that particular hub happened to
wire, and the surfaces most worth covering (the marketplace, the secret
store, the upstream editor) are exactly the ones it would miss.
:func:`test_the_route_table_agrees_with_the_source_scan` keeps the scan
honest by checking it is a superset of what a real app serves.

Each name must appear verbatim in ``v3/docs/security/threat-model.md``. Ship
a new router or a new tool family without a line in the threat model and this
test fails with its name.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.routing import Route

import palaia_hub
from palaia_hub import app as app_module

from .conftest import Hub

REPO_V3 = Path(__file__).resolve().parents[3]
THREAT_MODEL = REPO_V3 / "docs" / "security" / "threat-model.md"
REVIEW_BRIEF = REPO_V3 / "docs" / "security" / "external-review-brief.md"
SECURITY_POLICY = REPO_V3 / "SECURITY.md"


def _walk(routes: Iterable[Any]) -> Iterator[Route]:
    """Flatten the app's route list, following included routers.

    Same shape as ``tests/test_admin_session.py``'s walk, and for the same
    reason: this FastAPI version keeps an included router as one opaque
    entry rather than splicing its routes into ``app.routes``.
    """
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            yield from _walk(original.routes)
        elif isinstance(route, Route):
            yield route


#: A path literal: leading slash, then segments of the characters a route
#: template may use (including ``{param}`` placeholders).
_PATH_RE = re.compile(r"^/[A-Za-z0-9_.\-{}]+(?:/[A-Za-z0-9_.\-{}]+)*$")


def _source_path_literals() -> set[str]:
    """Every route-shaped string constant in the ``palaia_hub`` package."""
    package = Path(palaia_hub.__file__).parent
    literals: set[str] = set()
    for module in sorted(package.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                if _PATH_RE.match(value):
                    literals.add(value)
    return literals


def api_groups() -> set[str]:
    """``{"/api/vaults", "/api/auth", …}`` — one entry per router group."""
    groups: set[str] = set()
    for value in _source_path_literals():
        parts = value.strip("/").split("/")
        if parts[0] == "api" and len(parts) >= 2 and parts[1]:
            groups.add(f"/api/{parts[1]}")
    return groups


def oauth_paths() -> set[str]:
    return {
        value for value in _source_path_literals() if value.startswith(("/oauth/", "/.well-known/"))
    }


def mcp_mounts() -> set[str]:
    """Every ``app.mount("/mcp…")`` literal in :mod:`palaia_hub.app`."""
    tree = ast.parse(Path(app_module.__file__).read_text(encoding="utf-8"))
    mounts: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "mount"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            if first.value.startswith("/mcp"):
                mounts.add(first.value)
    return mounts


def live_api_groups(app: FastAPI) -> set[str]:
    """The same shape, read off an assembled app's real route table."""
    groups: set[str] = set()
    for route in _walk(app.routes):
        parts = route.path.strip("/").split("/")
        if parts[0] == "api" and len(parts) >= 2:
            groups.add(f"/api/{parts[1]}")
    return groups


def tool_family_modules() -> set[str]:
    gateway_dir = Path(palaia_hub.__file__).parent / "gateway"
    return {path.stem for path in gateway_dir.glob("*_tools.py")}


@pytest.fixture(scope="module")
def threat_model() -> str:
    assert THREAT_MODEL.is_file(), f"{THREAT_MODEL} is missing"
    return THREAT_MODEL.read_text(encoding="utf-8")


# ------------------------------------------------------------ the inventories


def test_the_inventories_are_not_empty() -> None:
    """Guard the guard: an empty inventory passes every check below."""
    assert len(api_groups()) >= 15, sorted(api_groups())
    assert len(oauth_paths()) >= 8, sorted(oauth_paths())
    assert len(mcp_mounts()) >= 5, sorted(mcp_mounts())
    assert len(tool_family_modules()) >= 3, sorted(tool_family_modules())


def test_the_route_table_agrees_with_the_source_scan(hub: Hub) -> None:
    """The scan must cover at least what a real app actually serves."""
    served = live_api_groups(hub.app)
    assert served <= api_groups(), sorted(served - api_groups())


def test_every_rest_group_is_in_the_threat_model(threat_model: str) -> None:
    missing = sorted(group for group in api_groups() if group not in threat_model)
    assert missing == [], f"REST groups with no entry in the threat model: {missing}"


def test_every_oauth_path_is_in_the_threat_model(threat_model: str) -> None:
    missing = sorted(path for path in oauth_paths() if path not in threat_model)
    assert missing == [], f"authorization-server paths not covered: {missing}"


def test_every_mcp_mount_is_in_the_threat_model(threat_model: str) -> None:
    missing = sorted(mount for mount in mcp_mounts() if mount not in threat_model)
    assert missing == [], f"MCP mounts not covered: {missing}"


def test_every_tool_family_is_in_the_threat_model(threat_model: str) -> None:
    missing = sorted(name for name in tool_family_modules() if name not in threat_model)
    assert missing == [], f"tool families not covered: {missing}"


# -------------------------------------------------- the documents themselves


def test_the_threat_model_names_every_operating_mode(threat_model: str) -> None:
    for mode in ("locked", "cloud", "open"):
        assert f"`{mode}`" in threat_model, mode


#: A repo-relative path the threat model or the brief cites as enforcing a
#: claim, optionally pinned to one test (``path::test_name``).
_CITED_PATH_RE = re.compile(
    r"`((?:server|web|sdk)/[A-Za-z0-9_./-]+\.(?:py|tsx|ts|mjs)\b)(?:::([A-Za-z0-9_]+))?"
)


def cited_paths(text: str) -> list[tuple[str, str | None]]:
    """Every ``(path, symbol)`` the document cites, in order of appearance."""
    return [(match.group(1), match.group(2)) for match in _CITED_PATH_RE.finditer(text)]


def _dead_citations(text: str) -> list[str]:
    dead: list[str] = []
    for path, symbol in cited_paths(text):
        target = REPO_V3 / path
        if not target.is_file():
            dead.append(path)
            continue
        if symbol is not None and not re.search(
            rf"^\s*(?:async\s+)?def\s+{re.escape(symbol)}\b",
            target.read_text(encoding="utf-8"),
            re.M,
        ):
            dead.append(f"{path}::{symbol}")
    return dead


def test_the_threat_model_links_each_claim_to_code_or_a_test(threat_model: str) -> None:
    """SPEC-502 #1: "every claim linked to the enforcing code/test"."""
    assert threat_model.count("server/src/palaia_hub/") >= 20
    assert threat_model.count("server/tests/") >= 10


def test_every_path_the_threat_model_cites_exists(threat_model: str) -> None:
    """A link to a test that is not there proves nothing (issue #330): every
    `server/...`, `web/...` or `sdk/...` path the document names must be a
    real file, and a `path::test_name` pin must name a function in it."""
    cited = cited_paths(threat_model)
    assert len(cited) >= 60, "the citation scan found too little to be trusted"
    assert _dead_citations(threat_model) == []


def test_every_path_the_review_brief_cites_exists() -> None:
    """The brief inherits the threat model's claims; its links rot the same way."""
    text = REVIEW_BRIEF.read_text(encoding="utf-8")
    assert len(cited_paths(text)) >= 10
    assert _dead_citations(text) == []


def test_the_external_review_brief_exists_and_points_at_the_threat_model() -> None:
    assert REVIEW_BRIEF.is_file(), f"{REVIEW_BRIEF} is missing"
    text = REVIEW_BRIEF.read_text(encoding="utf-8")
    assert "threat-model.md" in text
    # The brief's whole job is to make a hired reviewer productive on day
    # one: what to run, where to look, and what is already accepted.
    for heading in ("## Scope", "## How to run everything locally", "## Accepted risks"):
        assert heading in text, heading


def test_the_security_policy_exists_and_says_how_to_report() -> None:
    assert SECURITY_POLICY.is_file(), f"{SECURITY_POLICY} is missing"
    text = SECURITY_POLICY.read_text(encoding="utf-8")
    assert "## Reporting a vulnerability" in text
    assert "## Supported versions" in text
    # The one monitored channel (the owner confirmed 2026-08-26 that no
    # security email inbox exists, so an "@" is exactly what must NOT be
    # promised here): GitHub's private vulnerability reporting.
    assert "private vulnerability reporting" in text, (
        "the security policy no longer names its reporting channel"
    )


def test_the_readme_links_the_security_policy() -> None:
    readme = (REPO_V3 / "README.md").read_text(encoding="utf-8")
    assert "SECURITY.md" in readme
