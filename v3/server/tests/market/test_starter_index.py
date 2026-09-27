"""The bundled starter index offers only what can actually be installed.

Issue #409: the starter index shipped two container entries, "Fetch" and
"Filesystem", whose images (``ghcr.io/palaia/addon-*``) were never
published. The marketplace offered them and every install failed. These
tests keep that from coming back: each container image in the starter index
must resolve in its registry.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from palaia_hub.market.curated import load_starter_index


def _container_images() -> list[str]:
    return [
        str(entry["source"]["value"])
        for entry in load_starter_index()["entries"]
        if entry.get("kind") == "container" and entry["source"]["type"] == "image"
    ]


def test_the_starter_index_loads_and_has_its_shape() -> None:
    document = load_starter_index()
    assert isinstance(document["entries"], list)


def test_the_unpublished_starter_add_ons_are_gone() -> None:
    images = _container_images()
    assert not any(image.startswith("ghcr.io/palaia/") for image in images), images


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not on PATH")
@pytest.mark.parametrize(
    "image",
    _container_images()
    or [
        pytest.param(
            None, marks=pytest.mark.skip(reason="the starter index bundles no container image")
        )
    ],
)
def test_every_bundled_container_image_exists(image: str) -> None:
    result = subprocess.run(  # noqa: S603, S607 - fixed argv, no shell
        ["docker", "manifest", "inspect", image],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (
        f"{image} is offered in the marketplace but does not resolve: {result.stderr.strip()}"
    )
