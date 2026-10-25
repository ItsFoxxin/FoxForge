"""Explicit, Python-owned commit/push/PR publishing after local validation."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from urllib.parse import quote, urlencode, urlsplit
from typing import Callable

from .github_app import BotIdentity, GitHubApp, GitHubAppError, repository_name
from .git_manager import GitError, current_branch, head_sha, run_git, resolve_ref
from .security import child_environment, ensure_key_outside_repo, redact, require_execution_worker
from .state import RunState
from .state_validator import validate_state_for_publish


class PublishingError(RuntimeError):
    pass


def validate_task_branch(repo: Path, branch: str) -> None:
    if not isinstance(branch, str) or not re.fullmatch(r"foxforge/[A-Za-z0-9][A-Za-z0-9._/-]*", branch) or redact(branch) != branch:
        raise PublishingError("Publishing requires a credential-free foxforge/* task branch")
    if run_git(repo, "check-ref-format", "--branch", branch, check=False, safe=True).returncode != 0:
        raise PublishingError("Invalid FoxForge task branch")
    if current_branch(repo) != branch:
        raise PublishingError("Current branch does not match the validated task branch")


def origin_repository(repo: Path) -> str:
    result = run_git(repo, "remote", "get-url", "--all", "origin", safe=True)
    urls = result.stdout.splitlines()
    if len(urls) != 1:
        raise PublishingError("Publishing requires exactly one origin URL")
    url = urls[0]
    if url.startswith("git@github.com:"):
        name = url[len("git@github.com:"):]
    else:
        try:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
                raise ValueError
            name = parsed.path.lstrip("/")
        except ValueError:
            raise PublishingError("Origin must be a credential-free GitHub HTTPS or git@github.com URL") from None
    if name.endswith(".git"):
        name = name[:-4]
    try:
        return repository_name(name)
    except GitHubAppError:
        raise PublishingError("Origin does not identify a supported GitHub repository") from None


def worktree_fingerprint(repo: Path, base_ref: str | None = None) -> str:
    """Content/mode identity, including untracked binaries, without staging."""
    names = run_git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z").stdout
    names += run_git(repo, "ls-tree", "-r", "--name-only", "-z", base_ref or "HEAD").stdout
    digest = hashlib.sha256()
    for name in sorted(set(filter(None, names.split("\0")))):
        path = repo / name
        digest.update(name.encode("utf-8") + b"\0")
        if not path.exists() and not path.is_symlink():
            digest.update(b"deleted\0")
        elif path.is_symlink():
            digest.update(b"link\0" + os.readlink(path).encode("utf-8") + b"\0")
        elif path.is_file():
            digest.update(str(stat.S_IMODE(path.stat().st_mode)).encode() + b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
        else:
            raise PublishingError("Publishing submodules or special files is not supported")
    return digest.hexdigest()


_ASKPASS = '''import os, sys
from urllib.parse import urlsplit
prompt = sys.argv[1] if len(sys.argv) > 1 else ""
try:
    address = prompt.split("'", 2)[1]
    url = urlsplit(address)
    expected = "/" + os.environ["_FOXFORGE_REPOSITORY"].casefold()
    if url.scheme != "https" or url.hostname != "github.com" or url.port or url.query or url.fragment or url.username not in (None, "x-access-token") or url.path.casefold() not in (expected, expected + ".git"):
        raise ValueError()
    if prompt.startswith("Username for "):
        print("x-access-token")
    elif prompt.startswith("Password for "):
        print(os.environ["_FOXFORGE_INSTALLATION_TOKEN"])
    else:
        raise ValueError()
except Exception:
    sys.exit(1)
'''


@contextmanager
def git_credentials(run_dir: Path, repository: str, token: str):
    """Helpers contain no secret. Token exists only in this child's environment."""
    repository_name(repository)
    with tempfile.TemporaryDirectory(prefix="git-auth-", dir=run_dir) as directory:
        directory = Path(directory)
        script = directory / "askpass.py"
        script.write_text(_ASKPASS, encoding="utf-8")
        helper = directory / ("askpass.cmd" if os.name == "nt" else "askpass.sh")
        helper.write_text(
            '@echo off\nsetlocal DisableDelayedExpansion\n"%_FOXFORGE_ASKPASS_PYTHON%" -I -S "%_FOXFORGE_ASKPASS_SCRIPT%" %*\n'
            if os.name == "nt" else '#!/bin/sh\nexec "$_FOXFORGE_ASKPASS_PYTHON" -I -S "$_FOXFORGE_ASKPASS_SCRIPT" "$@"\n',
            encoding="utf-8",
        )
        helper.chmod(0o700)
        hooks = directory / "no-hooks"
        hooks.mkdir()
        env = child_environment()
        env.update(GIT_ASKPASS=str(helper), GIT_ASKPASS_REQUIRE="force",
                   _FOXFORGE_INSTALLATION_TOKEN=token, _FOXFORGE_REPOSITORY=repository,
                   _FOXFORGE_ASKPASS_SCRIPT=str(script), _FOXFORGE_ASKPASS_PYTHON=sys.executable,
                   PYTHONIOENCODING="utf-8")
        options = ["-c", "credential.helper=", "-c", "credential.useHttpPath=true",
                   "-c", f"core.hooksPath={hooks.as_posix()}", "-c", "core.fsmonitor=false",
                   "-c", "http.extraHeader=", "-c", "http.followRedirects=false", "-c", "http.sslVerify=true",
                   "-c", "push.gpgSign=false", "-c", "protocol.ext.allow=never", "-c", "protocol.file.allow=never"]
        try:
            yield env, options
        finally:
            env.pop("_FOXFORGE_INSTALLATION_TOKEN", None)


