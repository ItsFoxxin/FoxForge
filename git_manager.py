from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


WINDOWS_DEFAULT_GIT = Path(r"C:\Program Files\Git\cmd\git.exe")


class GitError(RuntimeError):
    pass


def git_executable() -> str:
    configured = os.getenv("FOXFORGE_GIT_EXE")
    if configured:
        path = Path(configured)
        if not path.exists():
            raise GitError(
                f"FOXFORGE_GIT_EXE does not exist: {path}"
            )
        return str(path)

    if os.name == "nt" and WINDOWS_DEFAULT_GIT.exists():
        return str(WINDOWS_DEFAULT_GIT)

    detected = shutil.which("git")
    if detected:
        return detected

    raise GitError(
        "Git executable was not found. Set FOXFORGE_GIT_EXE "
        "to the full path of git.exe."
    )


def run_git(
    repo: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = [git_executable(), *args]

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


def worktree_status(repo: Path) -> str:
    return run_git(repo, "status", "--porcelain").stdout.strip()


def ensure_clean_worktree(repo: Path) -> None:
    status = worktree_status(repo)
    if status:
        raise GitError(
            "Working tree is not clean. Refusing to create a task branch.\n\n"
            + status
        )


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
    ensure_clean_worktree(repo)
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
    return run_git(repo, "diff", base_ref, "--").stdout


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
