"""Manual issue execution first; sequential polling reuses the same path."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from . import coordinator
from . import run_storage
from .github_app import AppConfig, GitHubApp, GitHubAppError
from .git_manager import ensure_repo, ensure_clean_worktree, run_git
from .intake_storage import atomic_json, issue_key, load_record, local_lock, outside_repo, record_path, worktree_key
from .issue_api import IssueAPI
from .actor_authorization import ActorPolicy
from .issue_tasks import BLOCKED, COMPLETE, ISSUE_LABELS, RUNNING, IssueError, IssueTask
from .process import duration_seconds
from .publishing import PublishingError, origin_repository, fetch_dev_branch
from .run_storage import create_run_dir
from .security import ensure_key_outside_repo
from .state import RunState
from .state_validator import validate_issue_fields, validate_state_for_report


def parse_args(command: str, argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=f"foxforge {command}", description="Explicit GitHub Issue intake using the existing FoxForge coordinator")
    if command == "issue":
        parser.add_argument("number", type=int, help="Approved GitHub issue number")
    parser.add_argument("--repo", required=True, help="Local target worktree; GitHub identity is derived from origin")
    parser.add_argument("--test-command", required=True, help="Trusted operator-supplied authoritative test command")
    parser.add_argument("--publish-pr", action="store_true", required=True, help="Explicit approval for App publishing of successful issue tasks")
    parser.add_argument("--skip-discord", action="store_true")
    parser.add_argument("--max-agent-time", default="20m")
    parser.add_argument("--max-test-time", default="20m")
    if command == "watch":
        parser.add_argument("--poll-interval", type=float, default=60, help="Seconds between polls (minimum 10)")
        parser.add_argument("--once", action="store_true", help="Poll once and run at most one issue")
    args = parser.parse_args(argv)
    try:
        duration_seconds(args.max_agent_time)
        duration_seconds(args.max_test_time)
        if command == "issue" and args.number <= 0:
            raise ValueError("Issue number must be positive")
        if command == "watch" and (not 10 <= args.poll_interval <= 86400):
            raise ValueError("Polling interval must be between 10 and 86400 seconds")
    except ValueError as exc:
        parser.error(str(exc))
    return args


def _client(repo: Path) -> IssueAPI:
    ensure_repo(repo)
    ensure_clean_worktree(repo)
    ensure_key_outside_repo(repo)
    api = IssueAPI(GitHubApp(AppConfig.from_env(), origin_repository(repo), publishing=True, issues=True))
    api.app.check_repository()
    return api


def _running_diagnostic(repo: Path, repository: str, number: int) -> IssueError:
    try:
        record = load_record(repo, repository, number)
        entry = record["attempts"][-1]
        state = RunState.load(Path(entry["state_path"]))
        validate_issue_fields(state)
        if (state.github_repository.casefold() != repository.casefold() or state.github_issue_number != number
                or state.run_id != entry["run_id"] or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", state.run_id)):
            raise ValueError
        return IssueError(f"Interrupted or active local run {state.run_id} exists for issue #{number}; inspect it before restarting")
    except (RuntimeError, OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return IssueError(f"Issue #{number} is running without trustworthy matching local state; intervention required")


def _history(repo: Path, snapshot: IssueTask, record: dict) -> set[str]:
    allowed = set()
    known_paths = set()
    for entry in record["attempts"]:
        try:
            if entry["phase"] != "BLOCKED":
                raise IssueError("Existing active, completed, interrupted, or uncertain issue run; intervention required")
            path = Path(entry["state_path"]).resolve()
            if path.is_relative_to(repo) or path.name != "state.json":
                raise ValueError
            old = RunState.load(path)
            validate_issue_fields(old)
            if (old.run_id != entry["run_id"] or old.github_repository.casefold() != snapshot.repository.casefold()
                    or old.github_issue_number != snapshot.number or old.branch != entry["branch"]
                    or old.final_status != "BLOCKED" or old.github_issue_status != "BLOCKED"
                    or old.issue_sync_status != "SYNCED" or old.commit_sha or old.remote_branch or old.pull_request_number):
                raise ValueError
            allowed.add(old.branch)
            known_paths.add(path)
            exists = run_git(repo, "show-ref", "--verify", f"refs/heads/{old.branch}", check=False, safe=True)
            if exists.returncode == 0 and exists.stdout.split()[0] != old.validated_head_sha:
                raise ValueError
        except (KeyError, TypeError, OSError, ValueError, RuntimeError, AttributeError) as exc:
            if isinstance(exc, IssueError):
                raise
            raise IssueError("Prior issue run cannot be verified; preserve artifacts and intervene") from None
    # An unindexed matching state must never create a second run, even if its
    # remote running label disappeared. The central reservation also survives
    # changing FOXFORGE_RUNS_DIR between invocations.
    paths = list(run_storage.runs_root().glob("*/*/state.json"))
    if len(paths) > 10000:
        raise IssueError("Local RunState scan limit exceeded; intervention required")
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            matches = data.get("github_repository", "")
            if isinstance(matches, str) and matches.casefold() == snapshot.repository.casefold() and data.get("github_issue_number") == snapshot.number and path.resolve() not in known_paths:
                raise IssueError("Existing unindexed issue RunState; intervention required")
        except (OSError, ValueError, AttributeError):
            raise IssueError("Local RunState cannot be inspected safely; intervention required") from None
    return allowed


def _duplicates(repo: Path, snapshot: IssueTask, record: dict, api: IssueAPI) -> None:
    allowed = _history(repo, snapshot, record)
    refs = run_git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/foxforge/", "refs/remotes/origin/foxforge/", safe=True).stdout.splitlines()
    for ref in refs:
        branch = ref.removeprefix("refs/heads/").removeprefix("refs/remotes/origin/")
        if branch.startswith(f"foxforge/{snapshot.number}-") and (ref.startswith("refs/remotes/") or branch not in allowed):
            raise IssueError("Existing local/tracking issue branch; intervention required")
    api.remote_conflicts(snapshot.number)


def _new_state(snapshot: IssueTask, run_id: str, branch: str, approval: tuple[int, str, int]) -> RunState:
    return RunState(run_id, snapshot.task_text, branch, "origin/dev", publish_requested=True,
                    github_repository=snapshot.repository, publishing_status="PENDING",
                    github_issue_number=snapshot.number, github_issue_url=snapshot.url,
                    github_issue_title=snapshot.title, github_issue_body=snapshot.body,
                    github_issue_labels=list(snapshot.labels), github_issue_created_at=snapshot.created_at,
                    github_issue_updated_at=snapshot.updated_at, github_issue_revision=snapshot.revision,
                    github_issue_ready_event_id=approval[0], github_issue_approved_by=approval[1],
                    github_issue_author_id=snapshot.author_id, github_issue_approved_by_id=approval[2],
                    github_issue_status="PENDING", issue_sync_status="PENDING")


def result_comment(state: RunState) -> str:
    """Facts only. Never accept a model-written notification or reviewer prose."""
    validate_issue_fields(state)
    if any(type(value) is not int or value < 0 for value in (state.tests_passed, state.tests_failed, state.repair_cycles)) or state.repair_cycles > 3:
        raise IssueError("Invalid result counters")
    if type(state.test_counts_verified) is not bool or state.review_result not in {"NOT_RUN", "PASS", "FAIL", "UNPARSEABLE"}:
        raise IssueError("Invalid result verification facts")
    success = state.final_status == "READY_FOR_PLAYTEST" and state.publishing_status == "PUBLISHED"
    if success:
        validate_state_for_report(state)
    tests = f"{state.tests_passed} passed, {state.tests_failed} failed" if state.test_counts_verified else "not verified"
    text = (f"FoxForge — {'READY_FOR_PLAYTEST' if success else 'BLOCKED'}\n\nRun: {state.run_id}\n"
            f"Branch: {state.branch}\nLocal validation: {state.final_status}\nPublishing: {state.publishing_status}\n"
            f"Tests: {tests}\nReview: {state.review_result}\nRepair cycles: {state.repair_cycles}/3")
    if state.publishing_status == "PUBLISHED":
        # Publication metadata may survive a later Reporter failure, but a URL
        # is never copied from issue/agent text.
        from .state_validator import _validate_publishing_fields
        _validate_publishing_fields(state)
        text += f"\nPR: {state.pull_request_url}"
    if not success:
        summaries = {"PASS": "Reviewer returned PASS; another required step did not complete.",
                     "FAIL": "Reviewer returned FAIL.", "UNPARSEABLE": "Reviewer verdict was not valid.",
                     "NOT_RUN": "Reviewer did not complete."}
        text += f"\nRemaining issue summary: {summaries[state.review_result]}\nManual intervention required."
    return text


def _guard(api: IssueAPI, snapshot: IssueTask, state: RunState, path: Path) -> None:
    try:
        api.require_running(snapshot)
    except IssueError as exc:
        state.issue_error = "ISSUE_CHANGED" if str(exc) == "ISSUE_CHANGED" else "CLAIM_LOST"
        state.github_issue_status = "INTERVENTION"
        state.final_status = "BLOCKED"
        state.publishing_status = "BLOCKED"
        state.publishing_error = "Claimed issue requirements or approval changed; publishing blocked"
        state.save(path)
        raise PublishingError(state.publishing_error) from None


def _sync(api: IssueAPI, snapshot: IssueTask, state: RunState, path: Path) -> None:
    try:
        current = api.get(snapshot.number)
        if current.state != "open" or set(current.labels) & ISSUE_LABELS != {RUNNING}:
            raise IssueError("Claim no longer held; do not overwrite owner label changes")
        if current.revision != snapshot.revision:
            state.final_status = "BLOCKED"
            state.issue_error = "ISSUE_CHANGED"
        success = state.final_status == "READY_FOR_PLAYTEST" and state.publishing_status == "PUBLISHED"
        state.issue_result_comment_id = api.comment(state, result_comment(state), "result")
        state.save(path)
        api.transition(snapshot.number, COMPLETE if success else BLOCKED)
        state.github_issue_status = "COMPLETE" if success else "BLOCKED"
        state.issue_sync_status = "SYNCED"
    except (RuntimeError, OSError, ValueError, TypeError):
        # No automatic POST retry or compensating label overwrite: a network
        # timeout can mean the write succeeded and its response was lost.
        state.github_issue_status = "INTERVENTION"
        state.issue_sync_status = "FAILED"
        state.issue_error = state.issue_error or "SYNC_FAILED"
    state.save(path)


def execute_issue(args: argparse.Namespace, *, api: IssueAPI | None = None, worktree_locked: bool = False) -> int:
    policy = ActorPolicy.from_env()
    repo = Path(args.repo).resolve()
    with ExitStack() as stack:
        if not worktree_locked:
            stack.enter_context(local_lock(repo, "worktree-" + worktree_key(repo)))
        api = api or _client(repo)
        if origin_repository(repo).casefold() != api.repository.casefold():
            raise IssueError("Issue client does not match target origin")
        stack.enter_context(local_lock(repo, "issue-" + issue_key(api.repository, args.number)))
        ensure_clean_worktree(repo)
        snapshot = api.get(args.number)
        policy.require(snapshot.author_id)
        if RUNNING in snapshot.labels:
            raise _running_diagnostic(repo, api.repository, snapshot.number)
        snapshot.require_ready()
        if api.ready_approval(snapshot.number, policy) is None:
            raise IssueError("Ready label lacks allowlisted actor approval; an approved actor must remove and reapply it")
        record = load_record(repo, snapshot.repository, snapshot.number)
        _duplicates(repo, snapshot, record, api)
        fresh = api.get(args.number)
        policy.require(fresh.author_id)
        fresh.require_ready()
        if fresh.revision != snapshot.revision or fresh.author_id != snapshot.author_id:
            raise IssueError("Issue changed during preflight; no claim was made")
        snapshot = fresh
        approval = api.ready_approval(snapshot.number, policy)
        if approval is None:
            raise IssueError("Issue approval changed during preflight; no claim was made")
        branch = snapshot.branch(len(record["attempts"]) + 1)
        run_git(repo, "check-ref-format", "--branch", branch, safe=True)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:12]
        run_dir = create_run_dir(repo, run_id)
        state = _new_state(snapshot, run_id, branch, approval)
        path = run_dir / "state.json"
        state.save(path)  # Identity is durable before the first remote mutation.
        atomic_json(run_dir / "issue-snapshot.json", state.to_dict())
        entry = {"run_id": run_id, "branch": branch, "state_path": str(path), "worktree": str(repo), "phase": "RESERVED"}
        record["attempts"].append(entry)
        ledger = record_path(repo, snapshot.repository, snapshot.number)
        atomic_json(ledger, record)
        claimed, hooks = False, None
        code = 1
        try:
            state.github_issue_status = "CLAIMING"
            state.save(path)
            api.transition(snapshot.number, RUNNING)
            api.require_running(snapshot)
            claimed = True
            state.github_issue_status = "RUNNING"
            state.save(path)
            entry["phase"] = "RUNNING"
            atomic_json(ledger, record)
            state.issue_claim_comment_id = api.comment(state, f"FoxForge claimed this issue.\nRun: {run_id}\nBranch: {branch}", "claim")
            state.save(path)
            argv = ["--repo", str(repo), "--task", snapshot.task_text, "--test-command", args.test_command,
                    "--create-branch", "--branch-name", branch, "--base-branch", "dev", "--publish-pr",
                    "--max-agent-time", args.max_agent_time, "--max-test-time", args.max_test_time]
            if args.skip_discord:
                argv.append("--skip-discord")
            hooks = coordinator.RunHooks(state, run_dir, lambda s, p: _guard(api, snapshot, s, p), lambda s, p: _sync(api, snapshot, s, p),
                                         fetch_origin=lambda target: fetch_dev_branch(target, api.repository, run_dir, api.app.installation_token()))
            code = coordinator.run(coordinator.parse_args(argv), hooks=hooks)
            if hooks.interrupted:
                raise KeyboardInterrupt
            if state.issue_sync_status == "PENDING":
                _sync(api, snapshot, state, path)
        except KeyboardInterrupt:
            state.final_status = "BLOCKED"
            state.github_issue_status = "INTERRUPTED"
            state.issue_error = "INTERRUPTED"
            entry["phase"] = "INTERRUPTED"
            state.save(path)
            atomic_json(ledger, record)
            print(f"[foxforge] Interrupted issue run {run_id}; preserved for intervention", file=sys.stderr)
            return 130
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
            state.final_status = "BLOCKED"
            state.issue_error = state.issue_error or "EXECUTION_FAILED"
            if claimed:
                _sync(api, snapshot, state, path)
            else:
                state.github_issue_status = "INTERVENTION"
                state.issue_sync_status = "FAILED"
            code = 1
        state.save(path)
        entry["phase"] = state.github_issue_status if state.issue_sync_status == "SYNCED" else "INTERVENTION"
        entry["exit_code"] = code
        atomic_json(ledger, record)
        print(f"[foxforge] issue #{snapshot.number}, run {run_id}, issue state {state.github_issue_status}; artifacts: {run_dir}")
        return code if state.issue_sync_status == "SYNCED" else 1


def watch(args: argparse.Namespace) -> int:
    policy = ActorPolicy.from_env()
    repo = Path(args.repo).resolve()
    with local_lock(repo, "worktree-" + worktree_key(repo)):
        api = _client(repo)
        status_path = outside_repo(repo) / "workers" / (worktree_key(repo) + ".json")
        def status(value, number=None):
            atomic_json(status_path, {"repository": api.repository, "worktree": str(repo), "status": value,
                                      "issue": number, "updated_at": datetime.now(timezone.utc).isoformat()})
        try:
            while True:
                status("POLLING")
                ensure_clean_worktree(repo)
                running = api.list_label(RUNNING)
                running = [task for task in running if policy.allows(task.author_id)]
                if running:
                    raise _running_diagnostic(repo, api.repository, running[0].number)
                ready = api.list_label("foxforge-ready")
                approved = []
                for task in ready:
                    if not policy.allows(task.author_id):
                        print("[foxforge] UNAUTHORIZED_GITHUB_ACTOR: issue skipped", file=sys.stderr)
                        continue
                    if api.ready_approval(task.number, policy) is not None:
                        approved.append(task)
                ready = approved
                if ready:
                    chosen = ready[0]
                    chosen.require_ready()
                    status("RUNNING", chosen.number)
                    args.number = chosen.number
                    code = execute_issue(args, api=api, worktree_locked=True)
                    if code:
                        status("INTERVENTION", chosen.number)
                        return code
                if args.once:
                    status("STOPPED")
                    return 0
                status("WAITING")
                time.sleep(args.poll_interval)
        except KeyboardInterrupt:
            status("STOPPED")
            return 0
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
            status("INTERVENTION")
            raise


def main(command: str, argv: list[str]) -> int:
    args = parse_args(command, argv)
    try:
        return execute_issue(args) if command == "issue" else watch(args)
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        detail = str(exc) if isinstance(exc, (IssueError, GitHubAppError)) else "Local setup, execution, or persistence failed"
        print(f"[foxforge] Issue intake stopped: {detail}. No automatic restart. Inspect external intake records and RunState.", file=sys.stderr)
        return 1
