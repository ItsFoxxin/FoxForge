import json
import os
from pathlib import Path
import sqlite3

import pytest

from foxforge import doctor
from foxforge.configuration import ConfigurationError, ModelPolicy, PlannerConfig, secret
from foxforge.container_cli import run
from foxforge.control_plane import ControlPlane, ControlPlaneError, data_root
from foxforge.storage_ops import backup, inspect_database, verify_directory


def store(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    cp = ControlPlane(root / "foxforge.db")
    return cp, root


@pytest.mark.parametrize("raw", [None, "", "relative", "/missing-foxforge-test-directory"])
def test_no_implicit_state_creation(tmp_path, monkeypatch, raw):
    if raw is None:
        monkeypatch.delenv("FOXFORGE_DATA_DIR", raising=False)
    else:
        monkeypatch.setenv("FOXFORGE_DATA_DIR", raw)
    with pytest.raises(ConfigurationError):
        data_root()


def test_missing_database_requires_explicit_initialization(tmp_path, monkeypatch):
    monkeypatch.setenv("FOXFORGE_DATA_DIR", str(tmp_path))
    with pytest.raises(ControlPlaneError, match="storage init"):
        ControlPlane()
    assert not (tmp_path / "foxforge.db").exists()


def test_empty_database_is_not_silently_initialized(tmp_path, monkeypatch):
    path = tmp_path / "foxforge.db"
    path.touch()
    monkeypatch.setenv("FOXFORGE_DATA_DIR", str(tmp_path))
    with pytest.raises(ControlPlaneError, match="Empty database"):
        ControlPlane()
    assert path.stat().st_size == 0


def test_unknown_schema_is_not_modified(tmp_path):
    path = tmp_path / "foxforge.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE schema_info(version INTEGER)")
        db.execute("INSERT INTO schema_info VALUES(99)")
    before = path.read_bytes()
    with pytest.raises(ControlPlaneError):
        ControlPlane(path)
    assert path.read_bytes() == before


def test_backup_refuses_overwrite_and_detects_artifact_loss(tmp_path):
    cp, root = store(tmp_path)
    project = cp.register_project(repository_id=1, repository="owner/repo", local_path=tmp_path, default_branch="dev")
    task, _ = cp.authorize_and_create_task(project, {"number": 1, "revision": "a" * 64}, actor_id=1, event_id=1)
    cp.update_task(task["id"], state="active", activity="planning")
    artifacts = cp.artifacts(task["id"])
    (artifacts / "plan.md").write_text("Review me", encoding="utf-8")
    cp.update_task(task["id"], state="awaiting_human_review", activity="idle", artifact_dir=artifacts)
    destination = tmp_path / "backup"
    backup(root, destination)
    assert verify_directory(destination)["counts"]["tasks"] == 1
    with pytest.raises(ControlPlaneError):
        backup(root, destination)
    (destination / "artifacts" / task["id"] / "plan.md").write_text("altered", encoding="utf-8")
    with pytest.raises(ControlPlaneError, match="manifest"):
        verify_directory(destination)
    assert cp.task(task["id"])["state"] == "awaiting_human_review"


