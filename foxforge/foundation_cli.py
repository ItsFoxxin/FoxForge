"""Planning-only control-plane CLI for FoxForge's first adaptive milestone."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .actor_authorization import ActorPolicy
from .capabilities import public_catalog
from .control_plane import ControlPlane, ControlPlaneError
from .github_app import AppConfig, GitHubApp, GitHubAppError, repository_name
from .git_manager import GitError, ensure_repo, resolve_ref
from .issue_api import IssueAPI
from .issue_tasks import IssueError, IssueTask
from .plan_schema import PlanValidationError, parse_plan
from .planning_provider import PlanningProviderError, request_plan
from .publishing import origin_repository
from .repository_discovery import DiscoveryError, discover_repository, planner_context
from .review_artifacts import write_artifacts


PLAN_LABEL = "foxforge:plan"


def snapshot(task: IssueTask) -> dict:
    return {"repository": task.repository, "number": task.number, "title": task.title, "body": task.body,
            "url": task.url, "state": task.state, "labels": list(task.labels), "created_at": task.created_at,
            "updated_at": task.updated_at, "author_id": task.author_id, "revision": task.revision}


def client(repository: str) -> IssueAPI:
    app = GitHubApp(AppConfig.from_env(), repository, issues=True)
    app.check_repository()
    return IssueAPI(app)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="foxforge", description="FoxForge adaptive planning foundation")
    groups = parser.add_subparsers(dest="group", required=True)
    projects = groups.add_parser("projects")
    projects_sub = projects.add_subparsers(dest="command", required=True)
    register = projects_sub.add_parser("register")
    register.add_argument("--repository", required=True)
    register.add_argument("--repo", required=True)
    register.add_argument("--default-branch", default="dev")
    projects_sub.add_parser("list")
    issues = groups.add_parser("issues")
    issues_sub = issues.add_subparsers(dest="command", required=True)
    discover = issues_sub.add_parser("discover")
    discover.add_argument("--project", required=True)
    tasks = groups.add_parser("tasks")
    tasks_sub = tasks.add_subparsers(dest="command", required=True)
    plan = tasks_sub.add_parser("plan")
    plan.add_argument("--project", required=True)
    plan.add_argument("--issue", required=True, type=int)
    plan.add_argument("--plan-file", help="Validated JSON response for offline/fake-provider testing")
    show = tasks_sub.add_parser("show")
    show.add_argument("task_id")
    capabilities = groups.add_parser("capabilities")
    capabilities.add_subparsers(dest="command", required=True).add_parser("list")
    return parser


def register_project(args, store: ControlPlane) -> int:
    repository = repository_name(args.repository)
    repo = Path(args.repo).resolve()
    ensure_repo(repo)
    if origin_repository(repo).casefold() != repository.casefold():
        raise ControlPlaneError("Local origin does not match the requested GitHub repository")
    resolve_ref(repo, f"origin/{args.default_branch}")
    metadata = GitHubApp(AppConfig.from_env(), repository, issues=True).check_repository()
    result = store.register_project(repository_id=metadata["id"], repository=metadata["full_name"],
                                    local_path=repo, default_branch=args.default_branch)
    print(json.dumps(result, indent=2))
    return 0


def discover_issues(args, store: ControlPlane) -> int:
    project = store.project(args.project)
    tasks = client(project["repository"]).list_open()
    for task in tasks:
        store.record_discovery(project, snapshot(task))
    print(json.dumps({"repository": project["repository"], "issues_discovered": len(tasks),
                      "model_requests": 0}, indent=2))
    return 0


def plan_task(args, store: ControlPlane) -> int:
    if args.issue <= 0:
        raise ControlPlaneError("Issue number must be positive")
    project = store.project(args.project)
    api = client(project["repository"])
    issue = api.get(args.issue)
    current = snapshot(issue)
    store.record_discovery(project, current)
    if issue.state != "open" or PLAN_LABEL not in issue.labels:
        raise ControlPlaneError(f"Issue requires the {PLAN_LABEL} label")
    approval = api.approval_for_label(issue.number, PLAN_LABEL, ActorPolicy.from_env(),
                                      not_before=issue.updated_at, max_age_hours=168)
    if approval is None:
        raise ControlPlaneError("Planning label lacks a current allowlisted actor approval")
    confirmed = api.get(args.issue)
    if confirmed != issue:
        raise ControlPlaneError("Issue changed while planning authorization was being verified; review and reapply the planning label")
    task, created = store.authorize_and_create_task(project, current, actor_id=approval[2], event_id=approval[0])
    if not created:
        existing = store.task(task["id"])
        print(json.dumps({"task_id": existing["id"], "state": existing["state"], "duplicate": True,
                          "artifact_dir": existing["artifact_dir"]}, indent=2))
        return 0 if existing["state"] == "awaiting_human_review" else 1
    try:
        store.update_task(task["id"], state="active", activity="analyzing")
        discovery = discover_repository(Path(project["local_path"]), f"origin/{project['default_branch']}")
        task = store.update_task(task["id"], state="active", activity="planning", base_sha=discovery["commit"], discovery=discovery)
        if args.plan_file:
            plan = parse_plan(Path(args.plan_file).read_text(encoding="utf-8"))
            telemetry = {"configured_model": "plan-file", "routed_via": None, "usage": {}, "source": "operator-supplied"}
        else:
            plan, telemetry = request_plan(requirement=issue.task_text, discovery_context=planner_context(discovery))
        directory = store.artifacts(task["id"])
        write_artifacts(directory, task, plan, discovery, telemetry)
        task = store.update_task(task["id"], state="awaiting_human_review", activity="idle", plan=plan, artifact_dir=directory)
        print(json.dumps({"task_id": task["id"], "state": task["state"], "artifact_dir": str(directory),
                          "plan": str(directory / "plan.md")}, indent=2))
        return 0
    except (OSError, DiscoveryError, IssueError, PlanValidationError, PlanningProviderError, ValueError):
        store.update_task(task["id"], state="blocked", activity="idle", error_code="PLANNING_FAILED")
        raise


def show_task(args, store: ControlPlane) -> int:
    print(json.dumps(store.task(args.task_id), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if (args.group, args.command) == ("capabilities", "list"):
            print(json.dumps(public_catalog(), indent=2)); return 0
        store = ControlPlane()
        if (args.group, args.command) == ("projects", "register"):
            return register_project(args, store)
        if (args.group, args.command) == ("projects", "list"):
            print(json.dumps(store.projects(), indent=2)); return 0
        if (args.group, args.command) == ("issues", "discover"):
            return discover_issues(args, store)
        if (args.group, args.command) == ("tasks", "plan"):
            return plan_task(args, store)
        if (args.group, args.command) == ("tasks", "show"):
            return show_task(args, store)
        raise ControlPlaneError("Unknown foundation command")
    except (ControlPlaneError, GitError, GitHubAppError, IssueError, DiscoveryError, PlanValidationError,
            PlanningProviderError, OSError, ValueError) as exc:
        print(f"[foxforge] {exc}", file=sys.stderr)
        return 1
