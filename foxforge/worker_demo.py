"""Operator-run, disposable integration harness. Never connects GitHub issues.

This harness puts logical controller and supervisor in one test process; it is
not a production topology or a service to deploy on the control-plane VM.
"""
import argparse
import json
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from . import worker_protocol as p
from .control_plane import ControlPlane
from .security import require_execution_worker
from .worker_controller import WorkerController
from .worker_docker import DockerSandbox, cleanup_expired
from .worker_runtime import WorkerRuntime


def exercise(directory: Path, sandbox, *, scenario="success", duration=60, cancelled=lambda: False):
    require_execution_worker()
    if directory.exists() or directory.is_symlink() or not directory.is_absolute():
        raise p.ProtocolError("Demo state must use a new absolute disposable directory")
    directory.mkdir(mode=0o700)
    controller_key, worker_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    store = ControlPlane(directory / "foxforge.db")
    controller = WorkerController(store, controller_key, trusted_actor_ids={1})
    worker_id = "disposable_worker"
    identity = {"worker_id": worker_id, "public_key": p.public_key(worker_key), "capabilities": ["quality.assurance"], "concurrency": 1}
    controller.register(p.sign(identity, worker_id, worker_key), trusted_public_key=p.public_key(worker_key))
    assignment = controller.issue_fixture(worker_id, actor_id=1, scenario=scenario, duration=duration)
    payload = p.verify(assignment, "controller", p.public_key(controller_key))
    worker = WorkerRuntime(worker_id, worker_key, p.public_key(controller_key), directory / "worker-inbox.db")
    try:
        worker.run(assignment, sandbox, controller.ingest, cancelled=cancelled)
    except p.ProtocolError:
        if not controller.recover_expired():
            raise
    result = controller.attempt(payload["attempt_id"])
    return {"attempt_id": result["id"], "state": result["state"], "requests": result["requests"],
            "tokens": result["tokens"], "result": json.loads(result["result_json"]) if result["result_json"] else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Disposable worker prototype; synthetic fixture and mock inference only")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--image", default="foxforge-worker:0.4.0")
    parser.add_argument("--scenario", choices=sorted(p.SCENARIOS), default="success")
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--cleanup-expired", action="store_true")
    args = parser.parse_args(argv)
    try:
        require_execution_worker()
        if args.cleanup_expired:
            print(json.dumps({"removed": cleanup_expired()}))
            return 0
        if args.state_dir is None:
            parser.error("--state-dir is required and must be new")
        result = exercise(args.state_dir, DockerSandbox(args.image), scenario=args.scenario, duration=args.duration)
        print(json.dumps(result, indent=2))
        return 0 if result["state"] == "succeeded" else 1
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        print("Worker prototype failed safely; inspect the disposable SQLite ledger. No credential values were logged.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
