import copy
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from foxforge import worker_protocol as p
from foxforge.control_plane import ControlPlane
from foxforge.storage_ops import backup, verify_directory
from foxforge.worker_controller import WorkerController
from foxforge.worker_demo import exercise
from foxforge.worker_docker import DockerSandbox, environment
from foxforge.worker_fixture import PROFILE_DIGEST, repository
from foxforge.worker_runtime import WorkerRuntime


@pytest.fixture
def context(tmp_path):
    controller_key, worker_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    clock = [2000000000]
    cp = ControlPlane(tmp_path / "foxforge.db")
    c = WorkerController(cp, controller_key, trusted_actor_ids={17}, clock=lambda: clock[0])
    identity = {"worker_id": "test_worker", "public_key": p.public_key(worker_key), "capabilities": ["quality.assurance"], "concurrency": 1}
    c.register(p.sign(identity, "test_worker", worker_key), trusted_public_key=p.public_key(worker_key))
    raw = c.issue_fixture("test_worker", actor_id=17)
    assignment = p.verify(raw, "controller", p.public_key(controller_key))
    return c, controller_key, worker_key, clock, assignment, raw


def event(context, kind="accepted", *, sequence=1, data=None, usage=None):
    c, ck, wk, clock, a, raw = context
    value = {"kind": kind, "assignment_id": a["assignment_id"], "attempt_id": a["attempt_id"], "worker_id": a["worker_id"],
             "assignment_digest": p.digest(a), "sequence": sequence, "usage": usage or {"requests": 0, "tokens": 0},
             "data": data or {"checkpoint": "accepted"}}
    return p.sign(value, a["worker_id"], wk)


class SuccessSandbox:
    calls = 0
    def run(self, assignment, *, cancelled):
        self.calls += 1
        return {"status": "succeeded", "reason": "validated", "evidence": [
            {"operation": "validation.execute", "target": "calculator-tests", "parameters_digest": "a"*64, "outcome": "succeeded"}],
            "artifacts": {"validation.txt": b"Ran 2 tests\nOK\n"}}


def test_real_signatures_reject_forgery_and_envelope_changes(context):
    c, ck, wk, clock, a, raw = context
    outer = p.decode(raw)
    outer["payload"]["budgets"]["tokens"] += 1
    with pytest.raises(p.ProtocolError, match="Unauthenticated"):
        p.verify(p.canonical(outer), "controller", p.public_key(ck))
    with pytest.raises(p.ProtocolError):
        c.ingest(p.sign(p.decode(event(context))["payload"], "test_worker", Ed25519PrivateKey.generate()))
    assert c.attempt(a["attempt_id"])["state"] == "issued"


@pytest.mark.parametrize("mutate", [
    lambda a: a.update(extra="injected"), lambda a: a.update(task_id="task_live_issue"),
    lambda a: a.update(capability="infrastructure.admin"), lambda a: a.update(kind={}),
    lambda a: a.update(policy_version=True), lambda a: a.update(operations=["shell.execute"]),
    lambda a: a.update(read_paths=["../secret"]), lambda a: a.update(write_paths=["/etc/passwd"]),
    lambda a: a["repository"].update(id=True), lambda a: a["repository"].update(base_sha="dev"),
    lambda a: a["approval"].update(action="plan"), lambda a: a["approval"].update(repository_id=2),
    lambda a: a["budgets"].update(tokens=4097), lambda a: a.update(expires_at=a["issued_at"]+301),
    lambda a: a["parameters"].update(command="rm"), lambda a: a.update(operations=["workspace.write"]),
])
def test_assignment_cannot_expand_scope_or_budget(context, mutate):
    a = copy.deepcopy(context[4])
    mutate(a)
    with pytest.raises(p.ProtocolError):
        p.validate_assignment(a)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b"[", b'"'+b"x"*65536+b'"', b"\xff", b"["*2000], ids=["duplicate", "nan", "truncated", "oversized", "encoding", "depth"])
def test_bad_or_oversized_wire_json(raw):
    with pytest.raises(p.ProtocolError):
        p.decode(raw)


