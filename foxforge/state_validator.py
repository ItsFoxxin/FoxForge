from __future__ import annotations

from .state import RunState
import re
from .security import redact


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
    _validate_state(state, REQUIRED_AGENTS)


def validate_state_for_publish(state: RunState) -> None:
    _validate_state(state, REQUIRED_AGENTS[:-1])
    if state.final_status != "READY_FOR_PLAYTEST" or not state.publish_requested or state.publishing_status != "PENDING":
        raise StateValidationError("Publishing requires explicit opt-in and successful local validation")
    if not re.fullmatch(r"foxforge/[A-Za-z0-9][A-Za-z0-9._/-]*", state.branch):
        raise StateValidationError("Publishing requires a foxforge/* task branch")
    if not state.validated_head_sha or not state.validated_tree_hash:
        raise StateValidationError("Publishing requires the validated Git/content snapshot")


def _validate_state(state: RunState, expected_agents: list[str]) -> None:
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
    if not isinstance(state.agents_completed, list) or state.agents_completed != expected_agents:
        raise StateValidationError("Completed agents must match the ordered project roles")
    if not isinstance(state.final_status, str) or state.final_status not in VALID_FINAL_STATUSES:
        raise StateValidationError(
            f"Invalid final status: {state.final_status}"
        )
    _validate_publishing_fields(state)

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

    lines = [
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
    if state.publish_requested:
        lines.extend([
            f"Branch: {state.branch}",
            f"Publishing: {state.publishing_status}",
            f"Commit: {state.commit_sha or '(none)'}",
            f"Remote branch: {state.remote_branch or '(none)'}",
            f"PR: {state.pull_request_url or '(none)'}",
        ])
    return lines


def _validate_publishing_fields(state: RunState) -> None:
    if type(state.publish_requested) is not bool or not isinstance(state.publishing_status, str):
        raise StateValidationError("Invalid publishing state")
    if state.publishing_status not in {"NOT_REQUESTED", "PENDING", "COMMITTED", "PUSHED", "PUBLISHED", "FAILED", "BLOCKED"}:
        raise StateValidationError("Invalid publishing status")
    if (state.publishing_status == "NOT_REQUESTED") != (not state.publish_requested):
        raise StateValidationError("Publishing state does not match explicit opt-in")
    if not state.publish_requested and any(getattr(state, name) is not None for name in (
        "github_repository", "validated_head_sha", "validated_tree_hash", "publishing_error", "commit_sha", "remote_branch", "pull_request_number", "pull_request_url",
    )):
        raise StateValidationError("Publishing metadata requires explicit opt-in")
    for name in ("validated_head_sha", "commit_sha"):
        value = getattr(state, name)
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value)):
            raise StateValidationError("Invalid publishing commit identity")
    if state.validated_tree_hash is not None and (not isinstance(state.validated_tree_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", state.validated_tree_hash)):
        raise StateValidationError("Invalid validated content identity")
    if state.publish_requested and (not isinstance(state.github_repository, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", state.github_repository)):
        raise StateValidationError("Missing or invalid publishing repository")
    if state.remote_branch is not None and (state.remote_branch != state.branch or not state.commit_sha):
        raise StateValidationError("Remote branch does not match the committed task branch")
    if state.pull_request_number is not None:
        if type(state.pull_request_number) is not int or state.pull_request_number <= 0 or not state.remote_branch:
            raise StateValidationError("Invalid pull request number/state")
        if state.pull_request_url != f"https://github.com/{state.github_repository}/pull/{state.pull_request_number}":
            raise StateValidationError("Pull request URL does not match verified repository and number")
    elif state.pull_request_url is not None:
        raise StateValidationError("Pull request URL requires a verified number")
    if state.publishing_status in {"COMMITTED", "PUSHED", "PUBLISHED"} and not state.commit_sha:
        raise StateValidationError("Publishing status requires a commit")
    if state.publishing_status in {"PUSHED", "PUBLISHED"} and not state.remote_branch:
        raise StateValidationError("Publishing status requires a remote task branch")
    if state.publishing_status == "PUBLISHED" and not state.pull_request_number:
        raise StateValidationError("Published state requires a verified pull request")
    if state.publishing_error is not None and (not isinstance(state.publishing_error, str) or redact(state.publishing_error) != state.publishing_error):
        raise StateValidationError("Unsafe publishing diagnostic")


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
