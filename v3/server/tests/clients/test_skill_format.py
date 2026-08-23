"""The CI gate for ``v3/clients`` (SPEC-207 acceptance: "skills pass format
lint; no jargon in user-facing text").

Two halves. The first runs :mod:`skill_lint` over the real, shipped skill
packages — that is the gate. The second tests the linter itself against
synthetic bad skills, because a lint that silently passes everything is
worse than no lint: it would let a malformed SKILL.md ship while reporting
green, and a loader's reaction to a malformed skill is to ignore it without
saying anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from . import skill_lint
from .skill_lint import (
    CLIENTS_ROOT,
    Issue,
    discover_skills,
    find_jargon,
    lint_all,
    lint_plugin_wrapper,
    lint_skills,
    parse_skill,
)

GOOD_FRONTMATTER = """---
name: sample-skill
description: Says plainly when a model should reach for this skill, and what it does once it has.
---

# Sample

Body text that teaches something.
"""


def _write(root: Path, slug: str, text: str) -> Path:
    directory = root / slug
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(text, encoding="utf-8")
    return directory


# --- the gate: the shipped packages ------------------------------------


def test_shipped_skills_and_plugin_wrapper_pass_lint() -> None:
    issues = lint_all()
    assert issues == [], "\n".join(str(issue) for issue in issues)


def test_both_spec_207_skill_packages_are_present() -> None:
    slugs = {directory.name for directory in discover_skills()}
    assert {"palaia-memory", "palaia-capture"} <= slugs, slugs


def test_capture_skill_is_the_smaller_one() -> None:
    """``palaia-capture`` exists for constrained agents (SPEC-207 #1).

    If it ever grew to the size of the core skill it would have no reason to
    exist, so its size relative to the core one is the thing worth asserting
    rather than an absolute line count.
    """
    core, _ = parse_skill(CLIENTS_ROOT / "skills" / "palaia-memory")
    minimal, _ = parse_skill(CLIENTS_ROOT / "skills" / "palaia-capture")
    assert core is not None and minimal is not None
    core_lines = len(core.body.splitlines())
    minimal_lines = len(minimal.body.splitlines())
    assert minimal_lines < core_lines / 2, (minimal_lines, core_lines)


def test_every_skill_carries_per_model_guidance() -> None:
    """SPEC-207 #1: "both carry per-model guidance where behavior differs".

    Written with the format spec's own variant marker (``[anthropic]``,
    ``[openai]``, ...) so the prose and the notes in the memory itself read
    the same way.
    """
    for directory in discover_skills():
        skill, issues = parse_skill(directory)
        assert issues == [], issues
        assert skill is not None
        assert "## Per-model notes" in skill.body, directory.name
        families = [f"[{name}]" for name in ("anthropic", "openai", "google")]
        present = [family for family in families if family in skill.body]
        assert len(present) >= 2, (directory.name, present)


def test_skills_name_the_four_capture_fields() -> None:
    """The 4-field contract is the one thing a capture cannot be composed
    without (format spec §7 / SPEC-107's mandatory fields)."""
    for directory in discover_skills():
        skill, _ = parse_skill(directory)
        assert skill is not None
        lowered = skill.body.lower()
        for field in ("what it concerns", "why keep it", "content", "source"):
            assert field in lowered, (directory.name, field)


# --- the linter itself -------------------------------------------------


def test_missing_skill_md_is_reported(tmp_path: Path) -> None:
    (tmp_path / "empty-skill").mkdir()
    issues = lint_skills(tmp_path)
    assert any("no SKILL.md" in issue.message for issue in issues), issues


def test_empty_root_is_reported(tmp_path: Path) -> None:
    assert lint_skills(tmp_path) == [Issue(str(tmp_path), "no skill packages found")]


def test_missing_frontmatter_is_reported(tmp_path: Path) -> None:
    _write(tmp_path, "no-front", "# Just a heading\n")
    issues = lint_skills(tmp_path)
    assert any("no YAML frontmatter" in issue.message for issue in issues), issues


def test_unparseable_frontmatter_is_reported(tmp_path: Path) -> None:
    _write(tmp_path, "bad-yaml", "---\nname: [unclosed\n---\nbody\n")
    issues = lint_skills(tmp_path)
    assert any("not valid YAML" in issue.message for issue in issues), issues


@pytest.mark.parametrize("key", ["name", "description"])
def test_missing_required_key_is_reported(tmp_path: Path, key: str) -> None:
    text = GOOD_FRONTMATTER.replace(f"{key}:", f"x-{key}:")
    _write(tmp_path, "sample-skill", text)
    issues = lint_skills(tmp_path)
    assert any(f"{key!r} is required" in issue.message for issue in issues), issues


def test_unsupported_key_is_reported(tmp_path: Path) -> None:
    text = GOOD_FRONTMATTER.replace("license:", "x:").replace(
        "---\nname:", "---\nmodel: opus\nname:"
    )
    _write(tmp_path, "sample-skill", text)
    issues = lint_skills(tmp_path)
    assert any("unsupported frontmatter key" in issue.message for issue in issues), issues


def test_name_must_match_directory(tmp_path: Path) -> None:
    _write(tmp_path, "other-name", GOOD_FRONTMATTER)
    issues = lint_skills(tmp_path)
    assert any("must match its directory name" in issue.message for issue in issues), issues


def test_name_must_be_a_slug(tmp_path: Path) -> None:
    _write(tmp_path, "Sample_Skill", GOOD_FRONTMATTER.replace("sample-skill", "Sample_Skill"))
    issues = lint_skills(tmp_path)
    assert any("lowercase words joined by single hyphens" in issue.message for issue in issues)


def test_short_description_is_reported(tmp_path: Path) -> None:
    text = GOOD_FRONTMATTER.replace(
        "Says plainly when a model should reach for this skill, and what it does once it has.",
        "Does memory things.",
    )
    _write(tmp_path, "sample-skill", text)
    issues = lint_skills(tmp_path)
    assert any("too short to say when the skill applies" in issue.message for issue in issues)


def test_overlong_description_is_reported(tmp_path: Path) -> None:
    long_text = "x " * 700
    text = GOOD_FRONTMATTER.replace(
        "Says plainly when a model should reach for this skill, and what it does once it has.",
        long_text.strip(),
    )
    _write(tmp_path, "sample-skill", text)
    issues = lint_skills(tmp_path)
    assert any("over the" in issue.message and "max" in issue.message for issue in issues), issues


def test_empty_body_is_reported(tmp_path: Path) -> None:
    text = GOOD_FRONTMATTER.split("\n# Sample")[0] + "\n"
    _write(tmp_path, "sample-skill", text)
    issues = lint_skills(tmp_path)
    assert any("body is empty" in issue.message for issue in issues), issues


def test_jargon_in_body_is_reported(tmp_path: Path) -> None:
    text = GOOD_FRONTMATTER + "\nThe curator files it into the vault later.\n"
    _write(tmp_path, "sample-skill", text)
    issues = lint_skills(tmp_path)
    words = {issue.message for issue in issues}
    assert any("'curator'" in word for word in words), issues
    assert any("'vault'" in word for word in words), issues


def test_jargon_in_description_is_reported(tmp_path: Path) -> None:
    text = GOOD_FRONTMATTER.replace(
        "Says plainly when",
        "Says, in MCP terms, when",
    )
    _write(tmp_path, "sample-skill", text)
    issues = lint_skills(tmp_path)
    assert any("description uses in-house word 'mcp'" in issue.message for issue in issues), issues


def test_tool_names_and_code_are_not_jargon() -> None:
    """A tool name is the string the model must type — never a lint failure."""
    assert find_jargon("Call `work_memory_capture` when something matters.") == []
    assert find_jargon("| `personal_memory_recall` | recall from it |") == []
    assert find_jargon("```\nmcp add palaia\n```\n") == []
    assert find_jargon("The curator files it.") == ["curator"]


def test_plugin_wrapper_lint_finds_a_broken_marketplace_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A marketplace entry pointing at a directory with no skills is exactly
    the failure that only shows up at distribution time."""
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "x", "description": "d", "version": "0.1.0"}', encoding="utf-8"
    )
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(
        '{"name": "x", "plugins": [{"name": "x", "source": "./nowhere"}]}', encoding="utf-8"
    )
    monkeypatch.setattr(skill_lint, "CLIENTS_ROOT", tmp_path)
    monkeypatch.setattr(skill_lint, "PLUGIN_MANIFEST", tmp_path / ".claude-plugin" / "plugin.json")
    monkeypatch.setattr(
        skill_lint, "MARKETPLACE_MANIFEST", tmp_path / ".claude-plugin" / "marketplace.json"
    )
    issues = lint_plugin_wrapper()
    assert any("has no .claude-plugin/plugin.json" in issue.message for issue in issues), issues
    assert any("carries no skills/" in issue.message for issue in issues), issues
