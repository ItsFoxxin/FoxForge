from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from agent_runner import AgentResult, run_project_agent
from git_manager import (
    changed_files,
    create_task_branch,
    diff,
    ensure_repo,
    slugify_task,
)
from state import RunState
from state_validator import (
    StateValidationError,
    validate_final_state,
    validate_reporter_output,
)
from test_runner import count_added_tests, run_tests


REPAIR_LIMIT = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FoxForge deterministic multi-agent coordinator"
    )

    parser.add_argument(
        "--repo",
        required=True,
        help="Repository root",
    )

    task_group = parser.add_mutually_exclusive_group(required=True)
    task_group.add_argument(
        "--task",
        help="Task text",
    )
    task_group.add_argument(
        "--task-file",
        help="UTF-8 text file containing the task",
    )

    parser.add_argument(
        "--test-command",
        required=True,
        help=(
            "Authoritative validation command, for example "
            r'".venv\Scripts\python.exe -m pytest -v"'
        ),
    )

    parser.add_argument(
        "--base-ref",
        default="HEAD",
        help=(
            "Git ref used to calculate task changes. "
            "Sandbox default: HEAD. "
            "Dead Circuit task branches should use origin/dev."
        ),
    )

    parser.add_argument(
        "--create-branch",
        action="store_true",
        help="Create foxforge/<slug> from origin/dev before running",
    )

    parser.add_argument(
        "--branch-name",
        help="Explicit foxforge/* branch name",
    )

    parser.add_argument(
        "--base-branch",
        default="dev",
        help="Base branch used with --create-branch",
    )

    parser.add_argument(
        "--skip-discord",
        action="store_true",
        help="Do not dispatch the final Discord notification",
    )

    parser.add_argument(
        "--max-agent-time",
        default="20m",
        help="Qwen Code wall-clock budget per role",
    )

    return parser.parse_args()


def read_task(args: argparse.Namespace) -> str:
    if args.task is not None:
        return args.task.strip()

    return Path(args.task_file).read_text(
        encoding="utf-8"
    ).strip()


def save_agent_result(
    run_dir: Path,
    result: AgentResult,
) -> None:
    text = result.stdout
    if result.stderr:
        text += "\n\n--- STDERR ---\n" + result.stderr

    (run_dir / f"{result.role}.txt").write_text(
        text.strip() + "\n",
        encoding="utf-8",
    )


def require_agent(
    repo: Path,
    run_dir: Path,
    role: str,
    task: str,
    context: str,
    max_wall_time: str,
) -> AgentResult:
    print(f"[foxforge] starting {role}...")

    result = run_project_agent(
        repo=repo,
        role=role,
        task=task,
        context=context,
        max_wall_time=max_wall_time,
    )

    save_agent_result(run_dir, result)

    if not result.succeeded:
        raise RuntimeError(
            f"{role} process failed with exit code {result.exit_code}\n"
            f"{result.stderr}"
        )

    print(
        f"[foxforge] {role} complete "
        f"({result.duration_seconds:.1f}s)"
    )

    return result


