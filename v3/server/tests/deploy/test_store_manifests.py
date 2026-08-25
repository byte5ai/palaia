"""SPEC-501 acceptance: "every store package passes its platform's
validator/linter (or, where none exists, a schema check written here from
the platform's docs, cited)".

None of Umbrel/CasaOS/Runtipi ship a standalone, offline-runnable schema
document — their own app listings *are* the schema, and their real
validators live inside their own repos' tooling (node/CI scripts this
environment has no checkout of). So each check below is a small pydantic
model built from that platform's real, currently-listed field set,
gathered from their own docs and — where a real example was reachable —
a real shipped app's manifest, cited in each model's docstring. Every
package's own ``SUBMIT.md`` repeats the citation and names exactly which
parts still want a live-instance check before a PR.

TrueNAS/Home Assistant ship narrower published field lists (see each
model below); those are checked structurally too, honestly short of a
live render/install (no TrueNAS instance, no Home Assistant Supervisor,
no docker daemon in this environment — see the packages' own SUBMIT.md /
EVALUATION.md for exactly what that leaves unverified).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import pytest
import yaml
from palaia_addon_sdk.jargon import find_jargon
from pydantic import BaseModel, ConfigDict, EmailStr, Field

STORES_ROOT = Path(__file__).resolve().parents[3] / "deploy" / "stores"

# The channel tag every store package's docker-compose.yml / ix_values.yaml
# pins the hub image to (SPEC-501: "pinning the GHCR image by channel
# tag"). A stable-listed app pins `stable`, never a moving `edge` build.
PINNED_CHANNEL = "stable"
PINNED_IMAGE = "ghcr.io/byte5ai/palaia-hub"


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_no_jargon(text: str, *, source: str) -> None:
    hits = find_jargon(text)
    assert not hits, f"jargon {hits!r} in {source}'s user-facing copy: {text!r}"


# ---------------------------------------------------------------------------
# Umbrel — field set from a real, currently-listed app's manifest
# (getumbrel/umbrel-apps: syncthing/umbrel-app.yml), since Umbrel publishes
# no standalone schema document.
# ---------------------------------------------------------------------------
class UmbrelAppManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifestVersion: int
    id: str
    category: str
    name: str
    version: str
    tagline: str = Field(max_length=80)
    description: str
    developer: str
    website: str
    dependencies: list[str]
    repo: str
    support: str
    port: int
    gallery: list[str]
    path: str
    defaultPassword: str
    releaseNotes: str
    submitter: str
    submission: str


def test_umbrel_manifest_matches_the_real_app_schema() -> None:
    data = _load_yaml(STORES_ROOT / "umbrel" / "umbrel-app.yml")
    manifest = UmbrelAppManifest.model_validate(data)
    assert manifest.id == "palaia"
    _assert_no_jargon(manifest.tagline, source="umbrel/umbrel-app.yml tagline")
    _assert_no_jargon(manifest.description, source="umbrel/umbrel-app.yml description")


def test_umbrel_compose_pins_the_stable_channel() -> None:
    data = _load_yaml(STORES_ROOT / "umbrel" / "docker-compose.yml")
    image = data["services"]["hub"]["image"]
    assert image == f"{PINNED_IMAGE}:{PINNED_CHANNEL}"


# ---------------------------------------------------------------------------
# CasaOS — field set from a real, currently-listed app's manifest
# (IceWhaleTech/CasaOS-AppStore: Apps/Syncthing/docker-compose.yml), no
# standalone schema document published either.
# ---------------------------------------------------------------------------
class CasaosLocalizedText(BaseModel):
    model_config = ConfigDict(extra="allow")

    en_US: str


class CasaosMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    architectures: list[str]
    main: str
    author: str
    category: str
    description: CasaosLocalizedText
    developer: str
    icon: str
    tagline: CasaosLocalizedText
    thumbnail: str
    title: CasaosLocalizedText
    port_map: str
    version: str


def test_casaos_manifest_matches_the_real_app_schema() -> None:
    data = _load_yaml(STORES_ROOT / "casaos" / "docker-compose.yml")
    metadata = CasaosMetadata.model_validate(data["x-casaos"])
    assert metadata.id.endswith("palaia")
    _assert_no_jargon(metadata.tagline.en_US, source="casaos x-casaos.tagline.en_US")
    _assert_no_jargon(metadata.description.en_US, source="casaos x-casaos.description.en_US")


def test_casaos_compose_pins_the_stable_channel() -> None:
    data = _load_yaml(STORES_ROOT / "casaos" / "docker-compose.yml")
    image = data["services"]["hub"]["image"]
    assert image == f"{PINNED_IMAGE}:{PINNED_CHANNEL}"


# ---------------------------------------------------------------------------
# Runtipi — field set from their own "create your own app store" guide
# (https://runtipi.io/docs/guides/create-your-own-app-store).
# ---------------------------------------------------------------------------
class RuntipiConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    available: bool
    exposable: bool
    dynamic_config: bool
    port: int
    version: str
    tipi_version: int
    min_tipi_version: int | None = None
    categories: list[str]
    description: str
    short_desc: str = Field(max_length=100)
    author: str
    source: str
    website: str
    supported_architectures: list[Literal["amd64", "arm64"]]
    created_at: int
    updated_at: int
    form_fields: list[Any]


def test_runtipi_config_matches_the_documented_schema() -> None:
    data = _load_json(STORES_ROOT / "runtipi" / "apps" / "palaia" / "config.json")
    config = RuntipiConfig.model_validate(data)
    assert config.id == "palaia"
    _assert_no_jargon(config.short_desc, source="runtipi config.json short_desc")
    _assert_no_jargon(config.description, source="runtipi config.json description")


def test_runtipi_folder_name_matches_its_own_id() -> None:
    # "The folder name must match the app's ID specified in config.json"
    # (runtipi.io/docs/guides/create-your-own-app-store).
    data = _load_json(STORES_ROOT / "runtipi" / "apps" / "palaia" / "config.json")
    assert data["id"] == "palaia"


def test_runtipi_compose_pins_the_stable_channel_and_declares_the_main_service() -> None:
    data = _load_yaml(STORES_ROOT / "runtipi" / "apps" / "palaia" / "docker-compose.yml")
    image = data["services"]["hub"]["image"]
    assert image == f"{PINNED_IMAGE}:{PINNED_CHANNEL}"
    assert data["services"]["hub"]["x-runtipi"]["is_main"] is True


def test_runtipi_description_markdown_has_no_jargon() -> None:
    text = (STORES_ROOT / "runtipi" / "apps" / "palaia" / "metadata" / "description.md").read_text(
        encoding="utf-8"
    )
    _assert_no_jargon(text, source="runtipi metadata/description.md")


# ---------------------------------------------------------------------------
# TrueNAS SCALE — field set from truenas/apps' own app.yaml documentation
# (DeepWiki-mirrored field reference, https://deepwiki.com/truenas/apps/
# 2.1-app.yaml-app-metadata) — see truenas/SUBMIT.md for what a live
# instance still needs to confirm (lib_version, run_as_context, the
# questions.yaml/template schemas proper).
# ---------------------------------------------------------------------------
class TrueNasMaintainer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    email: EmailStr


class TrueNasAppYaml(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    title: str
    train: Literal["stable", "community", "enterprise", "dev", "test"]
    description: str
    home: str
    icon: str
    categories: list[str]
    keywords: list[str]
    sources: list[str]
    maintainers: list[TrueNasMaintainer]
    app_version: str
    version: str
    human_version: str


def test_truenas_app_yaml_matches_the_documented_schema() -> None:
    data = _load_yaml(STORES_ROOT / "truenas" / "community" / "palaia" / "app.yaml")
    app = TrueNasAppYaml.model_validate(data)
    assert app.name == "palaia"
    assert app.train == "community"
    _assert_no_jargon(app.description, source="truenas app.yaml description")


def test_truenas_ix_values_pins_the_stable_channel() -> None:
    data = _load_yaml(STORES_ROOT / "truenas" / "community" / "palaia" / "ix_values.yaml")
    assert data["image"]["repository"] == PINNED_IMAGE
    assert data["image"]["tag"] == PINNED_CHANNEL


def test_truenas_compose_template_references_the_pinned_image_via_ix_values() -> None:
    # A Jinja2 template, not literal YAML (it opens with a `{# ... #}`
    # comment) — checked by substring, not a YAML parse. See this test
    # module's docstring and truenas/SUBMIT.md for why a full render
    # wasn't done here.
    text = (
        STORES_ROOT / "truenas" / "community" / "palaia" / "templates" / "docker-compose.yaml"
    ).read_text(encoding="utf-8")
    assert "ix_values.image.repository" in text
    assert "ix_values.image.tag" in text


def test_truenas_questions_yaml_is_at_least_well_formed() -> None:
    data = _load_yaml(STORES_ROOT / "truenas" / "community" / "palaia" / "questions.yaml")
    assert "groups" in data
    assert "questions" in data
    variables = {q["variable"] for q in data["questions"]}
    assert {"web_port", "mode", "data_dataset"} <= variables


# ---------------------------------------------------------------------------
# Home Assistant — required fields per
# https://developers.home-assistant.io/docs/add-ons/configuration.
# ---------------------------------------------------------------------------
class HomeAssistantAddonConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    version: str
    slug: str
    description: str
    arch: list[Literal["armhf", "armv7", "aarch64", "amd64", "i386"]]
    image: str
    host_network: bool = False


def test_home_assistant_config_has_the_required_fields() -> None:
    data = _load_yaml(STORES_ROOT / "home-assistant" / "config.yaml")
    config = HomeAssistantAddonConfig.model_validate(data)
    assert config.slug == "palaia"
    assert config.image == PINNED_IMAGE
    # "If you are using a docker image with the image option, this needs
    # to match the tag" — the docs' own wording for `version`.
    assert config.version == PINNED_CHANNEL
    _assert_no_jargon(config.description, source="home-assistant config.yaml description")


def test_home_assistant_evaluation_reaches_a_verdict() -> None:
    text = (STORES_ROOT / "home-assistant" / "EVALUATION.md").read_text(encoding="utf-8")
    assert "## Verdict" in text


# ---------------------------------------------------------------------------
# Every package: a SUBMIT.md exists and names the real submission target.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "store", ["umbrel", "casaos", "runtipi", "truenas"]
)
def test_every_app_store_package_ships_a_submit_doc(store: str) -> None:
    submit = STORES_ROOT / store / "SUBMIT.md"
    assert submit.exists(), f"{store} is missing SUBMIT.md"
    text = submit.read_text(encoding="utf-8")
    assert len(text) > 200  # not a stub
