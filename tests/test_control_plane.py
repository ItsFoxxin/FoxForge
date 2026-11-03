import json

import pytest

from foxforge.control_plane import ControlPlane, ControlPlaneError


def project(store, tmp_path):
    return store.register_project(repository_id=17, repository="owner/project", local_path=tmp_path / "repo", default_branch="dev")


def snapshot():
    return {"number": 4, "revision": "a" * 64, "title": "Plan it"}


def test_authorization_consumption_is_idempotent(tmp_path):
    store = ControlPlane(tmp_path / "control.db")
    registered = project(store, tmp_path)
    store.record_discovery(registered, snapshot())
    first, created = store.authorize_and_create_task(registered, snapshot(), actor_id=5, event_id=91)
    second, created_again = store.authorize_and_create_task(registered, snapshot(), actor_id=5, event_id=91)
    assert created and not created_again and first["id"] == second["id"]


def test_authorization_evidence_cannot_be_rebound(tmp_path):
    store = ControlPlane(tmp_path / "control.db")
    registered = project(store, tmp_path)
    store.authorize_and_create_task(registered, snapshot(), actor_id=5, event_id=91)
    changed = {**snapshot(), "revision": "b" * 64}
    with pytest.raises(ControlPlaneError):
        store.authorize_and_create_task(registered, changed, actor_id=5, event_id=91)


def test_task_state_and_audit_survive_reopen(tmp_path):
    path = tmp_path / "control.db"
    store = ControlPlane(path)
    registered = project(store, tmp_path)
    task, _ = store.authorize_and_create_task(registered, snapshot(), actor_id=5, event_id=91)
    store.update_task(task["id"], state="active", activity="planning", base_sha="1" * 40,
                      discovery={"commit": "1" * 40})
    reopened = ControlPlane(path).task(task["id"])
    assert reopened["state"] == "active" and reopened["discovery"]["commit"] == "1" * 40


def test_secret_like_material_is_not_persisted(tmp_path):
    store = ControlPlane(tmp_path / "control.db")
    registered = project(store, tmp_path)
    with pytest.raises(ControlPlaneError):
        store.record_discovery(registered, {"number": 4, "revision": "a" * 64, "value": "ghp_abcdefghijklmnopqrstuvwxyz"})
