from __future__ import annotations

from state import RunState


REQUIRED_AGENTS = [
    "architect",
    "implementer",
    "tester",
    "reviewer",
    "helper",
    "reporter",
]


class StateValidationError(RuntimeError):
    pass


def validate_final_state(state: RunState) -> None:
    missing = [
        role for role in REQUIRED_AGENTS
        if role not in state.agents_completed
    ]

    if missing:
        raise StateValidationError(
            f"Missing completed agents: {', '.join(missing)}"
        )

    if state.test_exit_code != 0:
        raise StateValidationError(
            f"Authoritative test command failed with exit code "
            f"{state.test_exit_code}"
        )

    if state.tests_failed != 0:
        raise StateValidationError(
            f"Authoritative test result contains "
            f"{state.tests_failed} failure(s)"
        )

    if state.review_result != "PASS":
        raise StateValidationError(
            f"Reviewer did not return PASS: {state.review_result}"
        )

    expected_status = "READY_FOR_PLAYTEST"
    if state.final_status != expected_status:
        raise StateValidationError(
            f"Final status must be {expected_status} after all gates pass; "
            f"got {state.final_status}"
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
