"""SPEC-503 deliverable #3 / acceptance criterion "jargon lint green over
all prose": the docs site's every page — hand-written and generated alike
— run through the same shared blocklist the skill packages are linted
against (:mod:`palaia_addon_sdk.jargon`, see
``server/tests/clients/skill_lint.py``'s docstring for why that module
owns the canonical copy).

The blocklist's own code/table/fence stripping (``strip_code``) is what
makes this workable at all: a page that has to *talk about* the connection
protocol (the developers page) or paste a real connect command (every
generated client page) marks that text as code, and code is exempt. What
is not exempt is a page saying, in a sentence a reader has to parse, a word
that means something inside this repository and nothing to them.

Scans every Markdown file actually shipped in the site, not a fixed list —
a new page with jargon in it fails this the same way an existing one would.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from palaia_addon_sdk.jargon import find_jargon

# v3/server/tests/docs_site -> v3/server/tests -> v3/server -> v3 -> v3/site/docs
DOCS_CONTENT_ROOT = (
    Path(__file__).resolve().parents[3] / "site" / "docs" / "src" / "content" / "docs"
)


def discover_pages(root: Path = DOCS_CONTENT_ROOT) -> list[Path]:
    """Every Markdown page under the docs site's content root, sorted."""
    if not root.is_dir():
        return []
    return sorted(root.rglob("*.md"))


def test_docs_site_content_root_exists() -> None:
    """A red, obvious failure if the site moves or was never built here,
    rather than this whole module silently reporting "0 pages, all clean"."""
    assert DOCS_CONTENT_ROOT.is_dir(), f"no docs content directory at {DOCS_CONTENT_ROOT}"
    pages = discover_pages()
    assert len(pages) >= 10, f"expected at least 10 docs pages, found {len(pages)}"


@pytest.mark.parametrize(
    "page",
    discover_pages(),
    ids=lambda p: str(p.relative_to(DOCS_CONTENT_ROOT)),
)
def test_docs_page_has_no_jargon(page: Path) -> None:
    text = page.read_text(encoding="utf-8")
    hits = find_jargon(text)
    assert not hits, (
        f"{page.relative_to(DOCS_CONTENT_ROOT)} uses in-house word(s) {hits} outside a code "
        f"span/fence/table row — wrap the term as code, or rephrase in plain language"
    )