def test_identity_registration_is_not_self_authorization(context):
    c, ck, wk, clock, a, raw = context
    key = Ed25519PrivateKey.generate()
    identity = {"worker_id": "rogue", "public_key": p.public_key(key), "capabilities": ["quality.assurance"], "concurrency": 1}
    with pytest.raises(p.ProtocolError):
        c.register(p.sign(identity, "rogue", key), trusted_public_key=p.public_key(wk))
    with pytest.raises(p.ProtocolError):
        c.issue_fixture("rogue", actor_id=17)
    with pytest.raises(p.ProtocolError):
        c.issue_fixture("test_worker", actor_id=999)


def test_duplicate_acceptance_and_global_capacity(context):
    c, ck, wk, clock, a, raw = context
    assert c.ingest(event(context)) == "accepted"
    with pytest.raises(p.ProtocolError, match="Replay"):
        c.ingest(event(context))
    with pytest.raises(p.ProtocolError, match="concurrency"):
        c.issue_fixture("test_worker", actor_id=17)
    assert c.attempt(a["attempt_id"])["sequence"] == 1


def test_expired_attempt_cannot_complete_or_replay_after_restart(context):
    c, ck, wk, clock, a, raw = context
    c.ingest(event(context))
    clock[0] = a["expires_at"]
    with pytest.raises(p.ProtocolError, match="expired"):
        c.ingest(event(context, "checkpoint", sequence=2, data={"checkpoint": "sandbox_finished"}))
    reopened = WorkerController(ControlPlane(c.store.path), ck, trusted_actor_ids={17}, clock=lambda: clock[0])
    assert reopened.recover_expired() == [a["attempt_id"]]
    assert reopened.attempt(a["attempt_id"])["state"] == "interrupted"
    assert reopened.recover_expired() == []


def test_cancel_is_signed_scoped_and_invalidates_late_results(context, tmp_path):
    c, ck, wk, clock, a, raw = context
    c.ingest(event(context))
    cancel = c.cancel(a["attempt_id"], actor_id=17)
    runtime = WorkerRuntime("test_worker", wk, p.public_key(ck), tmp_path / "inbox.db", clock=lambda: clock[0])
    assert runtime.cancellation(cancel, a)
    with pytest.raises(p.ProtocolError):
        runtime.cancellation(p.sign(p.decode(cancel)["payload"], "controller", wk), a)
    with pytest.raises(p.ProtocolError):
        c.ingest(event(context, "checkpoint", sequence=2, data={"checkpoint": "sandbox_finished"}))
    assert c.attempt(a["attempt_id"])["state"] == "cancelled"


def test_runtime_success_durable_artifacts_and_duplicate_prevention(context, tmp_path):
    c, ck, wk, clock, a, raw = context
    runtime = WorkerRuntime("test_worker", wk, p.public_key(ck), tmp_path / "inbox.db", clock=lambda: clock[0])
    sandbox = SuccessSandbox()
    assert runtime.run(raw, sandbox, c.ingest) == "succeeded"
    persisted = c.attempt(a["attempt_id"])
    assert persisted["requests"] == 1 and persisted["tokens"] == 200
    artifact = tmp_path / "artifacts" / a["task_id"] / a["attempt_id"] / "validation.txt"
    assert artifact.read_bytes() == b"Ran 2 tests\nOK\n"
    reopened = WorkerRuntime("test_worker", wk, p.public_key(ck), tmp_path / "inbox.db", clock=lambda: clock[0])
    with pytest.raises(p.ProtocolError, match="Replayed"):
        reopened.run(raw, sandbox, c.ingest)
    assert sandbox.calls == 1
    copy_dir = tmp_path.parent / (tmp_path.name + "-backup")
    backup(tmp_path, copy_dir)
    assert verify_directory(copy_dir)["counts"]["worker_attempts_v1"] == 1
    assert verify_directory(copy_dir)["counts"]["worker_events_v1"] >= 4


def test_worker_crash_reserves_attempt_and_never_restarts_it(context, tmp_path):
    c, ck, wk, clock, a, raw = context
    class Crash:
        def run(self, *args, **kwargs):
            raise OSError("synthetic crash")
    runtime = WorkerRuntime("test_worker", wk, p.public_key(ck), tmp_path / "inbox.db", clock=lambda: clock[0])
    with pytest.raises(OSError):
        runtime.run(raw, Crash(), c.ingest)
    assert c.attempt(a["attempt_id"])["state"] == "accepted"
    with pytest.raises(p.ProtocolError, match="Replayed"):
        runtime.run(raw, SuccessSandbox(), c.ingest)


