"""Issue #400: the Dockerfile's ignore file admits exactly what the
Dockerfile copies — a bare `!v3` used to re-include the whole tree."""

from __future__ import annotations

import re
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[3] / "deploy"
DOCKERFILE = DEPLOY / "Dockerfile"
IGNORE = DEPLOY / "Dockerfile.dockerignore"


def _copy_sources() -> list[str]:
    sources: list[str] = []
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        if not line.startswith("COPY ") or "--from=" in line:
            continue
        parts = line.split()[1:-1]  # `COPY <src...> <dest>`
        sources.extend(part for part in parts if part.startswith("v3/"))
    return sources


def _rules() -> list[str]:
    return [
        line.strip()
        for line in IGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def test_no_rule_readmits_the_whole_v3_tree() -> None:
    assert "!v3" not in _rules()
    assert "!v3/" not in _rules()


def test_every_copied_source_is_readmitted() -> None:
    admitted = [rule[1:].rstrip("/") for rule in _rules() if rule.startswith("!")]
    for source in _copy_sources():
        normalized = source.rstrip("/")
        assert any(normalized == rule or normalized.startswith(rule + "/") for rule in admitted), (
            f"Dockerfile copies {source} but Dockerfile.dockerignore does not admit it"
        )


def test_heavy_local_trees_stay_out() -> None:
    rules = _rules()
    assert rules[0] == "*"
    for heavy in ("v3/web/node_modules", "v3/server/.venv"):
        assert heavy in rules
    # `v3/.venv` and `v3/site/docs/node_modules` are excluded by `*` alone:
    # nothing readmits `v3/.venv` or `v3/site`.
    assert not any(re.match(r"^!v3/(\.venv|site)(/|$)", rule) for rule in rules)
