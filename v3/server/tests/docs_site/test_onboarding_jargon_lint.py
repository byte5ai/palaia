"""SPEC-504 acceptance criterion "jargon lint green", for the onboarding
page specifically.

``test_docs_jargon_lint.py`` (SPEC-503) only scans ``.md`` files under
``src/content/docs`` — the onboarding page is a custom Astro component
(``src/pages/onboarding.astro``, not a content-collection entry; see that
file's own docstring for why), so it needs its own coverage rather than
falling out of that discovery loop by accident.

Only the rendered template is checked, not the whole file: the frontmatter
script fence (``---...---``) and the ``<script>``/``<style>`` blocks are
developer-facing code (comments naming this SPEC, CSS selectors, a
``dataset.copyTarget`` property access) that a reader never sees — the
same reasoning ``find_jargon``'s own ``strip_code`` already applies to
Markdown code fences, extended here to this file's two other "not prose"
regions.
"""

from __future__ import annotations

import re
from pathlib import Path

from palaia_addon_sdk.jargon import find_jargon

# v3/server/tests/docs_site -> v3/server/tests -> v3/server -> v3 -> v3/site/docs
ONBOARDING_PAGE = (
    Path(__file__).resolve().parents[3]
    / "site"
    / "docs"
    / "src"
    / "pages"
    / "onboarding.astro"
)

_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
_SCRIPT_RE = re.compile(r"<script\b.*?</script>", re.DOTALL)
_STYLE_RE = re.compile(r"<style\b.*?</style>", re.DOTALL)
# `<StarlightPage frontmatter={{ title: ..., template: "splash" }}>` — an
# opening tag's own prop object, never rendered text (Starlight reads
# `frontmatter`/`template` as component configuration; neither word reaches
# the page). Not a Markdown code fence `find_jargon`'s own `strip_code`
# would catch, so stripped here the same way the script/style blocks above
# are: syntax a reader never sees, not prose.
_COMPONENT_OPEN_TAG_RE = re.compile(r"<StarlightPage\b.*?}}>", re.DOTALL)


def _rendered_template(source: str) -> str:
    """The part of an .astro file an end reader actually sees."""
    without_frontmatter = _FRONTMATTER_RE.sub("", source, count=1)
    without_script = _SCRIPT_RE.sub("", without_frontmatter)
    without_style = _STYLE_RE.sub("", without_script)
    return _COMPONENT_OPEN_TAG_RE.sub("", without_style)


def test_onboarding_page_exists() -> None:
    assert ONBOARDING_PAGE.is_file(), f"no onboarding page at {ONBOARDING_PAGE}"


def test_onboarding_page_template_has_no_jargon() -> None:
    source = ONBOARDING_PAGE.read_text(encoding="utf-8")
    template = _rendered_template(source)
    assert template.strip(), "stripping frontmatter/script/style left nothing to check"

    hits = find_jargon(template)
    assert not hits, (
        f"onboarding.astro's rendered template uses in-house word(s) {hits} — wrap the term "
        f"as code, or rephrase in plain language"
    )