def test_artifact_forgery_is_rejected_without_completing_task(context):
    c, ck, wk, clock, a, raw = context
    c.ingest(event(context))
    data = {"status": "failed", "reason": "validation_failed", "artifacts": [{"path": "result.txt", "sha256": "0"*64, "size": 4}]}
    with pytest.raises(p.ProtocolError, match="integrity"):
        c.ingest(event(context, "failure", sequence=2, data=data), artifacts={"result.txt": b"fake"})
    assert c.attempt(a["attempt_id"])["sequence"] == 1


def test_unauthorized_tool_evidence_and_budget_reset_are_rejected(context):
    c, ck, wk, clock, a, raw = context
    c.ingest(event(context))
    evidence = {"operation": "workspace.write", "target": "calculator.py", "parameters_digest": "a"*64, "outcome": "succeeded"}
    with pytest.raises(p.ProtocolError, match="scope"):
        c.ingest(event(context, "tool", sequence=2, data=evidence))
    evidence["outcome"] = "denied"
    c.ingest(event(context, "tool", sequence=2, data=evidence, usage={"requests": 1, "tokens": 200}))
    with pytest.raises(p.ProtocolError, match="accounting"):
        c.ingest(event(context, "checkpoint", sequence=3, data={"checkpoint": "sandbox_finished"}))
    with pytest.raises(p.ProtocolError, match="accounting"):
        c.ingest(event(context, "checkpoint", sequence=3, data={"checkpoint": "sandbox_finished"}, usage={"requests": 2, "tokens": 600}))


@pytest.mark.parametrize("scenario,expected", [("unavailable", "inference_unavailable"), ("success", "inference_budget")])
def test_unavailable_inference_and_empty_budget_never_launch_sandbox(tmp_path, scenario, expected):
    class Forbidden:
        def run(self, *a, **kw):
            pytest.fail("Sandbox must not launch")
    if scenario == "unavailable":
        result = exercise(tmp_path / "demo", Forbidden(), scenario=scenario)
        assert result["state"] == "failed" and result["requests"] == 0
        assert result["result"]["data"]["reason"] == expected
    else:
        ck, wk = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
        cp = ControlPlane(tmp_path / "foxforge.db")
        c = WorkerController(cp, ck, trusted_actor_ids={1})
        identity = {"worker_id": "worker", "public_key": p.public_key(wk), "capabilities": ["quality.assurance"], "concurrency": 1}
        c.register(p.sign(identity, "worker", wk), trusted_public_key=p.public_key(wk))
        raw = c.issue_fixture("worker", actor_id=1, budgets={**p.MAXIMA, "requests": 0})
        runtime = WorkerRuntime("worker", wk, p.public_key(ck), tmp_path / "inbox.db")
        assert runtime.run(raw, Forbidden(), c.ingest) == "failed"


def test_sandbox_command_has_no_mounts_network_credentials_or_privileges(context, monkeypatch):
    sandbox = DockerSandbox.__new__(DockerSandbox)
    sandbox.exe, sandbox.image = "docker", "sha256:" + "a"*64
    command = sandbox.command(context[4], "foxforge-fixture-test")
    assert "--network=none" in command and "--read-only" in command and "--cap-drop=ALL" in command
    assert "--user=11001:11001" in command and "--log-driver=none" in command
    assert not any(x in command for x in ("-v", "--volume", "--mount", "--privileged", "--env-file", "-e"))
    assert any(x.startswith("--memory=") for x in command) and any(x.startswith("--pids-limit=") for x in command)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-inherited")
    monkeypatch.setenv("DOCKER_HOST", "unapproved-host")
    assert "OPENAI_API_KEY" not in environment() and "DOCKER_HOST" not in environment()


