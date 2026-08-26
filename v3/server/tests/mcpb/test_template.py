"""Locating the MCPB build template and the `mcpb` CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.mcpb.template import TemplateNotFoundError, mcpb_binary, template_dir


def test_finds_the_real_template_in_this_checkout() -> None:
    """This repo *is* the dev checkout the fallback guess targets."""
    directory = template_dir(env={})
    assert (directory / "manifest.template.json").is_file()
    assert (directory / "proxy" / "palaia-proxy.mjs").is_file()
    assert (directory / "icon.png").is_file()


def test_env_override_wins_when_valid(tmp_path: Path) -> None:
    (tmp_path / "manifest.template.json").write_text("{}")
    directory = template_dir(env={"PALAIA_MCPB_TEMPLATE_DIR": str(tmp_path)})
    assert directory == tmp_path


def test_env_override_that_does_not_exist_raises_with_the_fix() -> None:
    with pytest.raises(TemplateNotFoundError, match="PALAIA_MCPB_TEMPLATE_DIR"):
        template_dir(env={"PALAIA_MCPB_TEMPLATE_DIR": "/nonexistent/path/x1y2z3"})


def test_mcpb_binary_env_override_wins() -> None:
    binary = mcpb_binary(Path("/nonexistent"), env={"PALAIA_MCPB_BIN": "/usr/bin/true"})
    assert binary == "/usr/bin/true"


def test_mcpb_binary_finds_the_real_local_install_or_path() -> None:
    """Either `npm ci` has run in the template (a local devDependency
    install) or `mcpb` is globally on PATH — whichever is true in this
    environment, this must find it, since the e2e/CI jobs need it too."""
    directory = template_dir(env={})
    try:
        binary = mcpb_binary(directory, env={})
    except TemplateNotFoundError:
        pytest.skip("mcpb CLI not installed in this environment (run `npm ci` in the template dir)")
    else:
        assert binary
