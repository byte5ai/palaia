from __future__ import annotations

from pathlib import Path

from palaia_hub.market.installed_store import InstalledAddonRecord, InstalledAddonStore


def _record(upstream_key: str = "palaia-fetch") -> InstalledAddonRecord:
    return InstalledAddonRecord(
        upstream_key=upstream_key,
        entry_id="palaia.fetch",
        name="Fetch",
        kind="container",
        provenance="curated",
        installed_ref="ghcr.io/palaia/addon-fetch:1.0.0",
        image="ghcr.io/palaia/addon-fetch:1.0.0",
        container_name="palaia-addon-fetch",
        installed_at=1234.5,
    )


def test_put_then_get_round_trips(tmp_path: Path) -> None:
    store = InstalledAddonStore(tmp_path / "installed.json")
    store.put(_record())

    got = store.get("palaia-fetch")
    assert got == _record()


def test_get_missing_returns_none(tmp_path: Path) -> None:
    store = InstalledAddonStore(tmp_path / "installed.json")
    assert store.get("nothing-here") is None


def test_list_is_sorted_by_key(tmp_path: Path) -> None:
    store = InstalledAddonStore(tmp_path / "installed.json")
    store.put(_record("zeta"))
    store.put(_record("alpha"))

    assert [r.upstream_key for r in store.list()] == ["alpha", "zeta"]


def test_delete_removes_the_record(tmp_path: Path) -> None:
    store = InstalledAddonStore(tmp_path / "installed.json")
    store.put(_record())

    assert store.delete("palaia-fetch") is True
    assert store.get("palaia-fetch") is None
    assert store.delete("palaia-fetch") is False


def test_a_fresh_store_with_no_file_yet_lists_empty(tmp_path: Path) -> None:
    store = InstalledAddonStore(tmp_path / "does-not-exist-yet.json")
    assert store.list() == []


def test_write_is_atomic_no_half_written_file_survives_a_second_write(tmp_path: Path) -> None:
    path = tmp_path / "installed.json"
    store = InstalledAddonStore(path)
    store.put(_record("one"))
    store.put(_record("two"))

    # No leftover .tmp sibling after two successful writes.
    assert not path.with_suffix(".tmp").exists()
    assert {r.upstream_key for r in store.list()} == {"one", "two"}
