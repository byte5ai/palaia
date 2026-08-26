"""Format lint for the skill packages in ``v3/clients/skills`` (SPEC-207 #2).

The skills are the only palaia artifact that runs inside *someone else's*
agent loader. There is no server to reject a malformed one and no user to
see the error: a SKILL.md whose frontmatter a loader cannot parse is simply
never offered to the model, and the failure looks exactly like "the skill
did not help". So the shape is checked here, in CI, rather than discovered
in a transcript.

Two things get checked, and they are different in kind:

- **Frontmatter validity** — the agentskills contract (``name`` +
  ``description``, a portable key set, a directory name that matches the
  declared name). Mechanical, and a hard error.
- **Jargon** — SPEC-207's acceptance criterion "no jargon in user-facing
  text". Every word of a skill is read by a model that has never seen this
  repository: "the curator files it later" means nothing to it, while "an
  exact duplicate is recognised and dropped" does. Enforced as a word
  blocklist over the prose only — fenced blocks, inline code and table rows
  naming tools are stripped first, because ``work_memory_capture`` is a real
  identifier the skill has to be able to print. The blocklist itself lives
  in :mod:`palaia_addon_sdk.jargon` (SPEC-406: "one blocklist, one place" —
  the add-on SDK's ``validate`` command holds the canonical copy so a
  third-party author has no dependency on this repository's server package,
  and this lint imports it back).

Importable as a plain module (the pytest suite in ``test_skill_format.py``
drives it) and runnable by hand for a quick check::

    uv run python server/tests/clients/skill_lint.py
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from palaia_addon_sdk.jargon import find_jargon

#: ``v3/clients`` — the skill packages plus the Claude Code plugin wrapper.
CLIENTS_ROOT = Path(__file__).resolve().parents[3] / "clients"
SKILLS_ROOT = CLIENTS_ROOT / "skills"
PLUGIN_MANIFEST = CLIENTS_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_MANIFEST = CLIENTS_ROOT / ".claude-plugin" / "marketplace.json"

#: Short labels for the two manifests, so an :class:`Issue` reads as a path.
_PLUGIN_LABEL = ".claude-plugin/plugin.json"
_MARKET_LABEL = ".claude-plugin/marketplace.json"

#: The two keys every agentskills loader requires.
REQUIRED_KEYS: tuple[str, ...] = ("name", "description")

#: Keys a skill may declare. Deliberately small: anything outside this set is
#: a loader-specific extension, and a skill that only works in one client is
#: not what "provider-portable" means. ``allowed-tools`` is in the standard
#: but unused here on purpose — these skills must not narrow the tool surface
#: of the agent that loads them.
ALLOWED_KEYS: frozenset[str] = frozenset({"name", "description", "license", "allowed-tools"})

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME_LENGTH = 64
#: Loaders put every installed skill's description into the model's context at
#: once, so a long one is a tax on every unrelated turn.
MAX_DESCRIPTION_LENGTH = 1024
#: A description short enough to be only a title cannot say *when* to use the
#: skill, which is the only thing progressive disclosure has to go on.
MIN_DESCRIPTION_LENGTH = 60
#: Body length ceiling. Past this, a skill should be splitting detail into
#: reference files rather than growing its always-loaded half.
MAX_BODY_LINES = 300

_FRONTMATTER_RE = re.compile(r"\A---\n(?P<yaml>.*?)\n---\n(?P<body>.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class Issue:
    """One lint failure, addressed well enough to fix without re-running."""

    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


@dataclass(frozen=True)
class Skill:
    """A parsed SKILL.md: its declared frontmatter and its prose body."""

    directory: Path
    path: Path
    frontmatter: dict[str, Any]
    body: str

    @property
    def slug(self) -> str:
        return self.directory.name


def parse_skill(directory: Path) -> tuple[Skill | None, list[Issue]]:
    """Read ``directory/SKILL.md`` into a :class:`Skill`, or report why not."""
    path = directory / "SKILL.md"
    where = f"{directory.name}/SKILL.md"
    if not path.is_file():
        return None, [Issue(directory.name, "no SKILL.md — a skill package is that file")]
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return None, [
            Issue(where, "no YAML frontmatter — the file must open with a '---' fenced block")
        ]
    try:
        loaded = yaml.safe_load(match.group("yaml"))
    except yaml.YAMLError as exc:
        return None, [Issue(where, f"frontmatter is not valid YAML: {exc}")]
    if not isinstance(loaded, dict):
        return None, [Issue(where, "frontmatter must be a mapping of keys to values")]
    return Skill(directory=directory, path=path, frontmatter=loaded, body=match.group("body")), []


def lint_skill(skill: Skill) -> list[Issue]:
    """Every frontmatter and prose rule, applied to one parsed skill."""
    where = f"{skill.slug}/SKILL.md"
    issues: list[Issue] = []
    front = skill.frontmatter

    for key in REQUIRED_KEYS:
        value = front.get(key)
        if not isinstance(value, str) or not value.strip():
            issues.append(Issue(where, f"{key!r} is required and must be a non-empty string"))

    unknown = sorted(set(front) - ALLOWED_KEYS)
    if unknown:
        issues.append(
            Issue(
                where,
                f"unsupported frontmatter key(s) {unknown} — portable skills declare only "
                f"{sorted(ALLOWED_KEYS)}",
            )
        )

    name = front.get("name")
    if isinstance(name, str) and name.strip():
        if not NAME_RE.match(name):
            issues.append(
                Issue(where, f"name {name!r} must be lowercase words joined by single hyphens")
            )
        if len(name) > MAX_NAME_LENGTH:
            issues.append(
                Issue(where, f"name is {len(name)} chars, over the {MAX_NAME_LENGTH} max")
            )
        if name != skill.slug:
            issues.append(
                Issue(where, f"name {name!r} must match its directory name {skill.slug!r}")
            )

    description = front.get("description")
    if isinstance(description, str) and description.strip():
        length = len(description)
        if length > MAX_DESCRIPTION_LENGTH:
            issues.append(
                Issue(
                    where,
                    f"description is {length} chars, over the {MAX_DESCRIPTION_LENGTH} max",
                )
            )
        if length < MIN_DESCRIPTION_LENGTH:
            issues.append(
                Issue(
                    where,
                    f"description is {length} chars — too short to say when the skill applies, "
                    f"which is all a loader has to decide on",
                )
            )
        if "\n" in description:
            issues.append(Issue(where, "description must be a single line"))
        for word in find_jargon(description):
            issues.append(Issue(where, f"description uses in-house word {word!r}"))

    body = skill.body.strip()
    if not body:
        issues.append(Issue(where, "body is empty — frontmatter alone teaches nothing"))
    line_count = len(skill.body.splitlines())
    if line_count > MAX_BODY_LINES:
        issues.append(
            Issue(where, f"body is {line_count} lines, over the {MAX_BODY_LINES} max")
        )
    for word in find_jargon(skill.body):
        issues.append(Issue(where, f"body uses in-house word {word!r}"))

    return issues


def discover_skills(root: Path = SKILLS_ROOT) -> list[Path]:
    """Every skill package directory under ``root``, sorted."""
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))


def lint_skills(root: Path = SKILLS_ROOT) -> list[Issue]:
    """Lint every skill package under ``root``."""
    directories = discover_skills(root)
    if not directories:
        return [Issue(str(root), "no skill packages found")]
    issues: list[Issue] = []
    for directory in directories:
        skill, parse_issues = parse_skill(directory)
        issues.extend(parse_issues)
        if skill is not None:
            issues.extend(lint_skill(skill))
    return issues


def lint_plugin_wrapper() -> list[Issue]:
    """Check the Claude Code plugin manifest and the Phase-3 marketplace stub.

    The wrapper is what makes the same ``skills/`` directory installable as
    one unit (``claude --plugin-dir``, and a marketplace entry later), so it
    has to stay consistent with what is actually on disk — a manifest listing
    a plugin whose source does not carry the skills is the kind of thing that
    is only noticed at distribution time.
    """
    issues: list[Issue] = []

    if not PLUGIN_MANIFEST.is_file():
        issues.append(Issue(_PLUGIN_LABEL, "missing"))
    else:
        try:
            plugin = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append(Issue(_PLUGIN_LABEL, f"not valid JSON: {exc}"))
            plugin = None
        if isinstance(plugin, dict):
            for key in ("name", "description", "version"):
                if not str(plugin.get(key, "")).strip():
                    issues.append(Issue(_PLUGIN_LABEL, f"{key!r} is required"))
            name = plugin.get("name")
            if isinstance(name, str) and not NAME_RE.match(name):
                issues.append(
                    Issue(_PLUGIN_LABEL, f"name {name!r} must be a hyphenated slug")
                )
            description = plugin.get("description")
            if isinstance(description, str):
                for word in find_jargon(description):
                    issues.append(
                        Issue(_PLUGIN_LABEL, f"description uses in-house word {word!r}")
                    )

    if not MARKETPLACE_MANIFEST.is_file():
        issues.append(Issue(_MARKET_LABEL, "missing"))
        return issues
    try:
        market = json.loads(MARKETPLACE_MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [*issues, Issue(_MARKET_LABEL, f"not valid JSON: {exc}")]
    if not isinstance(market, dict):
        return [*issues, Issue(_MARKET_LABEL, "must be a JSON object")]
    if not str(market.get("name", "")).strip():
        issues.append(Issue(_MARKET_LABEL, "'name' is required"))
    plugins = market.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        issues.append(Issue(_MARKET_LABEL, "'plugins' must be a non-empty list"))
        return issues
    for entry in plugins:
        if not isinstance(entry, dict):
            issues.append(Issue(_MARKET_LABEL, "each plugin must be an object"))
            continue
        source = str(entry.get("source", ""))
        if not source:
            issues.append(
                Issue(_MARKET_LABEL, f"plugin {entry.get('name')!r} has no source")
            )
            continue
        resolved = (CLIENTS_ROOT / source).resolve()
        if not (resolved / ".claude-plugin" / "plugin.json").is_file():
            issues.append(
                Issue(
                    ".claude-plugin/marketplace.json",
                    f"source {source!r} has no .claude-plugin/plugin.json",
                )
            )
        if not (resolved / "skills").is_dir():
            issues.append(
                Issue(_MARKET_LABEL, f"source {source!r} carries no skills/")
            )
    return issues


def lint_all() -> list[Issue]:
    """Every check this module has: the skills plus the plugin wrapper."""
    return [*lint_skills(), *lint_plugin_wrapper()]


def main() -> int:
    issues = lint_all()
    for issue in issues:
        print(issue, file=sys.stderr)
    if issues:
        print(f"\n{len(issues)} problem(s) in {CLIENTS_ROOT}", file=sys.stderr)
        return 1
    print(f"skill format OK ({len(discover_skills())} package(s))")
    return 0


if __name__ == "__main__":  # pragma: no cover - hand-run entry point
    raise SystemExit(main())
