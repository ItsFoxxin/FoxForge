import shutil
import subprocess
import os

import pytest

from foxforge.git_manager import run_git


@pytest.fixture(autouse=True)
def isolate_credentials_and_network(monkeypatch):
    from foxforge import security
    import urllib.request
    security._secrets.clear()
    for key in list(os.environ):
        if key.upper().startswith(("FOXFORGE_GITHUB_", "FOXFORGE_PLANNER_", "_FOXFORGE_")) or key.upper() in {"FOXFORGE_ALLOWED_GITHUB_USER_IDS", "GITHUB_TOKEN", "GH_TOKEN", "DISCORD_WEBHOOK_URL"}:
            monkeypatch.delenv(key)
    def reject_http(*args, **kwargs):
        raise AssertionError("Real HTTP is forbidden in FoxForge unit tests")
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", reject_http)
    monkeypatch.setattr(urllib.request, "urlopen", reject_http)
    real_run = subprocess.run
    def offline_run(command, *args, **kwargs):
        if isinstance(command, list) and Path(str(command[0])).name.lower() in {"git", "git.exe"} and any(arg in {"push", "fetch", "ls-remote"} for arg in command[1:]):
            raise AssertionError("Git network operations must be mocked in FoxForge tests")
        return real_run(command, *args, **kwargs)
    from pathlib import Path
    monkeypatch.setattr(subprocess, "run", offline_run)
    real_popen = subprocess.Popen
    def offline_popen(command, *args, **kwargs):
        if isinstance(command, list) and Path(str(command[0])).name.lower() in {"git", "git.exe"} and any(arg in {"push", "fetch", "ls-remote"} for arg in command[1:]):
            raise AssertionError("Git network operations must be mocked in FoxForge tests")
        return real_popen(command, *args, **kwargs)
    monkeypatch.setattr(subprocess, "Popen", offline_popen)
    yield
    security._secrets.clear()


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
