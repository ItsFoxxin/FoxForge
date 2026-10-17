import json
import os
from pathlib import Path
import subprocess

import pytest

from foxforge import publishing
from foxforge.github_app import BotIdentity, GitHubAppError
from foxforge.git_manager import head_sha, run_git
from foxforge.publishing import PublishingError, worktree_fingerprint
from foxforge.state import RunState
from foxforge.state_validator import REQUIRED_AGENTS, expected_reporter_lines, validate_reporter_output


@pytest.fixture
def publish_context(git_repo, tmp_path):
    base = head_sha(git_repo)
    run_git(git_repo, "update-ref", "refs/remotes/origin/dev", base)
    run_git(git_repo, "remote", "add", "origin", "https://github.com/owner/project.git")
    (git_repo / "module.py").write_text("value = 2\n")
    state = RunState("run-1", "Improve calculation", "foxforge/test", base,
        agents_completed=REQUIRED_AGENTS[:-1].copy(), files_changed=["module.py"],
        tests_passed=5, test_exit_code=0, test_counts_verified=True, review_result="PASS", final_status="READY_FOR_PLAYTEST",
        publish_requested=True, github_repository="owner/project", validated_head_sha=base,
        validated_tree_hash=worktree_fingerprint(git_repo, base), publishing_status="PENDING")
    path = tmp_path / "run" / "state.json"
    state.save(path)
    return git_repo, state, path


class FakeApp:
    publishing = True
    repository = "owner/project"

    def __init__(self, state):
        self.state = state
        self.calls = []
        self.existing = False
        self.remote = None
        self.fail_pr = False

    def check_repository(self): return {"id": 42, "full_name": self.repository}
    def bot_identity(self): return BotIdentity("foxforge[bot]", 987)
    def installation_token(self): return "installation-secret-for-tests-only"

    def pr(self, *, sha=None, body=None):
        return {"number": 12, "html_url": "https://github.com/owner/project/pull/12", "state": "open", "merged_at": None,
            "base": {"ref": "dev", "repo": {"full_name": self.repository}},
            "head": {"ref": self.state.branch, "sha": sha or self.state.commit_sha, "repo": {"full_name": self.repository}},
            "user": {"id": 987, "login": "foxforge[bot]"}, "body": body or publishing.pr_marker(self.state)}

    def api(self, method, path, body=None):
        self.calls.append((method, path, body))
        if "/git/ref/heads/" in path:
            if self.remote is None:
                raise GitHubAppError("not found", 404)
            return {"object": {"sha": self.remote}}
        if method == "GET" and "/pulls?" in path:
            return [self.pr(sha=self.remote)] if self.existing else []
        if method == "POST" and path.endswith("/pulls"):
            if self.fail_pr:
                raise GitHubAppError("server echoed installation-secret-for-tests-only", 500)
            return self.pr(body=body["body"])
        raise AssertionError("Unexpected mock API request")


def test_successful_publish_commits_as_api_bot_and_records_pr(publish_context, monkeypatch):
    repo, state, path = publish_context
    app = FakeApp(state)
    pushes = []
    monkeypatch.setattr(publishing, "push_task_branch", lambda *args: pushes.append(args))
    publishing.publish_run(repo, state, path, app)
    loaded = RunState.load(path)
    assert loaded.publishing_status == "PUBLISHED" and loaded.pull_request_number == 12
    assert loaded.pull_request_url == "https://github.com/owner/project/pull/12"
    assert loaded.commit_sha == head_sha(repo) and loaded.remote_branch == "foxforge/test"
    assert run_git(repo, "show", "-s", "--format=%an|%ae|%cn|%ce", "HEAD").stdout.strip() == (
        "foxforge[bot]|987+foxforge[bot]@users.noreply.github.com|foxforge[bot]|987+foxforge[bot]@users.noreply.github.com")
    assert len(pushes) == 1
    request = next(body for method, url, body in app.calls if method == "POST")
    assert request["base"] == "dev" and request["head"] == "foxforge/test"
    assert "5 passed, 0 failed" in request["body"]
    assert "installation-secret" not in path.read_text()
    state.agents_completed.append("reporter")
    output = "\n".join(expected_reporter_lines(state))
    validate_reporter_output(state, output)
    with pytest.raises(RuntimeError):
        validate_reporter_output(state, output.replace("/pull/12", "/pull/13"))


