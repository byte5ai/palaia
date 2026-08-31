"""``palaia_hub.backup``: the archive builder (SPEC-604 deliverable #1).

Router-level behavior (headers, admin gating) lives in ``test_routes.py``;
this file is about what actually ends up inside the ``tar.gz`` — the
excluded index, and the online-backup snapshot's honesty about WAL-resident
data.
"""

from __future__ import annotations

import io
import sqlite3
import tarfile
from pathlib import Path

import pytest

from palaia_hub.backup import ARCHIVE_MEDIA_TYPE, archive_filename, iter_archive_bytes
from palaia_hub.index.db import INDEX_RELATIVE_PATH


def build_archive(home: Path) -> tarfile.TarFile:
    """Drain :func:`iter_archive_bytes` and open the result as a tarfile —
    the same bytes a client of ``GET /api/backup`` would receive, just
    collected in memory instead of streamed over a socket."""
    data = b"".join(iter_archive_bytes(home))
    return tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")


def test_archive_filename_is_timestamped_and_stable_within_a_second() -> None:
    name = archive_filename(now=1_800_000_000)
    assert name == "palaia-backup-20270115T080000Z.tar.gz"
    assert archive_filename(now=1_800_000_000) == name


def test_media_type_is_gzip() -> None:
    assert ARCHIVE_MEDIA_TYPE == "application/gzip"


def test_plain_files_and_directory_structure_are_preserved(tmp_path: Path) -> None:
    home = tmp_path
    (home / "config.yaml").write_text("mode: locked\n", encoding="utf-8")
    vault = home / "vaults" / "work"
    vault.mkdir(parents=True)
    (vault / "note.md").write_text("# hi\n\nbody\n", encoding="utf-8")

    with build_archive(home) as tar:
        names = set(tar.getnames())
        assert "config.yaml" in names
        assert "vaults/work/note.md" in names
        content = tar.extractfile("vaults/work/note.md")
        assert content is not None
        assert content.read() == b"# hi\n\nbody\n"


def test_the_vault_search_index_is_excluded(tmp_path: Path) -> None:
    home = tmp_path
    palaia_dir = home / "vaults" / "work" / ".palaia"
    palaia_dir.mkdir(parents=True)
    index_path = palaia_dir / "index.sqlite3"
    conn = sqlite3.connect(str(index_path))
    conn.execute("CREATE TABLE notes(permalink TEXT)")
    conn.commit()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.close()
    assert index_path.name == Path(INDEX_RELATIVE_PATH).name

    with build_archive(home) as tar:
        names = tar.getnames()
        assert not any(name.endswith("index.sqlite3") for name in names), names
        assert not any("index.sqlite3-" in name for name in names), names
        # The directory that *held* the index is still there — nothing about
        # excluding the index should hide the rest of the vault's engine
        # storage were something else ever to live alongside it.
        assert "vaults/work/.palaia" in names


def test_a_deeply_nested_vault_path_still_has_its_index_excluded(tmp_path: Path) -> None:
    """The exclusion matches by *tail*, not by a fixed depth — a vault
    registered at a custom path still under `home` must be covered."""
    home = tmp_path
    nested = home / "custom" / "place" / "my-vault" / ".palaia"
    nested.mkdir(parents=True)
    (nested / "index.sqlite3").write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)

    with build_archive(home) as tar:
        names = tar.getnames()
        assert not any(name.endswith("index.sqlite3") for name in names), names


def test_sqlite_databases_are_found_by_content_not_extension(tmp_path: Path) -> None:
    """`stash.db`/`directory.db`/`messenger.db` are real SQLite databases
    under a `.db` name (`curator/wiring.py`, `serve.py`) — the archive must
    snapshot them the same consistent way as every `.sqlite3` store."""
    home = tmp_path
    db_path = home / "stash.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE entries(k TEXT, v TEXT)")
    conn.execute("INSERT INTO entries VALUES ('key', 'value')")
    conn.commit()
    conn.close()

    with build_archive(home) as tar:
        member = tar.extractfile("stash.db")
        assert member is not None
        snapshot_bytes = member.read()

    restored_path = tmp_path / "restored-stash.db"
    restored_path.write_bytes(snapshot_bytes)
    restored = sqlite3.connect(str(restored_path))
    row = restored.execute("SELECT v FROM entries WHERE k = 'key'").fetchone()
    assert row == ("value",)
    restored.close()


def test_a_sqlite_snapshot_includes_wal_resident_data_and_omits_the_wal_file(
    tmp_path: Path,
) -> None:
    """The consistency claim, proven: data committed but still sitting in
    `-wal` (never checkpointed) makes it into the snapshot, and the raw
    `-wal`/`-shm` files themselves are never added as their own members."""
    home = tmp_path
    db_path = home / "secrets.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE secrets(name TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.execute("INSERT INTO secrets VALUES ('github-token', 'ghp_super_secret')")
    conn.commit()  # committed, but WAL checkpoints on its own schedule
    assert (home / "secrets.sqlite3-wal").exists(), "test setup assumption: WAL is active"

    try:
        with build_archive(home) as tar:
            names = tar.getnames()
            assert "secrets.sqlite3" in names
            assert "secrets.sqlite3-wal" not in names
            assert "secrets.sqlite3-shm" not in names
            member = tar.extractfile("secrets.sqlite3")
            assert member is not None
            snapshot_bytes = member.read()
    finally:
        conn.close()

    # Restored to a real file rather than `:memory:`: the snapshot's own
    # header still says `journal_mode=WAL` (copied verbatim from the
    # source), and SQLite's `:memory:` databases cannot honor that — this
    # is exactly what a real restore does (write the archive member back to
    # a file on disk), so that is what this proves against.
    restored_path = tmp_path / "restored-secrets.sqlite3"
    restored_path.write_bytes(snapshot_bytes)
    restored = sqlite3.connect(str(restored_path))
    value = restored.execute(
        "SELECT value FROM secrets WHERE name = 'github-token'"
    ).fetchone()
    assert value == ("ghp_super_secret",)
    restored.close()


def test_the_secret_key_file_travels_alongside_the_secret_store(tmp_path: Path) -> None:
    """Not a SQLite file at all — a raw Fernet key
    (`upstream/secrets.py::SECRETS_KEY_NAME`) — so it must go through the
    plain-copy path, not be silently skipped as some kind of sibling."""
    home = tmp_path
    (home / "secrets.key").write_bytes(b"\x01" * 32)

    with build_archive(home) as tar:
        member = tar.extractfile("secrets.key")
        assert member is not None
        assert member.read() == b"\x01" * 32


def test_an_empty_home_yields_a_valid_empty_archive(tmp_path: Path) -> None:
    home = tmp_path / "brand-new"
    home.mkdir()

    with build_archive(home) as tar:
        assert tar.getnames() == []


def test_a_symlink_is_never_followed_or_stored(tmp_path: Path) -> None:
    home = tmp_path
    (home / "real.md").write_text("real content\n", encoding="utf-8")
    outside = tmp_path.parent / "outside-secret.md"
    outside.write_text("should never appear in a backup\n", encoding="utf-8")
    link = home / "link.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not supported on this filesystem")

    with build_archive(home) as tar:
        names = tar.getnames()
        assert "real.md" in names
        assert "link.md" not in names
