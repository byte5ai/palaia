"""Issue #344: a one-click update keeps the add-on's mounts and settings.

The install resolved a container's config into `-v host:host` bind mounts
and `-e KEY=value` environment inside the `docker run` argv, and stored
`env={}` on the upstream. The update path rebuilt the argv from that empty
`env` and `mounts={}` — the restarted container had neither its data
directory nor its settings. The resolved plan is now persisted on the
install record, and a record from before that field existed recovers it
from the argv this hub wrote.
"""

from __future__ import annotations

from pathlib import Path

from palaia_hub.market.docker_runtime import build_stdio_run_args
from palaia_hub.market.install import _plan_from_run_args
from palaia_hub.market.installed_store import InstalledAddonRecord, InstalledAddonStore


def test_the_plan_round_trips_through_the_run_argv() -> None:
    """What the hub wrote at install time is exactly what an update reads
    back for a record without a persisted plan."""
    mounts = {"data_dir": "/srv/addon-data", "cache": "/var/cache/addon"}
    plain_env = {"MOUNT_PATH": "/srv/addon-data", "LOG_LEVEL": "debug", "EMPTY": ""}
    run_args = build_stdio_run_args(
        "ghcr.io/acme/tool:1.0",
        container_name="palaia-addon-tool",
        mounts=mounts,
        plain_env=plain_env,
        secret_env_vars=["API_TOKEN"],
    )

    recovered_mounts, recovered_env = _plan_from_run_args(
        run_args.args, secret_env_vars=["API_TOKEN"]
    )

    # Mounts are keyed by host path on recovery (the config field names are
    # gone), which is all `build_stdio_run_args` needs: it uses the values.
    assert sorted(recovered_mounts.values()) == sorted(mounts.values())
    assert recovered_env == plain_env
    # The secret stays a secret: `-e API_TOKEN` carries no value and is not
    # a plain variable.
    assert "API_TOKEN" not in recovered_env

    rebuilt = build_stdio_run_args(
        "ghcr.io/acme/tool:2.0",
        container_name="palaia-addon-tool",
        mounts=recovered_mounts,
        plain_env=recovered_env,
        secret_env_vars=["API_TOKEN"],
    )
    assert rebuilt.args[:-1] == run_args.args[:-1], "everything but the image is identical"
    assert rebuilt.args[-1] == "ghcr.io/acme/tool:2.0"


def test_recovery_ignores_argv_that_is_not_a_mount_or_a_setting() -> None:
    mounts, env = _plan_from_run_args(
        ["run", "--rm", "-i", "--name", "x", "-e", "SECRET", "-e", "A=1", "image"],
        secret_env_vars=["SECRET"],
    )
    assert mounts == {}
    assert env == {"A": "1"}


def test_the_installed_record_persists_the_plan_and_reads_old_records(tmp_path: Path) -> None:
    store = InstalledAddonStore(tmp_path / "installed.json")
    record = InstalledAddonRecord(
        upstream_key="tool",
        entry_id="acme.tool",
        name="Tool",
        kind="container",
        provenance="manual",
        installed_ref="ghcr.io/acme/tool:1.0",
        image="ghcr.io/acme/tool:1.0",
        container_name="palaia-addon-tool",
        installed_at=1.0,
        mounts={"data_dir": "/srv/addon-data"},
        plain_env={"MOUNT_PATH": "/srv/addon-data"},
    )
    store.put(record)

    loaded = store.get("tool")
    assert loaded is not None
    assert loaded.mounts == {"data_dir": "/srv/addon-data"}
    assert loaded.plain_env == {"MOUNT_PATH": "/srv/addon-data"}

    # A record written before the field existed loads with empty plans —
    # the update path then recovers them from the argv.
    legacy = InstalledAddonRecord.from_json(
        {
            "upstream_key": "old",
            "entry_id": "acme.old",
            "name": "Old",
            "kind": "container",
            "provenance": "manual",
            "installed_ref": "img:1",
            "image": "img:1",
            "container_name": "palaia-addon-old",
            "installed_at": 1.0,
        }
    )
    assert legacy.mounts == {} and legacy.plain_env == {}