def _assert_safe_git_config(repo: Path) -> None:
    # URL rewrites, per-URL auth headers and proxy auth must not reroute/expose the token.
    result = run_git(repo, "config", "--local", "--includes", "--name-only", "--get-regexp",
                     r"^(url\..*\.(insteadof|pushinsteadof)|http\..*\.(extraheader|proxy|sslverify)|http\.proxy|credential\..*\.helper)$",
                     check=False, safe=True)
    if result.returncode == 0 and result.stdout.strip():
        raise PublishingError("Repository Git authentication/URL overrides require manual review before publishing")
    if result.returncode not in (0, 1):
        raise PublishingError("Could not inspect repository Git authentication settings")


def commit_validated_changes(repo: Path, state: RunState, bot: BotIdentity, run_dir: Path) -> str:
    require_execution_worker()
    validate_task_branch(repo, state.branch)
    if head_sha(repo) != state.validated_head_sha or worktree_fingerprint(repo, state.validated_head_sha) != state.validated_tree_hash:
        raise PublishingError("Repository content or HEAD changed after authoritative validation")
    if run_git(repo, "diff", "--cached", "--quiet", "HEAD", check=False, safe=True).returncode != 0:
        raise PublishingError("Unexpected staged changes; Python owns the publishing index")
    ensure_key_outside_repo(repo)
    for name in state.files_changed:
        path = repo / name
        if (path.name.startswith(".env") and path.suffix not in {".example", ".sample", ".template"}) or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
            raise PublishingError("Refusing to publish credential-like files")
        if path.is_file() and not path.is_symlink():
            # Do not commit actual configured/generated credentials, even if ignored rules are wrong.
            carry = b""
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    content = (carry + chunk).decode("utf-8", errors="replace")
                    if redact(content) != content:
                        raise PublishingError("Refusing to publish content containing credential material")
                    carry = (carry + chunk)[-8192:]
    env = child_environment()
    env.update(GIT_AUTHOR_NAME=bot.login, GIT_AUTHOR_EMAIL=bot.email,
               GIT_COMMITTER_NAME=bot.login, GIT_COMMITTER_EMAIL=bot.email)
    with tempfile.TemporaryDirectory(prefix="commit-hooks-", dir=run_dir) as hooks:
        options = ["-c", f"core.hooksPath={Path(hooks).as_posix()}", "-c", "core.fsmonitor=false", "-c", "commit.gpgsign=false"]
        run_git(repo, *options, "add", "--all", "--", ".", env=env, safe=True)
        if worktree_fingerprint(repo, state.validated_head_sha) != state.validated_tree_hash:
            raise PublishingError("Repository changed while staging validated files")
        staged = run_git(repo, "diff", "--cached", "--quiet", "HEAD", check=False, safe=True)
        if staged.returncode == 0:
            # Safe retry/no-op only for a previously bot-authored task commit.
            message = run_git(repo, "show", "-s", "--format=%B", "HEAD", safe=True).stdout
            author = run_git(repo, "show", "-s", "--format=%ae", "HEAD", safe=True).stdout.strip()
            committer = run_git(repo, "show", "-s", "--format=%ce", "HEAD", safe=True).stdout.strip()
            if author != bot.email or committer != bot.email or f"FoxForge-Branch: {state.branch}" not in message.splitlines() or f"FoxForge-Repository: {state.github_repository}" not in message.splitlines():
                raise PublishingError("No validated changes to commit and HEAD is not a FoxForge task commit")
            return head_sha(repo)
        if staged.returncode != 1:
            raise PublishingError("Could not verify the staged task changes")
        subject = " ".join((state.github_issue_title or state.task).split())[:100]
        message = f"FoxForge: {subject}\n\nFoxForge-Run: {state.run_id}\nFoxForge-Branch: {state.branch}\nFoxForge-Repository: {state.github_repository}\n"
        run_git(repo, *options, "commit", "--no-gpg-sign", "-m", message, env=env, safe=True)
        state.commit_sha = head_sha(repo)
    if worktree_fingerprint(repo, state.validated_head_sha) != state.validated_tree_hash:
        raise PublishingError("Repository content changed during the publishing commit")
    return head_sha(repo)


