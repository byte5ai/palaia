"""The consent page's one-line-per-scope wording (issue #328).

Every hub-level scope family must read as a plain sentence, not as its raw
``family:permission`` string — the owner is deciding what an AI tool may do,
and ``telegram:send`` on its own does not say "this can message people from
your bots". Issue #439 added the Telegram family to the page.
"""

from __future__ import annotations

import pytest

from palaia_hub.oauth.routes import _describe_scope


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        ("vault:work:read", "Read the “work” memory"),
        ("vault:work:write", "Save into the “work” memory"),
        ("stash:write", "Change the shared scratch space"),
        ("directory:read", "Read the session directory"),
        ("messenger:send", "Send through the messenger"),
        ("telegram:read", "Read your Telegram bots"),
        ("telegram:send", "Send through your Telegram bots"),
    ],
)
def test_every_scope_family_reads_as_a_sentence(scope: str, expected: str) -> None:
    assert _describe_scope(scope) == expected
