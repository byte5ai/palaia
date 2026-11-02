"""The session launcher and the prompt (SPEC-206 deliverable #1, "The prompt").

The runner command is config, not code: these tests pin the contract a
configured command can rely on (prompt on stdin, placeholders substituted,
strict single-server MCP config) and that the prompt is assembled from the
SPEC's own role block, verbatim.
"""

from __future__ import annotations

import json
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


def _flag_value(command: tuple[str, ...], flag: str) -> str:
    assert flag in command, f"{flag} missing from {command}"
    return command[command.index(flag) + 1]


def test_the_default_command_gives_the_session_only_the_curator_tools() -> None:
    """Issue #604: ``--allowed-tools`` only grants; these flags take the rest away."""
    command = DEFAULT_RUNNER_COMMAND
    assert "--restricted" in command  # no user/project/local settings, no bypass
    assert _flag_value(command, "--tools") == ""  # no built-in tools at all
    assert "--strict-mcp-config" in command  # no other MCP server
    assert _flag_value(command, "--permission-mode") == "dontAsk"  # unlisted = denied
    assert _flag_value(command, "--allowed-tools") == "{allowed_tools}"
    assert "--dangerously-skip-permissions" not in command


def test_an_earlier_default_spelled_out_in_config_yaml_gets_todays_default() -> None:
    """Hubs set up before #604 carry the old default verbatim in config.yaml."""
    superseded = [
        "claude",
        "-p",
        "--mcp-config",
        "{mcp_config}",
        "--strict-mcp-config",
        "--allowed-tools",
        "{allowed_tools}",
        "--output-format",
        "text",
    ]
    config = HubConfig.model_validate({"curator": {"runner_command": superseded}})
    assert tuple(config.curator.runner_command) == DEFAULT_RUNNER_COMMAND
    custom = ["my-cli", "--prompt-on-stdin", "--mcp={mcp_config}"]
    config = HubConfig.model_validate({"curator": {"runner_command": custom}})
    assert config.curator.runner_command == custom


def test_the_generated_config_file_spells_out_todays_default(tmp_path) -> None:  # noqa: ANN001
    from palaia_hub.config import ensure_default_config, load_config

    path = tmp_path / "config.yaml"
    ensure_default_config(path)
    assert "--restricted" in path.read_text(encoding="utf-8")
    assert tuple(load_config(tmp_path).curator.runner_command) == DEFAULT_RUNNER_COMMAND


@pytest.mark.anyio
async def test_a_session_runs_in_a_fresh_directory_without_the_hubs_variables(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:  # noqa: ANN001
    """Issue #604: nothing of the hub's cwd or ``PALAIA_*`` environment reaches it."""
    monkeypatch.setenv("PALAIA_CURATOR_TOKEN", "plt_must_not_leak")
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "hub-file.txt").write_text("hub data")
    script = (
        "import json, os; print(json.dumps({'cwd': os.getcwd(), 'files': os.listdir('.'), "
        "'palaia': sorted(k for k in os.environ if k.startswith('PALAIA_')), "
        "'extra': os.environ.get('EXTRA_FOR_CLI')}))"
    )
    runner = SubprocessSessionRunner(
        command=[sys.executable, "-c", script], env={"EXTRA_FOR_CLI": "kept"}
    )
    result = await runner.run(REQUEST)
    assert result.exit_code == 0, result.stderr
    seen = json.loads(result.stdout)
    assert seen["palaia"] == []
    assert seen["extra"] == "kept"
    assert seen["files"] == []
    assert seen["cwd"] != str(tmp_path)


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
        'You are the palaia curator for the vault "work" — Team knowledge for ACME engineering.'
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