def push_task_branch(repo: Path, state: RunState, run_dir: Path, token: str, expected_remote: str | None) -> None:
    require_execution_worker()
    validate_task_branch(repo, state.branch)
    if head_sha(repo) != state.commit_sha or worktree_fingerprint(repo, state.validated_head_sha) != state.validated_tree_hash:
        raise PublishingError("Repository changed before the task branch push")
    if origin_repository(repo).casefold() != state.github_repository.casefold():
        raise PublishingError("Origin changed after publishing was requested")
    _assert_safe_git_config(repo)
    if expected_remote and run_git(repo, "merge-base", "--is-ancestor", expected_remote, state.commit_sha, check=False, safe=True).returncode != 0:
        raise PublishingError("Refusing to rewrite existing remote task history")
    ref = f"refs/heads/{state.branch}"
    # Explicit expected-ref lease prevents creating over a racing foreign branch.
    # Existing refs additionally require the fast-forward ancestry check above.
    with git_credentials(run_dir, state.github_repository, token) as (env, options):
        run_git(repo, *options, "push", "--porcelain", f"--force-with-lease={ref}:{expected_remote or ''}",
                f"https://github.com/{state.github_repository}.git", f"{state.commit_sha}:{ref}", env=env, safe=True)


def fetch_dev_branch(repo: Path, repository: str, run_dir: Path, token: str) -> None:
    """Unattended intake fetches dev using the same ephemeral App credentials."""
    require_execution_worker()
    if origin_repository(repo).casefold() != repository.casefold():
        raise PublishingError("Origin changed before the issue base fetch")
    _assert_safe_git_config(repo)
    with git_credentials(run_dir, repository, token) as (env, options):
        run_git(repo, *options, "fetch", "--no-tags", f"https://github.com/{repository}.git",
                "refs/heads/dev:refs/remotes/origin/dev", env=env, safe=True)


def pr_marker(state: RunState) -> str:
    return f"<!-- foxforge:{state.github_repository.casefold()}:{state.branch} -->"


def _assert_owned_history(repo: Path, state: RunState, bot: BotIdentity) -> None:
    history = run_git(repo, "rev-list", f"{state.base_ref}..{state.validated_head_sha}", "--", safe=True).stdout.splitlines()
    for sha in history:
        fields = run_git(repo, "show", "-s", "--format=%ae%x00%ce%x00%B", sha, safe=True).stdout.split("\0", 2)
        if len(fields) != 3 or fields[0] != bot.email or fields[1] != bot.email or f"FoxForge-Branch: {state.branch}" not in fields[2].splitlines() or f"FoxForge-Repository: {state.github_repository}" not in fields[2].splitlines():
            raise PublishingError("Task branch contains commits outside FoxForge's verified branch/repository ownership")


def _validate_pr(data, state: RunState, bot: BotIdentity, *, sha: str | None = None) -> dict:
    try:
        number = data["number"]
        expected_url = f"https://github.com/{state.github_repository}/pull/{number}"
        if type(number) is not int or number <= 0 or data["html_url"].casefold() != expected_url.casefold():
            raise ValueError
        if data["state"] != "open" or data.get("merged_at") or data["base"]["ref"] != "dev" or data["head"]["ref"] != state.branch:
            raise ValueError
        if any(data[side]["repo"]["full_name"].casefold() != state.github_repository.casefold() for side in ("head", "base")):
            raise ValueError
        if data["user"]["id"] != bot.user_id or data["user"]["login"] != bot.login or pr_marker(state) not in data["body"]:
            raise ValueError
        if sha is not None and data["head"]["sha"] != sha:
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise PublishingError("Existing/returned pull request failed repository, owner, branch, or dev-target validation") from None
    return {"number": number, "url": expected_url}