def parse_review_result(text: str) -> str:
    match = re.search(
        r"REVIEW_RESULT\s*:\s*(PASS|FAIL)",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return "UNPARSEABLE"

    return match.group(1).upper()


def build_reviewer_task(original_task: str) -> str:
    return f"""
Independently review the completed implementation.

Authoritative task:
{original_task}

Passing tests do not prove correctness.

Inspect the implementation and tests for credible contract violations,
regressions, missing behavior, or weakened tests.

Modify nothing.

Your LAST non-empty line MUST be exactly one of:

REVIEW_RESULT: PASS
REVIEW_RESULT: FAIL
""".strip()


def build_helper_task() -> str:
    return """
Using ONLY the verified facts supplied in context, produce:

1. One concise suggested commit message.
2. One short changelog entry.

Do not inspect files.
Do not run commands.
Do not modify anything.
Do not approve the implementation.
Do not invent facts.
""".strip()


def build_reporter_task() -> str:
    return """
Produce the FoxForge status message from the supplied verified facts only.

Use EXACTLY this format and no additional lines:

FoxForge Status

Task: <task>
Agents completed: <agents>
Files changed: <files>
Tests added: <number>
Tests: <passed> passed, <failed> failed
Review: <review result>
Repair cycles: <number>
Status: <final status>

Do not inspect files.
Do not run commands.
Do not use tools.
Do not infer or invent facts.
Do not change any supplied value.
""".strip()


def dispatch_discord(
    repo: Path,
    state_path: Path,
    reporter_path: Path,
) -> bool:
    dispatcher = repo / "orchestrator" / "reporter_dispatch.py"

    result = subprocess.run(
        [
            sys.executable,
            str(dispatcher),
            "--state",
            str(state_path),
            "--reporter",
            str(reporter_path),
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.stdout:
        print(result.stdout.strip())

    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)

    return result.returncode == 0


def main() -> int:
    args = parse_args()

    repo = Path(args.repo).resolve()
    ensure_repo(repo)

    task = read_task(args)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = repo / "orchestrator" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    (run_dir / "task.txt").write_text(
        task + "\n",
        encoding="utf-8",
    )

    branch = "(current branch)"
    base_ref = args.base_ref

    if args.create_branch:
        branch = (
            args.branch_name
            or f"foxforge/{slugify_task(task)}"
        )

        create_task_branch(
            repo=repo,
            branch=branch,
            base_branch=args.base_branch,
        )

        base_ref = f"origin/{args.base_branch}"

    state = RunState(
        run_id=run_id,
        task=task,
        branch=branch,
        base_ref=base_ref,
    )

    state_path = run_dir / "state.json"
    reporter_path = run_dir / "reporter.txt"

    try:
        architect = require_agent(
            repo,
            run_dir,
            "architect",
            task,
            "Produce the smallest safe implementation plan. Modify nothing.",
            args.max_agent_time,
        )
        state.agents_completed.append("architect")

        implementer = require_agent(
            repo,
            run_dir,
            "implementer",
            task,
            "Approved architect plan:\n\n" + architect.stdout,
            args.max_agent_time,
        )
        state.agents_completed.append("implementer")

        tester = require_agent(
            repo,
            run_dir,
            "tester",
            task,
            (
                "Inspect the current implementation and add meaningful "
                "regression tests. Modify TEST FILES ONLY. "
                "Do not weaken existing tests."
            ),
            args.max_agent_time,
        )
        state.agents_completed.append("tester")

        test_result = run_tests(
            repo,
            args.test_command,
        )

        (run_dir / "tests.txt").write_text(
            test_result.output + "\n",
            encoding="utf-8",
        )

        state.test_exit_code = test_result.exit_code
        state.tests_passed = test_result.passed
        state.tests_failed = test_result.failed

        reviewer_context = (
            f"Authoritative test exit code: {test_result.exit_code}\n"
            f"Tests passed: {test_result.passed}\n"
            f"Tests failed: {test_result.failed}\n\n"
            f"Tester output:\n{tester.stdout}"
        )

        reviewer = require_agent(
            repo,
            run_dir,
            "reviewer",
            build_reviewer_task(task),
            reviewer_context,
            args.max_agent_time,
        )
        state.agents_completed.append("reviewer")
        state.review_result = parse_review_result(reviewer.stdout)

        while (
            (
                not test_result.succeeded
                or state.review_result != "PASS"
            )
            and state.repair_cycles < REPAIR_LIMIT
        ):
            state.repair_cycles += 1

            repair_context = (
                f"Repair cycle: {state.repair_cycles}/{REPAIR_LIMIT}\n\n"
                f"Authoritative tests:\n{test_result.output}\n\n"
                f"Reviewer result:\n{reviewer.stdout}"
            )

            require_agent(
                repo,
                run_dir,
                "implementer",
                task,
                repair_context,
                args.max_agent_time,
            )

            require_agent(
                repo,
                run_dir,
                "tester",
                task,
                (
                    "Re-check the repaired implementation. "
                    "Modify TEST FILES ONLY when needed. "
                    "Do not weaken tests."
                ),
                args.max_agent_time,
            )

            test_result = run_tests(
                repo,
                args.test_command,
            )

            (run_dir / f"tests-repair-{state.repair_cycles}.txt").write_text(
                test_result.output + "\n",
                encoding="utf-8",
            )

            state.test_exit_code = test_result.exit_code
            state.tests_passed = test_result.passed
            state.tests_failed = test_result.failed

            reviewer = require_agent(
                repo,
                run_dir,
                "reviewer",
                build_reviewer_task(task),
                (
                    f"Repair cycle {state.repair_cycles} completed.\n"
                    f"Authoritative test exit code: "
                    f"{test_result.exit_code}\n"
                    f"Tests passed: {test_result.passed}\n"
                    f"Tests failed: {test_result.failed}"
                ),
                args.max_agent_time,
            )

            state.review_result = parse_review_result(
                reviewer.stdout
            )

        state.files_changed = changed_files(
            repo,
            base_ref,
        )

        task_diff = diff(
            repo,
            base_ref,
        )
        (run_dir / "task.diff").write_text(
            task_diff,
            encoding="utf-8",
        )

        state.tests_added = count_added_tests(
            task_diff,
        )

        if (
            test_result.succeeded
            and state.tests_failed == 0
            and state.review_result == "PASS"
        ):
            state.final_status = "READY_FOR_PLAYTEST"
        else:
            state.final_status = "BLOCKED"

        helper_facts = json.dumps(
            {
                "task": state.task,
                "files_changed": state.files_changed,
                "tests_added": state.tests_added,
                "tests_passed": state.tests_passed,
                "tests_failed": state.tests_failed,
                "review_result": state.review_result,
                "repair_cycles": state.repair_cycles,
                "final_status": state.final_status,
            },
            indent=2,
        )

        require_agent(
            repo,
            run_dir,
            "helper",
            build_helper_task(),
            helper_facts,
            args.max_agent_time,
        )
        state.agents_completed.append("helper")

        # Reporter is the final agent. Its successful return is what makes
        # "reporter" a verified completed agent.
        final_agent_list = [
            *state.agents_completed,
            "reporter",
        ]

        reporter_facts = json.dumps(
            {
                "task": state.task,
                "agents_completed": final_agent_list,
                "files_changed": state.files_changed,
                "tests_added": state.tests_added,
                "tests_passed": state.tests_passed,
                "tests_failed": state.tests_failed,
                "review_result": state.review_result,
                "repair_cycles": state.repair_cycles,
                "final_status": state.final_status,
            },
            indent=2,
        )

        reporter = require_agent(
            repo,
            run_dir,
            "reporter",
            build_reporter_task(),
            reporter_facts,
            args.max_agent_time,
        )

        state.agents_completed.append("reporter")

        reporter_path.write_text(
            reporter.stdout.strip() + "\n",
            encoding="utf-8",
        )

        state.save(state_path)

        # Discord is gated by deterministic Python validation.
        if state.final_status == "READY_FOR_PLAYTEST":
            validate_final_state(state)
            validate_reporter_output(
                state,
                reporter.stdout,
            )

            if args.skip_discord:
                state.notification_status = "SKIPPED"
            else:
                sent = dispatch_discord(
                    repo,
                    state_path,
                    reporter_path,
                )
                state.notification_status = (
                    "SENT" if sent else "FAILED"
                )
        else:
            state.notification_status = "NOT_SENT_BLOCKED"

        state.save(state_path)

    except (
        RuntimeError,
        StateValidationError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        state.final_status = "BLOCKED"
        state.notification_status = "NOT_SENT_ERROR"
        state.save(state_path)

        (run_dir / "error.txt").write_text(
            str(exc) + "\n",
            encoding="utf-8",
        )

        print(f"[foxforge] BLOCKED: {exc}", file=sys.stderr)
        print(f"[foxforge] run: {run_dir}")
        return 1

    print()
    print("FOXFORGE RUN COMPLETE")
    print(f"Run: {run_id}")
    print(f"Status: {state.final_status}")
    print(
        f"Tests: {state.tests_passed} passed, "
        f"{state.tests_failed} failed"
    )
    print(f"Review: {state.review_result}")
    print(f"Repair cycles: {state.repair_cycles}")
    print(f"Notification: {state.notification_status}")
    print(f"Artifacts: {run_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
