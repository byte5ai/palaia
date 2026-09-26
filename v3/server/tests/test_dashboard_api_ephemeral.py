"""Issue #168: ephemeral (task-bound) vaults — create, promote, close.

Covers the manifest round trip in the engine, the three dashboard routes
(``POST /api/vaults`` with ``ephemeral``/``ttl_days``, ``POST .../promote``,
``POST .../close``), the live unmount on a running
:class:`~palaia_hub.gateway.dynamic.DynamicGateway`, and the doctor's
``ephemeral-expired`` finding.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.doctor import DoctorContext
from palaia_hub.doctor.checks import VaultsCheck
from palaia_hub.gateway.build import GatewayConfigError
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.dynamic import DynamicGateway
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.index import VaultIndex
from palaia_hub.vault import VaultConfigError, VaultRegistry
from palaia_hub.vault.engine import VaultEngine
from palaia_hub.vault.watcher import VaultWatcher

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Hub:
    def __init__(self, tmp_path: Path) -> None:
        self.registry = VaultRegistry(tmp_path / "home")
        self.indexes: dict[str, VaultIndex] = {}
        self.watchers: dict[str, VaultWatcher] = {}
        self.gateway = DynamicGateway(GatewayConfig(), {})
        self.client = TestClient(
            create_app(
                HubConfig(),
                vault_registry=self.registry,
                indexes=self.indexes,
                vault_watchers=self.watchers,
                dynamic_gateway=self.gateway,
            )
        )


@pytest.fixture
def hub(tmp_path: Path) -> _Hub:
    return _Hub(tmp_path)


async def _seed(registry: VaultRegistry, vault: str, *notes: tuple[str, str, str]) -> None:
    engine = await registry.get(vault)
    for path, title, body in notes:
        await engine.write_note(path, title=title, body=body, frontmatter={"tags": ["infra"]})


# ------------------------------------------------------------------ engine


async def test_manifest_round_trips_lifecycle_and_expiry(tmp_path: Path) -> None:
    expires = datetime(2031, 1, 2, 3, 4, 5, tzinfo=UTC)
    engine = VaultEngine(tmp_path / "trip", "trip")
    info = await engine.open(purpose="One trip.", ephemeral=True, expires=expires)
    assert info.ephemeral is True
    assert info.expires == "2031-01-02T03:04:05Z"

    manifest = (tmp_path / "trip" / "meta" / "vault.md").read_text(encoding="utf-8")
    assert "lifecycle: ephemeral" in manifest
    assert "2031-01-02T03:04:05Z" in manifest

    reopened = VaultEngine(tmp_path / "trip", "trip")
    again = await reopened.open(create=False)
    assert (again.ephemeral, again.expires) == (True, "2031-01-02T03:04:05Z")


async def test_a_plain_vault_is_not_ephemeral(tmp_path: Path) -> None:
    info = await VaultEngine(tmp_path / "work", "work").open(purpose="Work.")
    assert (info.ephemeral, info.expires) == (False, None)
    assert info.expired() is False
    manifest = (tmp_path / "work" / "meta" / "vault.md").read_text(encoding="utf-8")
    assert "lifecycle" not in manifest


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # A hand edit without quotes: YAML hands these back as datetime/date.
        ("2030-05-06T07:08:09Z", "2030-05-06T07:08:09Z"),
        ("2030-05-06", "2030-05-06T00:00:00Z"),
        ("'2030-05-06T09:08:09+02:00'", "2030-05-06T07:08:09Z"),
        ("not a date", None),
    ],
)
async def test_hand_edited_expiry_is_normalized(
    tmp_path: Path, raw: str, expected: str | None
) -> None:
    engine = VaultEngine(tmp_path / "trip", "trip")
    await engine.open(purpose="One trip.", ephemeral=True)
    manifest = tmp_path / "trip" / "meta" / "vault.md"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(
        text.replace("lifecycle: ephemeral", f"lifecycle: ephemeral\nexpires: {raw}")
    )

    info = await VaultEngine(tmp_path / "trip", "trip").open(create=False)
    assert info.ephemeral is True
    assert info.expires == expected


async def test_only_an_ephemeral_vault_can_expire(tmp_path: Path) -> None:
    with pytest.raises(VaultConfigError):
        await VaultEngine(tmp_path / "work", "work").open(expires=datetime.now(tz=UTC))


# ------------------------------------------------------------ REST: create


def test_create_ephemeral_vault_with_a_time_limit(hub: _Hub) -> None:
    with hub.client as client:
        before = datetime.now(tz=UTC)
        response = client.post(
            "/api/vaults",
            json={
                "key": "trip",
                "purpose": "Research for one trip.",
                "ephemeral": True,
                "ttl_days": 7,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ephemeral"] is True
        expires = datetime.fromisoformat(body["expires"])
        assert before + timedelta(days=7) - timedelta(seconds=5) <= expires
        assert expires <= datetime.now(tz=UTC) + timedelta(days=7)

        listed = {v["key"]: v for v in client.get("/api/vaults").json()}
        assert listed["trip"]["ephemeral"] is True


def test_plain_vault_reports_not_ephemeral(hub: _Hub) -> None:
    with hub.client as client:
        body = client.post("/api/vaults", json={"key": "work"}).json()
    assert body["ephemeral"] is False
    assert body["expires"] is None


def test_time_limit_without_ephemeral_is_refused(hub: _Hub) -> None:
    with hub.client as client:
        response = client.post("/api/vaults", json={"key": "work", "ttl_days": 3})
        assert response.status_code == 400
        assert "ephemeral" in response.json()["detail"]
        assert client.get("/api/vaults").json() == []


def test_time_limit_must_be_positive(hub: _Hub) -> None:
    with hub.client as client:
        response = client.post(
            "/api/vaults", json={"key": "trip", "ephemeral": True, "ttl_days": 0}
        )
    assert response.status_code == 422


# ----------------------------------------------------------- REST: promote


def _two_vaults(hub: _Hub, client: TestClient) -> None:
    assert client.post("/api/vaults", json={"key": "work"}).status_code == 200
    assert client.post("/api/vaults", json={"key": "trip", "ephemeral": True}).status_code == 200
    client.portal.call(  # type: ignore[union-attr]
        _seed,
        hub.registry,
        "trip",
        ("findings/rate-limits.md", "Rate limits", "The API allows 100 req/min.\n"),
        ("findings/retry-policy.md", "Retry policy", "Back off; see [[Rate limits]].\n"),
        ("scratch.md", "Scratch", "Throwaway.\n"),
    )


def test_promote_copies_notes_with_identity_and_frontmatter(hub: _Hub) -> None:
    with hub.client as client:
        _two_vaults(hub, client)
        response = client.post(
            "/api/vaults/trip/promote",
            json={"target": "work", "notes": ["findings/rate-limits", "Retry policy"]},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source"] == "trip"
        assert body["target"] == "work"
        assert [n["path"] for n in body["promoted"]] == [
            "findings/rate-limits.md",
            "findings/retry-policy.md",
        ]

        note = client.get("/api/vaults/work/notes/findings/rate-limits").json()
        assert note["title"] == "Rate limits"
        assert "100 req/min" in note["body"]
        # The source keeps its notes: promotion copies, closing is separate.
        assert client.get("/api/vaults/trip/notes/findings/rate-limits").status_code == 200

    promoted = hub.registry.home / "vaults" / "work" / "findings" / "rate-limits.md"
    text = promoted.read_text(encoding="utf-8")
    assert "permalink: findings/rate-limits" in text
    assert "infra" in text  # the source note's tags came along


def test_promote_refuses_a_collision_and_writes_nothing(hub: _Hub) -> None:
    with hub.client as client:
        _two_vaults(hub, client)
        client.portal.call(  # type: ignore[union-attr]
            _seed, hub.registry, "work", ("findings/retry-policy.md", "Retry policy", "Mine.\n")
        )
        response = client.post(
            "/api/vaults/trip/promote",
            json={"target": "work", "notes": ["findings/rate-limits", "findings/retry-policy"]},
        )
        assert response.status_code == 409
        assert "Nothing was copied" in response.json()["detail"]
        # All-or-nothing: the first, non-colliding note was not written either.
        assert client.get("/api/vaults/work/notes/findings/rate-limits").status_code == 404


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"target": "work", "notes": ["no-such-note"]}, 404),
        ({"target": "nowhere", "notes": ["scratch"]}, 404),
        ({"target": "trip", "notes": ["scratch"]}, 400),
        ({"target": "work", "notes": ["meta/vault"]}, 400),
        ({"target": "work", "notes": ["scratch", "scratch.md"]}, 400),
        ({"target": "work", "notes": []}, 422),
    ],
)
def test_promote_refusals(hub: _Hub, payload: dict[str, object], status: int) -> None:
    with hub.client as client:
        _two_vaults(hub, client)
        response = client.post("/api/vaults/trip/promote", json=payload)
        assert response.status_code == status, response.text
        assert client.get("/api/vaults/work/notes/scratch").status_code == 404


# ------------------------------------------------------------- REST: close


def test_close_archives_the_vault_and_unmounts_it_live(hub: _Hub) -> None:
    with hub.client as client:
        _two_vaults(hub, client)
        vault_dir = hub.registry.home / "vaults" / "trip"
        assert "trip" in hub.indexes and "trip" in hub.watchers
        assert {v.key for v in hub.gateway.config.vaults} == {"work", "trip"}

        response = client.post("/api/vaults/trip/close", json={"confirm": "trip"})
        assert response.status_code == 200, response.text
        archived = Path(response.json()["archived_to"])

        # Files kept, just moved aside: notes and git history both.
        assert not vault_dir.exists()
        assert archived.parent == hub.registry.archive_dir
        assert (archived / "findings" / "rate-limits.md").exists()
        assert (archived / ".git").is_dir()

        # Gone from the hub: registry, REST, index, watcher, gateway.
        assert "trip" not in hub.registry
        assert [v["key"] for v in client.get("/api/vaults").json()] == ["work"]
        assert client.get("/api/vaults/trip/notes").status_code == 404
        assert "trip" not in hub.indexes and "trip" not in hub.watchers
        assert [v.key for v in hub.gateway.config.vaults] == ["work"]
        default = next(p for p in hub.gateway.config.profiles if p.path == "default")
        assert default.vaults == ["work"]

        # The name is free again, and a new vault under it starts empty.
        again = client.post("/api/vaults", json={"key": "trip", "ephemeral": True})
        assert again.status_code == 200
        assert again.json()["note_count"] == 1  # just the manifest


def test_close_needs_the_exact_confirmation(hub: _Hub) -> None:
    with hub.client as client:
        _two_vaults(hub, client)
        response = client.post("/api/vaults/trip/close", json={"confirm": "work"})
        assert response.status_code == 400
        assert "trip" in hub.registry


def test_close_refuses_a_long_lived_vault(hub: _Hub) -> None:
    with hub.client as client:
        _two_vaults(hub, client)
        response = client.post("/api/vaults/work/close", json={"confirm": "work"})
        assert response.status_code == 409
        assert "work" in hub.registry
        assert (hub.registry.home / "vaults" / "work").exists()


def test_close_unknown_vault_is_404(hub: _Hub) -> None:
    with hub.client as client:
        response = client.post("/api/vaults/nope/close", json={"confirm": "nope"})
    assert response.status_code == 404


# ---------------------------------------------------- gateway: remove_vault


async def test_remove_vault_drops_its_tools_and_keeps_the_profile() -> None:
    config = GatewayConfig(
        vaults=[
            VaultMountConfig(key="work", name="work", purpose="Work vault."),
            VaultMountConfig(key="trip", name="trip", purpose="One trip."),
        ],
        profiles=[
            ProfileConfig(path="default", vaults=["work", "trip"]),
            ProfileConfig(path="solo", vaults=["trip"]),
        ],
    )
    gateway = DynamicGateway(config, {"work": FakeVaultService(), "trip": FakeVaultService()})
    await gateway.start()

    rebuilt = await gateway.remove_vault("trip")
    assert sorted(rebuilt) == ["default", "solo"]

    async with Client(gateway.profile_servers["default"]) as client:
        names = {t.name for t in await client.list_tools()}
    assert "work_memory_search" in names
    assert not any(name.startswith("trip_") for name in names)
    # A profile left with no vault stays mounted rather than vanishing.
    assert "solo" in gateway.profile_servers

    with pytest.raises(GatewayConfigError):
        await gateway.remove_vault("trip")
    await gateway.aclose()


# ------------------------------------------------------------------ doctor


async def test_doctor_warns_about_an_overdue_ephemeral_vault(tmp_path: Path) -> None:
    overdue = VaultEngine(tmp_path / "trip", "trip")
    await overdue.open(ephemeral=True, expires=datetime.now(tz=UTC) - timedelta(days=1))
    current = VaultEngine(tmp_path / "next", "next")
    await current.open(ephemeral=True, expires=datetime.now(tz=UTC) + timedelta(days=1))
    plain = VaultEngine(tmp_path / "work", "work")
    await plain.open()

    context = DoctorContext(
        config=HubConfig(),
        home=tmp_path,
        vaults={"trip": overdue, "next": current, "work": plain},
    )
    findings = [f for f in await VaultsCheck().run(context) if f.code == "ephemeral-expired"]
    assert [f.subject for f in findings] == ["trip"]
    assert findings[0].severity == "warning"
    assert findings[0].repairable is False
    assert "/api/vaults/trip/close" in findings[0].fix
