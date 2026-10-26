"""Controller-owned worker attempts in the existing SQLite control plane.

Only synthetic tasks can be issued. Planning records never authorize execution.
No shell, Docker or inference calls are made by this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from uuid import uuid4

from . import worker_protocol as p
from .control_plane import ControlPlane
from .capabilities import get_capability
from .worker_fixture import PROFILE_DIGEST, repository


class WorkerController:
    def __init__(self, store: ControlPlane, signing_key, *, trusted_actor_ids: set[int], clock=time.time, concurrency=1):
        if not trusted_actor_ids or any(type(x) is not int or x <= 0 for x in trusted_actor_ids):
            raise p.ProtocolError("Explicit trusted operator IDs required")
        p.integer(concurrency, 1, 4)
        self.store, self.key, self.actors, self.clock, self.concurrency = store, signing_key, frozenset(trusted_actor_ids), clock, concurrency
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS workers_v1(
                    id TEXT PRIMARY KEY, identity_json TEXT NOT NULL, active INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS worker_attempts_v1(
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL UNIQUE, worker_id TEXT NOT NULL REFERENCES workers_v1(id),
                    assignment_json TEXT NOT NULL, assignment_digest TEXT NOT NULL UNIQUE, state TEXT NOT NULL,
                    sequence INTEGER NOT NULL DEFAULT 0, requests INTEGER NOT NULL DEFAULT 0, tokens INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT);
                CREATE TABLE IF NOT EXISTS worker_events_v1(
                    attempt_id TEXT NOT NULL REFERENCES worker_attempts_v1(id), sequence INTEGER NOT NULL,
                    event_digest TEXT NOT NULL UNIQUE, event_json TEXT NOT NULL,
                    PRIMARY KEY(attempt_id,sequence));
            """)

    def _audit(self, db, event, outcome, **detail):
        self.store._audit(db, None, "worker." + event, outcome, detail)

    def register(self, signed_identity: bytes, *, trusted_public_key: str):
        # The public key is approved by an operator out of band, never by this message.
        raw = p.decode(signed_identity)
        if not isinstance(raw, dict):
            raise p.ProtocolError("Expected signed worker identity")
        identity = p.verify(signed_identity, raw.get("key_id"), trusted_public_key)
        p.validate_identity(identity)
        if raw["key_id"] != identity["worker_id"] or identity["public_key"] != trusted_public_key or identity["capabilities"] != ["quality.assurance"]:
            raise p.ProtocolError("Worker identity/capabilities are not operator approved")
        encoded = self.store._safe_json(identity)
        with self.store.transaction() as db:
            old = db.execute("SELECT * FROM workers_v1 WHERE id=?", (identity["worker_id"],)).fetchone()
            if old and (old["identity_json"] != encoded or not old["active"]):
                raise p.ProtocolError("Worker replacement or reactivation requires separate approval")
            db.execute("INSERT OR IGNORE INTO workers_v1 VALUES (?,?,1)", (identity["worker_id"], encoded))
            self._audit(db, "registered", "allowed", worker_id=identity["worker_id"], public_key_digest=p.digest(trusted_public_key))

    def issue_fixture(self, worker_id: str, *, actor_id: int, scenario="success", duration=60,
                      operations=None, write_paths=None, budgets=None):
        if actor_id not in self.actors or type(actor_id) is not int:
            raise p.ProtocolError("Execution requires an explicitly trusted operator")
        p.integer(duration, 1, 300)
        now = int(self.clock())
        assignment = {"kind": "assignment", "assignment_id": "assignment_" + uuid4().hex,
            "task_id": "fixture_" + uuid4().hex, "attempt_id": "attempt_" + uuid4().hex,
            "worker_id": worker_id, "repository": repository(), "capability": "quality.assurance",
            "operations": operations if operations is not None else sorted(p.OPERATIONS),
            "read_paths": sorted(["calculator.py", "test_calculator.py"]),
            "write_paths": write_paths if write_paths is not None else ["test_calculator.py"],
            "policy_version": 1, "profile_digest": PROFILE_DIGEST, "issued_at": now,
            "expires_at": now + duration, "budgets": budgets if budgets is not None else {**p.MAXIMA, "requests": 1, "tokens": 512},
            "parameters": {"fixture": "calculator", "scenario": scenario}}
        assignment["approval"] = {"actor_id": actor_id, "task_id": assignment["task_id"], "action": "fixture.execute",
            "repository_id": 1, "base_sha": assignment["repository"]["base_sha"],
            "parameters_digest": p.digest(p.execution_parameters(assignment)), "expires_at": assignment["expires_at"]}
        p.validate_assignment(assignment)
        registered_operations = {tool.operation for tool in get_capability(assignment["capability"]).tools}
        if any(operation not in registered_operations for operation in assignment["operations"]):
            raise p.ProtocolError("Assignment exceeds the central capability catalog")
        if any(x not in {"test_calculator.py"} for x in assignment["write_paths"]):
            raise p.ProtocolError("Fixture writes must be confined to test_calculator.py")
        with self.store.transaction() as db:
            worker = db.execute("SELECT * FROM workers_v1 WHERE id=? AND active=1", (worker_id,)).fetchone()
            if not worker:
                raise p.ProtocolError("Unregistered worker")
            count = db.execute("SELECT COUNT(*) FROM worker_attempts_v1 WHERE state IN ('issued','accepted')").fetchone()[0]
            busy = db.execute("SELECT 1 FROM worker_attempts_v1 WHERE worker_id=? AND state IN ('issued','accepted')", (worker_id,)).fetchone()
            if count >= self.concurrency or busy:
                raise p.ProtocolError("Worker concurrency limit reached")
            db.execute("INSERT INTO worker_attempts_v1(id,task_id,worker_id,assignment_json,assignment_digest,state) VALUES (?,?,?,?,?,'issued')",
                (assignment["attempt_id"], assignment["task_id"], worker_id, self.store._safe_json(assignment), p.digest(assignment)))
            self._audit(db, "authorized", "allowed", attempt_id=assignment["attempt_id"], actor_id=actor_id,
                        scope=assignment["approval"], assignment_digest=p.digest(assignment))
        return p.sign(assignment, "controller", self.key)

    def attempt(self, attempt_id):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM worker_attempts_v1 WHERE id=?", (attempt_id,)).fetchone()
        if not row:
            raise p.ProtocolError("Unknown execution attempt")
        return dict(row)

    def ingest(self, raw: bytes, *, artifacts: dict[str, bytes] | None = None):
        try:
            return self._ingest(raw, artifacts=artifacts)
        except p.ProtocolError:
            with self.store.transaction() as db:
                self._audit(db, "message_rejected", "denied", code="protocol_rejected",
                            message_digest=hashlib.sha256(raw[:p.MAX_MESSAGE] if isinstance(raw, bytes) else b"").hexdigest())
            raise

    def _ingest(self, raw: bytes, *, artifacts: dict[str, bytes] | None = None):
        outer = p.decode(raw)
        if not isinstance(outer, dict) or not isinstance(outer.get("key_id"), str):
            raise p.ProtocolError("Missing worker identity")
        with self.store.transaction() as db:
            worker = db.execute("SELECT * FROM workers_v1 WHERE id=? AND active=1", (outer["key_id"],)).fetchone()
            if not worker:
                raise p.ProtocolError("Unknown or revoked worker")
            event = p.verify(raw, worker["id"], json.loads(worker["identity_json"])["public_key"])
            p.validate_event(event)
            row = db.execute("SELECT * FROM worker_attempts_v1 WHERE id=?", (event["attempt_id"],)).fetchone()
            if not row:
                raise p.ProtocolError("Unknown attempt")
            assignment = json.loads(row["assignment_json"])
            if any(event[k] != assignment[k] for k in ("assignment_id", "attempt_id", "worker_id")) or event["assignment_digest"] != row["assignment_digest"]:
                raise p.ProtocolError("Stale or cross-task result")
            if self.clock() >= assignment["expires_at"] or row["state"] not in {"issued", "accepted"}:
                raise p.ProtocolError("Lease expired, cancelled or already completed")
            if event["sequence"] != row["sequence"] + 1 or (row["state"] == "issued") != (event["kind"] == "accepted"):
                raise p.ProtocolError("Replay or out-of-order event")
            for key in ("requests", "tokens"):
                if not row[key] <= event["usage"][key] <= assignment["budgets"][key]:
                    raise p.ProtocolError("Worker exceeded or reset resource accounting")
            if event["kind"] == "tool":
                ev = event["data"]
                allowed = ev["operation"] in assignment["operations"] and (
                    ev["target"] in assignment["write_paths"] if ev["operation"] == "workspace.write" else
                    ev["target"] == "calculator-tests" if ev["operation"] == "validation.execute" else ev["target"] in assignment["read_paths"])
                if not allowed and ev["outcome"] != "denied":
                    raise p.ProtocolError("Tool evidence exceeds assignment scope")
            terminal = event["kind"] in {"result", "failure", "cancelled"}
            if terminal:
                self._verify_artifacts(event["data"]["artifacts"], artifacts or {}, assignment["budgets"]["artifact_bytes"])
                if event["kind"] == "result":
                    evidence = [json.loads(r[0])["data"] for r in db.execute("SELECT event_json FROM worker_events_v1 WHERE attempt_id=?", (row["id"],)) if json.loads(r[0])["kind"] == "tool"]
                    if not any(e["operation"] == "validation.execute" and e["outcome"] == "succeeded" for e in evidence):
                        raise p.ProtocolError("Success requires actual validation evidence")
                self._store_artifacts(assignment, artifacts or {})
            elif artifacts:
                raise p.ProtocolError("Artifacts only accompany final results")
            state = event["data"]["status"] if terminal else "accepted"
            safe = self.store._safe_json(event)
            db.execute("INSERT INTO worker_events_v1 VALUES (?,?,?,?)", (row["id"], event["sequence"], p.digest(event), safe))
            db.execute("UPDATE worker_attempts_v1 SET state=?,sequence=?,requests=?,tokens=?,result_json=? WHERE id=?",
                (state, event["sequence"], event["usage"]["requests"], event["usage"]["tokens"], safe if terminal else None, row["id"]))
            self._audit(db, event["kind"], state, attempt_id=row["id"], sequence=event["sequence"],
                        event_digest=p.digest(event), data=event["data"])
        return state

    def _store_artifacts(self, assignment, contents):
        if not contents:
            return
        # IDs and bytes have already passed the strict contract/integrity checks.
        root = self.store.path.parent / "artifacts"
        directory = root / assignment["task_id"] / assignment["attempt_id"]
        for ancestor in (root, directory.parent, directory):
            if ancestor.is_symlink():
                raise p.ProtocolError("Artifact directories cannot be symlinks")
            ancestor.mkdir(mode=0o700, exist_ok=True)
        for name, body in contents.items():
            if "/" in name:  # prototype exports flat, bounded artifacts only
                raise p.ProtocolError("Nested artifacts are not supported by the prototype")
            target = directory / name
            if target.is_symlink():
                raise p.ProtocolError("Artifact symlinks are forbidden")
            if target.exists():
                if target.read_bytes() != body:
                    raise p.ProtocolError("Refusing to overwrite an existing artifact")
            else:
                with target.open("xb") as stream:
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())
        if hasattr(os, "O_DIRECTORY"):
            for ancestor in (directory, directory.parent, root):
                fd = os.open(ancestor, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)

    @staticmethod
    def _verify_artifacts(refs, contents, maximum):
        if set(contents) != {x["path"] for x in refs} or sum(x["size"] for x in refs) > maximum:
            raise p.ProtocolError("Artifact manifest/size mismatch")
        for ref in refs:
            body = contents[ref["path"]]
            if not isinstance(body, bytes) or len(body) != ref["size"] or hashlib.sha256(body).hexdigest() != ref["sha256"]:
                raise p.ProtocolError("Artifact integrity failure")

    def cancel(self, attempt_id: str, *, actor_id: int):
        if type(actor_id) is not int or actor_id not in self.actors:
            raise p.ProtocolError("Cancellation requires trusted operator")
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM worker_attempts_v1 WHERE id=?", (attempt_id,)).fetchone()
            if not row or row["state"] not in {"issued", "accepted"}:
                raise p.ProtocolError("No cancellable lease")
            assignment = json.loads(row["assignment_json"])
            if self.clock() >= assignment["expires_at"]:
                raise p.ProtocolError("Expired leases require recovery, not cancellation")
            message = {"kind": "cancel", "assignment_id": assignment["assignment_id"], "attempt_id": attempt_id,
                       "worker_id": row["worker_id"], "assignment_digest": row["assignment_digest"], "expires_at": assignment["expires_at"]}
            p.validate_cancel(message)
            db.execute("UPDATE worker_attempts_v1 SET state='cancelled' WHERE id=?", (attempt_id,))
            self._audit(db, "cancelled", "cancelled", attempt_id=attempt_id, actor_id=actor_id)
        return p.sign(message, "controller", self.key)

    def recover_expired(self):
        # Never restart an uncertain attempt or refund its inference reservation.
        changed = []
        with self.store.transaction() as db:
            for row in db.execute("SELECT * FROM worker_attempts_v1 WHERE state IN ('issued','accepted')").fetchall():
                if self.clock() >= json.loads(row["assignment_json"])["expires_at"]:
                    db.execute("UPDATE worker_attempts_v1 SET state='interrupted' WHERE id=?", (row["id"],))
                    self._audit(db, "recovered", "interrupted", attempt_id=row["id"])
                    changed.append(row["id"])
        return changed
