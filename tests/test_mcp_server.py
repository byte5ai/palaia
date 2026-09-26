"""Tests for palaia MCP server tool handlers."""

from __future__ import annotations

import pytest

from palaia.config import DEFAULT_CONFIG, load_config, save_config
from palaia.store import Store

# Skip all if mcp not installed
mcp = pytest.importorskip("mcp")


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
