"""Drift check for ``v3/clients/skills/palaia-install`` (issue #449).

The install skill walks someone through setup by *reading* what
``v3/deploy`` ships — the cloud-init file, the ``get.palaia.ai`` installer,
the deploy README and ``v3/VERSION`` — rather than restating it. That is the
same "extract, don't copy" rule the onboarding page follows
(``v3/site/docs/scripts/lib/deploy-snippets.mjs`` and
``v3/site/docs/tests/onboarding.test.ts``). A skill is prose, though, and it
still has to *quote* a few things: the command's shape, the key line to edit,
the log file to open, the lines that log prints. Each such quote is a promise
about a file that can change underneath it, so this module checks every one:

- every inline code span and fenced line in the skill is either found
  verbatim in ``v3/deploy``, a placeholder form (``<their-key>``) of
  something that is, a ``get.palaia.ai`` command that reduces to the exact
  command ``get-palaia.sh``'s header documents, an existing repo path or raw
  GitHub URL — or one of a short, reasoned list of literals that are not
  palaia's to ship (a generic ``tail``, Tailscale's key prefixes), whose
  palaia-specific parts are still checked;
- the image tag is never hardcoded — the skill derives it from
  ``v3/VERSION`` the same way the onboarding page and
  ``test_version_drift.py`` do;
- the key substitution the skill prescribes, applied to the real
  ``cloud-init.yaml``, yields a cloud-config that still parses and whose
  "forgot the key" guard lets the real key through — executed, not just
  pattern-matched, because the naive replace-every-placeholder edit silently
  produces a server that stops on first boot.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from .skill_lint import CLIENTS_ROOT, parse_skill

V3_ROOT = CLIENTS_ROOT.parent
REPO_ROOT = V3_ROOT.parent
DEPLOY_ROOT = V3_ROOT / "deploy"
CLOUD_INIT_PATH = DEPLOY_ROOT / "cloud-init.yaml"
GET_PALAIA_PATH = DEPLOY_ROOT / "get-palaia.sh"
SKILL_DIR = CLIENTS_ROOT / "skills" / "palaia-install"

#: What the skill may quote from. The install-path files it tells the
#: assistant to read, plus ``install.sh`` (the flag list both of them mirror).
_CORPUS_FILES = ("cloud-init.yaml", "get-palaia.sh", "README.md", "install.sh")

#: The raw-GitHub prefix the skill sends an assistant without a checkout to.
_RAW_PREFIX = "https://raw.githubusercontent.com/byte5ai/palaia/main/"

#: Same header regex ``deploy-snippets.mjs``'s ``loadGetPalaiaCommand`` uses.
_GET_PALAIA_HEADER_RE = re.compile(r"^#\s+(curl\s.*get\.palaia\.ai.*)$", re.MULTILINE)

#: The one edit the skill prescribes to the cloud-init file, and its result.
_KEY_LINE = 'TAILSCALE_AUTH_KEY="tskey-REPLACE_ME"'
_KEY_LINE_FILLED = 'TAILSCALE_AUTH_KEY="<their-key>"'
_SETUP_SCRIPT_PATH = "/opt/palaia/cloud-init-setup.sh"
#: How the setup script's "forgot the key" guard opens (found by shape, not
#: by the placeholder, so a wrongly edited copy is still located).
_GUARD_OPENING = 'if [ "${TAILSCALE_AUTH_KEY}" = '

#: Literals the skill quotes that are not palaia's own to ship, so they
#: cannot be found in ``v3/deploy`` — each with the reason it may stand.
#: Their palaia-specific parts (paths, container name) are still anchored,
#: by :func:`_anchor_tokens`.
_NOT_FROM_DEPLOY: dict[str, str] = {
    "tskey-auth-": "Tailscale's own prefix for an auth key — not a palaia literal",
    "tskey-api-": "Tailscale's own prefix for an API access token — not a palaia literal",
    "sudo tail -n 50 /var/log/cloud-init-output.log": (
        "a generic way to read the log; the path itself is anchored below"
    ),
    "sudo docker logs --tail 50 palaia-hub": (
        "a generic way to read a container's log; the container name is anchored below"
    ),
}

#: Tokens inside a quote that name something palaia ships: absolute paths,
#: the installer's environment variables, the container/host name, the port.
_ANCHOR_RE = re.compile(r"(/(?:var|opt|etc)/[\w./-]+|\bPALAIA_[A-Z_]+|\bpalaia-hub\b|\b8420\b)")

_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_FENCE_RE = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"<[a-z][a-z-]*>")
_CURL_ASSIGNMENT_RE = re.compile(r"\|\s*((?:[A-Z_]+=\S+\s+)*)sh\s*$")


def _skill_body() -> str:
    skill, issues = parse_skill(SKILL_DIR)
    assert issues == [], issues
    assert skill is not None
    return skill.body


def _corpus() -> str:
    return "\n".join((DEPLOY_ROOT / name).read_text(encoding="utf-8") for name in _CORPUS_FILES)


def _quoted_literals(body: str) -> list[str]:
    """Every inline code span and every non-empty fenced line in the body."""
    literals: list[str] = []
    for fence in _FENCE_RE.findall(body):
        literals.extend(line.strip() for line in fence.splitlines() if line.strip())
    without_fences = _FENCE_RE.sub("", body)
    literals.extend(span.strip() for span in _INLINE_CODE_RE.findall(without_fences))
    return literals


def _header_command() -> str:
    match = _GET_PALAIA_HEADER_RE.search(GET_PALAIA_PATH.read_text(encoding="utf-8"))
    assert match, (
        "get-palaia.sh's header no longer documents a `curl … get.palaia.ai` command — "
        "update this extractor (and deploy-snippets.mjs's) to match, never hand-copy it"
    )
    return match.group(1).strip()


def _placeholder_pattern(literal: str) -> re.Pattern[str]:
    pieces = _PLACEHOLDER_RE.split(literal)
    return re.compile(r"\S+".join(re.escape(piece) for piece in pieces))


def _anchor_tokens(literal: str) -> list[str]:
    return _ANCHOR_RE.findall(literal)


def _check_literal(literal: str, corpus: str, header: str) -> str | None:
    """``None`` if ``literal`` is grounded in what ships, else why it is not."""
    if literal in corpus:
        return None
    if "get.palaia.ai" in literal:
        match = _CURL_ASSIGNMENT_RE.search(literal)
        if match is None:
            return "a get.palaia.ai command that does not end in `| [VAR=value ...] sh`"
        reduced = literal[: match.start()] + "| sh"
        if reduced != header:
            return f"reduces to {reduced!r}, but get-palaia.sh's header says {header!r}"
        for assignment in match.group(1).split():
            name = assignment.split("=", 1)[0]
            if f"${{{name}" not in corpus:
                return f"sets {name}, which get-palaia.sh never reads"
        return None
    if literal.startswith(_RAW_PREFIX):
        relative = literal[len(_RAW_PREFIX) :]
        if not (REPO_ROOT / relative).exists():
            return f"raw GitHub URL for {relative!r}, which is not in the repository"
        return None
    if literal.startswith("v3/"):
        if not (REPO_ROOT / literal).exists():
            return f"names {literal!r}, which does not exist"
        return None
    if _PLACEHOLDER_RE.search(literal):
        if _placeholder_pattern(literal).search(corpus) is None:
            return "a placeholder form that matches nothing in v3/deploy"
        return None
    if literal in _NOT_FROM_DEPLOY:
        missing = [token for token in _anchor_tokens(literal) if token not in corpus]
        if missing:
            return f"its palaia-specific part(s) {missing} are not in v3/deploy"
        return None
    return "not found in v3/deploy and not in this test's reasoned allow-list"


def test_every_quoted_literal_matches_what_ships() -> None:
    body = _skill_body()
    corpus = _corpus()
    header = _header_command()
    literals = _quoted_literals(body)
    assert literals, "found no quoted literals in the install skill — the extractor broke"

    problems = [
        f"`{literal}`: {why}"
        for literal in dict.fromkeys(literals)
        if (why := _check_literal(literal, corpus, header)) is not None
    ]
    assert not problems, (
        "palaia-install/SKILL.md quotes something that no longer matches v3/deploy:\n  "
        + "\n  ".join(problems)
    )


def test_allow_list_entries_are_still_used() -> None:
    """An allow-list entry the skill no longer quotes is dead weight that
    would quietly excuse the next, different use of the same text."""
    literals = set(_quoted_literals(_skill_body()))
    stale = sorted(set(_NOT_FROM_DEPLOY) - literals)
    assert not stale, f"_NOT_FROM_DEPLOY entries the skill no longer quotes: {stale}"


def test_skill_points_at_every_file_it_derives_from() -> None:
    literals = set(_quoted_literals(_skill_body()))
    for relative in (
        "v3/deploy/cloud-init.yaml",
        "v3/deploy/get-palaia.sh",
        "v3/deploy/README.md",
        "v3/VERSION",
    ):
        assert relative in literals, f"the skill no longer tells the assistant to read {relative}"
    assert _RAW_PREFIX in literals


def test_the_get_palaia_command_is_the_headers_own() -> None:
    """The skill's bare command must be the header's, character for character
    — the same thing the onboarding page shows via loadGetPalaiaCommand()."""
    header = _header_command()
    assert header in _quoted_literals(_skill_body())


def test_the_image_tag_is_derived_from_version_not_hardcoded() -> None:
    """Issue #449: "the image tag must follow v3/VERSION". The skill names no
    concrete image tag at all; it tells the assistant the rule (pre-release →
    `beta`, else `stable`), leaves cloud-init.yaml's pinned tag alone — which
    ``test_unattended_install_paths_pin_the_channel_matching_version``
    already forces to match VERSION — and adds ``PALAIA_CHANNEL=beta`` to the
    installer line for a pre-release, exactly as the onboarding page does."""
    body = _skill_body()
    assert not re.search(r"palaia-hub:[A-Za-z0-9]", body), (
        "the skill hardcodes an image tag — it must follow v3/VERSION instead"
    )
    literals = _quoted_literals(body)
    assert "v3/VERSION" in literals
    assert "PALAIA_CHANNEL=beta" in literals

    get_palaia = GET_PALAIA_PATH.read_text(encoding="utf-8")
    assert 'CHANNEL="${PALAIA_CHANNEL:-stable}"' in get_palaia
    assert "ghcr.io/byte5ai/palaia-hub:${CHANNEL}" in get_palaia

    # The pre-release form the skill shows is the header command with the
    # variable inserted before `sh` — the same transform OnboardingBody.astro
    # applies when isPrerelease().
    header = _header_command()
    beta_lines = [line for line in literals if "PALAIA_CHANNEL=beta" in line and "curl" in line]
    assert beta_lines, "the skill no longer shows the pre-release installer line"
    for line in beta_lines:
        assert line.startswith(header.removesuffix("sh").rstrip()), line
        assert line.endswith("PALAIA_CHANNEL=beta sh"), line


# --- the key substitution, applied to the real file ----------------------


def _substitute(cloud_init: str, key: str) -> str:
    """The edit Step 2a prescribes: replace the key line's exact text."""
    return cloud_init.replace(_KEY_LINE, _KEY_LINE_FILLED.replace("<their-key>", key))


