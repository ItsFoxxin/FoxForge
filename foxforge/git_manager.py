from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


DEFAULT_GIT_EXE = Path(r"C:\Program Files\Git\cmd\git.exe")


class GitError(RuntimeError):
    pass


def git_executable() -> Path:
    configured = os.getenv("FOXFORGE_GIT_EXE")
    path = Path(configured) if configured else DEFAULT_GIT_EXE

    if not path.exists():
        raise GitError(
            f"Git executable not found: {path}\n"
            "Set FOXFORGE_GIT_EXE to the full path of git.exe."
        )

    return path


def run_git(
    repo: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = [str(git_executable()), *args]

    result = subprocess.run(
        command,
        cwd=repo,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    if check and result.returncode != 0:
        raise GitError(
            f"Git command failed ({result.returncode}): "
            f"{' '.join(command)}\n\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    return result


def ensure_repo(repo: Path) -> None:
    result = run_git(repo, "rev-parse", "--is-inside-work-tree")
    if result.stdout.strip().lower() != "true":
        raise GitError(f"Not a Git work tree: {repo}")


def fetch(repo: Path) -> None:
    run_git(repo, "fetch", "origin", "--prune")


def current_branch(repo: Path) -> str:
    return run_git(repo, "branch", "--show-current").stdout.strip()


def head_sha(repo: Path) -> str:
    return run_git(repo, "rev-parse", "HEAD").stdout.strip()


def has_tracked_worktree_changes(repo: Path) -> bool:
    unstaged = run_git(repo, "diff", "--quiet", check=False).returncode != 0
    staged = (
        run_git(repo, "diff", "--cached", "--quiet", check=False).returncode
        != 0
    )
    return unstaged or staged


def local_branch_exists(repo: Path, branch: str) -> bool:
    result = run_git(
        repo,
        "show-ref",
        "--verify",
        f"refs/heads/{branch}",
        check=False,
    )
    return result.returncode == 0


def remote_branch_exists(repo: Path, branch: str) -> bool:
    result = run_git(
        repo,
        "show-ref",
        "--verify",
        f"refs/remotes/origin/{branch}",
        check=False,
    )
    return result.returncode == 0


def slugify_task(task: str, max_length: int = 48) -> str:
    slug = task.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    slug = slug[:max_length].rstrip("-")
    return slug or "task"


def create_task_branch(
    repo: Path,
    branch: str,
    base_branch: str = "dev",
) -> None:
    if not branch.startswith("foxforge/"):
        raise GitError(
            "FoxForge task branches must begin with 'foxforge/'."
        )

    ensure_repo(repo)

    if has_tracked_worktree_changes(repo):
        raise GitError(
            "Tracked working-tree changes already exist. "
            "Refusing to switch branches."
        )

    fetch(repo)

    if local_branch_exists(repo, branch) or remote_branch_exists(repo, branch):
        raise GitError(f"Branch already exists: {branch}")

    run_git(
        repo,
        "switch",
        "--create",
        branch,
        f"origin/{base_branch}",
    )


def changed_files(repo: Path, base_ref: str) -> list[str]:
    tracked = run_git(
        repo,
        "diff",
        "--name-only",
        base_ref,
        "--",
    ).stdout.splitlines()

    untracked = run_git(
        repo,
        "ls-files",
        "--others",
        "--exclude-standard",
    ).stdout.splitlines()

    paths = {
        line.strip()
        for line in [*tracked, *untracked]
        if line.strip()
    }

    return sorted(paths)


def diff(repo: Path, base_ref: str) -> str:
    return run_git(
        repo,
        "diff",
        base_ref,
        "--",
    ).stdout


def push_branch(repo: Path, branch: str) -> None:
    if not branch.startswith("foxforge/"):
        raise GitError(
            "Refusing to push a branch outside the foxforge/ namespace."
        )

    run_git(
        repo,
        "push",
        "--set-upstream",
        "origin",
        branch,
    )
