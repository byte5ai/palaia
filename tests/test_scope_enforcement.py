"""Tests for scope enforcement audit (#39).

Verifies that all read/write operations respect scope boundaries.
"""

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.scope import can_access
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    config = dict(DEFAULT_CONFIG)
    config["agent"] = "agent1"
    save_config(root, config)
    return root


@pytest.fixture
def store(palaia_root):
    return Store(palaia_root)


# --- store.read() scope enforcement ---


def test_read_team_scope_accessible(store):
    """Team-scoped entries are accessible to any agent."""
    entry_id = store.write("Team entry", scope="team", agent="agent1")
    result = store.read(entry_id, agent="agent2")
    assert result is not None


def test_read_private_scope_own_agent(store):
    """Private entries readable only by owning agent."""
    entry_id = store.write("Private entry", scope="private", agent="agent1")
    result = store.read(entry_id, agent="agent1")
    assert result is not None


def test_read_private_scope_other_agent(store):
    """Private entries NOT readable by other agents."""
    entry_id = store.write("Private entry", scope="private", agent="agent1")
    result = store.read(entry_id, agent="agent2")
    assert result is None


def test_read_private_scope_no_agent(store):
    """Private entries NOT readable when no agent specified."""
    entry_id = store.write("Private entry", scope="private", agent="agent1")
    result = store.read(entry_id, agent=None)
    assert result is None


def test_read_public_scope_accessible(store):
    """Public entries accessible to any agent."""
    entry_id = store.write("Public entry", scope="public", agent="agent1")
    result = store.read(entry_id, agent="anyone")
    assert result is not None


# --- store.list_entries() scope enforcement ---


def test_list_filters_private_entries(store):
    """list_entries should not include other agents' private entries."""
    store.write("Agent1 private", scope="private", agent="agent1")
    store.write("Agent2 private", scope="private", agent="agent2")
    store.write("Team entry", scope="team", agent="agent1")

    entries_a1 = store.list_entries("hot", agent="agent1")
    entries_a2 = store.list_entries("hot", agent="agent2")

    # agent1 sees their private + team
    assert len(entries_a1) == 2
    # agent2 sees their private + team
    assert len(entries_a2) == 2


def test_list_no_agent_sees_team_and_public(store):
    """Without agent, list returns team + public entries only."""
    store.write("Private", scope="private", agent="agent1")
    store.write("Team", scope="team", agent="agent1")
    store.write("Public", scope="public", agent="agent1")

    entries = store.list_entries("hot", agent=None)
    assert len(entries) == 2  # team + public, NOT private


# --- store.edit() scope enforcement ---


def test_edit_own_private_entry(store):
    """Agent can edit their own private entries."""
    entry_id = store.write("My private data", scope="private", agent="agent1")
    meta = store.edit(entry_id, body="Updated private data", agent="agent1")
    assert meta is not None


def test_edit_other_private_entry_blocked(store):
    """Agent cannot edit another agent's private entries."""
    entry_id = store.write("Agent1 private", scope="private", agent="agent1")
    with pytest.raises(PermissionError, match="Scope violation"):
        store.edit(entry_id, body="Hacked!", agent="agent2")


def test_edit_team_entry_allowed(store):
    """Any agent can edit team-scoped entries."""
    entry_id = store.write("Team data", scope="team", agent="agent1")
    meta = store.edit(entry_id, body="Updated team data", agent="agent2")
    assert meta is not None


def test_edit_no_scope_escalation(store):
    """Edit cannot change scope to escalate access."""
    # Note: store.edit doesn't currently accept scope changes
    # This is by design — scope is immutable after creation
    entry_id = store.write("Private", scope="private", agent="agent1")
    entry = store.read(entry_id, agent="agent1")
    assert entry is not None
    meta, _ = entry
    assert meta["scope"] == "private"


# --- all_entries() scope enforcement ---


def test_all_entries_respects_scope(store):
    """all_entries should filter by scope like list_entries."""
    store.write("Private A1", scope="private", agent="agent1")
    store.write("Private A2", scope="private", agent="agent2")
    store.write("Team entry", scope="team", agent="agent1")

    all_a1 = store.all_entries(include_cold=True, agent="agent1")
    all_a2 = store.all_entries(include_cold=True, agent="agent2")

    assert len(all_a1) == 2  # own private + team
    assert len(all_a2) == 2  # own private + team


