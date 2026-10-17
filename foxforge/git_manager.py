from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from .security import redact
from .process import run_process


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
    env: dict[str, str] | None = None,
    safe: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [git_executable(), *args]

    try:
        result = run_process(command, repo, timeout=120, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError("Git process failed to start or exceeded its deadline" if safe else redact(f"Could not execute Git: {exc}")) from None

    if check and result.returncode != 0:
        if safe:
            raise GitError(f"Git operation failed (exit code {result.returncode}); credential-bearing diagnostics suppressed")
        raise GitError(
            redact(f"Git command failed ({result.returncode}): "
            f"{' '.join(command)}\n\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}")
        )

    return result


def ensure_repo(repo: Path) -> None:
    result = run_git(repo, "rev-parse", "--is-inside-work-tree")
    if result.stdout.strip().lower() != "true":
        raise GitError(f"Not a Git work tree: {repo}")
    root = run_git(repo, "rev-parse", "--show-toplevel").stdout.strip()
    if Path(root).resolve() != repo.resolve():
        raise GitError(f"--repo must identify the Git work tree root: {root}")


def resolve_ref(repo: Path, ref: str) -> str:
    return run_git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").stdout.strip()


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

    if base_branch != "dev":
        raise GitError("Task branches must start from origin/dev")
    run_git(repo, "check-ref-format", "--branch", branch)

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
        "--no-renames",
        "-z",
        resolve_ref(repo, base_ref),
        "--",
    ).stdout.split("\0")

    untracked = run_git(
        repo,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    ).stdout.split("\0")

    paths = {
        line
        for line in [*tracked, *untracked]
        if line
    }
    return sorted(paths)


def diff(repo: Path, base_ref: str) -> str:
    text = run_git(repo, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", resolve_ref(repo, base_ref), "--").stdout
    untracked = run_git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout
    for path in filter(None, untracked.split("\0")):
        result = run_git(repo, "diff", "--no-index", "--no-ext-diff", "--", os.devnull, path, check=False)
        if result.returncode not in (0, 1):
            raise GitError(f"Cannot diff untracked file: {path}\n{result.stderr}")
        text += result.stdout
    return text
