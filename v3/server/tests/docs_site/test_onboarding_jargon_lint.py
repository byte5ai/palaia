"""SPEC-504 acceptance criterion "jargon lint green", for the onboarding
page specifically.

``test_docs_jargon_lint.py`` (SPEC-503) only scans ``.md`` files under
``src/content/docs`` — the onboarding page is a custom Astro component, so it
needs its own coverage rather than falling out of that discovery loop by
accident.

The onboarding page is now localized (en/de/fr/es/it — the languages the
palaia.ai homepage offers) and its visible English prose lives in
``src/i18n/onboarding/en.json``, rendered by ``src/components/OnboardingBody.astro``.
So this checks the English dictionary: every string a reader actually sees. The
install commands are read from ``v3/deploy`` at build time and never appear in
the dictionary, so there is no developer-facing code here to strip — the whole
file is prose (with the occasional inline ``<code>``/``<a>`` HTML, which
``find_jargon`` tolerates exactly as it did in the rendered template before).
Non-English dictionaries are not linted: the jargon rules are English.
"""

from __future__ import annotations

import json
from pathlib import Path

from palaia_addon_sdk.jargon import find_jargon

# v3/server/tests/docs_site -> v3/server/tests -> v3/server -> v3 -> v3/site/docs
DOCS_ROOT = Path(__file__).resolve().parents[3] / "site" / "docs"
ONBOARDING_EN = DOCS_ROOT / "src" / "i18n" / "onboarding" / "en.json"
ONBOARDING_PAGE = DOCS_ROOT / "src" / "pages" / "onboarding.astro"


def _all_strings(value: object) -> list[str]:
    """Every string leaf in the (nested) dictionary — all the visible prose."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _all_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _all_strings(v)]
    return []


def test_onboarding_page_exists() -> None:
    assert ONBOARDING_PAGE.is_file(), f"no onboarding page at {ONBOARDING_PAGE}"
    assert ONBOARDING_EN.is_file(), f"no English dictionary at {ONBOARDING_EN}"


def test_onboarding_english_copy_has_no_jargon() -> None:
    strings = _all_strings(json.loads(ONBOARDING_EN.read_text(encoding="utf-8")))
    assert strings, "the English onboarding dictionary has no strings to check"

    text = "\n".join(strings)
    hits = find_jargon(text)
    assert not hits, (
        f"the onboarding page's English copy uses in-house word(s) {hits} — wrap the "
        f"term as code, or rephrase in plain language (edit src/i18n/onboarding/en.json)"
    )
