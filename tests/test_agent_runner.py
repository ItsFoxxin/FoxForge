from foxforge.agent_runner import build_delegate_prompt
import subprocess
import os
import sys

import pytest

from foxforge import agent_runner
from foxforge.security import register_secret


def test_delegate_prompt_names_role_and_task() -> None:
    prompt = build_delegate_prompt(
        role="architect",
        task="Add square",
        context="Existing calculator module",
    )

    assert "`architect`" in prompt
    assert "Add square" in prompt
    assert "Existing calculator module" in prompt
    assert "Do not perform the `architect` agent's work yourself." in prompt


@pytest.fixture
def agent_repo(tmp_path, monkeypatch):
    agents = tmp_path / ".qwen" / "agents"
    agents.mkdir(parents=True)
    (agents / "architect.md").write_text("tools: []")
    monkeypatch.setattr(agent_runner, "find_qwen", lambda: "qwen.exe")
    return tmp_path


def test_parent_only_preapproves_agent_and_fresh_processes(agent_repo, monkeypatch):
    calls = []
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "secret")
    def process(command, repo, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "Plan", "")
    monkeypatch.setattr(agent_runner, "run_process", process)
    for _ in range(2):
        assert agent_runner.run_project_agent(agent_repo, "architect", "task").succeeded
    assert len(calls) == 2
    for command, options in calls:
        assert command[command.index("--core-tools") + 1] == "agent"
        assert command[command.index("--allowed-tools") + 1] == "agent"
        assert command[command.index("--approval-mode") + 1] == "default"
        assert "yolo" not in command and "--yolo" not in command
        assert "task" not in command  # Prompt goes through stdin.
        assert options["timeout"] == 1200
        assert "DISCORD_WEBHOOK_URL" not in options["env"]


def test_agent_timeout_is_a_failed_result(agent_repo, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("qwen", 1, output="partial", stderr="details")
    monkeypatch.setattr(agent_runner, "run_process", timeout)
    result = agent_runner.run_project_agent(agent_repo, "architect", "task", max_wall_time="1s")
    assert result.exit_code == 124 and not result.succeeded
    assert "partial" in result.stdout and "timed out" in result.stderr


@pytest.mark.parametrize("role,mode", [("unknown", "default"), ("reporter", "default"), ("architect", "yolo")])
def test_invalid_agent_configuration_never_launches(agent_repo, monkeypatch, role, mode):
    monkeypatch.setattr(agent_runner, "run_process", lambda *a, **k: pytest.fail("Unexpected process"))
    with pytest.raises(agent_runner.AgentRunnerError):
        agent_runner.run_project_agent(agent_repo, role, "task", approval_mode=mode)


@pytest.mark.skipif(os.name != "nt", reason="Windows batch launcher")
def test_windows_launcher_with_spaces_and_stdin(agent_repo, monkeypatch):
    directory = agent_repo / "launcher with spaces"
    directory.mkdir()
    shim = directory / "qwen.cmd"
    shim.write_text('@echo off\n"' + sys.executable + '" -c "import sys; print(sys.stdin.read())"\n', encoding="utf-8")
    monkeypatch.setattr(agent_runner, "find_qwen", lambda: str(shim))
    result = agent_runner.run_project_agent(agent_repo, "architect", "Task with & and spaces")
    assert result.succeeded
    assert "Task with & and spaces" in result.stdout


def test_actual_agent_launch_drops_all_publishing_credentials(agent_repo, monkeypatch):
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "FOXFORGE_GITHUB_APP_ID", "FOXFORGE_GITHUB_INSTALLATION_ID", "GIT_ASKPASS", "GIT_CONFIG_PARAMETERS", "DISCORD_WEBHOOK_URL"):
        monkeypatch.setenv(name, "private-agent-environment-value")
    monkeypatch.setenv("FOXFORGE_GITHUB_PRIVATE_KEY", str(agent_repo.parent / "outside.pem"))
    def process(command, repo, **kwargs):
        env = kwargs["env"]
        assert not any(name in env for name in ("GITHUB_TOKEN", "GH_TOKEN", "FOXFORGE_GITHUB_APP_ID", "FOXFORGE_GITHUB_INSTALLATION_ID", "FOXFORGE_GITHUB_PRIVATE_KEY", "GIT_ASKPASS", "GIT_CONFIG_PARAMETERS", "DISCORD_WEBHOOK_URL"))
        return subprocess.CompletedProcess(command, 0, "Plan", "")
    monkeypatch.setattr(agent_runner, "run_process", process)
    assert agent_runner.run_project_agent(agent_repo, "architect", "Task").succeeded


def test_agent_output_credentials_are_redacted_and_fail(agent_repo, monkeypatch):
    register_secret("installation-secret-for-tests-only")
    monkeypatch.setattr(agent_runner, "run_process", lambda command, *a, **k: subprocess.CompletedProcess(command, 0, "installation-secret-for-tests-only", ""))
    result = agent_runner.run_project_agent(agent_repo, "architect", "Task")
    assert not result.succeeded and "installation-secret" not in result.stdout
    assert "REDACTED" in result.stdout


def test_credentials_cannot_be_in_agent_prompts(agent_repo, monkeypatch):
    register_secret("installation-secret-for-tests-only")
    monkeypatch.setattr(agent_runner, "run_process", lambda *a, **k: pytest.fail("Secret prompt reached process"))
    with pytest.raises(agent_runner.AgentRunnerError, match="credential"):
        agent_runner.run_project_agent(agent_repo, "architect", "installation-secret-for-tests-only")
