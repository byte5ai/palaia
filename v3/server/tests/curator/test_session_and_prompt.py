"""The session launcher and the prompt (SPEC-206 deliverable #1, "The prompt").

The runner command is config, not code: these tests pin the contract a
configured command can rely on (prompt on stdin, placeholders substituted,
strict single-server MCP config) and that the prompt is assembled from the
SPEC's own role block, verbatim.
"""

from __future__ import annotations

import sys

import pytest

from palaia_hub.config import HubConfig
from palaia_hub.curator.prompt import ROLE_BLOCK, build_prompt
from palaia_hub.curator.session import (
    DEFAULT_RUNNER_COMMAND,
    MCP_SERVER_NAME,
    SessionRequest,
    SubprocessSessionRunner,
    mcp_config_document,
)

REQUEST = SessionRequest(
    vault="work",
    capture_id="cap-3f9a1c02d4",
    prompt="curate this",
    endpoint="http://127.0.0.1:8420/mcp/curator",
    allowed_tools=("mcp__palaia__work_memory_write", "mcp__palaia__work_memory_read"),
    token="plt_secret",
)


def test_the_config_default_matches_the_session_default() -> None:
    """``config.yaml``'s default command and the code's must not drift."""
    assert tuple(HubConfig().curator.runner_command) == DEFAULT_RUNNER_COMMAND


def test_the_mcp_config_names_exactly_one_server_with_the_token() -> None:
    document = mcp_config_document(REQUEST)
    assert list(document["mcpServers"]) == [MCP_SERVER_NAME]  # type: ignore[index]
    server = document["mcpServers"][MCP_SERVER_NAME]  # type: ignore[index]
    assert server["url"] == REQUEST.endpoint
    assert server["headers"] == {"Authorization": "Bearer plt_secret"}


def test_argv_substitutes_every_placeholder(tmp_path) -> None:  # noqa: ANN001
    runner = SubprocessSessionRunner(
        command=[
            "runner",
            "--config={mcp_config}",
            "--tools={allowed_tools}",
            "--at={endpoint}",
            "--vault={vault}",
            "--capture={capture_id}",
        ]
    )
    argv = runner.argv(REQUEST, tmp_path / "mcp.json")
    assert argv[1].endswith("mcp.json")
    assert argv[2] == "--tools=mcp__palaia__work_memory_write,mcp__palaia__work_memory_read"
    assert argv[3] == f"--at={REQUEST.endpoint}"
    assert argv[4] == "--vault=work"
    assert argv[5] == "--capture=cap-3f9a1c02d4"


@pytest.mark.anyio
async def test_the_prompt_arrives_on_stdin_and_the_exit_code_is_reported() -> None:
    runner = SubprocessSessionRunner(
        command=[sys.executable, "-c", "import sys; print(sys.stdin.read().strip())"]
    )
    result = await runner.run(REQUEST)
    assert result.exit_code == 0
    assert result.stdout.strip() == "curate this"
    assert not result.failed


@pytest.mark.anyio
async def test_a_hung_session_is_killed_and_reported_as_timed_out() -> None:
    runner = SubprocessSessionRunner(
        command=[sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.3
    )
    result = await runner.run(REQUEST)
    assert result.timed_out
    assert result.failed


@pytest.mark.anyio
async def test_a_missing_runner_command_is_an_outcome_not_a_crash() -> None:
    runner = SubprocessSessionRunner(command=["palaia-no-such-command-exists"])
    result = await runner.run(REQUEST)
    assert not result.launched
    assert result.failed
    assert "config.yaml" in result.stderr


def test_the_prompt_carries_the_spec_role_block_verbatim() -> None:
    prompt = build_prompt(
        vault_name="work",
        purpose="Team knowledge for ACME engineering.",
        capture_id="cap-3f9a1c02d4",
        capture_permalink="inbox/api-gateway",
        capture_text="- [entity] API Gateway\n- [why] deliberate limit\n",
    )
    assert prompt.startswith(
        'You are the palaia curator for the vault "work" — Team knowledge for '
        "ACME engineering."
    )
    for sentence in (
        "INGEST is yours",
        "MAINTENANCE is never yours",
        "The restriction\nis enforced, not advisory",
        "Search the vault at least twice",
        "Every note you write carries",
        "Never invent facts the capture",
        'End with one line of JSON: {"action":"ingested"|"needs_review"',
    ):
        assert sentence in prompt
    assert "- [source] inbox capture cap-3f9a1c02d4" in prompt
    assert "- [entity] API Gateway" in prompt
    # No stray format braces survived the templating.
    assert "{vault_name}" not in prompt
    assert "{{" not in ROLE_BLOCK.format(vault_name="x", purpose="y")


def test_the_vaults_own_curation_rules_are_included_when_present() -> None:
    prompt = build_prompt(
        vault_name="work",
        purpose="Team knowledge",
        capture_id="cap-1",
        capture_permalink="inbox/x",
        capture_text="text",
        curation_note="- Never file anything under projects/legacy.",
    )
    assert "meta/curation.md" in prompt
    assert "Never file anything under projects/legacy." in prompt


def test_the_endpoint_defaults_to_the_hubs_own_address() -> None:
    assert HubConfig().curator_endpoint() == "http://127.0.0.1:8420"
    wildcard = HubConfig(mode="open", host="0.0.0.0", port=9000)  # noqa: S104
    assert wildcard.curator_endpoint() == "http://127.0.0.1:9000"
    explicit = HubConfig(curator={"endpoint": "https://hub.example.com/"})
    assert explicit.curator_endpoint() == "https://hub.example.com"