def find_existing_pr(app: GitHubApp, state: RunState, bot: BotIdentity, sha: str | None = None):
    # Deliberately omit base filter: an existing PR targeting main must be rejected.
    query = urlencode({"state": "open", "head": state.github_repository.split("/")[0] + ":" + state.branch, "per_page": 100})
    items = app.api("GET", f"/repos/{state.github_repository}/pulls?{query}")
    if not isinstance(items, list) or len(items) > 1:
        raise PublishingError("Ambiguous existing task pull requests")
    return _validate_pr(items[0], state, bot, sha=sha) if items else None


def ensure_pull_request(app: GitHubApp, state: RunState, bot: BotIdentity) -> dict:
    require_execution_worker()
    existing = find_existing_pr(app, state, bot, state.commit_sha)
    if existing:
        return existing
    title = (f"FoxForge #{state.github_issue_number}: " if state.github_issue_number is not None else "FoxForge: ") + " ".join((state.github_issue_title or state.task).split())[:120]
    task = "\n".join("> " + line for line in state.task.splitlines())
    body = (f"{pr_marker(state)}\n\n{task}\n\n"
            f"Local status: {state.final_status}\nBranch: `{state.branch}`\nCommit: `{state.commit_sha}`\n"
            f"Tests: {state.tests_passed} passed, {state.tests_failed} failed\nReview: {state.review_result}\n"
            f"Repair cycles: {state.repair_cycles}/3\nTests added: {state.tests_added}\n"
            "\nTargets dev. Requires human review/playtest; no automatic merge or main integration.\n")
    if state.github_issue_number is not None:
        body += f"\nFoxForge-Issue: {state.github_repository}#{state.github_issue_number}\nRelated issue: {state.github_issue_url}\n"
    try:
        data = app.api("POST", f"/repos/{state.github_repository}/pulls",
                       {"title": title, "head": state.branch, "base": "dev", "body": body, "maintainer_can_modify": False})
    except GitHubAppError as exc:
        if exc.status == 422:
            raced = find_existing_pr(app, state, bot, state.commit_sha)
            if raced:
                return raced
        raise
    return _validate_pr(data, state, bot, sha=state.commit_sha)


def publish_run(repo: Path, state: RunState, state_path: Path, app: GitHubApp, *, guard: Callable[[], None] | None = None) -> None:
    """Persist each completed side effect so partial failures remain inspectable."""
    require_execution_worker()
    validate_state_for_publish(state)
    stage = "preflight"
    try:
        validate_task_branch(repo, state.branch)
        if not app.publishing or app.repository.casefold() != state.github_repository.casefold() or origin_repository(repo).casefold() != state.github_repository.casefold():
            raise PublishingError("Publishing client and origin do not match the expected repository")
        if resolve_ref(repo, "origin/dev") != state.base_ref or run_git(repo, "merge-base", "--is-ancestor", state.base_ref, state.validated_head_sha, check=False, safe=True).returncode != 0:
            raise PublishingError("Task is not based on the verified origin/dev integration reference")
        app.check_repository()
        bot = app.bot_identity()
        _assert_owned_history(repo, state, bot)
        stage = "branch ownership"
        try:
            remote = app.api("GET", f"/repos/{state.github_repository}/git/ref/heads/{quote(state.branch, safe='/')}")
            expected_remote = remote["object"]["sha"]
            if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", expected_remote):
                raise PublishingError("Invalid remote task branch metadata")
        except GitHubAppError as exc:
            if exc.status != 404:
                raise
            expected_remote = None
        if expected_remote and not find_existing_pr(app, state, bot, expected_remote):
            raise PublishingError("Existing remote task branch has no owned FoxForge PR")
        stage = "commit"
        if guard:
            guard()
        state.commit_sha = commit_validated_changes(repo, state, bot, state_path.parent)
        state.publishing_status = "COMMITTED"
        state.save(state_path)
        stage = "push"
        if guard:
            guard()
        push_task_branch(repo, state, state_path.parent, app.installation_token(), expected_remote)
        state.remote_branch = state.branch
        state.publishing_status = "PUSHED"
        state.save(state_path)
        stage = "pull request"
        if guard:
            guard()
        pr = ensure_pull_request(app, state, bot)
        state.pull_request_number, state.pull_request_url = pr["number"], pr["url"]
        state.publishing_status = "PUBLISHED"
        state.save(state_path)
    except (GitHubAppError, GitError, PublishingError, OSError, ValueError, TypeError, KeyError):
        # All upstream bodies/commands are deliberately excluded from durable errors.
        state.publishing_status = "FAILED"
        state.publishing_error = f"GitHub App publishing failed during {stage}; inspect safe run metadata and retry explicitly"
        state.save(state_path)
        raise PublishingError(state.publishing_error) from None