def test_search_respects_scope(palaia_root):
    """search returns the agent's own private entries and hides other agents' ones."""
    from palaia.search import SearchEngine

    config = dict(DEFAULT_CONFIG, agent="agent1", embedding_chain=["bm25"])
    save_config(palaia_root, config)
    store = Store(palaia_root)
    store.write("Launch codes for agent one", scope="private", agent="agent1", title="A1 secret")
    store.write("Launch codes for agent two", scope="private", agent="agent2", title="A2 secret")
    store.write("Launch codes shared with the team", scope="team", agent="agent1", title="Team note")

    def titles(agent):
        return {r["title"] for r in SearchEngine(store).search("launch codes", agent=agent)}

    assert titles("agent1") == {"A1 secret", "Team note"}
    assert titles("agent2") == {"A2 secret", "Team note"}
    assert titles(None) == {"Team note"}


# --- GC scope isolation ---


def test_gc_does_not_cross_scope_boundaries(store, palaia_root):
    """GC operates on all entries (system-level) but doesn't leak data."""
    store.write("Private A1", scope="private", agent="agent1")
    store.write("Team entry", scope="team", agent="agent1")

    result = store.gc()
    # GC should complete without errors
    assert isinstance(result, dict)

    # After GC, private entries are still only visible to owner
    entries = store.list_entries("hot", agent="agent2")
    private_entries = [(m, b) for m, b in entries if m.get("scope") == "private"]
    assert len(private_entries) == 0


# --- Export scope enforcement ---


def test_export_only_public(store, palaia_root):
    """Export only exports public entries, not team or private."""
    from palaia.scope import is_exportable

    store.write("Private entry", scope="private", agent="agent1")
    store.write("Team entry", scope="team", agent="agent1")
    store.write("Public entry", scope="public", agent="agent1")

    all_entries = store.all_entries(include_cold=True)
    exportable = [(m, b, t) for m, b, t in all_entries if is_exportable(m.get("scope", "team"))]
    assert len(exportable) == 1
    assert exportable[0][0]["scope"] == "public"


# --- can_access() unit tests ---


def test_can_access_team():
    assert can_access("team", "anyone", "owner") is True


def test_can_access_public():
    assert can_access("public", "anyone", "owner") is True


def test_can_access_private_owner():
    assert can_access("private", "owner", "owner") is True


def test_can_access_private_other():
    assert can_access("private", "other", "owner") is False


def test_can_access_private_no_agent():
    assert can_access("private", None, "owner") is False


def test_can_access_shared_legacy_as_team():
    """Legacy shared:X entries are treated as team — always accessible."""
    assert can_access("shared:myproj", "anyone", "owner", projects=["myproj"]) is True
    assert can_access("shared:myproj", "anyone", "owner", projects=["other"]) is True
    assert can_access("shared:myproj", "anyone", "owner", projects=None) is True


# --- Alias-aware scope enforcement ---


def test_private_access_via_alias(palaia_root):
    """Private entries accessible via aliased agent names."""
    from palaia.config import set_alias

    set_alias(palaia_root, "default", "agent1")
    store = Store(palaia_root)
    entry_id = store.write("Alias test", scope="private", agent="default")

    # Access via alias target
    result = store.read(entry_id, agent="agent1")
    assert result is not None

    # Access via alias source
    result = store.read(entry_id, agent="default")
    assert result is not None

    # Other agent still blocked
    result = store.read(entry_id, agent="agent2")
    assert result is None


# --- resolve_visible_id ---


def _clone_entry(store, entry_id, new_id, **meta_changes):
    """Copy an entry file under a chosen id (to control shared prefixes)."""
    from palaia.entry import parse_entry, serialize_entry

    meta, body = parse_entry((store.root / "hot" / f"{entry_id}.md").read_text(encoding="utf-8"))
    meta.update(id=new_id, **meta_changes)
    (store.root / "hot" / f"{new_id}.md").write_text(serialize_entry(meta, body), encoding="utf-8")


def test_resolve_visible_id_skips_hidden_entries(store):
    src = store.write("Template", scope="team", agent="agent1")
    _clone_entry(store, src, "abc00000-0000-0000-0000-000000000001", scope="private", agent="agent2")
    _clone_entry(store, src, "abc00000-0000-0000-0000-000000000002", scope="private", agent="agent1")

    # The hidden agent2 entry sorts first but must neither shadow nor be revealed.
    assert store.resolve_visible_id("abc", agent="agent1") == "abc00000-0000-0000-0000-000000000002"
    assert store.resolve_visible_id("abc00000-0000-0000-0000-000000000001", agent="agent1") is None
    assert store.resolve_visible_id("abc", agent="agent2") == "abc00000-0000-0000-0000-000000000001"
    assert store.resolve_visible_id("abc", agent=None) is None


