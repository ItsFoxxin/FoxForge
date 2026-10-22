import json
from pathlib import Path

from foxforge import control_plane, foundation_cli
from foxforge.control_plane import ControlPlane
from foxforge.git_manager import head_sha, run_git
from foxforge.issue_tasks import IssueTask


PLAN = {"schema_version": 1, "summary": "Inspect, implement, and validate.",
        "acceptance_criteria": ["Feature works."], "assumptions": [], "unknowns": [],
        "subtasks": [{"id": "implementation", "title": "Implement", "description": "Make the bounded change.",
                      "capability": "development.general", "depends_on": [],
                      "acceptance_criteria": ["Feature works."], "owned_paths": ["module.py"],
                      "validation": ["Run the repository tests."]}]}


class FakeAPI:
    def __init__(self, item): self.item = item
    def list_open(self): return [self.item]
    def get(self, number): assert number == self.item.number; return self.item
    def approval_for_label(self, number, label, policy, **kwargs):
        assert label == "foxforge:plan" and policy.allows(5)
        assert kwargs["not_before"] == self.item.updated_at and kwargs["max_age_hours"] == 168
        return 91, "owner", 5


def issue(labels=("foxforge:plan",)):
    return IssueTask("owner/project", 47, "Plan feature", "Do the thing.",
                     "https://github.com/owner/project/issues/47", "open", labels,
                     "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z", 999)


def setup_store(git_repo, tmp_path, monkeypatch):
    run_git(git_repo, "remote", "add", "origin", "https://github.com/owner/project.git")
    run_git(git_repo, "update-ref", "refs/remotes/origin/dev", head_sha(git_repo))
    root = tmp_path / "data"
    monkeypatch.setattr(control_plane, "data_root", lambda: root)
    store = ControlPlane(root / "foxforge.db")
    store.register_project(repository_id=17, repository="owner/project", local_path=git_repo, default_branch="dev")
    return store, root


def test_discovery_never_calls_planner(git_repo, tmp_path, monkeypatch, capsys):
    store, _ = setup_store(git_repo, tmp_path, monkeypatch)
    monkeypatch.setattr(foundation_cli, "ControlPlane", lambda: store)
    monkeypatch.setattr(foundation_cli, "client", lambda repository: FakeAPI(issue(labels=())))
    monkeypatch.setattr(foundation_cli, "request_plan", lambda **kwargs: (_ for _ in ()).throw(AssertionError("model called")))
    assert foundation_cli.main(["issues", "discover", "--project", "owner/project"]) == 0
    assert json.loads(capsys.readouterr().out)["model_requests"] == 0


def test_authorized_offline_plan_reaches_human_review(git_repo, tmp_path, monkeypatch, capsys):
    store, root = setup_store(git_repo, tmp_path, monkeypatch)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(PLAN), encoding="utf-8")
    monkeypatch.setenv("FOXFORGE_ALLOWED_GITHUB_USER_IDS", "5")
    monkeypatch.setattr(foundation_cli, "ControlPlane", lambda: store)
    monkeypatch.setattr(foundation_cli, "client", lambda repository: FakeAPI(issue()))
    assert foundation_cli.main(["tasks", "plan", "--project", "owner/project", "--issue", "47", "--plan-file", str(plan_file)]) == 0
    result = json.loads(capsys.readouterr().out)
    task = store.task(result["task_id"])
    assert task["state"] == "awaiting_human_review" and task["base_sha"] == head_sha(git_repo)
    artifact = Path(task["artifact_dir"])
    assert (artifact / "plan.json").is_file() and "authorizes no implementation" in (artifact / "plan.md").read_text(encoding="utf-8")
    assert foundation_cli.main(["tasks", "plan", "--project", "owner/project", "--issue", "47", "--plan-file", str(plan_file)]) == 0
    duplicate = json.loads(capsys.readouterr().out)
    assert duplicate["duplicate"] is True and duplicate["task_id"] == task["id"]


def test_unapproved_issue_causes_no_planner_call(git_repo, tmp_path, monkeypatch):
    store, _ = setup_store(git_repo, tmp_path, monkeypatch)
    api = FakeAPI(issue())
    api.approval_for_label = lambda *args: None
    monkeypatch.setattr(foundation_cli, "ControlPlane", lambda: store)
    monkeypatch.setattr(foundation_cli, "client", lambda repository: api)
    monkeypatch.setattr(foundation_cli, "request_plan", lambda **kwargs: (_ for _ in ()).throw(AssertionError("model called")))
    assert foundation_cli.main(["tasks", "plan", "--project", "owner/project", "--issue", "47"]) == 1


def test_removed_planning_label_causes_no_authorization_or_model_call(git_repo, tmp_path, monkeypatch):
    store, _ = setup_store(git_repo, tmp_path, monkeypatch)
    api = FakeAPI(issue(labels=()))
    monkeypatch.setattr(foundation_cli, "ControlPlane", lambda: store)
    monkeypatch.setattr(foundation_cli, "client", lambda repository: api)
    monkeypatch.setattr(foundation_cli, "request_plan", lambda **kwargs: (_ for _ in ()).throw(AssertionError("model called")))
    assert foundation_cli.main(["tasks", "plan", "--project", "owner/project", "--issue", "47"]) == 1
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM authorizations").fetchone()[0] == 0


def test_issue_change_during_authorization_requires_fresh_approval(git_repo, tmp_path, monkeypatch):
    store, _ = setup_store(git_repo, tmp_path, monkeypatch)
    original = issue()
    edited = IssueTask(original.repository, original.number, original.title, "Edited after approval.",
                       original.url, original.state, original.labels, original.created_at,
                       "2026-10-03T00:00:00Z", original.author_id)

    class ChangingAPI(FakeAPI):
        def __init__(self):
            super().__init__(original)
            self.reads = 0
        def get(self, number):
            self.reads += 1
            return original if self.reads == 1 else edited

    monkeypatch.setenv("FOXFORGE_ALLOWED_GITHUB_USER_IDS", "5")
    monkeypatch.setattr(foundation_cli, "ControlPlane", lambda: store)
    monkeypatch.setattr(foundation_cli, "client", lambda repository: ChangingAPI())
    monkeypatch.setattr(foundation_cli, "request_plan", lambda **kwargs: (_ for _ in ()).throw(AssertionError("model called")))
    assert foundation_cli.main(["tasks", "plan", "--project", "owner/project", "--issue", "47"]) == 1
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM authorizations").fetchone()[0] == 0


def test_capability_listing_has_no_control_plane_side_effect(monkeypatch, capsys):
    monkeypatch.setattr(foundation_cli, "ControlPlane", lambda: (_ for _ in ()).throw(AssertionError("database opened")))
    assert foundation_cli.main(["capabilities", "list"]) == 0
    assert json.loads(capsys.readouterr().out)