def test_control_plane_mode_rejects_all_new_execution_paths(tmp_path, monkeypatch):
    from foxforge import worker_sandbox
    monkeypatch.setenv("FOXFORGE_CONTROL_PLANE_ONLY", "1")
    with pytest.raises(RuntimeError, match="control-plane"):
        DockerSandbox()
    with pytest.raises(RuntimeError, match="control-plane"):
        WorkerRuntime("x", None, "a"*64, tmp_path / "must-not-exist.db")
    with pytest.raises(RuntimeError, match="control-plane"):
        exercise(tmp_path / "must-not-exist", SuccessSandbox())
    assert worker_sandbox.main() == 2
    assert not (tmp_path / "must-not-exist").exists()


def test_fixture_revision_is_immutable_and_sha_shaped():
    value = repository()
    assert value == repository() and len(value["base_sha"]) == 40
    assert value["name"] == "foxforge-fixtures/calculator"


def test_worker_rejects_a_changed_fixture_before_execution(context, tmp_path, monkeypatch):
    from foxforge import worker_fixture
    c, ck, wk, clock, a, raw = context
    runtime = WorkerRuntime("test_worker", wk, p.public_key(ck), tmp_path / "inbox.db", clock=lambda: clock[0])
    monkeypatch.setitem(worker_fixture.FILES, "calculator.py", b"raise RuntimeError('changed fixture')\n")
    with pytest.raises(p.ProtocolError, match="fixture"):
        runtime.run(raw, SuccessSandbox(), c.ingest)
    assert c.attempt(a["attempt_id"])["state"] == "issued"


@pytest.mark.parametrize("name", ["../file", "/etc/passwd", "C:/file", "CON", "aux.txt", "file.", ".git/config", "a//b"])
def test_scoped_paths_are_portable_and_cannot_escape(name):
    with pytest.raises(p.ProtocolError):
        p.path(name)


def test_rejected_messages_are_audited_without_untrusted_payload(context):
    c, *_ = context
    with pytest.raises(p.ProtocolError):
        c.ingest(b'{"untrusted":"do-not-log-me"}')
    with c.store.connect() as db:
        row = db.execute("SELECT outcome,detail_json FROM audit_events WHERE event_type='worker.message_rejected'").fetchone()
    assert row["outcome"] == "denied" and "do-not-log-me" not in row["detail_json"]


def test_result_requires_independent_validation_step_and_matching_attempt(context):
    c, ck, wk, clock, a, raw = context
    c.ingest(event(context))
    data = {"status": "succeeded", "reason": "validated", "artifacts": []}
    with pytest.raises(p.ProtocolError, match="validation evidence"):
        c.ingest(event(context, "result", sequence=2, data=data))
    value = p.decode(event(context))["payload"]
    value["attempt_id"] = "attempt_stale"
    with pytest.raises(p.ProtocolError, match="Unknown attempt"):
        c.ingest(p.sign(value, "test_worker", wk))


def test_cancel_before_launch_does_not_invoke_sandbox(context, tmp_path):
    c, ck, wk, clock, a, raw = context
    sandbox = SuccessSandbox()
    runtime = WorkerRuntime("test_worker", wk, p.public_key(ck), tmp_path / "inbox.db", clock=lambda: clock[0])
    assert runtime.run(raw, sandbox, c.ingest, cancelled=lambda: True) == "cancelled"
    assert sandbox.calls == 0 and c.attempt(a["attempt_id"])["state"] == "cancelled"


def test_failure_does_not_cancel_an_unrelated_worker(context):
    c, ck, wk, clock, a, raw = context
    other_key = Ed25519PrivateKey.generate()
    c.concurrency = 2
    identity = {"worker_id": "other", "public_key": p.public_key(other_key), "capabilities": ["quality.assurance"], "concurrency": 1}
    c.register(p.sign(identity, "other", other_key), trusted_public_key=p.public_key(other_key))
    other_raw = c.issue_fixture("other", actor_id=17)
    other = p.verify(other_raw, "controller", p.public_key(ck))
    c.ingest(event(context))
    c.ingest(event(context, "failure", sequence=2, data={"status": "failed", "reason": "inference_unavailable", "artifacts": []}))
    assert c.attempt(other["attempt_id"])["state"] == "issued"


def test_cleanup_cannot_remove_unrelated_container(monkeypatch):
    sandbox = DockerSandbox.__new__(DockerSandbox)
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: pytest.fail("Unowned container must never reach Docker"))
    with pytest.raises(p.ProtocolError, match="unowned"):
        sandbox.remove("another-project-container")
