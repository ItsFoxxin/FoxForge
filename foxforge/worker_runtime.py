"""Authenticated mock-runtime adapter for synthetic tasks on a worker host.

Private worker signing keys stay in the supervisor, outside the sandbox. The
independent worker inbox only prevents replay; it cannot authorize any new work.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from . import worker_protocol as p
from .security import require_execution_worker
from .worker_fixture import PROFILE_DIGEST, repository


class WorkerRuntime:
    def __init__(self, worker_id, signing_key, controller_public_key: str, inbox: Path, *, clock=time.time):
        require_execution_worker()
        p.identifier(worker_id)
        p.sha256(controller_public_key)
        if inbox.is_symlink():
            raise p.ProtocolError("Worker inbox symlinks are forbidden")
        self.worker_id, self.key, self.controller, self.inbox, self.clock = worker_id, signing_key, controller_public_key, inbox, clock
        with closing(sqlite3.connect(inbox)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS receipts(assignment_id TEXT PRIMARY KEY, attempt_id TEXT UNIQUE, digest TEXT NOT NULL, state TEXT NOT NULL)")
            db.commit()

    def run(self, signed_assignment: bytes, sandbox, emit, *, cancelled=lambda: False):
        require_execution_worker()
        assignment = p.verify(signed_assignment, "controller", self.controller)
        p.validate_assignment(assignment)
        if (assignment["worker_id"] != self.worker_id or assignment["repository"] != repository()
            or assignment["profile_digest"] != PROFILE_DIGEST or not assignment["issued_at"] <= self.clock() < assignment["expires_at"]
            or any(x != "test_calculator.py" for x in assignment["write_paths"])
            or any(x not in {"calculator.py", "test_calculator.py"} for x in assignment["read_paths"])):
            raise p.ProtocolError("Worker scope, fixture, profile or lease mismatch")
        with closing(sqlite3.connect(self.inbox)) as db:
            try:
                db.execute("INSERT INTO receipts VALUES (?,?,?,'accepted')", (assignment["assignment_id"], assignment["attempt_id"], p.digest(assignment)))
                db.commit()  # durable before any external operation
            except sqlite3.IntegrityError:
                raise p.ProtocolError("Replayed assignment requires intervention") from None
        sequence = 0
        usage = {"requests": 0, "tokens": 0}
        def event(kind, data, artifacts=None):
            nonlocal sequence
            sequence += 1
            value = {"kind": kind, "assignment_id": assignment["assignment_id"], "attempt_id": assignment["attempt_id"],
                "worker_id": self.worker_id, "assignment_digest": p.digest(assignment), "sequence": sequence,
                "usage": dict(usage), "data": data}
            p.validate_event(value)
            emit(p.sign(value, self.worker_id, self.key), artifacts=artifacts)
        state = receipt_state = "interrupted"
        try:
            event("accepted", {"checkpoint": "accepted"})  # caller must acknowledge before dispatch
            if cancelled():
                state, reason, evidence, artifacts = "cancelled", "operator_cancelled", [], {}
            elif assignment["parameters"]["scenario"] == "unavailable":
                state, reason, evidence, artifacts = "failed", "inference_unavailable", [], {}
            elif assignment["budgets"]["requests"] < 1 or assignment["budgets"]["tokens"] < 200:
                state, reason, evidence, artifacts = "failed", "inference_budget", [], {}
            else:
                # Mock accounting only. No gateway or paid inference is invoked.
                usage.update(requests=1, tokens=200)
                event("checkpoint", {"checkpoint": "sandbox_starting"})
                result = sandbox.run(assignment, cancelled=cancelled)
                p.fields(result, "status reason evidence artifacts")
                reply_status, reason, evidence, artifacts = (result[name] for name in ("status", "reason", "evidence", "artifacts"))
                if not isinstance(reply_status, str) or reply_status not in {"succeeded", "failed", "cancelled", "interrupted"} or not isinstance(evidence, list) or len(evidence) > 12:
                    raise p.ProtocolError("Malformed sandbox result")
                state = reply_status
                for item in evidence:
                    p.validate_evidence(item)
                    event("tool", item)
                event("checkpoint", {"checkpoint": "sandbox_finished"})
            if self.clock() >= assignment["expires_at"]:
                state, reason = "interrupted", "lease_expired"
            refs = []
            if not isinstance(artifacts, dict) or len(artifacts) > 4 or any(not isinstance(x, bytes) for x in artifacts.values()) or sum(len(x) for x in artifacts.values()) > assignment["budgets"]["artifact_bytes"]:
                raise p.ProtocolError("Sandbox artifacts exceed policy")
            for name, body in sorted(artifacts.items()):
                p.path(name)
                if not isinstance(body, bytes):
                    raise p.ProtocolError("Artifact contents must be bytes")
                refs.append({"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size": len(body)})
            kind = "result" if state == "succeeded" else "cancelled" if state == "cancelled" else "failure"
            event(kind, {"status": state, "reason": reason, "artifacts": refs}, artifacts)
            receipt_state = state  # terminal only after the controller acknowledges
            return state
        finally:
            with closing(sqlite3.connect(self.inbox)) as db:
                db.execute("UPDATE receipts SET state=? WHERE assignment_id=?", (receipt_state, assignment["assignment_id"]))
                db.commit()

    def cancellation(self, signed_cancel: bytes, assignment: dict) -> bool:
        value = p.verify(signed_cancel, "controller", self.controller)
        p.validate_cancel(value)
        if (any(value[k] != assignment[k] for k in ("assignment_id", "attempt_id", "worker_id", "expires_at"))
                or value["assignment_digest"] != p.digest(assignment) or self.clock() >= value["expires_at"]):
            raise p.ProtocolError("Stale or mismatched cancellation")
        return True
