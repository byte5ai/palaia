"""The wizard's ``/api/vaults`` create/list surface and the memory
explorer's list/read/search/history/graph endpoints (SPEC-110).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.vault import VaultRegistry


def _client(tmp_path: Path) -> TestClient:
    registry = VaultRegistry(tmp_path / "home")
    app = create_app(HubConfig(), vault_registry=registry)
    return TestClient(app)


def _note_by_title(notes: list[dict], title: str) -> dict:
    for note in notes:
        if note["title"] == title:
            return note
    raise AssertionError(f"no note titled {title!r} in {notes!r}")


def test_router_absent_without_vault_registry() -> None:
    app = create_app(HubConfig())
    client = TestClient(app)

    response = client.get("/api/vaults")

    assert response.status_code == 404


def test_create_vault_then_list_shows_it(tmp_path: Path) -> None:
    client = _client(tmp_path)

    created = client.post("/api/vaults", json={"key": "work", "purpose": "Team knowledge."})
    assert created.status_code == 200
    body = created.json()
    assert body["key"] == "work"
    assert body["purpose"] == "Team knowledge."
    assert body["writable"] is True
    # 1, not 0: the vault's own meta/vault.md manifest is itself a catalog
    # entry (format spec §1.2) — see EngineVaultService's module docstring
    # for why the "normal recall" surface filters `type: meta` out but this
    # raw note_count does not.
    assert body["note_count"] == 1

    listed = client.get("/api/vaults")
    assert listed.status_code == 200
    assert [v["key"] for v in listed.json()] == ["work"]


def test_create_vault_honors_explicit_path(tmp_path: Path) -> None:
    client = _client(tmp_path)
    custom = tmp_path / "elsewhere"

    response = client.post("/api/vaults", json={"key": "work", "path": str(custom)})

    assert response.status_code == 200
    assert response.json()["path"] == str(custom)
    assert (custom / "meta" / "vault.md").exists()


def test_create_duplicate_name_is_400(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/vaults", json={"key": "work"})

    response = client.post("/api/vaults", json={"key": "work"})

    assert response.status_code == 400


def test_create_with_template_seeds_two_notes(tmp_path: Path) -> None:
    client = _client(tmp_path)

    created = client.post("/api/vaults", json={"key": "work", "template": True})
    assert created.json()["note_count"] == 3  # 2 template notes + the manifest

    notes = client.get("/api/vaults/work/notes").json()
    titles = {note["title"] for note in notes}
    assert titles == {"Welcome to this vault", "Example project"}


def test_list_notes_unknown_vault_is_404(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/vaults/nope/notes")

    assert response.status_code == 404


def test_read_note_roundtrip(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/vaults", json={"key": "work", "template": True})
    notes = client.get("/api/vaults/work/notes").json()
    welcome = _note_by_title(notes, "Welcome to this vault")

    response = client.get(f"/api/vaults/work/notes/{welcome['permalink']}")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Welcome to this vault"
    assert "starter note" in body["body"]


def test_read_note_unknown_permalink_is_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/vaults", json={"key": "work"})

    response = client.get("/api/vaults/work/notes/does-not-exist")

    assert response.status_code == 404


def test_search_finds_matching_note(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/vaults", json={"key": "work", "template": True})

    response = client.get("/api/vaults/work/search", params={"q": "starter note"})

    assert response.status_code == 200
    hits = response.json()
    assert any(hit["title"] == "Welcome to this vault" for hit in hits)


def test_search_empty_query_returns_no_hits(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/vaults", json={"key": "work", "template": True})

    response = client.get("/api/vaults/work/search", params={"q": ""})

    assert response.status_code == 200
    assert response.json() == []


def test_note_history_reports_the_creating_commit(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/vaults", json={"key": "work", "template": True})
    notes = client.get("/api/vaults/work/notes").json()
    welcome = _note_by_title(notes, "Welcome to this vault")

    response = client.get(f"/api/vaults/work/notes/{welcome['permalink']}/history")

    assert response.status_code == 200
    commits = response.json()
    assert len(commits) >= 1
    assert all({"sha", "subject", "author_name", "committed_at"} <= c.keys() for c in commits)


def test_note_history_unknown_permalink_is_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/vaults", json={"key": "work"})

    response = client.get("/api/vaults/work/notes/does-not-exist/history")

    assert response.status_code == 404


def test_note_graph_links_the_template_notes_both_ways(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/vaults", json={"key": "work", "template": True})
    notes = client.get("/api/vaults/work/notes").json()
    welcome = _note_by_title(notes, "Welcome to this vault")
    example = _note_by_title(notes, "Example project")

    example_graph = client.get(f"/api/vaults/work/notes/{example['permalink']}/graph").json()
    assert any(node["title"] == "Welcome to this vault" for node in example_graph["outbound"])
    assert example_graph["inbound"] == []

    welcome_graph = client.get(f"/api/vaults/work/notes/{welcome['permalink']}/graph").json()
    assert any(node["title"] == "Example project" for node in welcome_graph["inbound"])
    assert welcome_graph["outbound"] == []


def test_note_graph_unknown_permalink_is_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/vaults", json={"key": "work"})

    response = client.get("/api/vaults/work/notes/does-not-exist/graph")

    assert response.status_code == 404


def test_inbox_status_falls_back_to_registry_backed_vault(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/vaults", json={"key": "work"})

    response = client.get("/api/vaults/work/inbox_status")

    assert response.status_code == 200
    assert response.json()["count"] == 0
