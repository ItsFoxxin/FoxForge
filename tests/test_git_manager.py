from foxforge.git_manager import slugify_task
import os

import pytest

from foxforge import git_manager
from foxforge.test_runner import count_added_tests


def test_slugify_task() -> None:
    assert (
        slugify_task("Add Blood Capacitor Item!")
        == "add-blood-capacitor-item"
    )


def test_slugify_task_has_fallback() -> None:
    assert slugify_task("!!!") == "task"


def test_slugify_task_truncates() -> None:
    slug = slugify_task("A" * 200)
    assert len(slug) <= 48


def test_changed_files_and_diff_include_untracked_unicode(git_repo):
    (git_repo / "module.py").write_text("value = 2\n")
    new_file = "test_구미호.py"
    (git_repo / new_file).write_text("def test_new():\n    assert True\n", encoding="utf-8")
    assert git_manager.changed_files(git_repo, "HEAD") == ["module.py", new_file]
    text = git_manager.diff(git_repo, "HEAD")
    assert "+value = 2" in text and "+def test_new" in text
    assert count_added_tests(text) == 1


@pytest.mark.skipif(os.name == "nt", reason="Windows forbids newlines in filenames")
def test_changed_files_preserves_whitespace_names(git_repo):
    name = " test\nodd.py "
    (git_repo / name).write_text("x")
    assert git_manager.changed_files(git_repo, "HEAD") == [name]


def test_ensure_repo_rejects_nested_directory(git_repo):
    nested = git_repo / "nested"
    nested.mkdir()
    with pytest.raises(git_manager.GitError, match="root"):
        git_manager.ensure_repo(nested)


@pytest.mark.parametrize("branch,base", [("main", "dev"), ("foxforge/x", "main"), ("foxforge/../bad", "dev")])
def test_unsafe_branch_request_never_fetches(git_repo, monkeypatch, branch, base):
    monkeypatch.setattr(git_manager, "fetch", lambda *a: pytest.fail("Unexpected fetch"))
    with pytest.raises(git_manager.GitError):
        git_manager.create_task_branch(git_repo, branch, base)


def test_dirty_worktree_never_fetches(git_repo, monkeypatch):
    (git_repo / "dirty.txt").write_text("untracked")
    monkeypatch.setattr(git_manager, "fetch", lambda *a: pytest.fail("Unexpected fetch"))
    with pytest.raises(git_manager.GitError, match="not clean"):
        git_manager.create_task_branch(git_repo, "foxforge/new")


def test_task_branch_starts_at_origin_dev(git_repo, monkeypatch):
    original = git_manager.head_sha(git_repo)
    git_manager.run_git(git_repo, "update-ref", "refs/remotes/origin/dev", original)
    fetched = []
    monkeypatch.setattr(git_manager, "fetch", lambda repo: fetched.append(repo))
    git_manager.create_task_branch(git_repo, "foxforge/new")
    assert fetched == [git_repo]
    assert git_manager.current_branch(git_repo) == "foxforge/new"
    assert git_manager.head_sha(git_repo) == original
