"""The supported control-plane mode rejects execution before external effects."""
import pytest

from foxforge import agent_runner, coordinator, issue_intake, publishing, test_runner
from foxforge.security import require_execution_worker


@pytest.mark.parametrize("invoke", [
    lambda: agent_runner.run_project_agent(None, "implementer", "untrusted input"),
    lambda: test_runner.run_tests(None, "must-not-execute"),
    lambda: coordinator.run(None),
    lambda: issue_intake.execute_issue(None),
    lambda: issue_intake.watch(None),
    lambda: publishing.publish_run(None, None, None, None),
    lambda: publishing.commit_validated_changes(None, None, None, None),
    lambda: publishing.push_task_branch(None, None, None, None, None),
    lambda: publishing.fetch_dev_branch(None, None, None, None),
    lambda: publishing.ensure_pull_request(None, None, None),
])
def test_control_plane_rejects_direct_legacy_calls_before_preflight(invoke, monkeypatch):
    monkeypatch.setenv("FOXFORGE_CONTROL_PLANE_ONLY", "1")
    # None arguments deliberately cannot pass preflight; the policy must run first.
    with pytest.raises(RuntimeError, match="separate authorized worker"):
        invoke()


@pytest.mark.parametrize("value", ["", "0", "false"])
def test_control_plane_flag_cannot_be_disabled_by_malformed_value(value, monkeypatch):
    monkeypatch.setenv("FOXFORGE_CONTROL_PLANE_ONLY", value)
    with pytest.raises(RuntimeError, match="control-plane mode"):
        require_execution_worker()


def test_legacy_venv_remains_available_when_mode_is_absent(monkeypatch):
    monkeypatch.delenv("FOXFORGE_CONTROL_PLANE_ONLY", raising=False)
    require_execution_worker()
