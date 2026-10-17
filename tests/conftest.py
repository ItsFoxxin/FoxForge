import shutil
import subprocess

import pytest

from foxforge.git_manager import run_git


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    """A disposable local repo; no persisted user Git configuration or network."""
    git = shutil.which("git")
    if not git:
        pytest.skip("Git is required for integration tests")
    monkeypatch.setenv("FOXFORGE_GIT_EXE", git)
    repo = tmp_path / "target"
    repo.mkdir()
    subprocess.run([git, "init", "-b", "foxforge/test", str(repo)], check=True, capture_output=True)
    (repo / "module.py").write_text("value = 1\n", encoding="utf-8")
    run_git(repo, "add", "module.py")
    run_git(repo, "-c", "user.name=FoxForge Test", "-c", "user.email=tests@example.invalid", "commit", "-m", "fixture")
    return repo