@pytest.mark.parametrize("branch", ["main", "master", "dev", "feature/test", "foxforge/../dev", "foxforge/test:dev", "foxforge/"])
def test_branch_allowlist_rejects_unsafe_destinations(publish_context, branch):
    repo, state, _ = publish_context
    with pytest.raises(PublishingError):
        publishing.validate_task_branch(repo, branch)


def test_push_uses_ephemeral_credentials_and_exact_safe_ref(publish_context, monkeypatch):
    repo, state, path = publish_context
    state.commit_sha = state.validated_head_sha
    calls = []
    real_git = publishing.run_git
    token = "installation-secret-for-tests-only"
    def git(repo, *args, **kwargs):
        if "push" in args:
            calls.append((args, dict(kwargs["env"])))
            helper = Path(kwargs["env"]["GIT_ASKPASS"])
            assert helper.exists()
            for file in helper.parent.iterdir():
                if file.is_file(): assert token not in file.read_text(encoding="utf-8")
            assert token not in repr(args)
            return subprocess.CompletedProcess(args, 0, "", "")
        return real_git(repo, *args, **kwargs)
    monkeypatch.setattr(publishing, "run_git", git)
    publishing.push_task_branch(repo, state, path.parent, token, None)
    args, env = calls[0]
    assert args[-1] == state.commit_sha + ":refs/heads/foxforge/test"
    assert "--force-with-lease=refs/heads/foxforge/test:" in args
    assert "credential.helper=" in args and "http.followRedirects=false" in args
    assert env["_FOXFORGE_INSTALLATION_TOKEN"] == token
    assert not Path(env["GIT_ASKPASS"]).exists()
    assert not list(path.parent.glob("git-auth-*"))
    assert token not in run_git(repo, "config", "--local", "--list").stdout


def test_askpass_works_with_real_git_credential_fill_without_network(publish_context):
    repo, state, path = publish_context
    token = "installation-secret-for-tests-only"
    with publishing.git_credentials(path.parent, state.github_repository, token) as (env, options):
        result = subprocess.run(["git", *options, "credential", "fill"], cwd=repo,
            input="protocol=https\nhost=github.com\npath=owner/project.git\n\n", text=True,
            capture_output=True, env=env, timeout=20)
        assert result.returncode == 0, result.stderr
        assert "username=x-access-token" in result.stdout
        assert "password=" + token in result.stdout
    assert not list(path.parent.glob("git-auth-*"))


def test_helper_refuses_another_host(publish_context):
    _, state, path = publish_context
    with publishing.git_credentials(path.parent, state.github_repository, "installation-secret-for-tests-only") as (env, _):
        result = subprocess.run([env["_FOXFORGE_ASKPASS_PYTHON"], env["_FOXFORGE_ASKPASS_SCRIPT"], "Password for 'https://other.invalid/owner/project.git': "], env=env, capture_output=True, timeout=10)
        assert result.returncode == 1 and result.stdout == b""


def test_push_failure_preserves_commit_but_not_remote_success(publish_context, monkeypatch):
    repo, state, path = publish_context
    def fail(*args): raise PublishingError("installation-secret-for-tests-only")
    monkeypatch.setattr(publishing, "push_task_branch", fail)
    with pytest.raises(PublishingError) as caught:
        publishing.publish_run(repo, state, path, FakeApp(state))
    assert "installation-secret" not in str(caught.value)
    loaded = RunState.load(path)
    assert loaded.final_status == "READY_FOR_PLAYTEST" and loaded.publishing_status == "FAILED"
    assert loaded.commit_sha and loaded.remote_branch is None and loaded.pull_request_url is None
    assert "during push" in loaded.publishing_error


def test_pr_failure_preserves_verified_push(publish_context, monkeypatch):
    repo, state, path = publish_context
    app = FakeApp(state)
    app.fail_pr = True
    monkeypatch.setattr(publishing, "push_task_branch", lambda *args: None)
    with pytest.raises(PublishingError):
        publishing.publish_run(repo, state, path, app)
    loaded = RunState.load(path)
    assert loaded.remote_branch == state.branch and loaded.pull_request_url is None
    assert loaded.publishing_status == "FAILED" and "during pull request" in loaded.publishing_error
    assert "installation-secret" not in path.read_text()


