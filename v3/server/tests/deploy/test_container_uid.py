"""Issue #329: the image's uid/gid is pinned, and every store package says so.

The app-store packages under ``v3/deploy/stores`` bind-mount a host directory
onto ``/data``. A bind mount keeps the host's ownership, so the process inside
must run as a *known* uid — one the package can declare with ``user:`` and an
operator can ``chown`` to. ``useradd --system`` without ``--uid`` hands out
whatever number the base image has free, which can change with a base-image
update; these tests pin the number in the Dockerfile and check that every
package declares the same one. The docker smoke test
(``server/tests/e2e/test_docker_one_liner_smoke.py``) asserts the running
container's uid on CI, where a daemon exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

DEPLOY = Path(__file__).resolve().parents[3] / "deploy"
DOCKERFILE = DEPLOY / "Dockerfile"
STORES = DEPLOY / "stores"

PINNED_UID = 1000
PINNED_GID = 1000

#: Every store compose file that bind-mounts /data and so must run as the
#: pinned pair. TrueNAS is a Jinja2 template, checked separately below.
BIND_MOUNT_COMPOSE_FILES = (
    STORES / "umbrel" / "docker-compose.yml",
    STORES / "casaos" / "docker-compose.yml",
    STORES / "runtipi" / "apps" / "palaia" / "docker-compose.yml",
)


def test_the_dockerfile_pins_the_uid_and_gid() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(rf"groupadd\s+--system\s+--gid\s+{PINNED_GID}\s+palaia", text), (
        "the palaia group is not pinned to a fixed gid"
    )
    assert re.search(rf"useradd\s+--system\s+--uid\s+{PINNED_UID}\s+--gid\s+palaia", text), (
        "the palaia user is not pinned to a fixed uid"
    )
    # The unpinned form must not creep back in on a second user.
    assert not re.search(r"useradd\s+--system\s+--create-home", text)
    assert "USER palaia" in text


def test_every_bind_mount_store_package_declares_the_pinned_user() -> None:
    for path in BIND_MOUNT_COMPOSE_FILES:
        compose = yaml.safe_load(path.read_text(encoding="utf-8"))
        service = compose["services"]["hub"]
        assert service.get("user") == f"{PINNED_UID}:{PINNED_GID}", path
        # The declaration only matters because /data is a bind mount; keep
        # the test honest about why it exists.
        volumes = service["volumes"]
        assert any(
            (isinstance(volume, str) and volume.endswith(":/data"))
            or (isinstance(volume, dict) and volume.get("target") == "/data")
            for volume in volumes
        ), (path, volumes)


def test_the_truenas_package_declares_the_pinned_user_in_both_places() -> None:
    package = STORES / "truenas" / "community" / "palaia"
    app = yaml.safe_load((package / "app.yaml").read_text(encoding="utf-8"))
    contexts = app["run_as_context"]
    assert contexts, "run_as_context is empty again"
    assert {(context["uid"], context["gid"]) for context in contexts} == {(PINNED_UID, PINNED_GID)}

    values = yaml.safe_load((package / "ix_values.yaml").read_text(encoding="utf-8"))
    assert (values["palaia"]["uid"], values["palaia"]["gid"]) == (PINNED_UID, PINNED_GID)

    template = (package / "templates" / "docker-compose.yaml").read_text(encoding="utf-8")
    assert 'user: "{{ ix_values.palaia.uid }}:{{ ix_values.palaia.gid }}"' in template


def test_every_bind_mount_submit_note_carries_the_chown_line() -> None:
    for store in ("umbrel", "casaos", "runtipi", "truenas"):
        text = (STORES / store / "SUBMIT.md").read_text(encoding="utf-8")
        assert f"chown -R {PINNED_UID}:{PINNED_GID}" in text, store


def test_the_shared_readme_states_the_uid_and_the_owner_check() -> None:
    text = (STORES / "README.md").read_text(encoding="utf-8")
    assert f"`{PINNED_UID}:{PINNED_GID}`" in text
    assert "First boot on a bind mount" in text
