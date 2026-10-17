from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .agent_runner import AgentResult, run_project_agent
from .git_manager import (
    changed_files,
    create_task_branch,
    current_branch,
    diff,
    ensure_repo,
    ensure_clean_worktree,
    slugify_task,
    head_sha,
    resolve_ref,
)
from .process import duration_seconds
from .reporter_dispatch import dispatch_report
from .run_storage import create_run_dir
from .state import RunState
from .state_validator import (
    StateValidationError,
    validate_reporter_output,
    validate_state_for_report,
    report_value,
)
from .test_runner import count_added_tests, run_tests


REPAIR_LIMIT = 3


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FoxForge deterministic multi-agent coordinator"
    )

    parser.add_argument(
        "--repo",
        required=True,
        help="Repository root",
    )

    task_group = parser.add_mutually_exclusive_group(required=True)
    task_group.add_argument("--task", help="Task text")
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
            "Project task branches should use origin/dev."
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
        choices=["dev"],
        help="Base branch used with --create-branch (origin/dev only)",
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
    parser.add_argument("--max-test-time", default="20m", help="Python-enforced test process deadline")

    args = parser.parse_args(argv)
    if args.branch_name and not args.create_branch:
        parser.error("--branch-name requires --create-branch")
    try:
        duration_seconds(args.max_agent_time)
        duration_seconds(args.max_test_time)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def read_task(args: argparse.Namespace) -> str:
    if args.task is not None:
        return args.task.strip()

    return Path(args.task_file).read_text(
        encoding="utf-8"
    ).strip()


def save_agent_result(
    run_dir: Path,
    result: AgentResult,
    suffix: str = "",
) -> None:
    text = result.stdout
    if result.stderr:
        text += "\n\n--- STDERR ---\n" + result.stderr

    (run_dir / f"{result.role}{suffix}.txt").write_text(
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
    suffix: str = "",
) -> AgentResult:
    print(f"[foxforge] starting {role}{suffix}...")
    identity = (current_branch(repo), head_sha(repo))
    readonly = role in {"architect", "reviewer", "helper", "reporter"}
    before = diff(repo, "HEAD") if readonly else None

    result = run_project_agent(
        repo=repo,
        role=role,
        task=task,
        context=context,
        max_wall_time=max_wall_time,
    )

    save_agent_result(
        run_dir,
        result,
        suffix=suffix,
    )
    if (current_branch(repo), head_sha(repo)) != identity:
        raise RuntimeError(f"{role} changed Git branch or HEAD; Python owns Git lifecycle")
    if readonly and diff(repo, "HEAD") != before:
        raise RuntimeError(f"Read-only agent {role} modified repository content")

    if not result.succeeded:
        raise RuntimeError(
            f"{role} process failed with exit code {result.exit_code}\n"
            f"{result.stderr}"
        )
    if not result.stdout.strip():
        raise RuntimeError(f"{role} returned empty output")

    print(
        f"[foxforge] {role}{suffix} complete "
        f"({result.duration_seconds:.1f}s)"
    )
    return result


