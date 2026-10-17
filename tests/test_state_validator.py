import pytest

from foxforge.state import RunState
from foxforge.state_validator import (
    StateValidationError,
    expected_reporter_lines,
    validate_reporter_output,
    validate_state_for_report,
)


def ready_state() -> RunState:
    return RunState(
        run_id="run-1",
        task="Add square",
        branch="feature",
        base_ref="HEAD",
        agents_completed=[
            "architect",
            "implementer",
            "tester",
            "reviewer",
            "helper",
            "reporter",
        ],
        files_changed=[
            "calculator.py",
            "test_calculator.py",
        ],
        tests_added=4,
        tests_passed=12,
        tests_failed=0,
        test_exit_code=0,
        test_counts_verified=True,
        review_result="PASS",
        repair_cycles=0,
        final_status="READY_FOR_PLAYTEST",
    )


def test_ready_state_validates() -> None:
    validate_state_for_report(ready_state())


def test_ready_state_rejects_failed_tests() -> None:
    state = ready_state()
    state.tests_failed = 1

    with pytest.raises(StateValidationError):
        validate_state_for_report(state)


def test_reporter_output_must_match_exact_state() -> None:
    state = ready_state()
    output = "\n".join(expected_reporter_lines(state))

    validate_reporter_output(state, output)

    with pytest.raises(StateValidationError):
        validate_reporter_output(
            state,
            output.replace("12 passed", "13 passed"),
        )


@pytest.mark.parametrize("name,value", [
    ("tests_passed", -1), ("tests_failed", True), ("tests_added", "3"),
    ("repair_cycles", 4), ("repair_cycles", -1), ("review_result", []),
    ("final_status", []), ("files_changed", "calculator.py"),
    ("agents_completed", ["architect"]), ("test_exit_code", False),
    ("test_counts_verified", False), ("tests_passed", 0), ("branch", "main"),
])
def test_invalid_state_facts_cannot_be_reported(name, value):
    state = ready_state()
    setattr(state, name, value)
    with pytest.raises(StateValidationError):
        validate_state_for_report(state)


def test_multiline_task_and_filename_are_escaped():
    state = ready_state()
    state.task = "First line\nSecond line"
    state.files_changed = ["test\nodd.py"]
    output = "\n".join(expected_reporter_lines(state))
    assert "Task: First line\\nSecond line" in output
    validate_reporter_output(state, output)
