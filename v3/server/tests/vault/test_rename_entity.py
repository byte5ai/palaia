"""``rename_entity`` on a golden vault: total, atomic, no dangling backlinks."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import TEST_ATTRIBUTION, EngineFactory

from palaia_hub.vault import EntityRenamed, EventBus, VaultDoctor, VolatileNameError
from palaia_hub.vault.doctor import summarize

pytestmark = pytest.mark.anyio


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


CODE_FENCE_NOTE = """\
Documentation of the link syntax.

```markdown
Link to [[API Gateway]] like this.
```

Inline `[[API Gateway]]` is code too.
"""


async def golden_vault(make_engine: EngineFactory, bus: EventBus | None = None):
    """A small vault whose inbound links exercise every wikilink form."""
    engine = await make_engine("work", bus=bus)
    await engine.write_note(
        "projects/api-gateway",
        title="API Gateway",
        body="- [rate-limit] 100 req/min ^rate\n",
        attribution=TEST_ATTRIBUTION,
    )
    await engine.write_note(
        "decisions/rate-limit",
        title="Rate limit decision",
        body=(
            "We capped ingest because of [[API Gateway]] throughput.\n\n"
            "- part_of [[API Gateway]]\n"
            "- relates_to [[API Gateway|the gateway]] (see PR 88)\n"
            "- [ ] follow up with [[API Gateway]] owners\n"
        ),
    )
    await engine.write_note(
        "notes/pricing",
        title="Pricing",
        body="Current limit: ![[API Gateway#^rate]]\n",
    )
    await engine.write_note(
        "notes/by-permalink",
        title="By permalink",
        body="Addressed by permalink: [[projects/api-gateway]]\n",
    )
    await engine.write_note("notes/syntax", title="Syntax", body=CODE_FENCE_NOTE)
    await engine.write_note("notes/unrelated", title="Unrelated", body="No links here.\n")
    return engine


async def test_rename_entity_rewrites_every_backlink_in_one_commit(
    make_engine: EngineFactory,
) -> None:
    bus = EventBus()
    events: list[object] = []
    bus.subscribe(events.append)
    engine = await golden_vault(make_engine, bus)
    commits_before = len(git(engine.root, "log", "--format=%H").splitlines())

    result = await engine.rename_entity(
        "projects/api-gateway", "Edge Gateway", attribution=TEST_ATTRIBUTION
    )

    # 1. New identity, 2. old title and permalink preserved as aliases.
    assert result.note.title == "Edge Gateway"
    assert result.note.permalink == "projects/edge-gateway"
    assert result.old_title == "API Gateway"
    assert result.old_permalink == "projects/api-gateway"
    assert set(result.note.aliases) == {"API Gateway", "projects/api-gateway"}

    # 3. Every inbound wikilink rewritten — titles as titles, permalinks as
    #    permalinks, anchors and display text preserved, code untouched.
    decision = (engine.root / "decisions/rate-limit.md").read_text(encoding="utf-8")
    assert "[[API Gateway" not in decision
    assert "- part_of [[Edge Gateway]]" in decision
    assert "[[Edge Gateway|the gateway]] (see PR 88)" in decision
    assert "- [ ] follow up with [[Edge Gateway]] owners" in decision
    assert "![[Edge Gateway#^rate]]" in (engine.root / "notes/pricing.md").read_text(
        encoding="utf-8"
    )
    assert "[[projects/edge-gateway]]" in (engine.root / "notes/by-permalink.md").read_text(
        encoding="utf-8"
    )
    syntax = (engine.root / "notes/syntax.md").read_text(encoding="utf-8")
    assert "Link to [[API Gateway]] like this." in syntax
    assert "`[[API Gateway]]`" in syntax
    assert result.rewritten_links == 6
    assert "notes/unrelated.md" not in result.rewritten

    # 4. Exactly one commit for the whole operation.
    commits_after = len(git(engine.root, "log", "--format=%H").splitlines())
    assert commits_after == commits_before + 1
    assert git(engine.root, "log", "-1", "--format=%s").strip() == (
        "curator/claude-code/anthropic: rename projects/api-gateway -> projects/edge-gateway"
    )
    touched = set(git(engine.root, "log", "-1", "--name-only", "--format=").split())
    assert touched == {
        "projects/api-gateway.md",
        "decisions/rate-limit.md",
        "notes/pricing.md",
        "notes/by-permalink.md",
    }

    renamed_events = [event for event in events if isinstance(event, EntityRenamed)]
    assert len(renamed_events) == 1
    assert renamed_events[0].rewritten_links == 6


async def test_rename_leaves_no_dangling_backlinks(make_engine: EngineFactory) -> None:
    engine = await golden_vault(make_engine)
    await engine.rename_entity("projects/api-gateway", "Edge Gateway")
    findings = await VaultDoctor(engine).verify()
    counts = summarize(findings)
    assert counts.get("dangling-link", 0) == 0
    assert counts.get("partial-rename", 0) == 0


async def test_old_references_still_resolve_through_aliases(make_engine: EngineFactory) -> None:
    engine = await golden_vault(make_engine)
    await engine.rename_entity("projects/api-gateway", "Edge Gateway")
    for reference in ("projects/api-gateway", "memory://projects/api-gateway", "API Gateway"):
        note = await engine.read_note(reference)
        assert note.permalink == "projects/edge-gateway"


async def test_external_partial_rename_is_flagged_by_the_doctor(
    make_engine: EngineFactory,
) -> None:
    """An Obsidian-style rename that does not rewrite backlinks is a finding."""
    engine = await golden_vault(make_engine)
    target = engine.root / "projects/api-gateway.md"
    target.write_text(
        target.read_text(encoding="utf-8").replace("title: API Gateway", "title: Edge Gateway"),
        encoding="utf-8",
    )
    await engine.refresh()

    findings = await VaultDoctor(engine).verify()
    partial = [finding for finding in findings if finding.code == "partial-rename"]
    assert partial, summarize(findings)
    assert {finding.path for finding in partial} == {
        "decisions/rate-limit.md",
        "notes/pricing.md",
    }
    assert "renamed without rewriting its backlinks" in partial[0].detail


async def test_rename_can_also_rename_the_file_in_the_same_commit(
    make_engine: EngineFactory,
) -> None:
    engine = await golden_vault(make_engine)
    commits_before = len(git(engine.root, "log", "--format=%H").splitlines())
    result = await engine.rename_entity(
        "projects/api-gateway", "Edge Gateway", rename_file=True
    )
    assert result.note.path == "projects/edge-gateway.md"
    assert not (engine.root / "projects/api-gateway.md").exists()
    assert len(git(engine.root, "log", "--format=%H").splitlines()) == commits_before + 1
    note = await engine.read_note("projects/edge-gateway")
    assert note.title == "Edge Gateway"


async def test_rename_to_a_volatile_title_is_refused(make_engine: EngineFactory) -> None:
    engine = await golden_vault(make_engine)
    with pytest.raises(VolatileNameError):
        await engine.rename_entity("projects/api-gateway", "API Gateway v2.1")
    note = await engine.read_note("projects/api-gateway")
    assert note.title == "API Gateway"


async def test_rename_does_not_rewrite_links_owned_by_another_note(
    make_engine: EngineFactory,
) -> None:
    """A path-shaped form that is another note's permalink stays untouched.

    The renamed note lives at ``projects/api.md`` but its permalink is
    something else, and a *different* note owns the permalink
    ``projects/api`` — so ``[[projects/api]]`` means that other note.
    """
    engine = await make_engine("work")
    await engine.write_note(
        "projects/api", title="Gateway", body="x\n", permalink="platform/gateway"
    )
    await engine.write_note("other/decoy", title="Decoy", body="x\n", permalink="projects/api")
    await engine.write_note(
        "notes/links", title="Links", body="[[projects/api]] and [[platform/gateway]]\n"
    )

    await engine.rename_entity("platform/gateway", "Edge Gateway")

    text = (engine.root / "notes/links.md").read_text(encoding="utf-8")
    assert "[[projects/api]]" in text  # still the decoy's permalink
    # The renamed note's new permalink: minted from its folder path (§3.1).
    assert "[[projects/edge-gateway]]" in text


async def test_explicit_new_permalink_is_honoured(make_engine: EngineFactory) -> None:
    engine = await golden_vault(make_engine)
    result = await engine.rename_entity(
        "projects/api-gateway", "Edge Gateway", new_permalink="platform/edge"
    )
    assert result.note.permalink == "platform/edge"
    assert "[[platform/edge]]" in (engine.root / "notes/by-permalink.md").read_text(
        encoding="utf-8"
    )
