"""Registry: many vaults, physically isolated storage, persisted pointers."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import TEST_POLICY

from palaia_hub.vault import (
    NoteNotFoundError,
    VaultConfigError,
    VaultNotFoundError,
    VaultRegistry,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def registry(tmp_path: Path) -> VaultRegistry:
    return VaultRegistry(tmp_path / "home", policy=TEST_POLICY)


async def test_two_vaults_share_no_files_git_or_engine_state(
    registry: VaultRegistry, tmp_path: Path
) -> None:
    work = await registry.create("work", tmp_path / "vaults/work", purpose="Work knowledge.")
    personal = await registry.create(
        "personal", tmp_path / "vaults/personal", purpose="Personal knowledge."
    )

    await work.write_note("notes/secret-work", body="work only\n", title="Secret Work")
    await personal.write_note("notes/secret-home", body="home only\n", title="Secret Home")

    # Physically separate directories, git repositories and engine storage.
    assert work.root != personal.root
    assert work.git.git_dir != personal.git.git_dir
    assert work.engine_dir != personal.engine_dir
    assert (work.root / "notes/secret-work.md").exists()
    assert not (personal.root / "notes/secret-work.md").exists()

    # A search-shaped lookup in one vault can never reach into the other.
    assert "notes/secret-work.md" in work.catalog
    assert "notes/secret-work.md" not in personal.catalog
    with pytest.raises(NoteNotFoundError):
        await personal.read_note("notes/secret-work")

    # Separate histories.
    work_log = {commit.subject for commit in work.git.log()}
    personal_log = {commit.subject for commit in personal.git.log()}
    assert not (work_log & personal_log) or work_log != personal_log
    assert any("secret-work" in subject for subject in work_log)
    assert not any("secret-work" in subject for subject in personal_log)


async def test_registry_persists_and_reloads(registry: VaultRegistry, tmp_path: Path) -> None:
    await registry.create("work", tmp_path / "vaults/work", purpose="Work.")
    payload = yaml.safe_load(registry.registry_path.read_text(encoding="utf-8"))
    assert payload == {"vaults": [{"name": "work", "path": str(tmp_path / "vaults/work")}]}

    reloaded = VaultRegistry(registry.home, policy=TEST_POLICY)
    assert reloaded.names() == ["work"]
    engine = await reloaded.get("work")
    assert engine.info().purpose == "Work."
    assert engine.opened


async def test_manifest_purpose_and_name_reach_the_registry_info(
    registry: VaultRegistry, tmp_path: Path
) -> None:
    await registry.create("work", tmp_path / "vaults/work", purpose="Team knowledge.")
    infos = await registry.info()
    assert [(info.name, info.purpose, info.writable) for info in infos] == [
        ("work", "Team knowledge.", True)
    ]


async def test_duplicate_name_is_refused(registry: VaultRegistry, tmp_path: Path) -> None:
    await registry.create("work", tmp_path / "vaults/work")
    with pytest.raises(VaultConfigError, match="already registered"):
        await registry.create("work", tmp_path / "vaults/other")


async def test_shared_or_nested_paths_are_refused(
    registry: VaultRegistry, tmp_path: Path
) -> None:
    await registry.create("work", tmp_path / "vaults/work")
    with pytest.raises(VaultConfigError, match="share its directory"):
        await registry.create("copy", tmp_path / "vaults/work")
    with pytest.raises(VaultConfigError, match="nested"):
        await registry.create("inner", tmp_path / "vaults/work/inner")
    with pytest.raises(VaultConfigError, match="nested"):
        await registry.create("outer", tmp_path / "vaults")


@pytest.mark.parametrize("name", ["Work", "with space", "-leading", "a" * 33, ""])
async def test_invalid_names_are_refused(
    registry: VaultRegistry, tmp_path: Path, name: str
) -> None:
    with pytest.raises(VaultConfigError, match="invalid"):
        await registry.create(name, tmp_path / "vaults/x")


async def test_unregister_keeps_the_files(registry: VaultRegistry, tmp_path: Path) -> None:
    engine = await registry.create("work", tmp_path / "vaults/work")
    await engine.write_note("notes/a", body="x\n", title="A")
    record = registry.unregister("work")
    assert record.path == tmp_path / "vaults/work"
    assert (record.path / "notes/a.md").exists()
    assert registry.names() == []
    with pytest.raises(VaultNotFoundError):
        await registry.get("work")


async def test_register_adopts_an_existing_vault(registry: VaultRegistry, tmp_path: Path) -> None:
    engine = await registry.create("work", tmp_path / "vaults/work")
    await engine.write_note("notes/a", body="x\n", title="A")
    registry.unregister("work")

    adopted = await registry.register("work", tmp_path / "vaults/work")
    note = await adopted.read_note("notes/a")
    assert note.body == "x\n"


async def test_register_refuses_a_directory_that_is_not_a_vault(
    registry: VaultRegistry, tmp_path: Path
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(VaultNotFoundError):
        await registry.register("plain", plain)


def test_registry_defaults_to_the_hub_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path / "hub-home"))
    registry = VaultRegistry()
    assert registry.registry_path == tmp_path / "hub-home" / "vaults.yaml"


async def test_broken_registry_file_fails_loudly(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "vaults.yaml").write_text("vaults: not-a-list\n", encoding="utf-8")
    with pytest.raises(VaultConfigError, match="vaults"):
        VaultRegistry(home)
