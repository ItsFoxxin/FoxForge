from foxforge.git_manager import head_sha, run_git
from foxforge.repository_discovery import discover_repository


def test_discovery_reads_pinned_commit_without_executing_repository_code(git_repo):
    marker = git_repo.parent / "repository-code-executed"
    (git_repo / "README.md").write_text("committed instructions\n", encoding="utf-8")
    (git_repo / "setup.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('unsafe')\n",
        encoding="utf-8",
    )
    run_git(git_repo, "add", "README.md", "setup.py")
    run_git(git_repo, "-c", "user.name=FoxForge Test", "-c", "user.email=tests@example.invalid",
            "commit", "-m", "discovery fixture")
    commit = head_sha(git_repo)

    (git_repo / "README.md").write_text("uncommitted replacement\n", encoding="utf-8")
    result = discover_repository(git_repo, commit)

    assert result["commit"] == commit
    assert result["context_files"]["README.md"] == "committed instructions\n"
    assert not marker.exists()