def parse_review_result(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and lines[-1] in {"REVIEW_RESULT: PASS", "REVIEW_RESULT: FAIL"}:
        verdicts = [line for line in lines if line.startswith("REVIEW_RESULT:")]
        if len(verdicts) == 1:
            return lines[-1].split(": ")[1]
    return "UNPARSEABLE"


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
Task and file values already escape backslashes and line breaks; print those supplied strings literally.
""".strip()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"[foxforge] Setup failed: {exc}", file=sys.stderr)
        return 1


def run(args: argparse.Namespace) -> int:

    repo = Path(args.repo).resolve()
    ensure_repo(repo)
    ensure_clean_worktree(repo)
    task = read_task(args)
    if not task:
        raise ValueError("Task must not be empty")

    branch = current_branch(repo)
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

    if not branch or branch in {"main", "master", "dev"}:
        raise ValueError("Use a task/sandbox branch, or --create-branch, before running agents")

    base_ref = resolve_ref(repo, base_ref)
    starting_head = head_sha(repo)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:12]
    run_dir = create_run_dir(repo, run_id)
    (run_dir / "task.txt").write_text(task + "\n", encoding="utf-8")

    state = RunState(
        run_id=run_id,
        task=task,
        branch=branch,
        base_ref=base_ref,
    )

    state_path = run_dir / "state.json"
    reporter_path = run_dir / "reporter.txt"

    try:
        state.save(state_path)
        architect = require_agent(
            repo,
            run_dir,
            "architect",
            task,
            "Produce the smallest safe implementation plan. Modify nothing.",
            args.max_agent_time,
        )
        state.agents_completed.append("architect")
        state.save(state_path)

        require_agent(
            repo,
            run_dir,
            "implementer",
            task,
            "Approved architect plan:\n\n" + architect.stdout,
            args.max_agent_time,
        )
        state.agents_completed.append("implementer")
        state.save(state_path)

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
        state.save(state_path)

        test_result = run_tests(repo, args.test_command, timeout=duration_seconds(args.max_test_time))
        (run_dir / "tests.txt").write_text(
            test_result.output + "\n",
            encoding="utf-8",
        )
        state.test_exit_code = test_result.exit_code
        state.tests_passed = test_result.passed
        state.tests_failed = test_result.failed
        state.test_counts_verified = test_result.counts_verified
        state.save(state_path)

        reviewer = require_agent(
            repo,
            run_dir,
            "reviewer",
            build_reviewer_task(task),
            (
                f"Authoritative test exit code: {test_result.exit_code}\n"
                f"Tests passed: {test_result.passed}\n"
                f"Tests failed: {test_result.failed}\n\n"
                f"Tester output:\n{tester.stdout}"
            ),
            args.max_agent_time,
        )
        state.agents_completed.append("reviewer")
        state.review_result = parse_review_result(
            reviewer.stdout
        )
        state.save(state_path)

        while (
            (
                not test_result.succeeded
                or state.review_result != "PASS"
            )
            and state.repair_cycles < REPAIR_LIMIT
        ):
            state.repair_cycles += 1
            state.save(state_path)
            suffix = f"-repair-{state.repair_cycles}"

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
                suffix=suffix,
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
                suffix=suffix,
            )

            test_result = run_tests(
                repo,
                args.test_command,
                timeout=duration_seconds(args.max_test_time),
            )

            (run_dir / f"tests{suffix}.txt").write_text(
                test_result.output + "\n",
                encoding="utf-8",
            )

            state.test_exit_code = test_result.exit_code
            state.tests_passed = test_result.passed
            state.tests_failed = test_result.failed
            state.test_counts_verified = test_result.counts_verified
            state.save(state_path)

            reviewer = require_agent(
                repo,
                run_dir,
                "reviewer",
                build_reviewer_task(task),
                (
                    f"Repair cycle {state.repair_cycles} completed.\n"
                    f"Authoritative test exit code: {test_result.exit_code}\n"
                    f"Tests passed: {test_result.passed}\n"
                    f"Tests failed: {test_result.failed}"
                ),
                args.max_agent_time,
                suffix=suffix,
            )

            state.review_result = parse_review_result(
                reviewer.stdout
            )
            state.save(state_path)

        if (current_branch(repo), head_sha(repo)) != (branch, starting_head):
            raise RuntimeError("Branch or HEAD changed during the run")
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
        state.save(state_path)

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
        state.save(state_path)

        final_agent_list = [
            *state.agents_completed,
            "reporter",
        ]

        reporter_facts = json.dumps(
            {
                "task": report_value(state.task),
                "agents_completed": final_agent_list,
                "files_changed": [report_value(path) for path in state.files_changed],
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

        validate_state_for_report(state)
        validate_reporter_output(
            state,
            reporter.stdout,
        )

        if args.skip_discord:
            state.notification_status = "SKIPPED"
        else:
            sent = dispatch_report(
                state_path,
                reporter_path,
            )
            state.notification_status = (
                "SENT" if sent else "FAILED"
            )

        state.save(state_path)

    except (
        RuntimeError,
        StateValidationError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
        KeyboardInterrupt,
    ) as exc:
        state.final_status = "BLOCKED"
        state.notification_status = "NOT_SENT_ERROR"
        try:
            state.save(state_path)
            (run_dir / "error.txt").write_text(str(exc) + "\n", encoding="utf-8")
        except OSError as persistence_error:
            print(f"[foxforge] Could not persist failure: {persistence_error}", file=sys.stderr)

        print(
            f"[foxforge] BLOCKED: {exc}",
            file=sys.stderr,
        )
        print(f"[foxforge] run: {run_dir}")
        return 1

    print(reporter.stdout)
    print(f"Artifacts: {run_dir}")

    return 0 if state.final_status == "READY_FOR_PLAYTEST" and state.notification_status != "FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
