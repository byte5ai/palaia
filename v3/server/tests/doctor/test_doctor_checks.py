"""What the shipped checks actually find (issue #296).

One test per finding that an owner would act on, plus the two repairs the
doctor is allowed to perform on its own.
"""

from __future__ import annotations

import stat
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path

import pytest

from palaia_hub.auth import TokenStore
from palaia_hub.config import HubConfig, config_file_path
from palaia_hub.curator.wiring import TOKEN_ENV
from palaia_hub.doctor import (
    CheckSkipped,
    ClientsCheck,
    ConfigCheck,
    DoctorContext,
    Finding,
    SearchCheck,
    StorageCheck,
    VaultsCheck,
)
from palaia_hub.index import EmbeddingConfig, VaultIndex
from palaia_hub.oauth import OAuthStore
from palaia_hub.vault import IndexEntry
from palaia_hub.vault.atomic import TEMP_SUFFIX
from palaia_hub.vault.engine import VaultEngine

pytestmark = pytest.mark.anyio

#: The ``make_vault`` fixture's shape (conftest.py). Restated rather than
#: imported: a plain ``import conftest`` only resolves through pytest's own
#: sys.path insertion, which is not a contract worth relying on.
VaultFactory = Callable[..., Awaitable[VaultEngine]]


def codes(findings: Iterable[Finding]) -> list[str]:
    return [finding.code for finding in findings]


def by_code(findings: Iterable[Finding], code: str) -> Finding:
    matches = [finding for finding in findings if finding.code == code]
    assert matches, f"no {code!r} finding in {codes(findings)}"
    return matches[0]


class FakeIndex:
    """Just enough index for the file↔index drift check to have an opinion."""

    def __init__(self, entries: list[IndexEntry]) -> None:
        self._entries = entries

    def index_entries(self) -> Iterable[IndexEntry]:
        return list(self._entries)


# --------------------------------------------------------------------- config


async def test_a_public_mode_without_a_public_address_is_flagged(home: Path) -> None:
    config = HubConfig(mode="cloud", host="127.0.0.1")
    findings = await ConfigCheck().run(DoctorContext(config=config, home=home))

    finding = by_code(findings, "public-address-missing")
    assert finding.severity == "warning"
    assert "exposure.public_url" in finding.fix


async def test_a_plaintext_public_address_is_an_error(home: Path) -> None:
    config = HubConfig(exposure={"public_url": "http://hub.lan"})
    findings = await ConfigCheck().run(DoctorContext(config=config, home=home))

    finding = by_code(findings, "public-address-plaintext")
    assert finding.severity == "error"
    assert "refuse a plaintext connection" in finding.detail


async def test_a_copied_example_address_is_flagged_as_a_placeholder(home: Path) -> None:
    config = HubConfig(oauth={"enabled": True, "issuer": "https://hub.example.com"})
    findings = await ConfigCheck().run(DoctorContext(config=config, home=home))

    finding = by_code(findings, "placeholder-value")
    assert finding.subject == "oauth.issuer"


async def test_oauth_without_an_issuer_is_an_error(home: Path) -> None:
    config = HubConfig(oauth={"enabled": True})
    findings = await ConfigCheck().run(DoctorContext(config=config, home=home))

    assert by_code(findings, "oauth-issuer-missing").severity == "error"


async def test_a_loopback_issuer_is_useless_to_a_remote_client(home: Path) -> None:
    config = HubConfig(
        mode="cloud",
        host="127.0.0.1",
        exposure={"public_url": "https://hub.ts.net"},
        oauth={"enabled": True, "issuer": "http://localhost:8420"},
    )
    findings = await ConfigCheck().run(DoctorContext(config=config, home=home))

    assert "oauth-issuer-local" in codes(findings)


async def test_a_locked_hub_listening_on_every_interface_is_flagged(home: Path) -> None:
    config = HubConfig(mode="locked", host="0.0.0.0")
    findings = await ConfigCheck().run(DoctorContext(config=config, home=home))

    assert by_code(findings, "bind-wider-than-mode").severity == "warning"


