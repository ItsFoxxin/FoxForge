"""Disposable fixture broker INSIDE the optional sandbox image (stdlib only).

Fixed tools, fixed fixture, no arbitrary commands/model inference/credentials.
This is not a hostile multi-tenant execution service.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

if __package__:
    from .worker_fixture import FILES, TEST_UPDATE
else:
    sys.path.insert(0, "/runner")  # trusted read-only image code, never the workspace
    from worker_fixture import FILES, TEST_UPDATE


def main():
    if "FOXFORGE_CONTROL_PLANE_ONLY" in os.environ:
        return 2
    import resource  # Linux-only optional sandbox; package imports stay portable
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        return 2
    value = json.loads(raw)
    limits = value["budgets"]
    # Outer supervisor validates all input first. Still enforce in this process.
    remaining = value["expires_at"] - int(time.time())
    if remaining < 1:
        return 2
    signal.alarm(remaining)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (limits["artifact_bytes"], limits["artifact_bytes"]))
    os.umask(0o077)
    root = Path("/workspace")
    for name, body in FILES.items():
        (root / name).write_bytes(body)
    evidence = []
    artifacts = {}
    def tool(operation, target, parameters):
        allowed = operation in value["operations"] and (
            target in value["write_paths"] if operation == "workspace.write" else
            target == "calculator-tests" if operation == "validation.execute" else target in value["read_paths"])
        item = {"operation": operation, "target": target, "parameters_digest": hashlib.sha256(
            json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "outcome": "allowed" if allowed else "denied"}
        evidence.append(item)
        return item if allowed else None
    scenario = value["parameters"]["scenario"]
    status, reason = "failed", "tool_denied"
    if scenario == "output":
        sys.stdout.write("x" * 100000)
        return 0
    if scenario == "deadline":
        time.sleep(310)
    if scenario == "memory":
        data = bytearray(400 * 1024 * 1024)
        data[0] = 1
        return 3
    if scenario == "disk":
        try:
            (root / "bounded.bin").write_bytes(b"x" * (limits["artifact_bytes"] + 1))
        except OSError:
            reason = "disk_limited"
        else:
            reason = "disk_limit_failed"
    elif scenario == "network":
        try:
            socket.create_connection(("192.0.2.1", 9), timeout=1).close()
            reason = "network_limit_failed"
        except OSError:
            reason = "network_denied"
    elif scenario == "processes":
        children = []
        try:
            for _ in range(64):
                children.append(subprocess.Popen(["/bin/sleep", "10"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        except OSError:
            reason = "process_limited"
        else:
            reason = "process_limit_failed"
        finally:
            for child in children:
                child.kill()
                child.wait()
    else:
        target = "calculator.py" if scenario == "readonly-denial" else "test_calculator.py"
        write = tool("workspace.write", target, {"content_sha256": hashlib.sha256(TEST_UPDATE).hexdigest()})
        if write:
            (root / target).write_bytes(TEST_UPDATE)
            write["outcome"] = "succeeded"
            validation = tool("validation.execute", "calculator-tests", {"command_id": "fixture-unittest-v1"})
            if validation:
                # The command registry is code-owned, not a string from a model.
                command = [sys.executable, "-I", "-B", "-c", "import sys,unittest;sys.path.insert(0,'/workspace');r=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover('/workspace'));sys.exit(0 if r.wasSuccessful() and r.testsRun>0 else 1)"]
                out = root / "validation.txt"
                with out.open("wb") as stream:
                    result = subprocess.run(command, cwd=root, env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/nonexistent"}, stdout=stream, stderr=subprocess.STDOUT, timeout=max(1, remaining-1))
                body = out.read_bytes()
                validation["outcome"] = "succeeded" if result.returncode == 0 else "failed"
                artifacts["validation.txt"] = base64.b64encode(body).decode("ascii")
                status, reason = ("succeeded", "validated") if result.returncode == 0 else ("failed", "validation_failed")
    print(json.dumps({"status": status, "reason": reason, "evidence": evidence, "artifacts": artifacts}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print('{"status":"failed","reason":"sandbox_error","evidence":[],"artifacts":{}}')
        raise SystemExit(1)
