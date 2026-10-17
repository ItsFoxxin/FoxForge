import json

import pytest

from foxforge import coordinator
from foxforge.agent_runner import AgentResult
from foxforge.state import RunState
from foxforge.state_validator import expected_reporter_lines
from foxforge.test_runner import TestResult as ValidationResult


@pytest.mark.parametrize("text,expected", [
    ("No issues\nREVIEW_RESULT: PASS\n", "PASS"),
    ("Issue\nREVIEW_RESULT: FAIL", "FAIL"),
    ("REVIEW_RESULT: PASS\nactually broken", "UNPARSEABLE"),
    ("REVIEW_RESULT: PASS\nREVIEW_RESULT: FAIL", "UNPARSEABLE"),
    ("REVIEW_RESULT: PASSING", "UNPARSEABLE"),
    ("PASS", "UNPARSEABLE"), ("", "UNPARSEABLE"),
])
def test_review_requires_single_final_verdict(text, expected):
    assert coordinator.parse_review_result(text) == expected


@pytest.fixture
def orchestration(git_repo, tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setattr(coordinator, "create_run_dir", lambda *args: run_dir)
    calls = []

    def agent(repo, role, task, context="", **kwargs):
        calls.append(role)
        if role == "reporter":
            state = RunState.load(run_dir / "state.json")
            state.agents_completed.append("reporter")
            text = "\n".join(expected_reporter_lines(state))
        elif role == "reviewer":
            text = "REVIEW_RESULT: PASS"
        else:
            text = "Completed"
        return AgentResult(role, 0, text, "", .01)

    monkeypatch.setattr(coordinator, "run_project_agent", agent)
    monkeypatch.setattr(coordinator, "run_tests", lambda *args, **kwargs: ValidationResult(["pytest"], 0, 5, 0, "5 passed", True))
    args = ["--repo", str(git_repo), "--task", "Improve calculation", "--test-command", "pytest", "--skip-discord"]
    return args, run_dir, calls, agent


def test_complete_run_uses_six_roles_and_saves_state(orchestration):
    args, run_dir, calls, _ = orchestration
    assert coordinator.main(args) == 0
    state = RunState.load(run_dir / "state.json")
    assert calls == ["architect", "implementer", "tester", "reviewer", "helper", "reporter"]
    assert state.final_status == "READY_FOR_PLAYTEST"
    assert state.notification_status == "SKIPPED"
    assert len(state.base_ref) == 40  # Frozen before agents run.


def test_repair_stops_at_three_and_blocked_is_failure(orchestration, monkeypatch):
    args, run_dir, calls, _ = orchestration
    monkeypatch.setattr(coordinator, "run_tests", lambda *args, **kwargs: ValidationResult(["pytest"], 1, 3, 2, "2 failed, 3 passed", True))
    assert coordinator.main(args) == 1
    state = RunState.load(run_dir / "state.json")
    assert state.final_status == "BLOCKED" and state.repair_cycles == 3
    assert calls.count("implementer") == calls.count("tester") == calls.count("reviewer") == 4
    assert (run_dir / "tests-repair-3.txt").exists()
    assert not (run_dir / "tests-repair-4.txt").exists()


def test_repair_can_recover(orchestration, monkeypatch):
    args, run_dir, calls, _ = orchestration
    results = iter([ValidationResult([], 1, 0, 1, "1 failed", True), ValidationResult([], 0, 1, 0, "1 passed", True)])
    monkeypatch.setattr(coordinator, "run_tests", lambda *args, **kwargs: next(results))
    assert coordinator.main(args) == 0
    assert RunState.load(run_dir / "state.json").repair_cycles == 1


def test_review_failure_repairs_even_when_tests_pass(orchestration, monkeypatch):
    args, run_dir, _, agent = orchestration
    verdicts = iter(["REVIEW_RESULT: FAIL", "REVIEW_RESULT: PASS"])
    def review(repo, role, task, **kwargs):
        if role == "reviewer":
            return AgentResult(role, 0, next(verdicts), "", .01)
        return agent(repo, role, task, **kwargs)
    monkeypatch.setattr(coordinator, "run_project_agent", review)
    assert coordinator.main(args) == 0
    assert RunState.load(run_dir / "state.json").repair_cycles == 1


def test_unknown_test_counts_never_become_ready(orchestration, monkeypatch):
    args, run_dir, _, _ = orchestration
    monkeypatch.setattr(coordinator, "run_tests", lambda *a, **k: ValidationResult([], 0, 0, 0, "success", False))
    assert coordinator.main(args) == 1
    state = RunState.load(run_dir / "state.json")
    assert state.final_status == "BLOCKED" and state.repair_cycles == 3


@pytest.mark.parametrize("exit_code,text", [(1, "failed"), (0, " ")])
def test_agent_failure_is_persisted_without_later_roles(orchestration, monkeypatch, exit_code, text):
    args, run_dir, calls, agent = orchestration
    def fail(repo, role, task, **kwargs):
        if role == "implementer":
            return AgentResult(role, exit_code, text, "diagnostic", .01)
        return agent(repo, role, task, **kwargs)
    monkeypatch.setattr(coordinator, "run_project_agent", fail)
    assert coordinator.main(args) == 1
    state = RunState.load(run_dir / "state.json")
    assert state.agents_completed == ["architect"]
    assert state.final_status == "BLOCKED"
    assert (run_dir / "error.txt").exists()
    assert "reporter" not in calls


def test_forged_reporter_never_dispatches(orchestration, monkeypatch):
    args, run_dir, _, agent = orchestration
    def forge(repo, role, task, **kwargs):
        if role == "reporter":
            return AgentResult(role, 0, "Everything passed!", "", .01)
        return agent(repo, role, task, **kwargs)
    monkeypatch.setattr(coordinator, "run_project_agent", forge)
    monkeypatch.setattr(coordinator, "dispatch_report", lambda *args: pytest.fail("Invalid report was sent"))
    assert coordinator.main(args[:-1]) == 1
    assert RunState.load(run_dir / "state.json").notification_status == "NOT_SENT_ERROR"


def test_notification_failure_sets_failure_exit(orchestration, monkeypatch):
    args, run_dir, _, _ = orchestration
    monkeypatch.setattr(coordinator, "dispatch_report", lambda *args: False)
    assert coordinator.main(args[:-1]) == 1
    state = RunState.load(run_dir / "state.json")
    assert state.final_status == "READY_FOR_PLAYTEST" and state.notification_status == "FAILED"


def test_readonly_role_modification_is_blocked(orchestration, monkeypatch):
    args, run_dir, _, agent = orchestration
    def mutate(repo, role, task, **kwargs):
        if role == "architect":
            (repo / "module.py").write_text("tampered\n")
        return agent(repo, role, task, **kwargs)
    monkeypatch.setattr(coordinator, "run_project_agent", mutate)
    assert coordinator.main(args) == 1
    assert "Read-only agent" in (run_dir / "error.txt").read_text()


def test_setup_failure_is_clean(tmp_path, capsys):
    assert coordinator.main(["--repo", str(tmp_path), "--task", "x", "--test-command", "pytest"]) == 1
    assert "Setup failed" in capsys.readouterr().err