def _setup_script(cloud_init: str) -> str:
    document = yaml.safe_load(cloud_init)
    assert isinstance(document, dict)
    for entry in document.get("write_files", []):
        if entry.get("path") == _SETUP_SCRIPT_PATH:
            return str(entry["content"])
    raise AssertionError(f"cloud-init.yaml no longer writes {_SETUP_SCRIPT_PATH}")


def _guard_prefix(script: str) -> str:
    """The script up to and including the "forgot the key" guard's ``fi``."""
    lines = script.splitlines()
    guard = next(
        (i for i, line in enumerate(lines) if line.lstrip().startswith(_GUARD_OPENING)),
        None,
    )
    assert guard is not None, "the setup script no longer checks for the unfilled key"
    end = next(i for i in range(guard, len(lines)) if lines[i].strip() == "fi")
    return "\n".join(lines[: end + 1]) + "\n"


def test_the_skill_prescribes_exactly_this_edit() -> None:
    literals = _quoted_literals(_skill_body())
    assert _KEY_LINE in literals
    assert _KEY_LINE_FILLED in literals


def test_the_substituted_file_is_a_valid_cloud_config() -> None:
    template = CLOUD_INIT_PATH.read_text(encoding="utf-8")
    filled = _substitute(template, "tskey-auth-kEXAMPLE1CNTRL-0123456789abcdef")

    assert filled.startswith("#cloud-config")
    assert yaml.safe_load(filled) is not None
    # Only the key changed: the documented line was actually present, and
    # every other line is untouched.
    changed = [
        (old, new)
        for old, new in zip(template.splitlines(), filled.splitlines(), strict=True)
        if old != new
    ]
    assert changed, f"{_KEY_LINE!r} is not in cloud-init.yaml any more"
    assert all(_KEY_LINE in old for old, _ in changed), changed

    script = _setup_script(filled)
    assert 'TAILSCALE_AUTH_KEY="tskey-auth-kEXAMPLE1CNTRL-0123456789abcdef"' in script
    # The guard still compares against the placeholder, not the real key.
    assert '= "tskey-REPLACE_ME" ]' in script


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
def test_the_guard_passes_the_substituted_key_and_stops_the_rest(tmp_path: Path) -> None:
    """Run the real guard: the skill's edit must pass it; the unedited file,
    and the naive "replace every placeholder" edit, must both be stopped."""
    template = CLOUD_INIT_PATH.read_text(encoding="utf-8")
    key = "tskey-auth-kEXAMPLE1CNTRL-0123456789abcdef"
    cases = {
        "skill's edit": (_substitute(template, key), 0),
        "unedited": (template, 1),
        "replace-every-placeholder": (template.replace("tskey-REPLACE_ME", key), 1),
    }
    for label, (text, expected) in cases.items():
        script = tmp_path / f"{label.replace(' ', '_')}.sh"
        script.write_text(_guard_prefix(_setup_script(text)), encoding="utf-8")
        result = subprocess.run(
            ["bash", str(script)], capture_output=True, text=True, timeout=30, check=False
        )
        assert result.returncode == expected, (label, result.stdout, result.stderr)