def test_doctor_does_not_create_database_or_leak_secrets(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FOXFORGE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FOXFORGE_PLANNER_API_KEY", "never-print-this-key")
    assert doctor.main([]) == 1
    output = capsys.readouterr().out
    assert "never-print" not in output
    assert not (tmp_path / "foxforge.db").exists()
    assert json.loads(output)["inference_requests"] == 0


def test_secret_files_and_ambiguous_configuration(tmp_path, monkeypatch):
    path = tmp_path / "key"
    path.write_text("file-secret-only", encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setenv("FOXFORGE_PLANNER_API_KEY_FILE", str(path))
    assert secret("FOXFORGE_PLANNER_API_KEY") == "file-secret-only"
    monkeypatch.setenv("FOXFORGE_PLANNER_API_KEY", "another-key")
    with pytest.raises(ConfigurationError):
        secret("FOXFORGE_PLANNER_API_KEY")


@pytest.mark.skipif(os.name == "nt", reason="POSIX credential permission bits")
def test_world_readable_secret_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "key"
    path.write_text("secret-value", encoding="utf-8")
    path.chmod(0o644)
    monkeypatch.setenv("FOXFORGE_PLANNER_API_KEY_FILE", str(path))
    with pytest.raises(ConfigurationError):
        secret("FOXFORGE_PLANNER_API_KEY")


@pytest.mark.parametrize("args", [["--repo", "/tmp"], ["issue", "1"], ["watch"], ["shell"], ["deploy"]])
def test_container_entrypoint_cannot_dispatch_execution(args):
    assert run(args) == 2


def test_model_policy_rejects_budget_expansion_and_unknown_task(tmp_path, monkeypatch):
    path = tmp_path / "policy.json"
    value = {"schema_version": 1, "tasks": {"development.plan": {
        "models": ["tested-model"], "providers": ["test-provider"], "max_requests": 1, "max_retries": 0,
        "max_output_tokens": 8000, "max_input_bytes": 300000, "max_reserved_tokens": 310000, "timeout_seconds": 120}}}
    path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setenv("FOXFORGE_MODEL_POLICY_FILE", str(path))
    assert ModelPolicy.from_env().max_requests == 1
    with pytest.raises(ConfigurationError):
        ModelPolicy.from_env("infrastructure.execute")
    value["tasks"]["development.plan"]["max_requests"] = 999
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ConfigurationError):
        ModelPolicy.from_env()


def test_request_budget_is_atomic_and_survives_restart(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    cp, root = store(tmp_path)
    project = cp.register_project(repository_id=1, repository="owner/repo", local_path=tmp_path, default_branch="dev")
    task, _ = cp.authorize_and_create_task(project, {"number": 1, "revision": "a" * 64}, actor_id=1, event_id=1)
    cp.update_task(task["id"], state="active", activity="planning")
    policy = ModelPolicy("development.plan", ("test-model",), ("test-provider",))
    def reserve():
        try:
            return cp.reserve_model_request(task["id"], policy, 100)
        except ControlPlaneError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(), range(2)))
    assert len([value for value in results if value is not None]) == 1
    reopened = ControlPlane(root / "foxforge.db")
    with pytest.raises(ControlPlaneError):
        reopened.reserve_model_request(task["id"], policy, 100)
    with pytest.raises(ControlPlaneError, match="policy"):
        reopened.reserve_model_request(task["id"], replace(policy, max_requests=2), 100)
    cp.update_task(task["id"], state="blocked", activity="idle", error_code="TIMEOUT")
    with pytest.raises(ControlPlaneError):
        cp.update_task(task["id"], state="active", activity="planning")


def test_additive_ledger_preserves_030_records(tmp_path):
    cp, root = store(tmp_path)
    project = cp.register_project(repository_id=1, repository="owner/repo", local_path=tmp_path, default_branch="dev")
    task, _ = cp.authorize_and_create_task(project, {"number": 1, "revision": "a" * 64}, actor_id=1, event_id=1)
    with cp.connect() as db:
        db.execute("DROP TABLE model_requests")  # Reproduce an actual 0.3.0 schema.
    before = inspect_database(root / "foxforge.db")
    reopened = ControlPlane(root / "foxforge.db")
    after = inspect_database(root / "foxforge.db")
    assert reopened.task(task["id"])["revision"] == "a" * 64
    assert {key: value for key, value in after["counts"].items() if key != "model_requests"} == before["counts"]
    assert after["schema_version"] == 1


def test_doctor_flags_conflicting_state_without_merging(tmp_path, monkeypatch, capsys):
    cp, root = store(tmp_path)
    other = tmp_path / "old"
    other.mkdir()
    ControlPlane(other / "foxforge.db")
    monkeypatch.setenv("FOXFORGE_DATA_DIR", str(root))
    monkeypatch.setattr(doctor, "legacy_locations", lambda: [other, root])
    assert doctor.main([]) == 1
    report = json.loads(capsys.readouterr().out)
    assert next(row for row in report["checks"] if row["check"] == "conflicting_state")["ok"] is False
    assert (other / "foxforge.db").exists()


def test_corrupt_database_is_detected_without_overwrite(tmp_path):
    path = tmp_path / "foxforge.db"
    path.write_bytes(b"This is not SQLite")
    with pytest.raises(sqlite3.Error):
        inspect_database(path)
    assert path.read_bytes() == b"This is not SQLite"
