"""SQLite (FTS5) index build/rebuild + search, for the vault round-trip spike.

Plain module (no PEP 723 header) — imported by round_trip.py and index.py,
which declare its transitive dependency (PyYAML, via grammar.py) themselves.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import grammar

SCHEMA = """
CREATE TABLE entities (
    permalink   TEXT PRIMARY KEY,
    path        TEXT NOT NULL,
    title       TEXT NOT NULL,
    type        TEXT NOT NULL,
    tags        TEXT NOT NULL,
    created     TEXT,
    modified    TEXT
);

CREATE TABLE observations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_permalink  TEXT NOT NULL REFERENCES entities(permalink),
    category          TEXT NOT NULL,
    content           TEXT NOT NULL,
    tags              TEXT NOT NULL,
    context           TEXT
);

CREATE TABLE relations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_permalink    TEXT NOT NULL REFERENCES entities(permalink),
    relation_type       TEXT NOT NULL,
    target_raw          TEXT NOT NULL,
    context             TEXT
);

CREATE VIRTUAL TABLE fts USING fts5(
    permalink UNINDEXED,
    title,
    body
);
"""


def list_vault_files(vault_dir: str) -> list[str]:
    return sorted(
        str(p) for p in Path(vault_dir).rglob("*.md")
    )


def build_index(vault_dir: str, db_path: str) -> dict:
    """(Re)build the index at db_path from scratch by parsing every .md
    file under vault_dir. Returns timing/count stats."""
    import time

    if os.path.exists(db_path):
        os.remove(db_path)

    t0 = time.perf_counter()
    files = list_vault_files(vault_dir)
    t_list = time.perf_counter()

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    n_entities = n_obs = n_rel = n_errors = 0
    for fs_path in files:
        try:
            entity = grammar.parse_file(fs_path, vault_dir)
        except grammar.ParseError:
            n_errors += 1
            continue
        conn.execute(
            "INSERT INTO entities(permalink, path, title, type, tags, created, modified) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entity.permalink,
                entity.path,
                entity.title,
                entity.type,
                ",".join(entity.tags),
                entity.created,
                entity.modified,
            ),
        )
        for obs in entity.observations:
            n_obs += 1
            conn.execute(
                "INSERT INTO observations(entity_permalink, category, content, tags, context) "
                "VALUES (?, ?, ?, ?, ?)",
                (obs.entity_permalink, obs.category, obs.content, ",".join(obs.tags), obs.context),
            )
        for rel in entity.relations:
            n_rel += 1
            conn.execute(
                "INSERT INTO relations(source_permalink, relation_type, target_raw, context) "
                "VALUES (?, ?, ?, ?)",
                (rel.source_permalink, rel.relation_type, rel.target_raw, rel.context),
            )
        body_text = entity.body + "\n" + "\n".join(o.content for o in entity.observations)
        conn.execute(
            "INSERT INTO fts(permalink, title, body) VALUES (?, ?, ?)",
            (entity.permalink, entity.title, body_text),
        )
        n_entities += 1
    conn.commit()
    t_build = time.perf_counter()

    conn.close()
    db_size = os.path.getsize(db_path)
    return {
        "n_files": len(files),
        "n_entities": n_entities,
        "n_observations": n_obs,
        "n_relations": n_rel,
        "n_parse_errors": n_errors,
        "list_seconds": t_list - t0,
        "build_seconds": t_build - t_list,
        "total_seconds": t_build - t0,
        "db_size_bytes": db_size,
    }


def search(db_path: str, query: str, limit: int = 10) -> list[str]:
    """Return matching entity permalinks, ranked, for a search string.

    The raw string is quoted as an FTS5 phrase so callers can pass
    hyphenated/plain tokens without needing to know FTS5 query-syntax
    operators (`-`, `:`, ...) — good enough for this spike's purposes.
    """
    phrase = '"' + query.replace('"', '""') + '"'
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT permalink FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?",
            (phrase, limit),
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]
