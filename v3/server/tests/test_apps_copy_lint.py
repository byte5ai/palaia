"""No jargon in the two MCP Apps this SPEC adds (SPEC-405 deliverable #5:
"jargon-free copy (lint, both screens and both apps' visible text)").

``docs/design/system.md`` §3 rule 0 is binding, the same rule
``test_signin_copy_lint.py`` already lints the sign-in surface against and
``web/src/routes/Exposure.test.tsx`` lints the exposure wizard against: no
protocol name, standard, acronym, transport or implementation word in a
label, heading, button, badge, status line or option name.

Scope: the session-monitor app (:mod:`palaia_hub.gateway.apps.team_app`)
and the stash browser app (:mod:`palaia_hub.gateway.apps.stash_browser_app`)
— this SPEC's own two apps. The pre-existing apps (hub status, marketplace,
recall explorer, review queue) are SPEC-208/304's copy, out of scope here.

Both apps build their visible markup at runtime, inside their own
``_SCRIPT_JS`` string (there is no server-rendered text beyond the page
``<title>`` and a "Loading…" placeholder — see
:mod:`palaia_hub.gateway.apps.shell`). So this scans each app's whole
script source plus its title for the banned terms — a coarser net than
scanning rendered DOM nodes (as the dashboard's own vitest lints do), but
sufficient here: none of these scripts embed a banned term inside a class
name, attribute, or comment either, so a plain source scan and a
rendered-DOM scan would catch exactly the same violations.
"""

from __future__ import annotations

import re

BANNED = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bmcp\b",
        r"\boauth\b",
        r"\boidc\b",
        r"\bjwt\b",
        r"\bpkce\b",
        r"\bcimd\b",
        r"\bdcr\b",
        r"\bttl\b",
        r"\bcsrf\b",
        r"\basgi\b",
        r"\brfc\s*\d",
        r"\bapi\b",
        r"\bjson\b",
        r"\buuid\b",
        r"\bsqlite\b",
        r"\bbearer\b",
    )
]


def _assert_plain(text: str, *, source: str) -> None:
    for pattern in BANNED:
        assert not pattern.search(text), f"jargon {pattern.pattern!r} in {source}: {text!r}"


def test_the_session_monitor_app_has_no_jargon_in_its_copy() -> None:
    from palaia_hub.gateway.apps.team_app import _SCRIPT_JS, _TITLE

    _assert_plain(_TITLE, source="team_app._TITLE")
    _assert_plain(_SCRIPT_JS, source="team_app._SCRIPT_JS")


def test_the_stash_browser_app_has_no_jargon_in_its_copy() -> None:
    from palaia_hub.gateway.apps.stash_browser_app import _SCRIPT_JS, _TITLE

    _assert_plain(_TITLE, source="stash_browser_app._TITLE")
    _assert_plain(_SCRIPT_JS, source="stash_browser_app._SCRIPT_JS")
