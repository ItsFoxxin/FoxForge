from __future__ import annotations

from .state import RunState


REQUIRED_AGENTS = [
    "architect",
    "implementer",
    "tester",
    "reviewer",
    "helper",
    "reporter",
]

VALID_FINAL_STATUSES = {
    "READY_FOR_PLAYTEST",
    "BLOCKED",
}


class StateValidationError(RuntimeError):
    pass


def validate_state_for_report(state: RunState) -> None:
    for name in ("run_id", "task", "branch", "base_ref"):
        value = getattr(state, name)
        if not isinstance(value, str) or not value.strip():
            raise StateValidationError(f"Invalid {name}")
    for name in ("tests_added", "tests_passed", "tests_failed", "repair_cycles"):
        value = getattr(state, name)
        if type(value) is not int or value < 0:
            raise StateValidationError(f"Invalid nonnegative integer: {name}")
    if state.repair_cycles > 3:
        raise StateValidationError("Repair limit exceeded")
    if type(state.test_counts_verified) is not bool:
        raise StateValidationError("Invalid test-count verification flag")
    if state.test_exit_code is not None and type(state.test_exit_code) is not int:
        raise StateValidationError("Invalid test exit code")
    if not isinstance(state.review_result, str) or state.review_result not in {"NOT_RUN", "PASS", "FAIL", "UNPARSEABLE"}:
        raise StateValidationError("Invalid reviewer result")
    if not isinstance(state.files_changed, list) or any(not isinstance(path, str) or not path for path in state.files_changed):
        raise StateValidationError("Invalid changed-file list")
    if not isinstance(state.agents_completed, list) or state.agents_completed != REQUIRED_AGENTS:
        raise StateValidationError("Completed agents must match the ordered project roles")
    if not isinstance(state.final_status, str) or state.final_status not in VALID_FINAL_STATUSES:
        raise StateValidationError(
            f"Invalid final status: {state.final_status}"
        )

    if state.final_status == "READY_FOR_PLAYTEST":
        if state.branch in {"main", "master", "dev"}:
            raise StateValidationError("READY_FOR_PLAYTEST requires a task/sandbox branch")
        if not state.test_counts_verified or state.tests_passed == 0:
            raise StateValidationError("READY_FOR_PLAYTEST requires verified, nonzero test counts")
        if state.test_exit_code != 0:
            raise StateValidationError(
                "READY_FOR_PLAYTEST requires a zero authoritative "
                "test exit code."
            )

        if state.tests_failed != 0:
            raise StateValidationError(
                "READY_FOR_PLAYTEST cannot contain failed tests."
            )

        if state.review_result != "PASS":
            raise StateValidationError(
                "READY_FOR_PLAYTEST requires reviewer PASS."
            )


def validate_final_state(state: RunState) -> None:
    """Backward-compatible strict READY_FOR_PLAYTEST validator."""
    validate_state_for_report(state)

    if state.final_status != "READY_FOR_PLAYTEST":
        raise StateValidationError(
            "Final status must be READY_FOR_PLAYTEST."
        )


def expected_reporter_lines(state: RunState) -> list[str]:
    files = ", ".join(report_value(path) for path in state.files_changed) if state.files_changed else "(none)"
    agents = ", ".join(state.agents_completed)

    return [
        "FoxForge Status",
        f"Task: {report_value(state.task)}",
        f"Agents completed: {agents}",
        f"Files changed: {files}",
        f"Tests added: {state.tests_added}",
        f"Tests: {state.tests_passed} passed, {state.tests_failed} failed",
        f"Review: {state.review_result}",
        f"Repair cycles: {state.repair_cycles}",
        f"Status: {state.final_status}",
    ]


def report_value(value: str) -> str:
    """Keep task-file newlines and unusual filenames inside one report line."""
    return value.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")


def validate_reporter_output(
    state: RunState,
    reporter_output: str,
) -> None:
    validate_state_for_report(state)
    normalized = [
        line.strip()
        for line in reporter_output.splitlines()
        if line.strip()
    ]
    expected = expected_reporter_lines(state)

    if normalized != expected:
        raise StateValidationError(
            "Reporter output does not exactly match verified state.\n\n"
            "Expected:\n"
            + "\n".join(expected)
            + "\n\nActual:\n"
            + "\n".join(normalized)
        )