async def test_a_curator_with_no_token_cannot_sign_in(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    config = HubConfig(curator={"enabled": True})
    findings = await ConfigCheck().run(DoctorContext(config=config, home=home))

    assert TOKEN_ENV in by_code(findings, "curator-token-missing").fix

    monkeypatch.setenv(TOKEN_ENV, "plt_something")
    findings = await ConfigCheck().run(DoctorContext(config=config, home=home))
    assert "curator-token-missing" not in codes(findings)


async def test_a_default_config_has_nothing_to_report(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    assert await ConfigCheck().run(DoctorContext(config=HubConfig(), home=home)) == []


# --------------------------------------------------------------------- vaults


async def test_a_hub_with_no_vault_is_told_so(home: Path) -> None:
    findings = await VaultsCheck().run(DoctorContext(config=HubConfig(), home=home))

    assert by_code(findings, "no-vaults").severity == "warning"


async def test_vault_findings_carry_the_vault_they_are_about(
    home: Path, make_vault: VaultFactory
) -> None:
    engine: VaultEngine = await make_vault("work")
    # Crash residue: the engine sweeps this on open, so it has to land after.
    (engine.root / f"note.md{TEMP_SUFFIX}").write_text("half a write", encoding="utf-8")
    context = DoctorContext(config=HubConfig(), home=home, vaults={"work": engine})

    findings = await VaultsCheck().run(context)

    finding = by_code(findings, "orphan-temp-file")
    assert finding.subject is not None and finding.subject.startswith("work")
    assert finding.repairable is True


async def test_the_safe_vault_repairs_run_and_are_reported(
    home: Path, make_vault: VaultFactory
) -> None:
    engine: VaultEngine = await make_vault("work")
    leftover = engine.root / f"note.md{TEMP_SUFFIX}"
    leftover.write_text("half a write", encoding="utf-8")
    context = DoctorContext(config=HubConfig(), home=home, vaults={"work": engine})

    outcomes = await VaultsCheck().repair(context)

    assert [outcome.code for outcome in outcomes] == ["orphan-temp-file"]
    assert outcomes[0].subject == "work"
    assert not leftover.exists()
    assert "orphan-temp-file" not in codes(await VaultsCheck().run(context))


async def test_index_drift_collapses_into_one_actionable_finding(
    home: Path, make_vault: VaultFactory
) -> None:
    engine: VaultEngine = await make_vault("work")
    ghosts = [
        IndexEntry(permalink=f"work/ghost-{n}", path=f"ghost-{n}.md", checksum="0")
        for n in range(4)
    ]
    context = DoctorContext(
        config=HubConfig(),
        home=home,
        vaults={"work": engine},
        indexes={"work": FakeIndex(ghosts)},  # type: ignore[dict-item]
    )

    findings = await VaultsCheck().run(context)

    assert codes(findings).count("index-drift") == 1
    drift = by_code(findings, "index-drift")
    assert drift.subject == "work"
    assert drift.repairable is True
    assert "difference(s) between work's files" in drift.detail
    # The per-entry noise — one finding per ghost — never reaches the operator.
    assert not [code for code in codes(findings) if code.startswith("index-orphan")]


# --------------------------------------------------------------------- search


async def test_search_is_skipped_rather_than_green_when_there_is_no_vault(home: Path) -> None:
    with pytest.raises(CheckSkipped):
        await SearchCheck().run(DoctorContext(config=HubConfig(), home=home))


async def test_a_vault_without_an_index_cannot_be_searched(
    home: Path, make_vault: VaultFactory
) -> None:
    engine: VaultEngine = await make_vault("work")
    context = DoctorContext(config=HubConfig(), home=home, vaults={"work": engine})

    finding = by_code(await SearchCheck().run(context), "index-absent")

    assert finding.severity == "warning"
    assert finding.subject == "work"
    assert "notes themselves are untouched" in finding.detail


async def test_semantic_search_being_off_is_a_note_not_a_problem(
    home: Path, make_vault: VaultFactory
) -> None:
    engine: VaultEngine = await make_vault("work")
    index = VaultIndex(engine, embedding=EmbeddingConfig(enabled=False))
    await index.open(start_worker=False)
    try:
        context = DoctorContext(
            config=HubConfig(), home=home, vaults={"work": engine}, indexes={"work": index}
        )
        findings = await SearchCheck().run(context)
    finally:
        await index.close()

    assert "index-absent" not in codes(findings)
    finding = by_code(findings, "semantic-search-off")
    assert finding.severity == "info"
    assert "full-text search" in finding.detail.lower()
    assert all(other.severity != "error" for other in findings)


# -------------------------------------------------------------------- clients


async def test_clients_is_skipped_without_a_token_store(home: Path) -> None:
    with pytest.raises(CheckSkipped):
        await ClientsCheck().run(DoctorContext(config=HubConfig(), home=home))


async def test_a_hub_nothing_can_connect_to_says_so(home: Path) -> None:
    context = DoctorContext(config=HubConfig(), home=home, tokens=TokenStore(home))

    finding = by_code(await ClientsCheck().run(context), "no-way-in")

    assert "palaia-hub token create" in finding.fix


async def test_a_token_bound_to_a_vanished_profile_is_an_error(home: Path) -> None:
    store = TokenStore(home)
    created = store.create("claude-code", "retired", ["vault:work:read"])
    context = DoctorContext(
        config=HubConfig(), home=home, tokens=store, profiles=("default", "curator")
    )

    finding = by_code(await ClientsCheck().run(context), "token-unknown-profile")

    assert finding.severity == "error"
    assert finding.subject == created.info.id
    assert created.info.id in finding.fix


async def test_an_unknown_profile_list_condemns_nothing(home: Path) -> None:
    """``profiles=None`` means "could not be established", not "none exist" —
    a hub with no vault yet must not have all its tokens called invalid."""
    store = TokenStore(home)
    store.create("claude-code", "default", ["vault:work:read"])
    context = DoctorContext(config=HubConfig(), home=home, tokens=store, profiles=None)

    assert "token-unknown-profile" not in codes(await ClientsCheck().run(context))


async def test_never_connected_is_only_reported_from_inside_the_running_hub(home: Path) -> None:
    """``last_used_at`` lives in the hub process's memory, so a CLI pass sees
    ``None`` for every token and must not call them all unused."""
    store = TokenStore(home)
    store.create("claude-code", "default", ["vault:work:read"])
    kwargs = {"config": HubConfig(), "home": home, "tokens": store, "profiles": ("default",)}

    assert "token-never-connected" not in codes(await ClientsCheck().run(DoctorContext(**kwargs)))
    live = await ClientsCheck().run(DoctorContext(live=True, **kwargs))
    assert "token-never-connected" in codes(live)


async def test_oauth_without_an_owner_account_locks_everyone_out(home: Path) -> None:
    store = OAuthStore(home)
    store.open()
    config = HubConfig(oauth={"enabled": True, "issuer": "https://hub.ts.net"})
    context = DoctorContext(config=config, home=home, tokens=TokenStore(home), oauth=store)
    try:
        findings = await ClientsCheck().run(context)
    finally:
        store.close()

    assert by_code(findings, "oauth-no-owner").severity == "error"


async def test_oauth_enabled_before_the_first_start_is_only_a_note(home: Path) -> None:
    config = HubConfig(oauth={"enabled": True, "issuer": "https://hub.ts.net"})
    context = DoctorContext(config=config, home=home, tokens=TokenStore(home))

    assert by_code(await ClientsCheck().run(context), "oauth-not-started").severity == "info"


# -------------------------------------------------------------------- storage


async def test_a_config_others_can_read_is_flagged_and_narrowed(home: Path) -> None:
    path = config_file_path(home)
    path.write_text("mode: locked\n", encoding="utf-8")
    path.chmod(0o644)
    context = DoctorContext(config=HubConfig(), home=home)

    finding = by_code(await StorageCheck().run(context), "config-readable-by-others")
    assert finding.repairable is True
    assert "client secret" in finding.detail

    outcomes = await StorageCheck().repair(context)

    assert [outcome.code for outcome in outcomes] == ["config-readable-by-others"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "config-readable-by-others" not in codes(await StorageCheck().run(context))


async def test_an_already_narrow_config_needs_no_repair(home: Path) -> None:
    path = config_file_path(home)
    path.write_text("mode: locked\n", encoding="utf-8")
    path.chmod(0o600)
    context = DoctorContext(config=HubConfig(), home=home)

    assert "config-readable-by-others" not in codes(await StorageCheck().run(context))
    assert await StorageCheck().repair(context) == []
