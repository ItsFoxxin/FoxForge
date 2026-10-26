"""Trusted worker-host Docker supervisor. Never usable by the control-plane image.

No socket, bind mounts, key, token, Docker client or network is given to a sandbox.
The supervisor itself is privileged relative to its Docker daemon: isolate it on
a disposable worker VM. Docker alone is not a hostile-code security boundary.
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from uuid import uuid4

from . import worker_protocol as p
from .security import require_execution_worker


def environment():
    return {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP"}}


class DockerSandbox:
    def __init__(self, image="foxforge-worker:0.4.0", *, clock=time.time):
        require_execution_worker()
        if sys.platform != "linux":
            raise p.ProtocolError("The optional prototype supervisor requires a disposable Linux Docker host")
        if image != "foxforge-worker:0.4.0" and not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
            raise p.ProtocolError("Use the reviewed local worker image or its immutable image ID")
        self.exe = shutil.which("docker")
        if not self.exe:
            raise p.ProtocolError("Optional Docker worker is unavailable; ordinary unit tests do not need it")
        inspected = subprocess.run([self.exe, "image", "inspect", image, "--format", "{{.Id}}"], capture_output=True, timeout=15, env=environment())
        self.image = inspected.stdout.decode("ascii", errors="replace").strip()
        if inspected.returncode or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image):
            raise p.ProtocolError("Build and review the local worker image before execution")
        self.clock = clock

    def command(self, assignment, name):
        budget = assignment["budgets"]
        return [self.exe, "run", "--name", name, "--label", "foxforge.prototype=true",
                "--label", f"foxforge.expires_at={assignment['expires_at']}",
                "--read-only", "--user=11001:11001", "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
                "--network=none", "--log-driver=none", "--cpus=1", f"--memory={budget['memory_mb']}m",
                f"--memory-swap={budget['memory_mb']}m", f"--pids-limit={budget['pids']}",
                "--ulimit=nofile=128:128", "--ulimit=core=0:0",
                f"--tmpfs=/workspace:rw,noexec,nosuid,nodev,size={budget['disk_mb']}m,uid=11001,gid=11001,mode=0700",
                "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=4m,uid=11001,gid=11001,mode=0700",
                "-i", self.image]

    def remove(self, name):
        require_execution_worker()
        if not isinstance(name, str) or not re.fullmatch(r"foxforge-fixture-[0-9a-f]{32}", name):
            raise p.ProtocolError("Refusing to remove an unowned container identity")
        # Only a random name this supervisor just allocated, never a model value.
        subprocess.run([self.exe, "rm", "-f", name], capture_output=True, timeout=15, env=environment())

    def run(self, assignment, *, cancelled=lambda: False):
        require_execution_worker()
        p.validate_assignment(assignment)
        name = "foxforge-fixture-" + uuid4().hex
        cap = assignment["budgets"]["output_bytes"]
        output, error = bytearray(), bytearray()
        output_lock = threading.Lock()
        overflow = threading.Event()
        process = None
        def drain(pipe, saved):
            while True:
                data = pipe.read(4096)
                if not data:
                    break
                with output_lock:
                    available = max(0, cap - len(output) - len(error))
                    if len(data) > available:
                        overflow.set()
                    saved.extend(data[:available])
        def fail(reason, status="failed"):
            return {"status": status, "reason": reason, "evidence": [], "artifacts": {}}
        try:
            process = subprocess.Popen(self.command(assignment, name), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment())
            readers = [threading.Thread(target=drain, args=(process.stdout, output), daemon=True),
                       threading.Thread(target=drain, args=(process.stderr, error), daemon=True)]
            for reader in readers:
                reader.start()
            # Send a bounded resolved scope, never controller/worker signing keys.
            def send():
                try:
                    process.stdin.write(p.canonical(assignment))
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
            writer = threading.Thread(target=send, daemon=True)
            writer.start()
            while process.poll() is None:
                if cancelled() or overflow.is_set() or self.clock() >= assignment["expires_at"]:
                    self.remove(name)  # killing only the Docker CLI would leave code running
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
                    for reader in readers:
                        reader.join(timeout=2)
                    return fail("operator_cancelled", "cancelled") if cancelled() else fail("output_limited") if overflow.is_set() else fail("lease_expired", "interrupted")
                time.sleep(0.05)
            for reader in readers:
                reader.join(timeout=2)
            if overflow.is_set():
                return fail("output_limited")
            if process.returncode:
                return fail("sandbox_failed")
            value = p.decode(bytes(output))
            p.fields(value, "status reason evidence artifacts")
            if not isinstance(value["artifacts"], dict) or len(value["artifacts"]) > 4:
                raise p.ProtocolError("Malformed sandbox artifacts")
            value["artifacts"] = {name: base64.b64decode(body, validate=True) for name, body in value["artifacts"].items()}
            if sum(len(body) for body in value["artifacts"].values()) > assignment["budgets"]["artifact_bytes"]:
                raise p.ProtocolError("Oversized artifacts")
            return value
        except (OSError, subprocess.SubprocessError, p.ProtocolError, ValueError, TypeError):
            return fail("sandbox_unavailable")
        finally:
            try:
                self.remove(name)
            finally:
                if process:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=10)
                    if "writer" in locals():
                        writer.join(timeout=2)
                    for pipe in (process.stdin, process.stdout, process.stderr):
                        if pipe:
                            pipe.close()


def cleanup_expired():
    """Explicit worker-operator cleanup; only labelled, expired prototype containers."""
    require_execution_worker()
    exe = shutil.which("docker")
    if not exe:
        raise p.ProtocolError("Docker is unavailable")
    result = subprocess.run([exe, "ps", "-aq", "--filter=label=foxforge.prototype=true"], capture_output=True, text=True, check=True, timeout=15, env=environment())
    removed = []
    for name in result.stdout.splitlines():
        if not re.fullmatch(r"[0-9a-f]{12,64}", name):
            raise p.ProtocolError("Invalid Docker identity")
        row = subprocess.run([exe, "inspect", name], capture_output=True, check=True, timeout=15, env=environment())
        labels = p.decode(row.stdout)[0]["Config"]["Labels"]
        expires = labels.get("foxforge.expires_at", "")
        if labels.get("foxforge.prototype") == "true" and expires.isdecimal() and int(expires) <= time.time():
            subprocess.run([exe, "rm", "-f", name], capture_output=True, check=True, timeout=15, env=environment())
            removed.append(name)
    return removed
