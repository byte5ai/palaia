"""Tests for palaia MCP server tool handlers."""

from __future__ import annotations

import pytest

from palaia.config import DEFAULT_CONFIG, load_config, save_config
from palaia.store import Store

# Skip all if mcp not installed
mcp = pytest.importorskip("mcp")


@pytest.fixture(autouse=True)
def _isolated_agent_identity(monkeypatch, tmp_path_factory):
    """Keep the host's identity out: the server resolves its agent like the CLI does,
    from PALAIA_AGENT, the store config and ~/.openclaw/config.json."""
    monkeypatch.delenv("PALAIA_AGENT", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal .palaia directory with BM25-only config."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()

    config = dict(DEFAULT_CONFIG)
    config["agent"] = "test-agent"
    config["embedding_chain"] = ["bm25"]
    save_config(root, config)
    return root


@pytest.fixture
def palaia_root_with_entries(palaia_root):
    """Create a .palaia directory with some test entries."""
    store = Store(palaia_root)
    store.write(body="Python best practices for API design", tags=["python", "api"], title="API Design")
    store.write(body="JavaScript async patterns", tags=["javascript"], title="JS Async", entry_type="process")
    store.write(
        body="Fix auth bug in login flow",
        tags=["bug"],
        title="Auth Bug",
        entry_type="task",
        status="open",
        priority="high",
    )
    return palaia_root


@pytest.fixture
def server(palaia_root_with_entries):
    """Create a configured MCP server."""
    from palaia.mcp.server import create_server

    return create_server(palaia_root_with_entries)


@pytest.fixture
def readonly_server(palaia_root_with_entries):
    """Create a read-only MCP server."""
    from palaia.mcp.server import create_server

    return create_server(palaia_root_with_entries, read_only=True)


def _get_tool_fn(server, name):
    """Get a tool function by name from the FastMCP server."""
    tools = server._tool_manager._tools
    if name not in tools:
        raise KeyError(f"Tool '{name}' not found. Available: {list(tools.keys())}")
    return tools[name].fn


# ── Tool registration ────────────────────────────────────────────

class TestToolRegistration:
    def test_read_write_tools_registered(self, server):
        tools = server._tool_manager._tools
        expected = {"palaia_search", "palaia_read", "palaia_list", "palaia_status",
                    "palaia_store", "palaia_edit", "palaia_gc"}
        assert expected.issubset(set(tools.keys()))

    def test_readonly_no_write_tools(self, readonly_server):
        tools = readonly_server._tool_manager._tools
        assert "palaia_search" in tools
        assert "palaia_read" in tools
        assert "palaia_list" in tools
        assert "palaia_status" in tools
        assert "palaia_store" not in tools
        assert "palaia_edit" not in tools
        assert "palaia_gc" not in tools

    def test_all_parameters_have_descriptions(self, server):
        """Parameter descriptions must reach the JSON schema the client sees (#464)."""
        undescribed = [
            f"{name}.{param}"
            for name, tool in server._tool_manager._tools.items()
            for param, schema in tool.parameters.get("properties", {}).items()
            if not schema.get("description")
        ]
        assert undescribed == []
        # Guard against a vacuous pass if the schema layout changes.
        total = sum(len(tool.parameters.get("properties", {})) for tool in server._tool_manager._tools.values())
        assert total == 33


# ── palaia_search ────────────────────────────────────────────────

class TestSearch:
    def test_search_finds_entries(self, server):
        fn = _get_tool_fn(server, "palaia_search")
        result = fn(query="Python API", limit=5)
        assert "result" in result.lower() or "API Design" in result

    def test_search_no_results(self, server):
        fn = _get_tool_fn(server, "palaia_search")
        result = fn(query="xyzzy nonexistent topic 12345")
        assert "no matching" in result.lower() or "0 result" in result.lower() or "found" in result.lower()

    def test_search_with_type_filter(self, server):
        fn = _get_tool_fn(server, "palaia_search")
        result = fn(query="patterns", entry_type="process")
        assert isinstance(result, str)

    def test_search_with_status_filter(self, server):
        fn = _get_tool_fn(server, "palaia_search")
        result = fn(query="bug", status="open")
        assert isinstance(result, str)


# ── palaia_read ──────────────────────────────────────────────────

class TestRead:
    def test_read_entry(self, palaia_root_with_entries, server):
        store = Store(palaia_root_with_entries)
        entries = store.list_entries("hot")
        assert entries
        meta, _ = entries[0]
        entry_id = meta["id"]

        fn = _get_tool_fn(server, "palaia_read")
        result = fn(entry_id=entry_id)
        assert entry_id in result or entry_id[:8] in result

    def test_read_not_found(self, server):
        fn = _get_tool_fn(server, "palaia_read")
        result = fn(entry_id="00000000-0000-0000-0000-000000000000")
        assert "not found" in result.lower()


# ── palaia_list ──────────────────────────────────────────────────

class TestList:
    def test_list_hot(self, server):
        fn = _get_tool_fn(server, "palaia_list")
        result = fn(tier="hot")
        assert "3 entries" in result or "entries in hot" in result

    def test_list_empty_tier(self, server):
        fn = _get_tool_fn(server, "palaia_list")
        result = fn(tier="cold")
        assert "no entries" in result.lower() or "0 entries" in result.lower()

    def test_list_with_type_filter(self, server):
        fn = _get_tool_fn(server, "palaia_list")
        result = fn(entry_type="task")
        assert isinstance(result, str)


# ── palaia_status ────────────────────────────────────────────────

class TestStatus:
    def test_status(self, server):
        fn = _get_tool_fn(server, "palaia_status")
        result = fn()
        assert "hot=" in result
        assert "Embedding" in result or "embed" in result.lower()


# ── palaia_store ─────────────────────────────────────────────────

class TestStore:
    def test_store_entry(self, server, palaia_root_with_entries):
        fn = _get_tool_fn(server, "palaia_store")
        result = fn(content="New memory about testing", title="Test Memory", tags=["test"])
        assert "stored" in result.lower() or "entry" in result.lower()

        # Verify it was actually stored
        store = Store(palaia_root_with_entries)
        entries = store.list_entries("hot")
        assert len(entries) == 4

    def test_store_task(self, server):
        fn = _get_tool_fn(server, "palaia_store")
        result = fn(
            content="Implement new feature",
            entry_type="task",
            status="open",
            priority="medium",
        )
        assert "stored" in result.lower()


# ── palaia_edit ──────────────────────────────────────────────────

class TestEdit:
    def test_edit_entry(self, palaia_root_with_entries, server):
        store = Store(palaia_root_with_entries)
        entries = store.list_entries("hot")
        meta, _ = entries[0]
        entry_id = meta["id"]

        fn = _get_tool_fn(server, "palaia_edit")
        result = fn(entry_id=entry_id, title="Updated Title")
        assert "updated" in result.lower()

    def test_edit_by_short_prefix(self, server, palaia_root_with_entries):
        store = Store(palaia_root_with_entries)
        full_id = store.write(body="Original body", title="Prefix edit")
        fn = _get_tool_fn(server, "palaia_edit")
        result = fn(entry_id=full_id[:8], title="Edited via prefix")
        assert "updated" in result.lower()
        assert store.read(full_id)[0]["title"] == "Edited via prefix"

    def test_edit_not_found(self, server):
        fn = _get_tool_fn(server, "palaia_edit")
        result = fn(entry_id="00000000-0000-0000-0000-000000000000")
        assert "not found" in result.lower()


# ── palaia_gc ────────────────────────────────────────────────────

class TestGC:
    def test_gc_dry_run_lists_scored_entries(self, server):
        fn = _get_tool_fn(server, "palaia_gc")
        result = fn(dry_run=True)
        assert "no changes made" in result.lower()
        assert "scored 3 entries" in result
        for title in ("API Design", "JS Async", "Auth Bug"):
            assert title in result

    def test_gc_dry_run_respects_limit(self, server):
        fn = _get_tool_fn(server, "palaia_gc")
        result = fn(dry_run=True, limit=1)
        assert "scored 3 entries" in result
        assert "... and 2 more" in result

    def test_gc_dry_run_changes_nothing(self, server, palaia_root_with_entries):
        stale_id = _backdate(palaia_root_with_entries, "Stale note", days=60)
        _get_tool_fn(server, "palaia_gc")(dry_run=True)
        assert (palaia_root_with_entries / "hot" / f"{stale_id}.md").exists()

    def test_gc_reports_tier_moves(self, server, palaia_root_with_entries):
        stale_id = _backdate(palaia_root_with_entries, "Stale note", days=60)
        result = _get_tool_fn(server, "palaia_gc")(dry_run=False)
        assert "hot -> cold: 1" in result
        assert (palaia_root_with_entries / "cold" / f"{stale_id}.md").exists()

    def test_gc_reports_no_moves(self, server):
        result = _get_tool_fn(server, "palaia_gc")(dry_run=False)
        assert "Tier moves: none" in result
        assert "Pruned" not in result

    def test_gc_reports_pruned_entries(self, palaia_root_with_entries):
        from palaia.mcp.server import create_server

        config = load_config(palaia_root_with_entries)
        config["max_entries_per_tier"] = 1
        save_config(palaia_root_with_entries, config)

        server = create_server(palaia_root_with_entries)
        result = _get_tool_fn(server, "palaia_gc")(dry_run=False)
        assert "Pruned (over storage budget): 2 entries" in result
        assert result.count("budget:max_entries_per_tier") == 2


def _backdate(root, title, days):
    """Write an entry whose last access lies `days` in the past; return its id."""
    from datetime import datetime, timedelta, timezone

    from palaia.entry import parse_entry, serialize_entry

    store = Store(root)
    entry_id = store.write(body=f"{title} body", title=title)
    path = root / "hot" / f"{entry_id}.md"
    meta, body = parse_entry(path.read_text(encoding="utf-8"))
    past = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    meta["created"] = past
    meta["accessed"] = past
    meta["access_count"] = 1
    path.write_text(serialize_entry(meta, body), encoding="utf-8")
    return entry_id


# ── Agent identity ───────────────────────────────────────────────


def _raw_meta(root, entry_id):
    from palaia.entry import parse_entry

    for tier in ("hot", "warm", "cold"):
        path = root / tier / f"{entry_id}.md"
        if path.exists():
            return parse_entry(path.read_text(encoding="utf-8"))[0]
    raise FileNotFoundError(entry_id)


def _stored_id(result):
    # "Stored entry ab12cd34 (memory)"
    return result.split()[2]


class TestAgentIdentity:
    """The server acts as the agent the CLI would resolve ("test-agent" from the config here)."""

    def test_store_stamps_server_agent(self, server, palaia_root_with_entries):
        result = _get_tool_fn(server, "palaia_store")(content="Team note from MCP")
        assert _raw_meta(palaia_root_with_entries, _full_id(palaia_root_with_entries, result))["agent"] == "test-agent"

    def test_explicit_agent_param_owns_team_entry(self, server, palaia_root_with_entries):
        result = _get_tool_fn(server, "palaia_store")(content="Note for someone else", agent="other-agent")
        assert _raw_meta(palaia_root_with_entries, _full_id(palaia_root_with_entries, result))["agent"] == "other-agent"

    def test_private_entry_for_foreign_owner_is_refused(self, server, palaia_root_with_entries):
        result = _get_tool_fn(server, "palaia_store")(
            content="Secret for bob", scope="private", agent="bob"
        )
        assert result.startswith("Cannot store a private entry for agent 'bob'")
        assert not any("Secret for bob" in p.read_text() for p in palaia_root_with_entries.glob("*/*.md"))

    def test_single_agent_config_wins_over_env(self, palaia_root_with_entries, monkeypatch):
        """Same precedence as the CLI: in single-agent mode the config's agent wins."""
        from palaia.mcp.server import create_server

        monkeypatch.setenv("PALAIA_AGENT", "env-agent")
        server = create_server(palaia_root_with_entries)
        result = _get_tool_fn(server, "palaia_store")(content="Single-agent note")
        assert _raw_meta(palaia_root_with_entries, _full_id(palaia_root_with_entries, result))["agent"] == "test-agent"

    def test_multi_agent_env_wins_over_config(self, palaia_root_with_entries, monkeypatch):
        from palaia.mcp.server import create_server

        config = load_config(palaia_root_with_entries)
        config["multi_agent"] = True
        save_config(palaia_root_with_entries, config)
        monkeypatch.setenv("PALAIA_AGENT", "env-agent")
        server = create_server(palaia_root_with_entries)
        result = _get_tool_fn(server, "palaia_store")(content="Multi-agent note")
        assert _raw_meta(palaia_root_with_entries, _full_id(palaia_root_with_entries, result))["agent"] == "env-agent"

    def test_same_identity_as_cli(self, palaia_root_with_entries, monkeypatch):
        from palaia.cli_helpers import resolve_agent
        from palaia.mcp.server import create_server

        monkeypatch.setenv("PALAIA_HOME", str(palaia_root_with_entries))
        monkeypatch.chdir(palaia_root_with_entries.parent)
        server = create_server(palaia_root_with_entries)
        result = _get_tool_fn(server, "palaia_store")(content="Who am I")
        stored_as = _raw_meta(palaia_root_with_entries, _full_id(palaia_root_with_entries, result))["agent"]
        assert stored_as == resolve_agent(type("Args", (), {"agent": None})())

    def test_own_private_entry_round_trip(self, server):
        stored = _get_tool_fn(server, "palaia_store")(
            content="Launch codes live in the vault", title="Private plan", scope="private"
        )
        short_id = _stored_id(stored)

        assert "Launch codes" in _get_tool_fn(server, "palaia_read")(entry_id=short_id)
        assert "Private plan" in _get_tool_fn(server, "palaia_search")(query="launch codes vault")
        assert "Private plan" in _get_tool_fn(server, "palaia_list")()

        edited = _get_tool_fn(server, "palaia_edit")(entry_id=short_id, title="Private plan v2")
        assert edited.startswith("Updated entry")
        assert "Private plan v2" in _get_tool_fn(server, "palaia_read")(entry_id=short_id)

    def test_other_agents_private_entry_is_indistinguishable_from_missing(self, server, palaia_root_with_entries):
        other_id = Store(palaia_root_with_entries).write(
            body="Someone else's secret", title="Not yours", scope="private", agent="other-agent"
        )

        for entry_id in (other_id, other_id[:8]):
            assert _get_tool_fn(server, "palaia_read")(entry_id=entry_id) == f"Entry not found: {entry_id}"
            edited = _get_tool_fn(server, "palaia_edit")(entry_id=entry_id, title="Hijacked")
            assert edited == f"Entry not found: {entry_id}"
        assert "Not yours" not in _get_tool_fn(server, "palaia_list")()
        assert "Not yours" not in _get_tool_fn(server, "palaia_search")(query="someone else secret")
        assert _raw_meta(palaia_root_with_entries, other_id)["title"] == "Not yours"

    def test_edit_reports_invalid_values(self, server, palaia_root_with_entries):
        eid = Store(palaia_root_with_entries).write(body="A task", entry_type="task", title="Task")
        result = _get_tool_fn(server, "palaia_edit")(entry_id=eid, status="closed")
        assert result.startswith("Error:")
        assert "not found" not in result.lower()


class TestNoAgentIdentity:
    """Multi-agent store, no PALAIA_AGENT, no config agent: the identity falls back to
    'default', which is not an owner for private entries (same rule as the CLI)."""

    @pytest.fixture
    def anonymous_server(self, palaia_root_with_entries):
        from palaia.mcp.server import create_server
        from palaia.project import ProjectManager

        config = load_config(palaia_root_with_entries)
        config["agent"] = None
        config["multi_agent"] = True
        save_config(palaia_root_with_entries, config)
        ProjectManager(palaia_root_with_entries).create("secret-project", default_scope="private")
        return create_server(palaia_root_with_entries)

    def test_explicit_private_store_is_refused(self, anonymous_server, palaia_root_with_entries):
        result = _get_tool_fn(anonymous_server, "palaia_store")(content="Orphan secret", scope="private")
        assert result.startswith("Cannot write with scope 'private' without an agent identity")
        assert not any("Orphan secret" in p.read_text() for p in palaia_root_with_entries.glob("*/*.md"))

    def test_private_project_default_store_is_refused(self, anonymous_server):
        result = _get_tool_fn(anonymous_server, "palaia_store")(content="Orphan via project", project="secret-project")
        assert result.startswith("Cannot write with scope 'private' without an agent identity")

    def test_team_store_still_works(self, anonymous_server):
        result = _get_tool_fn(anonymous_server, "palaia_store")(content="Shared note without identity")
        assert result.startswith("Stored entry")


def _full_id(root, stored_result):
    from palaia.services.query import _resolve_short_id

    return _resolve_short_id(Store(root), _stored_id(stored_result))


# ── Server creation ─────────────────────────────────────────────

class TestServerCreation:
    def test_create_server_returns_fastmcp(self, palaia_root):
        from mcp.server.fastmcp import FastMCP

        from palaia.mcp.server import create_server

        server = create_server(palaia_root)
        assert isinstance(server, FastMCP)

    def test_create_readonly_server(self, palaia_root):
        from palaia.mcp.server import create_server

        server = create_server(palaia_root, read_only=True)
        tools = server._tool_manager._tools
        assert "palaia_search" in tools
        assert "palaia_store" not in tools