def test_existing_owned_pr_is_reused_without_creation(publish_context, monkeypatch):
    repo, state, path = publish_context
    app = FakeApp(state)
    app.existing = True
    app.remote = state.validated_head_sha
    def push(*args):
        app.remote = state.commit_sha
    monkeypatch.setattr(publishing, "push_task_branch", push)
    publishing.publish_run(repo, state, path, app)
    assert state.pull_request_number == 12
    assert not any(method == "POST" for method, _, _ in app.calls)


@pytest.mark.parametrize("violation", ["target-main", "foreign-author", "foreign-repo"])
def test_existing_foreign_pr_is_rejected_before_commit(publish_context, violation):
    repo, state, path = publish_context
    app = FakeApp(state)
    app.remote = state.validated_head_sha
    original = app.api
    def api(method, url, body=None):
        if "/pulls?" in url:
            value = app.pr(sha=app.remote)
            if violation == "target-main": value["base"]["ref"] = "main"
            if violation == "foreign-author": value["user"]["id"] = 999
            if violation == "foreign-repo": value["head"]["repo"]["full_name"] = "other/project"
            return [value]
        return original(method, url, body)
    app.api = api
    with pytest.raises(PublishingError):
        publishing.publish_run(repo, state, path, app)
    assert head_sha(repo) == state.validated_head_sha and state.commit_sha is None


def test_content_mutation_after_tests_prevents_commit(publish_context):
    repo, state, path = publish_context
    (repo / "module.py").write_text("unvalidated mutation\n")
    with pytest.raises(PublishingError):
        publishing.publish_run(repo, state, path, FakeApp(state))
    assert head_sha(repo) == state.validated_head_sha


def test_validated_deletion_can_be_committed(publish_context):
    repo, state, path = publish_context
    (repo / "module.py").unlink()
    state.validated_tree_hash = worktree_fingerprint(repo, state.validated_head_sha)
    sha = publishing.commit_validated_changes(repo, state, BotIdentity("foxforge[bot]", 987), path.parent)
    assert sha == head_sha(repo) and "module.py" not in run_git(repo, "ls-files").stdout


def test_pr_creation_race_reuses_only_verified_owned_pr(publish_context):
    _, state, _ = publish_context
    state.commit_sha = "a" * 40
    app = FakeApp(state)
    original = app.api
    def api(method, url, body=None):
        if method == "POST":
            app.existing = True
            raise GitHubAppError("already exists", 422)
        return original(method, url, body)
    app.api = api
    assert publishing.ensure_pull_request(app, state, app.bot_identity())["number"] == 12


def test_unknown_remote_branch_is_not_overwritten(publish_context):
    repo, state, path = publish_context
    app = FakeApp(state)
    app.remote = state.validated_head_sha
    with pytest.raises(PublishingError):
        publishing.publish_run(repo, state, path, app)
    assert head_sha(repo) == state.validated_head_sha and state.commit_sha is None


def test_unsafe_git_url_rewrite_prevents_push(publish_context, monkeypatch):
    repo, state, path = publish_context
    state.commit_sha = state.validated_head_sha
    run_git(repo, "config", "url.https://other.invalid/.insteadOf", "https://github.com/")
    with pytest.raises(PublishingError):
        publishing.push_task_branch(repo, state, path.parent, "installation-secret-for-tests-only", None)
    assert not list(path.parent.glob("git-auth-*"))


def test_unowned_local_history_cannot_be_published(publish_context):
    repo, state, path = publish_context
    run_git(repo, "add", "module.py")
    run_git(repo, "-c", "user.name=Unowned", "-c", "user.email=unowned@example.invalid", "commit", "-m", "unowned commit")
    (repo / "module.py").write_text("value = 3\n")
    state.validated_head_sha = head_sha(repo)
    state.validated_tree_hash = worktree_fingerprint(repo, state.validated_head_sha)
    with pytest.raises(PublishingError):
        publishing.publish_run(repo, state, path, FakeApp(state))
    assert state.commit_sha is None and state.publishing_status == "FAILED"
