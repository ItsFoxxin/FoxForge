import os
from pathlib import Path
import subprocess
import sys

import pytest

from foxforge import intake_storage
from foxforge.intake_storage import atomic_json, issue_key, local_lock
from foxforge.issue_tasks import IssueError, IssueTask
from foxforge.security import register_secret


@pytest.mark.parametrize("title,expected", [
    ("Static Coil", "foxforge/47-static-coil"),
    ("../../MAIN; $(unsafe) & | < >", "foxforge/47-main-unsafe"),
    ("🦊 한글", "foxforge/47-task"),
    ("-x\n\tcommit ..", "foxforge/47-x-commit"),
])
def test_branch_names_are_deterministic_and_safe(title, expected):
    task = IssueTask("owner/repo", 47, title, "", "https://github.com/owner/repo/issues/47", "open", (), "2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z")
    assert task.branch() == task.branch() == expected
    assert task.branch(2) == expected + "-retry-2"


def test_process_lock_is_exclusive_and_released_after_exit(tmp_path, monkeypatch):
    root = tmp_path / "shared"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(intake_storage, "intake_root", lambda: root)
    code = """
import sys
from pathlib import Path
from foxforge import intake_storage
from foxforge.issue_tasks import IssueError
intake_storage.intake_root = lambda: Path(sys.argv[2])
try:
    with intake_storage.local_lock(Path(sys.argv[1]), 'same-issue'):
        print('ACQUIRED')
except IssueError:
    print('LOCKED')
"""
    command = [sys.executable, "-c", code, str(repo), str(root)]
    with local_lock(repo, "same-issue"):
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0 and result.stdout.strip() == "LOCKED"
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0 and result.stdout.strip() == "ACQUIRED"


def test_issue_key_is_repository_scoped_case_insensitive():
    assert issue_key("Owner/Repo", 47) == issue_key("owner/repo", 47)
    assert issue_key("owner/repo", 47) != issue_key("other/repo", 47)
    assert issue_key("owner/repo", 47) != issue_key("owner/repo", 48)


def test_storage_refuses_secrets_and_target_internal_root(tmp_path, monkeypatch):
    secret = "synthetic-private-value-12345"
    register_secret(secret)
    with pytest.raises(IssueError):
        atomic_json(tmp_path / "record.json", {"value": secret})
    monkeypatch.setattr(intake_storage, "intake_root", lambda: tmp_path / "inside")
    with pytest.raises(IssueError, match="outside"):
        with local_lock(tmp_path, "unsafe"):
            pytest.fail("Internal storage was accepted")