@pytest.mark.parametrize("entry_id", ["", "../hot/x", "*", "abc*", "zz-not-hex"])
def test_resolve_visible_id_rejects_malformed_ids(store, entry_id):
    store.write("Team entry", scope="team", agent="agent1")
    assert store.resolve_visible_id(entry_id, agent="agent1") is None


# --- private write guard (shared by the CLI write service and MCP) ---


def test_write_entry_refuses_private_project_default_without_identity(palaia_root, monkeypatch):
    from palaia.project import ProjectManager
    from palaia.services.write import write_entry

    monkeypatch.delenv("PALAIA_AGENT", raising=False)
    save_config(palaia_root, dict(DEFAULT_CONFIG, agent=None, multi_agent=True))
    ProjectManager(palaia_root).create("secret", default_scope="private")

    result = write_entry(palaia_root, body="Orphan via project default", project="secret", agent="default")
    assert "without an agent identity" in result["error"]
    assert write_entry(palaia_root, body="Owned", project="secret", agent="agent1").get("id")


class _FakeProvider:
    model_name = "fake"

    def embed_query(self, text):
        return [1.0, 0.0]

    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class _FakeVecBackend:
    """Unfiltered KNN over the whole table, like sqlite-vec / pgvector."""

    _has_vec = True

    def __init__(self, similarities):
        self.similarities = similarities  # {entry_id: similarity}; absent = no embedding

    def vector_search(self, vec, top_k=10, *, tier=None, entry_type=None):
        ranked = sorted(self.similarities.items(), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


def _native_vector_engine(store, monkeypatch, similarities):
    from palaia.search import SearchEngine

    monkeypatch.setattr(store, "_backend", _FakeVecBackend(similarities), raising=False)
    engine = SearchEngine(store)
    engine._provider = _FakeProvider()
    assert engine.has_embeddings
    return engine


@pytest.fixture
def bm25_store(palaia_root):
    save_config(palaia_root, dict(DEFAULT_CONFIG, agent="agent1", embedding_chain=["bm25"]))
    return Store(palaia_root)


def test_search_native_vector_hits_respect_filters(bm25_store, monkeypatch):
    """Vector hits outside the scope or the structured filters must not reach the results."""
    store = bm25_store
    ids = [
        store.write("Deploy notes alpha", scope="team", agent="agent1", project="x", title="X team"),
        store.write("Deploy notes beta", scope="private", agent="agent1", project="y", title="Y own private"),
        store.write("Deploy notes gamma", scope="team", agent="agent1", project="y", title="Y team"),
        store.write("Deploy notes delta", scope="private", agent="agent2", project="x", title="X foreign private"),
    ]
    engine = _native_vector_engine(store, monkeypatch, {i: 0.99 for i in ids})

    titles = {r["title"] for r in engine.search("deploy notes", agent="agent1", project="x")}
    assert titles == {"X team"}


def test_search_native_vector_recall_survives_filtered_out_neighbours(bm25_store, monkeypatch):
    """An eligible semantic-only match is found even when many filtered-out entries
    are nearer to the query than it is."""
    store = bm25_store
    target = store.write("Quarterly revenue forecast", project="x", title="Forecast")
    noise = [store.write(f"Unrelated entry {i}", project="y", title=f"Noise {i}") for i in range(30)]
    sims = {i: 0.95 for i in noise}
    sims[target] = 0.6
    engine = _native_vector_engine(store, monkeypatch, sims)

    results = engine.search("money outlook", top_k=2, agent="agent1", project="x")
    assert [r["title"] for r in results] == ["Forecast"]
    assert results[0]["embed_score"] == 0.6


def test_search_hybrid_weighting_ignores_filtered_out_vector_hits(bm25_store, monkeypatch):
    """When every vector hit is filtered out, eligible keyword matches keep their full
    BM25 score instead of being down-weighted as if a semantic score existed."""
    store = bm25_store
    store.write("Deploy checklist for release", project="x", title="Checklist")  # no embedding
    other = store.write("Something else entirely", project="y", title="Other")
    engine = _native_vector_engine(store, monkeypatch, {other: 0.99})

    results = engine.search("deploy checklist", agent="agent1", project="x")
    assert [r["title"] for r in results] == ["Checklist"]
    assert results[0]["score"] == 1.0
