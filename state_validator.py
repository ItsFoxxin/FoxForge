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
    missing = [
        role
        for role in REQUIRED_AGENTS
        if role not in state.agents_completed
    ]
    if missing:
        raise StateValidationError(
            f"Missing completed agents: {', '.join(missing)}"
        )

    if state.final_status not in VALID_FINAL_STATUSES:
        raise StateValidationError(
            f"Invalid final status: {state.final_status}"
        )

    if state.final_status == "READY_FOR_PLAYTEST":
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
    files = ", ".join(state.files_changed) if state.files_changed else "(none)"
    agents = ", ".join(state.agents_completed)

    return [
        "FoxForge Status",
        f"Task: {state.task}",
        f"Agents completed: {agents}",
        f"Files changed: {files}",
        f"Tests added: {state.tests_added}",
        f"Tests: {state.tests_passed} passed, {state.tests_failed} failed",
        f"Review: {state.review_result}",
        f"Repair cycles: {state.repair_cycles}",
        f"Status: {state.final_status}",
    ]


def validate_reporter_output(
    state: RunState,
    reporter_output: str,
) -> None:
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
